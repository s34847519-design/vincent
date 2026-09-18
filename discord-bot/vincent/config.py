"""環境變數 → 設定物件。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time as dtime
from zoneinfo import ZoneInfo


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _parse_hhmm(raw: str) -> dtime:
    hh, mm = raw.strip().split(":")
    return dtime(int(hh), int(mm))


@dataclass(frozen=True)
class Window:
    """一個「可能主動開口」的時段。"""

    start: dtime
    end: dtime
    probability: float

    @property
    def label(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


def _parse_windows(raw: str) -> list[Window]:
    windows: list[Window] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        span, _, prob = chunk.partition("@")
        start_raw, _, end_raw = span.partition("-")
        windows.append(
            Window(
                start=_parse_hhmm(start_raw),
                end=_parse_hhmm(end_raw),
                probability=float(prob) if prob else 1.0,
            )
        )
    return windows


@dataclass(frozen=True)
class Config:
    discord_token: str
    owner_id: int

    persona_files: list[str]

    model: str
    effort: str
    thinking: str          # "adaptive"（會思考，貴）或 "off"（不思考，便宜）
    max_tokens: int
    use_fallbacks: bool

    db_path: str
    history_messages: int

    tz: ZoneInfo
    initiative_enabled: bool
    windows: list[Window] = field(default_factory=list)
    quiet_start: dtime = dtime(1, 0)
    quiet_end: dtime = dtime(8, 0)
    max_per_day: int = 3
    idle_hours: int = 20
    recent_skip_minutes: int = 60
    stale_minutes: int = 90   # 排定時間已過這麼久就不補發（電腦睡著的情況）

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit("缺少 DISCORD_BOT_TOKEN，先照著 .env.example 填一份 .env。")

        owner_raw = os.getenv("VINCENT_OWNER_ID", "").strip()
        if not owner_raw.isdigit():
            raise SystemExit("缺少 VINCENT_OWNER_ID（你自己的 Discord 使用者 ID，一串數字）。")

        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise SystemExit("缺少 ANTHROPIC_API_KEY。")

        quiet_raw = os.getenv("VINCENT_QUIET", "01:00-08:00")
        quiet_start_raw, _, quiet_end_raw = quiet_raw.partition("-")

        return cls(
            discord_token=token,
            owner_id=int(owner_raw),
            persona_files=[
                p.strip()
                for p in os.getenv("VINCENT_PERSONA_FILES", "../CLAUDE.md").split(":")
                if p.strip()
            ],
            model=os.getenv("VINCENT_MODEL", "claude-opus-5").strip(),
            effort=os.getenv("VINCENT_EFFORT", "medium").strip(),
            thinking=os.getenv("VINCENT_THINKING", "adaptive").strip().lower(),
            max_tokens=_int("VINCENT_MAX_TOKENS", 8000),
            use_fallbacks=_bool("VINCENT_FALLBACKS", True),
            db_path=os.getenv("VINCENT_DB", "./data/vincent.db").strip(),
            history_messages=_int("VINCENT_HISTORY", 60),
            tz=ZoneInfo(os.getenv("VINCENT_TZ", "Asia/Taipei").strip()),
            initiative_enabled=_bool("VINCENT_INITIATIVE", True),
            windows=_parse_windows(
                os.getenv(
                    "VINCENT_WINDOWS",
                    "08:00-10:30@0.55,13:00-15:30@0.35,21:00-23:30@0.75",
                )
            ),
            quiet_start=_parse_hhmm(quiet_start_raw),
            quiet_end=_parse_hhmm(quiet_end_raw),
            max_per_day=_int("VINCENT_MAX_PER_DAY", 3),
            idle_hours=_int("VINCENT_IDLE_HOURS", 20),
            recent_skip_minutes=_int("VINCENT_RECENT_SKIP_MIN", 60),
            stale_minutes=_int("VINCENT_STALE_MIN", 90),
        )
