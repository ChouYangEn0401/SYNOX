"""安全管線五關（架構 v1 §4）：宣告、靜態掃描、packs.lock、呼叫驗證、分隔符。不執行任何 pack 的惡意程式。"""

import io
import json
import os
import shutil
import sys
import zipfile

import pytest

from isdtelekit.users.models import User
from isdtelekit.users.roles import BasicRoles

from synox.agent import delimit, validate
from synox.llm.base import SYSTEM, TOOL
from synox.packs import admin, kit, loader, lock, scan
from synox.packs.manifest import ManifestError, read, validate as validate_manifest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
EVIL = os.path.join(FIXTURES, "evil_pack")


def _zip_dir(folder) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for base, _dirs, files in os.walk(folder):
            for name in files:
                if "__pycache__" in base:
                    continue
                path = os.path.join(base, name)
                z.write(path, os.path.relpath(path, folder))
    return buf.getvalue()


def _write_pack(folder, raw, files=None):
    os.makedirs(folder, exist_ok=True)
    base = {"name": "demo", "title": "Demo", "summary": "s", "version": "0.1.0", "kind": "python",
            "skill": "SKILL.md"}
    base.update(raw)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(base, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {base['name']}\ndescription: d\n---\n正文\n")
    for rel, text in (files or {}).items():
        with open(os.path.join(folder, rel), "w", encoding="utf-8") as f:
            f.write(text)
    return folder


HELLO_PY = ("def install(app, pack):\n"
            "    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, 'hi there'), '打招呼', default=True)\n")


# ── 第 1 關：宣告 ─────────────────────────────────────────────────────

def test_v2_manifest_fields(tmp_path):
    folder = _write_pack(str(tmp_path / "p"), {"capabilities": ["network"], "publisher": "someone",
                                                "auth": {"type": "token"}}, {"pack.py": HELLO_PY})
    m = read(folder)
    assert m.v2 and m.capabilities == ["network"] and m.publisher == "someone" and m.auth == "token"
    assert m.allows("network") and not m.allows("exec")


@pytest.mark.parametrize("over,needle", [
    ({"capabilities": ["root"]}, "capabilities"),
    ({"auth": {"type": "magic"}}, "auth.type"),
    ({"kind": "mcp", "mcp": {"tools_allow": ["search", "delete"], "effects": {"search": "READ"}}}, "delete"),
    ({"kind": "mcp", "mcp": {"tools_allow": []}}, "tools_allow"),
    ({"integrity": {"sha256": {"../x": "0" * 64}}}, "integrity"),
])
def test_v2_manifest_errors(tmp_path, over, needle):
    folder = _write_pack(str(tmp_path / "p"), {}, {"pack.py": HELLO_PY})
    raw = json.load(open(os.path.join(folder, "pack.json"), encoding="utf-8"))
    raw.update(over)
    with pytest.raises(ManifestError) as e:
        validate_manifest(raw, folder)
    assert needle in str(e.value)


def test_cli_effect_required_when_strict(tmp_path):
    raw = {"name": "c", "title": "C", "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "cli": {"argv": ["tool"], "commands": [{"name": "go", "argv": ["go"]}]}}
    folder = _write_pack(str(tmp_path / "c"), raw)
    assert read(folder).commands[0]["effect"] == "READ"          # 載入時：舊寫法照舊能用
    with pytest.raises(ManifestError) as e:
        read(folder, strict=True)                                # 安裝時：一定要寫
    assert "effect" in str(e.value)


# ── 第 2 關：靜態掃描 ─────────────────────────────────────────────────

def test_evil_pack_scan_findings():
    m = read(EVIL)
    report = scan.scan(m)
    print(report.format(m))
    assert report.required_capabilities == ["exec", "filesystem:any", "network"]
    kinds = {(f.file, f.kind) for f in report.findings}
    assert ("pack.py", "network") in kinds and ("pack.py", "exec") in kinds and ("pack.py", "filesystem:any") in kinds
    problems = report.problems(m)
    assert any(p.startswith("pack.py:3 ") and "network" in p for p in problems)          # import urllib.request
    assert any("pack.py:10 " in p and "filesystem:any" in p for p in problems)            # open("../../config.json")
    assert any("pack.py:12 " in p and "exec" in p for p in problems)                      # exec(...)


def test_evil_pack_refused_on_upload(tmp_path):
    with pytest.raises(admin.GateRefused) as e:
        admin.stage(_zip_dir(EVIL), str(tmp_path / "data"))
    assert "拒裝" in str(e.value) and "pack.py:3" in str(e.value)
    assert set(e.value.summary["scan"]["undeclared"]) == {"exec", "filesystem:any", "network"}
    staging = tmp_path / "data" / "web_uploads"
    assert not staging.exists() or not any(staging.iterdir())                            # 暫存清掉了


def test_declared_capabilities_pass(tmp_path):
    folder = str(tmp_path / "evil2")
    shutil.copytree(EVIL, folder)
    raw = json.load(open(os.path.join(folder, "pack.json"), encoding="utf-8"))
    raw["capabilities"] = ["network", "exec", "filesystem:any"]
    json.dump(raw, open(os.path.join(folder, "pack.json"), "w", encoding="utf-8"))
    m = read(folder)
    assert scan.scan(m).problems(m) == []


def test_scan_catches_aliases_and_subprocess():
    src = ("import subprocess as sp\nfrom os import system\nimport os\n"
           "sp.run(['x'])\nsystem('dir')\nos.environ.get('KEY')\nopen(name)\n"
           "getattr(os, 'popen')('x')\n__import__('socket')\n")
    found = {(f.line, f.kind) for f in scan.scan_source("x.py", src)}
    assert (1, "subprocess") in found and (2, "subprocess") in found and (4, "subprocess") in found
    assert (6, "env") in found and (7, "filesystem:own") in found and (8, "exec") in found and (9, "exec") in found


def test_cli_argv_template_rules(tmp_path):
    raw = {"name": "c", "title": "C", "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "cli": {"argv": ["{python}", "./tool.py"], "commands": [
               {"name": "ok", "effect": "READ", "argv": ["make", "{room}", "--size={size}"],
                "fields": [{"name": "room"}, {"name": "size"}]},
               {"name": "split", "effect": "READ", "argv": ["make", "--size", "{size}"], "fields": [{"name": "size"}]},
               {"name": "glued", "effect": "READ", "argv": ["--{flag}"], "fields": [{"name": "flag"}]},
               {"name": "ghost", "effect": "READ", "argv": ["{nope}"], "fields": []}]}}
    folder = _write_pack(str(tmp_path / "c"), raw, {"tool.py": "print('{}')\n"})
    m = read(folder, strict=True)
    problems = scan.scan(m).problems(m)
    assert not any("command ok" in p for p in problems)
    assert any("command split" in p and "--size={size}" in p for p in problems)
    assert any("command glued" in p for p in problems) and any("nope" in p for p in problems)


def test_connector_with_code_rejected(tmp_path):
    folder = _write_pack(str(tmp_path / "conn"), {"name": "conn", "kind": "connector", "auth": "token"},
                         {"helper.py": "x = 1\n"})
    with pytest.raises(admin.GateRefused) as e:
        admin.stage(_zip_dir(folder), str(tmp_path / "data"))
    assert "helper.py" in str(e.value)


def test_integrity_mismatch_refused(tmp_path):
    folder = _write_pack(str(tmp_path / "p"), {"integrity": {"sha256": {"pack.py": "0" * 64}}}, {"pack.py": HELLO_PY})
    with pytest.raises(admin.GateRefused) as e:
        admin.stage(_zip_dir(folder), str(tmp_path / "data"))
    assert "integrity" in str(e.value)


# ── 第 3 關：packs.lock ───────────────────────────────────────────────

def test_install_writes_lock_and_tamper_blocks_load(make_bot, owner, tmp_path):
    src = _write_pack(str(tmp_path / "src" / "hello"), {"name": "hello", "group": "hello"}, {"pack.py": HELLO_PY})
    user_packs = tmp_path / "userpacks"
    bot = make_bot(pack_dirs=(str(user_packs),))
    data_dir = bot.app.config.data_dir
    token, summary = admin.stage(_zip_dir(src), data_dir)
    assert summary["scan"]["ok"]
    assert admin.install_staged(token, data_dir, str(user_packs), approved_by=owner, via="web") == "hello"
    entry = lock.entry(data_dir, "hello")
    assert entry["approved_by"] == owner and entry["via"] == "web" and "pack.py" in entry["files"]
    report = admin.reload(bot.app, bot.app.config, None, (str(user_packs),))
    assert [(i.status, i.lock) for i in report.items] == [("loaded", "locked")]
    bot.say(owner, "/hello")
    assert bot.last(owner) == "hi there"
    # 竄改：載入時不符 → 不載、通知擁有者一次
    with open(user_packs / "hello" / "pack.py", "a", encoding="utf-8") as f:
        f.write("import socket\n")
    bot.clear()
    report = admin.reload(bot.app, bot.app.config, None, (str(user_packs),))
    item = report.items[0]
    assert item.status == "tampered" and "改了 pack.py" in item.detail and not report.ok
    assert bot.app.registry.node("hello") is None
    notices = [t for t in bot.texts(owner) if "沒有載入" in t]
    assert len(notices) == 1 and "pack.py" in notices[0]
    admin.reload(bot.app, bot.app.config, None, (str(user_packs),))
    assert len([t for t in bot.texts(owner) if "沒有載入" in t]) == 1                 # 同一種竄改只通知一次
    assert lock.verify(data_dir, "hello", str(user_packs / "hello"))[0] == lock.TAMPERED


def test_staged_files_changed_after_review_refused(tmp_path):
    src = _write_pack(str(tmp_path / "hello"), {"name": "hello"}, {"pack.py": HELLO_PY})
    data = str(tmp_path / "data")
    token, _summary = admin.stage(_zip_dir(src), data)
    with open(os.path.join(data, "web_uploads", token, "pack", "SKILL.md"), "a", encoding="utf-8") as f:
        f.write("偷偷加一句\n")
    with pytest.raises(admin.PackAdminError) as e:
        admin.install_staged(token, data, str(tmp_path / "packs"))
    assert "被改過" in str(e.value)


def test_install_cli_command(tmp_path, monkeypatch, capsys):
    from synox import __main__ as cli
    src = _write_pack(str(tmp_path / "hello"), {"name": "hello"}, {"pack.py": HELLO_PY})
    path = tmp_path / "hello-0.1.0.synoxpack"
    path.write_bytes(_zip_dir(src))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 42, "data_dir": str(tmp_path / "data"), "web": {"port": 18830}}),
                   encoding="utf-8")
    opened = []
    args = cli.argparse.Namespace(config=str(cfg), file=str(path), yes=False, packs_dir=str(tmp_path / "packs"))
    assert cli.cmd_install(args, is_up=lambda port: port == 18830, open_url=opened.append) == 0
    assert opened and "?pack=" in opened[0] and opened[0].endswith("#packs")
    assert not (tmp_path / "packs" / "hello").exists()                                 # 沒按確認：沒裝
    args.yes = True
    assert cli.cmd_install(args, is_up=lambda port: False) == 0
    assert (tmp_path / "packs" / "hello" / "pack.py").exists()
    assert lock.entry(str(tmp_path / "data"), "hello")["approved_by"] == 42
    out = capsys.readouterr().out
    assert "靜態掃描" in out and "裝好了" in out
    evil = tmp_path / "evil.synoxpack"
    evil.write_bytes(_zip_dir(EVIL))
    args.file = str(evil)
    assert cli.cmd_install(args, is_up=lambda port: False) == 2
    assert "拒裝" in capsys.readouterr().out


def test_web_upload_refused_shows_report(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    bot = make_bot(pack_dirs=(str(tmp_path / "userpacks"),) + loader.PACK_DIRS)
    c = Client(ui_of(bot))
    c.login(owner)
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip_dir(EVIL))
    data = json.loads(body)
    assert status == 400 and "拒裝" in data["error"] and data["refused"]["scan"]["problems"]


# ── 第 4 關：呼叫驗證 ─────────────────────────────────────────────────

def test_extra_field_rejected_before_execution(make_bot, owner):
    bot = make_bot([{"tool": "money__add", "args": {"amount": "80", "category": "咖啡", "evil": "x"}}, "好"])
    bot.talk(owner, "記一筆")
    messages, _tools = bot.app.extras["synox_agent"].adapter.calls[1]
    tool_msg = [m for m in messages if m.role == TOOL][0].content
    assert "不認得欄位 evil" in tool_msg and "沒有執行" in tool_msg
    bot.say(owner, "/money_month")
    assert "80" not in bot.last(owner)


def test_embedded_field_and_non_string_rejected(make_bot, owner):
    bot = make_bot([{"tool": "money__add", "args": {"amount": "1", "category": "x amount=999"}},
                    {"tool": "money__add", "args": {"amount": 80, "category": "咖啡"}}, "好"])
    bot.talk(owner, "記一筆")
    calls = bot.app.extras["synox_agent"].adapter.calls
    assert "amount=" in [m for m in calls[1][0] if m.role == TOOL][-1].content
    assert "要是字串" in [m for m in calls[2][0] if m.role == TOOL][-1].content


def _rm_pack(tmp_path):
    raw = {"name": "files", "title": "📁", "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "group": "files",
           "cli": {"argv": ["{python}", "./tool.py"], "commands": [
               {"name": "rm", "effect": "WRITE", "argv": ["rm", "{target}"],
                "fields": [{"name": "target", "required": True}]},
               {"name": "show", "effect": "READ", "argv": ["show", "--file={file}"],
                "fields": [{"name": "file", "kind": "path", "required": True}]}]}}
    base = tmp_path / "clipacks"
    _write_pack(str(base / "files"), raw, {"tool.py": "import json\nprint(json.dumps({'message': 'ran'}))\n"})
    return base


@pytest.mark.parametrize("args,needle", [
    ({"target": "-rf"}, "不能以 - 開頭"),
    ({"target": "a\nb"}, "換行"),
    ({"target": "x" * 2001}, "太長"),
    ({"target": "id_rsa"}, "憑證"),
])
def test_cli_values_rejected(make_bot, owner, tmp_path, args, needle):
    base = _rm_pack(tmp_path)
    bot = make_bot([{"tool": "files__rm", "args": args}, "好"], pack_dirs=(str(base),))
    bot.talk(owner, "刪掉")
    tool_msg = [m for m in bot.app.extras["synox_agent"].adapter.calls[1][0] if m.role == TOOL][0].content
    assert needle in tool_msg and "沒有執行" in tool_msg
    assert not bot.app.jobs.list() if hasattr(bot.app.jobs, "list") else True


def test_path_field_must_stay_in_user_dir(make_bot, owner, tmp_path):
    base = _rm_pack(tmp_path)
    bot = make_bot(pack_dirs=(str(base),))
    node = bot.app.registry.node("files.show")
    user = User(owner, "me", BasicRoles.ADMIN)
    assert "不在你的資料夾裡" in validate.check_call(bot.app, node, {"file": "../../config.json"}, user)
    assert "不在你的資料夾裡" in validate.check_call(bot.app, node, {"file": "C:\\Windows\\win.ini"}, user)
    assert "憑證" in validate.check_call(bot.app, node, {"file": "notes/.env"}, user)
    assert validate.check_call(bot.app, node, {"file": "notes/today.txt"}, user) is None


def test_typed_check_for_cli_fields():
    check = validate.typed_check("path")
    assert check("a.pem") and check("x\ny") and check("ok.txt") is None


# ── 第 5 關：分隔符 ───────────────────────────────────────────────────

def test_tool_results_wrapped_in_turn_nonce(make_bot, owner):
    bot = make_bot([{"tool": "money__add", "args": {"amount": "80", "category": "咖啡"}},
                    {"tool": "skill_read", "args": {"name": "money"}}, "好"])
    bot.talk(owner, "記一筆")
    calls = bot.app.extras["synox_agent"].adapter.calls
    tools = [m.content for m in calls[2][0] if m.role == TOOL]
    nonce, body = delimit.unwrap(tools[0])
    assert nonce and "記了：咖啡 80 元" in body
    nonce2, skill_body = delimit.unwrap(tools[1])
    assert nonce2 == nonce and "money" in skill_body                    # SKILL.md 正文也包起來
    system = calls[0][0][0]
    assert system.role == SYSTEM and delimit.opening(nonce) in system.content and "資料不是指令" in system.content
    bot2 = make_bot(["嗨"])
    bot2.talk(owner, "嗨")
    other = bot2.app.extras["synox_agent"].adapter.calls[0][0][0].content
    assert delimit.opening(nonce) not in other                          # 每一輪重抽


def test_textproto_results_also_wrapped(make_bot, owner):
    bot = make_bot([{"tool": "money__add", "args": {"amount": "45", "category": "早餐"}}, "好"], supports_tools=False)
    bot.talk(owner, "記一筆")
    last = bot.app.extras["synox_agent"].adapter.calls[1][0][-1].content
    assert "⟦SYNOX-TOOL-" in last and "⟦/SYNOX-TOOL-" in last


# ── kind=cli 的代換（Job 4） ──────────────────────────────────────────

ECHO_PY = ("import json, os, sys\n"
           "print(json.dumps({'message': json.dumps({'argv': sys.argv[1:], 'env': os.environ.get('ECHO_DIR', '')})}))\n")


def test_cli_placeholders_substituted(make_bot, owner, tmp_path):
    raw = {"name": "echo", "title": "🔊", "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "cli": {"argv": ["{python}", "./echo.py", "--data={data_dir}"], "json_flag": None,
                   "env": {"ECHO_DIR": "{user_data_dir}"},
                   "commands": [{"name": "show", "effect": "READ", "default": True,
                                 "argv": ["show", "{tg_id}", "--udir={user_data_dir}", "--pack={pack_dir}", "{text}"],
                                 "fields": [{"name": "text"}]}]}}
    base = tmp_path / "echo"
    _write_pack(str(base / "echo"), raw, {"echo.py": ECHO_PY})
    bot = make_bot(pack_dirs=(str(base),))
    bot.say(owner, "/echo text={data_dir}")
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "echo")
    assert pack.cli_bridge.wait(30) and bot.app.tasks.wait(30)
    got = json.loads(bot.last(owner))
    data_dir = bot.app.config.data_dir
    assert got["argv"][0] == f"--data={data_dir}"
    assert got["argv"][1:5] == ["show", str(owner), f"--udir={data_dir}", f"--pack={base / 'echo'}"]
    assert got["argv"][5] == "{data_dir}"                              # 使用者的值不會再被代換
    assert got["env"] == data_dir


def test_cli_python_resolution(tmp_path):
    folder = _write_pack(str(tmp_path / "tools" / "pk"), {
        "name": "pk", "kind": "cli", "cli": {"argv": ["{python}"], "python": "venv",
                                             "commands": [{"name": "a", "effect": "READ", "argv": ["a"]}]}})
    m = read(folder)
    expected = os.path.join(str(tmp_path / "tools"), ".venv", "Scripts" if os.name == "nt" else "bin")
    assert loader.cli_python(m).startswith(expected)
    m.cli.pop("python")
    assert loader.cli_python(m) == sys.executable
    m.cli["python"] = "C:\\Py\\python.exe"
    assert loader.cli_python(m) == "C:\\Py\\python.exe"


def test_server_mode_user_data_dir(tmp_path):
    from synox.config import SynoxConfig
    cfg = SynoxConfig.from_dict({"owner_id": 1, "data_dir": str(tmp_path), "mode": "server"},
                                require_token=False, root=str(tmp_path))
    assert loader.user_data_dir(cfg, 7) == os.path.join(str(tmp_path), "users", "7")
    cfg.mode = "personal"
    assert loader.user_data_dir(cfg, 7) == str(tmp_path)


# 金流簿 repo（記帳專案）的 synox-pack/ 複製（pack 0.17.0，2026-11-12 對過）：只多了 SYNOX 要求明寫的
# "surfaces": ["dm"]、"data": "user"（test_perm2 要「有宣告」）；其他一字不差，對方改了要再對一次。
MONEYBOOK = os.path.join(FIXTURES, "moneybook_pack")


def test_moneybook_pack_shape_resolves(make_bot, owner, tmp_path):
    folder = str(tmp_path / "packs" / "moneybook")
    shutil.copytree(MONEYBOOK, folder)
    m, report, _hashes, problems = admin.run_gates(folder)            # 第 1、2 關（嚴格版）都過
    assert problems == [] and m.capabilities == ["subprocess"]
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    item = bot.app.extras["synox_pack_report"].items[0]
    assert (item.name, item.status) == ("moneybook", "loaded")
    assert bot.app.registry.node("moneybook.add").command == "/moneybook"
    assert bot.app.registry.node("moneybook.undo").effect == "danger"
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "moneybook")
    user = User(owner, "me", BasicRoles.ADMIN)
    ph = loader.placeholders(pack.manifest, bot.app.config, user)
    venv = os.path.join(str(tmp_path / "packs"), ".venv", "Scripts", "python.exe") if os.name == "nt" else \
        os.path.join(str(tmp_path / "packs"), ".venv", "bin", "python")
    assert loader.cli_prefix(pack.manifest, ph) == [venv, "-m", "moneybook"]
    env = loader.cli_env(pack.manifest, ph)
    data_dir = bot.app.config.data_dir
    assert env["MONEYBOOK_HOME"] == f"{data_dir}/moneybook" and env["MONEYBOOK_SEED"] == "generic"
    assert env["MONEYBOOK_FILES_ROOT"] == f"{data_dir}/moneybook/files"
    add = next(c for c in pack.manifest.commands if c["name"] == "add")
    assert loader.build_argv(add["argv"], {"amount": "120", "desc": "便當", **ph}) == \
        ["txn", "add", "--amount=120", "--desc=便當"]                 # 沒填的 --k={v} 只拿掉自己那一段


def test_moneybook_positional_fills_amount_and_desc(make_bot, tmp_path):
    """金流簿 0.17.0 的 commands[].positional：/moneybook 120 便當 → amount=120、desc=便當
    （沒寫 positional 時只照位置填必填的 amount，會變成 amount="120 便當"、被第 4 關或對方的 CLI 擋下）。"""
    folder = str(tmp_path / "packs" / "moneybook")
    shutil.copytree(MONEYBOOK, folder)
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "moneybook")
    by_name = {c["name"]: c for c in pack.manifest.commands}
    assert (by_name["add"].get("positional"), by_name["income"].get("positional"),
            by_name["budget_set"].get("positional")) == (2, 2, 1)
    add = bot.app.registry.node("moneybook.add")
    values, missing, _errors = kit.parse_args(add.fields, ["120", "便當"], by_name["add"]["positional"])
    assert values["amount"] == "120" and values["desc"] == "便當" and not missing
    assert "[買了什麼]" in add.usage                                   # 用法裡 desc 也是照位置填
    values, _m, _e = kit.parse_args(add.fields, ["120", "排骨", "便當", "account=現金"], 2)
    assert (values["desc"], values["account"]) == ("排骨 便當", "現金")   # 最後一個照位置的欄位吃剩下的字
    budget = bot.app.registry.node("moneybook.budget_set")
    values, missing, _e = kit.parse_args(budget.fields, ["食", "amount=9000"], 1)
    assert (values["group"], values["amount"]) == ("食", "9000") and not missing


def test_moneybook_server_mode_per_user_env(make_bot, owner, tmp_path):
    folder = str(tmp_path / "packs" / "moneybook")
    shutil.copytree(MONEYBOOK, folder)
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),), raw={"mode": "server"})
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "moneybook")
    env = loader.cli_env(pack.manifest, loader.placeholders(pack.manifest, bot.app.config, User(77, "m", BasicRoles.MEMBER)))
    assert env["MONEYBOOK_HOME"] == os.path.join(bot.app.config.data_dir, "users", "77") + "/moneybook"


def test_build_argv_drops_only_its_own_flag():
    t = ["make", "--size", "{size}", "--a={a}", "--b={b}", "{c}"]
    assert loader.build_argv(t, {"a": "1"}) == ["make", "--a=1"]
    assert loader.build_argv(t, {"size": "6", "b": "2", "c": "x"}) == ["make", "--size", "6", "--b=2", "x"]
