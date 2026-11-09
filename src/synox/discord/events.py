"""
Discord Gateway 事件 → Inbound（純函式；整個 SYNOX 只有這裡認得 Discord 事件的形狀，像 SDK 的 telegram/updates.py）。

    parsed = parse_event("MESSAGE_CREATE", d, resolve=ids_resolve)
    if parsed: inbound, dm_channel_id = parsed

- parse_event（私訊型 bot）只收**私訊**（沒有 guild_id 的 MESSAGE_CREATE）與私訊裡的按鈕（INTERACTION_CREATE type 3）；
  伺服器頻道的訊息一律略過（不讀、不回）。
- parse_room_event（頻道型 bot，PERM-5）只收 guilds[g].channels 列出的頻道、trigger 命中的訊息（"mention"＝被 @，
  @ 的那段字去掉；"/"＝以 / 開頭），和那些頻道裡的按鈕；私訊、其他頻道、沒觸發的一律略過。
  chat_id 是頻道的內部 id（負號，identity.resolve_room），user_id 是發話的人（同私訊的那個內部 id）。
- 機器人自己（含別的 bot）的訊息略過；沒有文字的訊息（只有附件、貼圖）也略過。
- 私訊：Inbound.chat_id == user_id（內部 id），private_only 指令照常可用；回覆時 DiscordChannel 再把它換回私訊頻道。
- 按鈕：custom_id 就是 Telegram 的 callback_data；cq_id 是 "<interaction id>:<interaction token>"（回應按鈕要用）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from isdtelekit.core.channel import CallbackInfo, Inbound

DISCORD = "discord"
DISCORD_ROOM = "discord-channel"   # identities 裡頻道的通道名（內部 id 是負號）
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


@dataclass
class RoomEvent:
    """頻道裡一則觸發了 bot 的訊息（或一次按鈕）。"""
    inbound: Inbound
    channel_id: str                  # Discord 頻道 id
    guild_id: str
    roles: List[str] = field(default_factory=list)   # 發話者在這個伺服器的身分組 id（member.roles）
    message_id: str = ""             # 觸發的那則訊息（回覆時引用它）
    display_name: str = ""           # 發話者在這個伺服器的顯示名稱（頻道 AI 只當標籤用，PERM-6）
    attachments: List[str] = field(default_factory=list)   # 附件的檔名（頻道 AI 只當資料，不下載）


def display_name_of(d: dict) -> str:
    """伺服器暱稱 → 全域顯示名稱 → 使用者名稱。"""
    member = d.get("member") or {}
    author = d.get("author") or member.get("user") or {}
    for v in (member.get("nick"), author.get("global_name"), author.get("username")):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def strip_mention(text: str, bot_id) -> Optional[str]:
    """訊息裡有 @這個 bot（<@id> 或 <@!id>）→ 去掉那段字後的文字；沒有 → None。"""
    if not bot_id:
        return None                   # 還不知道自己是誰（READY 前）：不認 mention（寧可不回）
    pattern = re.compile(rf"<@!?{re.escape(str(bot_id))}>")
    if not pattern.search(text):
        return None
    return re.sub(r"\s+", " ", pattern.sub(" ", text)).strip()


def parse_room_event(event: str, d: dict, *, spec, resolve: Callable[[str], int],
                     resolve_room: Callable[[str], int], bot_id=None) -> Optional[RoomEvent]:
    """頻道型 bot 的事件 → RoomEvent 或 None（不處理）。spec：BotSpec（guilds、trigger）。
    略過：私訊、沒列的伺服器／頻道、bot（含自己）與系統訊息、只有附件沒有字、沒觸發（沒 @、不是 / 開頭）、編輯過的訊息。"""
    if not isinstance(d, dict):
        return None
    guild_id, channel_id = str(d.get("guild_id") or ""), str(d.get("channel_id") or "")
    if not guild_id or not spec.allows(guild_id, channel_id):
        return None
    member = d.get("member") or {}
    roles = [str(r) for r in (member.get("roles") or []) if isinstance(r, (str, int))]
    if event == "MESSAGE_CREATE":
        author = d.get("author") or {}
        if not author.get("id") or author.get("bot") or author.get("system") or d.get("webhook_id"):
            return None
        if bot_id and str(author["id"]) == str(bot_id):
            return None
        text = str(d.get("content") or "").strip()
        if not text:
            return None
        if spec.trigger == "mention":
            text = strip_mention(text, bot_id)
        elif not text.startswith("/"):
            text = None
        if not text:
            return None
        uid = resolve(str(author["id"]))
        room = resolve_room(channel_id)
        inbound = Inbound(DISCORD, user_id=uid, chat_id=room, text=text, username=author.get("username", ""),
                          sent_at=_epoch(d.get("timestamp")))
        files = [str(a.get("filename") or "") for a in (d.get("attachments") or []) if isinstance(a, dict)]
        return RoomEvent(inbound, channel_id, guild_id, roles, str(d.get("id") or ""),
                         display_name_of(d), [f for f in files if f])
    if event == "INTERACTION_CREATE":
        if d.get("type") != COMPONENT:
            return None
        user = member.get("user") or d.get("user") or {}
        message = d.get("message") or {}
        data = d.get("data") or {}
        if not user.get("id") or user.get("bot") or not message.get("id") or not d.get("id") or not d.get("token"):
            return None
        uid = resolve(str(user["id"]))
        room = resolve_room(channel_id)
        cb = CallbackInfo(chat_id=room, message_id=int(message["id"]), cq_id=f"{d['id']}:{d['token']}",
                          clicker_id=uid, data=str(data.get("custom_id") or ""), text=message.get("content") or "",
                          message_date=_epoch(message.get("edited_timestamp")) or _epoch(message.get("timestamp")))
        inbound = Inbound(DISCORD, user_id=uid, chat_id=room, button=cb, username=user.get("username", ""),
                          sent_at=time.time())
        return RoomEvent(inbound, channel_id, guild_id, roles, str(message["id"]))
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
