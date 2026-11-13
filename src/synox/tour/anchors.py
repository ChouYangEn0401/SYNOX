"""
教學可以指的「畫面位置」：穩定的名字 → 網頁上 `data-tour="<名字>"` 的那個元素（static/app.html）。

步驟檔只能寫這張表裡的名字，**不能寫 CSS 選擇器**：畫面改版、元素搬家，名字跟著搬，舊教學不會壞。
找不到（這個人看不到、這一版沒有）＝那一步退成畫面中央的純文字卡，照樣能按下一步（教學永遠走得完）。

相容規則（0.x，docs/tutorials-engine.md「位置清單」）：
- 名字只加不改。真的要改名：新名字進表、舊名字放進 RENAMED（舊 → 新）至少留一個 MINOR 版本，步驟檔用舊名照樣找得到。
- 刪掉一個位置也要至少留一個 MINOR：先在說明寫「下一版拿掉」。
- **確認、刪除、密鑰欄位這種按鈕不進這張表**（教學只能指給人看、不能替人按）。
  安裝報告（settings.packs.review）是整張卡，不是確認鈕。
- tests/test_tour.py 會比對 app.html 的 data-tour 與這張表：多一個少一個都會失敗。
"""

from __future__ import annotations

from typing import Dict, Tuple

VERSION = 1                       # 位置清單的版本：加名字不用升；改名／刪名（過了相容期）才升

# 名字 → (說明, 哪一版 SYNOX 加的)
ANCHORS: Dict[str, Tuple[str, str]] = {
    "nav.chat": ("左側（手機在下方）的「對話」", "0.2"),
    "nav.tools": ("左側（手機在下方）的「工具」", "0.2"),
    "nav.settings": ("左側（手機在下方）的「設定」", "0.2"),
    "chat.list": ("對話頁：對話紀錄清單", "0.2"),
    "chat.new": ("對話頁：「＋ 新對話」按鈕", "0.2"),
    "chat.input": ("對話頁：打字的地方（輸入框＋送出鈕）", "0.2"),
    "chat.send": ("對話頁：「送出」按鈕", "0.2"),
    "tools.page": ("工具頁：工具清單", "0.2"),
    "settings.tabs": ("設定頁：分頁列", "0.2"),
    "settings.tab.ai": ("設定頁：「🤖 AI」分頁", "0.2"),
    "settings.tab.channels": ("設定頁：「💬 聊天通道」分頁", "0.2"),
    "settings.tab.packs": ("設定頁：「🧩 功能與安裝」分頁", "0.2"),
    "settings.tab.accounts": ("設定頁：「👥 帳號」分頁（伺服器版）", "0.2"),
    "settings.tab.system": ("設定頁：「💻 電腦與備份」分頁", "0.2"),
    "settings.tab.help": ("設定頁：「🙋 遇到問題？」分頁", "0.2"),
    "settings.ai.source": ("設定頁：「AI 從哪裡來」那張卡", "0.2"),
    "settings.channels": ("設定頁：聊天通道（Telegram／Discord）那張卡", "0.2"),
    "settings.packs.catalog": ("設定頁：官方工具庫那張卡", "0.2"),
    "settings.packs.catalog.load": ("設定頁：「載入工具清單」按鈕（只讀清單，不會裝任何東西）", "0.2"),
    "settings.packs.upload": ("設定頁：上傳 .synoxpack 那張卡", "0.2"),
    "settings.packs.review": ("設定頁：安裝前的檢查報告（整張卡；不是確認鈕）", "0.2"),
    "settings.packs.installed": ("設定頁：已安裝的工具清單", "0.2"),
    "settings.backup": ("設定頁：備份那張卡", "0.2"),
}

# 改過名的：舊名字 → 新名字（留至少一個 MINOR）。現在沒有。
RENAMED: Dict[str, str] = {}

# 「帶我去」可以去的地方（封閉清單；步驟檔的 go 只能寫這些）：view → 允許的 tab
GO_VIEWS: Dict[str, Tuple[str, ...]] = {
    "chat": (),
    "tools": (),
    "settings": ("ai", "channels", "packs", "accounts", "system"),
}

# 「這一步做完了嗎」的事件（封閉清單；網頁由 static/tour.js 觀察，聊天通道只認 command）
EVENTS: Dict[str, str] = {
    "view": "切到哪一頁（value：chat｜tools｜settings）",
    "tab": "設定頁切到哪個分頁（value：ai｜channels｜packs｜accounts｜system）",
    "message_sent": "在對話頁送出一則訊息（不看內容）",
    "command": "送出某個指令（value：指令名，不含 /，例如 help）",
    "catalog_loaded": "官方工具清單載入好了",
    "pack_report": "出現安裝前的檢查報告",
    "pack_installed": "裝好一個工具（使用者自己按了確認）",
    "pack_removed": "移除了一個工具（使用者自己按了移除）",
}


def resolve(name: str) -> str:
    """步驟檔寫的名字 → 現在的名字；不認得＝""。"""
    name = RENAMED.get(name, name)
    return name if name in ANCHORS else ""


def known(name: str) -> bool:
    return bool(resolve(name))
