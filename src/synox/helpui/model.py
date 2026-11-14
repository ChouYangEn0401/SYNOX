"""
/help 的資料（純資料，三個通道各自畫）：這個人看得到哪些工具、每個工具「最常用」的指令、每個指令的白話與範例。

    tools(app, user)                         # [Tool, …]：工具（pack）在前，系統指令的群組在後，基本指令（/start、/help…）最後
    find(app, user, "記帳")                  # 照 id、名字、標題找一個工具（或一個指令 → ("command", node)）
    command(app, node, user, private)        # 一張指令卡的資料：白話、效果、範例（照這個人的叫法）、要給什麼
    help_json(app, user)                     # 網頁 GET /api/help（「💡 範例」面板）

可見性只問 registry.visible（跟真的執行時同一個 authorize；不另外維護隱藏清單）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from isdtelekit.core.registry import DANGER, READ, Node

from synox.helpui import examples as ex_mod

BASICS_ID = "_basics"
BASICS_TITLE = "🧭 基本"
BASICS_SUMMARY = "開始、說明、教學"
HIDDEN_PATHS = ("agent.ai_approve",)
MAX_FEATURED = 5
EFFECT_BADGE = {READ: "🟢 只看不改", "write": "🟡 會寫入", DANGER: "🔴 危險：會先問你"}
_ASIDE = re.compile(r"[（(][^（）()]*[）)]")


@dataclass
class Tool:
    id: str
    title: str
    summary: str
    nodes: List[Node] = field(default_factory=list)
    stage: str = ""                    # 「🧪 alpha」；系統的指令沒有
    pack: str = ""                     # pack 名字；系統的是 ""

    @property
    def button(self) -> str:
        return self.title


def _visible_leaves(app, user, group: Node) -> List[Node]:
    reg = app.registry
    return [n for n in group.walk() if not n.is_group and n.path not in HIDDEN_PATHS and reg.visible(user, n)]


def tools(app, user) -> List[Tool]:
    reg = app.registry
    out: List[Tool] = []
    seen = set()
    for pack in app.extras.get("synox_packs", []) or []:
        m = pack.manifest
        group = reg.node(m.group)
        seen.add(m.group)
        if group is None or not reg.visible(user, group):
            continue
        leaves = _visible_leaves(app, user, group)
        if leaves:
            out.append(Tool(m.group, m.title, m.summary, leaves, getattr(m, "stage_label", ""), m.name))
    for node in reg.root.children.values():
        if not node.is_group or node.name in seen or not reg.visible(user, node):
            continue
        leaves = _visible_leaves(app, user, node)
        if leaves:
            out.append(Tool(node.name, node.title, node.summary, leaves))
    basics = [n for n in reg.root.children.values() if not n.is_group and reg.visible(user, n)]
    if basics:
        out.append(Tool(BASICS_ID, BASICS_TITLE, BASICS_SUMMARY, basics))
    return out


def tool_of(app, user, tool_id: str) -> Optional[Tool]:
    return next((t for t in tools(app, user) if t.id == tool_id), None)


def find(app, user, query: str) -> Tuple[str, object]:
    """/help <字>：("tool", Tool)、("command", Node) 或 ("", None)。"""
    q = (query or "").strip().lstrip("/").lower()
    if not q:
        return "", None
    all_tools = tools(app, user)
    for t in all_tools:
        if q in (t.id, t.pack.lower()):
            return "tool", t
    for t in all_tools:
        for n in t.nodes:
            if q in [c.lstrip("/") for c in n.names] or q == n.path.replace(".", "_"):
                return "command", n
    for t in all_tools:
        if q in t.title.lower() or (t.summary and q in t.summary.lower()):
            return "tool", t
    return "", None


def featured(app, tool: Tool) -> List[Node]:
    """「最常用」：help.featured 有寫照它；沒寫＝主要動作＋有範例的（照宣告順序），最多 5 個；都沒有＝前幾個。"""
    declared = (app.extras.get("synox_help_featured") or {}).get(tool.id) or []
    by_name = {n.name: n for n in tool.nodes if n.parent is not None and n.parent.name == tool.id}
    picked = [by_name[name] for name in declared if name in by_name]
    if not picked:
        picked = [n for n in tool.nodes if n.default] + \
                 [n for n in tool.nodes if not n.default and ex_mod.doc_of(app, n).get("examples")]
    if not picked:
        picked = list(tool.nodes)
    return unique(picked)[:MAX_FEATURED]


def unique(nodes) -> List[Node]:
    """去掉重複的節點（Node 不能當 dict 的鍵：比的是身分）。"""
    seen, out = set(), []
    for n in nodes:
        if id(n) not in seen:
            seen.add(id(n))
            out.append(n)
    return out


def short_ask(ask: str) -> str:
    """欄位問句去掉括號裡的補充（「哪一天（預設今天；例如 …）」→「哪一天」）。"""
    return _ASIDE.sub("", ask or "").strip() or ask


def title_of(app, node: Node) -> str:
    """一個指令的白話名字：plain 有寫用 plain，沒寫用 summary（去掉括號補充）。"""
    doc = ex_mod.doc_of(app, node)
    return doc.get("plain") or short_ask(node.summary) or node.command


def can_try(node: Node, args: List[str]) -> bool:
    """「試試看」：只有唯讀、不用 /sudo、不用驗證碼、不會開問答的指令（寫入與危險的範例永遠只是字）。"""
    if node.effect != READ or node.interactive or node.policy.elevated:
        return False
    if any(getattr(f, "fresh_code", False) for f in node.fields):
        return False
    try:
        return node.effect_of(args) == READ
    except Exception:
        return False


def command(app, node: Node, user=None, private: bool = True) -> dict:
    """一張指令卡的資料。examples[].text＝照這個人的叫法顯示的整句（private=False：共用的頻道，一律正式的 /指令）；
    run＝正式的整句（「試試看」跑的就是它）。"""
    from synox import aliases
    tg_id = getattr(user, "tg_id", None)
    shown = aliases.shown(app, tg_id, node, private)
    canonical = aliases.command_of(node)
    doc = ex_mod.doc_of(app, node)
    items = list(doc.get("examples") or [])
    fields = [f for f in node.fields if not getattr(f, "fresh_code", False)]
    if not items and not any(f.required for f in fields) and not node.usage:
        items = [{"text": ""}]                        # 不用參數的指令：指令本身就是範例
    examples = []
    for e in items:
        args = e["text"]
        ex = {"text": f"{shown} {args}".rstrip(), "run": f"{canonical} {args}".rstrip()}
        if e.get("note"):
            ex["note"] = e["note"]
        ex["try"] = can_try(node, args.split()) and not ex_mod.node_runnable(node, args)
        examples.append(ex)
    return {"path": node.path, "command": shown, "canonical": canonical, "title": title_of(app, node),
            "plain": doc.get("plain", ""), "summary": node.summary, "effect": node.effect,
            "badge": EFFECT_BADGE.get(node.effect, ""), "examples": examples,
            "required": [short_ask(f.ask) for f in fields if f.required],
            "optional": [short_ask(f.ask) for f in fields if not f.required],
            "usage": "" if fields or not node.usage else node.usage,
            "alias_suggest": list(doc.get("alias_suggest") or [])}


def help_json(app, user) -> dict:
    """網頁「💡 範例」面板：工具 → 指令（白話、範例照這個人的叫法）。看不到的工具不在裡面。"""
    out = []
    for t in tools(app, user):
        feat = featured(app, t)
        cmds = [command(app, n, user, True) for n in t.nodes]
        out.append({"id": t.id, "title": t.title, "summary": t.summary, "stage": t.stage,
                    "featured": [n.path for n in feat], "commands": cmds})
    from synox import aliases
    tab = aliases.table_of(app, user.tg_id)
    return {"tools": out, "prefix": tab.prefix}
