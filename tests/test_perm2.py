"""PERM-2：pack.json 的權限宣告（surfaces、data）、第 2 關的 data 規則、loader 的 private_only／shared 寫入要管理員、
安裝報告的 trust（寫進 packs.lock）、升級比對。只用暫存資料夾，不連網、不開埠。"""

import json
import os

import pytest

from synox.packs import admin, loader, lock, upgrade
from synox.packs.manifest import ManifestError, read, validate

from conftest import trust_core
from test_security import HELLO_PY, _write_pack, _zip_dir

STORE_PY = ("def install(app, pack):\n"
            "    def add(api, c, u, a):\n"
            "        pack.store.update(lambda d: d.setdefault('items', []).append(1), {})\n"
            "    def show(api, c, u, a):\n"
            "        api.send_message(c, str(pack.store.load({})))\n"
            "    def mine(api, c, u, a):\n"
            "        api.send_message(c, str(pack.store.of(u).load({})))\n"
            "    pack.group.leaf('add', add, 'add')\n"
            "    pack.group.leaf('show', show, 'show')\n"
            "    pack.group.leaf('mine', mine, 'mine')\n")

OF_USER_PY = ("def install(app, pack):\n"
              "    def add(api, c, u, a):\n"
              "        pack.store.of(u).update(lambda d: d.setdefault('items', []).append(1), {})\n"
              "        key = pack.secret('token', u)\n"
              "        other = pack.secret('token', user=u)\n"
              "        api.send_message(c, 'ok' if pack.store.encrypted is not None else '')\n"
              "    pack.group.leaf('add', add, 'add')\n")


def _gates(tmp_path, raw, files, tag="p"):
    folder = _write_pack(str(tmp_path / tag), raw, files)
    return admin.run_gates(folder)


# ── 第 1 關：surfaces、data ───────────────────────────────────────────

def test_defaults_surfaces_dm_and_data_from_storage(tmp_path):
    plain = read(_write_pack(str(tmp_path / "a"), {}, {"pack.py": HELLO_PY}))
    assert plain.surfaces == ["dm"] and not plain.surfaces_declared and not plain.channel_ok
    assert plain.data == "none" and not plain.data_declared                 # python 沒寫 storage＝none
    stored = read(_write_pack(str(tmp_path / "b"), {"storage": "plain"}, {"pack.py": HELLO_PY}))
    assert stored.data == "user"                                            # 寫了 storage＝user
    for tag, kind in (("c", "connector"),):
        m = read(_write_pack(str(tmp_path / tag), {"kind": kind, "auth": "token"}))
        assert m.data == "none" and m.surfaces == ["dm"]


@pytest.mark.parametrize("cli_env,expected", [
    ({"HOME_DIR": "{user_data_dir}/x"}, "user"),
    ({"HOME_DIR": "{data_dir}/x"}, "shared"),
    ({"HOME_DIR": "{data_dir}/x", "MINE": "{user_data_dir}"}, "user"),   # 兩個都用＝user（第 2 關要明寫 shared）
    ({}, "none"),
])
def test_cli_default_data_from_templates(tmp_path, cli_env, expected):
    raw = {"kind": "cli", "cli": {"argv": ["{python}", "./t.py"], "env": cli_env,
                                  "commands": [{"name": "x", "effect": "READ", "argv": ["x"]}]}}
    assert read(_write_pack(str(tmp_path / "p"), raw, {"t.py": "print(1)\n"})).data == expected


def test_declared_surfaces_and_data(tmp_path):
    m = read(_write_pack(str(tmp_path / "a"), {"surfaces": ["channel", "dm"], "data": "shared"},
                         {"pack.py": HELLO_PY}))
    assert m.surfaces == ["dm", "channel"] and m.channel_ok and m.data == "shared" and m.data_declared


@pytest.mark.parametrize("over,needle", [
    ({"surfaces": "dm"}, "surfaces 要是清單"),
    ({"surfaces": []}, "surfaces 要是清單"),
    ({"surfaces": ["dm", "group"]}, "不認得 group"),
    ({"surfaces": ["channel"]}, '一定要有 "dm"'),
    ({"surfaces": ["dm", "dm"]}, "重複"),
    ({"data": "everyone"}, "data 只能是"),
    ({"surfaces": ["dm", "channel"], "data": "user"}, "每個人自己的資料不能在頻道"),
    ({"surfaces": ["dm", "channel"], "storage": "vault"}, "照預設推成 user"),
])
def test_bad_scope_rejected_at_gate1(tmp_path, over, needle):
    folder = _write_pack(str(tmp_path / "p"), over, {"pack.py": HELLO_PY})
    with pytest.raises(ManifestError) as e:
        read(folder, strict=True)
    assert needle in str(e.value)


# ── 第 2 關：data 規則 ────────────────────────────────────────────────

def test_data_user_bare_store_refused_with_line_numbers(tmp_path):
    m, report, _h, problems = _gates(tmp_path, {"data": "user"}, {"pack.py": STORE_PY})
    data = [f for f in report.findings if f.kind == "data"]
    assert sorted(f.line for f in data) == [3, 5]                         # update 那行、load 那行；of(u) 那行不算
    assert all(f.blocking for f in data)
    assert any(p.startswith("pack.py:3 ") and "pack.store.of(user)" in p for p in problems)
    assert any(p.startswith("pack.py:5 ") for p in problems)
    assert "❌ 拒裝" in report.format(m)


def test_data_user_bare_store_refused_at_stage(tmp_path):
    src = _write_pack(str(tmp_path / "src"), {"storage": "vault"}, {"pack.py": STORE_PY})   # 沒寫 data：storage＝user
    with pytest.raises(admin.GateRefused) as e:
        admin.stage(_zip_dir(src), str(tmp_path / "data"))
    assert "pack.py:3" in str(e.value) and "pack.py:5" in str(e.value)


def test_data_user_secret_without_user_refused(tmp_path):
    py = ("def install(app, pack):\n"
          "    def go(api, c, u, a):\n"
          "        key = pack.secret('token')\n"
          "        api.send_message(c, 'x')\n"
          "    pack.group.leaf('go', go, 'go')\n")
    raw = {"data": "user", "auth": {"type": "token", "fields": [{"name": "token", "secret": True}]}}
    _m, _r, _h, problems = _gates(tmp_path, raw, {"pack.py": py})
    assert len(problems) == 1 and problems[0].startswith("pack.py:3 ") and "pack.secret(name, user)" in problems[0]


def test_data_user_of_user_and_secret_with_user_pass(tmp_path):
    raw = {"data": "user", "auth": {"type": "token", "fields": [{"name": "token", "secret": True}]}}
    _m, report, _h, problems = _gates(tmp_path, raw, {"pack.py": OF_USER_PY})
    assert problems == [] and not [f for f in report.findings if f.kind == "data"]


def test_data_shared_allows_bare_store(tmp_path):
    _m, _r, _h, problems = _gates(tmp_path, {"data": "shared"}, {"pack.py": STORE_PY})
    assert problems == []


def test_data_none_declared_but_uses_store_refused(tmp_path):
    py = ("def install(app, pack):\n"
          "    p = pack.path('x.txt')\n"
          "    s = pack.store.of(1)\n")
    _m, _r, _h, problems = _gates(tmp_path, {"data": "none"}, {"pack.py": py})
    assert [p.split(" ")[0] for p in problems] == ["pack.py:2", "pack.py:3"]


def test_cli_data_user_refuses_data_dir_with_json_line(tmp_path):
    raw = {"kind": "cli", "data": "user",
           "cli": {"argv": ["{python}", "./t.py"], "env": {"HOME": "{data_dir}/x"},
                   "commands": [{"name": "x", "effect": "READ", "argv": ["x", "--d={user_data_dir}"]}]}}
    folder = _write_pack(str(tmp_path / "p"), raw, {"t.py": "print(1)\n"})
    path = os.path.join(folder, "pack.json")
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    with open(path, "w", encoding="utf-8") as f:                                  # 一行一個 key，好對行號
        json.dump(loaded, f, indent=1)
    lines = open(os.path.join(folder, "pack.json"), encoding="utf-8").read().splitlines()
    expected = next(i for i, line in enumerate(lines, 1) if "{data_dir}" in line)
    _m, report, _h, problems = admin.run_gates(folder)
    data = [f for f in report.findings if f.kind == "data"]
    assert len(data) == 1 and data[0].file == "pack.json" and data[0].line == expected
    assert problems == [f"pack.json:{expected} 資料歸屬（data）不合：{data[0].detail}"]
    assert "{user_data_dir}" in data[0].detail


def test_cli_data_shared_and_moneybook_pass(tmp_path):
    raw = {"kind": "cli", "cli": {"argv": ["{python}", "./t.py"], "env": {"HOME": "{data_dir}/x"},
                                  "commands": [{"name": "x", "effect": "READ", "argv": ["x"]}]}}
    _m, _r, _h, problems = _gates(tmp_path, raw, {"t.py": "print(1)\n"})          # 只用 {data_dir}＝shared
    assert problems == []
    here = os.path.dirname(__file__)
    m, _r, _h, problems = admin.run_gates(os.path.join(here, "fixtures", "moneybook_pack"))
    assert m.data == "user" and problems == []


@pytest.mark.parametrize("folder", ["tests/fixtures/packs/notes", "tests/fixtures/packs/money",   # 下架前內建版本的複本
                                    "connectors/notion",
                                    "connectors/todoist", "connectors/google-calendar",
                                    "connectors/apple-reminders-caldav", "tests/fixtures/moneybook_pack"])
def test_shipped_packs_declare_scope_and_pass_new_scan(folder):
    root = os.path.dirname(os.path.dirname(__file__))
    m, report, _h, problems = admin.run_gates(os.path.join(root, *folder.split("/")))
    assert m.surfaces_declared and m.data_declared
    assert m.surfaces == ["dm"] and m.data == "user"
    assert problems == [] and not [f for f in report.findings if f.kind == "data"]


# ── loader：private_only、shared 的寫入要管理員 ─────────────────────────

def _scoped_pack(base, name, **over):
    py = ("from isdtelekit.core.registry import DANGER, READ, WRITE\n"
          "def install(app, pack):\n"
          "    pack.group.leaf('look', lambda api, c, u, a: api.send_message(c, 'look'), 'look', effect=READ)\n"
          "    pack.group.leaf('put', lambda api, c, u, a: api.send_message(c, 'put'), 'put', effect=WRITE)\n"
          "    pack.group.leaf('wipe', lambda api, c, u, a: api.send_message(c, 'wipe'), 'wipe', effect=DANGER)\n")
    _write_pack(str(base / name), {"name": name, "group": name, "access": "everyone", **over}, {"pack.py": py})


def test_loader_private_only_unless_channel(make_bot, tmp_path, owner):
    base = tmp_path / "extra"
    _scoped_pack(base, "dmonly")
    _scoped_pack(base, "inchan", surfaces=["dm", "channel"], data="none")
    bot = make_bot()
    report = loader.load_all(bot.app, bot.app.config, None, dirs=[str(base)])
    assert {i.name: i.status for i in report.items} == {"dmonly": "loaded", "inchan": "loaded"}
    reg = bot.app.registry
    assert reg.node("dmonly").own.private_only and reg.node("dmonly.look").policy.private_only
    assert not reg.node("inchan.look").policy.private_only
    bot.say(owner, "/dmonly_look", chat_id=-100123)                    # 群組裡：SDK authorize 擋（private）
    assert "look" not in bot.api.texts(-100123)
    bot.say(owner, "/dmonly_look")                                     # 私訊照常
    assert bot.api.texts(owner)[-1] == "look"
    bot.say(owner, "/inchan_look", chat_id=-100123)
    assert bot.api.texts(-100123)[-1] == "look"


def test_shared_write_needs_admin_on_server(make_bot, tmp_path):
    base = tmp_path / "extra"
    _scoped_pack(base, "board", data="shared")
    _scoped_pack(base, "diary", data="user")
    bot = make_bot(raw={"mode": "server"})
    trust_core(bot.app.config.data_dir, str(base / "board"), str(base / "diary"))   # 手放的＝third-party（PERM-8）
    loader.load_all(bot.app, bot.app.config, None, dirs=[str(base)])
    reg = bot.app.registry
    admin_role = max(reg.roles)
    assert reg.node("board.look").policy.role < admin_role
    assert reg.node("board.put").policy.role == admin_role and reg.node("board.wipe").policy.role == admin_role
    assert reg.node("diary.put").policy.role < admin_role              # data=user 不動
    roles = bot.app.users.roles
    bot.app.users.get_or_create(777)
    bot.app.users.set_role(777, roles.MEMBER)
    member = bot.app.users.get_or_create(777)
    assert member.role == roles.MEMBER
    assert not reg.authorize(member, reg.node("board.put"), "typed").allowed
    assert reg.authorize(member, reg.node("board.look"), "typed").allowed


def test_shared_write_untouched_in_personal_mode(make_bot, tmp_path):
    base = tmp_path / "extra"
    _scoped_pack(base, "board", data="shared")
    bot = make_bot()
    loader.load_all(bot.app, bot.app.config, None, dirs=[str(base)])
    assert bot.app.registry.node("board.put").policy.role < max(bot.app.registry.roles)


# ── trust：安裝報告 → packs.lock ──────────────────────────────────────

def _stage(tmp_path, tag, raw, data, files=None):
    src = _write_pack(str(tmp_path / "src" / tag), raw, files or {"pack.py": HELLO_PY})
    return admin.stage(_zip_dir(src), data)


def test_summary_has_scope_and_trust_choices(tmp_path):
    data = str(tmp_path / "data")
    _token, summary = _stage(tmp_path, "a", {"surfaces": ["dm", "channel"], "data": "shared"}, data)
    assert summary["surfaces"] == ["dm", "channel"] and summary["data"] == "shared"
    assert summary["trust_default"] == "third-party"
    assert [c["value"] for c in summary["trust_choices"]] == ["core", "third-party"]
    text = admin.format_summary(summary)
    assert "🧭 在哪裡用：私訊＋頻道（群組）" in text and "大家共用一份" in text and "--trust core" in text
    assert any("頻道" in w for w in summary["warnings"]) and any("管理員" in w for w in summary["warnings"])


@pytest.mark.parametrize("trust,expected", [(None, "third-party"), ("core", "core"), ("third-party", "third-party")])
def test_trust_written_to_lock_and_read_back(tmp_path, trust, expected):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "a", {}, data)
    admin.install_staged(token, data, packs, approved_by=1, via="test", trust=trust)
    record = lock.entry(data, "demo")
    assert record["trust"] == expected and record["surfaces"] == ["dm"] and record["data"] == "none"
    assert lock.trust_of(data, "demo") == expected


def test_bad_trust_refused(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "a", {}, data)
    with pytest.raises(admin.PackAdminError):
        admin.install_staged(token, data, packs, trust="root")
    assert not os.path.exists(os.path.join(packs, "demo"))


def test_old_lock_without_trust_reads_as_third_party(tmp_path):
    data = str(tmp_path / "data")
    os.makedirs(data)
    with open(lock.lock_path(data), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "packs": {"old": {"name": "old", "version": "0.1.0", "files": {}}}}, f)
    assert lock.trust_of(data, "old") == "third-party"
    assert lock.trust_of(data, "nobody") is None


def test_approve_installed_keeps_trust(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "a", {}, data)
    admin.install_staged(token, data, packs, trust="core")
    admin.approve_installed(os.path.join(packs, "demo"), data, approved_by=1)
    assert lock.trust_of(data, "demo") == "core"
    admin.approve_installed(os.path.join(packs, "demo"), data, approved_by=1, trust="third-party")
    assert lock.trust_of(data, "demo") == "third-party"


# ── 升級：surfaces／data 放寬、trust 變更標紅 ───────────────────────────

def _m(tmp_path, tag, raw):
    folder = _write_pack(str(tmp_path / tag), raw, {"pack.py": HELLO_PY})
    with open(os.path.join(folder, "pack.json"), encoding="utf-8") as f:
        return validate(json.load(f), folder, strict=True)


def test_scope_widening_marked_red(tmp_path):
    old = _m(tmp_path, "a", {"data": "none"})
    new = _m(tmp_path, "b", {"surfaces": ["dm", "channel"], "data": "shared"})
    changes = {c["kind"]: c for c in upgrade.diff_manifests(old, new)}
    assert changes["surfaces"]["alert"] and "頻道" in changes["surfaces"]["text"]
    assert changes["data"]["alert"] and "none → shared" in changes["data"]["text"]
    back = {c["kind"]: c for c in upgrade.diff_manifests(new, old)}
    assert not back["surfaces"]["alert"] and not back["data"]["alert"]       # 變窄＝一般字
    assert not [c for c in upgrade.diff_manifests(old, _m(tmp_path, "c", {"data": "none"}))
                if c["kind"] in ("surfaces", "data")]


def test_upgrade_trust_change_red_and_written(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "v1", {}, data)
    admin.install_staged(token, data, packs, trust="third-party")
    token, _s = _stage(tmp_path, "v2", {"version": "0.2.0"}, data)
    upg = upgrade.staged_upgrade(token, data, packs)                       # 還沒選：不標紅、帶裝著的 trust
    assert upg["installed_trust"] == "third-party" and not [c for c in upg["changes"] if c["kind"] == "trust"]
    upg = upgrade.staged_upgrade(token, data, packs, trust="core")
    moved = [c for c in upg["changes"] if c["kind"] == "trust"]
    assert moved and moved[0]["alert"] and "third-party → core" in moved[0]["text"]
    assert "🔴 信任 trust third-party → core" in upgrade.format_upgrade(upg)
    done = upgrade.upgrade_staged(token, data, packs, trust="core")
    assert lock.trust_of(data, "demo") == "core" and done["report"]["trust"] == "core"


def test_upgrade_without_trust_keeps_old(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage(tmp_path, "v1", {}, data)
    admin.install_staged(token, data, packs, trust="core")
    token, _s = _stage(tmp_path, "v2", {"version": "0.2.0", "surfaces": ["dm", "channel"]}, data)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert [c for c in upg["changes"] if c["kind"] == "surfaces"][0]["alert"]
    upgrade.upgrade_staged(token, data, packs)
    assert lock.trust_of(data, "demo") == "core"
    assert lock.entry(data, "demo")["surfaces"] == ["dm", "channel"]


# ── 終端機 --trust、網頁的 trust ────────────────────────────────────────

def test_cli_install_trust_flag(tmp_path, capsys):
    from synox import __main__ as cli
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 42, "data_dir": data}), encoding="utf-8")

    def install(tag, raw, trust):
        src = _write_pack(str(tmp_path / "src" / tag), raw, {"pack.py": HELLO_PY})
        path = tmp_path / f"{tag}.synoxpack"
        path.write_bytes(_zip_dir(src))
        args = cli.argparse.Namespace(config=str(cfg), file=str(path), yes=True, packs_dir=packs,
                                      allow_downgrade=False, trust=trust)
        return cli.cmd_install(args, is_up=lambda port: False)

    assert install("v1", {}, "core") == 0
    out = capsys.readouterr().out
    assert "🧭 在哪裡用：只能私訊" in out and "信任 core" in out
    assert lock.trust_of(data, "demo") == "core"
    assert install("v2", {"version": "0.2.0"}, "third-party") == 0
    assert "🔴 信任 trust core → third-party" in capsys.readouterr().out
    assert lock.trust_of(data, "demo") == "third-party"
    assert install("v3", {"version": "0.3.0"}, None) == 0                  # 沒給＝沿用
    assert lock.trust_of(data, "demo") == "third-party"


def test_web_install_with_trust(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    bot = make_bot(pack_dirs=(str(user_packs),))
    c = Client(ui_of(bot))
    c.login(owner)
    src = _write_pack(str(tmp_path / "src" / "a"), {}, {"pack.py": HELLO_PY})
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip_dir(src))
    assert status == 200, body
    summary = json.loads(body)
    assert summary["trust_default"] == "third-party" and summary["surfaces"] == ["dm"]
    status, data = c.post("/api/packs/install", {"token": summary["token"], "trust": "core"})
    assert status == 200, data
    assert lock.trust_of(bot.app.config.data_dir, "demo") == "core"
