"""管理端 HLS 预览：FFmpeg 从 RTSP 拉流并写出低延迟 HLS，供浏览器 hls.js 播放。

每路预览会话独立子进程；关闭窗口或超时 idle 后停止以释放 CPU。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from jxvisionai.config.settings import (
    PREVIEW_HLS_IDLE_SEC,
    PREVIEW_HLS_LIST_SIZE,
    PREVIEW_HLS_ROOT,
    PREVIEW_HLS_SEGMENT_SEC,
)

logger = logging.getLogger(__name__)

_SAFE_TS = re.compile(r"^seg_\d{3}\.ts$")

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}
_sweeper_started = False


def _ensure_sweeper() -> None:
    global _sweeper_started
    if _sweeper_started:
        return
    with _lock:
        if _sweeper_started:
            return
        _sweeper_started = True

    def _loop() -> None:
        while True:
            time.sleep(30.0)
            try:
                sweep_idle_sessions()
            except Exception:  # noqa: BLE001
                logger.debug("HLS 预览 idle 扫描异常", exc_info=True)

    threading.Thread(target=_loop, name="preview-hls-sweeper", daemon=True).start()


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def start_session(stream_id: str, rtsp_url: str) -> tuple[Optional[str], Optional[str]]:
    """启动 FFmpeg；返回 (session_id, playlist_relative_url_path)。

    playlist URL 形如 /api/preview-hls/data/<session_id>/index.m3u8
    """
    if not stream_id or not rtsp_url.strip():
        return None, None
    if not ffmpeg_available():
        logger.warning("未找到 ffmpeg，无法启动 HLS 预览")
        return None, None

    _ensure_sweeper()

    session_id = uuid.uuid4().hex
    root = Path(PREVIEW_HLS_ROOT).resolve()
    out_dir = root / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist_path = out_dir / "index.m3u8"

    seg_time = f"{PREVIEW_HLS_SEGMENT_SEC:.2f}"
    list_size = str(PREVIEW_HLS_LIST_SIZE)

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-strict",
        "experimental",
        "-rtsp_transport",
        "tcp",
        "-i",
        rtsp_url,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "50",
        "-keyint_min",
        "25",
        "-sc_threshold",
        "0",
        "-f",
        "hls",
        "-hls_time",
        seg_time,
        "-hls_list_size",
        list_size,
        "-hls_flags",
        "delete_segments+append_list+omit_endlist+independent_segments",
        "-hls_segment_filename",
        str(out_dir / "seg_%03d.ts"),
        str(playlist_path),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(out_dir),
        )
    except OSError as e:
        logger.error("启动 ffmpeg 失败: %s", e)
        try:
            out_dir.rmdir()
        except OSError:
            pass
        return None, None

    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            logger.error("ffmpeg 预览进程过早退出 (code=%s)", proc.returncode)
            try:
                shutil.rmtree(out_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
            return None, None
        if playlist_path.is_file() and playlist_path.stat().st_size > 0:
            rel = f"/api/preview-hls/data/{session_id}/index.m3u8"
            with _lock:
                _sessions[session_id] = {
                    "stream_id": stream_id,
                    "dir": out_dir,
                    "proc": proc,
                    "last": time.monotonic(),
                }
            return session_id, rel
        time.sleep(0.08)

    logger.error("ffmpeg 在时限内未生成 index.m3u8")
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(out_dir, ignore_errors=True)
    return None, None


def touch_session(session_id: str) -> None:
    if not session_id:
        return
    with _lock:
        row = _sessions.get(session_id)
        if row:
            row["last"] = time.monotonic()


def stop_session(session_id: str) -> bool:
    if not session_id:
        return False
    with _lock:
        row = _sessions.pop(session_id, None)
    if not row:
        return False
    proc: subprocess.Popen = row["proc"]
    out_dir: Path = row["dir"]
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return True


def sweep_idle_sessions() -> None:
    now = time.monotonic()
    stale: list[str] = []
    with _lock:
        for sid, row in _sessions.items():
            if now - float(row.get("last", 0)) > float(PREVIEW_HLS_IDLE_SEC):
                stale.append(sid)
    for sid in stale:
        stop_session(sid)
        logger.info("HLS 预览会话因空闲已停止: %s", sid)


def session_dir(session_id: str) -> Optional[Path]:
    with _lock:
        row = _sessions.get(session_id)
        if not row:
            return None
        return Path(row["dir"])


def safe_hls_basename(name: str) -> bool:
    if name == "index.m3u8":
        return True
    return bool(_SAFE_TS.match(name))


def list_session_ids() -> set[str]:
    with _lock:
        return set(_sessions.keys())
