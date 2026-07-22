"""管理端 HLS 预览：FFmpeg 从 RTSP 拉流并写出低延迟 HLS，供浏览器 hls.js 播放。

有音轨时编码 AAC；无音轨或带声启动失败时回退纯视频（-an）。
每路预览会话独立子进程；关闭窗口或超时 idle 后停止以释放 CPU。
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

from visionai.config.settings import (
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


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def rtsp_has_audio(rtsp_url: str, timeout_sec: float = 8.0) -> bool:
    """用 ffprobe 判断 RTSP 是否含音轨；无 ffprobe 时返回 False（走 -an）。"""
    if not rtsp_url or not ffprobe_available():
        return False
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        rtsp_url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(3.0, float(timeout_sec)),
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return "audio" in out.lower()
    except Exception as e:  # noqa: BLE001
        logger.debug("ffprobe 音频探测失败: %s", e)
        return False


def _video_encode_args() -> List[str]:
    return [
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
    ]


def _audio_encode_args() -> List[str]:
    """监控摄像机多为 G.711 8kHz 单声道；强制 44.1k 立体声易出现隆隆声/失真。

    用 aresample 高质量重采样到 16k 单声道 AAC（语音足够清晰）。
    """
    return [
        "-af",
        # async 校正时钟漂移；highpass 去掉麦底噪/隆隆低频
        "aresample=16000:async=1:first_pts=0,highpass=f=80,lowpass=f=7000,aformat=sample_fmts=fltp:channel_layouts=mono",
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-b:a",
        "64k",
        "-ar",
        "16000",
        "-ac",
        "1",
    ]


def _build_ffmpeg_cmd(
    rtsp_url: str,
    playlist_path: Path,
    out_dir: Path,
    *,
    with_audio: bool,
) -> List[str]:
    seg_time = f"{PREVIEW_HLS_SEGMENT_SEC:.2f}"
    list_size = str(PREVIEW_HLS_LIST_SIZE)
    cmd: List[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "+genpts+discardcorrupt",
        "-flags",
        "low_delay",
        "-strict",
        "experimental",
        "-rtsp_transport",
        "tcp",
        "-i",
        rtsp_url,
    ]
    if with_audio:
        cmd.extend(["-map", "0:v:0", "-map", "0:a:0?"])
        cmd.extend(_video_encode_args())
        cmd.extend(_audio_encode_args())
    else:
        cmd.extend(["-map", "0:v:0", "-an"])
        cmd.extend(_video_encode_args())
    cmd.extend(
        [
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
    )
    return cmd


def _spawn_and_wait_playlist(
    cmd: List[str],
    out_dir: Path,
    playlist_path: Path,
    session_id: str,
    stream_id: str,
    *,
    has_audio: bool,
) -> Tuple[Optional[str], Optional[str], bool]:
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=str(out_dir),
        )
    except OSError as e:
        logger.error("启动 ffmpeg 失败: %s", e)
        return None, None, False

    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = ""
            try:
                if proc.stderr:
                    err = (proc.stderr.read() or b"")[-800:].decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
            logger.error(
                "ffmpeg 预览进程过早退出 (code=%s) audio=%s %s",
                proc.returncode,
                has_audio,
                err.strip()[:300],
            )
            return None, None, False
        if playlist_path.is_file() and playlist_path.stat().st_size > 0:
            rel = f"/api/preview-hls/data/{session_id}/index.m3u8"
            with _lock:
                _sessions[session_id] = {
                    "stream_id": stream_id,
                    "dir": out_dir,
                    "proc": proc,
                    "last": time.monotonic(),
                    "audio": bool(has_audio),
                }
            # 丢弃 stderr 管道避免阻塞
            try:
                if proc.stderr:
                    threading.Thread(
                        target=proc.stderr.read,
                        name=f"hls-ffmpeg-err-{session_id[:8]}",
                        daemon=True,
                    ).start()
            except Exception:  # noqa: BLE001
                pass
            return session_id, rel, bool(has_audio)
        time.sleep(0.08)

    logger.error("ffmpeg 在时限内未生成 index.m3u8 (audio=%s)", has_audio)
    try:
        proc.terminate()
        proc.wait(timeout=3.0)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    return None, None, False


def start_session(
    stream_id: str, rtsp_url: str
) -> Tuple[Optional[str], Optional[str], bool]:
    """启动 FFmpeg；返回 (session_id, playlist_path, has_audio)。

    playlist URL 形如 /api/preview-hls/data/<session_id>/index.m3u8
    """
    if not stream_id or not rtsp_url.strip():
        return None, None, False
    if not ffmpeg_available():
        logger.warning("未找到 ffmpeg，无法启动 HLS 预览")
        return None, None, False

    _ensure_sweeper()

    want_audio = rtsp_has_audio(rtsp_url)
    session_id = uuid.uuid4().hex
    root = Path(PREVIEW_HLS_ROOT).resolve()
    out_dir = root / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist_path = out_dir / "index.m3u8"

    if want_audio:
        cmd = _build_ffmpeg_cmd(rtsp_url, playlist_path, out_dir, with_audio=True)
        sid, rel, audio = _spawn_and_wait_playlist(
            cmd, out_dir, playlist_path, session_id, stream_id, has_audio=True
        )
        if sid:
            logger.info("HLS 预览已启动（含音频）stream=%s session=%s", stream_id, sid)
            return sid, rel, True
        # 带声失败：清空目录后回退静音
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        logger.warning("含音频 HLS 启动失败，回退纯视频 stream=%s", stream_id)

    session_id = uuid.uuid4().hex
    out_dir = root / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist_path = out_dir / "index.m3u8"
    cmd = _build_ffmpeg_cmd(rtsp_url, playlist_path, out_dir, with_audio=False)
    sid, rel, _ = _spawn_and_wait_playlist(
        cmd, out_dir, playlist_path, session_id, stream_id, has_audio=False
    )
    if sid:
        logger.info("HLS 预览已启动（无音频）stream=%s session=%s", stream_id, sid)
        return sid, rel, False

    shutil.rmtree(out_dir, ignore_errors=True)
    return None, None, False


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
