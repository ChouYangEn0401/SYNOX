"""
假工具：把一題的 tools 掛成指令樹的葉節點（跟 pack 的指令同一種東西），所以 AI 看到的工具清單、ai_decision、
第 4 關參數驗證、核准卡全部照真的迴圈走；葉節點被執行時不做任何事，只照題目的 results 回一段字，並記下來。

- 工具名 `群組__動作` → 群組 `群組`、葉節點 `動作`（跟 pack 一樣：note__add＝/note_add）。群組名跟內建指令撞名就拒。
- effect：read／write／danger（danger 一律核准卡）；confirm: true＝pack 的 commands[].confirm（AI 呼叫前先出卡）。
- 參數＝node.fields（全部字串；required、choices 照題目）。
- 回什麼：results 由上往下第一個 when 全部對得上的；reply 裡的 {參數名} 換成這次的值。都對不上＝NO_MATCH。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from isdtelekit.core.registry import DANGER, READ, WRITE, Field

from synox.evals.cases import Case, ToolDef, args_match
from synox.packs import kit

EFFECT = {"read": READ, "write": WRITE, "danger": DANGER}
NO_MATCH = "（找不到符合的資料）"
META_KEY = "synox_tool_meta"


class FakeToolError(ValueError):
    pass


@dataclass
class Executed:
    tool: str
    args: Dict[str, str]
    result: str


@dataclass
class ToolLog:
    executed: List[Executed] = field(default_factory=list)


def fields_of(tool: ToolDef):
    return tuple(Field(p["name"], p["ask"], required=bool(p.get("required")),
                       choices=tuple(str(c).lower() for c in p.get("choices") or ()))
                 for p in tool.params)


def reply_for(tool: ToolDef, values: Dict[str, str]) -> str:
    for rule in tool.results:
        if args_match(rule.get("when") or {}, values):
            text = rule["reply"]
            for key, value in values.items():
                text = text.replace("{" + key + "}", value)
            return text
    return NO_MATCH


def install(app, case: Case) -> ToolLog:
    """把這題的假工具掛上 app 的指令樹；回一份執行紀錄（每次被執行就加一筆）。"""
    registry = app.registry
    log = ToolLog()
    groups: Dict[str, object] = {}
    for tool in case.tools:
        group_name, leaf = tool.name.split("__", 1)
        if group_name not in groups:
            if registry.node(group_name) is not None or registry.is_known(group_name):
                raise FakeToolError(f"{case.id}：假工具的群組 {group_name!r} 跟 SYNOX 內建的指令撞名，換一個名字")
            groups[group_name] = registry.define_group(group_name, f"（評測）{group_name}", "評測用的假工具",
                                                       private_only=True)
        fields = fields_of(tool)

        def run(api, chat_id, user, argv, _tool=tool, _fields=fields):
            values, _missing, _errors = kit.parse_args(_fields, argv, positional=0)
            text = reply_for(_tool, values)
            log.executed.append(Executed(_tool.name, dict(values), text))
            api.send_message(chat_id, text)

        node = groups[group_name].leaf(leaf, run, tool.summary, effect=EFFECT[tool.effect])
        node.fields = fields
        if tool.confirm:
            app.extras.setdefault(META_KEY, {})[node.path] = {"confirm": True}
    return log
