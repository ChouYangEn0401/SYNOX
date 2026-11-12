"""
輸出 adapter：區塊 → 網頁。兩種形狀，內容一樣：

- `to_html(doc)`：伺服器端產生、**已跳脫**的 HTML 字串（黃金檔 web.html 比的是這個）。只用白名單標籤
  （ALLOWED：p、h3～h5、ul、ol、li、table 系列、pre、code、b、i、a、blockquote、span class=…）；
  屬性只有 a 的 href／rel、span 的 class、ol 的 start（數字）；不輸出 style、on*、<script>、外部資源。表格用真的 <table>，不降級。
- `wire(doc)`：給瀏覽器的 JSON 區塊（`WebText.blocks`）。對話頁（static/app.html 的 renderBlocks）用
  createElement＋textContent 畫——**實際接線用這個**，因為 AGENT.md invariant 9 規定網頁的字一律 textContent，
  app.html 也從來不用 innerHTML；伺服器產生的 HTML 不需要塞進頁面。
- 按鈕（只有 SYSTEM 的）照舊走訊息的 buttons（WebChannel 存 reply_markup），不放進區塊。
"""

from __future__ import annotations

import html
from typing import List

from synox.present.blocks import (
    TONES, Chunk, CodeBlock, ConfirmCard, Document, Heading, ListBlock, Paragraph, Quote, Span, Status, Table,
    reply_markup, visible,
)

ALLOWED = ("p", "h3", "h4", "h5", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
           "pre", "code", "b", "i", "a", "blockquote", "span")


class WebText(str):
    """送給 WebChannel 的字：字串本身是原本的文字（對話紀錄、預覽、常駐助理讀的都是它），`.blocks` 是要畫的區塊。
    其他 channel 拿到它就是一般字串。"""

    def __new__(cls, value: str, blocks: list):
        obj = super().__new__(cls, value)
        obj.blocks = blocks
        return obj


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def attr(text: str) -> str:
    return html.escape(text, quote=True)


def spans_html(spans: List[Span]) -> str:
    out = []
    for s in spans:
        body = esc(s.text)
        if s.code:
            body = f"<code>{body}</code>"
        if s.italic:
            body = f"<i>{body}</i>"
        if s.bold:
            body = f"<b>{body}</b>"
        if s.href:
            body = f'<a href="{attr(s.href)}" rel="noopener noreferrer">{body}</a>'
        out.append(body)
    return "".join(out)


def _list_html(block: ListBlock) -> str:
    tag = "ol" if block.ordered else "ul"
    items = []
    for item in block.items:
        inner = spans_html(item.spans)
        if item.children is not None and item.children.items:
            inner += _list_html(item.children)
        items.append(f"<li>{inner}</li>")
    start = f' start="{int(block.start)}"' if block.ordered and block.start != 1 else ""
    return f"<{tag}{start}>{''.join(items)}</{tag}>"


def block_html(block) -> str:
    if isinstance(block, Paragraph):
        return f"<p>{spans_html(block.spans)}</p>"
    if isinstance(block, Heading):
        tag = f"h{min(5, block.level + 2)}"
        return f"<{tag}>{spans_html(block.spans)}</{tag}>"
    if isinstance(block, ListBlock):
        return _list_html(block)
    if isinstance(block, Quote):
        return "<blockquote>" + "".join(f"<p>{spans_html(p)}</p>" for p in block.paragraphs) + "</blockquote>"
    if isinstance(block, CodeBlock):
        return f"<pre><code>{esc(block.code)}</code></pre>"
    if isinstance(block, Table):
        head = "".join(f"<th>{spans_html(c)}</th>" for c in block.header)
        rows = "".join("<tr>" + "".join(f"<td>{spans_html(c)}</td>" for c in row) + "</tr>" for row in block.rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"
    if isinstance(block, Status):
        tone = block.tone if block.tone in TONES else "info"
        return f'<p><span class="status status-{tone}">{esc(TONES[tone] + " " + block.label)}</span></p>'
    if isinstance(block, ConfirmCard):
        return f"<p><b>{esc(block.title)}</b></p>" + "".join(f"<p>{esc(line)}</p>" for line in block.lines)
    return ""


def to_html(doc: Document) -> str:
    return "\n".join(h for h in (block_html(b) for b in visible(doc)) if h)


def wire(doc: Document) -> List[dict]:
    """給瀏覽器的區塊（JSON）。確認卡只留標題與內容（按鈕走訊息的 buttons），回呼資料不進區塊。"""
    out = []
    for block in visible(doc):
        if isinstance(block, ConfirmCard):
            out.append({"type": "confirm", "trust": block.trust, "title": block.title, "lines": list(block.lines)})
        else:
            out.append(block.to_dict())
    return out


def render(doc: Document, source: str = "") -> List[Chunk]:
    """網頁沒有長度上限：一則。text 是 WebText（字串＝原本的文字，`.blocks`＝要畫的區塊）。"""
    return [Chunk(WebText(source, wire(doc)), reply_markup(doc))]
