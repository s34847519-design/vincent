#!/usr/bin/env python3
"""啟動文森特。"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
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

import aiohttp  # noqa: E402
import discord  # noqa: E402

from vincent.bot import VincentClient  # noqa: E402  （要先載入 .env）
from vincent.config import Config  # noqa: E402

log = logging.getLogger("vincent.run")

FIRST_DELAY = 5
MAX_DELAY = 300
STABLE_SECONDS = 120   # 撐過這麼久才算「連上過」，重連間隔歸零


async def serve(cfg: Config) -> None:
    """一直重連，直到你自己關掉它。

    網路斷掉、筆電睡著、Wi-Fi 換了——這些都會讓 Discord 的 gateway 解析失敗並
    往上拋，沒接住的話整個程式就死在那裡，而你只會發現他一整天沒說話。
    """
    delay = FIRST_DELAY
    while True:
        client = VincentClient(cfg, BASE_DIR)
        started = time.monotonic()
        try:
            await client.start(cfg.discord_token)
        except discord.LoginFailure:
            raise SystemExit(
                "DISCORD_BOT_TOKEN 不對。回 Discord Developer Portal → 機器人 → "
                "重設權杖，把新的貼進 .env。"
            )
        except discord.PrivilegedIntentsRequired:
            raise SystemExit(
                "MESSAGE CONTENT INTENT 沒開。Developer Portal → 機器人 → "
                "Privileged Gateway Intents 打開它，再存檔。"
            )
        except (aiohttp.ClientError, OSError, discord.DiscordException) as exc:
            lasted = time.monotonic() - started
            if lasted > STABLE_SECONDS:
                delay = FIRST_DELAY   # 本來好好的，只是斷了一下
            log.warning(
                "連線中斷（%s：%s），%d 秒後重連",
                type(exc).__name__, exc, delay,
            )
        else:
            log.info("連線正常結束")
            return
        finally:
            if not client.is_closed():
                await client.close()

        await asyncio.sleep(delay)
        delay = min(delay * 2, MAX_DELAY)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    cfg = Config.from_env()
    try:
        asyncio.run(serve(cfg))
    except KeyboardInterrupt:
        log.info("收工。")


if __name__ == "__main__":
    main()
