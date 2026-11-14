"""
/help 的三層卡片 → 一則訊息（字＋按鈕）。同一份資料（model.py），三個通道各自的樣子：

- Telegram：HTML（範例用 <code>，點一下就複製）；按鈕＝inline keyboard，原地換頁（edit_message_text）。
- Discord：同一份字（純文字）與按鈕（rest.components 轉；一列最多 5 顆、最多 5 列，所以這裡每張卡最多 5 列）。
- 網頁：純文字＋一個 examples 區塊（static/helpdock.js 畫成小標籤：點了＝填進輸入框，**不送出**）。

按鈕 callback（≤ 64 位元組；放不下的不出按鈕）：
    hp:h:<頁>                 第 0 層：你有哪些工具
    hp:t:<工具 id>:<頁>        第 1 層：工具卡
    hp:c:<節點路徑>            第 2 層：指令卡
    hp:x:<節點路徑>:<第幾個>    「試試看」（只有唯讀的指令；以按的人的身分、經 dispatcher 跑，同一個 authorize）
    hp:tour                    新手教學（/tutorial）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from isdtelekit.core.richtext import Html, esc

from synox.helpui import model, text as T

PREFIX = "hp:"
CALLBACK_MAX = 64
PAGE_TOOLS = 6                 # 第 0 層一頁幾顆工具（2 顆一列 → 3 列；加翻頁、教學 ≤ 5 列，Discord 放得下）
PAGE_COMMANDS = 6
MAX_CARD = 900                 # 每張卡的字數預算（Telegram 4096、Discord 2000 都是一則）


@dataclass
class Card:
    lines: List[str]                                   # 純文字的每一行
    html_lines: List[str]                              # Telegram HTML 的每一行（動態的字都 esc 過）
    keyboard: dict = field(default_factory=dict)
    examples: List[dict] = field(default_factory=list)  # 網頁的小標籤：[{"text", "note"}]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def html(self) -> Html:
        return Html("\n".join(self.html_lines))


def _cb(data: str) -> Optional[str]:
    return data if len(data.encode("utf-8")) <= CALLBACK_MAX else None


def _rows(buttons: List[dict], per_row: int = 2) -> List[List[dict]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _button(label: str, data: str) -> Optional[dict]:
    data = _cb(data)
    return {"text": label[:40], "callback_data": data} if data else None


def _pager(prefix: str, page: int, pages: int) -> List[dict]:
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append({"text": T.PREV_PAGE, "callback_data": f"{prefix}{page - 1}"})
    row.append({"text": f"{page + 1}／{pages}", "callback_data": f"{prefix}{page}"})
    if page + 1 < pages:
        row.append({"text": T.NEXT_PAGE, "callback_data": f"{prefix}{page + 1}"})
    return row


def _same(text: str) -> tuple:
    """純文字與 HTML 一樣的一行。"""
    return text, esc(text)


def home(app, user, page: int = 0, *, has_ai: bool = False, tutorial: bool = False) -> Card:
    """第 0 層：沒有指令清單，只有工具按鈕（擁有者 2026-11-14 決定 1）。"""
    all_tools = model.tools(app, user)
    first = T.HOME_AI if has_ai else T.HOME_NO_AI
    lines = [first, T.HOME_PICK if all_tools else T.HOME_NONE, "", T.HOME_ALL]
    card = Card(list(lines), [esc(x) for x in lines])
    pages = max(1, (len(all_tools) + PAGE_TOOLS - 1) // PAGE_TOOLS)
    page = min(max(0, page), pages - 1)
    shown = all_tools[page * PAGE_TOOLS:(page + 1) * PAGE_TOOLS]
    buttons = [b for b in (_button(t.button, f"{PREFIX}t:{t.id}:0") for t in shown) if b]
    rows = _rows(buttons)
    pager = _pager(f"{PREFIX}h:", page, pages)
    if pager:
        rows.append(pager)
    if tutorial:
        rows.append([{"text": T.TUTORIAL_BUTTON, "callback_data": f"{PREFIX}tour"}])
    card.keyboard = {"inline_keyboard": rows}
    return card


def tool_card(app, user, tool: model.Tool, page: int = 0, private: bool = True, buttons: bool = True) -> Card:
    """第 1 層：一個工具會什麼、最常用的幾個怎麼打；底下每個指令一顆按鈕。"""
    head = tool.title + (f"　{tool.stage}" if tool.stage else "")
    lines, html = [head], [f"<b>{esc(head)}</b>"]
    if tool.summary:
        lines.append(tool.summary)
        html.append(esc(tool.summary))
    feat = model.featured(app, tool)
    lines += ["", T.FEATURED]
    html += ["", esc(T.FEATURED)]
    chips: List[dict] = []
    for node in feat:
        info = model.command(app, node, user, private)
        ex = info["examples"][0] if info["examples"] else None
        if ex:
            lines.append(f"• {info['title']}　{T.EG}{ex['text']}")
            html.append(f"• {esc(info['title'])}　{esc(T.EG)}<code>{esc(ex['text'])}</code>")
            chips.append({"text": ex["text"], "note": info["title"]})
        else:
            lines.append(f"• {info['title']}　{info['command']}")
            html.append(f"• {esc(info['title'])}　<code>{esc(info['command'])}</code>")
    rest = len(tool.nodes) - len(feat)
    if rest > 0:
        lines += ["", T.MORE_BELOW.format(n=rest)]
        html += ["", esc(T.MORE_BELOW.format(n=rest))]
    card = Card(lines, html, examples=chips)
    if not buttons:
        return card
    nodes = model.unique(feat + tool.nodes)
    pages = max(1, (len(nodes) + PAGE_COMMANDS - 1) // PAGE_COMMANDS)
    page = min(max(0, page), pages - 1)
    btns = [b for b in (_button(model.title_of(app, n), f"{PREFIX}c:{n.path}")
                        for n in nodes[page * PAGE_COMMANDS:(page + 1) * PAGE_COMMANDS]) if b]
    rows = _rows(btns)
    pager = _pager(f"{PREFIX}t:{tool.id}:", page, pages)
    if pager:
        rows.append(pager)
    rows.append([{"text": T.BACK_HOME, "callback_data": f"{PREFIX}h:0"}])
    card.keyboard = {"inline_keyboard": rows}
    return card


def command_card(app, user, node, tool: Optional[model.Tool], private: bool = True) -> Card:
    """第 2 層：一句白話＋唯讀／會寫入／危險＋最多 3 個範例＋要給什麼。"""
    info = model.command(app, node, user, private)
    icon = tool.title.split(" ", 1)[0] if tool and " " in tool.title else ""
    head = f"{icon} {info['title']}".strip()
    badge = info["badge"]
    lines = [f"{head}　{badge}".rstrip()]
    html = [f"<b>{esc(head)}</b>　{esc(badge)}".rstrip()]
    chips: List[dict] = []
    if info["examples"]:
        lines += ["", T.TYPE_LIKE]
        html += ["", esc(T.TYPE_LIKE)]
        for ex in info["examples"]:
            note = f"　← {ex['note']}" if ex.get("note") else ""
            lines.append(f"  {ex['text']}{note}")
            html.append(f"  <code>{esc(ex['text'])}</code>{esc(note)}")
            chips.append({"text": ex["text"], **({"note": ex["note"]} if ex.get("note") else {})})
    elif info["usage"]:
        lines += ["", T.TYPE_LIKE, f"  {info['command']} {info['usage']}"]
        html += ["", esc(T.TYPE_LIKE), f"  <code>{esc(info['command'])}</code> {esc(info['usage'])}"]
    need = []
    if info["required"]:
        need.append(T.NEED + "、".join(info["required"]))
    if info["optional"]:
        need.append(T.OPTIONAL + "、".join(info["optional"]))
    if need:
        lines += ["", "　".join(need)]
        html += ["", esc("　".join(need))]
    if node.effect != "read":
        lines += ["", T.WRITE_NOTE]
        html += ["", esc(T.WRITE_NOTE)]
    card = Card(lines, html, examples=chips)
    rows: List[List[dict]] = []
    tries = [i for i, ex in enumerate(info["examples"]) if ex["try"]]
    if tries:
        b = _button(T.TRY, f"{PREFIX}x:{node.path}:{tries[0]}")
        if b:
            rows.append([b])
    back = []
    if tool is not None:
        b = _button(T.BACK_TOOL.format(t=tool.title), f"{PREFIX}t:{tool.id}:0")
        if b:
            back.append(b)
    back.append({"text": T.BACK_HOME, "callback_data": f"{PREFIX}h:0"})
    rows.append(back)
    card.keyboard = {"inline_keyboard": rows}
    return card


def tool_for(app, user, node) -> Optional[model.Tool]:
    """這個指令在哪個工具裡（第 2 層的「← 回」）。"""
    for t in model.tools(app, user):
        if any(n is node for n in t.nodes):
            return t
    return None
