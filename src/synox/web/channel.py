"""
WebChannel：SDK 的 Channel 介面（照 host/console.py 的 ConsoleChannel），把回覆寫進網頁的對話紀錄。

    api = WebChannel(store, tg_id=42, chat="c3", home=app.home)
    app.dispatcher.handle(api, Inbound(WEB, 42, 42, "/money_month"))

- 送給「這個人自己」（chat_id == tg_id，私訊）的訊息 → 存成這段對話的一則 bot 訊息；inline 按鈕原樣存
  （網頁畫成按鈕，按下時 callback_data 經 dispatcher.handle(…, button=…) 送回來，跟 Telegram 一樣先 authorize）。
  text 帶 `.blocks`（呈現層的 synox.present.web.WebText，config presentation.enabled 開著時的 AI 回覆）→ 一起存，
  網頁照區塊畫；一般字串沒有 blocks，存的東西跟以前一樣。
- 送給別人的（例如升級申請通知管理員）→ 交給 app.home（Telegram），不寫進這個人的網頁。
- edit_message_text／remove_buttons／delete_message 改同一則（message id 是這個人的對話紀錄裡的 id）。
- answer_callback_query 的那句 → 一則小字（from="note"）。
- 圖片（docs/sdk.md「回覆帶圖」）：send_image(chat_id, images, caption, reply_markup) 存成一則帶圖的 bot 訊息
  （synox/web/chatmedia.py 檢查類型、大小，SVG 照白名單重寫；存在 store.media），網頁用 <img> 畫在泡泡裡；
  edit_image 換掉同一則的圖、字、按鈕（例如「下一個按法」）。send_photo／send_media_group 收本機圖檔路徑，走同一條路；
  圖不收（不是圖、太大…）＝退回以前的一行「〔圖片〕說明」。
- 檔案：v1 只記一行「〔檔案〕說明」，網頁不提供下載。
"""

from __future__ import annotations

import os
from typing import Optional

import re

from isdtelekit.core.richtext import Html, plain

from synox.web.chats import ChatStore, markup_rows

WEB = "web"


_PRE = re.compile(r"<pre(?:\s[^>]*)?>(.*?)</pre>", re.S | re.I)


def html_blocks(text):
    """工具送的 richtext.Html 裡有 <pre>（等寬區塊，例如 TAB 譜）：網頁照區塊畫（段落＋程式碼區塊），等寬對得齊。
    沒有 <pre> 的 Html、一般字串＝None（照舊純文字）。區塊的信任等級一律 external（工具的輸出），內容都是純文字。"""
    if not isinstance(text, Html) or not _PRE.search(text):
        return None
    out, prev = [], 0
    for m in _PRE.finditer(text):
        before = plain(Html(text[prev:m.start()])).strip("\n")
        if before.strip():
            out.append({"type": "paragraph", "trust": "external", "spans": [{"text": before}]})
        out.append({"type": "code", "trust": "external", "code": plain(Html(m.group(1))).strip("\n")})
        prev = m.end()
    after = plain(Html(text[prev:])).strip("\n")
    if after.strip():
        out.append({"type": "paragraph", "trust": "external", "spans": [{"text": after}]})
    return out


class WebChannel:

    channel_name = WEB

    def __init__(self, store: ChatStore, tg_id: int, chat: str, home=None):
        self.store = store
        self.tg_id = int(tg_id)
        self.chat = chat
        self.home = home

    @property
    def thread(self) -> str:
        """這是網頁的哪一段對話（AI 的記憶每一段各自一份：agent/loop.py memory_key）。"""
        return self.chat

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
        msg = self.store.append(self.tg_id, self.chat, "bot", plain(text), markup_rows(reply_markup),
                                blocks=getattr(text, "blocks", None) or html_blocks(text))
        return {"ok": True, "result": {"message_id": msg["id"]}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        if not self._mine(chat_id):
            return self._forward("edit_message_text", chat_id, message_id, text, reply_markup=reply_markup)
        blocks = getattr(text, "blocks", None) or html_blocks(text)   # /help 換頁的卡片也帶區塊（synox/helpui）
        if reply_markup is None:
            ok = self.store.edit(self.tg_id, int(message_id), plain(text), blocks=blocks)
        else:
            ok = self.store.edit(self.tg_id, int(message_id), plain(text), markup_rows(reply_markup), blocks=blocks)
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

    def _store_images(self, images):
        """(要存進訊息的 images 中繼資料, 不收的原因)。沒有 media 存放處＝全部不收。"""
        from synox.web import chatmedia
        media = getattr(self.store, "media", None)
        if media is None:
            return [], ["這裡不能存圖。"]
        prepared, problems = chatmedia.prepare(images)
        return [p.meta(media.put(self.tg_id, p)) for p in prepared], problems

    def send_image(self, chat_id, images, caption="", reply_markup=None, **kw):
        """一則帶圖的訊息（圖在字的下面）。全部不收＝{"ok": False, "error": …}，什麼都不存（呼叫的人自己退回文字）。"""
        if not self._mine(chat_id):
            return {"ok": False, "error": "只能傳給自己的對話"}
        metas, problems = self._store_images(images)
        if not metas:
            return {"ok": False, "error": "；".join(problems) or "沒有圖"}
        msg = self.store.append(self.tg_id, self.chat, "bot", plain(caption or ""), markup_rows(reply_markup),
                                images=metas)
        return {"ok": True, "result": {"message_id": msg["id"]}, "refused": problems}

    def edit_image(self, chat_id, message_id, images, caption=None, reply_markup=None, **kw):
        """換掉同一則訊息的圖（caption／reply_markup 給了才換）。圖全部不收＝不改、回 ok False。"""
        if not self._mine(chat_id):
            return {"ok": False, "error": "只能改自己的對話"}
        metas, problems = self._store_images(images)
        if not metas:
            return {"ok": False, "error": "；".join(problems) or "沒有圖"}
        kwargs = {"images": metas}
        if caption is not None:
            kwargs["text"] = plain(caption)
        if reply_markup is not None:
            kwargs["buttons"] = markup_rows(reply_markup)
        ok = self.store.edit(self.tg_id, int(message_id), **kwargs)
        if not ok:
            media = getattr(self.store, "media", None)
            if media is not None:
                media.drop(self.tg_id, [m["id"] for m in metas])
        return {"ok": ok}

    @staticmethod
    def _read_path(path, limit: int):
        try:
            if not isinstance(path, str) or not os.path.isfile(path) or os.path.getsize(path) > limit:
                return None
            with open(path, "rb") as f:
                return f.read(limit + 1)
        except OSError:
            return None

    def _photos(self, chat_id, paths, caption):
        from synox.web.chatmedia import MAX_BYTES, MAX_IMAGES
        datas = [d for d in (self._read_path(p, MAX_BYTES) for p in list(paths or [])[:MAX_IMAGES]) if d]
        if not datas:
            return {"ok": False}
        return self.send_image(chat_id, [{"data": d, "alt": plain(caption or "")} for d in datas], caption)

    def _file(self, chat_id, label: str, caption: str):
        if not self._mine(chat_id):
            return {"ok": False}
        self.store.append(self.tg_id, self.chat, "bot", f"〔{label}〕{plain(caption or '')}".strip())
        return {"ok": True}

    def send_photo(self, chat_id, photo, caption=""):
        if not self._mine(chat_id):
            return self._forward("send_photo", chat_id, photo, caption=caption)
        sent = self._photos(chat_id, [photo], caption)
        if sent.get("ok"):
            return sent
        return self._file(chat_id, "圖片（網頁版還不能看圖，請到 Telegram 看）", caption)

    def send_document(self, chat_id, document, caption=""):
        if not self._mine(chat_id):
            return self._forward("send_document", chat_id, document, caption=caption)
        return self._file(chat_id, "檔案（網頁版還不能下載，請到 Telegram 拿）", caption)

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        if not self._mine(chat_id):
            return self._forward("send_media_group", chat_id, photo_paths, caption, kind)
        if kind == "photo":
            sent = self._photos(chat_id, photo_paths, caption)
            if sent.get("ok"):
                return sent
        return self._file(chat_id, f"{len(photo_paths)} 個檔案（請到 Telegram 看）", caption)

    def download_file(self, file_id, dest_path):
        return False

    def typing(self, chat_id):
        return None

    def pin_message(self, *a, **kw):
        return {"ok": True}

    def unpin_message(self, *a, **kw):
        return {"ok": True}
