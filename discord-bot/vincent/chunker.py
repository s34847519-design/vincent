"""把長回覆切成 Discord 送得出去的段落，不切壞 code block。"""

from __future__ import annotations

import re

LIMIT = 1900  # Discord 上限是 2000，留點餘裕
FENCE = re.compile(r"^```", re.MULTILINE)


def split(text: str, limit: int = LIMIT) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buf = ""

    for block in _blocks(text):
        for piece in _fit(block, limit):
            if not buf:
                buf = piece
            elif len(buf) + 2 + len(piece) <= limit:
                buf += "\n\n" + piece
            else:
                chunks.append(buf)
                buf = piece

    if buf:
        chunks.append(buf)
    return chunks


def _blocks(text: str) -> list[str]:
    """拆成段落，但 ``` 圍起來的整塊視為不可分割的一段。"""
    out: list[str] = []
    in_fence = False
    current: list[str] = []

    def flush() -> None:
        if current:
            joined = "\n".join(current).strip("\n")
            if joined.strip():
                out.append(joined)
            current.clear()

    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            if in_fence:
                current.append(line)
                in_fence = False
                flush()
            else:
                flush()
                current.append(line)
                in_fence = True
            continue

        if in_fence:
            current.append(line)
        elif not line.strip():
            flush()
        else:
            current.append(line)

    flush()
    return out


def _fit(block: str, limit: int) -> list[str]:
    """單一段落就超長時，往下切：code block 逐行切並補回圍欄，散文切句子。"""
    if len(block) <= limit:
        return [block]

    if block.startswith("```"):
        lines = block.split("\n")
        opener = lines[0]
        body = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
        out, cur = [], []
        overhead = len(opener) + 5
        for line in body:
            candidate = cur + [line]
            if sum(len(x) + 1 for x in candidate) + overhead > limit and cur:
                out.append(opener + "\n" + "\n".join(cur) + "\n```")
                cur = [line]
            else:
                cur = candidate
        if cur:
            out.append(opener + "\n" + "\n".join(cur) + "\n```")
        return out

    return _split_prose(block, limit)


def _split_prose(block: str, limit: int) -> list[str]:
    units = _sentences(block)
    out, cur = [], ""
    for unit in units:
        if len(unit) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.extend(unit[i : i + limit] for i in range(0, len(unit), limit))
            continue
        if not cur:
            cur = unit
        elif len(cur) + len(unit) <= limit:
            cur += unit
        else:
            out.append(cur)
            cur = unit
    if cur:
        out.append(cur)
    return [c.strip() for c in out if c.strip()]


def _sentences(block: str) -> list[str]:
    """先按行，再按中英文句末標點切；保留標點。"""
    units: list[str] = []
    for i, line in enumerate(block.split("\n")):
        line = line if i == 0 else "\n" + line
        parts = re.split(r"(?<=[。！？…\?\!])", line)
        units.extend(p for p in parts if p)
    return units
