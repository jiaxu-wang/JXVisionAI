"""仅管理面：Flask API / Web（不拉流）。

启动：``python -m visionai.api``
"""

from __future__ import annotations

import logging
import os

from visionai.config.settings import SAVE_DIR, SECRET
from visionai.utils.logger import setup_logger
from visionai.web.app import app


def main() -> None:
    logger = setup_logger()
    logger.info("JXVisionAI API 启动 (port 5000)")
    if SECRET == "123456-bb6b-4889-a715-d9eb2d1925cc":
        logger.warning(
            "安全警告: 正在使用默认 visionai_secret，生产环境请立即修改！"
        )
    os.makedirs(SAVE_DIR, exist_ok=True)
    # 可选 waitress
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=5000, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
