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


def _shape(prop) -> str:
    """不是字串的參數（schema 模式的 MCP 工具：整數、布林、陣列、物件）把 JSON Schema 附上，模型才知道要給什麼型別。"""
    if not isinstance(prop, dict) or prop.get("type") in (None, "string"):
        return ""
    text = json.dumps(prop, ensure_ascii=False)
    return f"（JSON 型別：{text if len(text) <= 400 else text[:399] + '…'}）"


def system_snippet(tools: Sequence[ToolSpec]) -> str:
    lines = ["## 怎麼使用工具",
             "要用工具時，整則回覆只能是一個 JSON 物件，前後不要有任何其他文字：",
             '{"tool": "<工具名>", "args": {"<參數>": "<值>"}}',
             "一次只呼叫一個工具。工具的結果會以「〔工具結果〕」開頭傳回給你，看完再決定下一步或回答使用者。",
             "不需要工具時，直接用繁體中文回答。", "", "可用的工具："]
    for t in tools:
        props = (t.parameters or {}).get("properties") or {}
        required = set((t.parameters or {}).get("required") or [])
        params = "、".join(f"{k}{'（必填）' if k in required else ''}：{v.get('description', '')}{_shape(v)}"
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


RESULT_PREFIX = "〔工具結果〕"


def result_message(tool: str, result: str) -> str:
    """文字協定下把工具結果交回給 AI 的那一則（role=user）。"""
    return f"{RESULT_PREFIX}{tool}\n{result}"


# ── 思考段、文字裡洩漏的工具呼叫（docs/adr/0009）──────────────────────────────
#
# 原生 tool-calling 的模型有時把呼叫當文字印出來（Ollama #14745／#14493：Qwen3.5 的 XML 格式對不上 Hermes 解析器），
# 或把思考段 <think>…</think> 留在 content 裡。這裡只**解析文字**：救回來的呼叫交給 agent 的迴圈，
# 照常過 ai_decision、第 4 關、確認卡（adapter 只回文字、決策在 harness，invariant 2）。

LEAK_MARKERS = ("<tool_call>", "<function=", "<invoke ", "<minimax:tool_call>")
MAX_LEAKED = 3                       # 一次最多救回 3 個呼叫，第 4 個起丟掉
_THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
_TOOL_CALL = re.compile(r"<tool_call>(.*?)(?:</tool_call>|(?=<tool_call>)|\Z)", re.DOTALL)
_FUNCTION = re.compile(r"<function=([^>\s]+)\s*>(.*?)(?:</function>|(?=<function=)|(?=</tool_call>)|\Z)", re.DOTALL)
_PARAMETER = re.compile(r"<parameter=([^>\s]+)\s*>(.*?)(?:</parameter>|(?=<parameter=)|(?=</function>)|\Z)", re.DOTALL)
_MINIMAX_BLOCK = re.compile(r"<minimax:tool_call>(.*?)(?:</minimax:tool_call>|\Z)", re.DOTALL)
_INVOKE = re.compile(r"""<invoke\s+name\s*=\s*["']([^"']+)["']\s*>(.*?)(?:</invoke>|(?=<invoke\s)|\Z)""", re.DOTALL)
_INVOKE_PARAM = re.compile(r"""<parameter\s+name\s*=\s*["']([^"']+)["']\s*>(.*?)(?:</parameter>|(?=<parameter\s)|\Z)""",
                           re.DOTALL)
_NAME_FIELD = re.compile(r"""["'](?:name|tool|function)["']\s*:\s*["']([^"']+)["']""")
_ARGS_FIELD = re.compile(r"""["'](?:arguments|args|parameters)["']\s*:\s*""")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def strip_think(text: str) -> Tuple[str, str]:
    """(去掉思考段的文字, 思考段)。認 <think>…</think>；只有結尾 </think>（模板把 <think> 放在提示裡）＝前面整段是思考；
    只有開頭 <think> 沒有結尾（思考到一半被切掉）＝後面整段是思考。工具呼叫一律只在去掉思考段的文字裡找（Qwen-Agent：
    不解析思考段裡的 tool_call）。"""
    text = text or ""
    thoughts = []

    def keep(m):
        thoughts.append(m.group(1))
        return ""

    clean = _THINK_BLOCK.sub(keep, text)
    low = clean.lower()
    end = low.find("</think>")
    if end != -1:
        thoughts.insert(0, clean[:end])
        clean = clean[end + len("</think>"):]
        low = clean.lower()
    start = low.find("<think>")
    if start != -1:
        thoughts.append(clean[start + len("<think>"):])
        clean = clean[:start]
    if not thoughts:
        return text, ""
    return clean.strip(), "\n".join(t.strip() for t in thoughts if t.strip())


def has_leak(text: str) -> bool:
    return any(m in (text or "") for m in LEAK_MARKERS)


def _repair(raw: str):
    """寬鬆的 JSON：先標準解析；不行就去尾逗號、單引號換雙引號、補缺的 }，再試。都不行回 None。"""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = _FENCE.sub(lambda m: m.group(1), raw).strip()
    attempts = [raw]
    fixed = _TRAILING_COMMA.sub(r"\1", raw)
    attempts.append(fixed)
    if '"' not in fixed and "'" in fixed:
        attempts.append(fixed.replace("'", '"'))
    for base in list(attempts):
        missing = base.count("{") - base.count("}")
        if missing > 0:
            attempts.append(base + "}" * missing)
    for candidate in attempts:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None


def _scrape(raw: str) -> Optional[ToolCall]:
    """JSON 修不好：用字串搜尋 "name": "…" 與 "arguments": {…}（arguments 解不出來就當沒有參數，第 4 關會把缺的告訴 AI）。"""
    m = _NAME_FIELD.search(raw or "")
    if not m:
        return None
    args = {}
    a = _ARGS_FIELD.search(raw, m.end()) or _ARGS_FIELD.search(raw)
    if a:
        try:
            value, _end = json.JSONDecoder().raw_decode(raw, a.end())
            args = value if isinstance(value, dict) else {}
        except ValueError:
            brace = raw.find("{", a.end())
            if brace != -1:
                fixed = _repair(raw[brace:].rstrip().rstrip("}") + "}")
                args = fixed if isinstance(fixed, dict) else {}
    return ToolCall(name=m.group(1).strip(), args=args)


def _value(raw: str):
    """XML 參數的值：去掉頭尾空白；看起來是 JSON 物件／陣列就解開（schema 模式的工具），其他一律字串。"""
    value = (raw or "").strip()
    if value[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def _xml_calls(body: str):
    for m in _FUNCTION.finditer(body):
        args = {k.strip(): _value(v) for k, v in _PARAMETER.findall(m.group(2))}
        yield ToolCall(name=m.group(1).strip(), args=args)


def _json_or_xml(body: str) -> list:
    if "<function=" in body:
        return list(_xml_calls(body))
    obj = _repair(body)
    call = _as_call(obj) if isinstance(obj, dict) else None
    if call is None:
        call = _scrape(body)
    return [call] if call is not None else []


def parse_leaked(text: str) -> Tuple[list, str]:
    """回 ([救回的 ToolCall], 其餘的文字)。依序認：(a) <tool_call>…</tool_call> 裡的 JSON（寬鬆修復、字串搜尋；未閉合也試），
    裡面是 Qwen XML 也收；(b) Qwen3-Coder／Qwen3.5 的 <function=名><parameter=k>v</parameter></function>；
    (c) MiniMax 的 <invoke name="…"><parameter name="k">v</parameter></invoke>（可包在 <minimax:tool_call> 裡）；
    (d) 都沒有就用 parse()（裸 JSON）。思考段裡的一律不解（先 strip_think）。一次最多 MAX_LEAKED 個，id 是 leak-{i}。
    一個都解不出來回 ([], 原文)。"""
    clean, _thought = strip_think(text or "")
    calls: list = []
    rest = clean
    if "<tool_call>" in rest:
        for m in _TOOL_CALL.finditer(rest):
            calls += _json_or_xml(m.group(1))
        rest = _TOOL_CALL.sub("", rest).replace("</tool_call>", "")
    if "<function=" in rest:
        calls += list(_xml_calls(rest))
        rest = _FUNCTION.sub("", rest)
    if "<invoke" in rest:
        blocks = [m.group(1) for m in _MINIMAX_BLOCK.finditer(rest)] or [rest]
        for block in blocks:
            for m in _INVOKE.finditer(block):
                args = {k.strip(): _value(v) for k, v in _INVOKE_PARAM.findall(m.group(2))}
                calls.append(ToolCall(name=m.group(1).strip(), args=args))
        rest = _INVOKE.sub("", _MINIMAX_BLOCK.sub("", rest))
    if not calls:
        call, rest2 = parse(clean)
        if call is None:
            return [], clean
        calls, rest = [call], rest2
    calls = [c for c in calls if c.name][:MAX_LEAKED]
    if not calls:
        return [], clean
    for i, c in enumerate(calls):
        c.id = f"leak-{i}"
    rest = re.sub(r"\n{3,}", "\n\n", rest.replace("</minimax:tool_call>", "")).strip()
    return calls, rest
