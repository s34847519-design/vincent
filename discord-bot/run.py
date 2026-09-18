#!/usr/bin/env python3
"""啟動文森特。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

if sys.version_info < (3, 10):
    raise SystemExit(
        f"你的 Python 是 {sys.version.split()[0]}，太舊了。\n"
        "anthropic 1.x 和 python-dotenv 都要 3.10 以上。\n"
        "去 python.org 裝 3.12，安裝畫面最下面的 "
        "「Add python.exe to PATH」記得勾。"
    )

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

from vincent.bot import VincentClient  # noqa: E402  （要先載入 .env）
from vincent.config import Config  # noqa: E402


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("discord").setLevel(logging.WARNING)

    cfg = Config.from_env()
    VincentClient(cfg, BASE_DIR).run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
