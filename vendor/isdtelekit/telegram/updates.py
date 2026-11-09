"""
Telegram update → Inbound。整個 SDK 只有這裡認得 Telegram update 的形狀。

poller 收到的每個 update、測試造的假 update（testing.text_update／button_update），都從 TelegramEntry.dispatch()
進 dispatcher。沒有文字的照片／檔案編成文字標記交給對話 handler：
    __MEDIA__:photo:<file_id>:          __MEDIA__:document:<file_id>:<檔名>
file_id 之後用同一個 api 的 download_file() 取回。
"""

from __future__ import annotations

import time
from typing import Optional

from isdtelekit.core.channel import TELEGRAM, CallbackInfo, Inbound
from isdtelekit.core.registry import TYPED

MEDIA_PREFIX = "__MEDIA__:"


def parse_update(update: dict) -> Optional[Inbound]:
    """看不懂或不需要處理的 update（沒有文字也沒有附件、沒有寄件人）回傳 None。"""
    callback = update.get("callback_query")
    if callback:
        message = callback.get("message") or {}
        sender = callback.get("from") or {}
        cb = CallbackInfo(
            chat_id=(message.get("chat") or {}).get("id"),
            message_id=message.get("message_id"),
            cq_id=callback.get("id"),
            clicker_id=sender.get("id"),
            data=callback.get("data", "") or "",
            text=message.get("text") or "",
            message_date=message.get("edit_date") or message.get("date"),
        )
        return Inbound(TELEGRAM, user_id=cb.clicker_id, chat_id=cb.chat_id, button=cb,
                       username=sender.get("username", ""), sent_at=time.time())

    message = update.get("message")
    edited = False
    if not message:
        message = update.get("edited_message")
        edited = bool(message)
    if not message:
        return None
    sender = message.get("from", {})
    user_id = sender.get("id")
    if not user_id:
        return None
    text = (message.get("text") or "").strip()
    if not text:
        photo = message.get("photo")
        document = message.get("document")
        if photo and isinstance(photo, list):
            text = f"{MEDIA_PREFIX}photo:{photo[-1].get('file_id')}:"
        elif document and isinstance(document, dict):
            text = f"{MEDIA_PREFIX}document:{document.get('file_id')}:{document.get('file_name') or ''}"
        else:
            return None
    sent = (message.get("edit_date") if edited else None) or message.get("date")
    return Inbound(TELEGRAM, user_id=user_id, chat_id=message["chat"]["id"], text=text,
                   username=sender.get("username", ""), sent_at=float(sent) if sent else None, edited=edited)


def parse_media(text: str):
    """'__MEDIA__:document:<file_id>:<檔名>' → ("document", file_id, 檔名)；不是附件標記回 None。"""
    if not text.startswith(MEDIA_PREFIX):
        return None
    kind, _, rest = text[len(MEDIA_PREFIX):].partition(":")
    file_id, _, name = rest.partition(":")
    return kind, file_id, name


class TelegramEntry:
    """Telegram 的入口：update → Inbound → dispatcher.handle()。"""

    def __init__(self, dispatcher):
        self.dispatcher = dispatcher

    def dispatch(self, api, update: dict, via: str = TYPED):
        """回傳 dispatcher 的 Route；看不懂的 update 回 None。"""
        inbound = parse_update(update)
        if inbound is None:
            return None
        return self.dispatcher.handle(api, inbound, via)
