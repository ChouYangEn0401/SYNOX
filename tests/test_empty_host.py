# -*- coding: utf-8 -*-
"""SYNOX 出廠不帶工具（legacy/builtin-packs.md）：沒裝任何工具時 build（＝synox run 會跑的那段）、/start、/help、
AI、網頁、doctor、精靈完成頁都要正常，並告訴擁有者「還沒裝任何工具、去哪裡裝」；從 .synoxpack 裝進來之後提示就消失。
全部在暫存資料夾，不連網、不開埠、不連 Telegram。"""
import json
import os

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import FIXTURE_PACKS, OTHER_ID, OWNER_ID

from synox.config import ROOT
from synox.packs import admin, library, loader
from synox.sdk import author, zip_pack

from test_web import Client, ui_of

HINT = "還沒裝任何工具"
CONNECTORS = os.path.join(ROOT, "connectors")


@pytest.fixture
def empty_dirs(tmp_path, monkeypatch):
    """這台的 SYNOX：packs/ 是空的（安裝的落點），connectors/ 照出廠。"""
    packs = tmp_path / "packs"
    packs.mkdir()
    monkeypatch.setattr(loader, "PACK_DIRS", (str(packs), CONNECTORS))
    return packs


def test_empty_host_builds_and_says_where_to_get_tools(make_bot, owner, empty_dirs):
    bot = make_bot()
    report = bot.app.extras["synox_pack_report"]
    assert report.ok and {i.name for i in report.items} == {"notion", "todoist", "google-calendar", "apple-reminders"}
    assert library.installed_tools(bot.app) == []                       # connector 不算「裝了工具」
    bot.say(owner, "/start")
    assert HINT in bot.last(owner) and "SYNOX_Libs" in bot.last(owner)
    bot.clear()
    bot.say(owner, "/help")
    texts = bot.texts(owner)
    assert texts[0].startswith("📖") and HINT in texts[-1] and "裝功能" in texts[-1]
    bot.say(owner, "/money 120 午餐")
    assert bot.last(owner).startswith("未知指令")


def test_nothing_at_all_still_works(make_bot, owner, tmp_path):
    """連 connector 都沒有：/help 只剩基本指令、AI 照常聊天（沒有工具）。"""
    bot = make_bot(["你好，我在。"], pack_dirs=[str(tmp_path / "nothing")])
    assert bot.app.extras["synox_pack_report"].items == []
    bot.say(owner, "/help")
    assert any(HINT in t for t in bot.texts(owner))
    bot.clear()
    bot.talk(owner, "嗨")
    assert "你好，我在。" in bot.last(owner)


def test_hint_is_only_for_the_owner(make_bot, owner, empty_dirs):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.say(OTHER_ID, "/start")
    assert HINT not in bot.last(OTHER_ID)
    bot.say(OTHER_ID, "/help")
    assert not any(HINT in t for t in bot.texts(OTHER_ID))


def test_configured_library_location_is_shown(make_bot, owner, empty_dirs, tmp_path):
    libs = tmp_path / "MyLibs" / "dist"
    libs.mkdir(parents=True)
    bot = make_bot(raw={"packs": {"library": "MyLibs/dist"}})          # 相對於 SYNOX 資料夾
    bot.say(owner, "/start")
    assert str(libs) in bot.last(owner)
    assert library.status(bot.app) == {"installed": 0, "empty": True, "library": str(libs),
                                       "hint": library.where_lines(bot.app.config)}
    web = make_bot(raw={"packs": {"library": "https://example.invalid/synox-libs/"}})
    assert library.library_location(web.app.config) == "https://example.invalid/synox-libs/"


def test_web_tells_owner_and_not_members(make_bot, owner, empty_dirs):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    c = Client(ui_of(bot))
    c.login(owner)
    status, tools = c.get("/api/tools")
    assert status == 200 and tools["library"]["empty"] and tools["library"]["installed"] == 0
    status, settings = c.get("/api/settings")
    assert status == 200 and settings["library"]["empty"]
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    assert "library" not in m.get("/api/tools")[1]


def _write_config(tmp_path, **extra):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "vault": {"mode": "file"},
                               **extra}), encoding="utf-8")
    return str(cfg)


def test_doctor_on_empty_host(tmp_path, empty_dirs):
    from synox import doctor
    lines = []
    doctor.run(offline=True, config_path=_write_config(tmp_path), out=lines.append)
    text = "\n".join(lines)
    assert "• 工具：還沒裝任何工具" in text and "SYNOX_Libs" in text and "packs.library" in text
    lines.clear()
    doctor.run(offline=True, config_path=_write_config(tmp_path, packs={"library": "nope"}), out=lines.append)
    assert "⚠️ config.json 的 packs.library 指到" in "\n".join(lines)


def test_doctor_counts_installed_tools(tmp_path, monkeypatch):
    from synox import doctor
    monkeypatch.setattr(loader, "PACK_DIRS", (FIXTURE_PACKS, CONNECTORS))
    lines = []
    doctor.run(offline=True, config_path=_write_config(tmp_path), out=lines.append)
    assert "• 工具：裝了 3 個（money、notes、remind）" in "\n".join(lines)


def test_wizard_finish_mentions_tool_library():
    from synox.wizard import logic
    text = logic.finish_status([], launched=True, has_token=True)
    assert "SYNOX_Libs" in text and ".synoxpack" in text


# ── 從 .synoxpack 裝進空的 host ───────────────────────────────────────

def _install(packs_dir, data_dir, blob):
    token, summary = admin.stage(blob, data_dir)
    assert summary["scan"]["ok"], summary["scan"]["problems"]
    return admin.install_staged(token, data_dir, str(packs_dir), approved_by=OWNER_ID, via="test")


def test_install_synoxpack_into_empty_host(make_bot, owner, empty_dirs, tmp_path):
    """測試用的 notes 打包成 .synoxpack（synox-sdk zip）→ 網頁那條安裝流程 → 重開：/note 能用、提示消失。"""
    out = zip_pack(os.path.join(FIXTURE_PACKS, "notes"), str(tmp_path / "dist"))
    data = str(tmp_path / "data")
    with open(out, "rb") as f:
        assert _install(empty_dirs, data, f.read()) == "notes"
    bot = make_bot()
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "notes")
    assert (item.status, item.lock) == ("loaded", "locked")
    assert [p.name for p in library.installed_tools(bot.app)] == ["notes"]
    bot.say(owner, "/note 買牛奶")
    assert "記下了" in bot.last(owner)
    bot.clear()
    bot.say(owner, "/help")
    assert not any(HINT in t for t in bot.texts(owner))


LIBS = os.environ.get("SYNOX_LIBS") or os.path.join(os.path.dirname(ROOT), "SYNOX_Libs")


@pytest.mark.skipif(not os.path.isdir(os.path.join(LIBS, "packs")),
                    reason="沒有工具庫（設環境變數 SYNOX_LIBS=<SYNOX_Libs 資料夾>，或放在 SYNOX 旁邊）")
def test_install_every_tool_from_synox_libs(make_bot, owner, empty_dirs, tmp_path):
    """整合：SYNOX_Libs 的每個工具打包成 .synoxpack、宣告的 requires.sdk 合這台、一個一個裝進空的 host、重開全部載入。
    只讀工具庫（打包寫在暫存資料夾）。"""
    data = str(tmp_path / "data")
    names = []
    for name in sorted(os.listdir(os.path.join(LIBS, "packs"))):
        folder = os.path.join(LIBS, "packs", name)
        if name.startswith("_") or not os.path.isfile(os.path.join(folder, "pack.json")):
            continue
        with open(os.path.join(folder, "pack.json"), encoding="utf-8") as f:
            requires = json.load(f).get("requires") or {}
        assert requires.get("sdk"), f"{name} 沒宣告 requires.sdk"
        out = zip_pack(folder, str(tmp_path / "dist"))
        with open(out, "rb") as f:
            names.append(_install(empty_dirs, data, f.read()))
    assert names
    bot = make_bot()
    status = {i.name: i.status for i in bot.app.extras["synox_pack_report"].items}
    assert all(status[n] == "loaded" for n in names), status
    assert author.SDK_VERSION                                       # 這台的 SDK 版本就是它們宣告要的
