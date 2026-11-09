# -*- coding: utf-8 -*-
"""SDK P4a：kind=mcp、mcp.transport=stdio 真的連線。假伺服器是 tmp 裡一支只用標準函式庫的 Python（可以故意壞掉：
崩潰、卡住、印非 JSON）；真伺服器是 SDK 的 serve --mcp。全部是本機子程序、stdio 管線，不連網、不開埠。"""
import json
import os
import sys

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID

from synox import sandbox, sdk
from synox.agent import tools as tools_mod
from synox.agent.loop import ai_decision
from synox.packs import loader, mcp, scan
from synox.packs import confirm as tc
from synox.packs.manifest import ManifestError, read, validate

FAKE = r'''
import json, os, sys, time
for s in (sys.stdin, sys.stdout):
    s.reconfigure(encoding="utf-8")
TOOLS = [
    {"name": "echo", "description": "回聲。\n\n第二段不進說明",
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "required": ["text"], "properties": {
         "text": {"type": "string", "description": "要說的話"}, "times": {"type": "integer"},
         "loudVoice": {"type": "boolean"}, "color": {"enum": ["Red", "Blue"]},
         "opts": {"type": "object"}, "tags": {"type": "array"}}}},
    {"name": "wipeAll", "description": "全部刪掉", "annotations": {"readOnlyHint": True, "destructiveHint": False},
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "hidden", "description": "沒列在 tools_allow", "inputSchema": {"type": "object"}},
    {"name": "crash", "description": "崩潰", "inputSchema": {"type": "object"}},
    {"name": "hang", "description": "卡住", "inputSchema": {"type": "object"}},
    {"name": "garbage", "description": "印非 JSON", "inputSchema": {"type": "object"}},
    {"name": "purge", "description": "刪舊的（要確認）", "inputSchema": {"type": "object", "properties": {"days": {"type": "integer"}}}},
    {"name": "nag", "description": "一直要確認", "inputSchema": {"type": "object"}},
    {"name": "deep", "description": "必填巢狀", "inputSchema": {"type": "object", "required": ["cfg"], "properties": {"cfg": {"type": "object"}}}},
]
def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n"); sys.stdout.flush()
def text(id, t, **extra):
    out({"jsonrpc": "2.0", "id": id, "result": {"content": [{"type": "text", "text": t}], "isError": False, **extra}})
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
    elif method == "ping":
        out({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "tools/call":
        name, args, meta = params.get("name"), params.get("arguments") or {}, params.get("_meta") or {}
        if name == "echo":
            env = {k: os.environ.get(k, "") for k in ("SYNOX_TG_ID", "SYNOX_USER_DATA_DIR", "SYNOX_PACK_NAME",
                                                       "SYNOX_CONFIRMED", "LEAKY_API_KEY", "FAKE_MODE")}
            text(mid, json.dumps({"args": args, "pid": os.getpid(), "env": env}, ensure_ascii=False))
        elif name == "wipeAll":
            text(mid, "全部刪了")
        elif name == "hidden":
            text(mid, "不該被叫到")
        elif name == "crash":
            sys.stderr.write("boom\n"); sys.stderr.flush(); os._exit(3)
        elif name == "hang":
            time.sleep(120)
        elif name == "garbage":
            sys.stdout.write("Traceback: not json at all\n"); sys.stdout.flush()
        elif name in ("purge", "nag"):
            if name == "purge" and meta.get("synox/confirm_token") == "tok-7":
                text(mid, "刪了 3 筆 token=" + meta["synox/confirm_token"])
            else:
                text(mid, "還沒做", structuredContent={"needs_confirm": True, "summary": "要刪 3 筆",
                                                     "confirm_token": "tok-7"})
        else:
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool"}})
    else:
        out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found"}})
'''

ALLOW = ["echo", "wipeAll", "crash", "hang", "garbage", "purge", "nag", "deep"]
EFFECTS = {"echo": "READ", "wipeAll": "DANGER", "crash": "READ", "hang": "READ", "garbage": "READ",
           "purge": "WRITE", "nag": "WRITE", "deep": "READ"}


def _pack(base, name="demo", **over):
    folder = os.path.join(str(base), name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "server.py"), "w", encoding="utf-8") as f:
        f.write(FAKE)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: 假的 MCP 伺服器\n---\n正文\n")
    mcp_raw = {"transport": "stdio", "argv": ["{python}", "./server.py"], "env": {"FAKE_MODE": "{tg_id}"},
               "timeout": 3, "tools_allow": ALLOW, "effects": EFFECTS, **over.pop("mcp", {})}
    raw = {"name": name, "title": "假 MCP", "summary": "測試用", "version": "0.1.0", "kind": "mcp",
           "capabilities": ["subprocess"], "data": "user", "skill": "SKILL.md", "mcp": mcp_raw, **over}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    return folder


def _bot(make_bot, tmp_path, script=None, raw=None, **over):
    folder = _pack(tmp_path / "packs", **over)
    bot = make_bot(script, raw=raw, pack_dirs=(str(tmp_path / "packs"),))
    item = bot.app.extras["synox_pack_report"].items[0]
    assert item.status == "loaded", item.detail
    return bot, folder


def _pool(bot):
    return bot.app.extras["synox_mcp_pool"]


def _echo(bot, uid=OWNER_ID, text="/demo_echo hi"):
    bot.say(uid, text)
    assert bot.app.tasks.wait(20)
    return json.loads(bot.last(uid))


def _buttons(bot, kind, uid=OWNER_ID):
    return [b for b in bot.buttons(uid) if b.startswith(f"agent_ok:{kind}:")]


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


# ── pack.json 與第 2 關 ─────────────────────────────────────────────────

def _raw(**mcp_over):
    return {"name": "x", "title": "x", "summary": "x", "version": "0.1.0", "kind": "mcp", "capabilities": ["subprocess"],
            "mcp": {"transport": "stdio", "argv": ["{python}", "./s.py"], "tools_allow": ["a"],
                    "effects": {"a": "READ"}, **mcp_over}}


def test_manifest_stdio_rules(tmp_path):
    (tmp_path / "SKILL.md").write_text("x", encoding="utf-8")
    m = validate(_raw(), str(tmp_path), strict=True)
    assert m.mcp_stdio and not m.registered_only and m.data == "none"
    assert validate(_raw(env={"HOME_X": "{user_data_dir}/x"}), str(tmp_path)).data == "user"   # 樣板推 data（同 cli）
    for raw, word in ((_raw(argv=[]), "mcp.argv"), (_raw(transport="sse"), "stdio"), (_raw(url="http://x"), "url"),
                      (_raw(timeout=0), "timeout"), (_raw(env={"A": 1}), "mcp.env"),
                      ({**_raw(), "capabilities": []}, "subprocess"),
                      (_raw(effects={}), "effect")):
        with pytest.raises(ManifestError, match=word):
            validate(raw, str(tmp_path), strict=True)
    legacy = validate({**_raw(), "mcp": {"url": "https://x", "tools_allow": ["a"], "effects": {"a": "READ"}}},
                      str(tmp_path))
    assert legacy.registered_only and not legacy.mcp_stdio


def test_scan_allows_code_for_stdio_and_marks_external(tmp_path):
    folder = _pack(tmp_path)
    m = read(folder, strict=True)
    report = scan.scan(m)
    assert report.problems(m) == []                                         # pack 內的 .py 照一般掃（只讀 os.environ）
    assert any(f.kind == "env" and f.file == "server.py" for f in report.findings)
    # pack 外的程式：不擋，標「未鎖定執行環境」
    ext = _pack(tmp_path / "ext", mcp={"argv": ["npx", "-y", "some-server", "C:/tools/x.js"]})
    m = read(ext, strict=True)
    found = [f for f in scan.scan(m).findings if f.kind == "external"]
    assert [f.snippet for f in found] == ["npx", "C:/tools/x.js"] and scan.scan(m).problems(m) == []
    assert "未鎖定執行環境" in scan.scan(m).format(m)
    # 沒宣告的能力照擋；argv 用了不認得的代換也擋
    bad = _pack(tmp_path / "bad", mcp={"argv": ["{python}", "./server.py", "{secret}"]})
    with open(os.path.join(bad, "net.py"), "w", encoding="utf-8") as f:
        f.write("import socket\n")
    m = read(bad, strict=True)
    problems = scan.scan(m).problems(m)
    assert any("network" in p for p in problems) and any("mcp.argv" in p for p in problems)
    # data=user 不准 {data_dir}（同 cli）
    shared = _pack(tmp_path / "sh", mcp={"env": {"X": "{data_dir}/x"}})
    m = read(shared, strict=True)
    assert any("data" in p for p in scan.scan(m).problems(m))
    # 只登記的 mcp 照舊不准附程式
    legacy = os.path.join(str(tmp_path), "legacy")
    os.makedirs(legacy)
    with open(os.path.join(legacy, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({**_raw(), "mcp": {"url": "https://x", "tools_allow": ["a"], "effects": {"a": "READ"}}}, f)
    for n in ("SKILL.md", "s.py"):
        with open(os.path.join(legacy, n), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
    m = read(legacy)
    assert any("只能是宣告" in p for p in scan.scan(m).problems(m))


def test_shape_and_names():
    assert mcp.to_identifier("getWeather") == "get_weather" and mcp.to_identifier("search-docs.v2") == "search_docs_v2"
    assert mcp.to_identifier("2fa") == "t_2fa" and mcp.to_identifier("中文") == "t"
    assert mcp.unique_identifiers(["a-b", "a_b", "A.B"]) == {"a-b": "a_b", "a_b": "a_b_2", "A.B": "a_b_3"}
    spec = {"description": "x", "inputSchema": {"type": "object", "required": ["q", "cfg"], "properties": {
        "q": {"type": "string"}, "maxResults": {"type": ["integer", "null"], "default": 5},
        "ratio": {"type": "number"}, "on": {"type": "boolean"}, "lvl": {"enum": [1, 2]}, "cfg": {"type": "object"}}}}
    shape = mcp.shape_of("t", "t", spec)
    assert [(f.name, f.prop, f.kind) for f in shape.fields] == [
        ("q", "q", "text"), ("max_results", "maxResults", "int"), ("ratio", "ratio", "number"),
        ("on", "on", "bool"), ("lvl", "lvl", "choice")]
    assert shape.fields[1].default == "5" and not shape.callable and "cfg" in shape.notes[0]
    args = mcp.to_arguments(shape, {"q": "hi", "max_results": "3", "ratio": "2.5", "on": "true", "lvl": "2"})
    assert args == {"q": "hi", "maxResults": 3, "ratio": 2.5, "on": True, "lvl": 2}


def test_effect_only_from_pack_json_missing_is_danger(tmp_path):
    m = read(_pack(tmp_path))
    assert mcp.effect_name(m, "echo") == "READ" and mcp.effect_name(m, "wipeAll") == "DANGER"
    m.mcp["effects"].pop("echo")
    assert mcp.effect_name(m, "echo") == "DANGER"                          # 沒指定＝DANGER


# ── 連線：假伺服器 ─────────────────────────────────────────────────────

def test_tools_become_leaves_and_typed_call_works(make_bot, tmp_path, bots):
    bot, folder = _bot(make_bot, tmp_path)
    bots.append(bot)
    reg = bot.app.registry
    assert _pool(bot).started == 0                                          # 載入時不啟動
    leaves = sorted(n.name for n in reg.node("demo").walk() if not n.is_group)
    assert leaves == sorted(["echo", "wipe_all", "crash", "hang", "garbage", "purge", "nag", "deep"])
    assert reg.node("demo.hidden") is None                                  # 沒列在 tools_allow＝不存在
    assert reg.node("demo.wipe_all").effect == "danger"                     # 工具自述 readOnlyHint 不算
    assert reg.node("demo.echo").effect == "read" and reg.node("demo.purge").effect == "write"
    reply = _echo(bot)
    assert reply["args"] == {"text": "hi"} and reply["env"]["SYNOX_PACK_NAME"] == "demo"
    assert reply["env"]["SYNOX_TG_ID"] == str(OWNER_ID) and reply["env"]["FAKE_MODE"] == str(OWNER_ID)
    assert reply["env"]["SYNOX_CONFIRMED"] == "0"
    # 讀過 tools/list：說明、欄位進節點（/help、AI schema），巢狀的不給
    node = reg.node("demo.echo")
    assert node.summary == "回聲。" and [f.name for f in node.fields] == ["text", "times", "loud_voice", "color"]
    assert node.fields[3].choices == ("Red", "Blue")
    again = _echo(bot, text="/demo_echo 你好 times=2 loud_voice=是 color=blue")
    assert again["args"] == {"text": "你好", "times": 2, "loudVoice": True, "color": "Blue"}
    assert again["pid"] == reply["pid"] and _pool(bot).started == 1         # 同一個長駐程序
    bot.say(OWNER_ID, "/demo_echo hi times=x")
    bot.app.tasks.wait(20)
    assert "整數" in bot.last(OWNER_ID)                                       # 型別檢查在交給工具之前
    cache = mcp.load_cache(bot.app.config.data_dir, read(folder))
    assert set(cache) == set(ALLOW)                                          # 快取只留 allowed（沒有 hidden）
    help_text = "\n".join(n.summary for n in reg.node("demo").walk() if not n.is_group)
    assert "回聲。" in help_text and "第二段" not in help_text
    assert reg.node("demo.deep").ai is False
    bot.say(OWNER_ID, "/demo_deep")
    bot.app.tasks.wait(20)
    assert "不支援" in bot.last(OWNER_ID)


def test_idle_reap_with_injected_clock(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path)
    bots.append(bot)
    pool = _pool(bot)
    now = [1000.0]
    pool.clock = lambda: now[0]
    first = _echo(bot)["pid"]
    now[0] += 599
    assert pool.reap() == 0 and len(pool.keys()) == 1
    now[0] += 2                                                              # 閒置超過 10 分鐘
    assert pool.reap() == 1 and pool.keys() == []
    second = _echo(bot)["pid"]
    assert second != first and pool.started == 2


def test_crash_then_restart(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path)
    bots.append(bot)
    first = _echo(bot)["pid"]
    bot.say(OWNER_ID, "/demo_crash")
    assert bot.app.tasks.wait(20)
    assert "中途結束" in bot.last(OWNER_ID) and "重新啟動" in bot.last(OWNER_ID)
    assert _echo(bot)["pid"] != first                                        # 下一次呼叫重啟


def test_timeout_and_bad_json_are_human_errors(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path, mcp={"timeout": 1.5})
    bots.append(bot)
    bot.say(OWNER_ID, "/demo_hang")
    assert bot.app.tasks.wait(20)
    assert "超過 1.5 秒沒有回應" in bot.last(OWNER_ID)
    bot.say(OWNER_ID, "/demo_garbage")
    assert bot.app.tasks.wait(20)
    assert "看不懂的東西" in bot.last(OWNER_ID) and "Traceback" in bot.last(OWNER_ID)
    assert _echo(bot)["args"] == {"text": "hi"}                               # bot 沒卡住，還能用
    assert _pool(bot).started == 3


def test_start_failure_is_human_error(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path, mcp={"argv": ["{python}", "./nope.py"]})
    bots.append(bot)
    bot.say(OWNER_ID, "/demo_echo hi")
    assert bot.app.tasks.wait(20)
    assert "啟動失敗" in bot.last(OWNER_ID) and "中途結束" in bot.last(OWNER_ID)


def test_ai_unlisted_tool_refused_danger_card_and_delimited(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path, script=[{"tool": "demo__hidden", "args": {}},
                                              {"tool": "demo__echo", "args": {"args": "hey"}},     # 還不知道欄位
                                              {"tool": "demo__echo", "args": {"text": "yo", "times": "2"}}, "好了",
                                              {"tool": "demo__wipe_all", "args": {}}, "不該走到這裡"])
    bots.append(bot)
    assert "args" in tools_mod.schema(bot.app.registry.node("demo.echo"))["properties"]
    bot.talk(OWNER_ID, "叫一下")
    adapter = bot.app.extras["synox_agent"].adapter
    tool_msgs = [m.content for msgs, _tools in adapter.calls for m in msgs if getattr(m, "role", "") == "tool"]
    assert "假的 MCP 伺服器" in adapter.calls[0][0][0].content                 # SKILL 進系統提示（mcp stdio 不再被略過）
    assert any("沒有 demo__hidden 這個工具" in t for t in tool_msgs)
    assert any("⟦SYNOX-TOOL-" in t and '"text": "hey"' in t for t in tool_msgs)   # 結果包 nonce 分隔符
    assert any('"times": 2' in t for t in tool_msgs)                          # 讀過 tools/list 之後用具名欄位
    assert set(tools_mod.schema(bot.app.registry.node("demo.echo"))["properties"]) == {"text", "times", "loud_voice", "color"}
    started = _pool(bot).started
    bot.talk(OWNER_ID, "全部刪掉")
    assert "AI 想執行" in bot.last(OWNER_ID) and "全部刪了" not in "\n".join(bot.texts(OWNER_ID))
    assert _pool(bot).started == started
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert bot.last(OWNER_ID) == "全部刪了"


def test_needs_confirm_round_trip_with_meta(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path)
    bots.append(bot)
    bot.say(OWNER_ID, "/demo_purge days=7")
    assert bot.app.tasks.wait(20)
    card = bot.last(OWNER_ID)
    assert "要你確認才會做" in card and "要刪 3 筆" in card and "days=7" in card
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert bot.last(OWNER_ID) == "刪了 3 筆 token=tok-7"                     # 同一組參數＋_meta 的 token
    assert len(tc.grants_of(bot.app)) == 0
    bot.say(OWNER_ID, "/demo_nag")
    assert bot.app.tasks.wait(20)
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert bot.last(OWNER_ID) == tc.AGAIN.format(name="nag")                 # 確認過又要確認：停


def test_needs_confirm_via_ai(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path, script=[{"tool": "demo__purge", "args": {"days": "7"}}, "不該走到這裡"])
    bots.append(bot)
    _echo(bot)                                                               # 先讓欄位已知
    bot.talk(OWNER_ID, "刪舊的")
    assert "要刪 3 筆" in bot.last(OWNER_ID) and "不該走到這裡" not in "\n".join(bot.texts(OWNER_ID))
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    assert bot.last(OWNER_ID) == "刪了 3 筆 token=tok-7"


def test_sandbox_wrap_gets_grants_and_clean_env(make_bot, tmp_path, bots, monkeypatch):
    seen = []

    class Recorder(sandbox.Sandbox):
        name, isolates = "recorder", True

        def wrap(self, argv, env, cwd, grants):
            seen.append((list(argv), dict(env), cwd, grants))
            return list(argv), dict(env)

    sandbox.set_factory(lambda config: Recorder())
    monkeypatch.setenv("LEAKY_API_KEY", "should-not-pass")
    bot, folder = _bot(make_bot, tmp_path)
    bots.append(bot)
    reply = _echo(bot)
    assert reply["env"]["LEAKY_API_KEY"] == ""                               # clean_env 照舊拿掉像密鑰的
    (argv, env, cwd, g), = seen
    data_dir = bot.app.config.data_dir
    assert argv[0] == sys.executable and argv[1] == os.path.join(folder, "server.py")
    assert g.write == (os.path.normpath(os.path.join(data_dir, "demo")),)   # data=user：<user_data_dir>/<pack>
    assert os.path.normpath(folder) in g.read and g.network is False and g.timeout is None
    assert "SYNOX_CONFIRM_TOKEN" in g.pass_env and g.hide == (os.path.normpath(data_dir),)
    assert env["SYNOX_PACK_NAME"] == "demo" and cwd == os.path.normpath(folder)


def test_shutdown_closes_processes(make_bot, tmp_path):
    bot, _ = _bot(make_bot, tmp_path)
    _echo(bot)
    pool = _pool(bot)
    (session,) = [pool.get(k) for k in pool.keys()]
    for hook in list(bot.app.on_stop):
        hook(bot.app)
    assert pool.keys() == [] and not session.alive and session.proc.poll() is not None


def test_shared_scope_is_interface_only():
    with pytest.raises(NotImplementedError, match="shared"):
        mcp.SharedScope().key("demo", None)
    assert mcp.PerUserScope().key("demo", type("U", (), {"tg_id": 5})()) == ("demo", 5)
    assert set(mcp.SCOPES) == {"per-user", "shared"}


def test_doctor_notes(tmp_path):
    folder = _pack(tmp_path, mcp={"argv": ["node", "./server.py"]})
    m = read(folder)
    data = str(tmp_path / "data")
    notes = mcp.doctor_notes(m, data)
    assert any("未鎖定執行環境" in n and "node" in n for n in notes) and any("還沒連過" in n for n in notes)
    mcp.save_cache(data, m, {"echo": {"name": "echo", "inputSchema": {"type": "object", "properties": {
        "opts": {"type": "object"}}}}})
    notes = mcp.doctor_notes(m, data)
    assert any("opts" in n and "不支援" in n for n in notes) and any("crash" in n and "沒有這個工具" in n for n in notes)


# ── 伺服器版：角色、每人一個程序 ─────────────────────────────────────────

def test_server_roles_and_per_user_processes(make_bot, tmp_path, bots):
    bot, _ = _bot(make_bot, tmp_path, raw={"mode": "server"}, access="member")
    bots.append(bot)
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    guest = 777
    bot.make(guest, BasicRoles.GUEST)
    reg = bot.app.registry
    for uid in (OTHER_ID, guest):                                            # subprocess 超出成員／訪客的能力上限
        user = bot.app.users.get_or_create(uid)
        assert not reg.visible(user, reg.node("demo"))
        assert not any(s.name.startswith("demo__") for s in
                       tools_mod.build(reg, lambda n: ai_decision(bot.app, user, n)))
        bot.say(uid, "/demo_echo hi")
        assert bot.last(uid) == "未知指令：/demo_echo，輸入 /help 查看可用指令。"
    assert _pool(bot).started == 0
    admin = 888
    bot.make(admin, BasicRoles.ADMIN)                                        # 管理員的上限有 subprocess
    mine, theirs = _echo(bot), _echo(bot, admin)
    assert mine["pid"] != theirs["pid"] and _pool(bot).started == 2          # 每個 (pack, 使用者) 一個程序
    assert theirs["env"]["SYNOX_TG_ID"] == str(admin)
    assert theirs["env"]["SYNOX_USER_DATA_DIR"].endswith(os.path.join("users", str(admin)))


# ── 真伺服器：SDK 的 serve --mcp ───────────────────────────────────────

SDK_TOOL = r'''"""SDK 寫的 MCP 伺服器。"""
from synox_sdk import Confirm, Ok, confirmed, context, serve, tool


@tool("READ")
def add(amount: int, memo: str = ""):
    """記一筆。

    Args:
        amount: 金額
    """
    return Ok(f"記了 {amount} {memo}".strip() + f" by {context().tg_id}")


@tool("WRITE")
def purge(days: int):
    """刪舊的。"""
    key = f"d{days}"
    if not confirmed(key):
        raise Confirm(f"要刪 {days} 天前的", token=key)
    return f"刪了 {days} 天前的"


if __name__ == "__main__":
    serve()
'''


def test_real_sdk_server(make_bot, tmp_path, bots):
    folder = tmp_path / "packs" / "sdkm"
    folder.mkdir(parents=True)
    (folder / "tool.py").write_text(SDK_TOOL, encoding="utf-8")
    sdk.write_single_file(str(folder / "synox_sdk.py"))
    (folder / "SKILL.md").write_text("---\nname: sdkm\ndescription: SDK 的 MCP\n---\n", encoding="utf-8")
    (folder / "pack.json").write_text(json.dumps({
        "name": "sdkm", "title": "SDK MCP", "summary": "真的 serve --mcp", "version": "0.1.0", "kind": "mcp",
        "capabilities": ["subprocess"], "skill": "SKILL.md",
        "mcp": {"transport": "stdio", "argv": ["{python}", "./tool.py", "--mcp"], "timeout": 20,
                "tools_allow": ["add", "purge"], "effects": {"add": "WRITE", "purge": "WRITE"}}}), encoding="utf-8")
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    bots.append(bot)
    assert bot.app.extras["synox_pack_report"].items[0].status == "loaded"
    bot.say(OWNER_ID, "/sdkm_add 5 memo=午餐")
    assert bot.app.tasks.wait(30)
    assert bot.last(OWNER_ID) == f"記了 5 午餐 by {OWNER_ID}"
    node = bot.app.registry.node("sdkm.add")
    assert node.summary == "記一筆。" and node.effect.upper() == "WRITE"     # effect 來自 pack.json，不是工具
    assert [(f.name, f.ask, f.required) for f in node.fields] == [("amount", "金額", True), ("memo", "memo", False)]
    bot.say(OWNER_ID, "/sdkm_purge 7")
    assert bot.app.tasks.wait(30)
    assert "要刪 7 天前的" in bot.last(OWNER_ID)
    bot.press_and_wait(OWNER_ID, _buttons(bot, "go")[0])
    bot.app.tasks.wait(30)
    assert bot.last(OWNER_ID) == "刪了 7 天前的"                             # SDK 的 confirmed() 從 _meta 拿到 token
    assert _pool(bot).started == 1
