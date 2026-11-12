"""
輸出 adapter：區塊 → Telegram HTML（parse_mode=HTML，SDK 的 richtext.Html）。

- 只輸出 b、i、code、pre、a、blockquote（ALLOWED）；字一律跳脫 & < >，屬性值再跳脫 "。
- 標題 → <b>；清單 → 「• 」「1. 」開頭的行（第二層縮排、用「◦ 」）；引用 → <blockquote>；程式碼 → <pre>（有語言標記時
  <pre><code class="language-…">）。表格照 tables.layout 降級（2 欄＝「第一欄：第二欄」、窄表＝<pre> 對齊、寬表＝一列一段）。
- 4096 切割（UTF-16 單位，split.Packer）：在區塊邊界切；單一區塊太長才在區塊裡切，每一段補上自己的標籤。
- 按鈕（只有 SYSTEM 的按鈕群／確認卡）→ 最後一則的 reply_markup。
"""

from __future__ import annotations

import html
from typing import List

from isdtelekit.core.richtext import Html

from synox.present import tables
from synox.present.blocks import (
    TONES, Chunk, CodeBlock, ConfirmCard, Document, Heading, ListBlock, Paragraph, Quote, Span, Status, Table,
    merge, reply_markup, visible,
)
from synox.present.split import Atom, Packer, Piece

LIMIT = 4096
ALLOWED = ("b", "i", "code", "pre", "a", "blockquote")


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def attr(text: str) -> str:
    return html.escape(text, quote=True)


def span_atoms(spans: List[Span], bold: bool = False) -> List[Atom]:
    if bold:
        spans = merge([Span(s.text, True, s.italic, s.code, s.href) for s in spans])
    out = []
    for s in spans:
        opens, closes = [], []
        if s.href:
            opens.append(f'<a href="{attr(s.href)}">')
            closes.append("</a>")
        if s.bold or bold:
            opens.append("<b>")
            closes.append("</b>")
        if s.italic:
            opens.append("<i>")
            closes.append("</i>")
        if s.code:
            opens.append("<code>")
            closes.append("</code>")
        out.append(Atom(s.text, "".join(opens), "".join(reversed(closes))))
    return out


def _list_atoms(block: ListBlock, depth: int = 0) -> List[Atom]:
    atoms: List[Atom] = []
    indent = "    " * depth
    for n, item in enumerate(block.items):
        if atoms:
            atoms.append(Atom("\n"))
        marker = f"{block.start + n}. " if block.ordered else ("• " if depth == 0 else "◦ ")
        atoms.append(Atom(indent + marker))
        atoms += span_atoms(item.spans)
        if item.children is not None and item.children.items:
            atoms.append(Atom("\n"))
            atoms += _list_atoms(item.children, depth + 1)
    return atoms


def _table_piece(block: Table) -> Piece:
    lay = tables.layout(block)
    atoms: List[Atom] = []
    if lay.form == "grid":
        lines = tables.grid_lines(lay.header, lay.rows)
        atoms = [Atom(line + ("\n" if i < len(lines) - 1 else "")) for i, line in enumerate(lines)]
        piece = Piece(atoms, "<pre>", "</pre>")
        if lay.note:
            piece.suffix += "\n<i>" + esc(lay.note) + "</i>"
        return piece
    if lay.form == "header":
        atoms.append(Atom(" │ ".join(tables.cell_text(c) for c in lay.header), "<b>", "</b>"))
    elif lay.form == "pairs":
        for row in lay.rows:
            if atoms:
                atoms.append(Atom("\n"))
            atoms += span_atoms(row[0], bold=True) + [Atom("：")] + span_atoms(row[1])
    else:
        names = [tables.cell_text(c) for c in lay.header]
        for row in lay.rows:
            if atoms:
                atoms.append(Atom("\n\n"))
            atoms += span_atoms(row[0], bold=True)
            for name, cell in zip(names[1:], row[1:]):
                atoms += [Atom("\n" + name + "：")] + span_atoms(cell)
    if lay.note:
        atoms += [Atom("\n"), Atom(lay.note, "<i>", "</i>")]
    return Piece(atoms)


def piece_of(block) -> Piece:
    if isinstance(block, Paragraph):
        return Piece(span_atoms(block.spans))
    if isinstance(block, Heading):
        return Piece(span_atoms(block.spans, bold=True))
    if isinstance(block, ListBlock):
        return Piece(_list_atoms(block))
    if isinstance(block, Quote):
        atoms: List[Atom] = []
        for p in block.paragraphs:
            if atoms:
                atoms.append(Atom("\n\n"))
            atoms += span_atoms(p)
        return Piece(atoms, "<blockquote>", "</blockquote>")
    if isinstance(block, CodeBlock):
        lines = (block.code or " ").split("\n")
        atoms = [Atom(line + ("\n" if i < len(lines) - 1 else "")) for i, line in enumerate(lines)]
        head = f'<pre><code class="language-{attr(block.lang)}">' if block.lang else "<pre>"
        tail = "</code></pre>" if block.lang else "</pre>"
        return Piece(atoms, head, tail)
    if isinstance(block, Table):
        return _table_piece(block)
    if isinstance(block, Status):
        return Piece([Atom(TONES.get(block.tone, TONES["info"]) + " "), Atom(block.label, "<b>", "</b>")])
    if isinstance(block, ConfirmCard):
        atoms = [Atom(block.title, "<b>", "</b>")]
        for line in block.lines:
            atoms.append(Atom("\n" + line))
        return Piece(atoms)
    return Piece()


def render(doc: Document) -> List[Chunk]:
    packer = Packer(LIMIT, esc)
    texts = packer.pack([piece_of(b) for b in visible(doc)])
    if not texts:
        texts = ["·"]
    chunks = [Chunk(Html(t)) for t in texts]
    chunks[-1].reply_markup = reply_markup(doc)
    return chunks
