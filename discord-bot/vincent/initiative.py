"""主動開口的排程。

他不會「想」開口——會開口是因為這裡把他叫醒。做法是：
每天替每個時段擲一次骰，中了就在那個時段裡隨機挑一分鐘，時間到了叫 Brain 寫第一句話。
所以時間是散的、有些日子安靜、有些日子多講一句，而不是每天整點報到。
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, datetime, time as dtime, timedelta
from typing import Awaitable, Callable

from .config import Config
from .memory import Memory

log = logging.getLogger("vincent.initiative")

TICK_SECONDS = 60


class Initiative:
    def __init__(
        self,
        cfg: Config,
        memory: Memory,
        speak: Callable[[str], Awaitable[None]],
    ) -> None:
        self.cfg = cfg
        self.memory = memory
        self.speak = speak  # 由 bot 提供：產生訊息並送到她的私訊

    async def run_forever(self) -> None:
        if not self.cfg.initiative_enabled:
            log.info("主動開口已關閉（VINCENT_INITIATIVE=0）")
            return
        log.info(
            "主動開口已啟動：%s｜安靜時段 %s-%s｜一天上限 %d 次",
            "、".join(f"{w.label}（{w.probability:.0%}）" for w in self.cfg.windows),
            self.cfg.quiet_start.strftime("%H:%M"),
            self.cfg.quiet_end.strftime("%H:%M"),
            self.cfg.max_per_day,
        )
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("主動開口的排程這一輪出錯，下一輪繼續")
            await asyncio.sleep(TICK_SECONDS)

    # ── 一輪 ──────────────────────────────────────────

    async def tick(self) -> None:
        now = datetime.now(self.cfg.tz)
        plan = await self._plan_for(now.date())

        due = [t for t in plan if t <= now]
        if due:
            await self._mark_fired(now.date(), due)
            reason = await self._blocked(now)
            if reason:
                log.info("到了排定的時間但先不開口：%s", reason)
            else:
                await self._fire(now, kind="window")
                return

        await self._idle_check(now)

    async def _idle_check(self, now: datetime) -> None:
        if self.cfg.idle_hours <= 0 or self._in_quiet(now):
            return
        last = await self.memory.last_message()
        if last is None:
            return
        gap = now - last.ts.astimezone(self.cfg.tz)
        if gap < timedelta(hours=self.cfg.idle_hours):
            return
        marker = await self.memory.get_state("last_idle_poke")
        if marker:
            since = datetime.fromisoformat(marker).astimezone(self.cfg.tz)
            if now - since < timedelta(hours=self.cfg.idle_hours):
                return
        await self.memory.set_state("last_idle_poke", now.isoformat())
        hours = int(gap.total_seconds() // 3600)
        await self._fire(
            now,
            kind="idle",
            extra=f"\n（你們已經 {hours} 小時沒說話了。）",
        )

    async def _fire(self, now: datetime, *, kind: str, extra: str = "") -> None:
        log.info("主動開口（%s）", kind)
        await self.speak(extra)

    # ── 條件 ──────────────────────────────────────────

    async def _blocked(self, now: datetime) -> str | None:
        if self._in_quiet(now):
            return "現在是安靜時段"

        midnight = datetime.combine(now.date(), dtime(0, 0), tzinfo=self.cfg.tz)
        used = await self.memory.initiated_count_since(midnight)
        if used >= self.cfg.max_per_day:
            return f"今天已經主動 {used} 次，到上限了"

        last_user = await self.memory.last_user_message()
        if last_user is not None:
            gap = now - last_user.ts.astimezone(self.cfg.tz)
            if gap < timedelta(minutes=self.cfg.recent_skip_minutes):
                return "她剛剛才說過話"
        return None

    def _in_quiet(self, now: datetime) -> bool:
        start, end = self.cfg.quiet_start, self.cfg.quiet_end
        t = now.time()
        if start <= end:
            return start <= t < end
        return t >= start or t < end  # 跨午夜

    # ── 排程 ──────────────────────────────────────────

    async def _plan_for(self, day: date) -> list[datetime]:
        key = f"plan:{day.isoformat()}"
        stored = await self.memory.get_state(key)
        if stored is None:
            stored = [t.isoformat() for t in self._roll(day)]
            await self.memory.set_state(key, stored)
            if stored:
                log.info(
                    "今天（%s）排定主動開口：%s",
                    day,
                    "、".join(datetime.fromisoformat(t).strftime("%H:%M") for t in stored),
                )
            else:
                log.info("今天（%s）骰子沒中，不主動開口", day)

        fired = set(await self.memory.get_state(f"fired:{day.isoformat()}", []) or [])
        return [
            datetime.fromisoformat(t)
            for t in stored
            if t not in fired
        ]

    def _roll(self, day: date) -> list[datetime]:
        picks: list[datetime] = []
        for window in self.cfg.windows:
            if random.random() > window.probability:
                continue
            start = datetime.combine(day, window.start, tzinfo=self.cfg.tz)
            end = datetime.combine(day, window.end, tzinfo=self.cfg.tz)
            if end <= start:
                end += timedelta(days=1)
            span = int((end - start).total_seconds() // 60)
            picks.append(start + timedelta(minutes=random.randint(0, max(span, 0))))
        return sorted(picks)

    async def _mark_fired(self, day: date, times: list[datetime]) -> None:
        key = f"fired:{day.isoformat()}"
        fired = set(await self.memory.get_state(key, []) or [])
        fired.update(t.isoformat() for t in times)
        await self.memory.set_state(key, sorted(fired))
