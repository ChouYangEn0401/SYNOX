"""
網頁對話頁的紀錄：每個人一份，裡面好幾段對話，每段只留最近 KEEP 則。

    {"rev": 12, "next_id": 9, "chats": [
        {"id": "c3", "title": "幫我記一筆…", "created": …, "updated": …,
         "messages": [{"id": 7, "rev": 11, "from": "me"|"bot"|"note", "text": "…",
                       "buttons": [[{"text": "✅ 執行", "data": "agent_ok:go:…"}]], "at": …}]}]}

- "blocks"（選配）：呈現層的區塊（synox/present/web.py 的 wire；config presentation.enabled 開著時 AI 回覆才有），
  網頁用 static/blocks.js 畫；text 仍是原本的文字（預覽、常駐助理讀的都是它）。改字或刪掉時一起拿掉。

- 檔案：有保管箱 → data/web_chats/<tg_id>.json.enc（那個人的金鑰，vault.for_user(id).at(...)）；
  沒有保管箱 → data/web_chats/<tg_id>.json。
- 封存：chat 多一個 "archived"（封存的時間）。封存的對話不出現在側欄、不算在 MAX_CHATS 裡（不會被擠掉）、不能再傳訊息；
  可以還原，或到「已封存」頁徹底刪除（只有封存過的才能刪；刪掉就沒了）。固定的兩段（工具頁、常駐助理）不能封存。
- message id 在這個人的所有對話裡唯一（按鈕送回來時用它找回那則訊息）。
- rev：每次新增或改一則訊息就 +1，那則訊息記下新的 rev；網頁每 2 秒問「rev 比 N 新的有哪些」（events）。
- 記憶體快取一份，寫入時同步存檔（每 2 秒的輪詢不用每次解密）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from isdtelekit.core import jsonstore

KEEP = 50
MAX_CHATS = 30
TOOLS_CHAT = "tools"
MOTHER_CHAT = "mother"             # 跟常駐助理（母 session）聊天的固定那一段（只有擁有者；不算一般對話、不會被擠掉）
PINNED = (TOOLS_CHAT, MOTHER_CHAT)
_KEEP_BUTTONS = object()


def markup_rows(reply_markup) -> List[List[dict]]:
    """Telegram 形狀的 reply_markup → [[{"text", "data"} 或 {"text", "url"}]]（只收 http/https 網址）。"""
    rows = []
    for row in (reply_markup or {}).get("inline_keyboard") or []:
        out = []
        for b in row or []:
            if not isinstance(b, dict):
                continue
            text = str(b.get("text", ""))[:64]
            if b.get("callback_data"):
                out.append({"text": text, "data": str(b["callback_data"])[:256]})
            elif str(b.get("url", "")).startswith(("http://", "https://")):
                out.append({"text": text, "url": str(b["url"])[:2000]})
        if out:
            rows.append(out)
    return rows


class ChatStore:

    def __init__(self, folder: str, vault=None, clock: Callable[[], float] = time.time, keep: int = KEEP):
        self.folder = folder
        self._vault = vault
        self._clock = clock
        self.keep = keep
        self._lock = threading.RLock()
        self._cache: Dict[int, dict] = {}

    # ── 檔案 ─────────────────────────────────────────────────────────

    def _user_vault(self, tg_id: int):
        return self._vault.for_user(tg_id).at(self.folder) if self._vault is not None else None

    def path(self, tg_id: int) -> str:
        vault = self._user_vault(tg_id)
        return vault.path(str(int(tg_id))) if vault is not None else os.path.join(self.folder, f"{int(tg_id)}.json")

    def _data(self, tg_id: int) -> dict:
        tg_id = int(tg_id)
        data = self._cache.get(tg_id)
        if data is None:
            vault = self._user_vault(tg_id)
            if vault is not None:
                data = vault.load_json(str(tg_id), None)
            else:
                data = jsonstore.load_json(self.path(tg_id), None)
            if not isinstance(data, dict):
                data = {"rev": 0, "next_id": 1, "chats": []}
            self._cache[tg_id] = data
        return data

    def _save(self, tg_id: int) -> None:
        data = self._cache[int(tg_id)]
        os.makedirs(self.folder, exist_ok=True)
        vault = self._user_vault(tg_id)
        if vault is not None:
            vault.save_json(str(int(tg_id)), data)
        else:
            jsonstore.save_json(self.path(tg_id), data)

    # ── 對話 ─────────────────────────────────────────────────────────

    def list_chats(self, tg_id: int, archived: bool = False) -> List[dict]:
        """archived=False：側欄的對話（沒封存的）；True：已封存的（最近封存的在前面）。"""
        with self._lock:
            chats = [c for c in self._data(tg_id)["chats"] if bool(c.get("archived")) == archived]
            key = (lambda c: -c.get("archived", 0)) if archived else (lambda c: -c.get("updated", 0))
            out = []
            for c in sorted(chats, key=key):
                last = c["messages"][-1]["text"][:60] if c["messages"] else ""
                row = {"id": c["id"], "title": c["title"], "updated": c.get("updated", 0),
                       "count": len(c["messages"]), "last": last}
                if archived:
                    row["archived"] = c.get("archived", 0)
                out.append(row)
            return out

    def archived_count(self, tg_id: int) -> int:
        with self._lock:
            return sum(1 for c in self._data(tg_id)["chats"] if c.get("archived"))

    def archive(self, tg_id: int, chat_id: str) -> bool:
        """封存一段對話（從側欄拿掉，資料還在）。固定的段、不存在的、已經封存的＝False。"""
        with self._lock:
            chat = self.get(tg_id, chat_id)
            if chat is None or chat_id in PINNED or chat.get("archived"):
                return False
            chat["archived"] = self._clock()
            self._save(tg_id)
            return True

    def restore(self, tg_id: int, chat_id: str) -> bool:
        """把封存的對話放回側欄。不存在或沒封存＝False。"""
        with self._lock:
            chat = self.get(tg_id, chat_id)
            if chat is None or not chat.get("archived"):
                return False
            del chat["archived"]
            chat["updated"] = self._clock()                 # 放回去就是最近用的
            self._save(tg_id)
            return True

    def delete_archived(self, tg_id: int, chat_id: str) -> bool:
        """徹底刪除：只有已封存的才刪（要先封存），刪了就沒了。"""
        with self._lock:
            chat = self.get(tg_id, chat_id)
            if chat is None or not chat.get("archived"):
                return False
            self._data(tg_id)["chats"].remove(chat)
            self._save(tg_id)
            return True

    def get(self, tg_id: int, chat_id: str) -> Optional[dict]:
        with self._lock:
            return next((c for c in self._data(tg_id)["chats"] if c["id"] == chat_id), None)

    def new_chat(self, tg_id: int, title: str = "新對話", chat_id: Optional[str] = None) -> dict:
        with self._lock:
            data = self._data(tg_id)
            if chat_id is None:
                n = data.get("next_chat", 1)
                data["next_chat"] = n + 1
                chat_id = f"c{n}"
            now = self._clock()
            chat = {"id": chat_id, "title": title, "created": now, "updated": now, "messages": []}
            data["chats"].append(chat)
            # 太多段就丟掉最久沒動的（工具頁那段不丟）
            normal = sorted((c for c in data["chats"] if c["id"] not in PINNED and not c.get("archived")),
                            key=lambda c: c.get("updated", 0))
            for old in normal[:max(0, len(normal) - MAX_CHATS)]:
                data["chats"].remove(old)
            self._save(tg_id)
            return chat

    def ensure(self, tg_id: int, chat_id: str, title: str) -> dict:
        with self._lock:
            return self.get(tg_id, chat_id) or self.new_chat(tg_id, title, chat_id)

    def clear(self, tg_id: int, chat_id: str) -> None:
        """清空這一段的訊息（段本身留著）。"""
        with self._lock:
            chat = self.get(tg_id, chat_id)
            if chat is not None and chat["messages"]:
                data = self._data(tg_id)
                data["rev"] = int(data.get("rev", 0)) + 1
                chat["messages"] = []
                self._save(tg_id)

    def rev(self, tg_id: int) -> int:
        with self._lock:
            return int(self._data(tg_id).get("rev", 0))

    # ── 訊息 ─────────────────────────────────────────────────────────

    def append(self, tg_id: int, chat_id: str, who: str, text: str, buttons=None, blocks=None) -> dict:
        with self._lock:
            data = self._data(tg_id)
            chat = self.get(tg_id, chat_id)
            if chat is None:
                raise KeyError(chat_id)
            data["rev"] = int(data.get("rev", 0)) + 1
            msg = {"id": int(data.get("next_id", 1)), "rev": data["rev"], "from": who, "text": str(text),
                   "buttons": buttons or [], "at": self._clock()}
            if blocks:
                msg["blocks"] = list(blocks)
            data["next_id"] = msg["id"] + 1
            chat["messages"].append(msg)
            del chat["messages"][:max(0, len(chat["messages"]) - self.keep)]
            chat["updated"] = msg["at"]
            if who == "me" and chat.get("title") == "新對話" and text.strip():
                chat["title"] = text.strip().splitlines()[0][:24]
            self._save(tg_id)
            return dict(msg)

    def find(self, tg_id: int, message_id: int) -> Tuple[Optional[dict], Optional[dict]]:
        with self._lock:
            for chat in self._data(tg_id)["chats"]:
                for msg in chat["messages"]:
                    if msg["id"] == message_id:
                        return chat, msg
            return None, None

    def edit(self, tg_id: int, message_id: int, text: Optional[str] = None, buttons=_KEEP_BUTTONS,
             deleted: bool = False, blocks=None) -> bool:
        with self._lock:
            data = self._data(tg_id)
            _chat, msg = self.find(tg_id, message_id)
            if msg is None:
                return False
            if text is not None:
                msg["text"] = str(text)
                msg.pop("blocks", None)                  # 字換了，舊的區塊就不對了（新的字有自己的區塊就換上）
                if blocks:
                    msg["blocks"] = list(blocks)
            if buttons is not _KEEP_BUTTONS:
                msg["buttons"] = buttons or []
            if deleted:
                msg["text"], msg["buttons"], msg["deleted"] = "（這則訊息已刪除）", [], True
                msg.pop("blocks", None)
            data["rev"] = int(data.get("rev", 0)) + 1
            msg["rev"] = data["rev"]
            self._save(tg_id)
            return True

    def events(self, tg_id: int, chat_id: str, since: int = 0) -> Tuple[List[dict], int]:
        with self._lock:
            chat = self.get(tg_id, chat_id)
            rev = self.rev(tg_id)
            if chat is None:
                return [], rev
            return [dict(m) for m in chat["messages"] if m.get("rev", 0) > since], rev

    def has_button(self, tg_id: int, chat_id: str, message_id: int, data: str) -> Optional[dict]:
        """這段對話裡的這則訊息上真的有這顆按鈕嗎（有 → 回那則訊息）。偽造的按鈕在這裡就擋掉。"""
        with self._lock:
            chat, msg = self.find(tg_id, message_id)
            if chat is None or chat["id"] != chat_id:
                return None
            for row in msg.get("buttons") or []:
                for b in row:
                    if b.get("data") == data:
                        return dict(msg)
            return None
