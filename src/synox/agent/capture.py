"""
執行工具時用的 Channel：指令「回給這個聊天的純文字」攔下來交給 AI（工具結果），其他照常送給使用者
（帶按鈕的訊息、圖片、檔案、送給別的聊天的），並在工具結果裡註明「已經直接傳給使用者」——照 ClawBot bridge 的規則。

via_ai = True：SDK 的 Forms 與 Node.precheck 看這個旗標（經 AI 呼叫時不開問答，例如驗證碼）。
note_failure：loader／mcp 經 health.observe_failure 交來的失敗（agent/loop.py 改回 AI 一行 `FAIL …`）。
"""

from __future__ import annotations

import threading
from typing import List

from isdtelekit.core.richtext import plain


def _labels(markup) -> str:
    rows = (markup or {}).get("inline_keyboard") or []
    names = [b.get("text", "") for row in rows for b in row]
    return f"（按鈕：{'、'.join(names)}）" if names else ""


class CaptureApi:
    via_ai = True

    def __init__(self, real, chat_id: int):
        self._real = real
        self._chat = chat_id
        self._lines: List[str] = []
        self._open = True
        self._lock = threading.Lock()
        self.carded = False                 # 執行中送了確認卡（工具回 needs_confirm）：這一輪 AI 就停在這裡
        self.failure = None                 # 工具失敗了（health.Failure）：loop 交回 AI 的是固定格式的一行，不是人看的字

    def mark_carded(self) -> None:
        self.carded = True

    def note_failure(self, failure) -> None:
        self.failure = failure

    @property
    def channel_name(self) -> str:
        return getattr(self._real, "channel_name", "")

    def _note(self, chat_id: int, line: str) -> None:
        with self._lock:
            if self._open and chat_id == self._chat:
                self._lines.append(line)

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, **kw):
        with self._lock:
            capture = self._open and chat_id == self._chat and reply_markup is None
            if capture:
                self._lines.append(plain(text))
        if capture:
            return {"ok": True, "result": {"message_id": 0}}
        if reply_markup is not None:
            self._note(chat_id, f"〔已直接傳給使用者一則帶按鈕的訊息〕{plain(text)[:300]}{_labels(reply_markup)}")
        return self._real.send_message(chat_id, text, reply_markup=reply_markup, quiet=quiet, **kw)

    def send_photo(self, chat_id, photo, caption=""):
        self._note(chat_id, f"〔已直接傳給使用者一張圖〕{caption[:200]}")
        return self._real.send_photo(chat_id, photo, caption=caption)

    def send_document(self, chat_id, document, caption=""):
        self._note(chat_id, f"〔已直接傳給使用者一個檔案〕{caption[:200]}")
        return self._real.send_document(chat_id, document, caption=caption)

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        self._note(chat_id, f"〔已直接傳給使用者 {len(photo_paths)} 個檔案〕{caption[:200]}")
        return self._real.send_media_group(chat_id, photo_paths, caption, kind)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self) -> str:
        with self._lock:
            self._open = False
            return "\n".join(self._lines)
