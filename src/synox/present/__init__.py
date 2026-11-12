"""
呈現層：與通道無關的內容區塊模型（docs/presentation.md）。

    來源（Markdown、純文字、系統產生的卡片）──來源 adapter──▶ 區塊清單 ──輸出 adapter──▶ Telegram／Discord／網頁

    from synox import present
    chunks = present.render("**好了**，共 3 筆", "telegram")      # → [Chunk(Html("<b>好了</b>，共 3 筆"))]
    present.deliver(app, api, chat_id, text)                       # AI 回覆送出（config presentation.enabled）

- blocks.py（資料型別、信任等級）、markdown.py（Markdown／純文字 → 區塊）、telegram.py／discord.py／web.py（輸出）、
  split.py（切訊息）、tables.py（表格降級）、width.py（顯示寬度、UTF-16 長度）。
- 開關：config.json `"presentation": {"enabled": false}`（預設關）。關著的時候 `deliver` 就是原本的
  `api.send_message(chat_id, text)`，一個位元組都不變。只接 AI 回覆這一條（agent/loop.py、agent/room.py 的 say）。
"""

from __future__ import annotations

import logging
from typing import List, Union

from isdtelekit.core.richtext import plain

from synox.present import discord as discord_out
from synox.present import telegram as telegram_out
from synox.present import web as web_out
from synox.present.blocks import ASSISTANT, EXTERNAL, SYSTEM, Chunk, Document, check_trust
from synox.present.markdown import from_plain
from synox.present.markdown import parse as parse_markdown

TELEGRAM, DISCORD, WEB = "telegram", "discord", "web"
CHANNELS = (TELEGRAM, DISCORD, WEB)
SOURCES = ("markdown", "plain")

__all__ = ["ASSISTANT", "CHANNELS", "Chunk", "Document", "EXTERNAL", "SYSTEM", "deliver", "document", "enabled",
           "render"]


def document(text: str, *, trust: str = ASSISTANT, source: str = "markdown") -> Document:
    """來源 adapter：Markdown（預設）或純文字 → Document。"""
    check_trust(trust)
    if source == "plain":
        return from_plain(text, trust)
    if source != "markdown":
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    return parse_markdown(text, trust)


def render(content: Union[str, Document], channel: str, *, trust: str = ASSISTANT,
           source: str = "markdown") -> List[Chunk]:
    """一段內容 → 這個通道的一則或幾則訊息（Chunk.text 照通道的格式；按鈕只在最後一則）。
    content 可以是字串（照 source 解析）或已經組好的 Document（程式產生的卡片；trust 以 Document 的為準）。"""
    doc = content if isinstance(content, Document) else document(content, trust=trust, source=source)
    if channel == TELEGRAM:
        return telegram_out.render(doc)
    if channel == DISCORD:
        return discord_out.render(doc)
    if channel == WEB:
        text = content if isinstance(content, str) else \
            "\n\n".join(plain(c.text) for c in telegram_out.render(doc))
        return web_out.render(doc, text)
    raise ValueError(f"channel must be one of {CHANNELS}, got {channel!r}")


def enabled(app) -> bool:
    """config.json 的 presentation.enabled（沒有這一塊、或不是 SYNOX 的設定＝關）。"""
    config = getattr(app, "config", app)
    settings = getattr(config, "presentation", None)
    return isinstance(settings, dict) and settings.get("enabled") is True


def deliver(app, api, chat_id: int, text: str, *, trust: str = ASSISTANT) -> None:
    """送出一段 AI 回覆。開關關著（預設）＝原本的 api.send_message(chat_id, text)，一個位元組都不變；
    開著＝依 api.channel_name 選輸出 adapter，一則一則送。沒有 adapter 的通道（本機畫面、測試的假通道）照原樣送；
    畫的時候出錯也照原樣送（記一行 log），不會因為格式讓回覆不見。"""
    if not enabled(app):
        api.send_message(chat_id, text)
        return
    channel = str(getattr(api, "channel_name", "") or "")
    if channel not in CHANNELS:
        api.send_message(chat_id, text)
        return
    try:
        chunks = render(text, channel, trust=trust)
    except Exception:
        logging.exception("[PRESENT] render failed for %s; sending the original text", channel)
        api.send_message(chat_id, text)
        return
    for chunk in chunks:
        if chunk.reply_markup:
            api.send_message(chat_id, chunk.text, reply_markup=chunk.reply_markup)
        else:
            api.send_message(chat_id, chunk.text)
