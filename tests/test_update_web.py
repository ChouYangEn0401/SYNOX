"""
網頁一鍵更新、回到上一版、補裝套件（docs/adr/0047 §1、§3）。不連網（假的 GitHub）、不開視窗（假的 Popen）、
不換這台的安裝（root 是 tmp_path）。update.ps1 只做靜態檢查（真的換檔要在 Windows 真機試，HumanTestList.md）。
"""

from __future__ import annotations

import json
import os

import pytest

from synox import __version__
from synox.guard import stepup
from synox.update import web_api

from test_update import ROOT, FakeGitHub, _fn, _ps, keypair, served
from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")


class Recorder:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        if self.fail:
            raise self.fail


def _setup(make_bot, tmp_path, monkeypatch, owner, *, signed=True, version="9.0.0", preview=False):
    """Windows＋ZIP 裝法的假 SYNOX 資料夾（tmp_path）＋假的 GitHub＋假的 Popen；背景工作改成馬上跑。"""
    monkeypatch.setattr(web_api.os, "name", "nt")
    bot = make_bot(raw={"mode": "server"})
    cfg = {"owner_id": owner, **({"updates": {"channel": "preview"}} if preview else {})}
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "Update.bat").write_text("@echo off\r\n", encoding="ascii")
    (tmp_path / "setup").mkdir(exist_ok=True)
    (tmp_path / "setup" / "update.ps1").write_text("# fake\r\n", encoding="utf-8")
    ui = bot.app.extras["synox_web"]
    key, pub = keypair()
    ui.update_opener = served(version, key=key) if signed else served(version)
    ui.update_keys = [pub]
    ui.catalog_opener = FakeGitHub(fail=OSError())
    ui.update_spawn = lambda fn: fn()
    ui.update_popen = Recorder()
    c = Client(ui)
    c.login(owner)
    return bot, ui, c, key


def test_status_says_what_the_card_needs(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    d = c.get("/api/settings/update")[1]
    assert d["can_update"] is True and d["previous"] == [] and d["job"] is None and d["boot"] == ui.boot_id
    assert d["last_update"] is None and d["deps"] is None and d["deps_job"] is None
    os.makedirs(ui.config.data_dir, exist_ok=True)
    open(os.path.join(ui.config.data_dir, "update_last.json"), "w", encoding="utf-8").write(
        json.dumps({"action": "update", "from": "0.2.0", "to": "9.0.0", "ok": True, "at": "2026-12-01T10:00:00",
                    "junk": {"x": 1}}))
    prev = tmp_path / "_previous"
    (prev / "0.2.0-20261201-100000").mkdir(parents=True)
    (prev / ".replaced-20261201-100500").mkdir()                              # 退回時的暫存：不算
    d = c.get("/api/settings/update")[1]
    assert d["last_update"] == {"action": "update", "from": "0.2.0", "to": "9.0.0", "ok": True, "at": "2026-12-01T10:00:00"}
    assert d["previous"] == ["0.2.0-20261201-100000"]
    os.mkdir(tmp_path / ".git")                                              # git 裝的：沒有一鍵更新
    assert c.get("/api/settings/update")[1]["can_update"] is False


def test_one_click_update_prepares_verifies_then_opens_update_bat_apply(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    d = c.post("/api/settings/update/check", {})[1]
    assert d["result"]["status"] == "newer" and d["result"]["signed"] is True
    status, d = c.post("/api/settings/update/start", {"version": "9.0.0"})
    assert status == 200, d
    job = d["job"]
    assert job["state"] == "launched" and job["version"] == "9.0.0" and job["from"] == __version__
    assert any("簽章驗過了" in line for line in job["lines"])
    assert ui.update_popen.calls == [["cmd", "/c", "start", "SYNOX Update", str(tmp_path / "Update.bat"),
                                      "-Apply", "-FromWeb"]]
    ready = json.load(open(tmp_path / "data" / "update" / "ready.json", encoding="utf-8"))
    assert ready["version"] == "9.0.0" and ready["signed"] is True                # update.ps1 -Apply 讀這一份
    assert c.post("/api/settings/update/start", {"version": "9.0.0"})[0] == 409  # 交出去了：等它換完，不會開第二個視窗


def test_unsigned_release_is_never_installed_from_the_web(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner, signed=False)
    d = c.post("/api/settings/update/check", {})[1]
    assert d["result"]["status"] == "newer" and d["result"]["signed"] is False
    status, d = c.post("/api/settings/update/start", {"version": "9.0.0"})
    assert status == 400 and "沒有簽章" in d["error"]
    assert ui.update_popen.calls == [] and not (tmp_path / "data" / "update").exists()


def test_signature_that_does_not_verify_stops_before_anything_changes(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    c.post("/api/settings/update/check", {})
    ui.update_keys = [keypair()[1]]                                          # 別人的公鑰：簽章對不上
    d = c.post("/api/settings/update/start", {"version": "9.0.0"})[1]
    assert d["job"]["state"] == "failed" and "簽章對不上" in d["job"]["message"]
    assert ui.update_popen.calls == [] and not (tmp_path / "data" / "update" / "ready.json").exists()


def test_only_the_version_the_owner_saw(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, key = _setup(make_bot, tmp_path, monkeypatch, owner)
    assert c.post("/api/settings/update/start", {"version": "9.0.0"})[0] == 400    # 還沒檢查過
    c.post("/api/settings/update/check", {})
    status, d = c.post("/api/settings/update/start", {"version": "8.0.0"})
    assert status == 400 and "檢查更新" in d["error"]
    assert c.post("/api/settings/update/start", {})[0] == 400
    ui.update_opener = served("9.1.0", key=key)                               # 檢查完之後又發了一版
    d = c.post("/api/settings/update/start", {"version": "9.0.0"})[1]
    assert d["job"]["state"] == "failed" and "不是你按的 9.0.0" in d["job"]["message"]
    assert ui.update_popen.calls == []


def test_preview_needs_the_preview_channel(make_bot, tmp_path, monkeypatch, owner):
    from synox.update import check as upd
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner, version="9.0.0-beta.1")
    upd.remember(ui.config.data_dir, upd.CheckResult(status="newer", installed=__version__, latest="9.0.0-beta.1",
                                                         signed=True, prerelease=True))
    status, d = c.post("/api/settings/update/start", {"version": "9.0.0-beta.1"})
    assert status == 400 and "也提醒我有測試版" in d["error"]


def test_preview_channel_installs_the_preview(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, key = _setup(make_bot, tmp_path, monkeypatch, owner, version="9.0.0-beta.1", preview=True)
    gh = served("9.0.0-beta.1", key=key)
    gh.files[upd_list()] = b"[" + gh.files.pop(upd_latest()) + b"]"        # 只有測試版：latest 沒有，清單裡有
    ui.update_opener = gh
    d = c.post("/api/settings/update/check", {})[1]
    assert d["result"]["status"] == "newer" and d["result"]["prerelease"] is True
    d = c.post("/api/settings/update/start", {"version": "9.0.0-beta.1"})[1]
    assert d["job"]["state"] == "launched" and ui.update_popen.calls[-1][-2:] == ["-Apply", "-FromWeb"]


def upd_list():
    from synox.update import check as upd
    return upd.API_LIST_URL


def upd_latest():
    from synox.update import check as upd
    return upd.API_URL


def test_launch_failure_throws_the_prepared_copy_away(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    ui.update_popen = Recorder(fail=OSError("no cmd"))
    c.post("/api/settings/update/check", {})
    d = c.post("/api/settings/update/start", {"version": "9.0.0"})[1]
    assert d["job"]["state"] == "failed" and "打不開更新視窗" in d["job"]["message"]
    assert not (tmp_path / "data" / "update" / "ready.json").exists()
    assert not (tmp_path / "data" / "update" / "9.0.0").exists()


def test_one_update_at_a_time(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    c.post("/api/settings/update/check", {})
    setattr(ui, web_api.JOB_KEY, {"state": "preparing", "lines": []})
    status, d = c.post("/api/settings/update/start", {"version": "9.0.0"})
    assert status == 409 and "已經在更新" in d["error"]
    assert c.post("/api/settings/update/rollback", {"confirm": True})[0] in (400, 409)


def test_not_windows_or_not_zip_has_no_one_click(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    c.post("/api/settings/update/check", {})
    os.mkdir(tmp_path / ".git")
    status, d = c.post("/api/settings/update/start", {"version": "9.0.0"})
    assert status == 400 and "git pull" in d["error"]
    os.rmdir(tmp_path / ".git")
    os.remove(tmp_path / "setup" / "update.ps1")                              # 舊版的 SYNOX：沒有 update.ps1
    assert c.post("/api/settings/update/start", {"version": "9.0.0"})[0] == 400
    monkeypatch.setattr(web_api.os, "name", "posix")
    status, d = c.post("/api/settings/update/start", {"version": "9.0.0"})
    assert status == 400 and "不是 Windows" in d["error"]
    assert ui.update_popen.calls == []


def test_rollback_from_the_web(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    status, d = c.post("/api/settings/update/rollback", {"confirm": True})
    assert status == 400 and "沒有可以退回的舊版" in d["error"]
    (tmp_path / "_previous" / "0.2.0-20261201-100000").mkdir(parents=True)
    assert c.post("/api/settings/update/rollback", {})[0] == 400                # 要明確確認
    status, d = c.post("/api/settings/update/rollback", {"confirm": True})
    assert status == 200 and d["job"]["action"] == "rollback" and d["job"]["state"] == "launched"
    assert ui.update_popen.calls == [["cmd", "/c", "start", "SYNOX Update", str(tmp_path / "Update.bat"),
                                      "-Rollback", "-FromWeb"]]


def test_deps_retry_runs_the_same_sync_in_the_background(make_bot, tmp_path, monkeypatch, owner):
    _bot, ui, c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    seen = []

    def fake_sync(root, data_dir, *, say, force):
        seen.append((root, data_dir, force))
        say("🔧 補裝中")
        return {"ok": True, "fixed": [{"name": "ntu_easy_llm"}], "lines": ["✅ 套件補好了：ntu_easy_llm 0.5.0 → 0.6.0a2"]}
    ui.deps_sync = fake_sync
    d = c.post("/api/settings/update/deps", {})[1]
    assert seen and seen[0][2] is True and os.path.normcase(seen[0][0]) == os.path.normcase(str(tmp_path))
    assert d["deps_job"]["state"] == "done" and d["deps_job"]["ok"] is True and d["deps_job"]["fixed"] == 1
    setattr(ui, web_api.DEPS_KEY, {"state": "running", "lines": []})
    assert c.post("/api/settings/update/deps", {})[0] == 409


def test_only_the_owner_and_stepup_labels(make_bot, tmp_path, monkeypatch, owner):
    from conftest import OTHER_ID
    from isdtelekit.users.roles import BasicRoles
    bot, ui, _c, _key = _setup(make_bot, tmp_path, monkeypatch, owner)
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui)
    m.login(OTHER_ID)
    for path in ("/api/settings/update/start", "/api/settings/update/rollback", "/api/settings/update/deps"):
        assert m.post(path, {"version": "9.0.0", "confirm": True})[0] == 403
    assert ui.update_popen.calls == []
    assert stepup.sensitive_action("POST", "/api/settings/update/start") == "更新 SYNOX"
    assert stepup.sensitive_action("POST", "/api/settings/update/rollback") == "退回上一版 SYNOX"
    assert stepup.sensitive_action("POST", "/api/settings/update/deps") == "補裝 SYNOX 的套件"


def test_page_has_the_one_click_card():
    html = open(os.path.join(ROOT, "src", "synox", "web", "static", "app.html"), encoding="utf-8").read()
    system = html.split('data-tab="system" role="tabpanel">', 1)[1].split('<div class="tab-panel', 1)[0]
    for needle in ('id="upd-start"', 'id="upd-back"', 'id="upd-ask"', 'id="upd-progress"', 'id="upd-channel"',
                   'id="upd-last"', 'id="upd-deps"', 'id="upd-deps-retry"', "data-restart-now"):
        assert needle in system, needle
    for needle in ("/api/settings/update/start", "/api/settings/update/rollback", "/api/settings/update/deps",
                   "watchRestart", "（測試版）", "r.signed"):
        assert needle in html, needle
    assert 'id="upd-go"' in system and "/api/settings/update/launch" in html   # 沒簽章的版本：照舊打開更新視窗


def test_update_ps1_apply_reads_ready_and_uses_the_same_swap():
    text = _ps("update.ps1")
    body = _fn(text, "Invoke-Apply")
    order = ["Read-Ready", "$ready.signed", "Invoke-Swap $ready"]
    pos = [body.index(s) for s in order]
    assert pos == sorted(pos), order
    assert "Remove-Prepared $ready" in body                                     # 沒簽章：丟掉，什麼都不換
    assert "--prepare" not in body and "update --check" not in body and "Stop-Synox" not in body   # 不再查、換檔只在 Invoke-Swap
    main = text.split("\n$code = 1", 1)[1]
    assert "elseif ($Apply) { $code = Invoke-Apply }" in main
    assert main.index("'.git'") < main.index("exe-installer") < main.index("Invoke-Apply")   # git／exe 一樣不換
    confirm = _fn(text, "Confirm-Step")
    assert "if ($Yes -or $FromWeb) { return $true }" in confirm
    start = _fn(text, "Start-Synox")
    assert "if ($FromWeb)" in start and "'--no-browser'" in start
    assert "-not $FromWeb -and (Test-Interactive)" in text.split("\n$code = 1", 1)[1]
