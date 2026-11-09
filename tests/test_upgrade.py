"""SDK P6：pack 升級（同名再裝＝升級、改了什麼、版本檢查）與 `packs rollback`。只用暫存資料夾，不連網、不開埠。"""

import json
import os

import pytest

from synox.packs import admin, lock, upgrade
from synox.packs.manifest import validate

from test_security import HELLO_PY, _write_pack, _zip_dir

TOOL_PY = "import json, sys\nprint(json.dumps({'ok': True}))\n"


def _cli_raw(version="0.1.0", commands=None, **over):
    raw = {"name": "tool", "title": "Tool", "summary": "s", "version": version, "kind": "cli",
           "cli": {"argv": ["{python}", "./tool.py"],
                   "commands": commands if commands is not None else [
                       {"name": "list", "effect": "READ", "argv": ["list"]},
                       {"name": "add", "effect": "READ", "argv": ["add"]}]}}
    raw.update(over)
    return raw


def _stage_cli(tmp_path, tag, raw, data):
    src = _write_pack(str(tmp_path / "src" / tag), raw, {"tool.py": TOOL_PY})
    return admin.stage(_zip_dir(src), data)


def _installed(tmp_path, raw):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = _stage_cli(tmp_path, "v1", raw, data)
    admin.install_staged(token, data, packs, approved_by=1, via="test")
    return data, packs


# ── 版本 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("old,new,status", [
    ("0.1.0", "0.2.0", upgrade.UPGRADE), ("0.9.0", "0.10.0", upgrade.UPGRADE),
    ("1.0.0-beta.2", "1.0.0-beta.10", upgrade.UPGRADE), ("1.0.0-rc.1", "1.0.0", upgrade.UPGRADE),
    ("1.0.0", "1.0.0", upgrade.SAME), ("1.2.0", "1.1.9", upgrade.DOWNGRADE),
    ("1.0.0", "1.0.0-rc.1", upgrade.DOWNGRADE), ("1.0.0", "1.0.0.1", upgrade.INVALID),
    ("01.0.0", "1.0.1", upgrade.INVALID),
])
def test_compare_versions(old, new, status):
    assert upgrade.compare_versions(old, new)[0] == status


# ── 改了什麼 ───────────────────────────────────────────────────────────

def _m(tmp_path, tag, raw, files=None):
    folder = _write_pack(str(tmp_path / tag), raw, files or {"tool.py": TOOL_PY})
    with open(os.path.join(folder, "pack.json"), encoding="utf-8") as f:
        return validate(json.load(f), folder, strict=True)


def test_diff_marks_widening_red(tmp_path):
    old = _m(tmp_path, "a", _cli_raw())
    new = _m(tmp_path, "b", _cli_raw("0.2.0", commands=[
        {"name": "list", "effect": "READ", "argv": ["list"]},
        {"name": "add", "effect": "DANGER", "argv": ["add"]},
        {"name": "sync", "effect": "WRITE", "argv": ["sync"]},
        {"name": "peek", "effect": "READ", "argv": ["peek"]}],
        capabilities=["network"], auth={"type": "token", "fields": [{"name": "k", "env": "TOOL_TOKEN"}]},
        access="everyone"))
    new.cli["argv"] = ["{python}", "./other.py"]
    changes = {c["kind"] + ":" + c["text"]: c["alert"] for c in upgrade.diff_manifests(old, new)}
    alerts = [k for k, v in changes.items() if v]
    assert any("command add 的 effect READ → DANGER" in k for k in alerts)
    assert any("新增 command sync（WRITE）" in k for k in alerts)
    assert not changes[next(k for k in changes if "新增 command peek" in k)]           # 新增 READ：不紅
    assert any(k.startswith("capability_added:") and "network" in k for k in alerts)
    assert any(k.startswith("runtime:") and "cli.argv" in k for k in alerts)
    assert any(k.startswith("auth:") for k in alerts) and any(k.startswith("secrets:") for k in alerts)
    assert any(k.startswith("access:") for k in alerts)
    # 反過來：變窄、移除都不紅
    back = upgrade.diff_manifests(new, old)
    assert any("移除 command sync" in c["text"] and not c["alert"] for c in back)
    assert any("DANGER → READ" in c["text"] and not c["alert"] for c in back)
    assert any(c["kind"] == "capability_removed" and not c["alert"] for c in back)


def test_python_pack_commands_not_comparable(tmp_path):
    old = _m(tmp_path, "a", {"name": "p", "kind": "python"}, {"pack.py": HELLO_PY})
    new = _m(tmp_path, "b", {"name": "p", "kind": "python", "version": "0.2.0"}, {"pack.py": HELLO_PY})
    changes = upgrade.diff_manifests(old, new)
    assert changes and changes[0]["kind"] == "commands" and not changes[0]["alert"]


# ── 升級流程 ───────────────────────────────────────────────────────────

def test_same_name_install_is_upgrade(tmp_path):
    data, packs = _installed(tmp_path, _cli_raw())
    old_lock = lock.entry(data, "tool")
    token, _s = _stage_cli(tmp_path, "v2", _cli_raw("0.2.0", capabilities=["network"]), data)
    with pytest.raises(admin.PackAdminError) as e:                         # 一般安裝不會蓋過去
        admin.install_staged(token, data, packs)
    assert "升級" in str(e.value)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert upg["version_ok"] and upg["installed_version"] == "0.1.0" and upg["alerts"] == 1
    assert "改了 pack.json" in upg["files"]
    text = upgrade.format_upgrade(upg)
    assert "🔴 新增能力 network" in text and "0.1.0 → 0.2.0" in text
    done = upgrade.upgrade_staged(token, data, packs, approved_by=7, via="test", now=1_800_000_000)
    assert done["from"] == "0.1.0" and done["to"] == "0.2.0"
    assert os.path.basename(done["backup"]).startswith("tool-0.1.0-")
    assert json.load(open(os.path.join(packs, "tool", "pack.json"), encoding="utf-8"))["version"] == "0.2.0"
    new_lock = lock.entry(data, "tool")
    assert new_lock["version"] == "0.2.0" and new_lock["approved_by"] == 7
    side = json.load(open(done["backup"] + upgrade.SIDECAR, encoding="utf-8"))
    assert side["lock"] == old_lock and side["reason"] == "upgrade"
    assert not os.path.exists(os.path.join(data, "web_uploads", token))  # 暫存清掉了
    assert lock.verify(data, "tool", os.path.join(packs, "tool"))[0] == lock.LOCKED


@pytest.mark.parametrize("version,needle", [("0.1.0", "版本一樣"), ("0.0.9", "降級")])
def test_same_or_lower_version_refused_unless_downgrade(tmp_path, version, needle):
    data, packs = _installed(tmp_path, _cli_raw())
    token, _s = _stage_cli(tmp_path, "v2", _cli_raw(version), data)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert not upg["version_ok"] and upg["can_force"] and needle in upg["version_message"]
    with pytest.raises(admin.PackAdminError) as e:
        upgrade.upgrade_staged(token, data, packs)
    assert needle in str(e.value)
    assert lock.entry(data, "tool")["version"] == "0.1.0"                  # 沒動
    done = upgrade.upgrade_staged(token, data, packs, allow_downgrade=True)
    assert done["to"] == version


def test_non_semver_new_version_cannot_be_forced(tmp_path):
    data, packs = _installed(tmp_path, _cli_raw())
    token, _s = _stage_cli(tmp_path, "v2", _cli_raw("0.2.0.1"), data)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert upg["version_status"] == upgrade.INVALID and not upg["can_force"]
    with pytest.raises(admin.PackAdminError):
        upgrade.upgrade_staged(token, data, packs, allow_downgrade=True)


def test_upgrade_refuses_files_changed_after_review(tmp_path):
    data, packs = _installed(tmp_path, _cli_raw())
    token, _s = _stage_cli(tmp_path, "v2", _cli_raw("0.2.0"), data)
    with open(os.path.join(data, "web_uploads", token, "pack", "tool.py"), "a", encoding="utf-8") as f:
        f.write("# 偷改\n")
    with pytest.raises(admin.PackAdminError) as e:
        upgrade.upgrade_staged(token, data, packs)
    assert "被改過" in str(e.value)
    assert lock.entry(data, "tool")["version"] == "0.1.0"


def test_upgrade_keeps_data_outside_pack_folder(tmp_path):
    data, packs = _installed(tmp_path, _cli_raw())
    store = os.path.join(data, "tool.json.enc")
    with open(store, "w", encoding="utf-8") as f:
        f.write("secret-bytes")
    token, _s = _stage_cli(tmp_path, "v2", _cli_raw("0.2.0"), data)
    upgrade.upgrade_staged(token, data, packs)
    upgrade.rollback("tool", packs, data)
    assert open(store, encoding="utf-8").read() == "secret-bytes"


# ── rollback ───────────────────────────────────────────────────────────

def test_rollback_restores_previous_version_and_lock(tmp_path):
    data, packs = _installed(tmp_path, _cli_raw())
    v1_lock = lock.entry(data, "tool")
    token, _s = _stage_cli(tmp_path, "v2", _cli_raw("0.2.0"), data)
    upgrade.upgrade_staged(token, data, packs, now=1_800_000_000)
    token, _s = _stage_cli(tmp_path, "v3", _cli_raw("0.3.0"), data)
    upgrade.upgrade_staged(token, data, packs, now=1_800_000_100)
    done = upgrade.rollback("tool", packs, data, now=1_800_000_200)
    assert done["version"] == "0.2.0" and done["lock"] == "restored"
    assert os.path.basename(done["archived"]).startswith("tool-0.3.0-")
    assert lock.verify(data, "tool", os.path.join(packs, "tool"))[0] == lock.LOCKED
    assert not os.path.exists(done["restored_from"] + upgrade.SIDECAR)
    done = upgrade.rollback("tool", packs, data, now=1_800_000_300)         # 再退一次：跳過退回時搬走的 0.3.0
    assert done["version"] == "0.1.0" and done["lock"] == "restored"
    entry = lock.entry(data, "tool")
    assert entry["files"] == v1_lock["files"] and entry["approved_at"] == v1_lock["approved_at"]
    with pytest.raises(admin.PackAdminError) as e:
        upgrade.rollback("tool", packs, data, now=1_800_000_400)
    assert "沒有" in str(e.value)


def test_rollback_after_remove_and_tampered_backup(tmp_path):
    data, packs = _installed(tmp_path, _cli_raw())
    dest = admin.remove("tool", packs, data_dir=data)
    assert os.path.basename(dest).startswith("tool-0.1.0-") and lock.entry(data, "tool") is None
    with open(os.path.join(dest, "tool.py"), "a", encoding="utf-8") as f:   # 在 _removed 裡被改過
        f.write("# x\n")
    done = upgrade.rollback("tool", packs, data)
    assert done["lock"] == "mismatch" and done["archived"] is None
    assert lock.entry(data, "tool") is None and os.path.isdir(os.path.join(packs, "tool"))


def test_rollback_ignores_other_packs_with_prefix(tmp_path):
    packs = str(tmp_path / "packs")
    os.makedirs(os.path.join(packs, "_removed", "tool-box-1.0.0-20261109-120000"))
    _write_pack(os.path.join(packs, "_removed", "tool-box-1.0.0-20261109-120000"), {"name": "tool-box"},
                {"pack.py": HELLO_PY})
    assert upgrade.backups("tool", packs) == []
    assert [b["version"] for b in upgrade.backups("tool-box", packs)] == ["1.0.0"]


# ── CLI ────────────────────────────────────────────────────────────────

def test_cli_install_upgrade_and_rollback(tmp_path, capsys):
    from synox import __main__ as cli
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": 42, "data_dir": data}), encoding="utf-8")

    def install(tag, raw, **kw):
        src = _write_pack(str(tmp_path / "src" / tag), raw, {"tool.py": TOOL_PY})
        path = tmp_path / f"{tag}.synoxpack"
        path.write_bytes(_zip_dir(src))
        args = cli.argparse.Namespace(config=str(cfg), file=str(path), yes=True, packs_dir=packs,
                                      allow_downgrade=kw.get("down", False))
        return cli.cmd_install(args, is_up=lambda port: False)

    assert install("v1", _cli_raw()) == 0
    assert install("v2", _cli_raw("0.2.0", capabilities=["network"])) == 0
    out = capsys.readouterr().out
    assert "這是升級" in out and "🔴 新增能力 network" in out and "升級好了" in out
    assert install("v0", _cli_raw("0.0.5")) == 2
    assert "--allow-downgrade" in capsys.readouterr().out
    assert lock.entry(data, "tool")["version"] == "0.2.0"
    args = cli.argparse.Namespace(config=str(cfg), packs_cmd="rollback", name="tool", packs_dir=packs, dirs=None)
    assert cli.cmd_packs(args) == 0
    assert "退回了" in capsys.readouterr().out and lock.entry(data, "tool")["version"] == "0.1.0"


# ── Web ────────────────────────────────────────────────────────────────

def test_web_upgrade_report_and_confirm(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    bot = make_bot(pack_dirs=(str(user_packs),))
    c = Client(ui_of(bot))
    c.login(owner)

    def upload(tag, raw):
        src = _write_pack(str(tmp_path / "src" / tag), raw, {"tool.py": TOOL_PY})
        status, _h, body = c.raw("POST", "/api/packs/upload", _zip_dir(src))
        assert status == 200, body
        return json.loads(body)

    s1 = upload("v1", _cli_raw())
    assert "upgrade" not in s1
    assert c.post("/api/packs/install", {"token": s1["token"]})[0] == 200
    s2 = upload("v2", _cli_raw("0.2.0", commands=[{"name": "list", "effect": "WRITE", "argv": ["list"]}]))
    upg = s2["upgrade"]
    assert upg["version_ok"] and any("READ → WRITE" in x["text"] and x["alert"] for x in upg["changes"])
    assert any("移除 command add" in x["text"] for x in upg["changes"])
    status, data = c.post("/api/packs/install", {"token": s2["token"]})            # 沒說 upgrade：不蓋
    assert status == 400 and "升級" in data["error"]
    status, data = c.post("/api/packs/install", {"token": s2["token"], "upgrade": True})
    assert status == 200 and data["upgraded"] and data["from"] == "0.1.0" and data["to"] == "0.2.0", data
    assert data["backup"].startswith(os.path.join("userpacks", "_removed", "tool-0.1.0-"))
    s3 = upload("v3", _cli_raw("0.1.5"))
    assert not s3["upgrade"]["version_ok"] and s3["upgrade"]["can_force"]
    status, data = c.post("/api/packs/install", {"token": s3["token"], "upgrade": True})
    assert status == 400 and "降級" in data["error"]
    status, data = c.post("/api/packs/install", {"token": s3["token"], "upgrade": True, "allow_downgrade": True})
    assert status == 200 and data["to"] == "0.1.5"
