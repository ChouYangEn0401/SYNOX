"""第 2 關的「網頁畫面」那一段（工具服務，ADR 0023 第三版、計畫 WP1）：只讀檔、不執行，只用標準函式庫。

- **擋（種類 app）**——只有解析 HTML 就能確定的：有內容的 `<script>`；`on*` 屬性；`<base>`；`<meta http-equiv>`；
  `<iframe>`／`<object>`／`<embed>`／`<frame>`；`script`／`link`／`img`／`source`／`video`／`audio`／`form` 的
  `src`／`href`／`action`／`srcset`／`poster` 指到外面（帶協定或 `//` 開頭）；入口頁的第一個 `<script>` 不是 `/_synox/kit.js`。
- **提醒（種類 app_note，不擋）**——字串比對：JS／CSS／JSON／SVG 裡的網址、`@import`、`url(` 指到外面、`eval(`、`new Function`、
  `document.cookie`、`window.open`、改 `location`、`sendBeacon`、`WebSocket`、`importScripts`、`serviceWorker`、`fetch(`、`XMLHttpRequest`。
每一筆都有檔名與行號。畫面程式在瀏覽器裡跑，SYNOX 看不懂它在做什麼：這些檢查擋的是「格式」，不是保證。
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import List, Optional, Tuple

KIT_SRC = "/_synox/kit.js"
FRAME_TAGS = ("iframe", "object", "embed", "frame")
URL_TAGS = ("script", "link", "img", "source", "video", "audio", "form")
URL_ATTRS = ("src", "href", "action", "srcset", "poster")
_EXTERNAL = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:|//|\\\\)", re.IGNORECASE)
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
_W3 = "http://www.w3.org/"
NOTES = [
    (re.compile(r"@import", re.IGNORECASE), "CSS 的 @import"),
    (re.compile(r"url\(\s*['\"]?\s*(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE), "CSS 的 url( 指到外面"),
    (re.compile(r"\beval\s*\("), "eval("),
    (re.compile(r"\bnew\s+Function\b"), "new Function"),
    (re.compile(r"document\.cookie"), "document.cookie"),
    (re.compile(r"window\.open\s*\("), "window.open"),
    (re.compile(r"location\.href\s*=(?!=)|\blocation\s*=(?!=)|location\.assign\s*\(|location\.replace\s*\("), "改網址（location）"),
    (re.compile(r"sendBeacon"), "sendBeacon"),
    (re.compile(r"\bWebSocket\b"), "WebSocket"),
    (re.compile(r"importScripts"), "importScripts"),
    (re.compile(r"serviceWorker"), "serviceWorker"),
    (re.compile(r"\bfetch\s*\("), "fetch(：畫面程式自己連線，沒經過共用元件"),
    (re.compile(r"XMLHttpRequest"), "XMLHttpRequest：畫面程式自己連線，沒經過共用元件"),
]
TEXT_EXT = (".js", ".css", ".json", ".svg")


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems: List[Tuple[int, str, str]] = []           # (行號, 片段, 說明)
        self.scripts: List[Tuple[int, Optional[str]]] = []       # (行號, src)
        self._in_script: Optional[int] = None

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        tag = tag.lower()
        for name, value in attrs:
            n = (name or "").lower()
            if n.startswith("on"):
                self.problems.append((line, f"<{tag} {n}=…>", "on… 屬性（內嵌的程式）"))
            if tag in URL_TAGS and n in URL_ATTRS and value and any(
                    _EXTERNAL.match(part.strip().split(" ")[0]) for part in value.split(",")):
                self.problems.append((line, f"<{tag} {n}=…>", "指到外面的網址"))
        if tag == "base":
            self.problems.append((line, "<base>", "<base> 會改掉頁面上所有相對網址"))
        if tag == "meta" and any((n or "").lower() == "http-equiv" for n, _v in attrs):
            self.problems.append((line, "<meta http-equiv>", "<meta http-equiv>"))
        if tag in FRAME_TAGS:
            self.problems.append((line, f"<{tag}>", f"<{tag}>（內嵌別的頁面或程式）"))
        if tag == "script":
            src = next((v for n, v in attrs if (n or "").lower() == "src"), None)
            self.scripts.append((line, src))
            self._in_script = line

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self._in_script = None

    def handle_data(self, data):
        if self._in_script is not None and data.strip():
            self.problems.append((self._in_script, "<script>…</script>", "內嵌的 <script>（程式要放在 .js 檔）"))


def _finding(rel: str, line: int, kind: str, snippet: str, detail: str):
    from synox.packs.scan import Finding
    return Finding(rel, line, kind, snippet[:80], detail)


def scan_app(m) -> list:
    """manifest 的 web.app 底下的檔 → [Finding]（種類 app＝擋、app_note＝提醒）。沒有 app 回 []。"""
    app = (getattr(m, "web", None) or {}).get("app")
    if not app:
        return []
    out = []
    for rel in app.get("files") or []:
        path = os.path.join(m.folder, *rel.split("/"))
        ext = os.path.splitext(rel)[1].lower()
        if ext not in (".html",) + TEXT_EXT:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            out.append(_finding(rel, 0, "app", rel, "讀不懂這個檔（要是 UTF-8 文字）"))
            continue
        if ext == ".html":
            parser = _Html()
            try:
                parser.feed(text)
                parser.close()
            except Exception:
                out.append(_finding(rel, 0, "app", rel, "HTML 解析不了"))
                continue
            for line, snippet, detail in parser.problems:
                out.append(_finding(rel, line, "app", snippet, detail))
            if rel == app.get("entry"):
                first = parser.scripts[0] if parser.scripts else None
                if first is None or (first[1] or "").strip() != KIT_SRC:
                    out.append(_finding(rel, first[0] if first else 0, "app", "<script src=…>",
                                        f"入口頁的第一個 <script> 一定要是 {KIT_SRC}（SYNOX 的共用元件）"))
            continue
        for no, line in enumerate(text.splitlines(), 1):
            for url in _URL_IN_TEXT.findall(line):
                if not url.lower().startswith(_W3):
                    out.append(_finding(rel, no, "app_note", url, "寫著外面的網址"))
            for pattern, label in NOTES:
                if pattern.search(line):
                    out.append(_finding(rel, no, "app_note", line.strip(), label))
    return out
