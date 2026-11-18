"""🔄 重新啟動 SYNOX（web/restart.py、__main__.cmd_restart）：全部用假的 spawn／stop／行程，不會真的重開任何東西。"""

import json
import os
import time

import pytest

from isdtelekit.users.roles import BasicRoles

from synox import __main__ as cli
from synox.web import restart

from conftest import OTHER_ID
from test_web import Client, ui_of
from test_web_channels import TG_TOKEN, _setup


class FakeTimer:
    """threading.Timer 的替身：記下來，測試自己決定要不要「時間到」。"""
    made = []

    def __init__(self, delay, fn):
        self.delay, self.fn, self.daemon, self.started = delay, fn, False, False
        FakeTimer.made.append(self)

    def start(self):
        self.started = True


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def fake_restarter(ui, *, mode="launcher", clock=None, spawn_error=None):
    calls = {"spawn": [], "stop": 0}

    def spawn(argv, cwd):
        if spawn_error:
            raise spawn_error
        calls["spawn"].append((argv, cwd))

    def stop():
        calls["stop"] += 1

    FakeTimer.made = []
    ui.restarter = restart.Restarter(ui.config.data_dir, "C:\\SYNOX", config_path="C:\\SYNOX\\config.json",
                                     stop=stop, spawn=spawn, mode=mode, clock=clock or Clock(),
                                     python="C:\\SYNOX\\.venv\\Scripts\\python.exe", pid=4321, timer=FakeTimer)
    return calls


@pytest.fixture
def owner_restart(make_bot):
    bot = make_bot()
    ui = ui_of(bot)
    c = Client(ui)
    c.login(bot.app.config.owner_id)
    return bot, ui, c


# ── 誰能按、怎麼擋 ───────────────────────────────────────────────────

def test_members_never_see_or_use_restart(make_bot):
    bot = make_bot(raw={"mode": "server"})
    ui = ui_of(bot)
    calls = fake_restarter(ui)
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui)
    m.login(OTHER_ID)
    me = m.get("/api/me")[1]
    assert me["restart"] is None                                   # 選單不會有那一項
    assert m.get("/api/settings/restart")[0] == 403
    assert m.post("/api/settings/restart", {"confirm": True})[0] == 403
    assert calls == {"spawn": [], "stop": 0}


def test_restart_needs_login_csrf_and_same_origin(owner_restart):
    _bot, ui, c = owner_restart
    calls = fake_restarter(ui)
    body = json.dumps({"confirm": True}).encode()
    anon = ui.handle("POST", "/api/settings/restart", {"Host": "127.0.0.1:8830"}, body)
    assert anon[0] == 401
    no_csrf = c.raw("POST", "/api/settings/restart", body, headers={"X-SYNOX-CSRF": "nope"})
    assert no_csrf[0] == 403
    other_origin = c.raw("POST", "/api/settings/restart", body, headers={"Origin": "http://evil.example"})
    assert other_origin[0] == 403
    cross = c.raw("POST", "/api/settings/restart", body, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross[0] == 403
    assert calls == {"spawn": [], "stop": 0}
    status, _ = c.get("/api/settings/restart")                     # GET 只看現況
    assert status == 200 and calls == {"spawn": [], "stop": 0}


def test_restart_needs_explicit_confirm(owner_restart):
    _bot, ui, c = owner_restart
    calls = fake_restarter(ui)
    for data in ({}, {"confirm": "yes"}, {"confirm": 1}):
        status, out = c.post("/api/settings/restart", data)
        assert status == 400 and "確認" in out["error"]
    assert calls["spawn"] == []


def test_restart_is_step_up_sensitive():
    from synox.guard.stepup import sensitive_action
    assert sensitive_action("POST", "/api/settings/restart") == "重新啟動 SYNOX"
    assert sensitive_action("GET", "/api/settings/restart") is None


# ── 真的按下去（假的小幫手、假的關機）────────────────────────────────

def test_restart_spawns_helper_then_stops_after_reply(owner_restart):
    bot, ui, c = owner_restart
    calls = fake_restarter(ui)
    status, out = c.post("/api/settings/restart", {"confirm": True})
    assert status == 202 and out["ok"] and out["boot"] == ui.boot_id
    (argv, cwd), = calls["spawn"]
    assert cwd == "C:\\SYNOX"
    assert argv[:5] == ["cmd", "/c", "start", "", "/b"]             # 經過 start：父行程不是 SYNOX（taskkill /T 不會砍到它）
    assert argv[5:] == ["C:\\SYNOX\\.venv\\Scripts\\python.exe", "-m", "synox", "--config", "C:\\SYNOX\\config.json",
                        "restart", "--after-pid", "4321"] + argv[13:]
    assert calls["stop"] == 0                                      # 回應送出去之前不關
    timer, = FakeTimer.made
    assert timer.started and timer.daemon and timer.delay == restart.STOP_DELAY
    timer.fn()
    assert calls["stop"] == 1
    rows = [json.loads(line) for line in open(os.path.join(bot.app.config.data_dir, "security_audit.jsonl"),
                                               encoding="utf-8")]
    row = [r for r in rows if r["event"] == "restart"][-1]
    assert row["ok"] and row["code"] == "ok" and row["target"] == "launcher" and row["by"] == bot.app.config.owner_id
    # 已經在重開：再按一次不會再開一支
    status, out = c.post("/api/settings/restart", {"confirm": True})
    assert status == 409 and len(calls["spawn"]) == 1


def test_rate_limit_survives_restart_and_caps_per_hour(owner_restart):
    _bot, ui, c = owner_restart
    clock = Clock()
    calls = fake_restarter(ui, clock=clock)
    assert c.post("/api/settings/restart", {"confirm": True})[0] == 202
    calls = fake_restarter(ui, clock=clock)                        # 「重開之後」：新的一支，記錄在 data/restart.json
    clock.t += 30
    status, out = c.post("/api/settings/restart", {"confirm": True})
    assert status == 429 and out["wait_s"] == restart.MIN_GAP - 30 and calls["spawn"] == []
    for _ in range(restart.MAX_PER_HOUR - 1):
        clock.t += restart.MIN_GAP + 1
        calls = fake_restarter(ui, clock=clock)
        assert c.post("/api/settings/restart", {"confirm": True})[0] == 202
    clock.t += restart.MIN_GAP + 1
    calls = fake_restarter(ui, clock=clock)
    status, out = c.post("/api/settings/restart", {"confirm": True})
    assert status == 429 and "這一個小時" in out["error"] and calls["spawn"] == []
    assert c.get("/api/settings/restart")[1]["wait_s"] > 0


@pytest.mark.parametrize("mode,word", [("manual", "Ctrl+C"), ("docker", "docker compose restart")])
def test_start_modes_that_cannot_restart_say_so(owner_restart, mode, word):
    bot, ui, c = owner_restart
    calls = fake_restarter(ui, mode=mode)
    st = c.get("/api/settings/restart")[1]
    assert st["can"] is False and st["mode"] == mode and word in st["how"]
    status, out = c.post("/api/settings/restart", {"confirm": True})
    assert status == 409 and word in out["error"] and calls == {"spawn": [], "stop": 0}
    assert c.get("/api/me")[1]["restart"]["can"] is False


def test_spawn_failure_does_not_stop_synox(owner_restart):
    _bot, ui, c = owner_restart
    calls = fake_restarter(ui, spawn_error=OSError("nope"))
    status, out = c.post("/api/settings/restart", {"confirm": True})
    assert status == 500 and "Stop.bat" in out["error"]
    assert calls["stop"] == 0 and FakeTimer.made == [] and not ui.restarter.busy


def test_start_mode_detection():
    assert restart.start_mode({"SYNOX_LAUNCHER": "start.bat"}, "nt") == "launcher"
    assert restart.start_mode({"SYNOX_LAUNCHER": "start.bat"}, "posix") == "manual"
    assert restart.start_mode({}, "nt") == "manual"                # 終端機裡 python -m synox run
    assert restart.start_mode({"SYNOX_IN_DOCKER": "1", "SYNOX_LAUNCHER": "start.bat"}, "nt") == "docker"
    assert restart.start_mode({"SYNOX_IN_CONTAINER": "1"}, "posix") == "docker"


def test_start_bat_marks_the_launcher():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bat = open(os.path.join(root, "Start.bat"), "rb").read()
    bat.decode("ascii")
    run = bat.split(b":run\r\n", 1)[1]
    assert run.index(b'set "SYNOX_LAUNCHER=start.bat"') < run.index(b"-m synox run")


def test_app_stopper_wakes_the_main_loop():
    import threading

    class App:
        def __init__(self):
            self._stop = threading.Event()
            self.stopped = 0

        def stop(self):
            self.stopped += 1

    app = App()
    restart.app_stopper(app)()
    assert app._stop.is_set() and app.stopped == 0                 # 主執行緒自己跑 stop()、放掉 host.lock


# ── 要重開才生效（選單上的小點）、/alive、/api/me ──────────────────────

def test_pending_flag_after_channel_settings_change(make_bot, tmp_path, owner):
    _bot, c, _path = _setup(make_bot, tmp_path, owner)
    assert c.get("/api/me")[1]["restart"]["pending"] is False
    assert c.get("/api/settings/restart")[1]["pending"] is False
    assert c.post("/api/settings/channels/telegram", {"token": TG_TOKEN})[0] == 200
    me = c.get("/api/me")[1]
    assert me["restart"]["pending"] is True and me["restart"]["reasons"] == ["Telegram 的設定改了"]
    st = c.get("/api/settings/restart")[1]
    assert st["pending"] is True and "Telegram" in st["reasons"][0]


def test_alive_needs_no_login_and_tells_boots_apart(owner_restart):
    _bot, ui, c = owner_restart
    status, headers, body = ui.handle("GET", "/alive", {"Host": "127.0.0.1:8830"})
    data = json.loads(body)
    assert status == 200 and data == {"ok": True, "boot": ui.boot_id}
    assert dict(headers)["Cache-Control"] == "no-store"
    assert len(ui.boot_id) == 16 and restart.new_boot_id() != ui.boot_id


def test_me_has_version_and_uptime(owner_restart):
    from synox import __version__
    _bot, ui, c = owner_restart
    ui.started_at = ui._clock() - 3 * 3600 - 5
    me = c.get("/api/me")[1]
    assert me["version"] == __version__ and 3 * 3600 <= me["uptime_s"] < 3 * 3600 + 60
    assert me["restart"]["pending"] is False


# ── 小幫手（python -m synox restart）：假的行程、假的埠 ─────────────────

class Proc:
    def __init__(self, alive_for=0):
        self.checks = 0
        self.alive_for = alive_for
        self.killed = []

    def alive(self, pid, created):
        self.checks += 1
        return not self.killed and self.checks <= self.alive_for

    def kill(self, pid):
        self.killed.append(pid)


def _helper_args(tmp_path, *, port=8830, start_bat=True):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"bot_token": "", "owner_id": 1, "data_dir": str(tmp_path / "data"),
                                "web": {"port": port}}), encoding="utf-8")
    if start_bat:
        (tmp_path / "Start.bat").write_text("@echo off\r\n", encoding="ascii")
    import argparse
    return argparse.Namespace(config=str(path), after_pid=4321, created="777")


class Mono:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_helper_waits_for_old_one_then_starts_once(tmp_path):
    proc, mono, started = Proc(alive_for=3), Mono(), []
    rc = cli.cmd_restart(_helper_args(tmp_path), alive=proc.alive, kill=proc.kill, is_up=lambda port: False,
                         running=lambda config: False, start=started.append, sleep=mono.sleep, clock=mono)
    assert rc == 0 and proc.killed == [] and started == [os.path.abspath(str(tmp_path))]


def test_helper_kills_a_stuck_old_one_like_stop_bat(tmp_path):
    proc, mono, started = Proc(alive_for=10 ** 9), Mono(), []
    rc = cli.cmd_restart(_helper_args(tmp_path), alive=proc.alive, kill=proc.kill, is_up=lambda port: False,
                         running=lambda config: False, start=started.append, sleep=mono.sleep, clock=mono)
    assert rc == 0 and proc.killed == [4321] and len(started) == 1
    assert mono.t >= restart.STOP_WAIT


def test_helper_never_starts_a_second_copy(tmp_path):
    mono, started = Mono(), []
    rc = cli.cmd_restart(_helper_args(tmp_path), alive=lambda p, c: False, kill=None, is_up=lambda port: False,
                         running=lambda config: True, start=started.append, sleep=mono.sleep, clock=mono)
    assert rc == 0 and started == []                               # 別的地方已經開了一支：不再開


def test_helper_gives_up_when_port_stays_busy_or_start_bat_is_missing(tmp_path):
    mono, started = Mono(), []
    rc = cli.cmd_restart(_helper_args(tmp_path), alive=lambda p, c: False, is_up=lambda port: True,
                         running=lambda config: False, start=started.append, sleep=mono.sleep, clock=mono)
    assert rc == 1 and started == []
    other = tmp_path / "b"
    other.mkdir()
    rc = cli.cmd_restart(_helper_args(other, start_bat=False), alive=lambda p, c: False, is_up=lambda port: False,
                         running=lambda config: False, start=started.append, sleep=mono.sleep, clock=Mono())
    assert rc == 1 and started == []


def test_helper_parser_accepts_the_spawned_command_line(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_restart", lambda args: seen.setdefault("args", args) and 0)
    argv = restart.helper_command("py", 4321, 777, "C:\\S\\config.json")
    cli.main(argv[argv.index("synox") + 1:])
    args = seen["args"]
    assert args.config == "C:\\S\\config.json" and args.after_pid == 4321 and args.created == "777"
    assert restart.helper_command("py", 1, None, "")[5:] == ["py", "-m", "synox", "restart", "--after-pid", "1"]


def test_wait_seconds_is_zero_when_fresh(tmp_path):
    r = restart.Restarter(str(tmp_path), str(tmp_path), mode="launcher", spawn=lambda a, c: None, clock=time.time)
    assert r.wait_seconds() == 0 and r.status([])["can"] is True and r.status(["x"])["pending"] is True


# ── 選單的 JS（tests/js/test_usermenu.js）與 app.html 的接線 ────────────

def test_usermenu_js_with_node():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_usermenu.js 沒跑")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([node, os.path.join(root, "tests", "js", "test_usermenu.js")], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_app_page_wires_the_menu(owner_restart):
    _bot, _ui, c = owner_restart
    status, _h, body = c.raw("GET", "/")
    html = body.decode("utf-8")
    assert status == 200
    menu = html.split('id="user-menu"', 1)[1]
    assert 'role="menu"' in menu[:80]
    for item in ("um-restart", "um-notify", 'href="#settings"', 'href="#settings:appearance"', 'href="#settings:help"',
                 "um-logout"):
        assert item in menu, item
    assert html.count('role="menuitem"') == 7 and 'role="separator"' in menu
    assert 'id="logout"' not in html                               # 舊的登出鈕拿掉了（notify.js 找不到就排在最後）
    assert "⟳" in html.split('id="restart-btn"', 1)[1][:200]
    assert "data-restart-now" in html.split('id="ch-restart"', 1)[1][:600]   # 黃色提示的「立即重新啟動」
    assert "window.SynoxUserMenu" in html and 'aria-haspopup="menu"' in html
