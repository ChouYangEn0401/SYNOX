"""
輸出 adapter：區塊 → Discord 的 Markdown 子集。

- 字一律跳脫 Markdown 特殊字元（\\ * _ ~ ` | < [ ] @，行首的 # > - + 與「1.」），不只 external：區塊已經是解析過的結果，
  字裡剩下的符號都是「字」，不跳脫的話 Discord 會再解讀一次（@everyone、<@id> 也不會變成提及）。
- 粗體 **、斜體 *、行內程式碼 `、連結：寫成 [字](網址)；字＝網址的只放網址。external 的連結在 blocks.visible
  就已經把網址露出來（外部內容不能用遮罩連結假裝成別的網址）。
- 標題 → ## ／###；清單 → 「- 」「1. 」，第二層縮兩格；引用 → 每行「> 」；程式碼 → ``` 圍欄（字裡的 ``` 插零寬空白拆開）。
- Discord 不支援表格：照 tables.layout 降級（窄表用程式碼區塊對齊、寬表一列一段、2 欄一列一行）。
- 2000 切割（UTF-16 單位，split.Packer）：切在程式碼區塊裡時，這一則結尾補 ```、下一則開頭重開（含語言標記）。
- 按鈕（只有 SYSTEM 的）→ 最後一則的 reply_markup（DiscordChannel 轉成按鈕元件）。
"""

from __future__ import annotations

import re
from typing import List

from synox.present import tables
from synox.present.blocks import (
    EXTERNAL, TONES, Chunk, CodeBlock, ConfirmCard, Document, Heading, ListBlock, Paragraph, Quote, Span, Status,
    Table, merge, reply_markup, visible,
)
from synox.present.split import Atom, Packer, Piece

LIMIT = 2000
ZWSP = "​"

_ANY = re.compile(r"([\\*_~`|<\[\]@])")
_LINE_MARK = re.compile(r"(^|\n)([ \t]*)([#>+\-])")
_LINE_NUM = re.compile(r"(^|\n)([ \t]*)(\d+)([.)])")


def esc(text: str) -> str:
    text = _ANY.sub(r"\\\1", text)
    text = _LINE_MARK.sub(r"\1\2\\\3", text)
    return _LINE_NUM.sub(r"\1\2\3\\\4", text)


def _code_text(text: str) -> str:
    return text.replace("```", "`" + ZWSP + "``")


def _url(url: str) -> str:
    return url.replace("(", "%28").replace(")", "%29")


def span_atoms(spans: List[Span], trust: str, bold: bool = False) -> List[Atom]:
    if bold:
        spans = merge([Span(s.text, True, s.italic, s.code, s.href) for s in spans])
    out: List[Atom] = []
    for s in spans:
        mark = ("**" if (s.bold or bold) else "") + ("*" if s.italic else "")
        if out and mark and out[-1].close.endswith("*"):
            out.append(Atom(ZWSP, escape=False))         # 「**a***b*」會黏在一起被誤讀：中間放一個零寬空白
        if s.code:
            fence = "``" if "`" in s.text else "`"
            pad = " " if s.text.startswith("`") or s.text.endswith("`") else ""
            out.append(Atom(s.text.replace("\n", " "), mark + fence + pad, pad + fence + mark[::-1], escape=False))
            continue
        if s.href and (trust == EXTERNAL or s.text.strip() == s.href):
            if s.text.strip() != s.href:
                out.append(Atom(s.text + " ", mark, mark[::-1]))
            out.append(Atom(s.href, escape=False))      # 只放網址（Discord 自己變連結）
            continue
        if s.href:
            out.append(Atom(s.text, mark + "[", "](" + _url(s.href) + ")" + mark[::-1]))
            continue
        out.append(Atom(s.text, mark, mark[::-1]))
    return out


def _list_atoms(block: ListBlock, trust: str, depth: int = 0) -> List[Atom]:
    atoms: List[Atom] = []
    for n, item in enumerate(block.items):
        if atoms:
            atoms.append(Atom("\n"))
        marker = f"{block.start + n}. " if block.ordered else "- "
        atoms.append(Atom("  " * depth + marker, escape=False))
        atoms += span_atoms(item.spans, trust)
        if item.children is not None and item.children.items:
            atoms.append(Atom("\n"))
            atoms += _list_atoms(item.children, trust, depth + 1)
    return atoms


def _fenced(lines: List[str], lang: str = "") -> Piece:
    atoms = [Atom(_code_text(line) + ("\n" if i < len(lines) - 1 else ""), escape=False)
             for i, line in enumerate(lines)]
    return Piece(atoms, "```" + lang + "\n", "\n```")


def _table_piece(block: Table, trust: str) -> List[Piece]:
    lay = tables.layout(block)
    note = [Piece([Atom(lay.note, "*", "*")])] if lay.note else []
    if lay.form == "grid":
        return [_fenced(tables.grid_lines(lay.header, lay.rows))] + note
    atoms: List[Atom] = []
    if lay.form == "header":
        atoms.append(Atom(" │ ".join(tables.cell_text(c) for c in lay.header), "**", "**"))
    elif lay.form == "pairs":
        for row in lay.rows:
            if atoms:
                atoms.append(Atom("\n"))
            atoms += span_atoms(row[0], trust, bold=True) + [Atom("：")] + span_atoms(row[1], trust)
    else:
        names = [tables.cell_text(c) for c in lay.header]
        for row in lay.rows:
            if atoms:
                atoms.append(Atom("\n\n"))
            atoms += span_atoms(row[0], trust, bold=True)
            for name, cell in zip(names[1:], row[1:]):
                atoms += [Atom("\n"), Atom(name + "：")] + span_atoms(cell, trust)
    return [Piece(atoms)] + note


def pieces_of(block, trust: str) -> List[Piece]:
    if isinstance(block, Paragraph):
        return [Piece(span_atoms(block.spans, trust))]
    if isinstance(block, Heading):
        return [Piece([Atom("## " if block.level <= 2 else "### ", escape=False)] + span_atoms(block.spans, trust))]
    if isinstance(block, ListBlock):
        return [Piece(_list_atoms(block, trust))]
    if isinstance(block, Quote):
        atoms: List[Atom] = []
        for p in block.paragraphs:
            if atoms:
                atoms.append(Atom("\n>\n", escape=False))
            for s in p:                              # 段落裡的換行：每一行都要自己的「> 」
                parts = s.text.split("\n")
                for k, part in enumerate(parts):
                    if k:
                        atoms.append(Atom("\n", escape=False))
                    if not atoms or atoms[-1].text.endswith("\n"):
                        atoms.append(Atom("> ", escape=False))
                    if part:
                        atoms += span_atoms([Span(part, s.bold, s.italic, s.code, s.href)], trust)
        return [Piece(atoms)]
    if isinstance(block, CodeBlock):
        return [_fenced((block.code or " ").split("\n"), block.lang)]
    if isinstance(block, Table):
        return _table_piece(block, trust)
    if isinstance(block, Status):
        return [Piece([Atom(TONES.get(block.tone, TONES["info"]) + " ", escape=False), Atom(block.label, "**", "**")])]
    if isinstance(block, ConfirmCard):
        atoms = [Atom(block.title, "**", "**")]
        for line in block.lines:
            atoms += [Atom("\n", escape=False), Atom(line)]
        return [Piece(atoms)]
    return []


def render(doc: Document) -> List[Chunk]:
    packer = Packer(LIMIT, esc)
    pieces = []
    for block in visible(doc):
        pieces += pieces_of(block, doc.effective(block))
    texts = packer.pack(pieces) or ["·"]
    chunks = [Chunk(t) for t in texts]
    chunks[-1].reply_markup = reply_markup(doc)
    return chunks
