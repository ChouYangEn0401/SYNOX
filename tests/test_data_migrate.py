"""資料版本與逐版升級的框架（synox/datastore/versioned.py、migrate.py；ADR 0043）。全部用假資料、tmp_path。"""

import json
import os
import sqlite3
import subprocess
import sys
import threading

import pytest

from synox.datastore import migrate, versioned
from synox.datastore.migrate import Chain, run_steps, upgrade_file, upgrade_sidecar_file, upgrade_sqlite
from synox.datastore.versioned import DataError, GapError, StepError, TooNewError

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def make_chain(calls=None, current=3):
    """0→1 補 items、1→2 把 name 改成 title、2→3 每筆加 done=False。calls 記每一步跑了幾次。"""
    calls = calls if calls is not None else []
    chain = Chain("notes.json", current=current)

    @chain.step(0)
    def _0(d):
        calls.append(0)
        d.setdefault("items", [])
        return d

    @chain.step(1)
    def _1(d):
        calls.append(1)
        for item in d["items"]:
            if "name" in item:
                item["title"] = item.pop("name")
        return d

    if current >= 3:
        @chain.step(2)
        def _2(d):
            calls.append(2)
            for item in d["items"]:
                item.setdefault("done", False)
            return d
    return chain


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── 版本號 ─────────────────────────────────────────────────────────────

def test_missing_version_is_legacy_zero():
    assert versioned.json_version({"a": 1}) == 0
    assert versioned.json_version({"schema_version": 4}) == 4
    assert versioned.json_version({"version": 2}, key="version") == 2


@pytest.mark.parametrize("bad", [True, "2", 1.5, -1, None])
def test_bad_version_values_rejected(bad):
    with pytest.raises(DataError):
        versioned.json_version({"schema_version": bad})


def test_top_level_list_cannot_carry_version():
    with pytest.raises(DataError):
        versioned.json_version([1, 2])


# ── 逐版連續升級（記憶體） ───────────────────────────────────────────────

def test_chain_runs_every_step_in_order_from_zero():
    calls = []
    out = run_steps(make_chain(calls), {"items": [{"name": "a"}]}, 0)
    assert calls == [0, 1, 2]
    assert out == {"items": [{"title": "a", "done": False}], "schema_version": 3}


def test_single_step_from_middle_version():
    calls = []
    out = run_steps(make_chain(calls), {"schema_version": 2, "items": [{"title": "a"}]}, 2)
    assert calls == [2]
    assert out["schema_version"] == 3 and out["items"][0]["done"] is False


def test_gap_in_chain_is_refused_not_skipped():
    chain = Chain("x", current=3)
    chain.step(0)(lambda d: d)
    chain.step(2)(lambda d: d)
    assert chain.gaps() == [1]
    with pytest.raises(GapError) as e:
        chain.plan(0)
    assert "1→2" in str(e.value)
    assert chain.plan(2) == [2]                      # 洞之後的版本照樣能升


def test_too_new_is_refused():
    with pytest.raises(TooNewError) as e:
        make_chain().plan(4)
    assert "較新版本" in str(e.value)


def test_steps_get_a_copy_and_do_not_mutate_input():
    data = {"items": [{"name": "a"}]}
    run_steps(make_chain(), data, 0)
    assert data == {"items": [{"name": "a"}]}


def test_step_returning_none_is_an_error():
    chain = Chain("x", current=1)
    chain.step(0)(lambda d: None)
    with pytest.raises(StepError):
        run_steps(chain, {}, 0)


def test_register_twice_or_beyond_current_is_a_bug():
    chain = Chain("x", current=1)
    chain.step(0)(lambda d: d)
    with pytest.raises(ValueError):
        chain.step(0)(lambda d: d)
    with pytest.raises(ValueError):
        chain.step(1)(lambda d: d)


def test_upgrade_data_stamps_current_version_and_refuses_newer():
    chain = make_chain()
    assert chain.upgrade_data({"items": []})["schema_version"] == 3
    same = {"schema_version": 3, "items": []}
    assert chain.upgrade_data(same) is same
    with pytest.raises(TooNewError):
        chain.upgrade_data({"schema_version": 9})


def test_each_step_is_idempotent():
    """步驟要冪等：已經是新格式的內容再跑一次，結果一樣（中斷後重跑同一步不會壞）。"""
    chain = make_chain()
    data = {"items": [{"name": "a"}, {"title": "b"}]}
    for v in range(chain.current):
        once = chain.steps[v](json.loads(json.dumps(data)))
        twice = chain.steps[v](json.loads(json.dumps(once)))
        assert once == twice
        data = once


# ── 檔案：連續升級、備份、失敗還原 ────────────────────────────────────────

def test_upgrade_file_0_to_3_writes_once_and_backs_up_the_original(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"items": [{"name": "a"}]})
    original = path.read_bytes()
    calls = []
    out = upgrade_file(str(path), make_chain(calls), now=1_700_000_000)
    assert out.action == "upgraded" and (out.before, out.after) == (0, 3)
    assert out.steps == ["0→1", "1→2", "2→3"]
    assert calls == [0, 1, 2]
    assert read_json(path) == {"items": [{"title": "a", "done": False}], "schema_version": 3}
    assert os.path.basename(out.backup).startswith("notes.json.v0.")
    assert open(out.backup, "rb").read() == original              # 備份是升級前的原樣
    assert not os.path.exists(str(path) + versioned.LOCK_SUFFIX)    # 鎖放掉了


def test_rerun_on_current_file_does_nothing(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    upgrade_file(str(path), make_chain())
    before = path.read_bytes()
    calls = []
    out = upgrade_file(str(path), make_chain(calls))
    assert out.action == "current" and calls == [] and path.read_bytes() == before


def test_failed_step_leaves_original_untouched(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"items": [{"name": "a"}]})
    original = path.read_bytes()
    chain = make_chain()

    def boom(d):
        raise KeyError("oops")
    chain.steps[2] = boom
    out = upgrade_file(str(path), chain)
    assert out.action == "failed" and not out.ok
    assert "2 升到 3" in out.message
    assert path.read_bytes() == original
    assert not os.path.isdir(tmp_path / versioned.BACKUP_DIR)       # 失敗在寫之前：連備份都不用做


def test_failure_after_write_restores_backup(tmp_path, monkeypatch):
    """寫回之後重讀驗證失敗（例如寫出看不懂的東西）→ 從備份換回原檔。"""
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    original = path.read_bytes()

    class BadCodec(migrate.JsonCodec):
        def encode(self, data):
            return b"{not json"
    out = upgrade_file(str(path), make_chain(), BadCodec())
    assert out.action == "failed"
    assert path.read_bytes() == original


def test_gap_in_file_upgrade_refused_and_file_untouched(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    original = path.read_bytes()
    chain = make_chain()
    del chain.steps[1]
    out = upgrade_file(str(path), chain)
    assert out.action == "failed" and "1→2" in out.message
    assert path.read_bytes() == original


def test_downgrade_refused_and_file_untouched(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"schema_version": 7, "items": []})
    original = path.read_bytes()
    out = upgrade_file(str(path), make_chain())
    assert out.action == "too_new" and out.before == 7
    assert "請升級 SYNOX" in out.message
    assert path.read_bytes() == original
    assert not os.path.isdir(tmp_path / versioned.BACKUP_DIR)


def test_missing_file_is_not_created(tmp_path):
    out = upgrade_file(str(tmp_path / "nope.json"), make_chain())
    assert out.action == "missing" and not os.path.exists(tmp_path / "nope.json")


def test_dry_run_reports_plan_without_touching_anything(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"schema_version": 1, "items": []})
    original = path.read_bytes()
    out = upgrade_file(str(path), make_chain(), dry_run=True)
    assert out.action == "planned" and out.steps == ["1→2", "2→3"] and out.needs_upgrade
    assert path.read_bytes() == original
    assert sorted(os.listdir(tmp_path)) == ["notes.json"]          # 沒有鎖檔、沒有備份


def test_vault_files_are_upgraded_and_stay_encrypted(tmp_path):
    from synox.vault import Vault
    vault = Vault(b"k" * 32, str(tmp_path))
    vault.save_json("notes", {"items": [{"name": "a"}]})
    path = vault.path("notes")
    out = upgrade_file(path, make_chain(), migrate.VaultCodec(vault))
    assert out.action == "upgraded"
    assert b"title" not in open(path, "rb").read()                # 還是密文
    assert vault.load_json("notes")["items"] == [{"title": "a", "done": False}]


# ── 原子寫入 ───────────────────────────────────────────────────────────

def test_atomic_write_interrupted_keeps_old_file_and_no_temp(tmp_path, monkeypatch):
    path = tmp_path / "a.json"
    path.write_bytes(b'{"old": true}')

    def crash(src, dst):
        raise OSError("power cut")
    monkeypatch.setattr(versioned.os, "replace", crash)
    with pytest.raises(OSError):
        versioned.atomic_write_bytes(str(path), b'{"new": true}')
    monkeypatch.undo()
    assert path.read_bytes() == b'{"old": true}'
    assert os.listdir(tmp_path) == ["a.json"]                     # 暫存檔清掉了


def test_upgrade_interrupted_during_write_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    original = path.read_bytes()
    real = versioned.os.replace

    def crash(src, dst):
        if str(dst) == str(path) and ".tmp" in str(src):
            raise OSError("killed")
        return real(src, dst)
    monkeypatch.setattr(versioned.os, "replace", crash)
    out = upgrade_file(str(path), make_chain())
    monkeypatch.undo()
    assert out.action == "failed"
    assert path.read_bytes() == original
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]


# ── 檔案鎖 ─────────────────────────────────────────────────────────────

def test_two_threads_upgrade_once(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    calls = []
    lock = threading.Lock()
    chain = make_chain()
    slow = chain.steps[0]

    def counted(d):
        with lock:
            calls.append(0)
        threading.Event().wait(0.2)                   # 讓另一條執行緒一定撞到鎖
        return slow(d)
    chain.steps[0] = counted
    results = []
    threads = [threading.Thread(target=lambda: results.append(upgrade_file(str(path), chain))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert calls == [0]
    assert sorted(r.action for r in results) == ["current", "upgraded"]
    assert read_json(path)["schema_version"] == 3


def test_lock_held_by_another_process_times_out_without_touching(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    original = path.read_bytes()
    with open(str(path) + versioned.LOCK_SUFFIX, "w") as f:      # 活著的程序（就是自己）拿著鎖
        json.dump({"pid": os.getpid(), "at": 9e12}, f)
    out = upgrade_file(str(path), make_chain(), lock_wait=0.2)
    assert out.action == "failed" and "另一個程序" in out.message
    assert path.read_bytes() == original


def test_stale_lock_from_dead_process_is_cleared(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    with open(str(path) + versioned.LOCK_SUFFIX, "w") as f:
        json.dump({"pid": 999999999, "at": 1}, f)                 # 很久以前、程序早就不在
    out = upgrade_file(str(path), make_chain(), lock_wait=0.2)
    assert out.action == "upgraded"


CHILD = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
from synox.datastore.migrate import Chain, upgrade_file
chain = Chain("notes.json", current=1)
@chain.step(0)
def _0(d):
    with open(sys.argv[3], "a") as f:
        f.write("ran\n")
    time.sleep(0.5)
    return d
print(upgrade_file(sys.argv[2], chain).action)
"""


def test_two_processes_upgrade_once(tmp_path):
    """兩個真的程序同時升級同一份檔：只有一個動手，另一個等完發現已經是最新。"""
    path = tmp_path / "notes.json"
    write_json(path, {"items": []})
    marker = tmp_path / "ran.txt"
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    procs = [subprocess.Popen([sys.executable, "-I", str(script), SRC, str(path), str(marker)],
                              stdout=subprocess.PIPE, text=True, env=env) for _ in range(2)]
    outs = sorted(p.communicate(timeout=60)[0].strip() for p in procs)
    assert outs == ["current", "upgraded"]
    assert marker.read_text().count("ran") == 1


# ── 備份保留策略 ───────────────────────────────────────────────────────

def test_backup_retention_keeps_newest_n(tmp_path):
    path = tmp_path / "notes.json"
    write_json(path, {})
    made = [versioned.make_backup(str(path), v, keep=3, now=1_700_000_000 + v) for v in range(5)]
    kept = versioned.backups_of(str(path))
    assert len(kept) == 3
    assert kept == list(reversed(made[2:]))                      # 新的在前，最舊的兩份刪掉


def test_backup_dir_ignores_other_files_with_same_prefix(tmp_path):
    a, b = tmp_path / "notes.json", tmp_path / "notes.json.enc"
    write_json(a, {})
    write_json(b, {})
    versioned.make_backup(str(a), 0, now=1)
    versioned.make_backup(str(b), 0, now=2)
    assert len(versioned.backups_of(str(a))) == 1 and len(versioned.backups_of(str(b))) == 1


# ── 其他格式：旁檔 .schema、SQLite、資料夾 ───────────────────────────────

def test_sidecar_format_upgrades_text_and_records_version(tmp_path):
    path = tmp_path / "rules.txt"
    path.write_bytes(b"a=1\n")
    chain = Chain("rules.txt", current=2)
    chain.step(0)(lambda b: b if b.startswith(b"# rules") else b"# rules\n" + b)
    chain.step(1)(lambda b: b.replace(b"=", b": "))
    out = upgrade_sidecar_file(str(path), chain)
    assert out.action == "upgraded" and path.read_bytes() == b"# rules\na: 1\n"
    assert versioned.sidecar_version(str(path)) == 2
    assert upgrade_sidecar_file(str(path), chain).action == "current"


def test_sidecar_failure_restores_data_and_keeps_old_version(tmp_path):
    path = tmp_path / "rules.txt"
    path.write_bytes(b"a=1\n")
    versioned.write_sidecar(str(path), 1)
    chain = Chain("rules.txt", current=2)
    chain.step(0)(lambda b: b)

    def boom(b):
        raise ValueError("bad line")
    chain.step(1)(boom)
    out = upgrade_sidecar_file(str(path), chain)
    assert out.action == "failed" and path.read_bytes() == b"a=1\n"
    assert versioned.sidecar_version(str(path)) == 1


def _db(path, version=0):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE notes (name TEXT)")
    conn.execute("INSERT INTO notes VALUES ('a')")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()


def _sqlite_chain():
    chain = Chain("notes.db", current=2)
    chain.step(0)(lambda c: c.execute("ALTER TABLE notes ADD COLUMN done INTEGER DEFAULT 0"))
    chain.step(1)(lambda c: c.execute("ALTER TABLE notes RENAME COLUMN name TO title"))
    return chain


def test_sqlite_user_version_upgrade(tmp_path):
    path = str(tmp_path / "notes.db")
    _db(path)
    out = upgrade_sqlite(path, _sqlite_chain())
    assert out.action == "upgraded" and out.after == 2
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT title, done FROM notes").fetchall() == [("a", 0)]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    conn.close()


def test_sqlite_failed_step_rolls_back_everything(tmp_path):
    path = str(tmp_path / "notes.db")
    _db(path)
    chain = _sqlite_chain()

    def boom(c):
        c.execute("ALTER TABLE notes RENAME COLUMN name TO title")
        raise RuntimeError("half way")
    chain.steps[1] = boom
    out = upgrade_sqlite(path, chain)
    assert out.action == "failed"
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(notes)")]
    assert cols == ["name"] and conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()


def test_sqlite_too_new_untouched(tmp_path):
    path = str(tmp_path / "notes.db")
    _db(path, version=5)
    assert upgrade_sqlite(path, _sqlite_chain()).action == "too_new"


def test_folder_upgrade_restores_on_failure(tmp_path):
    folder = tmp_path / "tool"
    folder.mkdir()
    (folder / "a.txt").write_text("old", encoding="utf-8")

    def step(v, path):
        with open(os.path.join(path, "a.txt"), "w", encoding="utf-8") as f:
            f.write(f"step{v}")
        if v == 1:
            raise RuntimeError("bad")
    with pytest.raises(StepError):
        migrate.upgrade_folder(str(folder), "tool", 0, [0, 1], step)
    assert (folder / "a.txt").read_text(encoding="utf-8") == "old"
