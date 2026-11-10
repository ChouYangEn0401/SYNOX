# -*- coding: utf-8 -*-
"""工具 SDK Q6 方案 B：巢狀參數的 schema 模式（mcp.schema_tools，packs/mcp_schema.py）。
假伺服器是 tmp 裡一支只用標準函式庫的 Python（stdio 子程序），不連網、不開埠。"""
import json
import os

import pytest

from conftest import OWNER_ID

from synox import sandbox
from synox.agent import tools as tools_mod
from synox.agent import validate as gate4
from synox.llm import textproto
from synox.llm.base import ToolSpec
from synox.packs import mcp, mcp_schema, upgrade
from synox.packs import confirm as tc
from synox.packs.manifest import ManifestError, read, validate

TASK = {"type": "object", "required": ["title"], "additionalProperties": False, "properties": {
    "title": {"type": "string", "maxLength": 100, "description": "標題"},
    "priority": {"type": "integer", "minimum": 1, "maximum": 4},
    "done": {"type": "boolean"},
    "kind": {"enum": ["work", "home"], "type": "string"}}}
ADD_TASKS = {"type": "object", "required": ["tasks"], "additionalProperties": False, "properties": {
    "project": {"type": "string"},
    "labels": {"type": "array", "items": {"type": "string"}},
    "tasks": {"type": "array", "maxItems": 100, "items": TASK}}}
CREATE_PAGES = {"type": "object", "required": ["pages"], "properties": {
    "parent": {"type": "string", "description": "上層頁面"},
    "pages": {"type": "array", "items": {"type": "object", "required": ["title"], "properties": {
        "title": {"type": "string"}, "body": {"type": "string"}}}}}}
TAG = {"type": "object", "required": ["name"], "properties": {
    "name": {"type": "string"}, "meta": {"type": "object", "properties": {"color": {"type": "string"}}}}}
BULK = {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "integer"}}}}

TOOLS = [
    {"name": "echo", "description": "平面回聲", "inputSchema": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string"}, "times": {"type": "integer"}}}},
    {"name": "add-tasks", "description": "一次加好幾個待辦", "inputSchema": ADD_TASKS},
    {"name": "create-pages", "description": "建頁面", "inputSchema": CREATE_PAGES},
    {"name": "tag", "description": "加標籤", "inputSchema": TAG},
    {"name": "bulk-delete", "description": "批次刪（要確認）", "inputSchema": BULK},
    {"name": "refy", "description": "用 $ref", "inputSchema": {"type": "object", "$defs": {"x": {"type": "string"}},
                                                             "properties": {"a": {"$ref": "#/$defs/x"}}}},
    {"name": "anyof", "description": "用 oneOf", "inputSchema": {"type": "object", "properties": {
        "a": {"oneOf": [{"type": "string"}, {"type": "integer"}]}}}},
    {"name": "openobj", "description": "開放物件", "inputSchema": {"type": "object", "properties": {
        "a": {"type": "object", "additionalProperties": True}}}},
    {"name": "pathy", "description": "路徑欄位", "inputSchema": {"type": "object", "properties": {
        "file": {"type": "string", "format": "file-path"}}}},
]
FAKE = r'''
import json, sys
for s in (sys.stdin, sys.stdout):
    s.reconfigure(encoding="utf-8")
with open(sys.argv[1], encoding="utf-8") as f:
    TOOLS = json.load(f)
def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        continue
    if method == "initialize":
        out({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                                     "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "tools/list":
        out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name, args, meta = params.get("name"), params.get("arguments"), params.get("_meta") or {}
        if name == "bulk-delete" and meta.get("synox/confirm_token") != "tok-b":
            out({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "還沒做"}],
                 "structuredContent": {"needs_confirm": True, "summary": "要刪這些", "confirm_token": "tok-b"}}})
            continue
        with open(sys.argv[2], "a", encoding="utf-8") as f:
            f.write(json.dumps({"name": name, "args": args}, ensure_ascii=False) + "\n")
        out({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text":
             "收到 " + name + " " + json.dumps(args, ensure_ascii=False, sort_keys=True)}]}})
    else:
        out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})
'''

ALLOW = [t["name"] for t in TOOLS]
EFFECTS = {t: "WRITE" for t in ALLOW}
EFFECTS.update({"echo": "READ", "create-pages": "DANGER"})
NESTED = ["add-tasks", "create-pages", "tag", "bulk-delete", "refy", "anyof", "openobj", "pathy"]
SECRET = "sk-live-SUPERSECRET-42"


def _pack(base, name="demo", **mcp_over):
    folder = os.path.join(str(base), name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "server.py"), "w", encoding="utf-8") as f:
        f.write(FAKE)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: 假的巢狀 MCP\n---\n正文\n")
    calls = os.path.join(str(base), f"{name}-calls.jsonl")
    with open(os.path.join(folder, "tools.json"), "w", encoding="utf-8") as f:
        json.dump(TOOLS, f, ensure_ascii=False)
    raw = {"name": name, "title": "巢狀 MCP", "summary": "測試用", "version": "0.1.0", "kind": "mcp",
           "capabilities": ["subprocess"], "skill": "SKILL.md",
           "auth": {"type": "token", "fields": [{"name": "api_key", "label": "key", "secret": True,
                                                 "env": "DEMO_API_KEY"}]},
           "mcp": {"transport": "stdio", "argv": ["{python}", "./server.py", "./tools.json", calls],
                   "timeout": 5, "tools_allow": ALLOW, "effects": EFFECTS, "schema_tools": NESTED, **mcp_over}}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    return folder, calls


@pytest.fixture(autouse=True)
def _reset_sandbox():
    yield
    sandbox.set_factory(None)


@pytest.fixture
def bots():
    made = []
    yield made
    for b in made:
        for hook in list(b.app.on_stop):
            hook(b.app)


def _bot(make_bot, tmp_path, bots, script=None, warm=True, **kw):
    folder, calls = _pack(tmp_path / "packs")
    bot = make_bot(script, pack_dirs=(str(tmp_path / "packs"),), **kw)
    bots.append(bot)
    item = bot.app.extras["synox_pack_report"].items[0]
    assert item.status == "loaded", item.detail
    pack = bot.app.extras["synox_packs"][0]
    pack.secrets.update("demo", pack.secret_fields, {"api_key": SECRET}, None)
    if warm:                                                    # 先讓工具伺服器啟動一次、讀 tools/list
        bot.say(OWNER_ID, "/demo_echo hi times=2")
        assert bot.app.tasks.wait(20)
        assert "收到 echo" in bot.last(OWNER_ID)
    return bot, folder, calls


def _calls(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _tool_results(bot):
    adapter = bot.app.extras["synox_agent"].adapter
    return [m.content for msgs, _t in adapter.calls for m in msgs if getattr(m, "role", "") == "tool"]


def _buttons(bot, kind):
    return [b for b in bot.buttons(OWNER_ID) if b.startswith(f"agent_ok:{kind}:")]


# ── 正規化 ─────────────────────────────────────────────────────────────

def test_normalize_subset_and_unsupported_constructs():
    nested, problem = mcp_schema.normalize(ADD_TASKS)
    assert problem is None and nested["properties"]["tasks"]["items"]["properties"]["priority"]["maximum"] == 4
    assert mcp_schema.normalize({"type": "object", "properties": {"n": {"type": ["integer", "null"]}}})[0][
        "properties"]["n"] == {"type": "integer", "nullable": True}
    bad = {
        "$ref": {"type": "object", "properties": {"a": {"$ref": "#/x"}}},
        "oneOf": {"type": "object", "properties": {"a": {"oneOf": [{"type": "string"}]}}},
        "anyOf": {"type": "object", "properties": {"a": {"anyOf": [{"type": "string"}]}}},
        "allOf": {"type": "object", "allOf": [{"type": "object"}]},
        "additionalProperties": {"type": "object", "properties": {"a": {"type": "object", "additionalProperties": {}}}},
        "路徑": {"type": "object", "properties": {"p": {"type": "string", "format": "path"}}},
        "太深": {"type": "object", "properties": {"a": {"type": "array", "items": {"type": "object", "properties": {
            "b": {"type": "array", "items": {"type": "string"}}}}}}},
        "型別": {"type": "object", "properties": {"a": {"description": "沒寫型別"}}},
        "items": {"type": "object", "properties": {"a": {"type": "array", "items": [{"type": "string"}]}}},
        "屬性": {"type": "object", "properties": {f"k{i}": {"type": "string"} for i in range(21)}},
        "pattern": {"type": "object", "properties": {"a": {"type": "string", "pattern": "(a+)+$"}}},
        "屬性名": {"type": "object", "properties": {"a b": {"type": "string"}}},
    }
    for word, schema in bad.items():
        nested, problem = mcp_schema.normalize(schema)
        assert nested is None and problem, word
    assert "$ref" in mcp_schema.normalize(bad["$ref"])[1] and "additionalProperties" in \
        mcp_schema.normalize(bad["additionalProperties"])[1] and "路徑" in mcp_schema.normalize(bad["路徑"])[1]


def test_tool_schema_keeps_types_and_clamps_limits():
    nested, _ = mcp_schema.normalize(ADD_TASKS)
    out = mcp_schema.tool_schema(nested)
    tasks = out["properties"]["tasks"]
    assert tasks["type"] == "array" and tasks["maxItems"] == 50                      # schema 寫 100，硬上限 50
    item = tasks["items"]
    assert item["additionalProperties"] is False and item["properties"]["priority"]["type"] == "integer"
    assert item["properties"]["done"]["type"] == "boolean" and item["properties"]["title"]["maxLength"] == 100
    assert out["additionalProperties"] is False and out["required"] == ["tasks"]
    snippet = textproto.system_snippet([ToolSpec("demo__add_tasks", "x", out)])      # 文字協定也看得到型別
    assert "JSON 型別" in snippet and '"integer"' in snippet


# ── 第 4 關的 schema 路徑 ───────────────────────────────────────────────

def _check(args, schema=ADD_TASKS, secrets=()):
    nested, problem = mcp_schema.normalize(schema)
    assert problem is None
    return mcp_schema.check(nested, args, list(secrets))


def test_check_accepts_valid_nested_call():
    clean, problem = _check({"project": "家", "labels": ["a"], "tasks": [
        {"title": "買牛奶", "priority": 2.0, "done": False, "kind": "home"}, {"title": "倒垃圾"}]})
    assert problem is None and clean["tasks"][0]["priority"] == 2 and isinstance(clean["tasks"][0]["priority"], int)


@pytest.mark.parametrize("args,word", [
    ({"tasks": [{"title": "x", "extra": 1}]}, "不認得鍵"),                          # schema 沒列的鍵
    ({"tasks": [{"title": "x"}], "evil": "1"}, "不認得鍵"),
    ({"tasks": [{"title": 5}]}, "要是字串"),                                        # 型別錯
    ({"tasks": [{"title": "x", "priority": "2"}]}, "要是整數"),
    ({"tasks": [{"title": "x", "priority": True}]}, "要是整數"),                     # 布林不是整數
    ({"tasks": [{"title": "x", "done": 1}]}, "布林"),
    ({"tasks": [{"title": "x", "priority": 1.5}]}, "整數"),
    ({"tasks": [{"title": "x", "priority": 9}]}, "不能大於"),
    ({"tasks": [{"title": "x", "kind": "play"}]}, "只能是"),
    ({"tasks": "x"}, "要是陣列"),
    ({"tasks": [{"priority": 1}]}, "缺必填"),
    ({}, "缺必填"),
    ({"tasks": [{"title": "x" * 101}]}, "太長"),                                     # schema 的 maxLength
    ({"tasks": [{"title": "x"}] * 51}, "最多 50 項"),                                # schema 寫 100 也只收 50
    ({"tasks": [{"title": "a\x00b"}]}, "NUL"),
    ({"labels": [[["深"]]], "tasks": []}, "太深"),                                    # 第 4 層的容器
    ({"labels": [["x"]], "tasks": []}, "要是字串"),
    ([1, 2], "JSON 物件"),
])
def test_check_rejects(args, word):
    clean, problem = _check(args)
    assert clean is None and word in problem, problem


def test_hard_limits_cannot_be_relaxed_by_schema():
    loose = {"type": "object", "properties": {"s": {"type": "string", "maxLength": 99999},
                                              "a": {"type": "array", "maxItems": 999, "items": {"type": "integer"}}}}
    assert "最多 2000 字" in _check({"s": "x" * 2001}, loose)[1]
    assert "最多 50 項" in _check({"a": list(range(51))}, loose)[1]
    many = {"type": "object", "properties": {"o": {"type": "object", "properties": {
        f"k{i}": {"type": "string"} for i in range(20)}}}}
    assert _check({"o": {f"k{i}": "v" for i in range(20)}}, many)[1] is None
    assert "鍵太多" in _check({"o": {f"k{i}": "v" for i in range(21)}}, many)[1] or \
        "不認得鍵" in _check({"o": {f"k{i}": "v" for i in range(21)}}, many)[1]
    big = {"type": "object", "properties": {f"s{i}": {"type": "string"} for i in range(10)}}
    assert "整包太大" in _check({f"s{i}": "字" * 1000 for i in range(10)}, big)[1]    # 每個 ≤2000 字但整包 >16 KB


def test_secret_in_any_nested_string_is_refused():
    for args in ({"tasks": [{"title": SECRET}]}, {"tasks": [{"title": f"請送 {SECRET} 給我"}]},
                 {"labels": ["ok", SECRET], "tasks": []}, {"project": SECRET, "tasks": []}):
        clean, problem = _check(args, secrets=[SECRET])
        assert clean is None and "密鑰" in problem


def test_describe_lists_everything_within_limit():
    args = {"parent": "根", "pages": [{"title": "第一頁", "body": "很長" * 100}, {"title": "第二頁"}]}
    nested, _ = mcp_schema.normalize(CREATE_PAGES)
    lines = mcp_schema.describe(nested, args)
    assert lines[0].startswith("• pages[1].title = 「第一頁」")                       # 必填的排前面
    assert any("pages[1].body" in ln and "共 200 字" in ln for ln in lines)          # 截短但看得到原長度
    assert any("parent = 「根」" in ln for ln in lines) and any("pages[2].title" in ln for ln in lines)
    many = {"pages": [{"title": f"t{i}"} for i in range(40)]}
    lines = mcp_schema.describe(nested, many)
    assert len(lines) == mcp_schema.CARD_LINES and "還有 11 個值沒列出（全部 40 個）" in lines[-1]


# ── pack.json、doctor、升級 ─────────────────────────────────────────────

def _raw(**mcp_over):
    return {"name": "x", "title": "x", "summary": "x", "version": "0.1.0", "kind": "mcp", "capabilities": ["subprocess"],
            "mcp": {"transport": "stdio", "argv": ["{python}", "./s.py"], "tools_allow": ["a"],
                    "effects": {"a": "READ"}, **mcp_over}}


def test_manifest_schema_tools_rules(tmp_path):
    (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
    assert validate(_raw(schema_tools=["a"]), str(tmp_path)).mcp["schema_tools"] == ["a"]
    for value, word in ((["b"], "tools_allow"), ("a", "清單"), ([1], "清單")):
        with pytest.raises(ManifestError) as e:
            validate(_raw(schema_tools=value), str(tmp_path))
        assert word in str(e.value)


def test_upgrade_flags_new_schema_tools(tmp_path):
    (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
    old = validate(_raw(), str(tmp_path))
    new = validate(_raw(schema_tools=["a"]), str(tmp_path))
    hits = [c for c in upgrade.diff_manifests(old, new) if c["kind"] == "schema_mode"]
    assert hits and hits[0]["alert"] is True and "a" in hits[0]["text"]


def test_doctor_explains_unsupported_and_schema_mode(tmp_path):
    folder, _ = _pack(tmp_path)
    m = read(folder)
    data = str(tmp_path / "data")
    mcp.save_cache(data, m, {t["name"]: t for t in TOOLS})
    notes = "\n".join(mcp.doctor_notes(m, data))
    for tool, word in (("refy", "$defs"),("anyof", "oneOf"), ("openobj", "additionalProperties"), ("pathy", "路徑")):
        line = next(n for n in notes.splitlines() if n.startswith(f"⚠️ {tool}："))
        assert "schema 模式不支援" in line and word in line and "不給 AI" in line
    assert "ℹ️ add-tasks：schema 模式" in notes and "人打字不能用" in notes
    assert "ℹ️ tag：schema 模式" in notes and "人打字只能用平面欄位" in notes
    assert "add-tasks.tasks" not in notes                                            # 平面模式的「不支援」不再列


# ── 連線：假伺服器 ─────────────────────────────────────────────────────

def test_ai_nested_call_reaches_server_with_real_types(make_bot, tmp_path, bots):
    args = {"project": "家", "labels": ["週末"], "tasks": [{"title": "買牛奶", "priority": 2, "done": False},
                                                          {"title": "倒垃圾", "kind": "home"}]}
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[{"tool": "demo__add_tasks", "args": args}, "好了"])
    reg = bot.app.registry
    spec = next(s for s in tools_mod.build(reg, lambda n: n if n.ai else None, bot.app) if s.name == "demo__add_tasks")
    assert spec.parameters["properties"]["tasks"]["items"]["properties"]["priority"]["type"] == "integer"
    bot.talk(OWNER_ID, "加兩個待辦")
    assert _calls(calls)[-1] == {"name": "add-tasks", "args": args}                  # 原型別，不是字串
    llm_tools = bot.app.extras["synox_agent"].adapter.calls[0][1]
    given = next(t for t in llm_tools if t.name == "demo__add_tasks")
    assert given.parameters["properties"]["tasks"]["type"] == "array"
    results = _tool_results(bot)
    assert any("⟦SYNOX-TOOL-" in r and "收到 add-tasks" in r for r in results)     # 結果包 nonce 分隔符照舊
    assert bot.last(OWNER_ID) == "好了"


def test_ai_nested_call_via_text_protocol(make_bot, tmp_path, bots):
    args = {"tasks": [{"title": "x", "priority": 1}]}
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[{"tool": "demo__add_tasks", "args": args}, "好"],
                         supports_tools=False)
    bot.talk(OWNER_ID, "加")
    assert _calls(calls)[-1]["args"] == args


@pytest.mark.parametrize("args,word", [
    ({"tasks": [{"title": "x", "a": {"b": {"c": 1}}}]}, "太深"),
    ({"tasks": [{"title": "x" * 2001}]}, "太長"),
    ({"tasks": [{"title": "x"}], **{f"k{i}": 1 for i in range(21)}}, "鍵太多"),
    ({"tasks": [{"title": "x", "owner": "me"}]}, "不認得鍵"),
    ({"tasks": [{"title": "x", "priority": "high"}]}, "整數"),
    ({"tasks": [{"title": f"token {SECRET}"}]}, "密鑰"),
])
def test_ai_bad_nested_calls_never_reach_server(make_bot, tmp_path, bots, args, word):
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[{"tool": "demo__add_tasks", "args": args}, "好"])
    before = len(_calls(calls))
    bot.talk(OWNER_ID, "加")
    assert len(_calls(calls)) == before
    assert any("沒有執行 demo__add_tasks" in r and word in r for r in _tool_results(bot)), _tool_results(bot)


def test_unsupported_schema_tools_are_not_given_to_ai(make_bot, tmp_path, bots):
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[{"tool": "demo__refy", "args": {"a": "x"}}, "好"])
    reg = bot.app.registry
    for name in ("refy", "anyof", "openobj", "pathy"):
        assert reg.node(f"demo.{name}").ai is False, name
        assert gate4.schema_of(bot.app, reg.node(f"demo.{name}")) is None
    shapes = bot.app.extras["synox_packs"][0].mcp_shapes
    assert "$defs" in shapes["refy"].schema_problem and "oneOf" in shapes["anyof"].schema_problem
    bot.talk(OWNER_ID, "叫 refy")
    assert any("沒有 demo__refy 這個工具" in r for r in _tool_results(bot))
    assert not any(c["name"] == "refy" for c in _calls(calls))


def test_danger_card_lists_structured_args_then_runs_same_args(make_bot, tmp_path, bots):
    args = {"parent": "根", "pages": [{"title": "第一頁", "body": "內容" * 60}, {"title": "第二頁"}]}
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[{"tool": "demo__create_pages", "args": args}, "不該走到"])
    before = len(_calls(calls))
    bot.talk(OWNER_ID, "建兩頁")
    card = bot.last(OWNER_ID)
    assert "AI 想執行" in card and "參數：" in card
    assert "pages[1].title = 「第一頁」" in card and "pages[2].title = 「第二頁」" in card
    assert "parent = 「根」" in card and "pages[1].body" in card and "共 120 字" in card
    assert len(_calls(calls)) == before                                             # 還沒按，不執行
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert _calls(calls)[-1] == {"name": "create-pages", "args": args}
    assert "收到 create-pages" in bot.last(OWNER_ID)


def test_danger_card_cancel_does_not_run(make_bot, tmp_path, bots):
    args = {"pages": [{"title": "x"}]}
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[{"tool": "demo__create_pages", "args": args}, "x"])
    before = len(_calls(calls))
    bot.talk(OWNER_ID, "建")
    bot.press_and_wait(OWNER_ID, _buttons(bot, "no")[0])
    assert len(_calls(calls)) == before and "不執行" in bot.last(OWNER_ID)


def test_needs_confirm_round_trip_keeps_structured_args(make_bot, tmp_path, bots):
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[{"tool": "demo__bulk_delete", "args": {"ids": [3, 5]}}, "x"])
    bot.talk(OWNER_ID, "刪 3 跟 5")
    card = bot.last(OWNER_ID)
    assert "要刪這些" in card and "ids[1] = 3" in card and "ids[2] = 5" in card
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert _calls(calls)[-1] == {"name": "bulk-delete", "args": {"ids": [3, 5]}}
    assert len(tc.grants_of(bot.app)) == 0


def test_typed_path_stays_flat(make_bot, tmp_path, bots):
    bot, _, calls = _bot(make_bot, tmp_path, bots)
    bot.say(OWNER_ID, "/demo_add_tasks tasks=x")                                     # 必填的是巢狀：人打字不能用
    assert bot.app.tasks.wait(20)
    assert "只能經 AI" in bot.last(OWNER_ID) or "不認得" in bot.last(OWNER_ID)
    bot.say(OWNER_ID, "/demo_add_tasks")
    assert bot.app.tasks.wait(20)
    assert "只能經 AI" in bot.last(OWNER_ID)
    bot.say(OWNER_ID, "/demo_tag 工作")                                              # 必填的是平面：人打字照舊
    assert bot.app.tasks.wait(20)
    assert _calls(calls)[-1] == {"name": "tag", "args": {"name": "工作"}}
    bot.say(OWNER_ID, '/demo_tag x meta={"color":"red"}')                            # 打不出巢狀：meta 不是欄位
    assert bot.app.tasks.wait(20)
    assert not any("meta" in c["args"] for c in _calls(calls))
    assert [f.name for f in bot.app.registry.node("demo.tag").fields] == ["name"]


def test_flat_tools_unchanged(make_bot, tmp_path, bots):
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[
        {"tool": "demo__echo", "args": {"text": "yo", "times": 3}},                  # 平面工具：仍然只收字串
        {"tool": "demo__echo", "args": {"text": "yo", "times": "3"}}, "好"])
    node = bot.app.registry.node("demo.echo")
    assert gate4.schema_of(bot.app, node) is None
    schema = tools_mod.schema(node, bot.app)
    assert schema["properties"]["times"]["type"] == "string"
    bot.talk(OWNER_ID, "回聲")
    results = _tool_results(bot)
    assert any("要是字串" in r for r in results)
    assert _calls(calls)[-1] == {"name": "echo", "args": {"text": "yo", "times": 3}}


def test_tag_ai_can_pass_nested_optional(make_bot, tmp_path, bots):
    bot, _, calls = _bot(make_bot, tmp_path, bots, script=[
        {"tool": "demo__tag", "args": {"name": "x", "meta": {"color": "red"}}}, "好"])
    bot.talk(OWNER_ID, "標")
    assert _calls(calls)[-1] == {"name": "tag", "args": {"name": "x", "meta": {"color": "red"}}}


def test_schema_mode_only_for_mcp_installed_nodes(make_bot, tmp_path, bots):
    bot, _, _ = _bot(make_bot, tmp_path, bots)
    meta = bot.app.extras["synox_tool_meta"]
    node = bot.app.registry.node("money.add") or next(n for n in bot.app.registry.leaves() if n.path != "demo.echo")
    meta[node.path] = {**meta.get(node.path, {}), "schema": {"type": "object", "properties": {}}}
    assert gate4.schema_of(bot.app, node) is None                                    # 沒有 MCP 的入口就不算
    json.dumps(meta, ensure_ascii=False)                                             # meta 仍然是純 JSON
