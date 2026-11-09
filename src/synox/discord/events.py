"""
Discord Gateway 事件 → Inbound（純函式；整個 SYNOX 只有這裡認得 Discord 事件的形狀，像 SDK 的 telegram/updates.py）。

    parsed = parse_event("MESSAGE_CREATE", d, resolve=ids_resolve)
    if parsed: inbound, dm_channel_id = parsed

- 最小版只收**私訊**（沒有 guild_id 的 MESSAGE_CREATE）與私訊裡的按鈕（INTERACTION_CREATE type 3）；
  伺服器頻道的訊息一律略過（不讀、不回）。
- 機器人自己（含別的 bot）的訊息略過；沒有文字的訊息（只有附件、貼圖）也略過。
- 私訊：Inbound.chat_id == user_id（內部 id），private_only 指令照常可用；回覆時 DiscordChannel 再把它換回私訊頻道。
- 按鈕：custom_id 就是 Telegram 的 callback_data；cq_id 是 "<interaction id>:<interaction token>"（回應按鈕要用）。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Callable, Optional, Tuple

from isdtelekit.core.channel import CallbackInfo, Inbound

DISCORD = "discord"
COMPONENT = 3          # INTERACTION_CREATE 的 type：按了訊息上的元件（按鈕）


def _epoch(stamp) -> Optional[float]:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_event(event: str, d: dict, resolve: Callable[[str], int]) -> Optional[Tuple[Inbound, str]]:
    """(Inbound, 私訊頻道 id) 或 None（不處理的事件）。resolve：Discord user id（字串）→ 內部 id。"""
    if not isinstance(d, dict):
        return None
    if event in ("MESSAGE_CREATE", "MESSAGE_UPDATE"):
        if d.get("guild_id"):
            return None
        author = d.get("author") or {}
        if not author.get("id") or author.get("bot") or author.get("system"):
            return None
        text = str(d.get("content") or "").strip()
        if not text or not d.get("channel_id"):
            return None
        edited = event == "MESSAGE_UPDATE"
        uid = resolve(str(author["id"]))
        sent = _epoch(d.get("edited_timestamp") if edited else None) or _epoch(d.get("timestamp"))
        return (Inbound(DISCORD, user_id=uid, chat_id=uid, text=text, username=author.get("username", ""),
                        sent_at=sent, edited=edited), str(d["channel_id"]))
    if event == "INTERACTION_CREATE":
        if d.get("type") != COMPONENT or d.get("guild_id"):
            return None
        user = d.get("user") or (d.get("member") or {}).get("user") or {}
        message = d.get("message") or {}
        data = d.get("data") or {}
        if not user.get("id") or user.get("bot") or not message.get("id") or not d.get("id") or not d.get("token"):
            return None
        uid = resolve(str(user["id"]))
        channel_id = str(d.get("channel_id") or message.get("channel_id") or "")
        cb = CallbackInfo(chat_id=uid, message_id=int(message["id"]), cq_id=f"{d['id']}:{d['token']}",
                          clicker_id=uid, data=str(data.get("custom_id") or ""), text=message.get("content") or "",
                          message_date=_epoch(message.get("edited_timestamp")) or _epoch(message.get("timestamp")))
        return (Inbound(DISCORD, user_id=uid, chat_id=uid, button=cb, username=user.get("username", ""),
                        sent_at=time.time()), channel_id)
    return None


def pairing_sender(event: str, d: dict, code: str) -> Optional[dict]:
    """這個事件是不是「私訊傳了配對碼」（照 wizard/telegram_probe.matches）；是的話回 {"id", "username", "channel_id"}。"""
    if event != "MESSAGE_CREATE" or not isinstance(d, dict) or d.get("guild_id"):
        return None
    author = d.get("author") or {}
    text = "".join(str(d.get("content") or "").split())
    if text == code and author.get("id") and not author.get("bot"):
        return {"id": str(author["id"]), "username": author.get("username", ""),
                "channel_id": str(d.get("channel_id") or "")}
    return None
