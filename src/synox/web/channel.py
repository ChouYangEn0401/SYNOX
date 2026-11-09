"""
WebChannel：SDK 的 Channel 介面（照 host/console.py 的 ConsoleChannel），把回覆寫進網頁的對話紀錄。

    api = WebChannel(store, tg_id=42, chat="c3", home=app.home)
    app.dispatcher.handle(api, Inbound(WEB, 42, 42, "/money_month"))

- 送給「這個人自己」（chat_id == tg_id，私訊）的訊息 → 存成這段對話的一則 bot 訊息；inline 按鈕原樣存
  （網頁畫成按鈕，按下時 callback_data 經 dispatcher.handle(…, button=…) 送回來，跟 Telegram 一樣先 authorize）。
- 送給別人的（例如升級申請通知管理員）→ 交給 app.home（Telegram），不寫進這個人的網頁。
- edit_message_text／remove_buttons／delete_message 改同一則（message id 是這個人的對話紀錄裡的 id）。
- answer_callback_query 的那句 → 一則小字（from="note"）。
- 圖片、檔案：v1 只記一行「〔圖片〕說明」，網頁不提供下載。
"""

from __future__ import annotations

from typing import Optional

from isdtelekit.core.richtext import plain

from synox.web.chats import ChatStore, markup_rows

WEB = "web"


class WebChannel:

    channel_name = WEB

    def __init__(self, store: ChatStore, tg_id: int, chat: str, home=None):
        self.store = store
        self.tg_id = int(tg_id)
        self.chat = chat
        self.home = home

    def _mine(self, chat_id) -> bool:
        try:
            return int(chat_id) == self.tg_id
        except (TypeError, ValueError):
            return False

    def _forward(self, method: str, *args, **kw):
        fn = getattr(self.home, method, None) if self.home is not None else None
        if fn is None:
            return {"ok": False}
        try:
            return fn(*args, **kw)
        except Exception:
            return {"ok": False}

    # ── Channel ──────────────────────────────────────────────────────

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, link_preview=True, **kw):
        if not self._mine(chat_id):
            if reply_markup is not None:
                return self._forward("send_message", chat_id, text, reply_markup=reply_markup)
            return self._forward("send_message", chat_id, text)
        msg = self.store.append(self.tg_id, self.chat, "bot", plain(text), markup_rows(reply_markup))
        return {"ok": True, "result": {"message_id": msg["id"]}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        if not self._mine(chat_id):
            return self._forward("edit_message_text", chat_id, message_id, text, reply_markup=reply_markup)
        if reply_markup is None:
            ok = self.store.edit(self.tg_id, int(message_id), plain(text))
        else:
            ok = self.store.edit(self.tg_id, int(message_id), plain(text), markup_rows(reply_markup))
        return {"ok": ok}

    def remove_buttons(self, chat_id, message_id, **kw):
        if not self._mine(chat_id):
            return self._forward("remove_buttons", chat_id, message_id)
        return {"ok": self.store.edit(self.tg_id, int(message_id), buttons=[])}

    def delete_message(self, chat_id, message_id):
        if not self._mine(chat_id):
            return self._forward("delete_message", chat_id, message_id)
        return {"ok": self.store.edit(self.tg_id, int(message_id), deleted=True)}

    def answer_callback_query(self, callback_query_id, text: Optional[str] = None, **kw):
        if text:
            self.store.append(self.tg_id, self.chat, "note", plain(text))
        return {"ok": True}

    def _file(self, chat_id, label: str, caption: str):
        if not self._mine(chat_id):
            return {"ok": False}
        self.store.append(self.tg_id, self.chat, "bot", f"〔{label}〕{plain(caption or '')}".strip())
        return {"ok": True}

    def send_photo(self, chat_id, photo, caption=""):
        if not self._mine(chat_id):
            return self._forward("send_photo", chat_id, photo, caption=caption)
        return self._file(chat_id, "圖片（網頁版還不能看圖，請到 Telegram 看）", caption)

    def send_document(self, chat_id, document, caption=""):
        if not self._mine(chat_id):
            return self._forward("send_document", chat_id, document, caption=caption)
        return self._file(chat_id, "檔案（網頁版還不能下載，請到 Telegram 拿）", caption)

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        if not self._mine(chat_id):
            return self._forward("send_media_group", chat_id, photo_paths, caption, kind)
        return self._file(chat_id, f"{len(photo_paths)} 個檔案（請到 Telegram 看）", caption)

    def download_file(self, file_id, dest_path):
        return False

    def typing(self, chat_id):
        return None

    def pin_message(self, *a, **kw):
        return {"ok": True}

    def unpin_message(self, *a, **kw):
        return {"ok": True}
