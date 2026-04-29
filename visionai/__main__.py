"""VisionAI主程序入口"""

import logging
import threading
import time

import cv2

from visionai.core.detector import Detector
from visionai.core.preview_cache import set_preview_jpeg
from visionai.core.stream_handler import StreamHandler
from visionai.utils.logger import setup_logger
from visionai.config.settings import SAVE_DIR
from visionai.config.detection_catalog import normalize_detections
from visionai.web.app import app
from visionai.core import stream_sync
import os

# 导入流状态管理
from visionai.core.state_manager import stream_status, stream_status_lock

# 导入Redis管理器
from visionai.core.redis_manager import redis_manager

# 线程追踪机制，防止重复启动线程
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
        stream_handler = StreamHandler(stream_info)
        if not stream_handler.connect():
            logger.error(f"[{stream_name}] 无法连接视频流，线程退出")
            with stream_status_lock:
                stream_status[stream_name] = "离线"
            return

        with stream_status_lock:
            stream_status[stream_name] = "在线"

        logger.info(f"[{stream_name}] 视频流已连接，正在加载检测模型…")
        detector = Detector(
            stream_name,
            stream_save_dir,
            stream_info.get("detections"),
            stream_id=stream_info.get("id"),
        )
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
                        with stream_status_lock:
                            stream_status[stream_name] = "离线"
                        break
                    # 重新连接成功，重置计数器并更新状态
                    read_failure_count = 0
                    with stream_status_lock:
                        stream_status[stream_name] = "在线"
                    logger.info(f"[{stream_name}] 重新连接成功")
                continue
            
            # 读取成功，重置失败计数器
            if read_failure_count > 0:
                read_failure_count = 0
            
            # 判断是否需要检测
            if stream_handler.should_detect():
                latest = get_stream_config_by_name(stream_name)
                if not latest or not latest.get("enabled", True):
                    logger.info(f"[{stream_name}] 流已在配置中禁用或已删除，停止处理")
                    break
                if latest.get("id"):
                    detector.stream_id = latest["id"]
                detector.detections = normalize_detections(latest.get("detections"))
                # 执行检测
                results = detector.detect(frame)
                # 处理结果
                processed_frame, detections = detector.process_results(frame, results)
                sid = (latest.get("id") or "").strip()
                if sid:
                    enc_ok, buf = cv2.imencode(
                        ".jpg",
                        processed_frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 72],
                    )
                    if enc_ok:
                        set_preview_jpeg(sid, buf.tobytes())
                # 保存截图
                detector.save_snapshot(processed_frame, detections)
                
    except KeyboardInterrupt:
        logger.info(f"[{stream_name}] 视频处理已停止")
    except Exception as e:
        logger.error(f"[{stream_name}] 视频处理异常: {e}", exc_info=True)
        # 异常时更新状态为离线
        with stream_status_lock:
            stream_status[stream_name] = "离线"
    finally:
        if stream_handler is not None:
            stream_handler.disconnect()
        # 退出时更新状态为离线
        with stream_status_lock:
            stream_status[stream_name] = "离线"
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
                        # 连接成功，更新为在线
                        with stream_status_lock:
                            stream_status[stream_name] = "在线"
                        stream_handler.disconnect()
                    else:
                        # 连接失败，更新为离线
                        with stream_status_lock:
                            stream_status[stream_name] = "离线"
                except Exception as e:
                    # 连接异常，更新为离线
                    with stream_status_lock:
                        stream_status[stream_name] = "离线"
            
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
                    
                    # 立即更新流状态为在线
                    with stream_status_lock:
                        stream_status[stream_name] = "在线"
                    
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
    logger.info("VisionAI 启动")
    
    # 创建保存根目录
    os.makedirs(SAVE_DIR, exist_ok=True)
    
    # 从Redis获取流配置
    streams = get_streams()
    if not streams:
        logger.warning("未从Redis获取到流配置，请检查Redis连接")
    
    # 初始化所有流的状态（包括禁用的流）
    with stream_status_lock:
        for stream_info in streams:
            if stream_info["name"] not in stream_status:
                stream_status[stream_info["name"]] = "离线"
    
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