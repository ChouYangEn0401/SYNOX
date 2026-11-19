"""核心自己的持久化資料接上版本與升級（synox/datastore/core.py；ADR 0043）：config.json、packs.lock、pack_data.json，
啟動時的升級、doctor、`python -m synox data`、網頁設定頁的 API。全部假資料、tmp_path；不開埠。"""

import json
import os
import types

import pytest

from synox.config import SynoxConfig
from synox.datastore import core, packdata, versioned
from synox.datastore.versioned import TooNewError
from synox.packs import lock
from synox.wizard import logic

pytestmark = pytest.mark.usefixtures("no_sockets")

OWNER = 123456789
LEGACY_CONFIG = {"owner_id": OWNER, "bot_token": "", "llm": {"kind": "fake"}, "vault": {"mode": "file"},
                 "web": {"enabled": False}, "data_dir": "data"}


def write(path, data):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── config.json ───────────────────────────────────────────────────────

def test_legacy_config_gets_a_version_and_reads_the_same(tmp_path):
    path = tmp_path / "config.json"
    write(path, LEGACY_CONFIG)
    before = SynoxConfig.load(str(path), require_token=False)
    out = core.upgrade_config(str(path))
    assert out.action == "upgraded" and (out.before, out.after) == (0, 1)
    after_raw = read(path)
    assert after_raw == {**LEGACY_CONFIG, "schema_version": 1}
    after = SynoxConfig.load(str(path), require_token=False)
    assert (after.owner_id, after.llm, after.data_dir, after.web) == (before.owner_id, before.llm, before.data_dir,
                                                                       before.web)
    assert core.upgrade_config(str(path)).action == "current"


def test_write_config_stamps_current_version(tmp_path):
    path = tmp_path / "config.json"
    logic.write_config(str(path), dict(LEGACY_CONFIG))
    assert read(path)["schema_version"] == core.CONFIG.current


def test_write_config_refuses_config_from_newer_synox(tmp_path):
    """舊程式（這個改動以前）會照樣蓋過去；現在拒絕寫、檔案原封不動。"""
    path = tmp_path / "config.json"
    write(path, {**LEGACY_CONFIG, "schema_version": 99, "future": {"x": 1}})
    original = path.read_bytes()
    cfg = logic.read_existing(str(path))
    cfg["mode"] = "server"
    with pytest.raises(TooNewError):
        logic.write_config(str(path), cfg)
    assert path.read_bytes() == original


# ── packs.lock ────────────────────────────────────────────────────────

def test_legacy_lock_without_version_is_upgraded(tmp_path):
    data = tmp_path / "data"
    write(data / "packs.lock", {"packs": {"hello": {"name": "hello", "files": {}}}})
    out = {o.kind: o for o in core.upgrade_data_dir(str(data))}
    assert out[core.LOCK.label].action == "upgraded"
    assert read(data / "packs.lock") == {"packs": {"hello": {"name": "hello", "files": {}}}, "version": 1}
    assert lock.entry(str(data), "hello") == {"name": "hello", "files": {}}


def test_lock_from_newer_synox_is_not_overwritten(tmp_path):
    from synox.packs.manifest import read as read_manifest
    from test_data_packs import write_pack
    data = tmp_path / "data"
    write(data / "packs.lock", {"version": 2, "packs": {}, "new_thing": True})
    original = (data / "packs.lock").read_bytes()
    m = read_manifest(write_pack(str(tmp_path / "p"), version=None, migrations=None))
    with pytest.raises(TooNewError):
        lock.approve(str(data), m, None, OWNER, via="test")
    assert (data / "packs.lock").read_bytes() == original
    assert core.upgrade_data_dir(str(data))[0].action == "too_new"


def test_pack_data_registry_is_versioned(tmp_path):
    data = tmp_path / "data"
    packdata.record(str(data), "demo", 2)
    assert read(data / "pack_data.json")["schema_version"] == core.PACK_DATA.current
    write(data / "pack_data.json", {"schema_version": 7, "packs": {}})
    with pytest.raises(TooNewError):
        packdata.record(str(data), "demo", 3)


def test_core_chains_have_no_gaps():
    for chain in (core.CONFIG, core.LOCK, core.PACK_DATA):
        assert chain.gaps() == [], chain.kind


# ── 啟動時 ─────────────────────────────────────────────────────────────

def _legacy_install(tmp_path):
    cfg = {**LEGACY_CONFIG, "data_dir": str(tmp_path / "data")}
    write(tmp_path / "config.json", cfg)
    write(tmp_path / "data" / "packs.lock", {"packs": {}})
    return str(tmp_path / "config.json")


def test_start_upgrades_config_then_data(tmp_path, capsys):
    from synox import __main__ as cli
    path = _legacy_install(tmp_path)
    config = cli.load_for_run(path)
    assert config.owner_id == OWNER
    assert read(path)["schema_version"] == 1 and read(tmp_path / "data" / "packs.lock")["version"] == 1
    printed = capsys.readouterr().out
    assert printed.count("🔁") == 2
    cli.load_for_run(path)
    assert "🔁" not in capsys.readouterr().out                    # 第二次啟動：什麼都不用做


def test_start_stops_when_an_upgrade_step_fails_and_keeps_the_file(tmp_path, monkeypatch):
    from synox import __main__ as cli
    from synox.config import ConfigError
    path = _legacy_install(tmp_path)
    original = open(path, "rb").read()

    def boom(cfg):
        raise RuntimeError("broken step")
    monkeypatch.setitem(core.CONFIG.steps, 0, boom)
    with pytest.raises(ConfigError, match="資料升級沒有成功"):
        cli.load_for_run(path)
    assert open(path, "rb").read() == original


def test_start_with_newer_config_warns_and_does_not_write(tmp_path, capsys):
    from synox import __main__ as cli
    path = _legacy_install(tmp_path)
    data = read(path)
    write(path, {**data, "schema_version": 42})
    original = open(path, "rb").read()
    cli.load_for_run(path)
    assert "較新版本" in capsys.readouterr().out
    assert open(path, "rb").read() == original


# ── doctor、python -m synox data、網頁 ─────────────────────────────────

def test_doctor_lists_data_versions(tmp_path):
    from synox import doctor
    path = _legacy_install(tmp_path)
    config = SynoxConfig.load(path, require_token=False)
    lines, bad = doctor.data_lines(config, path)
    text = "\n".join(lines)
    assert "資料版本" in text and "要升級" in text and "0 → 1" in text and bad == 0
    assert read(path).get("schema_version") is None                # doctor 不改檔
    core.upgrade_config(path)
    core.upgrade_data_dir(config.data_dir)
    lines, bad = doctor.data_lines(config, path)
    assert "都是這一版的格式" in lines[0] and bad == 0


def _args(cmd, path, **kw):
    return types.SimpleNamespace(config=path, data_cmd=cmd, dry_run=kw.get("dry_run", False),
                                 json=kw.get("json", False))


def test_data_status_and_dry_run_do_not_write(tmp_path, capsys):
    from synox import __main__ as cli
    path = _legacy_install(tmp_path)
    before = sorted(os.listdir(tmp_path / "data")), open(path, "rb").read()
    assert cli.cmd_data(_args("status", path, json=True)) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["needs_upgrade"] is True and {c["action"] for c in d["core"]} == {"planned", "missing"}
    assert cli.cmd_data(_args("upgrade", path, dry_run=True)) == 0
    assert "0→1" in capsys.readouterr().out
    assert (sorted(os.listdir(tmp_path / "data")), open(path, "rb").read()) == before


def test_data_upgrade_refuses_while_synox_runs(tmp_path, capsys):
    from synox import __main__ as cli
    path = _legacy_install(tmp_path)
    assert cli.cmd_data(_args("upgrade", path), running=lambda c: True) == 2
    assert "正在跑" in capsys.readouterr().out and "schema_version" not in read(path)
    assert cli.cmd_data(_args("upgrade", path), running=lambda c: False) == 0
    assert read(path)["schema_version"] == 1


def test_data_command_is_registered():
    from synox import __main__ as cli
    with pytest.raises(SystemExit) as e:
        cli.main(["data", "--help"])
    assert e.value.code == 0


def test_settings_page_api_shows_versions_owner_only(make_bot, tmp_path, owner):
    from conftest import OTHER_ID
    from isdtelekit.users.roles import BasicRoles
    from test_web import Client
    bot = make_bot(raw={"mode": "server"})
    ui = bot.app.extras["synox_web"]
    c = Client(ui)
    c.login(owner)
    status, d = c.get("/api/settings/data")
    assert status == 200 and isinstance(d["core"], list) and "needs_upgrade" in d
    assert any(r["kind"] == core.LOCK.label for r in d["core"])
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui)
    m.login(OTHER_ID)
    assert m.get("/api/settings/data")[0] == 403


def test_settings_page_has_the_data_card():
    page = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "synox", "web", "static",
                        "app.html")
    text = open(page, encoding="utf-8").read()
    assert 'id="set-data"' in text and "/api/settings/data" in text


def test_backups_live_next_to_the_data(tmp_path):
    path = _legacy_install(tmp_path)
    out = core.upgrade_data_dir(str(tmp_path / "data"))
    backup = [o for o in out if o.action == "upgraded"][0].backup
    assert os.path.dirname(backup) == os.path.join(str(tmp_path / "data"), versioned.BACKUP_DIR)
    assert path
