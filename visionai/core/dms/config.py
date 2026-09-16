"""按流疲劳驾驶 / DMS 配置。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

FATIGUE_KEY = "fatigue_driving"

PRESETS = {
    "unlimited": {
        "pull_mode": "always",
        "pull_interval_sec": 0.0,
        "window_mode": "duration",
        "window_duration_sec": 30.0,
        "window_frames": 240,
        "sample_fps": 8.0,
    },
    "sim": {
        "pull_mode": "burst",
        "pull_interval_sec": 45.0,
        "window_mode": "duration",
        "window_duration_sec": 6.0,
        "window_frames": 30,
        "sample_fps": 5.0,
    },
}


def default_fatigue_config() -> Dict[str, Any]:
    return {
        "preset": "unlimited",
        "pull_mode": "always",
        "pull_interval_sec": 0.0,
        "window_mode": "duration",
        "window_duration_sec": 30.0,
        "window_frames": 240,
        "sample_fps": 8.0,
        "ear_close": 0.18,
        "perclos_pct": 0.40,
        "yawn_count": 2,
        "nod_deg": 22.0,
        "observe_sec": 4.0,
        "min_face_px": 80,
        "alert_hold_sec": 2.0,
        "cooldown_sec": 45.0,
        "night_mode": False,
        "rotate": None,
        "bitrate_kbps": 800,
    }


def _as_float(v: Any, default: float, lo: float, hi: float) -> float:
    if v is None or str(v).strip() == "":
        return default
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int, lo: int, hi: int) -> int:
    if v is None or str(v).strip() == "":
        return default
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def normalize_fatigue_config(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base = default_fatigue_config()
    if not raw or not isinstance(raw, dict):
        return base
    preset = str(raw.get("preset") or "").strip().lower()
    if preset in PRESETS:
        base["preset"] = preset
        base.update(PRESETS[preset])
    elif preset:
        base["preset"] = "custom"

    mode = str(raw.get("pull_mode") or base["pull_mode"]).strip().lower()
    base["pull_mode"] = "burst" if mode == "burst" else "always"

    wm = str(raw.get("window_mode") or base["window_mode"]).strip().lower()
    base["window_mode"] = "frames" if wm == "frames" else "duration"

    if "pull_interval_sec" in raw:
        base["pull_interval_sec"] = _as_float(raw.get("pull_interval_sec"), 0.0, 0.0, 3600.0)
    if "window_duration_sec" in raw:
        base["window_duration_sec"] = _as_float(raw.get("window_duration_sec"), 30.0, 1.0, 120.0)
    if "window_frames" in raw:
        base["window_frames"] = _as_int(raw.get("window_frames"), 240, 8, 2000)
    if "sample_fps" in raw:
        base["sample_fps"] = _as_float(raw.get("sample_fps"), 8.0, 1.0, 15.0)
    elif "sample_interval_ms" in raw:
        ms = _as_float(raw.get("sample_interval_ms"), 160.0, 66.0, 1000.0)
        base["sample_fps"] = round(1000.0 / ms, 2)

    base["ear_close"] = _as_float(raw.get("ear_close"), base["ear_close"], 0.05, 0.45)
    base["perclos_pct"] = _as_float(raw.get("perclos_pct"), base["perclos_pct"], 0.15, 0.90)
    base["yawn_count"] = _as_int(raw.get("yawn_count"), base["yawn_count"], 1, 20)
    base["nod_deg"] = _as_float(raw.get("nod_deg"), base["nod_deg"], 8.0, 60.0)
    base["observe_sec"] = _as_float(raw.get("observe_sec"), base["observe_sec"], 0.5, 60.0)
    base["min_face_px"] = _as_int(raw.get("min_face_px"), base["min_face_px"], 40, 400)
    base["alert_hold_sec"] = _as_float(raw.get("alert_hold_sec"), base["alert_hold_sec"], 0.5, 20.0)
    base["cooldown_sec"] = _as_float(raw.get("cooldown_sec"), base["cooldown_sec"], 5.0, 600.0)
    base["night_mode"] = bool(raw.get("night_mode"))
    base["bitrate_kbps"] = _as_int(raw.get("bitrate_kbps"), base["bitrate_kbps"], 100, 8000)

    rot = raw.get("rotate")
    if rot is not None and str(rot).strip() != "":
        try:
            r = int(float(rot)) % 360
            base["rotate"] = r if r in (0, 90, 180, 270) else None
        except (TypeError, ValueError):
            pass
    return base


def resolve_window(cfg: Dict[str, Any]) -> Tuple[float, int, float]:
    """返回 (duration_sec, frame_count, sample_interval_sec)。"""
    fps = max(1.0, float(cfg.get("sample_fps") or 8.0))
    interval = 1.0 / fps
    if str(cfg.get("window_mode") or "duration") == "frames":
        n = max(8, int(cfg.get("window_frames") or 40))
        return n / fps, n, interval
    dur = max(1.0, float(cfg.get("window_duration_sec") or 8.0))
    return dur, max(8, int(round(dur * fps))), interval


def traffic_hint(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """粗算突发窗占空比与流量（kb/周期），供 UI。"""
    dur, frames, _ = resolve_window(cfg)
    pull = float(cfg.get("pull_interval_sec") or 0.0)
    mode = str(cfg.get("pull_mode") or "always")
    if mode == "burst":
        cycle = dur + max(0.0, pull)
        duty = dur / cycle if cycle > 0 else 1.0
    else:
        cycle = dur + max(0.0, pull)
        duty = 1.0 if pull <= 0 else dur / cycle
    kbps = float(cfg.get("bitrate_kbps") or 800)
    # 突发：仅窗内传流；常连：全程传流
    if mode == "burst":
        kb_per_cycle = kbps * dur
        kb_per_hour = kb_per_cycle * (3600.0 / max(cycle, 1.0))
    else:
        kb_per_hour = kbps * 3600.0
        kb_per_cycle = kbps * max(cycle, dur)
    return {
        "window_sec": round(dur, 2),
        "window_frames": frames,
        "duty": round(duty, 3),
        "mb_per_hour": round(kb_per_hour / 8.0 / 1024.0, 1),
        "pull_mode": mode,
    }
