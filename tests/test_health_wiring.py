# -*- coding: utf-8 -*-
"""工具健康接上整支 SYNOX（docs/tool-health.md）：假工具（kind=cli 用 synox_sdk、kind=python、kind=mcp 各一個）、
假 AI（只計次）、假時鐘、暫存資料夾裡的保管箱。AI 收到固定格式的一行、diag 與金鑰不進 AI；壞掉的工具不在 AI 的工具清單、
系統提示最後一行原因；AI 硬叫不執行；冷卻到了用自我檢查（AI 呼叫 0 次）；人手動打照常跑、多一行警告；
fail open（例外、存檔壞掉、設定關掉、沒裝）。doctor、網頁在 test_health_doctor.py／test_health_web.py。
子程序都是本機 Python，不連網、不開埠。"""
import json

from conftest import OWNER_ID

from synox import health, sdk
from synox.health import BROKEN, HEALTHY, NEEDS_ACTION, QUARANTINED
from synox.llm.base import SYSTEM, TOOL

FAKE_KEY = "sk-" + "Zy9Xw8Vu7Ts6Rq5Po4Nm3Lk2"            # prepublish-check: allow（假的）

CLI_TOOL = r'''"""健康測試用的假工具：mode.txt 決定這一次成功、哪一種失敗、丟例外、還是卡住。"""
import os
import time

from synox_sdk import ToolError, context, fail, serve, tool


def _mode(name):
    try:
        with open(os.path.join(context().pack_dir, name), encoding="utf-8") as f:
            return f.read().strip() or "ok"
    except OSError:
        return "ok"


@tool("READ")
def price(item: str = "apple"):
    """查價格。"""
    with open(os.path.join(context().pack_dir, "runs.log"), "a", encoding="utf-8") as f:
        f.write("x")
    mode = _mode("mode.txt")
    if mode == "ok":
        return f"{item} 30 元"
    if mode == "raise":
        raise RuntimeError("炸了")
    if mode == "hang":
        time.sleep(30)
        return "太晚了"
    if mode == "legacy":
        raise ToolError("upstream_unavailable", "舊的錯誤")
    if mode == "needs_config":
        fail("needs_config", "還沒設定城市", remedy={"kind": "needs_config", "summary": "到工具頁設定城市。"})
    fail(mode, "資料來源壞了 key=" + "%s", diag={"upstream": "DIAG-ONLY-MARK", "tool_version": "1.2.0"})


@tool("READ")
def ping():
    """自我檢查。"""
    with open(os.path.join(context().pack_dir, "pings.log"), "a", encoding="utf-8") as f:
        f.write("x")
    if _mode("ping.txt") == "ok":
        return "pong"
    fail("upstream_unavailable", "還是壞的")


if __name__ == "__main__":
    serve()
''' % FAKE_KEY

PY_PACK = '''from isdtelekit.core.registry import READ

from synox.packs import kit
from synox.sdk.author import fail


def install(app, pack):
    def work(api, chat_id, user, values):
        raise RuntimeError("python 工具炸了")

    def setup(api, chat_id, user, values):
        fail("needs_config", "還沒填帳號", scope="pack")

    kit.command(pack.group, "work", work, "做事", effect=READ)
    kit.command(pack.group, "setup", setup, "設定檢查", effect=READ)
'''


def _cli_pack(tmp_path, *, check=True, timeout=None):
    folder = tmp_path / "packs" / "demo"
    folder.mkdir(parents=True)
    (folder / "tool.py").write_text(CLI_TOOL, encoding="utf-8")
    sdk.write_single_file(str(folder / "synox_sdk.py"))
    sdk.init_from(str(folder / "tool.py"), "demo", "示範")
    raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    if check:
        raw["health"] = {"check": "ping"}
    if timeout:
        raw["cli"]["timeout"] = timeout
    (folder / "pack.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return folder


def _py_pack(tmp_path):
    folder = tmp_path / "packs" / "pyx"
    folder.mkdir(parents=True)
    (folder / "pack.json").write_text(json.dumps({
        "name": "pyx", "title": "🐍 假 python", "summary": "健康測試", "version": "0.1.0", "kind": "python",
        "python": {"module": "pack"}, "skill": "SKILL.md"}, ensure_ascii=False), encoding="utf-8")
    (folder / "pack.py").write_text(PY_PACK, encoding="utf-8")
    (folder / "SKILL.md").write_text("# 假 python\n", encoding="utf-8")
    return folder


class Clock:
    def __init__(self, now=2_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def _mode(folder, value, name="mode.txt"):
    (folder / name).write_text(value, encoding="utf-8")


def _runs(folder, name="runs.log"):
    path = folder / name
    return len(path.read_text(encoding="utf-8")) if path.exists() else 0


def _tool_results(adapter, call_index):
    messages, _tools = adapter.calls[call_index]
    return [m.content for m in messages if m.role == TOOL]


def _bot(make_bot, tmp_path, script, *, raw=None, check=True, timeout=None, python=False):
    folder = _cli_pack(tmp_path, check=check, timeout=timeout)
    if python:
        _py_pack(tmp_path)
    bot = make_bot(script, pack_dirs=(str(folder.parent),), raw=raw)
    assert all(i.status == "loaded" for i in bot.app.extras["synox_pack_report"].items)
    clock = Clock()
    reg = health.of(bot.app)
    if reg is not None:
        reg.clock = clock
    return bot, folder, clock


def _ai(bot):
    return bot.app.extras["synox_agent"].adapter


def _names(tools):
    return sorted(t.name for t in tools)


# ── AI 收到的一行、門檻、清單、提示、硬叫 ──────────────────────────────────

def test_ai_gets_one_fixed_line_and_broken_tool_leaves_the_list(make_bot, tmp_path):
    script = []
    for i in range(3):
        script += [{"tool": "demo__price", "args": {}}, f"答{i}"]
    script += ["好", {"tool": "demo__price", "args": {}}, "知道了"]
    bot, folder, _clock = _bot(make_bot, tmp_path, script)
    _mode(folder, "upstream_unavailable")
    adapter = _ai(bot)
    all_tools = None
    for i in range(3):
        bot.talk(OWNER_ID, "幫我查價格")
        if all_tools is None:
            all_tools = _names(adapter.calls[0][1])
    result = _tool_results(adapter, 1)[0]
    line = [ln for ln in result.splitlines() if ln.startswith("FAIL ")][0]
    assert line.startswith("FAIL upstream_unavailable retry=yes | 資料來源壞了 key=*** | 下一步：") and len(line) <= 300
    assert FAKE_KEY not in result and "DIAG-ONLY-MARK" not in result
    texts = "\n".join(bot.texts(OWNER_ID))
    assert FAKE_KEY not in texts
    entry = health.of(bot.app).hidden("demo.price")
    assert entry is not None and entry.state == BROKEN and entry.count == 3
    assert entry.diag.get("upstream") == "DIAG-ONLY-MARK"                     # diag 只在擁有者／log 那邊

    bot.talk(OWNER_ID, "還能查嗎")
    messages, tools = adapter.calls[-1]
    names = _names(tools)
    assert "demo__price" in all_tools and "demo__price" not in names and "demo__ping" in names
    assert sorted(set(all_tools) - {"demo__price"}) == names                  # 只拿掉壞掉的那一個
    prompt = messages[0].content
    assert messages[0].role == SYSTEM
    assert prompt.rstrip().splitlines()[-1].startswith("暫時不能用的功能：/demo_price（外部服務暫時不能用")
    assert "DIAG-ONLY-MARK" not in prompt and "資料來源壞了" not in prompt    # 提示裡只有 SYNOX 的字

    _mode(folder, "ok")
    before = _runs(folder)
    bot.talk(OWNER_ID, "硬叫一次")                                            # AI 硬叫被拿掉的工具：直接回原因、不執行
    forced = _tool_results(adapter, -1)[-1]
    assert "暫時不能用的功能：/demo_price" in forced and _runs(folder) == before


def test_prompt_lines_are_capped(make_bot, tmp_path):
    bot, _folder, _clock = _bot(make_bot, tmp_path, ["好"], raw={"health": {"prompt_lines": 1}}, python=True)
    reg = health.of(bot.app)
    for tool in ("demo.price", "demo.ping", "pyx.work"):
        reg.record_failure(tool, health.failures.from_text("x", "needs_config"), pack="demo")
        reg.entry(tool).state = NEEDS_ACTION
    bot.talk(OWNER_ID, "嗨")
    prompt = _ai(bot).calls[-1][0][0].content
    assert sum(1 for ln in prompt.splitlines() if ln.startswith("暫時不能用的功能：")) == 1


def test_self_reported_needs_config_hides_at_once(make_bot, tmp_path):
    bot, folder, _clock = _bot(make_bot, tmp_path, [{"tool": "demo__price", "args": {}}, "好", "再一次"])
    _mode(folder, "needs_config")
    bot.talk(OWNER_ID, "查價格")
    entry = health.of(bot.app).hidden("demo.price")
    assert entry is not None and entry.state == NEEDS_ACTION
    assert "FAIL needs_config retry=no | 還沒設定城市" in _tool_results(_ai(bot), 1)[0]
    bot.talk(OWNER_ID, "再查")
    assert "demo__price" not in _names(_ai(bot).calls[-1][1])
    assert health.of(bot.app).due() == []                                     # 要人處理：不自動檢查


def test_human_sees_reason_line_and_manual_run_still_works(make_bot, tmp_path):
    bot, folder, _clock = _bot(make_bot, tmp_path, None)
    _mode(folder, "needs_config")
    bot.talk(OWNER_ID, "/demo_price")
    assert "❌ price：還沒設定城市\n（還沒設定好；到工具頁設定城市。）" in bot.texts(OWNER_ID)
    assert health.of(bot.app).hidden("demo.price").state == NEEDS_ACTION
    bot.clear()
    _mode(folder, "ok")
    bot.talk(OWNER_ID, "/demo_price")                                          # 人自己打：照常執行、前面多一行警告
    texts = bot.texts(OWNER_ID)
    assert texts[0].startswith("⚠️ 這個工具目前要人處理") and "apple 30 元" in texts
    assert health.of(bot.app).hidden("demo.price") is None                    # 成功＝算一次重新檢查通過


def test_timeouts_and_legacy_envelopes(make_bot, tmp_path):
    script = [{"tool": "demo__price", "args": {}}, "好", {"tool": "demo__price", "args": {}}, "好"]
    bot, folder, _clock = _bot(make_bot, tmp_path, script, timeout=2)
    _mode(folder, "legacy")
    bot.talk(OWNER_ID, "查")
    assert _tool_results(_ai(bot), 1)[0].count("FAIL upstream_unavailable retry=yes | 舊的錯誤") == 1
    _mode(folder, "hang")
    bot.talk(OWNER_ID, "再查")
    assert "FAIL timeout retry=yes" in _tool_results(_ai(bot), 3)[0]
    entry = health.of(bot.app).entry("demo.price")
    assert entry.state == HEALTHY and entry.count == 2                         # 兩個不同的根因


def test_python_pack_exceptions_and_tool_failure(make_bot, tmp_path):
    script = [{"tool": "pyx__work", "args": {}}, "好", {"tool": "pyx__work", "args": {}}, "好",
              {"tool": "pyx__setup", "args": {}}, "好", "再一次"]
    bot, _folder, _clock = _bot(make_bot, tmp_path, script, python=True)
    bot.talk(OWNER_ID, "做事")
    assert _tool_results(_ai(bot), 1)[0].count("FAIL unclassified retry=no | RuntimeError: python 工具炸了") == 1
    bot.talk(OWNER_ID, "再做")
    assert health.of(bot.app).hidden("pyx.work").state == BROKEN             # 沒有合約：門檻 2
    bot.talk(OWNER_ID, "設定")
    assert "FAIL needs_config retry=no | 還沒填帳號" in _tool_results(_ai(bot), 5)[0]
    assert health.of(bot.app).hidden("pyx.setup").state == NEEDS_ACTION
    bot.talk(OWNER_ID, "還有什麼")
    names = _names(_ai(bot).calls[-1][1])
    assert "pyx__work" not in names and "pyx__setup" not in names and "demo__price" in names


# ── 冷卻、自我檢查（不叫 AI）、試用、隔離 ───────────────────────────────

def _break(bot, folder):
    _mode(folder, "upstream_unavailable")
    for _ in range(3):
        bot.talk(OWNER_ID, "/demo_price")
    entry = health.of(bot.app).hidden("demo.price")
    assert entry is not None and entry.state == BROKEN
    return entry


def test_recheck_uses_self_check_without_ai(make_bot, tmp_path):
    from synox import runtime
    bot, folder, clock = _bot(make_bot, tmp_path, None)
    rt = runtime.of(bot.app).use_fakes(spawn=lambda fn, name: fn())
    assert rt.loop.task(health.TASK_ID) is not None                           # 登記成 runtime 的任務
    entry = _break(bot, folder)
    calls = len(_ai(bot).calls)
    assert calls == 0                                                          # 人打的指令，沒有叫過 AI
    assert rt.loop.run_now(health.TASK_ID)                                     # 還沒到時間：什麼都不做
    assert _runs(folder, "pings.log") == 0 and entry.state == BROKEN
    _mode(folder, "bad", "ping.txt")
    clock.now = entry.next_check + 1
    assert rt.loop.run_now(health.TASK_ID)
    assert _runs(folder, "pings.log") == 1 and entry.state == BROKEN           # 自我檢查沒過：下一段冷卻
    assert entry.next_check == clock.now + 900
    _mode(folder, "ok", "ping.txt")
    clock.now = entry.next_check + 1
    assert rt.loop.run_now(health.TASK_ID)
    assert _runs(folder, "pings.log") == 2 and entry.state == HEALTHY          # 過了：放回
    assert len(_ai(bot).calls) == calls == 0                                   # 整個過程沒有叫 AI
    assert not [t for t in bot.texts(OWNER_ID) if "pong" in t]                 # 自我檢查的結果不送給任何人


def test_flapping_quarantines_and_only_owner_releases(make_bot, tmp_path):
    bot, folder, clock = _bot(make_bot, tmp_path, None)
    reg = health.of(bot.app)
    entry = _break(bot, folder)
    for _ in range(2):                                                         # 好壞反覆：第三次壞掉＝隔離
        clock.now = entry.next_check + 1
        health.tick(bot.app)                                                   # ping.txt 沒寫＝自我檢查過了
        assert entry.state == HEALTHY
        for _ in range(3):
            bot.talk(OWNER_ID, "/demo_price")
    assert entry.state == QUARANTINED and reg.due() == []
    clock.now += 10 * 86400
    assert health.tick(bot.app) == "沒有要檢查的" and entry.state == QUARANTINED
    _mode(folder, "ok")
    bot.talk(OWNER_ID, "/demo_price")                                          # 人手動成功也不解除
    assert entry.state == QUARANTINED
    assert reg.release("demo.price") and entry.state == HEALTHY


def test_self_check_that_did_not_really_run_does_not_pass():
    class Node:
        path = "demo.ping"

        @staticmethod
        def fn(api, chat_id, user, args):
            api.send_message(chat_id, "🔌 還沒連接")                         # 沒跑：只回一句話

    assert health.probe(None, Node, None) is False                             # cli／mcp：要真的成功才算過
    assert health.probe(None, Node, None, needs_success=False) is True         # python：沒丟例外就算


def test_tools_without_self_check_get_one_trial(make_bot, tmp_path):
    script = [{"tool": "demo__price", "args": {}}, "好"]
    bot, folder, clock = _bot(make_bot, tmp_path, script, check=False)
    entry = _break(bot, folder)
    clock.now = entry.next_check + 1
    assert "放回清單試用一次" in health.tick(bot.app)
    assert entry.trial and health.of(bot.app).hidden("demo.price") is None
    _mode(folder, "ok")
    bot.talk(OWNER_ID, "查價格")                                               # AI 試用一次，成功＝放回
    assert entry.state == HEALTHY and not entry.trial


MCP_TOOL = r'''"""SDK 寫的 MCP 伺服器（健康測試）。"""
import os

from synox_sdk import fail, serve, tool

HERE = os.path.dirname(os.path.abspath(__file__))


@tool("READ")
def price():
    """查價格。"""
    if os.path.exists(os.path.join(HERE, "ok.txt")):
        return "30 元"
    fail("upstream_unavailable", "上游掛了", diag={"upstream": "MCP-DIAG-MARK"})


@tool("READ")
def ping():
    """自我檢查。"""
    return "pong"


if __name__ == "__main__":
    serve()
'''


def test_mcp_tools_count_as_imported_and_recheck(make_bot, tmp_path):
    from synox.packs import mcp as pack_mcp
    folder = tmp_path / "packs" / "mcpx"
    folder.mkdir(parents=True)
    (folder / "tool.py").write_text(MCP_TOOL, encoding="utf-8")
    sdk.write_single_file(str(folder / "synox_sdk.py"))
    (folder / "SKILL.md").write_text("---\nname: mcpx\ndescription: 健康測試\n---\n", encoding="utf-8")
    (folder / "pack.json").write_text(json.dumps({
        "name": "mcpx", "title": "MCP 健康", "summary": "serve --mcp", "version": "0.1.0", "kind": "mcp",
        "capabilities": ["subprocess"], "skill": "SKILL.md", "health": {"check": "ping"},
        "mcp": {"transport": "stdio", "argv": ["{python}", "./tool.py", "--mcp"], "timeout": 20,
                "tools_allow": ["price", "ping"], "effects": {"price": "READ", "ping": "READ"}}}), encoding="utf-8")
    script = [{"tool": "mcpx__price", "args": {}}, "好", {"tool": "mcpx__price", "args": {}}, "好"]
    bot = make_bot(script, pack_dirs=(str(tmp_path / "packs"),))
    try:
        assert bot.app.extras["synox_pack_report"].items[0].status == "loaded"
        reg = health.of(bot.app)
        reg.clock = clock = Clock()
        bot.talk(OWNER_ID, "查")
        result = _tool_results(_ai(bot), 1)[0]
        assert "FAIL upstream_unavailable retry=yes | 上游掛了" in result and "MCP-DIAG-MARK" not in result
        bot.talk(OWNER_ID, "再查")
        entry = reg.hidden("mcpx.price")
        assert entry is not None and entry.state == BROKEN                       # 匯入的工具：門檻 2
        clock.now = entry.next_check + 1
        assert "自我檢查過了" in health.tick(bot.app) and entry.state == HEALTHY
        assert len(_ai(bot).calls) == 4
    finally:
        pack_mcp.pool_of(bot.app).close_all()


# ── fail open ─────────────────────────────────────────────────────────

def _list_after_failures(make_bot, tmp_path, raw=None, sabotage=None):
    script = []
    for _ in range(3):
        script += [{"tool": "demo__price", "args": {}}, "好"]
    script += ["最後"]
    folder = _cli_pack(tmp_path)
    if sabotage:
        sabotage(tmp_path)
    bot = make_bot(script, pack_dirs=(str(folder.parent),), raw=raw)
    _mode(folder, "upstream_unavailable")
    for _ in range(4):
        bot.talk(OWNER_ID, "查")
    adapter = _ai(bot)
    return _names(adapter.calls[0][1]), _names(adapter.calls[-1][1]), adapter.calls[-1][0][0].content


def test_fail_open_when_disabled(make_bot, tmp_path):
    first, last, prompt = _list_after_failures(make_bot, tmp_path, raw={"health": {"enabled": False}})
    assert first == last and "demo__price" in last and "暫時不能用" not in prompt


def test_fail_open_when_the_store_is_broken(make_bot, tmp_path):
    def garbage(root):
        folder = root / "data" / "health"
        folder.mkdir(parents=True)
        (folder / "tools.json.enc").write_bytes(b"garbage\n")

    first, last, _prompt = _list_after_failures(make_bot, tmp_path, sabotage=garbage)
    assert "demo__price" in first                                              # 一開始：存檔讀不開也照常給
    assert (tmp_path / "data" / "health" / "tools.json.enc").read_bytes() == b"garbage\n"   # 沒有蓋掉


def test_fail_open_when_the_registry_raises(make_bot, tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("health manager exploded")

    for name in ("hidden", "any_hidden", "record_failure", "record_success"):
        monkeypatch.setattr(health.HealthRegistry, name, boom)
    first, last, prompt = _list_after_failures(make_bot, tmp_path)
    assert first == last and "demo__price" in last and "暫時不能用" not in prompt


def test_fail_open_without_health_installed(make_bot, tmp_path):
    bot, _folder, _clock = _bot(make_bot, tmp_path, ["好"])
    baseline = _names(bot.app.extras["synox_agent"].tools_for(bot.app.users.get_or_create(OWNER_ID), OWNER_ID))
    del bot.app.extras[health.HEALTH_KEY]
    loop = bot.app.extras["synox_agent"]
    assert _names(loop.tools_for(bot.app.users.get_or_create(OWNER_ID), OWNER_ID)) == baseline
    assert loop.health_note(bot.app.users.get_or_create(OWNER_ID), OWNER_ID) == ""
