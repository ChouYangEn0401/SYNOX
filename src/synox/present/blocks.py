"""
與通道無關的內容區塊模型（docs/presentation.md）。

    來源（Markdown、純文字、程式產生的卡片）──來源 adapter──▶ Document（區塊清單）──輸出 adapter──▶ Telegram／Discord／網頁

- 行內一律攤平成 Span（一段字＋粗體／斜體／等寬／連結）：巢狀強調不會變成巢狀資料，輸出時每個 Span 自己開關標籤，
  所以切割訊息時每一段的標籤一定成對。
- 信任等級（`SYSTEM` > `ASSISTANT` > `EXTERNAL`）：整份 Document 一個、每個區塊一個；實際用的是兩者中**較低**的（`effective`）。
- 按鈕群（`Buttons`）、確認卡（`ConfirmCard`）只有實際信任等級是 `SYSTEM` 時才會變成真的按鈕；
  Markdown 解析器永遠不產生這兩種區塊（看起來像按鈕的字一律是普通文字）。
- 連結只收 http／https（`safe_url`）；其他一律當普通文字。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Union
from urllib.parse import urlsplit

SYSTEM, ASSISTANT, EXTERNAL = "system", "assistant", "external"
TRUSTS = (SYSTEM, ASSISTANT, EXTERNAL)
_RANK = {SYSTEM: 2, ASSISTANT: 1, EXTERNAL: 0}

TONES = {"ok": "✅", "warn": "⚠️", "error": "❌", "info": "ℹ️", "pending": "⏳"}
URL_MAX = 2000
_LANG = re.compile(r"[A-Za-z0-9_+#.-]{1,32}")
_URL_BAD = re.compile(r"[\s\x00-\x1f\x7f<>\"'`\\]")


def check_trust(trust: str) -> str:
    if trust not in TRUSTS:
        raise ValueError(f"trust must be one of {TRUSTS}, got {trust!r}")
    return trust


def lowest(*trusts: str) -> str:
    """幾個信任等級裡最低的（system > assistant > external）。"""
    return min(trusts, key=lambda t: _RANK.get(t, -1)) if trusts else EXTERNAL


def safe_url(url) -> Optional[str]:
    """只收 http／https、有主機、沒有空白／控制字元／引號；不合就 None（呼叫端把它當普通文字）。"""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or len(url) > URL_MAX or _URL_BAD.search(url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return url


def safe_lang(lang) -> str:
    """程式碼區塊的語言標記：只留像 python、c++、objective-c 這種字，其他丟掉。"""
    lang = str(lang or "").strip()
    return lang if _LANG.fullmatch(lang) else ""


# ── 行內 ─────────────────────────────────────────────────────────────

@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    href: Optional[str] = None

    def to_dict(self) -> dict:
        out: dict = {"text": self.text}
        for key in ("bold", "italic", "code"):
            if getattr(self, key):
                out[key] = True
        if self.href:
            out["href"] = self.href
        return out


def plain_of(spans: List[Span]) -> str:
    return "".join(s.text for s in spans)


def merge(spans: List[Span]) -> List[Span]:
    """相鄰、樣式一樣的 Span 併成一個；空字的丟掉。"""
    out: List[Span] = []
    for s in spans:
        if not s.text:
            continue
        if out and (out[-1].bold, out[-1].italic, out[-1].code, out[-1].href) == (s.bold, s.italic, s.code, s.href):
            out[-1] = Span(out[-1].text + s.text, s.bold, s.italic, s.code, s.href)
        else:
            out.append(s)
    return out


def text(value: str) -> List[Span]:
    """一段普通文字（不解析任何標記）。"""
    return [Span(str(value))] if value else []


# ── 區塊 ─────────────────────────────────────────────────────────────

@dataclass
class Paragraph:
    spans: List[Span]
    trust: str = ASSISTANT
    kind = "paragraph"

    def to_dict(self) -> dict:
        return {"type": self.kind, "trust": self.trust, "spans": [s.to_dict() for s in self.spans]}


@dataclass
class Heading:
    level: int
    spans: List[Span]
    trust: str = ASSISTANT
    kind = "heading"

    def to_dict(self) -> dict:
        return {"type": self.kind, "trust": self.trust, "level": self.level, "spans": [s.to_dict() for s in self.spans]}


@dataclass
class ListItem:
    spans: List[Span]
    children: Optional["ListBlock"] = None      # 第二層（最多兩層；更深的併到第二層）

    def to_dict(self) -> dict:
        out: dict = {"spans": [s.to_dict() for s in self.spans]}
        if self.children is not None:
            out["children"] = self.children.to_dict()
        return out


@dataclass
class ListBlock:
    ordered: bool
    items: List[ListItem]
    start: int = 1
    trust: str = ASSISTANT
    kind = "list"

    def to_dict(self) -> dict:
        out = {"type": self.kind, "trust": self.trust, "ordered": self.ordered,
               "items": [i.to_dict() for i in self.items]}
        if self.ordered and self.start != 1:
            out["start"] = self.start
        return out


@dataclass
class Table:
    header: List[List[Span]]
    rows: List[List[List[Span]]]
    trust: str = ASSISTANT
    kind = "table"

    def to_dict(self) -> dict:
        return {"type": self.kind, "trust": self.trust,
                "header": [[s.to_dict() for s in c] for c in self.header],
                "rows": [[[s.to_dict() for s in c] for c in row] for row in self.rows]}


@dataclass
class CodeBlock:
    code: str
    lang: str = ""
    trust: str = ASSISTANT
    kind = "code"

    def to_dict(self) -> dict:
        out = {"type": self.kind, "trust": self.trust, "code": self.code}
        if self.lang:
            out["lang"] = self.lang
        return out


@dataclass
class Quote:
    paragraphs: List[List[Span]]
    trust: str = ASSISTANT
    kind = "quote"

    def to_dict(self) -> dict:
        return {"type": self.kind, "trust": self.trust,
                "paragraphs": [[s.to_dict() for s in p] for p in self.paragraphs]}


@dataclass
class Status:
    """狀態標籤，例如 ✅ 完成、⏳ 等待中。tone 是 TONES 的鍵。"""
    label: str
    tone: str = "info"
    trust: str = SYSTEM
    kind = "status"

    def to_dict(self) -> dict:
        tone = self.tone if self.tone in TONES else "info"
        return {"type": self.kind, "trust": self.trust, "tone": tone, "icon": TONES[tone], "label": self.label}


@dataclass
class Button:
    text: str
    data: str = ""          # callback_data（按下時送回來，dispatcher 照樣 authorize）
    url: str = ""           # 或連結按鈕（只收 http／https）


@dataclass
class Buttons:
    """按鈕群：只有程式碼（SYSTEM）能建；信任不夠時輸出 adapter 只畫成普通文字。"""
    rows: List[List[Button]]
    trust: str = SYSTEM
    kind = "buttons"

    def to_dict(self) -> dict:
        return {"type": self.kind, "trust": self.trust,
                "rows": [[{k: v for k, v in (("text", b.text), ("data", b.data), ("url", b.url)) if v}
                          for b in row] for row in self.rows]}


@dataclass
class ConfirmCard:
    """確認卡：只能由核准流程建立（`confirm_card()`）；這一版只負責畫得出來，還沒取代 agent/approve.py 的卡。"""
    title: str
    lines: List[str]
    ok_data: str
    cancel_data: str
    ok_text: str = "✅ 執行"
    cancel_text: str = "❌ 取消"
    trust: str = SYSTEM
    kind = "confirm"

    def to_dict(self) -> dict:
        return {"type": self.kind, "trust": self.trust, "title": self.title, "lines": list(self.lines),
                "ok": {"text": self.ok_text, "data": self.ok_data},
                "cancel": {"text": self.cancel_text, "data": self.cancel_data}}

    def buttons(self) -> Buttons:
        return Buttons([[Button(self.ok_text, data=self.ok_data), Button(self.cancel_text, data=self.cancel_data)]],
                       trust=self.trust)


Block = Union[Paragraph, Heading, ListBlock, Table, CodeBlock, Quote, Status, Buttons, ConfirmCard]
INTERACTIVE = (Buttons, ConfirmCard)


def confirm_card(title: str, lines: List[str], ok_data: str, cancel_data: str, **kw) -> ConfirmCard:
    """核准流程用的入口（信任等級固定 SYSTEM）。Markdown、外部內容永遠走不到這裡。"""
    return ConfirmCard(title, list(lines), ok_data, cancel_data, trust=SYSTEM, **kw)


@dataclass
class Document:
    blocks: List[Block] = field(default_factory=list)
    trust: str = ASSISTANT

    def effective(self, block) -> str:
        """這個區塊實際的信任等級：區塊自己的與整份的取低的。"""
        return lowest(self.trust, getattr(block, "trust", EXTERNAL))

    def interactive_ok(self, block) -> bool:
        """這個按鈕群／確認卡能不能變成真的按鈕。"""
        return isinstance(block, INTERACTIVE) and self.effective(block) == SYSTEM

    def to_dict(self) -> dict:
        return {"trust": self.trust, "blocks": [b.to_dict() for b in self.blocks]}


def interactive_as_text(block) -> List[Span]:
    """信任不夠的按鈕群／確認卡：只畫成普通文字（按鈕的字放在〔〕裡），不會變成能按的東西。"""
    if isinstance(block, ConfirmCard):
        labels = [block.title] + list(block.lines) + [f"〔{block.ok_text}〕〔{block.cancel_text}〕"]
        return [Span("\n".join(labels))]
    labels = [f"〔{b.text}〕" for row in block.rows for b in row]
    return [Span(" ".join(labels))]


@dataclass
class Chunk:
    """輸出 adapter 的一則訊息：text 照通道的格式（Telegram 是 Html），按鈕只會在最後一則。"""
    text: str
    reply_markup: Optional[dict] = None


def expose_links(spans: List[Span]) -> List[Span]:
    """external 內容的連結：字跟網址不一樣時，字後面直接放網址（外部內容不能用「好看的字」遮住真正的網址）。"""
    out: List[Span] = []
    for s in spans:
        if s.href and s.text.strip() != s.href:
            out += [Span(s.text, s.bold, s.italic, s.code), Span(" "), Span(s.href, href=s.href)]
        else:
            out.append(s)
    return merge(out)


def map_spans(block, fn):
    """同一個區塊、每一段行內字都換成 fn(spans) 的結果（回新的區塊，不改原本的）。"""
    if isinstance(block, Paragraph):
        return Paragraph(fn(block.spans), trust=block.trust)
    if isinstance(block, Heading):
        return Heading(block.level, fn(block.spans), trust=block.trust)
    if isinstance(block, ListBlock):
        return ListBlock(block.ordered, [ListItem(fn(i.spans), map_spans(i.children, fn) if i.children else None)
                                         for i in block.items], start=block.start, trust=block.trust)
    if isinstance(block, Table):
        return Table([fn(c) for c in block.header], [[fn(c) for c in row] for row in block.rows], trust=block.trust)
    if isinstance(block, Quote):
        return Quote([fn(p) for p in block.paragraphs], trust=block.trust)
    return block


def visible(doc: Document) -> list:
    """輸出 adapter 要畫成字的區塊（三個通道與網頁的 JSON 都從這裡拿）：
    - 能用的按鈕群拿掉（改放 reply_markup）、能用的確認卡留著畫標題與內容；
    - 信任不夠的按鈕群／確認卡一律變成普通文字段落；
    - external 的區塊把連結的網址露出來（expose_links）。"""
    out = []
    for block in doc.blocks:
        if isinstance(block, INTERACTIVE):
            if doc.interactive_ok(block):
                if isinstance(block, ConfirmCard):
                    out.append(block)
                continue
            out.append(Paragraph(interactive_as_text(block), trust=doc.effective(block)))
        elif doc.effective(block) == EXTERNAL:
            out.append(map_spans(block, expose_links))
        else:
            out.append(block)
    return out


def reply_markup(doc: Document) -> Optional[dict]:
    """這份內容裡能用的按鈕（只有 SYSTEM 的按鈕群／確認卡）→ Telegram 形狀的 reply_markup；沒有＝None。"""
    rows = []
    for block in doc.blocks:
        if not doc.interactive_ok(block):
            continue
        group = block.buttons() if isinstance(block, ConfirmCard) else block
        for row in group.rows:
            out = []
            for b in row:
                url = safe_url(b.url) if b.url else None
                if url:
                    out.append({"text": str(b.text)[:64], "url": url})
                elif b.data:
                    out.append({"text": str(b.text)[:64], "callback_data": str(b.data)[:64]})
            if out:
                rows.append(out)
    return {"inline_keyboard": rows} if rows else None
