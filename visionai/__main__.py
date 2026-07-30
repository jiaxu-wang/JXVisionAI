"""
JXVisionAI 进程入口。

单进程内同时拉起：
  1. 每路 RTSP 的检测线程（读帧 → YOLO/行为插件 → 截图 → Redis/告警）
  2. Flask 管理端（默认 0.0.0.0:5000）
  3. 离线流探测与禁用流状态维护线程

流配置只读 Redis；改 config.ini / 模型文件后需重启本进程。
"""

import logging
import threading
import time

from visionai.core.detector import Detector
from visionai.core.stream_handler import StreamHandler
from visionai.utils.logger import setup_logger
from visionai.utils.alert_email import (
    normalize_stream_alert_emails,
    normalize_stream_alert_email_enabled,
)
from visionai.utils.alert_webhook import (
    normalize_stream_alert_webhook_enabled,
    normalize_stream_webhook_urls,
)
from visionai.config.settings import SAVE_DIR
from visionai.config.detection_catalog import normalize_detections
from visionai.core.face_recognition_config import normalize_face_recognition_config
from visionai.web.app import app
from visionai.core import stream_sync
import os

from visionai.core.state_manager import set_stream_status, stream_status, stream_status_lock
from visionai.core.redis_manager import redis_manager

# 按流名跟踪处理线程，避免同一路被重复拉起
active_threads = {}
threads_lock = threading.Lock()

def get_streams():
    """从Redis获取流配置，如果Redis不可用则返回空列表"""
    if redis_manager:
        return redis_manager.get_streams()
    return []


def get_stream_config_by_name(stream_name):
    """按名称查找当前 Redis 中的流配置（用于运行中刷新检测开关等）。"""
    for s in get_streams():
        if s.get("name") == stream_name:
            return s
    return None

def run_video_processing(stream_info):
    """运行单个视频流处理"""
    logger = logging.getLogger(__name__)
    stream_name = stream_info["name"]
    
    # 注册线程
    with threads_lock:
        active_threads[stream_name] = True
    
    stream_handler = None
    try:
        # 创建流对应的保存目录
        stream_save_dir = os.path.join(SAVE_DIR, stream_name)
        os.makedirs(stream_save_dir, exist_ok=True)

        # 先连 RTSP 再加载 YOLO，否则大模型会阻塞数十秒，界面长期显示「离线」
        pull_url = None
        zlm_fallback = True
        try:
            from visionai.config.settings import (
                ZLM_ENABLED,
                ZLM_FALLBACK_DIRECT_RTSP,
                ZLM_PREFER_LOCAL_PULL,
            )
            from visionai.core.zlm_client import get_zlm_client

            zlm_fallback = bool(ZLM_FALLBACK_DIRECT_RTSP)
            if ZLM_ENABLED and ZLM_PREFER_LOCAL_PULL:
                zlm = get_zlm_client()
                sid = (stream_info.get("id") or stream_name).strip()
                src = stream_info.get("url") or ""
                if zlm and zlm.alive():
                    proxied = zlm.ensure_proxy(sid, src)
                    if proxied.get("success") and proxied.get("local_rtsp"):
                        pull_url = proxied["local_rtsp"]
                        logger.info(
                            f"[{stream_name}] ZLM 代理就绪: {pull_url} online={proxied.get('online')}"
                        )
                    elif not zlm_fallback:
                        logger.error(f"[{stream_name}] ZLM 代理失败且禁止直连: {proxied}")
                        set_stream_status(stream_name, "离线")
                        return
                elif not zlm_fallback:
                    logger.error(f"[{stream_name}] ZLM 不可用且禁止直连")
                    set_stream_status(stream_name, "离线")
                    return
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[{stream_name}] ZLM 接入异常，将直连: {e}")

        stream_handler = StreamHandler(stream_info, pull_url=pull_url)
        if not stream_handler.connect():
            if pull_url and zlm_fallback:
                logger.warning(f"[{stream_name}] ZLM 本地拉流失败，回退直连源站")
                stream_handler = StreamHandler(stream_info, pull_url=None)
                if not stream_handler.connect():
                    logger.error(f"[{stream_name}] 无法连接视频流，线程退出")
                    set_stream_status(stream_name, "离线")
                    return
            else:
                logger.error(f"[{stream_name}] 无法连接视频流，线程退出")
                set_stream_status(stream_name, "离线")
                return

        set_stream_status(stream_name, "在线")
        last_status_hb = time.time()

        logger.info(f"[{stream_name}] 视频流已连接，正在加载检测模型…")
        detector = Detector(
            stream_name,
            stream_save_dir,
            stream_info.get("detections"),
            stream_id=stream_info.get("id"),
        )
        set_stream_status(stream_name, "在线")
        last_status_hb = time.time()
        logger.info(f"[{stream_name}] 开始处理视频流（检测）…")
        
        # 帧读取失败计数器
        read_failure_count = 0
        max_read_failures = 5  # 最大连续失败次数
        
        # 主循环
        while True:
            # 读取帧
            frame = stream_handler.read_frame()
            if frame is None:
                read_failure_count += 1
                logger.warning(f"[{stream_name}] 读取帧失败 ({read_failure_count}/{max_read_failures})")
                
                # 只有连续失败次数超过阈值才尝试重连
                if read_failure_count >= max_read_failures:
                    logger.warning(f"[{stream_name}] 连续读取帧失败次数过多，尝试重新连接")
                    # 尝试重新连接
                    if not stream_handler.reconnect():
                        logger.error(f"[{stream_name}] 重新连接失败，线程退出")
                        set_stream_status(stream_name, "离线")
                        break
                    # 重新连接成功，重置计数器并更新状态
                    read_failure_count = 0
                    set_stream_status(stream_name, "在线")
                    last_status_hb = time.time()
                    logger.info(f"[{stream_name}] 重新连接成功")
                continue
            
            # 读取成功，重置失败计数器
            if read_failure_count > 0:
                read_failure_count = 0

            # 定期刷新 Redis 在线心跳，供独立 API 进程展示状态
            now_hb = time.time()
            if now_hb - last_status_hb >= 20.0:
                set_stream_status(stream_name, "在线")
                last_status_hb = now_hb
            
            # 判断是否需要检测
            if stream_handler.should_detect():
                latest = get_stream_config_by_name(stream_name)
                if not latest or not latest.get("enabled", True):
                    logger.info(f"[{stream_name}] 流已在配置中禁用或已删除，停止处理")
                    break
                if latest.get("id"):
                    detector.stream_id = latest["id"]
                detector.detections = normalize_detections(latest.get("detections"))
                detector.alert_emails = normalize_stream_alert_emails(
                    latest.get("alert_emails")
                )
                detector.alert_email_enabled = normalize_stream_alert_email_enabled(
                    latest.get("alert_email_enabled")
                )
                detector.alert_webhook_urls = normalize_stream_webhook_urls(
                    latest.get("alert_webhook_urls")
                )
                detector.alert_webhook_enabled = normalize_stream_alert_webhook_enabled(
                    latest.get("alert_webhook_enabled")
                )
                detector.face_recognition_config = normalize_face_recognition_config(
                    latest.get("face_recognition_config")
                )
                # 执行检测
                t0 = time.time()
                results = detector.detect(frame)
                # 处理结果
                processed_frame, detections = detector.process_results(frame, results)
                sid = (latest.get("id") or "").strip()
                try:
                    from visionai.core.runtime_metrics import note_detect, note_frame

                    if sid:
                        note_frame(sid)
                        note_detect(sid, (time.time() - t0) * 1000.0)
                except Exception:  # noqa: BLE001
                    pass
                # 保存截图
                detector.save_snapshot(processed_frame, detections)
                
    except KeyboardInterrupt:
        logger.info(f"[{stream_name}] 视频处理已停止")
    except Exception as e:
        logger.error(f"[{stream_name}] 视频处理异常: {e}", exc_info=True)
        set_stream_status(stream_name, "离线")
    finally:
        if stream_handler is not None:
            stream_handler.disconnect()
        set_stream_status(stream_name, "离线")
        # 注销线程
        with threads_lock:
            if stream_name in active_threads:
                del active_threads[stream_name]
        logger.info(f"[{stream_name}] 视频处理已退出")

def run_web_server():
    """运行Web服务器"""
    logger = logging.getLogger(__name__)
    logger.info("启动Web管理界面，访问地址: http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

def check_disabled_stream_status():
    """检查禁用流的在线状态"""
    logger = logging.getLogger(__name__)
    while True:
        try:
            streams = get_streams()
            # 只检查禁用的流
            disabled_streams = [stream for stream in streams if not stream.get('enabled', True)]
            
            for stream_info in disabled_streams:
                stream_name = stream_info["name"]
                
                try:
                    # 尝试连接流来检查在线状态
                    stream_handler = StreamHandler(stream_info)
                    if stream_handler.connect():
                        set_stream_status(stream_name, "在线")
                        stream_handler.disconnect()
                    else:
                        set_stream_status(stream_name, "离线")
                except Exception as e:
                    set_stream_status(stream_name, "离线")
            
            # 每60秒检查一次
            time.sleep(60)
        except Exception as e:
            logger.error(f"[禁用流检测] 检查禁用流状态时发生错误: {e}")
            time.sleep(60)

def check_offline_streams():
    """为「已启用且尚无处理线程」的流启动拉流（含 Redis 中新加的流、断线重连）。"""
    logger = logging.getLogger(__name__)
    # 首次立即跑一轮，之后每 60s 或由 Web 保存配置唤醒
    wait_sec = 0.0
    while True:
        try:
            kicked = stream_sync.wait_until_next_check(wait_sec)
            if kicked:
                stream_sync.clear_kick()
            wait_sec = 60.0

            streams = get_streams()
            # 只检查启用的流
            enabled_streams = [stream for stream in streams if stream.get('enabled', True)]

            for stream_info in enabled_streams:
                stream_name = stream_info["name"]

                # 检查是否已经有线程在处理这个流
                with threads_lock:
                    if stream_name in active_threads:
                        continue

                logger.info(f"[离线检测] 尝试为流启动处理线程: {stream_name}")
                
                # 尝试连接流
                stream_handler = StreamHandler(stream_info)
                if stream_handler.connect():
                    logger.info(f"[离线检测] 流 {stream_name} 已重新上线")
                    stream_handler.disconnect()
                    
                    # 再次检查，防止竞态条件
                    with threads_lock:
                        if stream_name in active_threads:
                            logger.info(f"[离线检测] 流 {stream_name} 已有线程在运行，取消启动新线程")
                            continue
                    
                    set_stream_status(stream_name, "在线")

                    # 启动处理线程
                    video_thread = threading.Thread(
                        target=run_video_processing, 
                        args=(stream_info,), 
                        daemon=True
                    )
                    video_thread.start()
                    logger.info(f"[离线检测] 已启动流 {stream_name} 的处理线程")

        except Exception as e:
            logger.error(f"[离线检测] 检查离线流时发生错误: {e}")
            time.sleep(60)

def main():
    """主函数"""
    # 设置日志
    logger = setup_logger()
    logger.info("JXVisionAI 启动")
    try:
        from visionai.config.settings import describe_inference_backend

        logger.info("推理后端: %s", describe_inference_backend())
    except Exception as ex:  # noqa: BLE001
        logger.warning("无法打印推理后端信息: %s", ex)

    # 创建保存根目录
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    # 从Redis获取流配置
    streams = get_streams()
    if not streams:
        logger.warning("未从Redis获取到流配置，请检查Redis连接")
    
    # 初始化所有流的本地状态（包括禁用的流）；不覆盖 Redis 已有心跳
    for stream_info in streams:
        name = stream_info["name"]
        with stream_status_lock:
            if name not in stream_status:
                stream_status[name] = "离线"
    
    # 为每个启用的视频流启动一个处理线程
    for stream_info in streams:
        # 检查流是否启用（默认为true）
        if stream_info.get('enabled', True):
            video_thread = threading.Thread(
                target=run_video_processing, 
                args=(stream_info,), 
                daemon=True
            )
            video_thread.start()
            logger.info(f"已启动视频流处理线程: {stream_info['name']}")
        else:
            logger.info(f"视频流已禁用，跳过启动处理线程: {stream_info['name']}")
    
    # 启动离线流检测线程（用于启用的流）
    check_thread = threading.Thread(
        target=check_offline_streams,
        daemon=True
    )
    check_thread.start()
    logger.info("已启动离线流检测线程")
    
    # 启动禁用流状态检测线程
    disabled_check_thread = threading.Thread(
        target=check_disabled_stream_status,
        daemon=True
    )
    disabled_check_thread.start()
    logger.info("已启动禁用流状态检测线程")
    
    # 启动Web服务器
    run_web_server()

if __name__ == "__main__":
    main()