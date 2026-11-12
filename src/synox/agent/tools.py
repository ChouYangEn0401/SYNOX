"""
指令樹的葉節點 → AI 的工具（ToolSpec）。

- 名稱＝節點路徑，`.` 換成 `__`（money.add → money__add）；node_for(name) 反查。
- 說明＝summary＋用法（＋危險的會先送確認卡）。
- 參數＝node.fields → JSON schema（全部 string；required 照 Field.required）。**驗證碼欄位（fresh_code）不給**——
  驗證碼永遠不經 AI（spec §7.1）。沒有 fields 但有 usage 的節點給一個 `args` 字串參數。
- 哪些節點給 AI：由呼叫端傳入的 decide(node)（loop.ai_decision）決定，這裡不自己判斷——AI 能不能用一個節點只有一個判斷。
- schema 寫 additionalProperties: false 與 maxLength；真正擋的是第 4 關 agent/validate.py（模型不一定照 schema）。
- **schema 模式**（只有 MCP 工具，pack.json 的 mcp.schema_tools；packs/mcp_schema.py）：參數不是平面字串，
  而是那個工具正規化過的 inputSchema（保留整數、布林、陣列、物件），呼叫時整包結構化參數交給 MCP 後端，不轉成 argv。
- 工具參數 → 指令參數（argv）：每個欄位變成一個 `key=value` 片段（kit.parse_args 與 SDK 的 parse_fields 都認得）。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from isdtelekit.core.registry import DANGER, CommandRegistry, Node

from synox.agent.validate import MAX_LEN
from synox.llm.base import ToolSpec

SEP = "__"


def tool_name(node: Node) -> str:
    return node.path.replace(".", SEP)


def node_for(registry: CommandRegistry, name: str) -> Optional[Node]:
    node = registry.node(str(name or "").replace(SEP, "."))
    return None if node is None or node.is_group else node


def schema(node: Node, app=None) -> dict:
    nested = schema_mode(app, node)
    if nested is not None:
        from synox.packs import mcp_schema
        return mcp_schema.tool_schema(nested)
    props: Dict[str, dict] = {}
    required: List[str] = []
    if node.fields:
        for f in node.fields:
            if f.fresh_code:
                continue
            desc = f.ask + (f"（可選：{'/'.join(f.choices)}）" if f.choices else "") + \
                (f"（預設 {f.default}）" if f.default else "")
            props[f.name] = {"type": "string", "description": desc, "maxLength": MAX_LEN}
            if f.required:
                required.append(f.name)
    elif node.usage:
        props["args"] = {"type": "string", "description": f"參數，格式：{node.usage}", "maxLength": MAX_LEN}
    out = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


def description(node: Node) -> str:
    parts = [node.summary or node.title]
    if node.usage:
        parts.append(f"（人打的用法：{node.command} {node.usage}）")
    if node.effect == DANGER or node.wraps is not None:
        parts.append("危險或包著別的指令：系統會先送確認卡給使用者按，按了才執行。")
    return " ".join(parts)


def schema_mode(app, node: Node) -> Optional[dict]:
    """這個節點是 schema 模式的話回它正規化過的 schema（只有 packs/mcp.py 的 install 會標），否則 None。"""
    if app is None:
        return None
    from synox.agent.validate import schema_of
    return schema_of(app, node)


def build(registry: CommandRegistry, decide: Callable[[Node], object], app=None) -> List[ToolSpec]:
    return [ToolSpec(tool_name(n), description(n), schema(n, app)) for n in registry.leaves() if decide(n) is not None]


def to_argv(node: Node, args: dict) -> List[str]:
    """工具參數 → 指令的 args。表單欄位一律 key=value；沒有欄位的節點拿 args 字串切開。"""
    args = dict(args or {})
    if node.fields:
        names = {f.name for f in node.fields if not f.fresh_code}
        out = []
        for f in node.fields:
            if f.name in names and str(args.get(f.name, "")).strip():
                out += f"{f.name}={str(args[f.name]).strip()}".split()
        return out
    return str(args.get("args", "")).split()


def unknown_args(node: Node, args: dict) -> List[str]:
    allowed = {f.name for f in node.fields if not f.fresh_code} if node.fields else {"args"}
    return [k for k in (args or {}) if k not in allowed]
