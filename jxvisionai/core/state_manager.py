"""状态管理模块"""

import threading

# 导入Redis管理器
try:
    from jxvisionai.core.redis_manager import redis_manager
except:
    redis_manager = None

# 全局流状态管理
stream_status = {}
stream_status_lock = threading.Lock()

def init_stream_status():
    """从Redis初始化流状态"""
    if redis_manager:
        streams = redis_manager.get_streams()
        for stream_info in streams:
            stream_status[stream_info["name"]] = "离线"

# 初始化流状态
init_stream_status()
