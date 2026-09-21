"""仅管理面：Flask API / Web（不拉流）。

启动：``python -m visionai.api``
"""

from __future__ import annotations

import logging
import os

from visionai.config.settings import (
    REDIS_PASSWORD,
    S3_ACCESS_KEY_ID,
    S3_SECRET_ACCESS_KEY,
    SAVE_DIR,
    SECRET,
    SESSION_SECRET,
    ZLM_SECRET,
)
from visionai.utils.insecure_defaults import require_login_secret, warn_insecure_secrets
from visionai.utils.logger import setup_logger
from visionai.web.app import app


def main() -> None:
    logger = setup_logger()
    logger.info("JXVisionAI API 启动 (port 5000)")
    if not SECRET:
        logger.error("未设置 VISIONAI_SECRET / [basic] visionai_secret，拒绝以空口令对外服务")
        require_login_secret(SECRET)
    warn_insecure_secrets(
        [
            ("VISIONAI_SECRET", SECRET),
            ("VISIONAI_SESSION_SECRET", SESSION_SECRET),
            ("REDIS_PASSWORD", REDIS_PASSWORD),
            ("ZLM_SECRET", ZLM_SECRET),
            ("S3_ACCESS_KEY_ID", S3_ACCESS_KEY_ID),
            ("S3_SECRET_ACCESS_KEY", S3_SECRET_ACCESS_KEY),
        ],
        logger,
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
