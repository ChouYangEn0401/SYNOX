# -*- coding: utf-8 -*-
"""SDK P2：pack 的 secret（pack.json auth.fields[]）。
存進保管箱（packs/<name>/<field>；伺服器版每人一份）、Web UI 工具頁「連接」（password、不回值、只回最後 4 碼、
留空沿用、CSRF／Origin／權限）、cli pack 只拿到宣告了 env 的、絕不進 argv、python pack 的 pack.secret、
掃描器不算 capability、第 4 關擋 AI 把 secret 當參數、工具頁／doctor 的狀態、內建 connector 不受影響。
後端是本機的假命令列程式（真的經 JobRunner 跑），不連網、不開埠。"""
import json
import os
import sys

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID, trust_core

from synox import doctor
from synox.agent import validate as gate4
from synox.packs import scan
from synox.packs import secrets as pack_secrets
from synox.packs.manifest import ManifestError, read, validate
from synox.vault import Vault

from test_web import Client, ui_of

TOKEN = "tdk_live_0123456789abcdef"

# 回音 pack 宣告 subprocess；角色能力上限（PERM-1）預設只有 admin 有。這幾個測的是 secret 不是上限，所以把 subprocess 開給每一級。
_ALL_SUB = ["network", "filesystem:own", "subprocess"]
OPEN_POLICY = {"policy": {"roles": {r: {"capabilities": _ALL_SUB} for r in ("guest", "member", "admin")}}}

ECHO = r'''
import json, os, sys
print(json.dumps({"ok": True, "argv_text": " ".join(sys.argv[1:]),
                  "key": os.environ.get("ECHO_API_KEY", "(none)"),
                  "region": os.environ.get("ECHO_REGION", "(none)"),
                  "nokey": os.environ.get("NOENV_SECRET", "(none)")}, ensure_ascii=False))
'''

PY_PACK = r'''
from isdtelekit.core.registry import READ

def install(app, pack):
    def show(api, chat_id, user, args):
        value = pack.secret("api_key", user)
        api.send_message(chat_id, "有 key" if value else "沒有 key")
        api.send_message(chat_id, "長度 %d" % len(value or ""))
    pack.group.leaf("show", show, "看有沒有 key", effect=READ, default=True)
'''


def _cli_manifest(**over):
    m = {
        "name": "echo", "title": "回音", "summary": "測試用", "version": "0.1.0", "kind": "cli",
        "access": "owner", "capabilities": ["subprocess"], "skill": "SKILL.md",
        "auth": {"type": "token", "fields": [
            {"name": "api_key", "label": "Echo API key", "secret": True, "env": "ECHO_API_KEY"},
            {"name": "region", "label": "地區", "env": "ECHO_REGION", "required": False},
            {"name": "noenv", "label": "沒有 env 的", "secret": True, "required": False}]},
        "cli": {"python": sys.executable, "argv": ["{python}", "{pack_dir}/echo_cli.py"], "json_flag": "--json",
                "timeout": 30,
                "commands": [{"name": "add", "default": True, "positional": 1, "effect": "read", "summary": "回音",
                              "argv": ["add", "--text={text}"],
                              "fields": [{"name": "text", "ask": "內容", "required": True}]}]},
    }
    m.update(over)
    return m


def _write(folder, manifest, files):
    os.makedirs(folder, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: x\ndescription: 測試\n---\n")


def _cli_pack(tmp_path, **over):
    _write(str(tmp_path / "packs" / "echo"), _cli_manifest(**over), {"echo_cli.py": ECHO})
    return (str(tmp_path / "packs"),)


def _py_manifest(**over):
    m = {"name": "pykey", "title": "Py key", "summary": "測試", "version": "0.1.0", "kind": "python",
         "python": {"module": "pack"}, "capabilities": [], "skill": "SKILL.md",
         "auth": {"type": "token", "fields": [{"name": "api_key", "label": "API key", "secret": True}]}}
    m.update(over)
    return m


def _py_pack(tmp_path, **over):
    _write(str(tmp_path / "packs" / "pykey"), _py_manifest(**over), {"pack.py": PY_PACK})
    return (str(tmp_path / "packs"),)


def _client(bot, tg_id=OWNER_ID):
    c = Client(ui_of(bot))
    c.login(tg_id)
    return c


def _pack_row(c, name):
    status, data = c.get("/api/tools")
    assert status == 200, data
    return next(p for p in data["packs"] if p["name"] == name)


# ── manifest ───────────────────────────────────────────────────────────

def test_manifest_checks_auth_fields(tmp_path):
    folder = str(tmp_path / "p")
    _write(folder, _cli_manifest(), {"echo_cli.py": ECHO})
    m = read(folder)
    assert [f["name"] for f in pack_secrets.managed_fields(m)] == ["api_key", "region", "noenv"]
    bad = _cli_manifest(auth={"type": "token", "fields": [{"name": "Bad Name"}, {"name": "a", "env": "1X"},
                                                           {"name": "b", "kind": "blob"}, {"name": "c", "secret": "yes"}],
                              "managed": "maybe"})
    with pytest.raises(ManifestError) as e:
        validate(bad, folder)
    text = str(e.value)
    for part in ("auth.fields[0]", "a.env", "b.kind", "c.secret", "auth.managed"):
        assert part in text, text


def test_oauth_and_none_are_not_managed(tmp_path):
    folder = str(tmp_path / "p")
    _write(folder, _cli_manifest(auth={"type": "oauth", "fields": ["client_id"]}), {"echo_cli.py": ECHO})
    assert pack_secrets.managed_fields(read(folder)) == []


_LIBS = os.environ.get("SYNOX_LIBS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "SYNOX_Libs")


@pytest.mark.skipif(not os.path.isdir(os.path.join(_LIBS, "packs")),
                    reason="沒有工具庫（設環境變數 SYNOX_LIBS=<SYNOX_Libs 資料夾>，或放在 SYNOX 旁邊）")
def test_connectors_in_the_library_are_not_managed():
    """工具庫的 4 個 connector（2026-11-12 以前在 SYNOX 的 connectors/）有自己的 token 指令（/todoist_token…），
    工具頁不出「連接」按鈕，行為不變。只讀工具庫。"""
    names = []
    for sub in ("notion", "todoist", "google-calendar", "apple-reminders"):
        m = read(os.path.join(_LIBS, "packs", sub))
        names.append(m.name)
        assert pack_secrets.managed_fields(m) == [], m.name
    assert names == ["notion", "todoist", "google-calendar", "apple-reminders"]


def test_auth_managed_flag_overrides(tmp_path):
    folder = str(tmp_path / "p")
    _write(folder, _py_manifest(), {"pack.py": "def install(app, pack):\n    pass\n"})
    assert pack_secrets.managed_fields(read(folder)) == []           # python 沒呼叫 pack.secret
    _write(folder, _py_manifest(auth={"type": "token", "managed": "synox", "fields": ["api_key"]}),
           {"pack.py": "def install(app, pack):\n    pass\n"})
    assert [f["name"] for f in pack_secrets.managed_fields(read(folder))] == ["api_key"]
    _write(folder, _py_manifest(auth={"type": "token", "managed": "pack", "fields": ["api_key"]}), {"pack.py": PY_PACK})
    assert pack_secrets.managed_fields(read(folder)) == []


# ── 保管箱 ─────────────────────────────────────────────────────────────

def test_store_keys_and_per_user_isolation(tmp_path):
    vault = Vault(b"k" * 32, str(tmp_path))
    fields = [{"name": "api_key", "label": "k", "secret": True, "env": "", "kind": "text", "required": True,
               "help": ""}]
    shared = pack_secrets.PackSecrets(vault)
    shared.update("echo", fields, {"api_key": TOKEN})
    raw = vault.load_json(pack_secrets.VAULT_NAME)
    assert list(raw) == ["packs/echo/api_key"]
    with open(vault.path(pack_secrets.VAULT_NAME), "rb") as f:
        assert TOKEN.encode() not in f.read()                         # 落地是密文
    server = pack_secrets.PackSecrets(vault, server=True)
    server.update("echo", fields, {"api_key": "alice-secret-value"}, OWNER_ID)
    assert server.get("echo", "api_key", OWNER_ID) == "alice-secret-value"
    assert server.get("echo", "api_key", OTHER_ID) is None            # B 看不到 A 的
    assert os.path.exists(os.path.join(str(tmp_path), "users", str(OWNER_ID), "pack_secrets.json.enc"))
    with pytest.raises(pack_secrets.SecretError):
        server.get("echo", "api_key", None)                           # 伺服器版一定要給 user
    server.update("echo", fields, {"api_key": ""}, OWNER_ID)          # 空字串＝沿用
    assert server.get("echo", "api_key", OWNER_ID) == "alice-secret-value"
    server.update("echo", fields, {}, OWNER_ID, clear=["api_key"])
    assert server.get("echo", "api_key", OWNER_ID) is None
    with pytest.raises(pack_secrets.SecretError):
        shared.update("echo", fields, {"other": "x"})                # 沒宣告的欄位


# ── Web UI ─────────────────────────────────────────────────────────────

def test_connect_form_never_returns_value(make_bot, tmp_path):
    bot = make_bot(pack_dirs=_cli_pack(tmp_path))
    c = _client(bot)
    row = _pack_row(c, "echo")
    assert row["connect"] is True and row["status"] == "要先設定" and row["missing"] == ["Echo API key"]
    status, view = c.get("/api/pack-secrets/echo")
    assert status == 200 and view["connected"] is False
    assert {f["name"]: f["secret"] for f in view["fields"]} == {"api_key": True, "region": False, "noenv": True}
    status, saved = c.post("/api/pack-secrets/echo", {"values": {"api_key": TOKEN, "region": "tw"}})
    assert status == 200 and saved["connected"] is True, saved
    body = json.dumps(saved, ensure_ascii=False)
    assert TOKEN not in body
    key = next(f for f in saved["fields"] if f["name"] == "api_key")
    assert key["set"] is True and key["last4"] == TOKEN[-4:] and "value" not in key
    assert next(f for f in saved["fields"] if f["name"] == "region")["value"] == "tw"   # 不是 secret 的回值
    _status, again = c.get("/api/pack-secrets/echo")
    assert TOKEN not in json.dumps(again, ensure_ascii=False)
    assert _pack_row(c, "echo")["status"] == "已連接"
    # 留空＝沿用原值
    status, _ = c.post("/api/pack-secrets/echo", {"values": {"api_key": "", "region": "jp"}})
    assert status == 200
    store = pack_secrets.of(bot.app)
    assert store.get("echo", "api_key") == TOKEN and store.get("echo", "region") == "jp"


def test_connect_needs_csrf_and_same_origin(make_bot, tmp_path):
    bot = make_bot(pack_dirs=_cli_pack(tmp_path))
    c = _client(bot)
    body = json.dumps({"values": {"api_key": TOKEN}}).encode()
    status, _h, _b = c.raw("POST", "/api/pack-secrets/echo", body, headers={"X-SYNOX-CSRF": "wrong"})
    assert status == 403
    status, _h, _b = c.raw("POST", "/api/pack-secrets/echo", body, headers={"Origin": "http://evil.example"})
    assert status == 403
    assert pack_secrets.of(bot.app).get("echo", "api_key") is None
    anon = Client(ui_of(bot))
    status, _ = anon.get("/api/pack-secrets/echo")
    assert status == 401


def test_personal_mode_only_owner_can_connect(make_bot, tmp_path):
    bot = make_bot(raw=OPEN_POLICY, pack_dirs=_cli_pack(tmp_path, access="everyone"))
    other = _client(bot, OTHER_ID)
    status, _ = other.post("/api/pack-secrets/echo", {"values": {"api_key": TOKEN}})
    assert status == 403
    assert _pack_row(other, "echo")["connect"] is False


def test_server_mode_each_user_sets_their_own(make_bot, tmp_path):
    dirs = _cli_pack(tmp_path, access="member")
    trust_core(tmp_path / "data", str(tmp_path / "packs" / "echo"))      # 手放的 cli pack＝third-party（PERM-8），先核准成 core
    bot = make_bot(raw={"mode": "server", **OPEN_POLICY}, pack_dirs=dirs)
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    owner_c, member_c = _client(bot), _client(bot, OTHER_ID)
    assert member_c.post("/api/pack-secrets/echo", {"values": {"api_key": "member-key-0000"}})[0] == 200
    assert _pack_row(member_c, "echo")["status"] == "已連接"
    assert _pack_row(owner_c, "echo")["status"] == "要先設定"            # 擁有者那一份還是空的
    store = pack_secrets.of(bot.app)
    assert store.get("echo", "api_key", OTHER_ID) == "member-key-0000"
    assert store.get("echo", "api_key", OWNER_ID) is None


def test_bad_values_are_rejected(make_bot, tmp_path):
    bot = make_bot(pack_dirs=_cli_pack(tmp_path))
    c = _client(bot)
    assert c.post("/api/pack-secrets/echo", {"values": {"api_key": "a\nb"}})[0] == 400
    assert c.post("/api/pack-secrets/echo", {"values": {"nope": "x"}})[0] == 400
    assert c.post("/api/pack-secrets/echo", {"values": {"api_key": 5}})[0] == 400
    assert c.get("/api/pack-secrets/note")[0] == 404                 # 沒有 auth.fields 的 pack


def test_file_field_upload(make_bot, tmp_path):
    over = {"auth": {"type": "file", "fields": [{"name": "creds", "label": "憑證檔", "secret": True,
                                                  "env": "ECHO_API_KEY"}]}}
    bot = make_bot(pack_dirs=_cli_pack(tmp_path, **over))
    c = _client(bot)
    content = '{\n  "private_key": "-----BEGIN-----abc-----END-----"\n}\n'
    status, saved = c.post("/api/pack-secrets/echo", {"values": {"creds": content}})
    assert status == 200 and saved["connected"]
    f = saved["fields"][0]
    assert f["kind"] == "file" and f["size"] == len(content) and "last4" not in f and "value" not in f
    assert pack_secrets.of(bot.app).get("echo", "creds") == content


# ── cli：只放進環境變數、不進 argv ────────────────────────────────────────

def test_cli_gets_declared_env_secret_only(make_bot, owner, tmp_path):
    bot = make_bot(pack_dirs=_cli_pack(tmp_path))
    _client(bot).post("/api/pack-secrets/echo", {"values": {"api_key": TOKEN, "region": "tw",
                                                             "noenv": "no-env-secret-zz"}})
    bot.say(owner, "/echo hello")
    assert bot.app.tasks.wait(20)
    out = "\n".join(bot.texts(owner))
    assert "--text=hello" in out
    assert TOKEN in out and "tw" in out        # 子程序的環境看得到（假程式把它印出來）
    assert "no-env-secret-zz" not in out       # 沒寫 env 的不給


def test_cli_argv_never_contains_secret(make_bot, owner, tmp_path, monkeypatch):
    from isdtelekit.jobs import cli as jobs_cli
    bot = make_bot(pack_dirs=_cli_pack(tmp_path))
    _client(bot).post("/api/pack-secrets/echo", {"values": {"api_key": TOKEN}})
    calls = []
    real_call = jobs_cli.JsonCli.call

    def spy(self, *args, **kw):
        calls.append(self.argv_prefix + [str(a) for a in args])
        return real_call(self, *args, **kw)
    monkeypatch.setattr(jobs_cli.JsonCli, "call", spy)
    bot.say(owner, "/echo hi")
    assert bot.app.tasks.wait(20)
    assert calls and all(TOKEN not in " ".join(map(str, c)) for c in calls)


def test_cli_without_secret_says_connect_on_web(make_bot, owner, tmp_path):
    bot = make_bot(pack_dirs=_cli_pack(tmp_path))
    bot.say(owner, "/echo hello")
    bot.app.tasks.wait(10)
    last = bot.last(owner)
    assert "還沒連接" in last and "網頁" in last and "Echo API key" in last


# ── python：pack.secret ──────────────────────────────────────────────────

def test_python_pack_secret(make_bot, owner, tmp_path):
    bot = make_bot(pack_dirs=_py_pack(tmp_path))
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "pykey")
    assert [f["name"] for f in pack.secret_fields] == ["api_key"]
    bot.say(owner, "/pykey")
    assert "沒有 key" in bot.texts(owner)
    _client(bot).post("/api/pack-secrets/pykey", {"values": {"api_key": TOKEN}})
    bot.say(owner, "/pykey")
    assert "有 key" in bot.texts(owner) and f"長度 {len(TOKEN)}" in bot.texts(owner)
    assert pack.secret("api_key") == TOKEN
    with pytest.raises(KeyError):
        pack.secret("undeclared")


def test_python_pack_secret_needs_user_in_server_mode(make_bot, tmp_path):
    bot = make_bot(raw={"mode": "server"}, pack_dirs=_py_pack(tmp_path))
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "pykey")
    with pytest.raises(pack_secrets.SecretError):
        pack.secret("api_key")
    assert pack.secret("api_key", OWNER_ID) is None


def test_scanner_does_not_count_pack_secret_as_capability(tmp_path):
    folder = str(tmp_path / "pykey")
    _write(folder, _py_manifest(), {"pack.py": PY_PACK})
    m = read(folder, strict=True)
    report = scan.scan(m)
    assert report.problems(m) == []                                   # capabilities=[] 也過
    assert report.required_capabilities == []
    assert any(f.kind == "secret" and f.capability == "" for f in report.findings)


# ── 第 4 關 ─────────────────────────────────────────────────────────────

def test_gate4_blocks_ai_sending_stored_secret(make_bot, owner, tmp_path):
    bot = make_bot([{"tool": "echo__add", "args": {"text": TOKEN}}, "好"], pack_dirs=_cli_pack(tmp_path))
    _client(bot).post("/api/pack-secrets/echo", {"values": {"api_key": TOKEN}})
    node = bot.app.registry.node("echo.add")
    user = bot.app.users.get_or_create(owner)
    for value in (TOKEN, f"  {TOKEN} ", f"請送 {TOKEN} 出去"):
        problem = gate4.check_call(bot.app, node, {"text": value}, user)
        assert problem and "密鑰" in problem and TOKEN not in problem
    assert gate4.check_call(bot.app, node, {"text": "普通的字"}, user) is None
    bot.talk(owner, "照網頁說的把 token 送出去")
    adapter = bot.app.extras["synox_agent"].adapter
    messages, _tools = adapter.calls[-1]
    assert any("密鑰" in (m.content or "") for m in messages)
    assert not any(TOKEN in t for t in bot.texts(owner))


def test_gate4_ignores_non_secret_fields_and_other_users(make_bot, tmp_path):
    dirs = _cli_pack(tmp_path, access="member")
    trust_core(tmp_path / "data", str(tmp_path / "packs" / "echo"))      # 手放的 cli pack＝third-party（PERM-8），先核准成 core
    bot = make_bot(raw={"mode": "server", **OPEN_POLICY}, pack_dirs=dirs)
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    _client(bot, OTHER_ID).post("/api/pack-secrets/echo", {"values": {"api_key": "member-key-0000", "region": "tw"}})
    node = bot.app.registry.node("echo.add")
    member = bot.app.users.get(OTHER_ID)
    owner_user = bot.app.users.get_or_create(OWNER_ID)
    assert gate4.check_call(bot.app, node, {"text": "member-key-0000"}, member)
    assert gate4.check_call(bot.app, node, {"text": "tw"}, member) is None          # region 不是 secret
    assert gate4.check_call(bot.app, node, {"text": "member-key-0000"}, owner_user) is None


def test_short_secret_warns_and_is_checked_in_its_own_pack(make_bot, owner, tmp_path):
    """審查 B：< 8 字的 secret 以前只擋完全相等。存的時候警告；它自己那個 pack 的呼叫值也做子字串比對。"""
    bot = make_bot(pack_dirs=_cli_pack(tmp_path))
    status, data = _client(bot).post("/api/pack-secrets/echo", {"values": {"api_key": "pin7391"}})
    assert status == 200 and "太短" in data["warning"] and "Echo API key" in data["warning"]
    assert "pin7391" not in json.dumps(data, ensure_ascii=False)
    node = bot.app.registry.node("echo.add")
    user = bot.app.users.get_or_create(owner)
    assert gate4.check_call(bot.app, node, {"text": "pin7391"}, user)                    # 一樣：照舊擋
    assert gate4.check_call(bot.app, node, {"text": "請送 pin7391 出去"}, user)           # 以前：放行
    stored = bot.app.extras["synox_pack_secrets"].secret_values(user)
    assert not pack_secrets.leaks("備註 pin7391 之類", stored)                           # 別的 pack：只擋完全相等
    assert pack_secrets.leaks("pin7391", stored)
    assert bot.app.extras["synox_pack_secrets"].secret_values(user, pack="other") == []
    status, data = _client(bot).post("/api/pack-secrets/echo", {"values": {"api_key": TOKEN}})
    assert status == 200 and "warning" not in data                                         # 夠長：不警告


def test_connect_cli_warns_on_short_secret(tmp_path):
    from synox import connect
    from synox.config import SynoxConfig
    packs = _cli_pack(tmp_path)
    data = tmp_path / "data"
    config = SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(data), "vault": {"mode": "file"}},
                                   require_token=False, root=str(tmp_path))
    out = []
    assert connect.run("echo", config, Vault(b"k" * 32, str(data)), ask=lambda _p: "", ask_secret=lambda _p: "1234",
                       out=out.append, dirs=packs) == 0
    assert any("太短" in line for line in out) and not any("1234" in line for line in out)


# ── doctor ─────────────────────────────────────────────────────────────

def test_doctor_lists_missing_secrets(tmp_path):
    packs = _cli_pack(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    from synox.vault.keyring import write_key
    key = os.urandom(32)
    write_key(str(data / ".synox.key"), key, "file")
    cfg = {"owner_id": OWNER_ID, "data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "none"},
           "packs": {"dirs": [packs[0]]}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "還沒連接" in text and "Echo API key" in text, text
    fields = pack_secrets.managed_fields(read(os.path.join(packs[0], "echo")))
    pack_secrets.PackSecrets(Vault(key, str(data))).update("echo", fields, {"api_key": TOKEN})
    lines.clear()
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "🔌 已連接" in text and TOKEN not in text and "Echo API key" not in text


# ── python -m synox connect：SYNOX 收的 pack 存同一份 ─────────────────────

def test_connect_cli_writes_same_store(tmp_path):
    from synox import connect
    from synox.config import SynoxConfig
    packs = _cli_pack(tmp_path)
    data = tmp_path / "data"
    config = SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(data), "vault": {"mode": "file"}},
                                   require_token=False, root=str(tmp_path))
    vault = Vault(b"k" * 32, str(data))
    out = []
    code = connect.run("echo", config, vault, ask=lambda _p: "", ask_secret=lambda _p: TOKEN, out=out.append,
                       dirs=packs)
    assert code == 0, out
    assert pack_secrets.PackSecrets(vault).get("echo", "api_key") == TOKEN
    assert TOKEN not in "\n".join(out)
    assert connect.run("echo", config, vault, clear=True, out=out.append, dirs=packs) == 0
    assert pack_secrets.PackSecrets(vault).get("echo", "api_key") is None
