"""載入人格設定：直接讀 repo 裡的 CLAUDE.md，兩邊同源，改一次就好。"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("vincent.persona")

# Discord 這個場子特有的操作守則。人格本身一律來自 CLAUDE.md，這裡只補通道差異。
CHANNEL_NOTES = """\
---

## 這個通道（Discord）

你現在透過 Discord 私訊跟她說話。

- 太長的回覆會被程式自動切成好幾則送出，你不用自己遷就長度，照平常寫。
- 開頭那一行 code block 照常放，切訊息時程式會保住它。
- 你看到用 `<系統提示>` 包起來的段落，那是程式給你的狀態說明（現在幾點、她多久沒說話），
  **不是她說的話**。不要把它當成她的發言引用，也不要在回覆裡覆述它。
- 你有時會在她沒開口的情況下被叫醒，要你主動說第一句話。那時就真的主動——
  想到什麼講什麼，不要用「在嗎」「打擾了」這種客套開場，也不要每次都問一樣的問題。
- 除非她問，否則不要談這個通道怎麼運作、模型怎麼跑、記憶怎麼存。

## 記憶的實話

你能看到的是：最近的對話原文，加上更早以前被壓縮過的摘要。
摘要會失真。凡是摘要沒寫清楚、你又要拿來當前提的具體事實，先問一句確認。
"""


def load(paths: list[str], base_dir: Path) -> str:
    """把設定檔串成一份 system prompt。"""
    parts: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if not path.exists():
            log.warning("人格檔不存在，略過：%s", path)
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)
            log.info("載入人格檔：%s（%d 字）", path, len(text))

    if not parts:
        raise SystemExit(
            "一個人格檔都沒讀到。檢查 VINCENT_PERSONA_FILES 指到的路徑（預設 ../CLAUDE.md）。"
        )

    parts.append(CHANNEL_NOTES)
    return "\n\n".join(parts)
