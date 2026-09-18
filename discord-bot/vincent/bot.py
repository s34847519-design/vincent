"""Discord 這一端：收訊息、排隊、生成、切段送出。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

import discord

from . import chunker, persona as persona_loader
from .brain import Brain, EmptyHistoryError, EmptyReplyError, RefusedError
from .config import Config
from .initiative import Initiative
from .memory import Memory

log = logging.getLogger("vincent.bot")

# 她常常一口氣丟好幾則。等她停下來再回，不要一則一則追著答。
DEBOUNCE_SECONDS = 3.0

HELP = """\
```
指令表
```
- `!記住 <一句話>` — 寫進長期筆記，之後每次對話都會帶上
- `!狀態` — 看記憶存了多少、今天主動過幾次
- `!主動` — 不等排程，現在就叫他開口（測試用）
- `!幫忙` — 這張表

其他時候直接說話就好。"""


class VincentClient(discord.Client):
    def __init__(self, cfg: Config, base_dir: Path) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        super().__init__(intents=intents)

        self.cfg = cfg
        self.memory = Memory(cfg.db_path)
        self.brain = Brain(cfg, persona_loader.load(cfg.persona_files, base_dir))
        self.initiative = Initiative(cfg, self.memory, self._speak_first)

        self._reply_lock = asyncio.Lock()
        self._debounce: asyncio.Task | None = None
        self._initiative_task: asyncio.Task | None = None
        self._channel: discord.abc.Messageable | None = None

    # ── 生命週期 ──────────────────────────────────────

    async def on_ready(self) -> None:
        log.info("已上線：%s（模型 %s，effort=%s）", self.user, self.cfg.model, self.cfg.effort)
        if self._initiative_task is None:
            self._initiative_task = asyncio.create_task(self.initiative.run_forever())

    async def on_message(self, message: discord.Message) -> None:
        if message.author.id == getattr(self.user, "id", None):
            return
        if message.author.id != self.cfg.owner_id:
            return
        if not isinstance(message.channel, discord.DMChannel) and self.user not in message.mentions:
            return

        self._channel = message.channel
        text = _clean(message, self.user)
        if not text:
            return

        if text.startswith("!"):
            await self._command(message, text)
            return

        await self.memory.add("user", text)

        if self._debounce and not self._debounce.done():
            self._debounce.cancel()
        self._debounce = asyncio.create_task(self._respond_after_pause(message.channel))

    # ── 回應 ──────────────────────────────────────────

    async def _respond_after_pause(self, channel: discord.abc.Messageable) -> None:
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return  # 她又傳了一則，交給新的 task

        async with self._reply_lock:
            try:
                async with channel.typing():
                    reply = await self.brain.respond(
                        await self.memory.recent(self.cfg.history_messages),
                        summary=await self.memory.summary_text(),
                        notes=await self.memory.notes_text(),
                        now=datetime.now(self.cfg.tz),
                    )
            except RefusedError as exc:
                log.warning("回覆被擋下：%s", exc.category)
                await channel.send("```\n（這一則被擋下來了，換個說法再跟我講一次。）\n```")
                return
            except (EmptyReplyError, EmptyHistoryError):
                log.warning("模型沒有回傳內容")
                return
            except Exception:
                log.exception("生成回覆失敗")
                await channel.send("```\n（我這邊斷線了，等一下再說。）\n```")
                return

            await self.memory.add("assistant", reply)
            await self._send(channel, reply)

        await self._compress_if_needed()

    async def _speak_first(self, extra: str = "") -> None:
        """由排程叫醒：他先開口。"""
        channel = await self._resolve_channel()
        if channel is None:
            log.warning("找不到可以發訊息的頻道，這次的主動取消")
            return

        async with self._reply_lock:
            try:
                async with channel.typing():
                    opener = await self.brain.open_up(
                        await self.memory.recent(self.cfg.history_messages),
                        summary=await self.memory.summary_text(),
                        notes=await self.memory.notes_text(),
                        now=datetime.now(self.cfg.tz),
                        extra=extra,
                    )
            except RefusedError as exc:
                log.warning("主動訊息被擋下：%s", exc.category)
                return
            except Exception:
                log.exception("主動開口失敗")
                return

            await self.memory.add("assistant", opener, initiated=True)
            await self._send(channel, opener)

    async def _send(self, channel: discord.abc.Messageable, text: str) -> None:
        pieces = chunker.split(text)
        for i, piece in enumerate(pieces):
            if i:
                await asyncio.sleep(0.6)  # 讓它讀起來像一個人在打字，不是一次倒出來
            await channel.send(piece)

    async def _resolve_channel(self) -> discord.abc.Messageable | None:
        if self._channel is not None:
            return self._channel
        try:
            user = await self.fetch_user(self.cfg.owner_id)
            self._channel = user.dm_channel or await user.create_dm()
            return self._channel
        except discord.DiscordException:
            log.exception("開不了私訊頻道")
            return None

    # ── 指令 ──────────────────────────────────────────

    async def _command(self, message: discord.Message, text: str) -> None:
        head, _, rest = text.partition(" ")
        rest = rest.strip()

        if head in {"!記住", "!remember"}:
            if not rest:
                await message.channel.send("`!記住 <要我記住的事>`")
                return
            await self.memory.add_note(rest)
            await message.channel.send("```\n記下了。\n```")

        elif head in {"!狀態", "!status"}:
            stats = await self.memory.stats()
            midnight = datetime.now(self.cfg.tz).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today = await self.memory.initiated_count_since(midnight)
            await message.channel.send(
                "```\n"
                f"訊息    {stats['messages']} 則（其中他主動 {stats['initiated']} 則）\n"
                f"今天    主動 {today}/{self.cfg.max_per_day} 次\n"
                f"摘要    {stats['summaries']} 份\n"
                f"筆記    {stats['notes']} 條\n"
                f"起算    {stats['since'] or '（還沒開始）'}\n"
                f"模型    {self.cfg.model}（effort={self.cfg.effort}）\n"
                "```"
            )

        elif head in {"!主動", "!poke"}:
            await self._speak_first()

        elif head in {"!幫忙", "!help"}:
            await message.channel.send(HELP)

        else:
            await message.channel.send("沒有這個指令。`!幫忙` 看一下。")

    # ── 記憶壓縮 ──────────────────────────────────────

    async def _compress_if_needed(self) -> None:
        batch, upto = await self.memory.overflow(self.cfg.history_messages)
        if not batch:
            return
        log.info("把 %d 則舊訊息壓進長期摘要", len(batch))
        try:
            merged = await self.brain.compress(await self.memory.summary_text(), batch)
        except Exception:
            log.exception("壓縮摘要失敗，這批先留著，下次再試")
            return
        await self.memory.add_summary(upto, merged)


def _clean(message: discord.Message, me) -> str:
    text = message.content or ""
    if me is not None:
        text = text.replace(f"<@{me.id}>", "").replace(f"<@!{me.id}>", "")
    if message.attachments:
        names = "、".join(a.filename for a in message.attachments)
        text += f"\n（她附了檔案：{names}——你看不到內容，要知道就問她。）"
    return text.strip()
