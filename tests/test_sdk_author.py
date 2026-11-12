# -*- coding: utf-8 -*-
"""SDK P1（作者端）：@tool 的型別註記→fields、serve() 的兩種殼（子指令＋--json、MCP stdio）、secret()／context()
（loader 注入的 SYNOX_* 環境變數）、ToolError／Confirm 信封、synox-sdk init --from／run、單檔版與正本一致、
pack.json 的 ai／confirm。子程序都是本機的 Python，不連網、不開埠。"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

import pytest

from conftest import OWNER_ID

from synox import sdk
from synox.agent import validate as gate4
from synox.packs import scan
from synox.packs.manifest import ManifestError, read
from synox.sdk import author
from synox.sdk.author import Confirm, Ok, SpecError, ToolError, tool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "demo_live_0123456789abcdef"

TOOL = r'''"""示範工具：記帳、選顏色。"""
from pathlib import Path
from typing import Literal, Optional

from synox_sdk import Confirm, Ok, ToolError, context, secret, serve, tool


@tool("WRITE", default=True)
def add(amount: int, memo: str = "", tax: Optional[float] = None, paid: bool = False):
    """記一筆。

    Args:
        amount: 金額
        memo: 備註
    """
    print("這一行是 log，不是結果")
    return Ok(f"記了 {amount}", {"amount": amount, "memo": memo, "tax": tax, "paid": paid})


@tool("READ")
def color(c: Literal["Red", "Blue"]):
    """選顏色。"""
    return c


@tool("DANGER", ai=False)
def wipe():
    """全部刪掉。"""
    raise Confirm("要刪 3 筆", "tok1")


@tool("READ")
def fail(code: str):
    """一定失敗。"""
    raise ToolError(code, "找不到")


@tool("READ")
def boom():
    """程式自己出錯。"""
    raise RuntimeError("壞了")


@tool("READ")
def whoami():
    """這一次是誰。"""
    ctx = context()
    return {"user_data_dir": ctx.user_data_dir, "tg_id": ctx.tg_id, "mode": ctx.mode, "pack_dir": ctx.pack_dir,
            "pack_name": ctx.pack_name, "key_len": len(secret("api_key") or "")}


@tool("READ")
def peek(file: Path):
    """看檔名。"""
    return {"name": file.name, "is_path": isinstance(file, Path)}


@tool("WRITE", confirm=True)
def send(text: str):
    """送出去（AI 要先問人）。"""
    return f"送了 {text}"


if __name__ == "__main__":
    serve()
'''


def _tool_dir(tmp_path, name="demo", source=TOOL, single=True):
    folder = tmp_path / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tool.py").write_text(source, encoding="utf-8")
    if single:
        sdk.write_single_file(str(folder / "synox_sdk.py"))
    return folder


def _run(folder, *args, stdin=None, env=None):
    full_env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}
    return subprocess.run([sys.executable, "-X", "utf8", str(folder / "tool.py"), *args], input=stdin,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=full_env, timeout=60)


def _last(proc) -> dict:
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── 型別註記 → fields ──────────────────────────────────────────────────

def test_annotations_become_fields():
    @tool("write", "記一筆")
    def add(amount: int, price: float, ok: bool, memo: str, file: Path, size: Literal["S", "M"],
            note: Optional[str], who: Annotated[str, "給誰"] = "", n: int = 3):
        pass

    spec = author.tool_spec(add)
    assert spec["effect"] == "WRITE" and spec["summary"] == "記一筆"
    got = {f["name"]: (f["kind"], f["required"]) for f in spec["fields"]}
    assert got == {"amount": ("int", True), "price": ("number", True), "ok": ("bool", True), "memo": ("text", True),
                   "file": ("path", True), "size": ("choice", True), "note": ("text", False),
                   "who": ("text", False), "n": ("int", False)}
    cmd = author.commands_for([add])[0]
    assert cmd["argv"][0] == "add" and "--size={size}" in cmd["argv"]
    size = next(f for f in cmd["fields"] if f["name"] == "size")
    assert size == {"name": "size", "ask": "size", "kind": "choice", "choices": ["S", "M"], "required": True}
    assert next(f for f in cmd["fields"] if f["name"] == "who")["ask"] == "給誰"
    assert "kind" not in next(f for f in cmd["fields"] if f["name"] == "memo")      # text 不寫 kind


def test_docstring_gives_summary_and_asks():
    @tool("READ")
    def show(day: str, limit: int = 5):
        """看某一天。

        Args:
            day: 哪一天（YYYY-MM-DD）
            limit (int): 最多幾筆
        """

    spec = author.tool_spec(show)
    assert spec["summary"] == "看某一天。"
    assert [f["ask"] for f in spec["fields"]] == ["哪一天（YYYY-MM-DD）", "最多幾筆"]


def test_spec_errors():
    @tool
    def no_effect(x: str):
        """沒寫 effect。"""

    @tool("MAYBE")
    def bad_effect():
        """effect 寫錯。"""

    @tool("READ")
    def bad_type(x: dict):
        """不支援的型別。"""

    @tool("READ")
    def no_doc():
        pass

    @tool("READ")
    def reserved(tg_id: str):
        """保留名。"""

    @tool("READ")
    def star(*args):
        """*args。"""

    for fn, word in ((no_effect, "一定要寫 effect"), (bad_effect, "只能是 READ"), (bad_type, "不支援的型別"),
                     (no_doc, "要有說明"), (reserved, "保留"), (star, "*args")):
        with pytest.raises(SpecError) as e:
            author.commands_for([fn])
        assert word in str(e.value), fn


# ── 殼 1：子指令＋--json（同一個程序）──────────────────────────────────

@tool("WRITE", default=True, name="add")
def _add(amount: int, memo: str = "", paid: bool = False, size: Literal["S", "M"] = "S"):
    """記一筆。"""
    return Ok(f"記了 {amount}", {"amount": amount, "memo": memo, "paid": paid, "size": size})


def _cli(*argv):
    out = io.StringIO()
    code = author.run_cli(list(argv), out, tools=[_add])
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


def test_cli_shell_parses_like_loader_argv():
    code, env = _cli("add", "--amount=1,200", "--memo=午餐 跟同事", "--paid=true", "--size=m", "--json")
    assert code == 0 and env == {"ok": True, "message": "記了 1200",
                                 "data": {"amount": 1200, "memo": "午餐 跟同事", "paid": True, "size": "M"}}
    code, env = _cli("add", "7", "--paid", "--json")                       # 位置參數、bool 旗標
    assert code == 0 and env["data"]["amount"] == 7 and env["data"]["paid"] is True
    code, env = _cli("add", "--amount=abc", "--json")
    assert code == 1 and env["code"] == "bad_value" and "整數" in env["error"]
    code, env = _cli("add", "--json")
    assert code == 1 and env["code"] == "usage" and "amount" in env["error"]
    code, env = _cli("add", "--amount=1", "--nope=2", "--json")
    assert code == 1 and "不認得" in env["error"]
    code, env = _cli("nothing", "--json")
    assert code == 1 and env["code"] == "usage"


def test_cli_shell_envelopes_in_subprocess(tmp_path):
    folder = _tool_dir(tmp_path)
    proc = _run(folder, "add", "--amount=120", "--memo=午餐", "--json")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines()[0] == "這一行是 log，不是結果"          # 前面的 log 沒關係：SYNOX 取最後一行
    assert _last(proc) == {"ok": True, "message": "記了 120",
                           "data": {"amount": 120, "memo": "午餐", "tax": None, "paid": False}}
    proc = _run(folder, "fail", "--code=not_found", "--json")
    assert proc.returncode == 1 and _last(proc) == {"ok": False, "error": "找不到", "code": "not_found"}
    proc = _run(folder, "wipe", "--json")
    env = _last(proc)
    assert proc.returncode == 0 and env["needs_confirm"] and env["summary"] == "要刪 3 筆" and env["confirm_token"] == "tok1"
    proc = _run(folder, "boom", "--json")
    assert proc.returncode == 1 and _last(proc)["code"] == "internal" and "RuntimeError" in proc.stderr
    proc = _run(folder, "color", "blue")                                    # 沒有 --json：給人看的字
    assert proc.returncode == 0 and proc.stdout.strip() == "Blue"
    from isdtelekit.jobs.cli import CliReply, last_json
    assert CliReply(0, last_json(_run(folder, "peek", "--file=a/b.txt", "--json").stdout)).data["data"] == \
        {"name": "b.txt", "is_path": True}


# ── 殼 2：MCP stdio ────────────────────────────────────────────────────

def test_mcp_stdio_server(tmp_path):
    folder = _tool_dir(tmp_path)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "add", "arguments": {"amount": 5, "paid": True}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "add", "arguments": {"amount": "x"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "wipe", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 6, "method": "ping"},
            {"jsonrpc": "2.0", "id": 7, "method": "resources/list"}]
    stdin = "\n".join(json.dumps(m, ensure_ascii=False) for m in msgs) + "\nnot json\n"
    proc = _run(folder, "--mcp", stdin=stdin)
    assert proc.returncode == 0, proc.stderr
    replies = [json.loads(line) for line in proc.stdout.splitlines()]      # 每一行都是 JSON-RPC（print 的 log 去了 stderr）
    assert "這一行是 log" in proc.stderr
    by_id = {r["id"]: r for r in replies}
    assert len(replies) == 8                                               # 通知不回；壞掉的那行回 parse error
    init = by_id[1]["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    tools = {t["name"]: t for t in by_id[2]["result"]["tools"]}
    assert "wipe" not in tools and {"add", "color", "send"} <= set(tools)   # ai=False 的不列
    schema = tools["add"]["inputSchema"]
    assert schema["properties"]["amount"] == {"type": "integer", "description": "金額"}
    assert schema["properties"]["paid"]["type"] == "boolean" and schema["properties"]["tax"]["type"] == "number"
    assert schema["required"] == ["amount"] and schema["additionalProperties"] is False
    assert tools["color"]["inputSchema"]["properties"]["c"] == {"enum": ["Red", "Blue"], "type": "string"}
    assert all("effect" not in json.dumps(t) and "annotations" not in t for t in tools.values())  # effect 不由工具自述
    call = by_id[3]["result"]
    assert call["isError"] is False and "記了 5" in call["content"][0]["text"]
    assert by_id[4]["result"]["isError"] is True and "整數" in by_id[4]["result"]["content"][0]["text"]
    assert by_id[5]["error"]["code"] == -32602                              # ai=False 的叫不到
    assert by_id[6]["result"] == {}
    assert by_id[7]["error"]["code"] == -32601
    assert by_id[None]["error"]["code"] == -32700


# ── secret()、context() ───────────────────────────────────────────────

def test_secret_and_context_read_synox_env(monkeypatch):
    for k in ("SYNOX_SECRET_ENV", "DEMO_API_KEY", "API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert author.secret("api_key") is None
    monkeypatch.setenv("DEMO_API_KEY", TOKEN)
    monkeypatch.setenv("SYNOX_SECRET_ENV", "api_key=DEMO_API_KEY,region=DEMO_REGION")
    assert author.secret("api_key") == TOKEN and author.secret("DEMO_API_KEY") == TOKEN
    assert author.secret("region") is None
    monkeypatch.setenv("SYNOX_USER_DATA_DIR", "/d/u/1")
    monkeypatch.setenv("SYNOX_TG_ID", "1")
    monkeypatch.setenv("SYNOX_MODE", "server")
    ctx = author.context()
    assert (ctx.user_data_dir, ctx.tg_id, ctx.mode, ctx.inside_synox) == ("/d/u/1", "1", "server", True)


def _init(tmp_path, **auth):
    folder = _tool_dir(tmp_path / "packs")
    result = sdk.init_from(str(folder / "tool.py"), "demo", "示範")
    if auth:
        raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
        raw["auth"] = auth
        (folder / "pack.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return folder, result


AUTH = {"type": "token", "fields": [{"name": "api_key", "label": "Demo key", "secret": True, "env": "DEMO_API_KEY"}]}


def test_loader_injects_context_env(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    folder, _ = _init(tmp_path, **AUTH)
    bot = make_bot(pack_dirs=(str(folder.parent),))
    c = Client(ui_of(bot))
    c.login(owner)
    c.post("/api/pack-secrets/demo", {"values": {"api_key": TOKEN}})
    bot.say(owner, "/demo_whoami")
    assert bot.app.tasks.wait(20)
    out = "\n".join(bot.texts(owner))
    assert f"tg_id：{owner}" in out and "mode：personal" in out and "pack_name：demo" in out
    assert f"key_len：{len(TOKEN)}" in out and TOKEN not in out


def test_context_env_server_mode(tmp_path):
    from types import SimpleNamespace
    from synox.packs import loader
    folder, _ = _init(tmp_path, **AUTH)
    m = read(str(folder), strict=True)
    config = SimpleNamespace(data_dir=str(tmp_path / "data"), mode="server", owner_id=1)
    ph = loader.placeholders(m, config, SimpleNamespace(tg_id=42))
    env = loader.context_env(m, config, ph, [{"name": "api_key", "env": "DEMO_API_KEY"}])
    assert env["SYNOX_USER_DATA_DIR"] == os.path.join(str(tmp_path / "data"), "users", "42")
    assert env["SYNOX_TG_ID"] == "42" and env["SYNOX_MODE"] == "server" and env["SYNOX_SECRET_ENV"] == "api_key=DEMO_API_KEY"
    from isdtelekit.jobs.cli import clean_env
    assert set(env) <= set(clean_env(env))                                 # 名字不像密鑰，不會被 JsonCli 拿掉


# ── init --from ─────────────────────────────────────────────────────────

def test_init_from_passes_gate1_and_gate2(tmp_path):
    folder, result = _init(tmp_path)
    assert {"pack.json", "SKILL.md"} <= set(result.written)
    m = read(str(folder), strict=True)                                     # 第 1 關（嚴格）
    report = scan.scan(m)                                                  # 第 2 關
    assert report.problems(m) == [] and report.required_capabilities == []
    assert result.check is not None and result.check.ok, result.check.problems
    raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert raw["kind"] == "cli" and raw["capabilities"] == [] and raw["requires"]["synox"] == author.SYNOX_REQUIRES
    assert raw["cli"]["argv"] == ["{python}", "./tool.py"] and raw["summary"] == "示範工具：記帳、選顏色。"
    by = {c["name"]: c for c in raw["cli"]["commands"]}
    assert by["add"]["default"] is True and by["add"]["effect"] == "WRITE"
    assert by["wipe"]["ai"] is False and by["send"]["confirm"] is True
    assert any("capabilities" in n for n in result.notes)
    skill = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: demo\n") and "`demo__add`" in skill and "demo__wipe" not in skill
    path = sdk.zip_pack(str(folder), str(tmp_path / "dist"))
    assert os.path.basename(path) == "demo-0.1.0.synoxpack"


def test_init_from_hints_capabilities_and_keeps_author_edits(tmp_path):
    source = TOOL.replace('"""示範工具：記帳、選顏色。"""', '"""示範。"""\nimport socket')
    folder = _tool_dir(tmp_path, source=source)
    result = sdk.init_from(str(folder / "tool.py"), "demo")
    assert any("network" in n for n in result.notes)
    raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    raw["title"] = "改過的標題"
    raw["cli"]["commands"][0]["stdin"] = "{memo}"
    (folder / "pack.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    (folder / "SKILL.md").write_text("作者寫的", encoding="utf-8")
    again = sdk.init_from(str(folder / "tool.py"), "demo")
    raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert raw["title"] == "改過的標題" and raw["cli"]["commands"][0]["stdin"] == "{memo}"
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == "作者寫的" and "SKILL.md" not in again.written


def test_init_from_refuses_missing_effect(tmp_path):
    folder = _tool_dir(tmp_path, source=TOOL.replace('@tool("READ")\ndef boom', '@tool\ndef boom'))
    with pytest.raises(ValueError) as e:
        sdk.init_from(str(folder / "tool.py"), "demo")
    assert "boom" in str(e.value) and "effect" in str(e.value)
    assert not (folder / "pack.json").exists() and not (folder / "SKILL.md").exists()


def test_init_from_copies_single_file_and_cli(tmp_path, capsys):
    folder = _tool_dir(tmp_path, single=False)
    assert sdk.main(["init", "--from", str(folder / "tool.py"), "--name", "demo", "--title", "示範"]) == 0
    assert "synox_sdk.py" in capsys.readouterr().out
    assert (folder / "synox_sdk.py").read_text(encoding="utf-8") == sdk.single_file_source()
    assert sdk.main(["check", str(folder)]) == 0
    assert _last(_run(folder, "color", "--c=red", "--json"))["message"] == "Red"


# ── run：本機試跑 ───────────────────────────────────────────────────────

def _run_cmd(folder, command, *args, **kw):
    out = io.StringIO()
    code = sdk.run_command(str(folder), command, list(args), data_dir=str(folder.parent / "data"), out=out, **kw)
    return code, out.getvalue()


def test_run_command_like_synox(tmp_path):
    folder, _ = _init(tmp_path)
    code, text = _run_cmd(folder, "add", "120", "memo=午餐 跟同事")
    assert code == 0, text
    assert "--amount=120" in text and "SYNOX 會回：記了 120" in text
    code, text = _run_cmd(folder, "add", "abc")
    assert code == 2 and "整數" in text
    code, text = _run_cmd(folder, "add", "5", "memo=-rf")
    assert code == 2
    code, text = _run_cmd(folder, "peek", "../../outside.txt")
    assert code == 2 and "第 4 關" in text and "不在你的資料夾裡" in text
    code, text = _run_cmd(folder, "peek", "notes.txt")
    assert code == 0 and "is_path：是" in text
    code, text = _run_cmd(folder, "fail", "nope")
    assert code == 1 and "❌ fail：找不到" in text
    code, text = _run_cmd(folder, "whoami")
    assert code == 0 and "mode：personal" in text and "pack_name：demo" in text
    with pytest.raises(ValueError):
        _run_cmd(folder, "nothing")


def test_run_command_secret_rules(tmp_path, monkeypatch):
    folder, _ = _init(tmp_path, **AUTH)
    monkeypatch.delenv("DEMO_API_KEY", raising=False)
    code, text = _run_cmd(folder, "whoami")
    assert code == 2 and "DEMO_API_KEY" in text
    monkeypatch.setenv("DEMO_API_KEY", TOKEN)
    code, text = _run_cmd(folder, "whoami")
    assert code == 0 and f"key_len：{len(TOKEN)}" in text and TOKEN not in text
    code, text = _run_cmd(folder, "fail", TOKEN)                            # 第 4 關：把 secret 當參數
    assert code == 2 and "密鑰" in text
    assert sdk.main(["run", "whoami", "--pack", str(folder), "--data", str(tmp_path / "d")]) == 0


# ── pack.json 的 ai／confirm ───────────────────────────────────────────

def test_manifest_ai_confirm_must_be_bool(tmp_path):
    folder, _ = _init(tmp_path)
    raw = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    raw["cli"]["commands"][0]["ai"] = "no"
    (folder / "pack.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ManifestError) as e:
        read(str(folder), strict=True)
    assert "ai 要是 true 或 false" in str(e.value)


def test_loader_honors_ai_false_and_confirm(make_bot, owner, tmp_path):
    folder, _ = _init(tmp_path)
    bot = make_bot([{"tool": "demo__send", "args": {"text": "hi"}}, "好"], pack_dirs=(str(folder.parent),))
    assert bot.app.registry.node("demo.wipe").ai is False and bot.app.registry.node("demo.add").ai is True
    assert gate4.wants_confirm(bot.app, bot.app.registry.node("demo.send"))
    assert not gate4.wants_confirm(bot.app, bot.app.registry.node("demo.add"))
    bot.talk(owner, "幫我送 hi")
    texts = bot.texts(owner)
    assert any("AI 想執行" in t and "/demo_send" in t for t in texts)      # 先送確認卡
    assert not any("送了 hi" in t for t in texts)                           # 沒有直接執行


# ── 單檔版與正本一致、範例 ───────────────────────────────────────────────

def test_single_file_matches_source():
    text = sdk.single_file_source()
    for rel in ("sdk/synox_sdk.py", "examples/hello/synox_sdk.py"):
        with open(os.path.join(ROOT, *rel.split("/")), "r", encoding="utf-8", newline="") as f:
            assert f.read() == text, f"{rel} 過期了：跑 scripts/build_synox_sdk.py"
    findings = scan.scan_source("synox_sdk.py", text)
    assert not [f for f in findings if f.blocking or f.capability], findings  # 放進 pack 不用宣告任何能力
    # 子程序印中文：一律 UTF-8（-X utf8＋PYTHONIOENCODING），不然 Windows 的 cp950 輸出會讓讀取執行緒解碼失敗
    proc = subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "scripts", "build_synox_sdk.py"), "--check"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_single_file_has_no_dependencies():
    import ast
    tree = ast.parse(sdk.single_file_source())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods


def test_example_pack_is_current_and_installable(tmp_path):
    folder = os.path.join(ROOT, "examples", "hello")
    _module, tools = sdk.load_tools(os.path.join(folder, "tool.py"))
    with open(os.path.join(folder, "pack.json"), "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["cli"]["commands"] == author.commands_for(tools)            # pack.json 跟函式對得上
    check = sdk.Pack.load(folder)
    assert check.ok, check.problems
    out = io.StringIO()
    assert sdk.run_command(folder, "tip", ["1000", "percent=15"], data_dir=str(tmp_path), out=out) == 0
    assert "共 1150 元" in out.getvalue()
