"""视频流处理模块"""

import cv2
import logging
import time
from visionai.config.settings import DETECTION_INTERVAL
from visionai.utils.rtsp_url import normalize_rtsp_url

logger = logging.getLogger(__name__)

class StreamHandler:
    """单个视频流处理器"""
    
    def __init__(self, stream_info):
        """初始化视频流处理器"""
        self.stream_info = stream_info
        self.name = stream_info["name"]
        self.url = normalize_rtsp_url(stream_info.get("url") or "")
        self.cap = None
        self.frame_count = 0
        self.fps = 30  # 默认帧率
    
    def connect(self):
        """连接视频流"""
        try:
            logger.info(f"[{self.name}] 正在连接视频流: {self.url}")
            self.cap = cv2.VideoCapture(self.url)
            
            if not self.cap.isOpened():
                logger.error(f"[{self.name}] 无法打开视频流")
                return False
            
            # 获取视频属性
            self.fps = int(self.cap.get(cv2.CAP_PROP_FPS)) or 30
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            logger.info(f"[{self.name}] 视频流连接成功，分辨率: {width}x{height}, 帧率: {self.fps}")
            return True
            
        except Exception as e:
            logger.error(f"[{self.name}] 连接视频流失败: {e}")
            return False
    
    def disconnect(self):
        """断开视频流"""
        if self.cap:
            self.cap.release()
            self.cap = None
            logger.info(f"[{self.name}] 视频流已关闭")
    
    def read_frame(self):
        """读取一帧"""
        if not self.cap or not self.cap.isOpened():
            logger.warning(f"[{self.name}] 视频流未连接")
            return None
        
        try:
            ret, frame = self.cap.read()
            if not ret:
                logger.warning(f"[{self.name}] 无法读取帧")
                return None
            
            self.frame_count += 1
            return frame
            
        except Exception as e:
            logger.error(f"[{self.name}] 读取帧失败: {e}")
            return None
    
    def should_detect(self):
        """判断是否需要检测"""
        return self.frame_count % (self.fps * DETECTION_INTERVAL) == 0
    
    def reconnect(self):
        """重新连接视频流"""
        logger.info(f"[{self.name}] 尝试重新连接视频流...")
        self.disconnect()
        time.sleep(1)
        return self.connect()