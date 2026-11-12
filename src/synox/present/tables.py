"""
表格在不支援表格的通道（Telegram、Discord）怎麼降級——兩邊共用同一套判斷，網頁一律用真的 <table>。

    2 欄                         → pairs：一列一行「第一欄：第二欄」
    窄表（每行顯示寬度 ≤ NARROW） → grid：等寬對齊（Telegram <pre>、Discord 程式碼區塊），中文算 2 格
    寬表                         → cards：一列一小段（第一欄當小標題，其餘「欄名：值」）
    超過 MAX_ROWS 列             → 只放前 SHOW_ROWS 列，最後加一行說明
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from synox.present.blocks import Span, Table, plain_of
from synox.present.width import pad, width

NARROW = 36
MAX_ROWS = 30
SHOW_ROWS = 20
GAP = "  "


@dataclass
class Layout:
    form: str                         # pairs | grid | cards | header
    header: List[List[Span]]
    rows: List[List[List[Span]]]
    note: Optional[str] = None


def cell_text(spans: List[Span]) -> str:
    return " ".join(plain_of(spans).split())


def too_long_note(total: int) -> str:
    return f"（表格太長：共 {total} 列，這裡只列前 {SHOW_ROWS} 列；完整內容請在網頁看）"


def layout(table: Table) -> Layout:
    rows = table.rows
    note = None
    if len(rows) > MAX_ROWS:
        note = too_long_note(len(rows))
        rows = rows[:SHOW_ROWS]
    n = len(table.header)
    if not rows:
        return Layout("header", table.header, [], note)
    if n == 2:
        return Layout("pairs", table.header, rows, note)
    if max(width(line) for line in grid_lines(table.header, rows)) <= NARROW:
        return Layout("grid", table.header, rows, note)
    return Layout("cards", table.header, rows, note)


def grid_lines(header: List[List[Span]], rows: List[List[List[Span]]]) -> List[str]:
    """等寬對齊的幾行：表頭、分隔線、每一列。"""
    texts = [[cell_text(c) for c in header]] + [[cell_text(c) for c in row] for row in rows]
    n = len(header)
    widths = [max(width(r[i]) for r in texts) for i in range(n)]
    lines = []
    for idx, r in enumerate(texts):
        lines.append(GAP.join(pad(r[i], widths[i]) if i < n - 1 else r[i] for i in range(n)).rstrip())
        if idx == 0:
            lines.append(GAP.join("-" * w for w in widths))
    return lines
