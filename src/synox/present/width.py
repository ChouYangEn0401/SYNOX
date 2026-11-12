"""
等寬字型裡的顯示寬度（<pre>／程式碼區塊裡的表格對齊用）與訊息長度。

- 中日韓全形字、全形符號、大部分 emoji（East Asian Width 是 W 或 F）算 2 格；
  組合字元、零寬字元（ZWJ、變體選擇符）算 0 格；其他算 1 格。
- 訊息長度一律用 UTF-16 單位算（Telegram、Discord 都是照這個或更寬鬆的算法），保守不超過上限。
"""

from __future__ import annotations

import unicodedata

_ZERO = {"​", "‌", "‍", "⁠", "﻿"}


def char_width(ch: str) -> int:
    if ch in _ZERO or unicodedata.combining(ch) or "︀" <= ch <= "️":
        return 0
    if unicodedata.category(ch) in ("Cc", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(text: str) -> int:
    """這段字在等寬字型裡佔幾格。"""
    return sum(char_width(ch) for ch in str(text))


def pad(text: str, cells: int) -> str:
    """補空白到 cells 格寬（照 width 算）。"""
    text = str(text)
    return text + " " * max(0, cells - width(text))


def clip(text: str, cells: int, mark: str = "…") -> str:
    """超過 cells 格就截掉，最後放 mark（mark 也算在 cells 裡）。"""
    text = str(text)
    if width(text) <= cells:
        return text
    room = max(0, cells - width(mark))
    out, used = [], 0
    for ch in text:
        w = char_width(ch)
        if used + w > room:
            break
        out.append(ch)
        used += w
    return "".join(out) + mark


def utf16_len(text: str) -> int:
    """訊息長度（UTF-16 單位）：BMP 以外的字（多數 emoji）算 2。"""
    return len(str(text).encode("utf-16-le")) // 2
