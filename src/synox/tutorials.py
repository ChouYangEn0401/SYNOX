"""圖文教學（docs/tutorials/<名字>/index.html）：精靈的「看圖文教學」按鈕與網頁的 GET /tutorials/<名字>/ 都從這裡拿。

    path = tutorials.path_of("telegram")      → "<SYNOX>/docs/tutorials/telegram/index.html" 或 None（沒有這份）
    tutorials.open_local("telegram")          → 用預設瀏覽器打開本機那份（精靈用；沒有＝False、不開）
    tutorials.names()                         → ["telegram", …]（有 index.html 的資料夾）

加一份新教學不用改程式：放 docs/tutorials/<名字>/index.html 就好（名字只用小寫英數、`-`、`_`，跟 pack 名一樣）。
每一份都要是**自足的一頁**：沒有外部資源（字型、圖、程式都內嵌；本機離線打開也要能看）、**沒有 JavaScript**
（網頁那條路的 CSP 只放行內嵌樣式，`<script>` 一律不執行）。規則與索引：docs/tutorials/README.md。
"""

from __future__ import annotations

import os
import re
import webbrowser
from typing import List, Optional

from synox.config import ROOT

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
FOLDER = os.path.join(ROOT, "docs", "tutorials")
INDEX = "index.html"


def path_of(name: str, folder: str = "") -> Optional[str]:
    """這份教學的 index.html 的絕對路徑；名字不合規則或檔案不存在＝None（網頁回 404、精靈不顯示按鈕）。"""
    if not NAME_RE.match(name or ""):
        return None
    path = os.path.join(folder or FOLDER, name, INDEX)
    return path if os.path.isfile(path) else None


def names(folder: str = "") -> List[str]:
    folder = folder or FOLDER
    if not os.path.isdir(folder):
        return []
    return sorted(n for n in os.listdir(folder) if path_of(n, folder))


def read(name: str, folder: str = "") -> Optional[bytes]:
    path = path_of(name, folder)
    if path is None:
        return None
    with open(path, "rb") as f:
        return f.read()


def file_url(path: str) -> str:
    """本機檔案給瀏覽器開的網址（Windows 的 C:\\… 也行）。"""
    from urllib.request import pathname2url
    return "file:" + pathname2url(os.path.abspath(path))


def open_local(name: str, opener=webbrowser.open, folder: str = "") -> bool:
    """用預設瀏覽器打開本機那份教學；沒有這份＝False（什麼都不開）。"""
    path = path_of(name, folder)
    if path is None:
        return False
    opener(file_url(path))
    return True
