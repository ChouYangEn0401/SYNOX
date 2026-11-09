"""
在終端機直接跟 bot 講話：不用 Telegram、不用 token，開發新指令時最快的試法。

    python -m mybot --console            （範本的 __main__.py 已經接好）
    你 > /help
    🤖 📖 指令選單 (1/3) …
       [1] ◀️ 上一頁   [2] 1/3   [3] 下一頁 ▶️
    你 > !3                               按第 3 顆按鈕
    你 > :as 42                           換成用 id 42 的身分講話（試別的角色看到什麼）
    你 > :q                               離開

走的是同一個 dispatcher、同一個 authorize、同一套速率限制——跟在 Telegram 私訊打字一樣，只是管子換成終端機。
送給「別的聊天」的訊息（例如升級申請通知管理員）也印出來，前面標是送給誰。
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Callable, List, Optional, Tuple

from isdtelekit.core.channel import CONSOLE, CallbackInfo, Inbound
from isdtelekit.core.richtext import plain

Button = Tuple[str, str, int, int]          # (文字, callback_data, chat_id, message_id)


class ConsoleChannel:
    """Channel：印到終端機。最後一次印出來的按鈕編號 1、2、3…，用 !N 按。"""

    channel_name = CONSOLE

    def __init__(self, out: Callable[[str], None] = print, me: Optional[int] = None):
        self._out = out
        self.me = me                         # 現在用誰的身分講話（送給別人的訊息前面標出來）
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.buttons: List[Button] = []

    def _show(self, chat_id: int, text, reply_markup=None, message_id: int = 0, prefix: str = "🤖") -> None:
        who = "" if chat_id == self.me else f"（→ 聊天 {chat_id}）"
        lines = [f"{prefix}{who} {line}" if i == 0 else f"   {line}"
                 for i, line in enumerate(plain(text).splitlines() or [""])]
        rows = (reply_markup or {}).get("inline_keyboard") or []
        with self._lock:
            if rows:
                self.buttons = []
                for row in rows:
                    labels = []
                    for b in row:
                        self.buttons.append((b.get("text", ""), b.get("callback_data", ""), chat_id, message_id))
                        labels.append(f"[{len(self.buttons)}] {b.get('text', '')}")
                    lines.append("   " + "   ".join(labels))
            self._out("\n".join(lines))

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, link_preview=True, **kw):
        message_id = next(self._ids)
        self._show(chat_id, text, reply_markup, message_id)
        return {"ok": True, "result": {"message_id": message_id}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        self._show(chat_id, text, reply_markup, message_id, prefix="✏️")
        return {"ok": True}

    def remove_buttons(self, chat_id, message_id, **kw):
        with self._lock:
            self.buttons = [b for b in self.buttons if b[3] != message_id]
        return {"ok": True}

    def answer_callback_query(self, callback_query_id, text=None, **kw):
        if text:
            self._out(f"💬 {text}")
        return {"ok": True}

    def send_photo(self, chat_id, photo, caption=""):
        self._out(f"🖼 （圖片 {photo}）{caption}")
        return {"ok": True}

    def send_document(self, chat_id, document, caption=""):
        self._out(f"📎 （檔案 {document}）{caption}")
        return {"ok": True}

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        self._out(f"🖼 （{len(photo_paths)} 個檔案）{caption}")
        return {"ok": True}

    def download_file(self, file_id, dest_path):
        return False

    def typing(self, chat_id):
        return None

    def delete_message(self, chat_id, message_id):
        return {"ok": True}

    def button(self, number: int) -> Optional[Button]:
        with self._lock:
            return self.buttons[number - 1] if 0 < number <= len(self.buttons) else None


HELP = "（打字跟 bot 講話；!N 按第 N 顆按鈕；:as <id> 換身分；:q 離開）"


def run_console(app, user_id: Optional[int] = None, ask: Callable[[str], str] = input,
                out: Callable[[str], None] = print) -> None:
    """互動迴圈。user_id 沒給＝機器擁有者。"""
    me = user_id or app.owner_id
    channel = ConsoleChannel(out, me=me)
    out(f"🖥 終端機模式：用 id {me} 的身分跟 bot 講話。{HELP}")
    while True:
        try:
            # lstrip BOM：從 PowerShell 把指令 pipe 進來時，第一行前面會多一個 ﻿，「/」就不在第一個字了
            line = ask("你 > ").strip().lstrip("﻿")
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in (":q", ":quit", ":exit"):
            break
        if line.startswith(":as"):
            try:
                me = channel.me = int(line.split()[1])
                out(f"（現在用 id {me} 的身分講話）")
            except (IndexError, ValueError):
                out("用法：:as <使用者 id>")
            continue
        if line.startswith("!") and line[1:].isdigit():
            found = channel.button(int(line[1:]))
            if found is None:
                out("沒有這顆按鈕。")
                continue
            _text, data, chat_id, message_id = found
            cb = CallbackInfo(chat_id=chat_id, message_id=message_id, cq_id="console", clicker_id=me, data=data,
                              message_date=time.time())
            app.dispatcher.handle(channel, Inbound(CONSOLE, me, chat_id, button=cb, username="console"))
            _settle(app, out)
            continue
        app.dispatcher.handle(channel, Inbound(CONSOLE, me, me, line, username="console", sent_at=time.time()))
        _settle(app, out)
    running = [j for j in app.jobs.list() if j.state == "running"]
    if running:
        out(f"（還有 {len(running)} 個背景工作在跑，bot 結束時會一起停掉：" + "、".join(j.name for j in running) + "）")
    out("👋 bye")


def _settle(app, out, patience: float = 3.0, limit: float = 120.0) -> None:
    """等這一句丟到背景的工作（app.tasks：例如呼叫服務）回完，再印下一個提示——不然下一句會搶在上一句的回覆前面，
    從腳本 pipe 指令進來時順序也會亂。等超過 patience 秒說一聲；跑很久、做完才通知的背景工作不在這裡等。"""
    if app.tasks.wait(patience):
        return
    out("（等服務回覆中…）")
    app.tasks.wait(limit)
