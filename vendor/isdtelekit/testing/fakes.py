"""
FakeChannel：Channel 的假實作，什麼都不送，全部記下來；以及造 Telegram update 的小工具。

    api = FakeChannel()
    dispatcher.handle(api, Inbound("test", 1, 1, "/help"))
    assert "指令選單" in api.last(1)
    api.buttons(1)            # 最後一則有按鈕的訊息上，每顆按鈕的 callback_data
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from isdtelekit.core.richtext import plain


@dataclass
class Sent:
    chat_id: int
    text: str
    reply_markup: Optional[Dict[str, Any]]
    message_id: int
    edits: List[str] = field(default_factory=list)   # 之後被改寫成什麼（最後一個是現在的樣子）

    @property
    def current(self) -> str:
        return self.edits[-1] if self.edits else self.text


class FakeChannel:
    """記下每一則送出去的訊息、改寫、按鈕回應。message_id 從 1 開始遞增。"""

    channel_name = "fake"

    def __init__(self):
        self.sent: List[Sent] = []
        self.answers: List[Optional[str]] = []           # answer_callback_query 跳出的那句（None＝沒有字）
        self.removed: List[Tuple[int, int]] = []         # remove_buttons 的 (chat_id, message_id)
        self.deleted: List[Tuple[int, int]] = []
        self.files: List[Tuple[str, int, Any, str]] = []  # (photo|document|media_group, chat_id, 路徑, caption)

    # ── Channel ──────────────────────────────────────────────────────

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, link_preview=True, **kw):
        message = Sent(chat_id, text, reply_markup, len(self.sent) + 1)
        self.sent.append(message)
        return {"ok": True, "result": {"message_id": message.message_id}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        message = self._message(message_id)
        if message is not None:
            message.edits.append(text)
            if reply_markup is not None:
                message.reply_markup = reply_markup
        return {"ok": True}

    def remove_buttons(self, chat_id, message_id, **kw):
        self.removed.append((chat_id, message_id))
        message = self._message(message_id)
        if message is not None:
            message.reply_markup = None
        return {"ok": True}

    def answer_callback_query(self, callback_query_id, text=None, **kw):
        self.answers.append(text)
        return {"ok": True}

    def send_photo(self, chat_id, photo, caption=""):
        self.files.append(("photo", chat_id, photo, caption))
        return {"ok": True}

    def send_document(self, chat_id, document, caption=""):
        self.files.append(("document", chat_id, document, caption))
        return {"ok": True}

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        self.files.append(("media_group", chat_id, list(photo_paths), caption))
        return {"ok": True}

    def download_file(self, file_id, dest_path):
        return False

    def typing(self, chat_id):
        return None

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
        return {"ok": True}

    # ── 給測試看的 ─────────────────────────────────────────────────────

    def _message(self, message_id: int) -> Optional[Sent]:
        return self.sent[message_id - 1] if 0 < message_id <= len(self.sent) else None

    def to(self, chat_id: Optional[int] = None) -> List[Sent]:
        return [m for m in self.sent if chat_id is None or m.chat_id == chat_id]

    def texts(self, chat_id: Optional[int] = None) -> List[str]:
        """送給 chat_id（沒給就是全部）的每一則，純文字、現在的樣子（改寫過的看最後一次）。"""
        return [plain(m.current) for m in self.to(chat_id)]

    def last(self, chat_id: Optional[int] = None) -> str:
        texts = self.texts(chat_id)
        return texts[-1] if texts else ""

    def text_of(self, message_id: int) -> str:
        message = self._message(message_id)
        return plain(message.current) if message else ""

    def buttons_of(self, message_id: int) -> List[str]:
        message = self._message(message_id)
        markup = (message.reply_markup if message else None) or {}
        return [b.get("callback_data", "") for row in markup.get("inline_keyboard", []) for b in row]

    def buttons(self, chat_id: Optional[int] = None) -> List[str]:
        """送給 chat_id 的最後一則「有按鈕」的訊息上，每顆按鈕的 callback_data。"""
        for message in reversed(self.to(chat_id)):
            if message.reply_markup and message.reply_markup.get("inline_keyboard"):
                return self.buttons_of(message.message_id)
        return []

    def clear(self) -> None:
        self.__init__()


def text_update(user_id: int, text: str, *, chat_id: Optional[int] = None, username: Optional[str] = None,
                date: Optional[float] = None, update_id: int = 1, edited: bool = False) -> dict:
    """一則 Telegram 文字訊息的 update（給 telegram/updates.py 的 TelegramEntry）。chat_id 沒給＝私訊。"""
    message = {"message_id": 1, "from": {"id": user_id, "username": username or f"u{user_id}"},
               "chat": {"id": chat_id if chat_id is not None else user_id}, "text": text,
               "date": int(date if date is not None else time.time())}
    if edited:
        message["edit_date"] = message["date"]
        return {"update_id": update_id, "edited_message": message}
    return {"update_id": update_id, "message": message}


def button_update(user_id: int, data: str, *, message_id: int = 7, chat_id: Optional[int] = None,
                  text: str = "", date: Optional[float] = None, update_id: int = 1) -> dict:
    """按下一顆 inline 按鈕的 update。date＝按鈕所在那則訊息的時間（危險按鈕看它判斷過期）。"""
    return {"update_id": update_id, "callback_query": {
        "id": "cq", "from": {"id": user_id}, "data": data,
        "message": {"message_id": message_id, "chat": {"id": chat_id if chat_id is not None else user_id},
                    "text": text, "date": int(date if date is not None else time.time())}}}
