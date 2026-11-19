"""工具資料的版本與 data-adapter 契約（synox/datastore/packdata.py、ADR 0044）。全部假資料、tmp_path；
cli 工具的遷移不真的開子程序（給假的 run），python 工具的 migrations 是測試自己寫的檔。"""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from synox.datastore import packdata, versioned
from synox.packs import lock, upgrade
from synox.packs.manifest import ManifestError, read
from synox.vault import Vault

OWNER = 123456789

PACK_PY = ("def install(app, pack):\n"
           "    data = pack.store.load({}) or {}\n"
           "    assert data.get('items') is not None and all('title' in i for i in data['items']), data\n"
           "    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, 'hi'), '打招呼', default=True)\n")

MIGRATIONS_V3 = (
    "def migrate_0_to_1(data):\n"
    "    if isinstance(data, list):\n"
    "        data = {'items': data}\n"
    "    return data\n"
    "\n"
    "def migrate_1_to_2(data):\n"
    "    for item in data.get('items', []):\n"
    "        if 'name' in item:\n"
    "            item['title'] = item.pop('name')\n"
    "    return data\n"
    "\n"
    "def migrate_2_to_3(data):\n"
    "    for item in data.get('items', []):\n"
    "        item.setdefault('done', False)\n"
    "    return data\n")


def write_pack(folder, *, version=3, files=("store",), migrations=MIGRATIONS_V3, kind="python", extra=None,
               pack_version="0.3.0", storage="plain"):
    os.makedirs(folder, exist_ok=True)
    raw = {"name": "demo", "title": "Demo", "summary": "s", "version": pack_version, "kind": kind,
           "skill": "SKILL.md", "storage": storage, "data": "user"}
    if version is not None:
        raw["data_schema"] = {"version": version, "files": list(files)}
    if kind == "cli":
        raw.pop("storage")
        raw["cli"] = {"argv": ["{python}", "./tool.py"],
                      "commands": [{"name": "show", "effect": "READ", "argv": ["show"], "summary": "看"}]}
        raw["capabilities"] = ["filesystem:own"]
        with open(os.path.join(folder, "tool.py"), "w", encoding="utf-8") as f:
            f.write("import json\nprint(json.dumps({'ok': True}))\n")
    raw.update(extra or {})
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: demo\ndescription: d\n---\n正文\n")
    if kind == "python":
        with open(os.path.join(folder, "pack.py"), "w", encoding="utf-8") as f:
            f.write(PACK_PY)
    if migrations is not None:
        with open(os.path.join(folder, "migrations.py"), "w", encoding="utf-8") as f:
            f.write(migrations)
    return folder


def config_for(data_dir, mode="personal"):
    return SimpleNamespace(data_dir=str(data_dir), mode=mode, owner_id=OWNER, raw={}, policy={}, packs={})


def store_file(data_dir, data, name="demo.json"):
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, name), "w", encoding="utf-8") as f:
        json.dump(data, f)


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── pack.json 的 data_schema ──────────────────────────────────────────

def test_parse_accepts_store_keys_and_dir():
    spec, bad = packdata.parse({"data_schema": {"version": 2, "files": ["store", "store:history", "dir"]}}, "python")
    assert bad == [] and spec == {"version": 2, "files": ["store", "store:history", "dir"]}


@pytest.mark.parametrize("value,kind,needle", [
    ("x", "python", "要是物件"),
    ({"version": 0, "files": ["store"]}, "python", "version"),
    ({"version": True, "files": ["store"]}, "python", "version"),
    ({"version": 1, "files": []}, "python", "files"),
    ({"version": 1, "files": ["db"]}, "python", "看不懂"),
    ({"version": 1, "files": ["store:Bad Key"]}, "python", "看不懂"),
    ({"version": 1, "files": ["store"]}, "cli", "kind=cli 只能用 dir"),
    ({"version": 1, "files": ["dir"]}, "mcp", "只支援 kind=python 與 kind=cli"),
    ({"version": 1, "files": ["dir"], "extra": 1}, "python", "不認得"),
])
def test_parse_rejects_bad_shapes(value, kind, needle):
    spec, bad = packdata.parse({"data_schema": value}, kind)
    assert spec == {} and any(needle in b for b in bad), bad


def test_no_data_schema_is_fine():
    assert packdata.parse({}, "python") == ({}, [])


def test_manifest_keeps_data_schema_and_existing_data_scope(tmp_path):
    m = read(write_pack(str(tmp_path / "p")))
    assert m.data_schema == {"version": 3, "files": ["store"]}
    assert m.data == "user"                                  # 舊的 data（資料屬於誰）不受影響


# ── 步驟序列的靜態檢查（不執行程式） ─────────────────────────────────────

def test_step_problems_ok_for_full_chain(tmp_path):
    folder = write_pack(str(tmp_path / "p"))
    assert packdata.step_problems({"version": 3, "files": ["store"]}, folder, "python") == ([], [])


def test_step_problems_reports_hole(tmp_path):
    src = MIGRATIONS_V3.replace("def migrate_1_to_2", "def other")
    folder = write_pack(str(tmp_path / "p"), migrations=src)
    problems, _notes = packdata.step_problems({"version": 3, "files": ["store"]}, folder, "python")
    assert any("有洞" in p and "migrate_1_to_2" in p for p in problems)


def test_step_problems_beyond_version_and_skipping_names(tmp_path):
    folder = write_pack(str(tmp_path / "p"), migrations=MIGRATIONS_V3 + "def migrate_3_to_4(d):\n    return d\n"
                        "def migrate_4_to_6(d):\n    return d\n")
    problems, _ = packdata.step_problems({"version": 3, "files": ["store"]}, folder, "python")
    assert any("超過" in p for p in problems) and any("只能升一版" in p for p in problems)


def test_step_problems_no_steps_for_v2(tmp_path):
    folder = write_pack(str(tmp_path / "p"), migrations=None)
    problems, _ = packdata.step_problems({"version": 2, "files": ["store"]}, folder, "python")
    assert any("沒有任何" in p for p in problems)


def test_step_problems_dir_needs_dir_steps(tmp_path):
    folder = write_pack(str(tmp_path / "p"))
    problems, _ = packdata.step_problems({"version": 3, "files": ["store", "dir"]}, folder, "python")
    assert any("_dir" in p for p in problems)


def test_step_problems_note_when_lowest_step_is_not_zero(tmp_path):
    src = "def migrate_1_to_2(d):\n    return d\n"
    folder = write_pack(str(tmp_path / "p"), migrations=src)
    problems, notes = packdata.step_problems({"version": 2, "files": ["store"]}, folder, "python")
    assert problems == [] and any("升不上來" in n for n in notes)


def test_install_gate_rejects_hole_but_load_does_not(tmp_path):
    src = MIGRATIONS_V3.replace("def migrate_1_to_2", "def other")
    folder = write_pack(str(tmp_path / "p"), migrations=src)
    with pytest.raises(ManifestError, match="有洞"):
        read(folder, strict=True)
    assert read(folder).data_schema["version"] == 3        # 載入時不擋在這裡（載入前的升級會停用它並說原因）


def test_sdk_check_blocks_pack_with_hole(tmp_path):
    from synox.sdk import Pack
    src = MIGRATIONS_V3.replace("def migrate_1_to_2", "def other")
    folder = write_pack(str(tmp_path / "p"), migrations=src)
    with pytest.raises(ValueError, match="有洞"):
        Pack.load(folder)


# ── python 工具：載入前升級 ─────────────────────────────────────────────

def test_legacy_data_without_record_runs_from_zero(tmp_path):
    data = tmp_path / "data"
    store_file(str(data), [{"name": "a"}])                   # 宣告 data_schema 以前的舊格式（頂層是清單）
    m = read(write_pack(str(tmp_path / "p")))
    out = packdata.ensure(m, config_for(data))
    assert out.action == "upgraded" and (out.before, out.after) == (0, 3)
    assert load(data / "demo.json") == {"items": [{"title": "a", "done": False}]}
    assert packdata.recorded(str(data), "demo") == 3
    assert versioned.backups_of(str(data / "demo.json"))     # 升級前的備份
    assert packdata.ensure(m, config_for(data)).action == "current"


def test_fresh_install_without_data_is_recorded_as_current(tmp_path):
    data = tmp_path / "data"
    m = read(write_pack(str(tmp_path / "p")))
    out = packdata.ensure(m, config_for(data))
    assert out.action == "current" and packdata.recorded(str(data), "demo") == 3


def test_recorded_middle_version_runs_remaining_steps_only(tmp_path):
    data = tmp_path / "data"
    store_file(str(data), {"items": [{"title": "a"}]})
    packdata.record(str(data), "demo", 2)
    m = read(write_pack(str(tmp_path / "p")))
    out = packdata.ensure(m, config_for(data))
    assert out.steps == ["2→3"] and load(data / "demo.json") == {"items": [{"title": "a", "done": False}]}


def test_missing_step_refuses_and_leaves_data(tmp_path):
    data = tmp_path / "data"
    store_file(str(data), {"items": [{"name": "a"}]})
    packdata.record(str(data), "demo", 1)
    before = (data / "demo.json").read_bytes()
    src = MIGRATIONS_V3.replace("def migrate_1_to_2", "def other")
    m = read(write_pack(str(tmp_path / "p"), migrations=src))
    out = packdata.ensure(m, config_for(data))
    assert out.action == "failed" and "1→2" in out.message
    assert (data / "demo.json").read_bytes() == before and packdata.recorded(str(data), "demo") == 1


def test_failing_step_restores_every_file(tmp_path):
    """兩份 store 檔：第一份升好了、第二份失敗 → 兩份都換回原樣，登記表不變。"""
    data = tmp_path / "data"
    store_file(str(data), {"items": [{"name": "a"}]})
    store_file(str(data), {"items": [{"name": "boom"}]}, name="demo.history.json")
    packdata.record(str(data), "demo", 1)
    src = MIGRATIONS_V3.replace("    for item in data.get('items', []):\n        if 'name' in item:",
                                "    for item in data.get('items', []):\n        if item.get('name') == 'boom':\n"
                                "            raise ValueError('cannot convert')\n        if 'name' in item:")
    m = read(write_pack(str(tmp_path / "p"), files=("store", "store:history"), migrations=src))
    a, b = (data / "demo.json").read_bytes(), (data / "demo.history.json").read_bytes()
    out = packdata.ensure(m, config_for(data))
    assert out.action == "failed" and "還原" in out.message and "cannot convert" in out.message
    assert (data / "demo.json").read_bytes() == a and (data / "demo.history.json").read_bytes() == b
    assert packdata.recorded(str(data), "demo") == 1


def test_data_newer_than_tool_is_refused_untouched(tmp_path):
    data = tmp_path / "data"
    store_file(str(data), {"items": []})
    packdata.record(str(data), "demo", 5)
    before = (data / "demo.json").read_bytes()
    m = read(write_pack(str(tmp_path / "p")))
    out = packdata.ensure(m, config_for(data))
    assert out.action == "too_new" and "較新版本" in out.message
    assert (data / "demo.json").read_bytes() == before and packdata.recorded(str(data), "demo") == 5


def test_dry_run_plans_without_writing(tmp_path):
    data = tmp_path / "data"
    store_file(str(data), [{"name": "a"}])
    before = (data / "demo.json").read_bytes()
    m = read(write_pack(str(tmp_path / "p")))
    out = packdata.ensure(m, config_for(data), dry_run=True)
    assert out.action == "planned" and out.steps == ["0→1", "1→2", "2→3"]
    assert (data / "demo.json").read_bytes() == before
    assert sorted(os.listdir(data)) == ["demo.json"]           # 沒有登記表、鎖、備份


def test_server_mode_upgrades_every_users_vault_file(tmp_path):
    data = tmp_path / "data"
    vault = Vault(b"k" * 32, str(data))
    for uid in (11, 22):
        vault.for_user(uid).save_json("demo", {"items": [{"name": f"u{uid}"}]})
    m = read(write_pack(str(tmp_path / "p"), storage="vault"))
    out = packdata.ensure(m, config_for(data, "server"), vault)
    assert out.action == "upgraded"
    for uid in (11, 22):
        assert vault.for_user(uid).load_json("demo") == {"items": [{"title": f"u{uid}", "done": False}]}


def test_dir_steps_change_the_folder_in_place(tmp_path):
    data = tmp_path / "data"
    folder = data / "packs" / "demo"
    folder.mkdir(parents=True)
    (folder / "a.txt").write_text("x=1", encoding="utf-8")
    src = ("import os\n"
           "def migrate_0_to_1_dir(path):\n"
           "    p = os.path.join(path, 'a.txt')\n"
           "    with open(p, encoding='utf-8') as f:\n"
           "        text = f.read()\n"
           "    with open(p, 'w', encoding='utf-8') as f:\n"
           "        f.write(text.replace('=', ': '))\n")
    m = read(write_pack(str(tmp_path / "p"), version=1, files=("dir",), migrations=src))
    assert packdata.ensure(m, config_for(data)).action == "upgraded"
    assert (folder / "a.txt").read_text(encoding="utf-8") == "x: 1"


def test_migrations_must_match_the_lock(tmp_path):
    data = tmp_path / "data"
    store_file(str(data), [{"name": "a"}])
    folder = write_pack(str(tmp_path / "p"))
    m = read(folder)
    locked = lock.hash_files(folder)
    with open(os.path.join(folder, "migrations.py"), "a", encoding="utf-8") as f:
        f.write("\n# changed after approval\n")
    before = (data / "demo.json").read_bytes()
    out = packdata.ensure(m, config_for(data), locked=locked)
    assert out.action == "failed" and "跟核准時不一樣" in out.message
    assert (data / "demo.json").read_bytes() == before


# ── cli 工具：migrate 子命令（假的 run，不開子程序） ───────────────────────

class FakeRun:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        frm = int(argv[argv.index("--from") + 1])
        folder = argv[argv.index("--data") + 1]
        if os.path.isdir(folder):
            with open(os.path.join(folder, "log.txt"), "a", encoding="utf-8") as f:
                f.write(f"{frm}\n")
        if frm == self.fail_at:
            return subprocess.CompletedProcess(argv, 1, json.dumps({"ok": False, "error": "格式不對"}), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True}), "")


def _cli_setup(tmp_path, version=2):
    data = tmp_path / "data"
    own = data / "demo"
    own.mkdir(parents=True)
    (own / "log.txt").write_text("", encoding="utf-8")
    packdata.record(str(data), "demo", 0)
    m = read(write_pack(str(tmp_path / "p"), kind="cli", version=version, files=("dir",), migrations=None))
    return data, own, m


def test_cli_migrate_called_once_per_step_with_contract_args(tmp_path):
    from synox.config import SynoxConfig
    data, own, m = _cli_setup(tmp_path)
    config = SynoxConfig.from_dict({"owner_id": OWNER, "data_dir": str(data), "vault": {"mode": "file"}},
                                   require_token=False, root=str(tmp_path))
    run = FakeRun()
    out = packdata.ensure(m, config, runner=packdata.cli_runner(m, config, run=run))
    assert out.action == "upgraded" and packdata.recorded(str(data), "demo") == 2
    assert len(run.calls) == 2
    argv, kw = run.calls[0]
    assert argv[-7:] == ["migrate", "--from", "0", "--to", "1", "--data", str(own)]
    assert kw["env"]["SYNOX_MIGRATE"] == "1" and kw["env"]["SYNOX_PACK_NAME"] == "demo"
    assert (own / "log.txt").read_text(encoding="utf-8") == "0\n1\n"


def test_cli_migrate_failure_restores_folder(tmp_path):
    from synox.config import SynoxConfig
    data, own, m = _cli_setup(tmp_path)
    config = SynoxConfig.from_dict({"owner_id": OWNER, "data_dir": str(data), "vault": {"mode": "file"}},
                                   require_token=False, root=str(tmp_path))
    out = packdata.ensure(m, config, runner=packdata.cli_runner(m, config, run=FakeRun(fail_at=1)))
    assert out.action == "failed" and "格式不對" in out.message
    assert (own / "log.txt").read_text(encoding="utf-8") == ""      # 第一步寫的也換回來了
    assert packdata.recorded(str(data), "demo") == 0


def test_cli_migrate_goes_through_the_sandbox_wrap(tmp_path, monkeypatch):
    """沙盒／容器後端：argv 由 box.wrap 包過、--data 換成子程序看得到的路徑（view_for）。"""
    from synox import sandbox
    from synox.config import SynoxConfig
    data, own, m = _cli_setup(tmp_path, version=1)
    config = SynoxConfig.from_dict({"owner_id": OWNER, "data_dir": str(data), "vault": {"mode": "file"}},
                                   require_token=False, root=str(tmp_path))

    class Box:
        name = "fakebox"

        def wrap(self, argv, env, cwd, grants):
            self.grants = grants
            return ["BOX", "--"] + list(argv), env

        def view(self, ph):
            return {**ph, "data_dir": "/data", "user_data_dir": "/data", "pack_dir": "/pack"}
    box = Box()
    monkeypatch.setattr(sandbox, "box_for", lambda cfg, mm: box)
    run = FakeRun()
    assert packdata.ensure(m, config, runner=packdata.cli_runner(m, config, run=run)).action == "upgraded"
    argv = run.calls[0][0]
    assert argv[:2] == ["BOX", "--"] and argv[-1] == "/data/demo"
    assert str(own) in [os.path.normpath(p) for p in box.grants.write]   # 能寫的只有自己的資料夾


def test_cli_without_folder_records_current(tmp_path):
    data = tmp_path / "data"
    m = read(write_pack(str(tmp_path / "p"), kind="cli", version=2, files=("dir",), migrations=None))
    run = FakeRun()
    out = packdata.ensure(m, config_for(data), runner=run)
    assert out.action == "current" and run.calls == []


# ── 工具升級：新版第一次執行之前先升資料 ──────────────────────────────────

def test_loader_upgrades_data_before_new_version_runs(make_bot, tmp_path):
    """舊版工具（資料版本 1、name 欄位）→ 換成新版（data_schema 3＋migrations）→ 載入：
    pack.py 的 install 一開始就讀資料、要求新格式；升級沒先做的話 install 會 assert 失敗。"""
    packs = tmp_path / "packs"
    folder = write_pack(str(packs / "demo"))
    data = tmp_path / "data"
    store_file(str(data), {"items": [{"name": "a"}]})
    packdata.record(str(data), "demo", 1)
    bot = make_bot(pack_dirs=(str(packs),))
    report = bot.app.extras["synox_pack_report"]
    item = next(i for i in report.items if i.name == "demo")
    assert item.status == "loaded", item.detail
    assert load(data / "demo.json") == {"items": [{"title": "a", "done": False}]}
    assert os.path.isdir(folder)


def test_loader_disables_tool_when_data_is_newer(make_bot, tmp_path):
    packs = tmp_path / "packs"
    write_pack(str(packs / "demo"))
    data = tmp_path / "data"
    store_file(str(data), {"items": [{"title": "a"}]})
    packdata.record(str(data), "demo", 9)
    bot = make_bot(pack_dirs=(str(packs),))
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "demo")
    assert item.status == "error" and "較新版本" in item.detail
    assert bot.app.registry.node("demo") is None


def test_upgrade_report_mentions_data_plan(tmp_path):
    data = tmp_path / "data"
    packdata.record(str(data), "demo", 1)
    note = packdata.plan_text({"version": 1, "files": ["store"]}, {"version": 3, "files": ["store"]}, str(data), "demo")
    assert note["alert"] is False and "1 升到 3" in note["text"]
    packdata.record(str(data), "demo", 3)
    back = packdata.plan_text({"version": 3, "files": ["store"]}, {"version": 1, "files": ["store"]}, str(data), "demo")
    assert back["alert"] is True and "停用" in back["text"]
    assert packdata.plan_text({}, {}, str(data / "x"), "other") is None


def test_upgrade_report_includes_data_line(tmp_path):
    old = read(write_pack(str(tmp_path / "old"), version=1, migrations="def migrate_0_to_1(d):\n    return d\n",
                          pack_version="0.1.0"))
    new = read(write_pack(str(tmp_path / "new")))
    data = tmp_path / "data"
    packdata.record(str(data), "demo", 1)
    changes = upgrade.data_changes(old, new, str(data))
    assert changes and "1 升到 3" in changes[0]["text"] and changes[0]["alert"] is False
