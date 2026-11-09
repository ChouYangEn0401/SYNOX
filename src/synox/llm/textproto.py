"""
文字協定：端點不支援原生 tool-calling 時（公司閘道沒開、claude -p），AI 用「只回一個 JSON」表示要呼叫工具。

    {"tool": "money__add", "args": {"amount": "80", "category": "咖啡"}}

system_snippet(tools) 產生放進系統提示的說明；parse(text) 從回覆裡找出那個 JSON。解析要容錯：
  - ```json … ``` 圍起來的
  - 前後多了話（「好的，我來記：{…} 記好了」）
  - "name"/"arguments"、"tool_name"/"parameters" 這些別名；args 是字串時再 json.loads 一次
找不到（或 tool 不是字串）就當成一般文字回覆。
"""

from __future__ import annotations

import json
import re
from typing import Optional, Sequence, Tuple

from synox.llm.base import ToolCall, ToolSpec

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_NAME_KEYS = ("tool", "name", "tool_name", "function")
_ARGS_KEYS = ("args", "arguments", "parameters", "input")


def system_snippet(tools: Sequence[ToolSpec]) -> str:
    lines = ["## 怎麼使用工具",
             "要用工具時，整則回覆只能是一個 JSON 物件，前後不要有任何其他文字：",
             '{"tool": "<工具名>", "args": {"<參數>": "<值>"}}',
             "一次只呼叫一個工具。工具的結果會以「〔工具結果〕」開頭傳回給你，看完再決定下一步或回答使用者。",
             "不需要工具時，直接用繁體中文回答。", "", "可用的工具："]
    for t in tools:
        props = (t.parameters or {}).get("properties") or {}
        required = set((t.parameters or {}).get("required") or [])
        params = "、".join(f"{k}{'（必填）' if k in required else ''}：{v.get('description', '')}"
                          for k, v in props.items()) or "（沒有參數）"
        lines.append(f"- {t.name}：{t.description}\n  參數：{params}")
    return "\n".join(lines)


def _as_call(obj) -> Optional[ToolCall]:
    if not isinstance(obj, dict):
        return None
    name = next((obj[k] for k in _NAME_KEYS if isinstance(obj.get(k), str) and obj.get(k)), None)
    if name is None:
        return None
    args = next((obj[k] for k in _ARGS_KEYS if k in obj), {})
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except ValueError:
            args = {"args": args}
    if not isinstance(args, dict):
        args = {}
    return ToolCall(name=name.strip(), args=args, id="text-0")


def _objects(text: str):
    """text 裡每一個能被 json 解開的 {…}（從每個 '{' 開始試 raw_decode）。"""
    decoder = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        yield obj, i, end
        i = text.find("{", end)


def parse(text: str) -> Tuple[Optional[ToolCall], str]:
    """回 (工具呼叫或 None, 其餘的文字)。"""
    text = text or ""
    for block in _FENCE.findall(text):
        for obj, _s, _e in _objects(block):
            call = _as_call(obj)
            if call is not None:
                rest = _FENCE.sub("", text).strip()
                return call, rest
    for obj, start, end in _objects(text):
        call = _as_call(obj)
        if call is not None:
            return call, (text[:start] + text[end:]).strip()
    return None, text.strip()


def result_message(tool: str, result: str) -> str:
    """文字協定下把工具結果交回給 AI 的那一則（role=user）。"""
    return f"〔工具結果〕{tool}\n{result}"
