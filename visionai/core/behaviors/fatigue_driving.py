"""疲劳驾驶：PERCLOS / 哈欠 / 低头 + 准入与冷却。"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from visionai.config.detection_catalog import FATIGUE_KEY  # noqa: F401
from visionai.core import face_engine
from visionai.core.behaviors.context import BehaviorContext
from visionai.core.dms.config import normalize_fatigue_config
from visionai.core.dms.gate import evaluate_gate, set_dms_status
from visionai.core.dms.geometry import measure_face

logger = logging.getLogger(__name__)


def _iou(a, b) -> float:
    try:
        ax1, ay1, ax2, ay2 = [float(v) for v in a[:4]]
        bx1, by1, bx2, by2 = [float(v) for v in b[:4]]
    except (TypeError, ValueError, IndexError):
        return 0.0
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _pick_tracked_face(faces: List[Dict[str, Any]], last_box) -> Optional[Dict[str, Any]]:
    if not faces:
        return None
    if last_box:
        best = None
        best_iou = 0.25
        for f in faces:
            v = _iou(last_box, f.get("bbox") or [0, 0, 0, 0])
            if v > best_iou:
                best_iou = v
                best = f
        if best is not None:
            return best
    return max(faces, key=lambda f: int(f.get("face_width") or 0))


class FatigueDrivingBehaviorPlugin:
    key = FATIGUE_KEY

    def evaluate(self, ctx: BehaviorContext, state: Dict[str, Any]) -> Dict[str, Any]:
        cfg = normalize_fatigue_config(ctx.extra.get("fatigue_driving_config"))
        stream_id = str(ctx.extra.get("stream_id") or "")
        out: Dict[str, Any] = {
            "alert": False,
            "boxes": [],
            "count": 0,
            "perclos": 0.0,
            "ear": 0.0,
            "reasons": [],
            "supported": state.get("supported"),
            "reason_zh": state.get("reason_zh") or "评估中（需看清正脸）",
        }

        hist: Deque[Tuple[float, Dict[str, Any]]] = state.setdefault("hist", deque(maxlen=800))
        rotate = cfg.get("rotate")
        if rotate is None:
            rotate = 0

        if not face_engine.is_available():
            state["supported"] = False
            state["reason"] = "no_engine"
            state["reason_zh"] = "无人脸检测模型（models/buffalo_l/）"
            self._flush_gate(stream_id, state, cfg, achieved_fps=0.0)
            out["supported"] = False
            out["reason_zh"] = state["reason_zh"]
            return out

        faces = face_engine.detect_faces_kps(ctx.frame_source, max_faces=2, rotate=int(rotate or 0))
        state["samples"] = int(state.get("samples") or 0) + 1
        state["faces_seen"] = int(state.get("faces_seen") or 0) + (1 if faces else 0)
        if faces:
            fw = max(int(f.get("face_width") or 0) for f in faces)
            state["max_face_px"] = max(int(state.get("max_face_px") or 0), fw)

        if not faces:
            hist.append((ctx.now, {"closed": False, "yawn": False, "nod": False, "valid": False}))
            self._maybe_gate(state, cfg, ctx, stream_id)
            out["supported"] = state.get("supported")
            out["reason_zh"] = state.get("reason_zh") or out["reason_zh"]
            return out

        face = _pick_tracked_face(faces, state.get("last_box"))
        if face is None:
            hist.append((ctx.now, {"closed": False, "yawn": False, "nod": False, "valid": False}))
            self._maybe_gate(state, cfg, ctx, stream_id)
            out["supported"] = state.get("supported")
            out["reason_zh"] = state.get("reason_zh") or out["reason_zh"]
            return out
        state["last_box"] = list(face.get("bbox") or [])
        m = measure_face(ctx.frame_source, face, night_mode=bool(cfg.get("night_mode")))
        ear_thr = float(cfg["ear_close"])
        closed = m["ear"] <= ear_thr and m["face_width"] >= int(cfg["min_face_px"]) * 0.7
        yawn = m["mouth"] >= 0.35
        nod = m["pitch"] is not None and float(m["pitch"]) >= float(cfg["nod_deg"])
        # 墨镜/纯黑眼区：眼分过低且不像正常闭眼纹理，本帧不计入 PERCLOS
        eyes_ok = bool(cfg.get("night_mode")) or m["ear"] > 0.02 or yawn
        rec = {
            "closed": closed,
            "yawn": yawn,
            "nod": nod,
            "valid": eyes_ok,
            "ear": m["ear"],
            "mouth": m["mouth"],
            "pitch": m["pitch"],
        }
        hist.append((ctx.now, rec))

        win_sec = max(float(cfg.get("window_duration_sec") or 6.0), float(cfg.get("observe_sec") or 4.0))
        valid = [r for t, r in hist if ctx.now - t <= win_sec + 0.5 and r.get("valid")]
        n_valid = len(valid)
        perclos = (sum(1 for r in valid if r.get("closed")) / n_valid) if n_valid else 0.0
        yawns = self._yawn_events(hist, ctx.now, win_sec)
        nods = sum(1 for r in valid if r.get("nod"))
        observe_ok = n_valid >= max(4, int(float(cfg["observe_sec"]) * max(1.0, float(cfg["sample_fps"]) * 0.5)))

        reasons: List[str] = []
        if observe_ok and perclos >= float(cfg["perclos_pct"]):
            reasons.append("闭眼占比高")
        if observe_ok and yawns >= int(cfg["yawn_count"]):
            reasons.append("打哈欠")
        if observe_ok and nods >= max(3, n_valid // 4) and n_valid >= 6:
            reasons.append("低头")

        last_alert = float(state.get("last_alert") or 0.0)
        cooling = (ctx.now - last_alert) < float(cfg["cooldown_sec"])
        want = bool(reasons) and not cooling
        hold_since = state.get("hold_since")
        if want:
            if hold_since is None:
                state["hold_since"] = ctx.now
            if ctx.now - float(state["hold_since"]) >= float(cfg["alert_hold_sec"]):
                out["alert"] = True
                state["last_alert"] = ctx.now
                state["hold_since"] = None
        else:
            if not reasons:
                state["hold_since"] = None

        label = f"疲劳 PERCLOS {perclos * 100:.0f}%"
        if reasons:
            label = f"{label} {'/'.join(reasons)}"
        out["boxes"] = [
            {
                "box": m["box"],
                "confidence": float(face.get("det_score") or 0.0),
                "name": label,
            }
        ]
        out["count"] = 1
        out["perclos"] = round(perclos, 3)
        out["ear"] = m["ear"]
        out["reasons"] = reasons
        out["metrics"] = {
            "closed": closed,
            "yawn": yawn,
            "nod": nod,
            "pitch": m["pitch"],
            "face_width": m["face_width"],
        }

        self._maybe_gate(state, cfg, ctx, stream_id)
        out["supported"] = state.get("supported")
        out["reason_zh"] = state.get("reason_zh") or out["reason_zh"]
        if state.get("supported") is False:
            out["alert"] = False
        return out

    def _yawn_events(self, hist: Deque, now: float, win_sec: float) -> int:
        n = 0
        prev = False
        for t, r in hist:
            if now - t > win_sec + 0.5:
                continue
            y = bool(r.get("yawn") and r.get("valid"))
            if y and not prev:
                n += 1
            prev = y
        return n

    def _maybe_gate(
        self,
        state: Dict[str, Any],
        cfg: Dict[str, Any],
        ctx: BehaviorContext,
        stream_id: str,
    ) -> None:
        fps = 0.0
        hist = state.get("hist")
        if hist and len(hist) >= 3:
            t0 = hist[0][0]
            t1 = hist[-1][0]
            if t1 > t0:
                fps = (len(hist) - 1) / (t1 - t0)
        gate = evaluate_gate(
            samples=int(state.get("samples") or 0),
            faces=int(state.get("faces_seen") or 0),
            max_face_px=int(state.get("max_face_px") or 0),
            min_face_px=int(cfg["min_face_px"]),
            achieved_fps=fps,
            want_fps=float(cfg["sample_fps"]),
            has_engine=True,
        )
        state["supported"] = gate["supported"]
        state["reason"] = gate["reason"]
        state["reason_zh"] = gate["reason_zh"]
        self._flush_gate(stream_id, state, cfg, achieved_fps=fps, extra=gate)

    def _flush_gate(
        self,
        stream_id: str,
        state: Dict[str, Any],
        cfg: Dict[str, Any],
        *,
        achieved_fps: float,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "supported": state.get("supported"),
            "reason": state.get("reason") or "pending",
            "reason_zh": state.get("reason_zh") or "",
            "max_face_px": int(state.get("max_face_px") or 0),
            "samples": int(state.get("samples") or 0),
            "sample_fps": round(achieved_fps, 2),
            "want_fps": cfg.get("sample_fps"),
            "pull_mode": cfg.get("pull_mode"),
        }
        if extra:
            payload.update({k: extra[k] for k in extra if k not in payload})
        set_dms_status(stream_id, payload)
