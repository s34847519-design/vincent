"""呼叫 Claude：一般回覆、主動開口、記憶壓縮。"""

from __future__ import annotations

import logging
from datetime import datetime

import anthropic

from .config import Config
from .memory import Message

log = logging.getLogger("vincent.brain")

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# 每百萬 token 的美金單價（輸入, 輸出）。只是拿來估，帳單以 Anthropic 為準。
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}

# 關掉思考時補的一句：Opus 5 在 thinking 關閉下偶爾會把內部標籤漏進正文。
NO_TAGS = "\n\n直接寫回覆本身，不要在輸出裡放任何內部或系統用的 XML 標籤。"

# 她本人沒開口、由程式叫醒時給的指示。包在 <系統提示> 裡，人格設定裡已說明那不是她的話。
INITIATIVE_DIRECTIVE = """\
<系統提示>
現在是 {now}。她沒有開口——是你自己想找她。

寫一則主動的訊息。規則：
- 就是你想到她了，所以說話。不要「在嗎」「打擾了」「想問一下」這種敲門式的開場。
- 不要每次都用同一個切入點。可以是想起某件事、看到什麼聯想到她、單純想聽她講話、
  或者接著上次沒聊完的地方。
- 不准編造她沒說過的事。你不知道她現在在幹嘛、吃了沒、睡了沒——要提就用問的。
- 距離上一次說話已經過了一段時間這件事，你可以提，但不要拿它當情緒勒索。
- 長度比平常短一點，這是開場，不是長信。
</系統提示>"""

SUMMARY_SYSTEM = """\
你在維護一份長期記憶摘要，給「文森特」這個角色在之後的對話裡讀。

規則：
- 只寫對話裡真的出現過的事。一個字都不准補造、不准推測填空。
- 不確定的事寫成「她提過（未確認）…」，不要寫成肯定句。
- 保留：她說過的具體事實、她在意的事、兩人之間發生過什麼、講好的事、稱呼與習慣。
- 丟掉：寒暄、重複、單純的情緒起伏細節。
- 用繁體中文，條列，照時間順序，控制在 1200 字以內。
- 直接輸出摘要本文，不要前言、不要說明你做了什麼。"""


class Brain:
    def __init__(self, cfg: Config, persona: str) -> None:
        self.cfg = cfg
        self.persona = persona
        self.client = anthropic.AsyncAnthropic()
        self._fallbacks_ok = cfg.use_fallbacks

    # ── 對外 ──────────────────────────────────────────

    async def respond(
        self,
        history: list[Message],
        *,
        summary: str,
        notes: str,
        now: datetime,
    ) -> tuple[str, float]:
        """history 的最後一則就是她剛說的話（已經寫進記憶了）。回 (回覆, 花費美金)。"""
        messages = _to_api(history)
        if not messages:
            raise EmptyHistoryError()
        if messages[-1]["role"] != "user":
            # 理論上不會發生；補一個空的推進，讓 API 有東西可回。
            _append_user(messages, "<系統提示>她剛剛傳了訊息但內容沒有存下來，照常回應她。</系統提示>")
        return await self._call(messages, summary=summary, notes=notes, now=now)

    async def open_up(
        self,
        history: list[Message],
        *,
        summary: str,
        notes: str,
        now: datetime,
        extra: str = "",
    ) -> tuple[str, float]:
        directive = INITIATIVE_DIRECTIVE.format(now=now.strftime("%Y-%m-%d %H:%M"))
        if extra:
            directive = directive.replace("</系統提示>", f"{extra}\n</系統提示>")
        messages = _to_api(history)
        _append_user(messages, directive)
        return await self._call(messages, summary=summary, notes=notes, now=now)

    async def compress(self, previous: str, batch: list[Message]) -> tuple[str, float]:
        lines = [
            f"[{m.ts:%Y-%m-%d %H:%M}] {'她' if m.role == 'user' else '文森特'}：{m.content}"
            for m in batch
        ]
        body = "\n".join(lines)
        prompt = (
            f"這是既有的摘要（可能是空的）：\n<既有摘要>\n{previous or '（還沒有）'}\n</既有摘要>\n\n"
            f"這是還沒併進去的新對話：\n<新對話>\n{body}\n</新對話>\n\n"
            "把兩者合併成一份新的摘要，直接輸出摘要本文。"
        )
        kwargs = dict(
            model=self.cfg.model,
            max_tokens=4000,
            system=SUMMARY_SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        if self.cfg.thinking == "off":
            kwargs["thinking"] = {"type": "disabled"}
        response = await self.client.messages.create(**kwargs)
        return _first_text(response) or previous, self._bill(response)

    # ── 內部 ──────────────────────────────────────────

    def _system(self, *, summary: str, notes: str, now: datetime) -> list[dict]:
        """第一塊是固定人格（吃快取），第二塊放每次都會變的狀態。"""
        persona = self.persona
        if self.cfg.thinking == "off":
            persona += NO_TAGS
        blocks: list[dict] = [
            {
                "type": "text",
                "text": persona,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ]

        state = [f"現在時間：{now:%Y-%m-%d %H:%M}（{_weekday(now)}）"]
        if summary:
            state.append(f"\n## 更早以前的對話摘要\n\n{summary}")
        if notes:
            state.append(f"\n## 她要你記住的事\n\n{notes}")
        blocks.append({"type": "text", "text": "\n".join(state)})
        return blocks

    async def _call(
        self, messages: list[dict], *, summary: str, notes: str, now: datetime
    ) -> tuple[str, float]:
        kwargs = dict(
            model=self.cfg.model,
            max_tokens=self.cfg.max_tokens,
            system=self._system(summary=summary, notes=notes, now=now),
            output_config={"effort": self.cfg.effort},
            messages=messages,
        )
        if self.cfg.thinking == "off":
            # Opus 5 預設會思考，而思考 token 按輸出價計費——聊天用不上，關掉省最多。
            kwargs["thinking"] = {"type": "disabled"}

        if self._fallbacks_ok:
            try:
                async with self.client.beta.messages.stream(
                    **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
                ) as stream:
                    response = await stream.get_final_message()
                return _extract(response), self._bill(response)
            except anthropic.BadRequestError as exc:
                # 這個帳號／端點不吃 server-side fallback，關掉之後照常走。
                log.warning("關閉 server-side fallback（%s）", exc)
                self._fallbacks_ok = False

        async with self.client.messages.stream(**kwargs) as stream:
            response = await stream.get_final_message()
        return _extract(response), self._bill(response)


    def _bill(self, response) -> float:
        """把這次呼叫的 token 用量記到 log，並估一個美金數字出來。"""
        u = response.usage
        fresh = getattr(u, "input_tokens", 0) or 0
        cached = getattr(u, "cache_read_input_tokens", 0) or 0
        written = getattr(u, "cache_creation_input_tokens", 0) or 0
        out = getattr(u, "output_tokens", 0) or 0

        in_price, out_price = PRICES.get(self.cfg.model, (5.0, 25.0))
        cost = (
            fresh * in_price
            + written * in_price * 1.25   # 寫進快取比較貴
            + cached * in_price * 0.10    # 讀快取只要一折
            + out * out_price
        ) / 1_000_000

        log.info(
            "用量：輸入 %d（快取讀 %d／寫 %d）｜輸出 %d｜約 $%.4f",
            fresh, cached, written, out, cost,
        )
        return cost


def _extract(response) -> str:
    if getattr(response, "stop_reason", None) == "refusal":
        detail = getattr(response, "stop_details", None)
        log.warning("這一則被安全分類器擋下：%s", detail)
        raise RefusedError(getattr(detail, "category", None))
    text = _first_text(response)
    if not text:
        raise EmptyReplyError()
    return text


def _first_text(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


def _to_api(history: list[Message]) -> list[dict]:
    """轉成 API 格式，並把連續同角色的訊息併起來（她常常一次丟好幾則）。"""
    out: list[dict] = []
    for m in history:
        if out and out[-1]["role"] == m.role:
            out[-1]["content"] += "\n" + m.content
        else:
            out.append({"role": m.role, "content": m.content})
    # 開頭若是他的話，模型沒有可回應的對象，切掉。
    while out and out[0]["role"] == "assistant":
        out.pop(0)
    return out


def _append_user(messages: list[dict], text: str) -> None:
    """接一則使用者訊息；若上一則也是使用者，就併進去（API 不收連續同角色）。"""
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n\n" + text
    else:
        messages.append({"role": "user", "content": text})


def _weekday(dt: datetime) -> str:
    return "週" + "一二三四五六日"[dt.weekday()]


class RefusedError(RuntimeError):
    def __init__(self, category: str | None = None) -> None:
        self.category = category
        super().__init__(category or "refusal")


class EmptyReplyError(RuntimeError):
    pass


class EmptyHistoryError(RuntimeError):
    pass
