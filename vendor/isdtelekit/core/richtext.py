"""
有格式的訊息：Telegram 支援的那一小套 HTML——
<b> 粗體、<i> 斜體、<code> 等寬、<pre> 等寬區塊、<blockquote> 引用、<blockquote expandable> 可收合的引用、<a href>。

    from isdtelekit.core.richtext import Html, esc
    api.send_message(chat_id, Html(f"<b>{esc(title)}</b>\\n<code>{esc(command)}</code>"))

Html 是 str 的子類別，跟 MarkupSafe 的 Markup 同一個想法：「這段已經是安全的 HTML」記在值本身，
所以 Channel 的方法不用多一個參數，包在外面的 api 也照樣傳得過去。
- Telegram（telegram/bot_api.py）看到 Html 就用 parse_mode=HTML；Telegram 不收（標籤寫錯）
  就自動改送純文字，訊息不會因為格式掉了。
- 不支援格式的 channel（本機畫面、測試）、要拿去記日誌的包裝，一律用 plain()。
- Html 跟一般字串相加、切片就變回一般字串（標籤會原樣顯示出來）：整段組好再包 Html(...)，
  裡面動態的文字（使用者的話、指令輸出）一律先 esc()。
"""

from __future__ import annotations

import html as _html
import re
import unicodedata

_TAG = re.compile(r"<[^>]+>")


class Html(str):
    """已經是 Telegram HTML 的字串（動態的部分都 esc 過）。"""
    __slots__ = ()


def esc(value) -> str:
    """動態文字放進 Html 之前一定要過這個（<、>、& 換掉；引號不用，Telegram 不需要）。"""
    return _html.escape("" if value is None else str(value), quote=False)


def plain(text) -> str:
    """Html → 給人看的純文字：去掉標籤、還原 &lt; 這類。一般字串原樣。"""
    if isinstance(text, Html):
        return _html.unescape(_TAG.sub("", text))
    return "" if text is None else str(text)


def width(text: str) -> int:
    """等寬字型裡佔幾格：中文、全形、emoji 算兩格（<pre> 表格對齊用）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def pad(text: str, cells: int) -> str:
    """補空白到 cells 格寬（照 width 算，中文不會把後面的欄位推歪）。"""
    text = str(text)
    return text + " " * max(0, cells - width(text))
