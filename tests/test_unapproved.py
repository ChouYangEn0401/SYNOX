# -*- coding: utf-8 -*-
"""ADR 0027 §4（S9）：沒有經過安裝頁（沒有 packs.lock 那一筆）的 pack 不載入；「送去安裝頁檢查」（packs/adopt.py）；
packs.dirs 的開發者路徑（packs lock --approve）。pack 都是 tmp 裡的小 python pack，不連網、不開埠、不跑子程序。"""
import json
import os
import sys

import pytest

from conftest import OWNER_ID

from synox.packs import admin, adopt, loader, lock, upgrade
from synox.packs.manifest import read

pytestmark = pytest.mark.usefixtures("no_sockets")

RUN_PY = r'''
from isdtelekit.core.registry import READ

def install(app, pack):
    def run(api, chat_id, user, args):
        api.send_message(chat_id, "跑了 " + pack.name)
    pack.group.leaf("run", run, "跑一下", effect=READ, default=True)
'''
NET_PY = "import socket\n\ndef install(app, pack):\n    pack.group.leaf('run', lambda *a: None, 'x')\n"
NOTICE = "不是從安裝頁裝的"


def _pack(base, name, py=RUN_PY, **over):
    folder = os.path.join(str(base), name)
    os.makedirs(folder, exist_ok=True)
    raw = {"name": name, "title": name, "summary": "測試", "version": "0.1.0", "kind": "python",
           "group": name, "access": "member", "python": {"module": "pack"}, "skill": "SKILL.md", **over}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "pack.py"), "w", encoding="utf-8") as f:
        f.write(py)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: 測試\n---\n")
    return folder


def _item(report, name):
    return next(i for i in report.items if i.name == name)


def _report(bot):
    return bot.app.extras["synox_pack_report"]


def _notices(bot):
    return [t for t in bot.texts(OWNER_ID) if NOTICE in t]


# ── 載入：不載入、白話、通知一次 ─────────────────────────────────────

@pytest.mark.parametrize("mode", ["personal", "server"])
def test_hand_placed_pack_is_unapproved_and_not_loaded(make_bot, tmp_path, mode):
    packs = tmp_path / "packs"
    _pack(packs, "ext")
    raw = {"mode": mode}
    bot = make_bot(raw=raw, pack_dirs=(str(packs),), lock_packs=False)
    item = _item(_report(bot), "ext")
    assert item.status == "unapproved" and item.lock == lock.UNLOCKED and item.scan == ""
    assert item.detail == loader.UNAPPROVED_TEXT and "送去安裝頁檢查" in item.detail and "packs.dirs" not in item.detail
    assert loader.unapproved_items(_report(bot)) == [item]
    assert bot.app.registry.node("ext") is None
    assert not any(p.manifest.name == "ext" for p in bot.app.extras["synox_packs"])
    bot.say(OWNER_ID, "/ext")
    assert bot.last(OWNER_ID) == "未知指令：/ext，輸入 /help 查看可用指令。"
    notes = _notices(bot)
    assert len(notes) == 1 and "ext" in notes[0] and "送去安裝頁檢查" in notes[0]
    again = make_bot(raw=raw, pack_dirs=(str(packs),), lock_packs=False)            # 同一份內容：不再通知
    assert _item(_report(again), "ext").status == "unapproved" and _notices(again) == []
    with open(os.path.join(str(packs), "ext", "pack.py"), "a", encoding="utf-8") as f:
        f.write("\n# 改了\n")
    changed = make_bot(raw=raw, pack_dirs=(str(packs),), lock_packs=False)          # 內容變了：再通知一次
    assert len(_notices(changed)) == 1


def test_failing_scan_pack_is_just_unapproved(make_bot, tmp_path):
    """以前伺服器版會補掃、標 rejected；現在載入時不掃，沒鎖就是 unapproved。"""
    packs = tmp_path / "packs"
    _pack(packs, "sneaky", py=NET_PY)
    bot = make_bot(raw={"mode": "server"}, pack_dirs=(str(packs),), lock_packs=False)
    item = _item(_report(bot), "sneaky")
    assert item.status == "unapproved" and item.scan == "" and bot.app.registry.node("sneaky") is None
    assert not hasattr(loader, "unlocked_scan")


def test_packs_dirs_pack_gets_developer_sentence(make_bot, tmp_path):
    user = tmp_path / "packs"
    _pack(user, "mine")
    _pack(tmp_path / "repo", "dev")                         # packs.dirs 直接指一個 pack 資料夾（別的 repo 裡）
    bot = make_bot(pack_dirs=(str(user), str(tmp_path / "repo" / "dev")), lock_packs=False)
    dev = _item(_report(bot), "dev")
    assert dev.status == "unapproved" and "送去安裝頁檢查" not in dev.detail
    assert "config.json packs.dirs" in dev.detail and "python -m synox packs lock --approve dev" in dev.detail
    assert _item(_report(bot), "mine").detail == loader.UNAPPROVED_TEXT
    assert loader.in_user_dir(str(user / "mine"), (str(user),))
    assert not loader.in_user_dir(str(tmp_path / "repo" / "dev"), (str(user),))


def test_bundled_mechanism_still_loads_but_is_empty(make_bot, tmp_path, monkeypatch):
    assert loader.BUNDLED == ()
    builtin = tmp_path / "builtin"
    _pack(builtin, "ext")
    monkeypatch.setattr(loader, "PACK_DIRS", (str(builtin),))
    monkeypatch.setattr(loader, "BUNDLED", ("ext",))
    bot = make_bot(lock_packs=False)
    item = _item(_report(bot), "ext")
    assert item.status == "loaded" and item.lock == lock.UNLOCKED
    bot.say(OWNER_ID, "/ext")
    assert bot.last(OWNER_ID) == "跑了 ext"


def test_locked_pack_loads_as_before(make_bot, tmp_path):
    packs = tmp_path / "packs"
    _pack(packs, "ext")
    bot = make_bot(pack_dirs=(str(packs),))                  # conftest 先鎖起來（擁有者經安裝頁裝過）
    assert _item(_report(bot), "ext").status == "loaded" and _notices(bot) == []


# ── 送去安裝頁檢查（packs/adopt.py） ─────────────────────────────────

def _setup(make_bot, tmp_path, mode="personal"):
    packs = tmp_path / "packs"
    _pack(packs, "ext")
    bot = make_bot(raw={"mode": mode}, pack_dirs=(str(packs),), lock_packs=False)
    return bot, str(packs), bot.app.config.data_dir


def test_adopt_stage_and_install(make_bot, tmp_path):
    bot, packs, data = _setup(make_bot, tmp_path)
    keep = os.path.join(data, "ext.json")                   # 工具的資料在 data/：送去安裝不動它
    with open(keep, "w", encoding="utf-8") as f:
        f.write('{"x": 1}')
    token, summary = adopt.stage_unlocked("ext", packs, data)
    assert summary["adopt"] == "ext" and summary["name"] == "ext" and summary["token"] == token
    assert token in [s["token"] for s in admin.list_staged(data)]
    assert admin.staged_summary(token, data)["adopt"] == "ext" and adopt.adopted_name(token, data) == "ext"
    assert lock.entry(data, "ext") is None                  # 還沒按確認：什麼都沒變
    assert adopt.install(token, data, packs, approved_by=OWNER_ID, via="web") == "ext"
    entry = lock.entry(data, "ext")
    assert entry is not None and entry["approved_by"] == OWNER_ID and entry["via"] == "web"
    backups = upgrade.backups("ext", packs)
    assert len(backups) == 1 and backups[0]["reason"] == "adopt"
    assert os.path.isfile(os.path.join(backups[0]["path"], "pack.py"))
    assert os.path.isfile(os.path.join(packs, "ext", "pack.json"))
    with open(keep, encoding="utf-8") as f:
        assert f.read() == '{"x": 1}'
    report = admin.reload(bot.app, bot.app.config, None, (packs,))
    assert _item(report, "ext").status == "loaded" and _item(report, "ext").lock == lock.LOCKED
    bot.say(OWNER_ID, "/ext")
    assert bot.last(OWNER_ID) == "跑了 ext"


def test_adopt_refuses_when_locked_meanwhile(make_bot, tmp_path):
    _bot, packs, data = _setup(make_bot, tmp_path)
    token, _summary = adopt.stage_unlocked("ext", packs, data)
    lock.approve(data, read(os.path.join(packs, "ext")), None, OWNER_ID, via="cli")     # 期間有人鎖了它
    before = sorted(os.listdir(packs))
    with pytest.raises(admin.PackAdminError, match="已經裝好"):
        adopt.install(token, data, packs, approved_by=OWNER_ID)
    assert sorted(os.listdir(packs)) == before and not os.path.exists(os.path.join(packs, admin.REMOVED))
    with pytest.raises(admin.PackAdminError, match="有鎖了"):
        adopt.stage_unlocked("ext", packs, data)


def test_adopt_puts_folder_back_when_install_fails(make_bot, tmp_path, monkeypatch):
    _bot, packs, data = _setup(make_bot, tmp_path)
    token, _summary = adopt.stage_unlocked("ext", packs, data)

    def boom(*_a, **_k):
        raise admin.PackAdminError("壞了")
    monkeypatch.setattr(admin, "install_staged", boom)
    with pytest.raises(admin.PackAdminError, match="壞了"):
        adopt.install(token, data, packs, approved_by=OWNER_ID)
    assert os.path.isfile(os.path.join(packs, "ext", "pack.py"))
    assert os.listdir(os.path.join(packs, admin.REMOVED)) == [] and lock.entry(data, "ext") is None


def test_adopt_rejects_plain_upload_and_bad_names(make_bot, tmp_path):
    _bot, packs, data = _setup(make_bot, tmp_path)
    with pytest.raises(admin.PackAdminError):
        adopt.stage_unlocked("../ext", packs, data)
    with pytest.raises(admin.PackAdminError, match="找不到"):
        adopt.stage_unlocked("nosuch", packs, data)
    import io
    import zipfile
    buf = io.BytesIO()
    src = _pack(tmp_path / "src", "other")
    with zipfile.ZipFile(buf, "w") as z:
        for name in os.listdir(src):
            z.write(os.path.join(src, name), name)
    token, summary = admin.stage(buf.getvalue(), data)          # 一般上傳：沒有 adopt
    assert "adopt" not in summary and adopt.adopted_name(token, data) is None
    with pytest.raises(admin.PackAdminError, match="一般的"):
        adopt.install(token, data, packs)


def test_adopt_failing_scan_is_refused_like_an_upload(make_bot, tmp_path):
    packs = tmp_path / "packs"
    _pack(packs, "sneaky", py=NET_PY)
    bot = make_bot(pack_dirs=(str(packs),), lock_packs=False)
    with pytest.raises(admin.GateRefused) as e:
        adopt.stage_unlocked("sneaky", str(packs), bot.app.config.data_dir)
    assert "pack.py:1" in str(e.value) and admin.list_staged(bot.app.config.data_dir) == []
    assert os.path.isfile(str(packs / "sneaky" / "pack.py"))


def test_adopt_refuses_symlinked_file(make_bot, tmp_path, monkeypatch):
    _bot, packs, data = _setup(make_bot, tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("私人的東西", encoding="utf-8")
    link = os.path.join(packs, "ext", "notes.txt")
    try:
        os.symlink(str(secret), link)
    except (OSError, NotImplementedError):            # Windows 沒開開發人員模式建不了：放一般檔、假裝它是連結
        secret_copy = open(link, "w", encoding="utf-8")
        secret_copy.write("x")
        secret_copy.close()
        real = adopt._is_link
        monkeypatch.setattr(adopt, "_is_link", lambda p: p.endswith("notes.txt") or real(p))
    with pytest.raises(admin.PackAdminError, match="捷徑"):
        adopt.stage_unlocked("ext", packs, data)
    assert admin.list_staged(data) == []


@pytest.mark.skipif(sys.platform != "win32", reason="junction 只有 Windows 有")
def test_adopt_refuses_junction_folder(make_bot, tmp_path):
    import _winapi
    _bot, packs, data = _setup(make_bot, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_text("x", encoding="utf-8")
    _winapi.CreateJunction(str(outside), os.path.join(packs, "ext", "linked"))
    with pytest.raises(admin.PackAdminError, match="捷徑"):
        adopt.stage_unlocked("ext", packs, data)


# ── packs.dirs 的開發者路徑、doctor、packs status ─────────────────────

def _config(tmp_path, dev_dir, **extra):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "llm": {"kind": "none"},
                                "packs": {"dirs": [str(dev_dir)]}, **extra}), encoding="utf-8")
    return str(path)


def test_packs_lock_approve_makes_packs_dirs_pack_load(make_bot, tmp_path, capsys):
    from synox.__main__ import main
    dev = _pack(tmp_path / "repo", "dev")
    cfg = _config(tmp_path, dev)
    bot = make_bot(raw={"packs": {"dirs": [dev]}}, lock_packs=False)
    assert _item(_report(bot), "dev").status == "unapproved"
    assert main(["--config", cfg, "packs", "lock", "--approve", "dev"]) == 0
    assert "已鎖定" in capsys.readouterr().out
    assert lock.entry(str(tmp_path / "data"), "dev") is not None
    bot = make_bot(raw={"packs": {"dirs": [dev]}}, lock_packs=False)
    assert _item(_report(bot), "dev").status == "loaded"
    bot.say(OWNER_ID, "/dev")
    assert bot.last(OWNER_ID) == "跑了 dev"


def test_doctor_and_packs_status_say_not_installed(tmp_path, capsys, monkeypatch):
    from synox import doctor
    from synox.__main__ import main
    user = tmp_path / "packs"
    _pack(user, "ext")
    monkeypatch.setattr(loader, "PACK_DIRS", (str(user),))
    dev = _pack(tmp_path / "repo", "dev")
    cfg = _config(tmp_path, dev, mode="server")
    lines = []
    doctor.run(offline=True, config_path=cfg, out=lines.append)
    text = "\n".join(lines)
    assert "⛔ ext 0.1.0：沒有經過安裝頁，沒有載入。" in text and "送去安裝頁檢查" in text
    assert "⛔ dev 0.1.0：沒有經過安裝頁，沒有載入。" in text and "packs lock --approve dev" in text
    assert "第 2 關掃描" not in text
    assert main(["--config", cfg, "packs", "status"]) == 0
    out = capsys.readouterr().out
    assert "沒有經過安裝頁" in out and "送去安裝頁檢查" in out and "packs lock --approve dev" in out
