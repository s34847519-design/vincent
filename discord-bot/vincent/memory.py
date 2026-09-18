"""SQLite 對話記憶：最近訊息原文 + 更早的滾動摘要 + 手動筆記。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    role      TEXT    NOT NULL,          -- 'user' | 'assistant'
    content   TEXT    NOT NULL,
    ts        TEXT    NOT NULL,          -- ISO-8601, UTC
    initiated INTEGER NOT NULL DEFAULT 0 -- 1 = 這則是他主動開口
);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);

CREATE TABLE IF NOT EXISTS summaries (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    upto_id  INTEGER NOT NULL,           -- 摘要涵蓋到哪一則 message.id
    text     TEXT    NOT NULL,
    ts       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    ts   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Message:
    id: int
    role: str
    content: str
    ts: datetime
    initiated: bool


class Memory:
    """所有 SQLite 操作都丟到執行緒去跑，不擋住 discord.py 的 event loop。"""

    def __init__(self, db_path: str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(fn, *args)

    # ── 寫入 ──────────────────────────────────────────

    async def add(self, role: str, content: str, *, initiated: bool = False) -> int:
        def work() -> int:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO messages (role, content, ts, initiated) VALUES (?, ?, ?, ?)",
                    (role, content, _now_iso(), int(initiated)),
                )
                return int(cur.lastrowid)

        return await self._run(work)

    async def add_note(self, text: str) -> None:
        def work() -> None:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO notes (text, ts) VALUES (?, ?)", (text, _now_iso())
                )

        await self._run(work)

    async def add_summary(self, upto_id: int, text: str) -> None:
        def work() -> None:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO summaries (upto_id, text, ts) VALUES (?, ?, ?)",
                    (upto_id, text, _now_iso()),
                )

        await self._run(work)

    async def set_state(self, key: str, value) -> None:
        def work() -> None:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO state (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )

        await self._run(work)

    async def add_spend(self, day: str, amount: float) -> None:
        """把一次呼叫的估算花費累加到當天，並累加到總額。"""

        def work() -> None:
            with self._connect() as conn:
                for key in (f"spend:{day}", "spend:total"):
                    row = conn.execute(
                        "SELECT value FROM state WHERE key = ?", (key,)
                    ).fetchone()
                    current = json.loads(row["value"]) if row else 0.0
                    conn.execute(
                        "INSERT INTO state (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, json.dumps(round(current + amount, 6))),
                    )

        await self._run(work)

    # ── 讀取 ──────────────────────────────────────────

    async def get_state(self, key: str, default=None):
        def work():
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM state WHERE key = ?", (key,)
                ).fetchone()
            return json.loads(row["value"]) if row else default

        return await self._run(work)

    async def recent(self, limit: int) -> list[Message]:
        """最近 N 則，由舊到新。只回摘要還沒吃掉的部分。"""

        def work() -> list[Message]:
            with self._connect() as conn:
                floor = conn.execute(
                    "SELECT COALESCE(MAX(upto_id), 0) AS f FROM summaries"
                ).fetchone()["f"]
                rows = conn.execute(
                    "SELECT * FROM messages WHERE id > ? ORDER BY id DESC LIMIT ?",
                    (floor, limit),
                ).fetchall()
            return [_row_to_message(r) for r in reversed(rows)]

        return await self._run(work)

    async def summary_text(self) -> str:
        def work() -> str:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT text FROM summaries ORDER BY id DESC LIMIT 1"
                ).fetchone()
            return row["text"] if row else ""

        return await self._run(work)

    async def notes_text(self, limit: int = 60) -> str:
        def work() -> str:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT text FROM notes ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return "\n".join(f"- {r['text']}" for r in reversed(rows))

        return await self._run(work)

    async def last_message(self) -> Message | None:
        return await self._last(None)

    async def last_user_message(self) -> Message | None:
        return await self._last("user")

    async def _last(self, role: str | None) -> Message | None:
        def work() -> Message | None:
            sql = "SELECT * FROM messages"
            args: tuple = ()
            if role:
                sql += " WHERE role = ?"
                args = (role,)
            sql += " ORDER BY id DESC LIMIT 1"
            with self._connect() as conn:
                row = conn.execute(sql, args).fetchone()
            return _row_to_message(row) if row else None

        return await self._run(work)

    async def initiated_count_since(self, since: datetime) -> int:
        def work() -> int:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM messages "
                    "WHERE initiated = 1 AND ts >= ?",
                    (since.astimezone(timezone.utc).isoformat(),),
                ).fetchone()
            return int(row["n"])

        return await self._run(work)

    async def stats(self) -> dict:
        def work() -> dict:
            with self._connect() as conn:
                total = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
                initiated = conn.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE initiated = 1"
                ).fetchone()["n"]
                summaries = conn.execute("SELECT COUNT(*) AS n FROM summaries").fetchone()["n"]
                notes = conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
                first = conn.execute(
                    "SELECT ts FROM messages ORDER BY id ASC LIMIT 1"
                ).fetchone()
            return {
                "messages": total,
                "initiated": initiated,
                "summaries": summaries,
                "notes": notes,
                "since": first["ts"] if first else None,
            }

        return await self._run(work)

    # ── 壓縮 ──────────────────────────────────────────

    async def overflow(self, keep: int) -> tuple[list[Message], int]:
        """回傳「超出保留視窗、該被壓成摘要」的那批訊息，以及它的最後一個 id。"""

        def work() -> tuple[list[Message], int]:
            with self._connect() as conn:
                floor = conn.execute(
                    "SELECT COALESCE(MAX(upto_id), 0) AS f FROM summaries"
                ).fetchone()["f"]
                live = conn.execute(
                    "SELECT COUNT(*) AS n FROM messages WHERE id > ?", (floor,)
                ).fetchone()["n"]
                excess = live - keep
                if excess <= 0:
                    return [], 0
                rows = conn.execute(
                    "SELECT * FROM messages WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (floor, excess),
                ).fetchall()
            msgs = [_row_to_message(r) for r in rows]
            return msgs, (msgs[-1].id if msgs else 0)

        return await self._run(work)


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=int(row["id"]),
        role=row["role"],
        content=row["content"],
        ts=datetime.fromisoformat(row["ts"]),
        initiated=bool(row["initiated"]),
    )
