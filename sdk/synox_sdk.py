# synox_sdk.py：SYNOX 工具 SDK 的單檔版（只用標準函式庫，可以直接複製進你的 repo）。
# 由 scripts/build_synox_sdk.py 從 src/synox/sdk/author.py 產生；要改請改正本再重產，不要直接改這個檔。
"""
synox_sdk：寫一個 Python 函式，就是一個 SYNOX 工具（也是一個 MCP 工具）。只用標準函式庫、零相依。

    from synox_sdk import tool, serve

    @tool("WRITE")
    def add(amount: int, memo: str = ""):
        \"\"\"記一筆花費。\"\"\"
        return f"記了 {amount} 元"

    if __name__ == "__main__":
        serve()

- `@tool(effect, summary="", default=False, ai=True, confirm=False)`：effect 一定要寫（READ／WRITE／DANGER）。
  參數的型別註記就是欄位：int→int、float→number、bool→bool、str→text、Path→path、Literal["a","b"]→choice；
  有預設值或 Optional[...] ＝選填。summary 沒寫就用 docstring 第一段；docstring 的 Args: 段落是欄位說明。
- `serve()`：同一組函式兩種殼。
      python tool.py add --amount=120 --memo=午餐 --json     → 最後一行印 SYNOX 的 JSON 信封（kind=cli pack 用這條）
      python tool.py --mcp                                 → MCP stdio server（JSON-RPC 2.0，給其他 AI 用戶端）
- 函式回什麼：字串＝給人看的那句話；dict／list／數字＝data；`Ok(message, data)` 兩個都給；
  `raise ToolError(code, message)`＝失敗；`raise Confirm(summary)`（或 return）＝要確認（信封 needs_confirm）。
- --mcp 模式的 Confirm：result 帶 structuredContent.needs_confirm；用戶端讓人確認後帶 _meta["synox/confirm_token"] 重叫。
- 確認來回：`if not confirmed(): raise Confirm("要刪 3 筆")`。SYNOX 出卡給人，按 ✅ 用同一組參數重跑一次，
  這一次 `confirmed()` 是 True（SYNOX 驗過一次性憑證才給 SYNOX_CONFIRMED=1；工具、AI、pack.json 都造不出來）。
  `Confirm(summary, token=…)` 的 token 會在重跑時原樣送回：`confirmed(token=…)` 可以順便核對「資料還是剛剛那份」。
- `secret(name)`：使用者在 SYNOX 工具頁「連接」填的值（pack.json 的 auth.fields；SYNOX 經環境變數給，不經 argv）。
- `context()`：這一次是誰在用：user_data_dir、tg_id、mode、pack_dir、pack_name、confirmed、confirm_token
  （SYNOX 經 SYNOX_* 環境變數給）。

這個檔有兩份：`src/synox/sdk/author.py`（正本，`from synox.sdk import tool, serve`）與 `sdk/synox_sdk.py`
（`scripts/build_synox_sdk.py` 從正本產生，可以直接複製進你的 repo）。
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
import traceback
import types
import typing
import uuid
from contextlib import redirect_stdout
from pathlib import PurePath
from typing import Any, Callable, Dict, List, Optional, Sequence

__all__ = ["tool", "serve", "secret", "context", "confirmed", "Context", "ToolError", "Confirm", "Ok", "SpecError",
           "tool_spec", "commands_for", "run_cli", "run_mcp", "registered"]

SDK_VERSION = "0.1.0"
SYNOX_REQUIRES = ">=0.1"               # 產生的 pack.json 的 requires.synox（SYNOX_* 環境變數、ai／confirm 從這版起）
EFFECTS = ("READ", "WRITE", "DANGER")
RESERVED = ("python", "node", "pack_dir", "data_dir", "user_data_dir", "tg_id", "json", "mcp", "help")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
BOOL_TRUE = ("true", "yes", "y", "on", "1", "是", "對", "要", "開")
BOOL_FALSE = ("false", "no", "n", "off", "0", "否", "不", "不要", "關")
MCP_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MCP_CONFIRM_META = "synox/confirm_token"   # MCP tools/call 的 params._meta：用戶端（不是 AI）確認過才帶
CONFIRM_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
EXIT_OK, EXIT_ERROR = 0, 1

_REGISTRY: List[Callable] = []
_SPEC_ATTR = "__synox_tool__"
_MCP_CONFIRM: Optional[str] = None     # MCP tools/call 進行中：_meta 帶的確認 token（"" ＝沒確認）；None＝不在 MCP 呼叫裡


# ── 結果與錯誤 ──────────────────────────────────────────────────────────

class ToolError(Exception):
    """失敗：`raise ToolError("not_found", "找不到這筆")` → {"ok": false, "error": …, "code": …}，結束碼 1。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = str(code), str(message)


class Confirm(Exception):
    """要人確認才做：`if not confirmed(): raise Confirm("要刪 3 筆")`（或 return）→ needs_confirm 信封。
    SYNOX 出核准卡（why＝summary）給下令的人；按 ✅ 用同一組參數重跑，這一次 confirmed() 是 True；按 ❌ 或過期就不跑。
    token：重跑時 SYNOX 原樣送回（SYNOX_CONFIRM_TOKEN），例如放「要刪的那 3 筆」的雜湊，重跑時用 confirmed(token=…) 核對。
    只收英數字與 . _ : -（128 字內）；其他的 SYNOX 當作沒給。沒給＝隨機一個。"""

    def __init__(self, summary: str, token: str = ""):
        super().__init__(summary)
        self.summary, self.token = str(summary), str(token or uuid.uuid4().hex)


class Ok:
    """同時給一句話與資料：`return Ok("共 3 筆", {"count": 3})`。"""

    def __init__(self, message: str = "", data: Any = None):
        self.message, self.data = str(message or ""), data


class SpecError(ValueError):
    """@tool 的宣告不合（沒寫 effect、不支援的型別、名字不對…）。"""


def ok_envelope(data: Any = None, message: str = "") -> dict:
    out: Dict[str, Any] = {"ok": True}
    if message:
        out["message"] = str(message)
    if data is not None:
        out["data"] = data
    return out


def error_envelope(code: str, message: str) -> dict:
    return {"ok": False, "error": str(message), "code": str(code)}


def confirm_envelope(summary: str, token: str) -> dict:
    return {"ok": True, "needs_confirm": True, "summary": str(summary), "confirm_token": str(token),
            "message": f"{summary}\n（要確認才會做）"}


# ── @tool ──────────────────────────────────────────────────────────────

def tool(effect: Any = None, summary: str = "", *, default: bool = False, ai: bool = True, confirm: bool = False,
         name: str = ""):
    """把函式登記成工具。`@tool("READ")`、`@tool("WRITE", "記一筆")`；也可以 `@tool`（但 init 會因為沒寫 effect 拒絕）。
    default＝打 /<群組> 就是它；ai=False＝不給 AI（也不在 MCP 列出）；confirm=True＝AI 要呼叫時先送確認卡給人按。"""
    if callable(effect) and not isinstance(effect, str):
        return tool()(effect)

    def wrap(fn: Callable) -> Callable:
        spec = {"name": name or fn.__name__, "effect": effect, "summary": summary, "default": bool(default),
                "ai": bool(ai), "confirm": bool(confirm)}
        fn.__dict__[_SPEC_ATTR] = spec
        if fn not in _REGISTRY:
            _REGISTRY.append(fn)
        return fn
    return wrap


def registered() -> List[Callable]:
    """這個程序裡用 @tool 登記過的函式（照定義的順序）。"""
    return list(_REGISTRY)


def _raw_spec(fn: Callable) -> Optional[dict]:
    try:
        return vars(fn).get(_SPEC_ATTR)
    except TypeError:
        return None


def _doc_parts(fn: Callable):
    """docstring → (第一段, {參數名: 說明})。認得 `Args:`／`參數：` 段落裡的 `name: 說明`、`name (型別): 說明`。"""
    doc = inspect.getdoc(fn) or ""
    paragraphs = re.split(r"\n\s*\n", doc.strip()) if doc.strip() else []
    first = ""
    if paragraphs and not re.match(r"^(Args|Arguments|Parameters|參數)\s*[:：]", paragraphs[0]):
        first = " ".join(line.strip() for line in paragraphs[0].splitlines())
    asks: Dict[str, str] = {}
    in_args = False
    for line in doc.splitlines():
        if re.match(r"^\s*(Args|Arguments|Parameters|參數)\s*[:：]\s*$", line):
            in_args = True
            continue
        if in_args:
            m = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)]*\))?\s*[:：]\s*(.+)$", line)
            if m:
                asks[m.group(1)] = m.group(2).strip()
            elif line.strip() and not line.startswith((" ", "\t")):
                in_args = False
    return first, asks


def _unwrap(annotation):
    """型別註記 → (型別, 是否 Optional, Annotated 的說明)。"""
    ask = ""
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        args = typing.get_args(annotation)
        annotation = args[0]
        ask = next((str(a) for a in args[1:] if isinstance(a, str)), "")
        origin = typing.get_origin(annotation)
    optional = False
    union_type = vars(types).get("UnionType")      # Python 3.10+ 的 X | None
    if origin is typing.Union or (union_type is not None and origin is union_type):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        optional = len(args) < len(typing.get_args(annotation))
        if len(args) != 1:
            raise SpecError(f"不支援 {annotation}（Union 只能是 Optional[某一種]）")
        annotation = args[0]
    return annotation, optional, ask


def _kind_of(annotation, where: str):
    """型別 → (kind, choices)。"""
    if annotation is inspect.Parameter.empty or annotation is str or annotation is Any:
        return "text", None
    if annotation is bool:
        return "bool", None
    if annotation is int:
        return "int", None
    if annotation is float:
        return "number", None
    if isinstance(annotation, type) and issubclass(annotation, PurePath):
        return "path", None
    if typing.get_origin(annotation) is typing.Literal:
        values = typing.get_args(annotation)
        if not values or not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in values):
            raise SpecError(f"{where}：Literal 只能放字串或整數")
        return "choice", list(values)
    raise SpecError(f"{where}：不支援的型別 {annotation!r}（可以用 str、int、float、bool、Path、Literal[...]、Optional[...]）")


def tool_spec(fn: Callable) -> dict:
    """一個 @tool 函式的完整宣告：{name, effect, summary, default, ai, confirm, fields: [...]}。不合丟 SpecError。"""
    raw = _raw_spec(fn)
    if raw is None:
        raise SpecError(f"{_name_of(fn)} 沒有用 @tool 登記")
    name = raw["name"]
    if not NAME_RE.match(name):
        raise SpecError(f"工具名 {name!r} 只能用小寫英數字、_（英文字母開頭，32 字內）")
    effect = str(raw["effect"] or "").strip().upper()
    if not raw["effect"]:
        raise SpecError(f"{name}：@tool 一定要寫 effect（READ 只看、WRITE 會改東西、DANGER 刪除或花錢），例如 @tool(\"READ\")")
    if effect not in EFFECTS:
        raise SpecError(f"{name}：effect 只能是 READ、WRITE 或 DANGER（寫的是 {raw['effect']!r}）")
    first, asks = _doc_parts(fn)
    summary = (raw["summary"] or first).strip()
    if not summary:
        raise SpecError(f"{name}：要有說明（@tool 的 summary，或函式的 docstring）")
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception as e:
        raise SpecError(f"{name}：型別註記看不懂（{e}）")
    fields = []
    for p in inspect.signature(fn).parameters.values():
        where = f"{name} 的參數 {p.name}"
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise SpecError(f"{where}：不能用 *args／**kwargs（每個參數都要有名字）")
        if not NAME_RE.match(p.name):
            raise SpecError(f"{where}：參數名只能用小寫英數字、_")
        if p.name in RESERVED:
            raise SpecError(f"{where}：這個名字保留給 SYNOX（{'、'.join(RESERVED)}），換一個")
        annotation, optional, ask = _unwrap(hints.get(p.name, inspect.Parameter.empty))
        kind, choices = _kind_of(annotation, where)
        field = {"name": p.name, "ask": asks.get(p.name) or ask or p.name, "kind": kind,
                 "required": p.default is inspect.Parameter.empty and not optional}
        if choices is not None:
            field["choices"] = choices
        field["_type"] = annotation
        fields.append(field)
    return {"name": name, "effect": effect, "summary": summary, "default": raw["default"], "ai": raw["ai"],
            "confirm": raw["confirm"], "fields": fields, "fn": fn}


def _name_of(fn) -> str:
    try:
        return str(fn.__name__)
    except AttributeError:
        return repr(fn)


def specs_for(tools: Optional[Sequence[Callable]] = None) -> List[dict]:
    """全部工具的宣告；有任何一個不合，把全部問題一起丟 SpecError。"""
    tools = list(_REGISTRY if tools is None else tools)
    out, problems, seen, defaults = [], [], set(), 0
    for fn in tools:
        try:
            spec = tool_spec(fn)
        except SpecError as e:
            problems.append(str(e))
            continue
        if spec["name"] in seen:
            problems.append(f"工具名 {spec['name']} 重複了")
        seen.add(spec["name"])
        defaults += 1 if spec["default"] else 0
        out.append(spec)
    if defaults > 1:
        problems.append("default=True 只能有一個（打 /<群組> 就是它）")
    if not tools:
        problems.append("沒有找到任何 @tool 函式")
    if problems:
        raise SpecError("\n".join(problems))
    return out


def commands_for(tools: Optional[Sequence[Callable]] = None) -> List[dict]:
    """pack.json 的 cli.commands：argv 一律 [指令名, --欄位={欄位}…]（SYNOX 只代換一段、沒填的選填整段拿掉）。"""
    out = []
    for spec in specs_for(tools):
        fields = []
        for f in spec["fields"]:
            item = {"name": f["name"], "ask": f["ask"]}
            if f["kind"] != "text":
                item["kind"] = f["kind"]
            if f.get("choices") is not None:
                item["choices"] = [str(c) for c in f["choices"]]
            if f["required"]:
                item["required"] = True
            fields.append(item)
        cmd: Dict[str, Any] = {"name": spec["name"], "effect": spec["effect"], "summary": spec["summary"],
                               "argv": [spec["name"]] + [f"--{f['name']}={{{f['name']}}}" for f in spec["fields"]]}
        if spec["default"]:
            cmd["default"] = True
        if not spec["ai"]:
            cmd["ai"] = False
        if spec["confirm"]:
            cmd["confirm"] = True
        if fields:
            cmd["fields"] = fields
        out.append(cmd)
    return out


# ── 值的轉換 ───────────────────────────────────────────────────────────

def _coerce(field: dict, value: Any) -> Any:
    """字串（命令列）或 JSON 值（MCP）→ 函式要的型別。不合丟 ToolError("bad_value", …)。"""
    kind, ask = field["kind"], field["ask"]

    def bad(text: str):
        return ToolError("bad_value", f"{ask}{text}")

    if kind == "bool":
        if isinstance(value, bool):
            return value
        v = str(value).strip().lower()
        if v in BOOL_TRUE:
            return True
        if v in BOOL_FALSE:
            return False
        raise bad("要是 是／否（true／false）")
    if kind == "int":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        try:
            return int(str(value).strip().replace(",", ""))
        except ValueError:
            raise bad("要是整數（例如 3）")
    if kind == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        try:
            n = float(str(value).strip().replace(",", ""))
        except ValueError:
            raise bad("要是數字（例如 12.5）")
        if n != n or n in (float("inf"), float("-inf")):
            raise bad("要是數字（例如 12.5）")
        return n
    if kind == "choice":
        for c in field["choices"]:
            if str(c).lower() == str(value).strip().lower():
                return c
        raise bad("只能是 " + "／".join(str(c) for c in field["choices"]))
    if not isinstance(value, str):
        raise bad("要是文字")
    if kind == "path":
        return field["_type"](value)
    return value


def _call(spec: dict, values: Dict[str, Any]):
    """檢查必填、轉型、呼叫。回 (信封, 結束碼)。"""
    fields = {f["name"]: f for f in spec["fields"]}
    unknown = [k for k in values if k not in fields]
    try:
        if unknown:
            raise ToolError("usage", f"{spec['name']} 不認得 {'、'.join(unknown)}（只收 {'、'.join(fields) or '（沒有參數）'}）")
        kwargs = {}
        for name, f in fields.items():
            if name in values and values[name] is not None and values[name] != "":
                kwargs[name] = _coerce(f, values[name])
        missing = [f["ask"] for n, f in fields.items() if f["required"] and n not in kwargs]
        if missing:
            raise ToolError("usage", f"{spec['name']} 少了：{'、'.join(missing)}")
        result = spec["fn"](**kwargs)
    except ToolError as e:
        return error_envelope(e.code, e.message), EXIT_ERROR
    except Confirm as c:
        return confirm_envelope(c.summary, c.token), EXIT_OK
    except Exception as e:                                  # 工具自己的錯：說是哪一種，細節印到 stderr
        traceback.print_exc(file=sys.stderr)
        return error_envelope("internal", f"{type(e).__name__}: {e}"), EXIT_ERROR
    if isinstance(result, Confirm):
        return confirm_envelope(result.summary, result.token), EXIT_OK
    if isinstance(result, Ok):
        return ok_envelope(result.data, result.message), EXIT_OK
    if isinstance(result, str):
        return ok_envelope(None, result), EXIT_OK
    return ok_envelope(result), EXIT_OK


def _dumps(obj: Any, **kw) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, **kw)


# ── 殼 1：子指令＋--json ───────────────────────────────────────────────

def _parse_cli(spec: dict, args: Sequence[str]) -> Dict[str, Any]:
    """--k=v、--k v、--旗標（bool＝true）、照順序的位置參數。"""
    fields = [f["name"] for f in spec["fields"]]
    kinds = {f["name"]: f["kind"] for f in spec["fields"]}
    values: Dict[str, Any] = {}
    rest: List[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("--") and len(token) > 2:
            key, eq, value = token[2:].partition("=")
            key = key.replace("-", "_")
            if not eq:
                if kinds.get(key) == "bool":
                    value = "true"
                elif i + 1 < len(args):
                    i += 1
                    value = args[i]
                else:
                    raise ToolError("usage", f"--{key} 後面要有值")
            values[key] = value
        else:
            rest.append(token)
        i += 1
    for name in fields:
        if not rest:
            break
        if name not in values:
            values[name] = rest.pop(0)
    if rest:
        raise ToolError("usage", f"多了參數：{' '.join(rest)}")
    return values


def _usage(specs: List[dict]) -> str:
    lines = ["用法：<指令> [--欄位=值 …] [--json]　｜　--mcp（MCP stdio server）", ""]
    for s in specs:
        params = " ".join((f"--{f['name']}=<{f['ask']}>" if f["required"] else f"[--{f['name']}=…]")
                          for f in s["fields"])
        lines.append(f"  {s['name']} {params}".rstrip() + f"\n      {s['summary']}")
    return "\n".join(lines)


def run_cli(argv: Sequence[str], out=None, tools: Optional[Sequence[Callable]] = None) -> int:
    """命令列殼：`<指令> [參數] [--json]`。有 --json 印一行 JSON 信封（SYNOX 讀最後一行）；沒有就印給人看的字。"""
    out = out or sys.stdout
    argv = list(argv)
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    try:
        specs = specs_for(tools)
    except SpecError as e:
        return _print(out, error_envelope("spec", str(e)), as_json, EXIT_ERROR)
    by_name = {s["name"]: s for s in specs}
    if not argv or argv[0] in ("-h", "--help", "help"):
        if as_json:
            return _print(out, ok_envelope({"commands": [s["name"] for s in specs]}, _usage(specs)), True, EXIT_OK)
        out.write(_usage(specs) + "\n")
        return EXIT_OK
    spec = by_name.get(argv[0].replace("-", "_"))
    if spec is None:
        return _print(out, error_envelope("usage", f"沒有 {argv[0]} 這個指令（有：{'、'.join(by_name)}）"),
                      as_json, EXIT_ERROR)
    try:
        values = _parse_cli(spec, argv[1:])
    except ToolError as e:
        return _print(out, error_envelope(e.code, e.message), as_json, EXIT_ERROR)
    envelope, code = _call(spec, values)
    return _print(out, envelope, as_json, code)


def _print(out, envelope: dict, as_json: bool, code: int) -> int:
    if as_json:
        out.write(_dumps(envelope) + "\n")
    elif not envelope.get("ok"):
        out.write(f"❌ {envelope.get('error')}\n")
    else:
        text = envelope.get("message") or ""
        if envelope.get("data") is not None:
            text = (text + "\n" if text else "") + _dumps(envelope["data"], indent=2)
        out.write((text or "完成") + "\n")
    out.flush()
    return code


# ── 殼 2：MCP stdio server ─────────────────────────────────────────────

_JSON_TYPES = {"text": "string", "path": "string", "int": "integer", "number": "number", "bool": "boolean"}


def input_schema(spec: dict) -> dict:
    """型別註記 → MCP 的 inputSchema（JSON Schema）。"""
    props = {}
    for f in spec["fields"]:
        if f["kind"] == "choice":
            values = f["choices"]
            prop: Dict[str, Any] = {"enum": values,
                                    "type": "integer" if all(isinstance(v, int) for v in values) else "string"}
        else:
            prop = {"type": _JSON_TYPES[f["kind"]]}
        if f["ask"] != f["name"]:
            prop["description"] = f["ask"]
        props[f["name"]] = prop
    schema: Dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    required = [f["name"] for f in spec["fields"] if f["required"]]
    if required:
        schema["required"] = required
    return schema


def _mcp_text(envelope: dict) -> str:
    if not envelope.get("ok"):
        return str(envelope.get("error") or "失敗")
    if envelope.get("needs_confirm"):
        return (f"還沒做：要使用者確認才會做：{envelope.get('summary')}\n"
                "（請把這句話給使用者看；要等用戶端確認後帶 _meta 的 synox/confirm_token 重新呼叫，AI 不能自己確認）")
    parts = [envelope["message"]] if envelope.get("message") else []
    if envelope.get("data") is not None:
        parts.append(_dumps(envelope["data"]))
    return "\n".join(parts) or "完成"


def _mcp_handle(msg: Any, specs: Dict[str, dict], info: dict) -> Optional[dict]:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request"}}
    method, params, has_id = msg["method"], msg.get("params") or {}, "id" in msg
    if not has_id:                                        # 通知（notifications/initialized…）不回
        return None

    def result(value: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg["id"], "result": value}

    def error(code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": code, "message": text}}

    if not isinstance(params, dict):
        return error(-32602, "params 要是物件")
    if method == "initialize":
        asked = params.get("protocolVersion")
        return result({"protocolVersion": asked if asked in MCP_PROTOCOLS else MCP_PROTOCOLS[0],
                       "capabilities": {"tools": {"listChanged": False}}, "serverInfo": info})
    if method == "ping":
        return result({})
    if method == "tools/list":
        return result({"tools": [{"name": s["name"], "description": s["summary"], "inputSchema": input_schema(s)}
                                 for s in specs.values()]})
    if method == "tools/call":
        spec = specs.get(params.get("name"))
        if spec is None:
            return error(-32602, f"Unknown tool: {params.get('name')}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return error(-32602, "arguments 要是物件")
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        token = meta.get(MCP_CONFIRM_META)
        global _MCP_CONFIRM
        _MCP_CONFIRM = token if isinstance(token, str) and CONFIRM_TOKEN_RE.fullmatch(token) else ""   # MCP 模式不看環境變數
        try:
            with redirect_stdout(sys.stderr):              # 工具自己 print 的字不能混進 JSON-RPC 的 stdout
                envelope, _code = _call(spec, args)
        finally:
            _MCP_CONFIRM = None
        reply = {"content": [{"type": "text", "text": _mcp_text(envelope)}], "isError": not envelope.get("ok")}
        if envelope.get("needs_confirm"):
            reply["structuredContent"] = {"needs_confirm": True, "summary": envelope.get("summary", ""),
                                          "confirm_token": envelope.get("confirm_token", "")}
        return result(reply)
    return error(-32601, f"Method not found: {method}")


def run_mcp(stdin=None, stdout=None, tools: Optional[Sequence[Callable]] = None, name: str = "",
            version: str = "") -> int:
    """MCP stdio server：一行一個 JSON-RPC 2.0 訊息。只做 initialize、ping、tools/list、tools/call。
    ai=False 的工具不列出、不能呼叫。effect 不由這裡講（SYNOX 的 kind=mcp pack 由 pack.json 的 mcp.effects 決定）。
    工具回 Confirm：result 的 isError=false、content 一句「還沒做：要使用者確認…」、structuredContent=
    {needs_confirm, summary, confirm_token}。用戶端讓人確認後，同一組 arguments 再呼叫一次並帶
    params._meta["synox/confirm_token"]＝那個 token，這一次 confirmed() 才是 True。MCP 模式不看 SYNOX_CONFIRMED
    環境變數（server 是長駐的，環境變數不是「這一次」）；AI 只決定 arguments、碰不到 _meta。"""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    specs = {s["name"]: s for s in specs_for(tools) if s["ai"]}
    info = {"name": name or "synox-tool", "version": version or SDK_VERSION}
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply: Optional[dict] = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = _mcp_handle(msg, specs, info)
        if reply is not None:
            stdout.write(_dumps(reply) + "\n")
            stdout.flush()
    return EXIT_OK


def _reconfigure_utf8() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def serve(argv: Optional[Sequence[str]] = None, *, name: str = "", version: str = "") -> None:
    """`if __name__ == "__main__": serve()`。有 --mcp 跑 MCP stdio server，不然跑命令列殼；結束程式。"""
    _reconfigure_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--mcp" in argv:
        server = name or os.path.splitext(os.path.basename(sys.argv[0] or "tool"))[0]
        sys.exit(run_mcp(name=server, version=version))
    sys.exit(run_cli(argv))


# ── secret、context ────────────────────────────────────────────────────

def _env(name: str) -> str:
    return os.environ.get(name, "")


def secret(name: str) -> Optional[str]:
    """pack.json auth.fields 的值（使用者在 SYNOX 工具頁「連接」填的）。name 可以是欄位名（"api_key"）或環境變數名。
    SYNOX 叫工具時把值放進 auth.fields[].env 那個環境變數，並在 SYNOX_SECRET_ENV 給「欄位名=環境變數名」對照。
    沒填回 None。不要印出來、不要放進回覆。"""
    mapping = {}
    for pair in _env("SYNOX_SECRET_ENV").split(","):
        key, eq, env = pair.partition("=")
        if eq and key.strip():
            mapping[key.strip()] = env.strip()
    for candidate in (mapping.get(name), name, name.upper()):
        if candidate:
            value = _env(candidate)
            if value:
                return value
    return None


class Context:
    """這一次是誰在用（SYNOX 經環境變數給；不是從 SYNOX 叫的就都是空的，`synox-sdk run` 會模擬）。

    user_data_dir：這個人的資料夾（伺服器版每人一個；個人版是 SYNOX 的 data/）。自己的檔放 <user_data_dir>/<pack_name>/。
    tg_id：下令的人的 Telegram id（字串）。mode：personal｜server。pack_dir：pack 資料夾。
    confirmed：這一次是人按過 ✅ 的重跑（見 confirmed()）。confirm_token：那時工具自己給的 Confirm token（沒確認＝空）。"""

    def __init__(self, user_data_dir: str, tg_id: str, mode: str, pack_dir: str, pack_name: str,
                 confirmed: bool = False, confirm_token: str = ""):
        self.user_data_dir, self.tg_id, self.mode = user_data_dir, tg_id, mode
        self.pack_dir, self.pack_name = pack_dir, pack_name
        self.confirmed, self.confirm_token = bool(confirmed), confirm_token if confirmed else ""

    @property
    def inside_synox(self) -> bool:
        return bool(self.mode)

    def __repr__(self) -> str:
        return (f"Context(user_data_dir={self.user_data_dir!r}, tg_id={self.tg_id!r}, mode={self.mode!r}, "
                f"pack_dir={self.pack_dir!r}, pack_name={self.pack_name!r}, confirmed={self.confirmed!r})")


def _confirm_state():
    """(是否已確認, 工具的 token)。命令列殼：SYNOX 驗過才給的 SYNOX_CONFIRMED=1＋SYNOX_CONFIRM_TOKEN；
    MCP 殼：這一次 tools/call 的 _meta（環境變數不算）。"""
    if _MCP_CONFIRM is not None:
        return bool(_MCP_CONFIRM), _MCP_CONFIRM
    if _env("SYNOX_CONFIRMED") != "1":
        return False, ""
    return True, _env("SYNOX_CONFIRM_TOKEN")


def confirmed(token: str = "") -> bool:
    """這一次是不是人按過 ✅ 的重跑。token 有給＝還要是當初 Confirm(…, token=…) 給的那個（資料變了就不算）。

        @tool("DANGER")
        def purge(days: int):
            rows = old_rows(days)
            key = digest(rows)
            if not confirmed(key):
                raise Confirm(f"要刪 {len(rows)} 筆", token=key)
            delete(rows)

    「已確認」是 SYNOX 驗過一次性憑證（綁 pack／指令／參數／人、數分鐘過期、用一次）才放進環境變數的，
    重跑的參數跟第一次一樣，沒有 AI 能塞的 --yes。不是從 SYNOX 叫的（自己在終端機跑）一律 False，
    除非你自己設了 SYNOX_CONFIRMED=1（`synox-sdk run … --confirmed` 就是這樣模擬按 ✅）。"""
    ok, given = _confirm_state()
    if not ok:
        return False
    return not token or given == str(token)


def context() -> Context:
    ok, given = _confirm_state()
    return Context(_env("SYNOX_USER_DATA_DIR"), _env("SYNOX_TG_ID"), _env("SYNOX_MODE"), _env("SYNOX_PACK_DIR"),
                   _env("SYNOX_PACK_NAME"), ok, given)
