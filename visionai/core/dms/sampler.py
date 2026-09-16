"""密检窗状态机：always 间隔开窗 / burst 一窗后断开。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from visionai.core.dms.config import normalize_fatigue_config, resolve_window


@dataclass
class WindowSampler:
    cfg: Dict[str, Any]
    in_window: bool = False
    window_started: float = 0.0
    last_sample: float = 0.0
    last_window_end: float = 0.0
    samples: int = 0
    first_sample_ts: float = 0.0
    last_sample_ts: float = 0.0

    @classmethod
    def from_cfg(cls, raw: Optional[Dict[str, Any]]) -> "WindowSampler":
        return cls(cfg=normalize_fatigue_config(raw))

    def update_cfg(self, raw: Optional[Dict[str, Any]]) -> None:
        self.cfg = normalize_fatigue_config(raw)

    def sample_interval(self) -> float:
        _, _, interval = resolve_window(self.cfg)
        return interval

    def window_limits(self) -> tuple[float, int]:
        dur, frames, _ = resolve_window(self.cfg)
        return dur, frames

    def pull_gap(self) -> float:
        return max(0.0, float(self.cfg.get("pull_interval_sec") or 0.0))

    def pull_mode(self) -> str:
        return "burst" if str(self.cfg.get("pull_mode") or "") == "burst" else "always"

    def waiting_for_next_pull(self, now: float) -> bool:
        if self.in_window:
            return False
        gap = self.pull_gap()
        if self.last_window_end <= 0:
            return False
        return (now - self.last_window_end) < gap

    def should_sample(self, now: float) -> bool:
        if not self.in_window:
            if self.waiting_for_next_pull(now):
                return False
            self.in_window = True
            self.window_started = now
            self.samples = 0
            self.last_sample = 0.0
        if now - self.last_sample < self.sample_interval() * 0.85:
            return False
        self.last_sample = now
        self.samples += 1
        if self.first_sample_ts <= 0:
            self.first_sample_ts = now
        self.last_sample_ts = now
        return True

    def achieved_fps(self) -> float:
        if self.samples < 2 or self.last_sample_ts <= self.first_sample_ts:
            return 0.0
        return (self.samples - 1) / (self.last_sample_ts - self.first_sample_ts)

    def maybe_close_window(self, now: float) -> bool:
        if not self.in_window:
            return False
        dur, frames = self.window_limits()
        done = False
        if str(self.cfg.get("window_mode") or "duration") == "frames":
            done = self.samples >= frames
        else:
            done = (now - self.window_started) >= dur or self.samples >= frames
        if not done:
            return False
        self.in_window = False
        self.last_window_end = now
        return True
