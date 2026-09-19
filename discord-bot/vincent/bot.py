"""Discord 這一端：收訊息、排隊、生成、切段送出。"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from datetime import datetime, timezone
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

# Claude 看得懂的圖片格式
VISION_TYPES = {"jpeg", "jpg", "png", "gif", "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

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
        self._pending_images: list[dict] = []
        self._initiative_task: asyncio.Task | None = None
        self._channel: discord.abc.Messageable | None = None

    # ── 生命週期 ──────────────────────────────────────

    async def on_ready(self) -> None:
        log.info("已上線：%s（模型 %s，effort=%s）", self.user, self.cfg.model, self.cfg.effort)
        if self._initiative_task is None:
            self._initiative_task = asyncio.create_task(self.initiative.run_forever())
        asyncio.create_task(self._catch_up())

    async def _catch_up(self) -> None:
        """離線期間她傳的訊息，Discord 不會事後補送給機器人——自己回頭去讀。"""
        last = await self.memory.last_message()
        if last is None:
            return  # 全新的記憶，沒有「漏掉」這回事

        channel = await self._resolve_channel()
        if channel is None or not hasattr(channel, "history"):
            return

        missed: list[str] = []
        try:
            async for msg in channel.history(
                after=last.ts.astimezone(timezone.utc), limit=100, oldest_first=True
            ):
                if msg.author.id != self.cfg.owner_id:
                    continue
                text = _clean(msg, self.user)
                if text and not text.startswith("!"):
                    missed.append(text)
        except discord.DiscordException:
            log.exception("回頭讀離線期間的訊息失敗")
            return

        if not missed:
            log.info("離線期間沒有漏掉訊息")
            return

        log.info("離線期間漏掉 %d 則，補讀回來並回應", len(missed))
        for text in missed:
            await self.memory.add("user", text)
        await self._reply_to_channel(channel)

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
        if self.cfg.vision:
            self._pending_images.extend(await self._download_images(message))

        if self._debounce and not self._debounce.done():
            self._debounce.cancel()
        self._debounce = asyncio.create_task(self._respond_after_pause(message.channel))

    async def _download_images(self, message: discord.Message) -> list[dict]:
        """把她傳的圖抓下來轉 base64。太大的略過——與其讓整則失敗，不如少看一張。"""
        out: list[dict] = []
        for attachment in message.attachments:
            if len(out) >= self.cfg.max_images:
                break
            if not _is_image(attachment):
                continue
            if attachment.size > MAX_IMAGE_BYTES:
                log.info("圖片 %s 太大（%.1f MB），略過", attachment.filename,
                         attachment.size / 1_048_576)
                continue
            try:
                raw = await attachment.read()
            except discord.DiscordException:
                log.exception("讀取圖片 %s 失敗", attachment.filename)
                continue
            ctype = (attachment.content_type or "image/png").split(";")[0].strip()
            out.append({
                "media_type": "image/jpeg" if ctype == "image/jpg" else ctype,
                "data": base64.standard_b64encode(raw).decode("ascii"),
            })
        if out:
            log.info("帶上 %d 張圖片給他看", len(out))
        return out

    # ── 回應 ──────────────────────────────────────────

    async def _respond_after_pause(self, channel: discord.abc.Messageable) -> None:
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return  # 她又傳了一則，交給新的 task
        await self._reply_to_channel(channel)

    async def _reply_to_channel(self, channel: discord.abc.Messageable) -> None:
        async with self._reply_lock:
            try:
                async with channel.typing():
                    images, self._pending_images = self._pending_images, []
                    reply, spent = await self.brain.respond(
                        await self.memory.recent(self.cfg.history_messages),
                        summary=await self.memory.summary_text(),
                        notes=await self.memory.notes_text(),
                        now=datetime.now(self.cfg.tz),
                        images=images,
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
            await self._record_spend(spent)
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
                    opener, spent = await self.brain.open_up(
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
            await self._record_spend(spent)
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
            day = midnight.strftime("%Y-%m-%d")
            spent_today = await self.memory.get_state(f"spend:{day}", 0.0) or 0.0
            spent_all = await self.memory.get_state("spend:total", 0.0) or 0.0
            await message.channel.send(
                "```\n"
                f"訊息    {stats['messages']} 則（其中他主動 {stats['initiated']} 則）\n"
                f"今天    主動 {today}/{self.cfg.max_per_day} 次\n"
                f"摘要    {stats['summaries']} 份\n"
                f"筆記    {stats['notes']} 條\n"
                f"起算    {stats['since'] or '（還沒開始）'}\n"
                f"模型    {self.cfg.model}（effort={self.cfg.effort}，"
                f"思考={'開' if self.cfg.thinking != 'off' else '關'}）\n"
                f"花費    今天約 ${spent_today:.3f}／累計約 ${spent_all:.3f} USD（估算）\n"
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
            merged, spent = await self.brain.compress(
                await self.memory.summary_text(), batch
            )
        except Exception:
            log.exception("壓縮摘要失敗，這批先留著，下次再試")
            return
        await self.memory.add_summary(upto, merged)
        await self._record_spend(spent)

    async def _record_spend(self, amount: float) -> None:
        day = datetime.now(self.cfg.tz).strftime("%Y-%m-%d")
        await self.memory.add_spend(day, amount)


CUSTOM_EMOJI = re.compile(r"<a?:(\w+):\d+>")


def _clean(message: discord.Message, me) -> str:
    """把一則 Discord 訊息壓成他讀得懂的純文字。

    貼圖、自訂表情、附檔都不在 content 裡（或是以原始碼的形式在裡面），
    不翻譯的話他要嘛看到亂碼，要嘛整則訊息是空的、直接被吞掉。
    """
    text = message.content or ""
    if me is not None:
        text = text.replace(f"<@{me.id}>", "").replace(f"<@!{me.id}>", "")

    # <:catcry:12345> -> :catcry:　名字才是意思所在
    text = CUSTOM_EMOJI.sub(r":\1:", text)

    prefix = ""
    ref = message.reference
    quoted = getattr(ref, "resolved", None) if ref is not None else None
    if isinstance(quoted, discord.Message) and quoted.content:
        snippet = quoted.content[:200].replace("\n", " ")
        prefix = f"（她回的是這句：「{snippet}」）\n"

    extras: list[str] = []

    # 貼圖完全不在 content 裡。名字就是它的意思，至少要讓他知道有這回事。
    if message.stickers:
        names = "、".join(s.name for s in message.stickers)
        extras.append(f"（她傳了貼圖：{names}）")

    images = [a for a in message.attachments if _is_image(a)]
    others = [a for a in message.attachments if not _is_image(a)]
    if images:
        extras.append(f"（她傳了圖片：{'、'.join(a.filename for a in images)}）")
    if others:
        extras.append(
            f"（她附了檔案：{'、'.join(a.filename for a in others)}"
            "——你看不到內容，要知道就問她。）"
        )

    body = "\n".join(filter(None, [prefix + text.strip(), *extras]))
    return body.strip()


def _is_image(attachment: discord.Attachment) -> bool:
    ctype = (attachment.content_type or "").lower()
    return ctype.startswith("image/") and ctype.split("/")[-1] in VISION_TYPES
