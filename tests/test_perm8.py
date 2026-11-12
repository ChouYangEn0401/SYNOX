# -*- coding: utf-8 -*-
"""PERM-8：伺服器版 python pack 的信任（third-party 只給擁有者、沒鎖的補第 2 關）與 pack.path_of(user)。
pack 都是 tmp 裡的小 python pack，不連網、不開埠、不跑子程序。"""
import json
import os

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID, trust_core

from synox.agent import tools as tools_mod
from synox.agent.loop import ai_decision
from synox.config import SynoxConfig
from synox.packs import loader, lock, scan
from synox.packs.manifest import read

RUN_PY = r'''
from isdtelekit.core.registry import READ

def install(app, pack):
    def run(api, chat_id, user, args):
        app.extras.setdefault("ran", []).append((pack.name, user.tg_id))
        api.send_message(chat_id, "跑了 " + pack.name)
    pack.group.leaf("run", run, "跑一下", effect=READ, default=True)
'''


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


def _server(make_bot, tmp_path, **raw):
    bot = make_bot(raw={"mode": "server", **raw},
                   pack_dirs=loader.PACK_DIRS + (str(tmp_path / "packs"),))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    return bot


def _sees(bot, tg_id, group):
    reg = bot.app.registry
    return reg.node(group) is not None and reg.visible(bot.app.users.get_or_create(tg_id), reg.node(group))


def _ai_groups(bot, tg_id):
    user = bot.app.users.get_or_create(tg_id)
    return {s.name.split("__")[0] for s in tools_mod.build(bot.app.registry, lambda n: ai_decision(bot.app, user, n))}


def _item(bot, name):
    return next(i for i in bot.app.extras["synox_pack_report"].items if i.name == name)


# ── 信任：third-party 只給擁有者 ──────────────────────────────────────

def test_unlocked_python_pack_owner_only_on_server(make_bot, tmp_path):
    _pack(tmp_path / "packs", "ext")
    bot = _server(make_bot, tmp_path)
    item = _item(bot, "ext")
    assert item.status == "loaded" and item.scan == "passed"
    assert "只對擁有者開放" in item.detail and "沒有 packs.lock" in item.detail and "--trust core" in item.detail
    assert _sees(bot, OWNER_ID, "ext") and not _sees(bot, OTHER_ID, "ext")
    bot.say(OTHER_ID, "/ext")
    assert bot.last(OTHER_ID) == "未知指令：/ext，輸入 /help 查看可用指令。"        # 跟不存在的一模一樣
    bot.say(OTHER_ID, "/nosuch")
    assert bot.last(OTHER_ID) == "未知指令：/nosuch，輸入 /help 查看可用指令。"
    assert "ext" not in _ai_groups(bot, OTHER_ID) and "ext" in _ai_groups(bot, OWNER_ID)
    assert bot.app.extras.get("ran", []) == []
    bot.say(OWNER_ID, "/ext")
    assert bot.last(OWNER_ID) == "跑了 ext"
    assert _sees(bot, OTHER_ID, "note") and _sees(bot, OTHER_ID, "money")          # 擁有者裝成 core 的照常（conftest）


def test_locked_trust_decides(make_bot, tmp_path):
    third = _pack(tmp_path / "packs", "third")
    core = _pack(tmp_path / "packs", "corep")
    data = tmp_path / "data"
    lock.approve(str(data), read(third), None, OWNER_ID, via="web")                 # 預設 third-party
    trust_core(data, core)
    bot = _server(make_bot, tmp_path)
    assert not _sees(bot, OTHER_ID, "third") and _sees(bot, OWNER_ID, "third")
    assert "安裝時信任選的是第三方" in _item(bot, "third").detail
    assert _sees(bot, OTHER_ID, "corep") and _item(bot, "corep").detail == ""
    assert _item(bot, "corep").scan == ""                                          # 有鎖：安裝時掃過，不再掃
    assert "corep" in _ai_groups(bot, OTHER_ID) and "third" not in _ai_groups(bot, OTHER_ID)


def test_bundled_core_unless_the_lock_says_otherwise(tmp_path):
    """審查 A #5：有鎖時以鎖的 trust 為準；出廠的名字＋位置只在沒有鎖時算 core。
    （2026-11-12 起出廠的只剩 connectors/，這裡用 notion；notes 已經不是出廠的。）"""
    from synox.packs import admin
    cfg = SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "mode": "server"},
                                require_token=False, root=str(tmp_path))
    notion = read(os.path.join(loader.PACK_DIRS[1], "notion"))
    assert loader.is_bundled(notion)
    assert not loader.is_bundled(read(os.path.join(loader.PACK_DIRS[0], "notes")))   # 測試用的 notes 不是出廠的
    assert loader.python_trust(cfg, notion) == lock.CORE                            # 沒鎖：出廠的＝core
    m, _report, problems = admin.approve_installed(notion.folder, cfg.data_dir, approved_by=OWNER_ID)
    assert not problems and lock.trust_of(cfg.data_dir, "notion") == lock.CORE        # 第一次鎖出廠的：沿用 core
    assert loader.python_trust(cfg, notion) == lock.CORE and loader.trust_reason(cfg, notion) == ""
    lock.approve(cfg.data_dir, notion, None, OWNER_ID, via="web")                    # 鎖記 third-party
    assert loader.python_trust(cfg, notion) == lock.THIRD_PARTY                      # 以前：名字蓋過鎖＝core
    copy = read(_pack(tmp_path / "elsewhere", "notion"))                             # 同名但不在內建資料夾
    assert not loader.is_bundled(copy)


def test_third_party_named_like_bundled_via_upgrade_is_not_core(tmp_path, monkeypatch):
    """惡意作者把 pack 取名成出廠的（notion）、經升級流程裝進內建的資料夾：鎖是 third-party，不能被名字改成 core。"""
    import io
    import zipfile
    from synox import sandbox
    from synox.packs import admin, upgrade
    packs, data = tmp_path / "packs", tmp_path / "data"
    monkeypatch.setattr(loader, "PACK_DIRS", (str(packs),))                         # 這個資料夾當成內建的 packs/
    factory = read(_pack(packs, "notion"))
    cfg = SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(data), "mode": "server"},
                                require_token=False, root=str(tmp_path))
    assert loader.is_bundled(factory) and loader.python_trust(cfg, factory) == lock.CORE
    evil = _pack(tmp_path / "evil", "notion", py=RUN_PY, version="0.2.0", publisher="someone-else")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in os.listdir(evil):
            z.write(os.path.join(evil, name), name)
    token, _summary = admin.stage(buf.getvalue(), str(data))
    upgrade.upgrade_staged(token, str(data), str(packs), approved_by=OWNER_ID, via="web")
    installed = read(str(packs / "notion"))
    assert installed.version == "0.2.0" and loader.is_bundled(installed)             # 名字、位置都像出廠的
    assert lock.trust_of(str(data), "notion") == lock.THIRD_PARTY
    assert loader.python_trust(cfg, installed) == lock.THIRD_PARTY                   # 以前：core
    assert "只對擁有者開放" in loader.trust_reason(cfg, installed)
    assert sandbox.trust_of(str(data), installed) == sandbox.THIRD_PARTY


def test_personal_mode_unaffected(make_bot, tmp_path):
    _pack(tmp_path / "packs", "ext")
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    item = _item(bot, "ext")
    assert item.status == "loaded" and item.detail == "" and item.scan == ""
    bot.say(OWNER_ID, "/ext")
    assert bot.last(OWNER_ID) == "跑了 ext"


# ── 沒鎖的：載入時補第 2 關 ───────────────────────────────────────────

NET_PY = "import socket\n\ndef install(app, pack):\n    pack.group.leaf('run', lambda *a: None, 'x')\n"


def test_unlocked_pack_failing_scan_is_not_loaded(make_bot, tmp_path):
    _pack(tmp_path / "packs", "sneaky", py=NET_PY)                                  # 連網但沒宣告 network
    bot = _server(make_bot, tmp_path)
    item = _item(bot, "sneaky")
    assert item.status == "rejected" and item.scan == "failed" and "pack.py:1" in item.detail
    assert bot.app.registry.node("sneaky") is None and not bot.app.extras["synox_pack_report"].ok
    bot.say(OWNER_ID, "/sneaky")
    assert bot.last(OWNER_ID).startswith("未知指令")
    personal = make_bot(pack_dirs=(str(tmp_path / "packs"),))                       # 個人版照舊載入
    assert _item(personal, "sneaky").status == "loaded"


def test_doctor_and_packs_status_explain(tmp_path, capsys):
    from synox import doctor
    from synox.__main__ import main
    base = tmp_path / "packs"
    _pack(base, "ext")
    _pack(base, "sneaky", py=NET_PY)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "mode": "server",
                                "llm": {"kind": "none"}, "packs": {"dirs": [str(base)]}}), encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "第 2 關掃描沒過，不會載入" in text and "沒有 packs.lock（手動放進來的）" in text
    assert main(["--config", str(path), "packs", "status"]) == 0
    out = capsys.readouterr().out
    assert "第 2 關掃描沒過" in out and "只對擁有者開放" in out


# ── pack.path_of(user) ───────────────────────────────────────────────

def _bare_pack(tmp_path, mode, data="user"):
    cfg = SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "mode": mode},
                                require_token=False, root=str(tmp_path))
    m = read(_pack(tmp_path / "src", "diary", data=data))
    return loader.Pack(m, loader.PackStore(m.name, cfg.data_dir), None, cfg.data_dir, config=cfg)


def test_path_of_is_per_user_and_created(tmp_path):
    pack = _bare_pack(tmp_path, "server")
    p = pack.path_of(OTHER_ID, "a", "b.txt")
    folder = os.path.join(str(tmp_path / "data"), "users", str(OTHER_ID), "diary", "files")
    assert p == os.path.join(folder, "a", "b.txt") and os.path.isdir(folder)
    assert pack.path_of(OWNER_ID) != pack.path_of(OTHER_ID)
    with pytest.raises(loader.PackPathError, match="下令的人"):
        pack.path_of(None, "x")
    personal = _bare_pack(tmp_path / "p", "personal")
    assert personal.path_of(None, "x") == os.path.join(str(tmp_path / "p" / "data"), "diary", "files", "x")


@pytest.mark.parametrize("parts", [("..", "x"), ("a", "..", "..", "x"), ("..",), ("/etc/passwd",),
                                   ("C:\\Windows",), ("a/../../b",)])
def test_path_of_blocks_escape(tmp_path, parts):
    pack = _bare_pack(tmp_path, "server")
    with pytest.raises(loader.PackPathError):
        pack.path_of(OTHER_ID, *parts)


def test_old_path_refused_on_server_for_data_user(tmp_path):
    with pytest.raises(loader.PackPathError, match="path_of"):
        _bare_pack(tmp_path, "server").path("x.txt")
    assert _bare_pack(tmp_path / "p", "personal").path("x.txt").endswith(os.path.join("packs", "diary", "x.txt"))
    shared = _bare_pack(tmp_path / "s", "server", data="shared")
    assert shared.path("x.txt").endswith(os.path.join("packs", "diary", "x.txt"))  # 共用資料照舊
    with pytest.raises(loader.PackPathError):
        shared.path("..", "..", "x")


# ── 第 2 關：data=user 不准 pack.path ────────────────────────────────

def test_scan_data_user_pack_path_refused_path_of_ok(tmp_path):
    bad = ("def install(app, pack):\n"
           "    def go(api, c, u, a):\n"
           "        open(pack.path('x.txt'), 'w').write('1')\n"
           "    pack.group.leaf('go', go, 'go')\n")
    good = bad.replace("pack.path('x.txt')", "pack.path_of(u, 'x.txt')")
    m = read(_pack(tmp_path / "a", "bad", py=bad, data="user", capabilities=["filesystem:own"]))
    problems = scan.gate2(m).problems(m)
    assert len(problems) == 1 and problems[0].startswith("pack.py:3 ") and "path_of" in problems[0]
    m2 = read(_pack(tmp_path / "b", "good", py=good, data="user", capabilities=["filesystem:own"]))
    assert scan.gate2(m2).problems(m2) == []


def test_bundled_packs_pass_gate2():
    for base in loader.PACK_DIRS:
        for folder in loader.discover((base,)):
            m = read(folder)
            assert scan.gate2(m).problems(m) == [], m.name
