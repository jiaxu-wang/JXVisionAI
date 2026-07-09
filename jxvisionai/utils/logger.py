"""进程日志：控制台 + 按日轮转文件（默认 ``logs/visionai.log``）。"""

import logging
import logging.handlers
import os

from jxvisionai.config.settings import LOG_DIR, LOG_LEVEL, LOG_RETENTION_DAYS


def setup_logger():
    """初始化根日志；文件名沿用历史 ``visionai.log``，便于运维脚本兼容。"""
    log_dir = LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    log_format = "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    formatter = logging.Formatter(log_format)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # 每日午夜轮转；backupCount 为「历史」文件份数，含当天共 LOG_RETENTION_DAYS 天 → backupCount = 天数 - 1
    backup_count = max(0, LOG_RETENTION_DAYS - 1)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, "visionai.log"),
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
        delay=False,
        utc=False,
    )
    file_handler.setFormatter(formatter)
    
    # 获取根logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL))
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger