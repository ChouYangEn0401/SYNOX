# -*- coding: utf-8 -*-
"""ADR 0041 §5.4 的 S1／S2／S4：帶警告的 pack 在警告下面多一行 SYNOX 自己寫的「這台實況」（只是顯示），
伺服器版把 vendor_no_security_guarantee 當成「一定要沙盒」（跟 T2 同一條路）。沒有警告的 pack 每個地方一個字都不多。
全部在暫存資料夾：不執行第三方程式、不執行 podman／docker（which 是假的）、不開埠、不連網。"""

import argparse
import json
import os
from types import SimpleNamespace

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID

from synox import sandbox
from synox.packs import admin, lock, packwarn
from synox.packs.manifest import read

from test_sandbox import Recording, _cfg, _cli_pack, _which
from test_security import HELLO_PY, _write_pack, _zip_dir

pytestmark = pytest.mark.usefixtures("no_sockets")

VENDOR = "vendor_no_security_guarantee"
WARN = {"code": VENDOR, "text": "官方不保證安全", "advice": "建議在 docker 或 sandbox 執行"}
OTHER_WARN = {"code": "beta_feature", "text": "實驗功能", "advice": ""}
IMAGE = "ghcr.io/example/boxed@sha256:" + "a" * 64
# 不管哪一種狀態，都不能說成「已經在沙盒裡」
OVERCLAIM = ("已在 sandbox", "已在沙盒", "已經在沙盒", "已經在 sandbox", "已隔離", "很安全", "是安全的")


@pytest.fixture(autouse=True)
def _reset():
    yield
    sandbox.set_factory(None)
    sandbox.set_engine_which(None)
    sandbox.set_container_factory(None)


def _set_pack_json(folder, **change):
    path = os.path.join(folder, "pack.json")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    raw.update(change)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    return folder


def _cli(base, name="ext", warnings=(WARN,), container=False):
    folder = _cli_pack(str(base), name, access="member")
    change = {}
    if warnings is not None:
        change["warnings"] = list(warnings)
    if container:
        change["runtime"] = {"container": {"image": IMAGE}}
    return _set_pack_json(folder, **change)


def _py(tmp_path, tag="py", warnings=(WARN,), **over):
    raw = dict(over)
    if warnings is not None:
        raw["warnings"] = list(warnings)
    return _write_pack(str(tmp_path / "src" / tag), raw, {"pack.py": HELLO_PY})


def _choose(data_dir, m, mode):
    lock.approve(str(data_dir), m, None, OWNER_ID, via="web", accepted_warnings=packwarn.codes(m.warnings))
    data = lock.load(str(data_dir))
    data["packs"][m.name]["runtime"] = {"mode": mode}
    with open(lock.lock_path(str(data_dir)), "w", encoding="utf-8") as f:
        json.dump(data, f)


def _no_overclaim(note):
    for word in OVERCLAIM:
        assert word not in note["text"] and word not in note["short"], (word, note)


# ── S1：isolation_note 依實際後端與 pack 宣告判斷 ──────────────────────────

def test_no_warnings_no_note(tmp_path):
    m = read(_cli(tmp_path / "packs", warnings=None))
    assert m.warnings == []
    assert sandbox.isolation_note(_cfg(tmp_path), m) == {}
    assert sandbox.isolation_note(None, m, installing=True) == {}
    assert sandbox.isolation_line({}) == ""


def test_python_pack_says_nothing_can_box_it(tmp_path):
    """S4：kind=python 帶警告 → 紅字「沒有任何後端能把它關起來」；照樣能裝（不拒絕）。"""
    m = read(_py(tmp_path), strict=True)
    sandbox.set_engine_which(_which("podman", "docker"))         # 有引擎也一樣：python 在 SYNOX 程序裡跑
    for installing in (True, False):
        note = sandbox.isolation_note(_cfg(tmp_path), m, installing=installing)
        assert note["state"] == "in_process" and note["isolated"] is False
        assert "沒有任何後端" in note["text"] and "以你的權限直接執行" in note["text"]
        assert "沒有任何後端能把它關起來" in note["short"]
        _no_overclaim(note)


def test_python_pack_still_installs_with_red_line(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, summary = admin.stage(_zip_dir(_py(tmp_path)), data)
    iso = summary["pack_warnings"]["isolation"]
    assert iso["state"] == "in_process"
    text = admin.format_summary(summary)
    assert "ℹ️ SYNOX 查這台的實況：這是 Python 工具" in text and "沒有任何後端" in text
    assert admin.install_staged(token, data, packs, accept_warnings=[VENDOR]) == "demo"   # 不拒裝


def test_cli_no_isolation_on_this_machine(tmp_path):
    m = read(_cli(tmp_path / "packs"))
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which())
    for installing in (True, False):
        note = sandbox.isolation_note(_cfg(tmp_path), m, installing=installing)
        assert note["state"] == "none" and note["isolated"] is False
        assert note["text"].startswith("這台沒有可用的隔離，這個工具會以你的權限直接執行")
        _no_overclaim(note)


def test_cli_jobobject_is_not_isolation(tmp_path):
    m = read(_cli(tmp_path / "packs"))
    sandbox.set_factory(lambda config: sandbox.JobObjectSandbox())
    note = sandbox.isolation_note(_cfg(tmp_path), m)
    assert note["state"] == "none" and not note["isolated"]
    assert "jobobject 只限制記憶體與程序數" in note["text"] and "以你的權限直接執行" in note["text"]


def test_cli_real_host_isolation(tmp_path):
    m = read(_cli(tmp_path / "packs"))
    sandbox.set_factory(lambda config: Recording(isolates=True, name="bwrap"))
    note = sandbox.isolation_note(_cfg(tmp_path, mode="server"), m)
    assert note["state"] == "isolated" and note["isolated"] is True and "bwrap" in note["text"]
    _no_overclaim(note)


def test_windows_personal_default_is_no_isolation(tmp_path):
    """預設設定（auto）在個人版：none。不靠假後端，照 resolve 的規則。"""
    m = read(_cli(tmp_path / "packs"))
    sandbox.set_engine_which(_which())
    assert sandbox.isolation_note(_cfg(tmp_path), m)["state"] == "none"
    assert sandbox.isolation_note(None, m, installing=True)["state"] == "none"


@pytest.mark.parametrize("engines, seen", [(("podman",), "這台已偵測到 podman"), ((), "這台沒偵測到")])
def test_installing_container_offered(tmp_path, engines, seen):
    m = read(_cli(tmp_path / "packs", container=True))
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which(*engines))
    note = sandbox.isolation_note(_cfg(tmp_path), m, installing=True)
    assert note["state"] == "container_offered" and not note["isolated"]
    assert "這個工具有提供容器（需要 podman 或 docker" in note["text"] and seen in note["text"]
    assert "以你的權限直接執行" in note["text"]
    if engines:
        assert "選「用容器」" in note["text"]
    _no_overclaim(note)


def test_installed_container_chosen_and_engine_found(tmp_path):
    m = read(_cli(tmp_path / "packs", container=True))
    cfg = _cfg(tmp_path)
    _choose(tmp_path / "data", m, "container")
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which("docker"))
    note = sandbox.isolation_note(cfg, m)
    assert note["state"] == "container" and note["isolated"] is True
    assert "docker 的容器" in note["text"] and "沒宣告網路就斷網" in note["text"]


def test_installed_container_chosen_but_no_engine(tmp_path):
    m = read(_cli(tmp_path / "packs", container=True))
    cfg = _cfg(tmp_path)
    _choose(tmp_path / "data", m, "container")
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which())
    note = sandbox.isolation_note(cfg, m)
    assert note["state"] == "container_offered" and not note["isolated"]
    assert note["text"].startswith("選了容器，但這台沒偵測到 podman 或 docker") and "以你的權限直接執行" in note["text"]


def test_installed_container_offered_but_host_chosen(tmp_path):
    m = read(_cli(tmp_path / "packs", container=True))
    cfg = _cfg(tmp_path)
    _choose(tmp_path / "data", m, "host")
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which("podman"))
    note = sandbox.isolation_note(cfg, m)
    assert note["state"] == "container_offered" and "目前選「不用容器」" in note["text"]
    assert "packs runtime ext container" in note["text"] and "這台已偵測到 podman" in note["text"]


@pytest.mark.parametrize("kind, registered_only, mcp, state", [
    ("theme", False, {}, "no_code"),
    ("connector", True, {}, "not_run"),
    ("mcp", False, {"transport": "http"}, "remote"),
])
def test_other_kinds(kind, registered_only, mcp, state):
    m = SimpleNamespace(name="x", kind=kind, warnings=[WARN], registered_only=registered_only, mcp=mcp)
    note = sandbox.isolation_note(None, m)
    assert note["state"] == state and not note["isolated"]
    _no_overclaim(note)


# ── S1：每個顯示的地方 ─────────────────────────────────────────────────

def test_install_report_line_under_warnings(tmp_path):
    sandbox.set_engine_which(_which())
    blob = _zip_dir(_cli(tmp_path / "src", "ext"))
    _token, summary = admin.stage(blob, str(tmp_path / "data"), config=_cfg(tmp_path))
    lines = admin.format_summary(summary).splitlines()
    warn_at = next(i for i, line in enumerate(lines) if VENDOR in line)
    assert lines[warn_at + 1].strip().startswith("ℹ️ SYNOX 查這台的實況：這台沒有可用的隔離")
    assert lines[warn_at + 2].strip().startswith("看過、決定要用")


def test_no_warning_install_report_unchanged(tmp_path):
    """沒有警告的 pack：報告的 pack_warnings 沒有 isolation 這一鍵，終端機的字一行都不多。"""
    _token, summary = admin.stage(_zip_dir(_py(tmp_path, warnings=None)), str(tmp_path / "data"),
                                  config=_cfg(tmp_path))
    assert summary["pack_warnings"] == {"items": [], "lines": [], "codes": [], "problems": [], "needs_accept": False}
    assert admin.format_pack_warnings(summary) == []
    assert "SYNOX 查這台的實況" not in admin.format_summary(summary)


def test_cli_install_prints_line(tmp_path, capsys):
    from synox import __main__ as cli
    data = str(tmp_path / "data")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": data}), encoding="utf-8")
    path = tmp_path / "w.synoxpack"
    path.write_bytes(_zip_dir(_py(tmp_path)))
    args = argparse.Namespace(config=str(cfg), file=str(path), yes=True, packs_dir=str(tmp_path / "packs"),
                              allow_downgrade=False, trust=None, accept_warning=None)
    assert cli.cmd_install(args, is_up=lambda port: False) == 2
    out = capsys.readouterr().out
    assert "SYNOX 查這台的實況：這是 Python 工具" in out


def test_packs_status_and_lock_print_line(tmp_path, capsys):
    from synox import __main__ as cli
    data = str(tmp_path / "data")
    packs = tmp_path / "packs"
    warned = _cli(packs, "ext")
    _cli(packs, "plain", warnings=None)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": data}), encoding="utf-8")
    sandbox.set_engine_which(_which())
    ns = argparse.Namespace(config=str(cfg), packs_cmd="lock", approve="ext", dirs=[str(packs)], packs_dir="",
                            trust=None, trust_publisher=None, runtime=None, accept_warning=[VENDOR])
    assert cli.cmd_packs(ns) == 0
    assert "SYNOX 查這台的實況：這台沒有可用的隔離" in capsys.readouterr().out
    lock.approve(data, read(str(packs / "plain")), None, OWNER_ID, via="test", folder=str(packs / "plain"))
    ns = argparse.Namespace(config=str(cfg), packs_cmd="status", dirs=[str(packs)], packs_dir="")
    assert cli.cmd_packs(ns) == 0
    out = capsys.readouterr().out
    assert out.count("SYNOX 查這台的實況") == 1                                  # 只有帶警告的那一個
    block = out.split("plain")[0]
    assert "實況" in block and os.path.basename(warned) in block


def test_settings_api_rows(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    data = str(tmp_path / "data")
    base = str(tmp_path / "packs")
    warned = _cli(base, "ext")
    plain = _cli(base, "plain", warnings=None)
    lock.approve(data, read(warned), None, OWNER_ID, via="test", folder=warned, accepted_warnings=[VENDOR])
    lock.approve(data, read(plain), None, OWNER_ID, via="test", folder=plain)
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which())
    bot = make_bot(pack_dirs=(base,))
    c = Client(ui_of(bot))
    c.login(owner)
    _status, settings = c.get("/api/settings")
    rows = {p["name"]: p for p in settings["packs"]}
    assert rows["ext"]["isolation"]["state"] == "none"
    assert rows["ext"]["isolation"]["text"].startswith("這台沒有可用的隔離")
    assert "isolation" not in rows["plain"]                                    # 沒有警告：一個鍵都不多


def test_web_upload_report_has_line(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    bot = make_bot(pack_dirs=(str(user_packs),))
    c = Client(ui_of(bot))
    c.login(owner)
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip_dir(_py(tmp_path)))
    assert status == 200, body
    assert json.loads(body)["pack_warnings"]["isolation"]["state"] == "in_process"
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip_dir(_py(tmp_path, "plain", warnings=None,
                                                                          name="plain", group="plain")))
    assert status == 200, body
    assert "isolation" not in json.loads(body)["pack_warnings"]


def test_web_page_renders_line():
    page = os.path.join(os.path.dirname(sandbox.__file__), "web", "static", "app.html")
    with open(page, encoding="utf-8") as f:
        html = f.read()
    assert html.count("ℹ️ SYNOX 查這台的實況：") == 2                            # 安裝報告＋設定頁
    assert "pw.isolation" in html and "p.isolation" in html


def test_doctor_line(tmp_path):
    from synox import doctor
    data = str(tmp_path / "data")
    warned = _py(tmp_path)
    plain = _py(tmp_path, "plain", warnings=None, name="plain", group="plain")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": data, "llm": {"kind": "none"},
                               "packs": {"dirs": [os.path.dirname(warned)]}}), encoding="utf-8")
    lock.approve(data, read(warned), None, OWNER_ID, via="test", folder=warned, accepted_warnings=[VENDOR])
    lock.approve(data, read(plain), None, OWNER_ID, via="test", folder=plain)
    lines = []
    try:
        doctor.run(offline=True, config_path=str(cfg), out=lines.append)
    except SystemExit:
        pass
    text = "\n".join(lines)
    assert text.count("SYNOX 查這台的實況") == 1 and "這是 Python 工具" in text


# ── S1：給 AI 的清單（短句） ───────────────────────────────────────────

def test_agent_entry_line_and_file():
    from synox.agent.index import AgentIndex, Entry, _entry_dict
    warned = Entry(name="w", title="🔎 搜尋", index="說明", warnings=[WARN], isolation="沒有隔離，以使用者的權限執行")
    assert warned.line().startswith(f"- 🔎 搜尋〔⚠️警告 {VENDOR}") and "〔實況：沒有隔離，以使用者的權限執行〕" in warned.line()
    assert "〔實況：" in warned.line(0)                                          # 縮到最短也留著
    plain = Entry(name="p", title="工具", index="說明")
    stray = Entry(name="p", title="工具", index="說明", isolation="不該出現")     # 沒有警告：不顯示
    assert plain.line() == stray.line() == "- 工具：說明"
    assert "isolation" not in _entry_dict(plain) and _entry_dict(warned)["isolation"]
    assert "isolation" not in json.dumps(AgentIndex([plain]).to_dict())


def test_agent_index_built_with_note(make_bot, tmp_path):
    from synox.agent import index
    from synox.packs import loader
    data = str(tmp_path / "data")
    folder = _py(tmp_path)
    lock.approve(data, read(folder), None, OWNER_ID, via="test", folder=folder, accepted_warnings=[VENDOR])
    bot = make_bot(pack_dirs=loader.PACK_DIRS + (os.path.dirname(folder),))
    entry = index.current(bot.app).get("demo")
    assert entry.isolation.startswith("Python 工具，沒有任何後端能把它關起來")
    block = index.prompt_block(bot.app)
    assert "〔實況：Python 工具" in block and packwarn.AGENT_RULE in block
    with open(os.path.join(data, index.INDEX_FILE), encoding="utf-8") as f:
        stored = {e["name"]: e for e in json.load(f)["entries"]}
    assert stored["demo"]["isolation"] and "isolation" not in stored["money"]


# ── S2：伺服器版把「官方不保證安全」當成一定要沙盒 ─────────────────────────

def _sees(bot, group):
    reg = bot.app.registry
    return lambda tg_id: reg.visible(bot.app.users.get_or_create(tg_id), reg.node(group))


def test_required_and_reason_for_vendor_cli(tmp_path):
    base = tmp_path / "packs"
    warned = read(_cli(base, "ext"))
    other = read(_cli(base, "beta", warnings=(OTHER_WARN,)))
    plain = read(_cli(base, "plain", warnings=None))
    # trust=core（出廠／擁有者選 core）：沒警告就不需要沙盒
    for m in (warned, other, plain):
        lock.approve(str(tmp_path / "data"), m, None, OWNER_ID, via="test", trust="core",
                     accepted_warnings=packwarn.codes(m.warnings) or None)
    server = _cfg(tmp_path, mode="server")
    personal = _cfg(tmp_path)
    assert sandbox.required(server, warned) and sandbox.required(personal, warned)
    assert not sandbox.required(server, plain) and not sandbox.required(server, other)   # 只看這一個 code
    reason = sandbox.restricted_reason(server, warned, sandbox.NoneSandbox())
    assert "只對擁有者開放" in reason and VENDOR in reason and "none" in reason
    assert sandbox.restricted_reason(server, warned, sandbox.JobObjectSandbox())          # jobobject 不算隔離
    assert sandbox.restricted_reason(server, warned, Recording(isolates=True, name="bwrap")) == ""
    assert sandbox.restricted_reason(personal, warned, sandbox.NoneSandbox()) == ""       # 個人版不變
    assert sandbox.restricted_reason(server, plain, sandbox.NoneSandbox()) == ""
    server_none = _cfg(tmp_path, mode="server", policy={"sandbox": {"required_for": "none"}})
    assert sandbox.restricted_reason(server_none, warned, sandbox.NoneSandbox())          # 不管 required_for


def test_vendor_cli_with_container_is_open_to_members(tmp_path):
    m = read(_cli(tmp_path / "packs", "ext", container=True))
    _choose(tmp_path / "data", m, "container")
    server = _cfg(tmp_path, mode="server")
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which("podman"))
    assert sandbox.restricted_reason(server, m) == ""
    sandbox.set_engine_which(_which())
    assert "找不到 podman 或 docker" in sandbox.restricted_reason(server, m)


def test_vendor_python_pack_owner_only_on_server(tmp_path):
    m = read(_py(tmp_path), strict=True)
    server = _cfg(tmp_path, mode="server")
    reason = sandbox.restricted_reason(server, m, Recording(isolates=True, name="bwrap"))
    assert "只對擁有者開放" in reason and "python 工具" in reason
    assert sandbox.restricted_reason(_cfg(tmp_path), m) == ""
    assert sandbox.restricted_reason(server, read(_py(tmp_path, "b", warnings=(OTHER_WARN,)))) == ""


def test_server_loader_hides_vendor_pack_from_members(make_bot, tmp_path):
    base = str(tmp_path / "packs")
    warned = _cli(base, "ext")
    plain = _cli(base, "plain", warnings=None)
    data = str(tmp_path / "data")
    lock.approve(data, read(warned), None, OWNER_ID, via="test", folder=warned, trust="core",
                 accepted_warnings=[VENDOR])
    lock.approve(data, read(plain), None, OWNER_ID, via="test", folder=plain, trust="core")
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    bot = make_bot(raw={"mode": "server"}, pack_dirs=(base,))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    items = {i.name: i for i in bot.app.extras["synox_pack_report"].items}
    assert items["ext"].status == "loaded" and "只對擁有者開放" in items["ext"].detail
    sees = _sees(bot, "ext")
    assert sees(OWNER_ID) and not sees(OTHER_ID)
    plain_sees = _sees(bot, "plain")
    assert plain_sees(OTHER_ID) and items["plain"].detail == ""                   # 沒警告、core：跟以前一樣
    bot.say(OTHER_ID, "/ext text=hi")
    assert "argv=show hi" not in (bot.last(OTHER_ID) or "")                       # 成員叫不到


def test_server_loader_vendor_pack_open_with_real_isolation(make_bot, tmp_path):
    base = str(tmp_path / "packs")
    warned = _cli(base, "ext")
    lock.approve(str(tmp_path / "data"), read(warned), None, OWNER_ID, via="test", folder=warned, trust="core",
                 accepted_warnings=[VENDOR])
    sandbox.set_factory(lambda config: Recording(isolates=True, name="bwrap"))
    bot = make_bot(raw={"mode": "server"}, pack_dirs=(base,))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    assert _sees(bot, "ext")(OTHER_ID)


def test_personal_loader_unchanged(make_bot, tmp_path):
    base = str(tmp_path / "packs")
    warned = _cli(base, "ext")
    lock.approve(str(tmp_path / "data"), read(warned), None, OWNER_ID, via="test", folder=warned,
                 accepted_warnings=[VENDOR])
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    bot = make_bot(pack_dirs=(base,))
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "ext")
    assert item.status == "loaded" and "只對擁有者開放" not in item.detail
    assert item.isolation["state"] == "none"                                     # 只多了顯示用的實況
