"""
來源 adapter：Markdown → 區塊（自己寫的小解析器，不用第三方套件），純文字 → 段落。

支援（AI 回覆常用的那一小套）：
- 區塊：段落、ATX 標題（# ～ ######）、清單（- * + 與 1. 1)，巢狀最多兩層，更深的併到第二層）、
  GFM 表格、``` 或 ~~~ 程式碼區塊（含語言標記；沒閉合＝到結尾都是程式碼）、> 引用（巢狀攤平）。
  分隔線（---）只當區塊分界，不輸出。
- 行內：**粗體**／__粗體__、*斜體*／_斜體_、`程式碼`、[字](網址)、<網址>、裸的 http(s) 網址、反斜線跳脫。
  沒閉合的 ** 一律是普通字。中文緊貼著的 **粗體：**後文 也算（不照 CommonMark 對標點的嚴格規定）。

安全：
- 永遠不產生按鈕群或確認卡；HTML 標籤、HTML 實體（&lt;）都是普通字（輸出時再跳脫，不會被解讀）。
- 連結只收 http／https（blocks.safe_url）；`[字](javascript:…)` 整段原樣當普通字。
- 不丟例外：解析出錯就整份退成純文字段落（from_plain）。
- 強調的配對是單一堆疊（交叉的直接當普通字），長度是線性的，大量巢狀不會變慢或爆遞迴。
"""

from __future__ import annotations

import bisect
import logging
import re
import string
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from synox.present.blocks import (
    ASSISTANT, CodeBlock, Document, Heading, ListBlock, ListItem, Paragraph, Quote, Span, Table,
    check_trust, merge, safe_lang, safe_url,
)

_PUNCT = set(string.punctuation)

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)[^`]*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_HR = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE = re.compile(r"^ {0,3}>")
_ITEM = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])(?:[ \t]+(.*))?$")
_SEP_CELL = re.compile(r"^\s*:?-+:?\s*$")
_SPECIAL = re.compile(r"[\\`\[<*_]|https?://")
_BARE_URL = re.compile(r"https?://[^\s<>\[\]\"'`]+")
_AUTOLINK = re.compile(r"<(https?://[^\s<>]+)>")
_TRAIL = ".,;:!?'\"*_~，。；：！？、」』）】"

MAX_LEVELS = 2
LABEL_MAX = 1000
URL_SCAN_MAX = 2100


# ── 純文字 ───────────────────────────────────────────────────────────

def from_plain(text: str, trust: str = ASSISTANT) -> Document:
    """純文字 → 段落（空行分段，不解析任何標記）。"""
    check_trust(trust)
    text = _normalize(text)
    blocks = []
    for part in re.split(r"\n[ \t]*\n", text):
        part = part.strip("\n")
        if part.strip():
            blocks.append(Paragraph([Span(part)], trust=trust))
    return Document(blocks, trust=trust)


def _normalize(text) -> str:
    text = "" if text is None else str(text)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "�")


# ── Markdown（區塊）─────────────────────────────────────────────────────

def parse(text: str, trust: str = ASSISTANT) -> Document:
    """Markdown → Document。不會丟例外：出錯就退成純文字段落。"""
    check_trust(trust)
    try:
        return Document(_Blocks(_normalize(text), trust).run(), trust=trust)
    except Exception:                      # 最差退成段落（驗收：壞掉的 Markdown 不丟例外）
        logging.exception("[PRESENT] markdown parse failed; falling back to plain text")
        return from_plain(text, trust)


def _indent(ws: str) -> int:
    return sum(4 if ch == "\t" else 1 for ch in ws)


def _blank(line: str) -> bool:
    return not line.strip()


def split_row(line: str) -> List[str]:
    """表格的一列 → 每格的原始字（`\\|` 是格子裡的 |）。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, buf, i = [], [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


class _Blocks:

    def __init__(self, text: str, trust: str):
        self.lines = text.split("\n")
        self.trust = trust
        self.out: list = []

    def run(self) -> list:
        lines, i = self.lines, 0
        while i < len(lines):
            line = lines[i]
            if _blank(line):
                i += 1
            elif _FENCE.match(line):
                i = self.fence(i)
            elif _HR.match(line):
                i += 1
            elif _HEADING.match(line):
                m = _HEADING.match(line)
                body = re.sub(r"(^|[ \t]+)#+[ \t]*$", "", m.group(2) or "").strip()
                self.out.append(Heading(len(m.group(1)), parse_inline(body), trust=self.trust))
                i += 1
            elif _QUOTE.match(line):
                i = self.quote(i)
            elif self.table_at(i):
                i = self.table(i)
            elif _ITEM.match(line):
                i = self.items(i)
            else:
                i = self.paragraph(i)
        return self.out

    # 每一種區塊回「下一行的位置」

    def fence(self, i: int) -> int:
        m = _FENCE.match(self.lines[i])
        mark, lang = m.group(1), safe_lang(m.group(2))
        body, j = [], i + 1
        while j < len(self.lines):
            close = self.lines[j].strip()
            if close and set(close) == {mark[0]} and len(close) >= len(mark) and \
                    _indent(self.lines[j][:len(self.lines[j]) - len(self.lines[j].lstrip())]) <= 3:
                j += 1
                break
            body.append(self.lines[j])
            j += 1
        while body and not body[-1].strip():               # 結尾的空行（沒閉合的圍欄常見）不算程式碼
            body.pop()
        self.out.append(CodeBlock("\n".join(body), lang, trust=self.trust))
        return j

    def quote(self, i: int) -> int:
        paragraphs, cur, j = [], [], i
        while j < len(self.lines) and _QUOTE.match(self.lines[j]):
            content = self.lines[j].lstrip()
            while content.startswith(">"):            # 巢狀引用攤平成一層
                content = content[1:].lstrip(" ")
            if content.strip():
                cur.append(content.strip())
            elif cur:
                paragraphs.append(cur)
                cur = []
            j += 1
        if cur:
            paragraphs.append(cur)
        if paragraphs:
            self.out.append(Quote([parse_inline("\n".join(p)) for p in paragraphs], trust=self.trust))
        return j

    def table_at(self, i: int) -> bool:
        if i + 1 >= len(self.lines) or "|" not in self.lines[i]:
            return False
        sep = self.lines[i + 1]
        if "-" not in sep or ("|" not in sep and "|" not in self.lines[i].strip().strip("|")):
            return False
        cells = split_row(sep)
        return all(_SEP_CELL.match(c) for c in cells) and len(cells) == len(split_row(self.lines[i]))

    def table(self, i: int) -> int:
        header = split_row(self.lines[i])
        n = len(header)
        rows, j = [], i + 2
        while j < len(self.lines):
            line = self.lines[j]
            if _blank(line) or "|" not in line or _FENCE.match(line) or _HEADING.match(line) or _QUOTE.match(line):
                break
            cells = split_row(line)
            cells = (cells + [""] * n)[:n]
            rows.append(cells)
            j += 1
        self.out.append(Table([parse_inline(c) for c in header],
                              [[parse_inline(c) for c in row] for row in rows], trust=self.trust))
        return j

    def items(self, i: int) -> int:
        first = _ITEM.match(self.lines[i])
        base = _indent(first.group(1))
        ordered = first.group(2)[0].isdigit()
        start = int(first.group(2)[:-1]) if ordered else 1
        items: List[Tuple[List[str], Optional[Tuple[bool, int, List[List[str]]]]]] = []
        j = i
        while j < len(self.lines):
            line = self.lines[j]
            if _blank(line):
                k = j + 1
                while k < len(self.lines) and _blank(self.lines[k]):
                    k += 1
                if k >= len(self.lines):
                    j = k
                    break
                nxt = self.lines[k]
                m = _ITEM.match(nxt)
                if (m and not _HR.match(nxt) and (_indent(m.group(1)) >= base + 2 or
                                                  m.group(2)[0].isdigit() == ordered)) or \
                        (_indent(nxt[:len(nxt) - len(nxt.lstrip())]) >= base + 2 and items):
                    j = k
                    continue
                break
            m = _ITEM.match(line)
            if m and not _HR.match(line):
                ind = _indent(m.group(1))
                body = (m.group(3) or "").strip()
                is_num = m.group(2)[0].isdigit()
                if ind >= base + 2 and items:                    # 第二層（更深的也併到這裡）
                    sub = items[-1][1]
                    if sub is None:
                        sub = (is_num, int(m.group(2)[:-1]) if is_num else 1, [])
                        items[-1] = (items[-1][0], sub)
                    sub[2].append([body])
                elif is_num != ordered:
                    break                                        # 換了清單種類＝新的一個清單
                else:
                    items.append(([body], None))
                j += 1
                continue
            if line[:1] in (" ", "\t") and items:                # 縮排的續行
                target = items[-1][1][2][-1] if items[-1][1] is not None and \
                    _indent(line[:len(line) - len(line.lstrip())]) >= base + 4 else items[-1][0]
                target.append(line.strip())
                j += 1
                continue
            break
        built = []
        for body, sub in items:
            children = None
            if sub is not None:
                children = ListBlock(sub[0], [ListItem(parse_inline("\n".join(b))) for b in sub[2]],
                                     start=sub[1], trust=self.trust)
            built.append(ListItem(parse_inline("\n".join(x for x in body if x)), children))
        self.out.append(ListBlock(ordered, built, start=start, trust=self.trust))
        return max(j, i + 1)

    def paragraph(self, i: int) -> int:
        buf, j = [], i
        while j < len(self.lines):
            line = self.lines[j]
            if j > i and (_blank(line) or _FENCE.match(line) or _HR.match(line) or _HEADING.match(line) or
                          _QUOTE.match(line) or self.table_at(j) or self._interrupts(line)):
                break
            if j == i and _blank(line):
                break
            buf.append(line.strip())
            j += 1
        self.out.append(Paragraph(parse_inline("\n".join(buf)), trust=self.trust))
        return max(j, i + 1)

    @staticmethod
    def _interrupts(line: str) -> bool:
        """清單項目能不能打斷段落：無序的都可以；有序的只有 1. 開頭的（照 CommonMark）。"""
        m = _ITEM.match(line)
        if not m or not (m.group(3) or "").strip():
            return False
        marker = m.group(2)
        return not marker[0].isdigit() or marker[:-1] == "1"


# ── Markdown（行內）─────────────────────────────────────────────────────

@dataclass
class _Delim:
    ch: str
    count: int
    can_open: bool
    can_close: bool
    opens: List[str] = field(default_factory=list)     # 這一串開了哪些（輸出順序：外層先）
    closes: List[str] = field(default_factory=list)    # 這一串關了哪些（輸出順序：內層先）


def _backtick_runs(src: str) -> Dict[int, List[int]]:
    runs: Dict[int, List[int]] = {}
    for m in re.finditer(r"`+", src):
        runs.setdefault(len(m.group(0)), []).append(m.start())
    return runs


def _pairs(src: str, open_ch: str, close_ch: str) -> Dict[int, int]:
    """一次掃完：每個 open_ch 對到的 close_ch 位置（反斜線跳脫的不算）。找連結時查表，不用每個 [ 都往後掃。"""
    stack: List[int] = []
    out: Dict[int, int] = {}
    for m in re.finditer(r"\\.|" + re.escape(open_ch) + "|" + re.escape(close_ch), src, re.S):
        ch = m.group(0)
        if ch == open_ch:
            stack.append(m.start())
        elif ch == close_ch and stack:
            out[stack.pop()] = m.start()
    return out


class _Links:
    """[label](url) 的位置表（brackets／parens 只算一次）。"""

    def __init__(self, src: str):
        self.src = src
        self.brackets = _pairs(src, "[", "]")
        self.parens = _pairs(src, "(", ")")

    def find(self, i: int) -> Optional[Tuple[int, str, str]]:
        """src[i] == "["：回 (結束位置, label, url 原字)；不是連結語法回 None。"""
        src = self.src
        j = self.brackets.get(i)
        if j is None or j - i > LABEL_MAX or src[j + 1:j + 2] != "(":
            return None
        k = self.parens.get(j + 1)
        if k is None or k - j > URL_SCAN_MAX:
            return None
        raw = src[j + 2:k]
        if "\n" in raw:
            return None
        raw = raw.strip()
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1]
        raw = raw.split(" ", 1)[0] if " " in raw and (raw.endswith('"') or raw.endswith("'")) else raw
        return k + 1, src[i + 1:j], raw


def _trim_url(url: str) -> str:
    while url and url[-1] in _TRAIL:
        url = url[:-1]
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url


def _tokens(src: str, links: bool) -> list:
    out: list = []
    runs = _backtick_runs(src)
    finder = _Links(src) if links and "[" in src else None
    buf: List[str] = []
    i, n = 0, len(src)

    def flush():
        if buf:
            out.append(("text", "".join(buf)))
            buf.clear()

    while i < n:
        m = _SPECIAL.search(src, i)
        if m is None:
            buf.append(src[i:])
            break
        if m.start() > i:
            buf.append(src[i:m.start()])
            i = m.start()
        ch = src[i]
        if ch == "\\":
            if i + 1 < n and src[i + 1] in _PUNCT:
                buf.append(src[i + 1])
                i += 2
            else:
                buf.append("\\")
                i += 1
        elif ch == "`":
            j = i
            while j < n and src[j] == "`":
                j += 1
            k = j - i
            starts = runs.get(k, [])
            pos = bisect.bisect_left(starts, i + k)
            if pos < len(starts):
                close = starts[pos]
                code = src[i + k:close].replace("\n", " ")
                if len(code) >= 2 and code[0] == " " and code[-1] == " " and code.strip():
                    code = code[1:-1]
                flush()
                out.append(("code", code))
                i = close + k
            else:
                buf.append("`" * k)
                i += k
        elif ch == "[":
            found = finder.find(i) if finder is not None else None
            if found is None:
                buf.append("[")
                i += 1
            else:
                end, label, raw = found
                url = safe_url(raw)
                if url is None:                         # 不是 http／https：整段原樣當普通字
                    buf.append(src[i:end])
                else:
                    flush()
                    out.append(("link", label, url))
                i = end
        elif ch == "<":
            am = _AUTOLINK.match(src, i)
            url = safe_url(am.group(1)) if am and links else None
            if url:
                flush()
                out.append(("url", url))
                i = am.end()
            else:
                buf.append("<")
                i += 1
        elif ch in "*_":
            j = i
            while j < n and src[j] == ch:
                j += 1
            prev = src[i - 1] if i > 0 else " "
            nxt = src[j] if j < n else " "
            if ch == "*":
                can_open, can_close = not nxt.isspace(), not prev.isspace()
            else:                                     # _ 不在字中間開關（snake_case 不會變斜體）
                can_open = not nxt.isspace() and not prev.isalnum()
                can_close = not prev.isspace() and not nxt.isalnum()
            flush()
            out.append(_Delim(ch, j - i, can_open, can_close))
            i = j
        else:                                         # http(s)://
            um = _BARE_URL.match(src, i)
            before = src[i - 1] if i > 0 else " "
            url = safe_url(_trim_url(um.group(0))) if um and links and not (before.isascii() and before.isalnum()) \
                else None
            if url:
                flush()
                out.append(("url", url))
                i += len(url)
            else:
                buf.append(src[i])
                i += 1
    flush()
    return out


def _pair(tokens: list) -> None:
    """強調的配對（單一堆疊）：closer 找堆疊裡最近的同一種 opener；中間交叉的 opener 丟掉（變普通字）。"""
    stack: List[_Delim] = []
    counts = {"*": 0, "_": 0}
    for tok in tokens:
        if not isinstance(tok, _Delim):
            continue
        if tok.can_close:
            while tok.count > 0 and counts[tok.ch] > 0:
                k = len(stack) - 1
                while stack[k].ch != tok.ch:
                    k -= 1
                for dropped in stack[k + 1:]:
                    counts[dropped.ch] -= 1
                del stack[k + 1:]
                opener = stack[k]
                use = 2 if opener.count >= 2 and tok.count >= 2 else 1
                kind = "bold" if use == 2 else "italic"
                opener.count -= use
                tok.count -= use
                opener.opens.insert(0, kind)
                tok.closes.append(kind)
                if opener.count == 0:
                    stack.pop()
                    counts[opener.ch] -= 1
        if tok.can_open and tok.count > 0:
            stack.append(tok)
            counts[tok.ch] += 1


def parse_inline(src: str, *, links: bool = True) -> List[Span]:
    """一段行內 Markdown → 攤平的 Span。"""
    tokens = _tokens(src or "", links)
    _pair(tokens)
    spans: List[Span] = []
    bold = italic = 0
    for tok in tokens:
        if isinstance(tok, _Delim):
            for kind in tok.closes:
                if kind == "bold":
                    bold -= 1
                else:
                    italic -= 1
            if tok.count:
                spans.append(Span(tok.ch * tok.count, bold > 0, italic > 0))
            for kind in tok.opens:
                if kind == "bold":
                    bold += 1
                else:
                    italic += 1
        elif tok[0] == "text":
            spans.append(Span(tok[1], bold > 0, italic > 0))
        elif tok[0] == "code":
            spans.append(Span(tok[1], bold > 0, italic > 0, code=True))
        elif tok[0] == "url":
            spans.append(Span(tok[1], bold > 0, italic > 0, href=tok[1]))
        elif tok[0] == "link":
            inner = parse_inline(tok[1], links=False) or [Span(tok[2])]
            for s in inner:
                spans.append(Span(s.text, s.bold or bold > 0, s.italic or italic > 0, s.code, href=tok[2]))
    return merge(spans)
