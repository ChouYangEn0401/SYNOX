"""保持清醒（docs/adr/0006）：假的 Windows 電源，不碰真的電腦睡眠設定。"""

import pytest

from synox.runtime import settings as rs
from synox.runtime.keepawake import R_UNSUPPORTED, TASK_ID, KeepAwake


class FakePower:
    available = True

    def __init__(self, hold_ok=True, timeout=(18000, 180)):
        self._handle = None
        self.hold_ok = hold_ok
        self.display = False
        self.timeout = tuple(timeout)                 # 電源計畫「關閉顯示器前的時間」（插電, 電池）秒
        self.writes = []

    def hold(self, reason):
        if not self.hold_ok:
            return False
        self._handle = 1
        return True

    def release(self):
        self._handle = None
        self.display = False

    def keep_display(self, on):
        self.display = bool(on) and bool(self._handle)

    def display_timeout(self):
        return self.timeout

    def set_display_timeout(self, ac, dc):
        self.timeout = (ac, dc)
        self.writes.append((ac, dc))


class FakeTask:
    def set_schedule_text(self, text):
        self.text = text


class FakeLoop:
    def __init__(self):
        self.intervals = {}
        self.t = FakeTask()

    def register(self, task_id, name, *, fn, interval, timeout):
        self.intervals[task_id] = interval
        return self.t

    def reschedule(self, task_id, interval):
        self.intervals[task_id] = interval
        return self.t

    def task(self, task_id):
        return self.t


def make(enabled=True, minutes=0, **power):
    p = FakePower(**power)
    return KeepAwake(FakeLoop(), settings={"enabled": enabled, "screen_off_after_min": minutes}, power=p), p


def test_defaults_are_off_and_validated():
    ka = rs.defaults()["keep_awake"]
    assert ka == {"enabled": False, "screen_off_after_min": 0}
    assert rs.parse({"keep_awake": {"enabled": True, "screen_off_after_min": 10}})["keep_awake"]["enabled"] is True
    assert rs.parse({"keep_awake": {"screen_off_after_min": -1}})["keep_awake"]["screen_off_after_min"] == -1
    assert rs.parse({"keep_awake": {"screen_off_after_min": 600}})["keep_awake"]["screen_off_after_min"] == 600
    for bad in ({"enabled": "yes"}, {"screen_off_after_min": -2}, {"screen_off_after_min": 10 ** 9},
                {"screen_off_after_min": True}):
        with pytest.raises(rs.RuntimeConfigError):
            rs.parse({"keep_awake": bad})


def test_disabled_does_nothing_and_has_no_schedule():
    ka, power = make(enabled=False)
    ka.register()
    assert ka.loop.intervals[TASK_ID] is None
    assert power._handle is None


def test_enabled_holds_the_request_on_register_and_releases_on_stop():
    ka, power = make()
    ka.register()
    assert power._handle and ka.loop.intervals[TASK_ID] == 60.0
    assert ka.view()["holding"] is True
    ka.release()
    assert power._handle is None


def test_failure_to_hold_raises_so_the_task_shows_failed():
    ka, _ = make(hold_ok=False)
    with pytest.raises(RuntimeError):
        ka.run()
    ka.register()                       # register 不能因為這樣讓 SYNOX 起不來


def test_screen_follows_windows_plan_by_default():
    ka, power = make(minutes=0)
    ka.run()
    assert power.writes == [] and power.display is False


def test_screen_timer_is_written_to_the_plan_and_restored():
    """2026-11-13 hotfix：不再廣播 SC_MONITORPOWER（現代待命上＝按睡眠鍵）；改設電源計畫的「關閉螢幕」，停用時改回。"""
    import synox.runtime.keepawake as k
    assert not hasattr(k, "SC_MONITORPOWER") and not hasattr(k.WinPower, "screen_off")
    ka, power = make(minutes=300)
    ka.run()
    ka.run()
    assert power.writes == [(18000, 18000)]                 # 只寫一次，不每分鐘重寫
    ka.update(enabled=False)
    assert power.timeout == (18000, 180)                     # 改回原本的（插電 300 分、電池 3 分）


def test_screen_timer_change_and_back_to_zero():
    ka, power = make(minutes=10)
    ka.run()
    ka.update(screen_off_after_min=20)
    assert power.timeout == (1200, 1200)
    ka.update(screen_off_after_min=0)
    assert power.timeout == (18000, 180)


def test_user_change_in_windows_is_not_fought_or_overwritten():
    ka, power = make(minutes=10)
    ka.run()
    power.timeout = (60, 60)                                 # 使用者自己在 Windows 設定改了
    ka.run()
    assert power.timeout == (60, 60)
    ka.release()
    assert power.timeout == (60, 60)                         # 不是我們寫的值：不改回


def test_minus_one_keeps_the_screen_on():
    ka, power = make(minutes=-1)
    assert "永不關" in ka.run()
    assert power.display is True and ka.view()["display_required"] is True
    ka.update(screen_off_after_min=0)
    assert power.display is False


def test_no_upper_limit_beyond_overflow_guard():
    ka, power = make(minutes=0)
    ka.update(screen_off_after_min=600)
    assert power.timeout == (36000, 36000)


def test_update_toggles_and_validates():
    ka, power = make(enabled=False)
    assert ka.update(enabled=True)["holding"] is True
    assert ka.loop.intervals[TASK_ID] == 60.0
    assert ka.update(screen_off_after_min=15)["screen_off_after_min"] == 15
    for bad in (-2, 10 ** 9, 1.5, True, "5"):
        with pytest.raises(ValueError):
            ka.update(screen_off_after_min=bad)
    assert ka.update(enabled=False)["holding"] is False
    assert power._handle is None and ka.loop.intervals[TASK_ID] is None


def test_unsupported_platform_is_not_a_failure():
    ka, power = make()
    power.available = False
    assert ka.run() == R_UNSUPPORTED
    assert ka.view()["modern_standby"] is None and ka.view()["modern_standby_note"] == ""


# ── 2026-11-13 附記：預設關、打開時講清楚、現代待命 ─────────────────────

def test_keep_awake_is_off_by_default_everywhere(tmp_path):
    """擁有者：SYNOX 裡保持清醒必須預設關閉——新安裝、舊 config 沒有這一塊、沒有 runtime 都是關。"""
    import json
    import os
    from synox.config import SynoxConfig
    from synox.wizard import logic
    assert rs.DEFAULT_RUNTIME["keep_awake"]["enabled"] is False
    assert rs.parse(None)["keep_awake"]["enabled"] is False
    assert rs.parse({})["keep_awake"]["enabled"] is False
    assert rs.parse({"keep_awake": {}})["keep_awake"]["enabled"] is False                       # 舊 config 缺欄位
    assert rs.parse({"keep_awake": {"screen_off_after_min": 5}})["keep_awake"]["enabled"] is False
    assert rs.parse({"heartbeat": {"interval_min": 30}})["keep_awake"]["enabled"] is False
    old = SynoxConfig.from_dict({"owner_id": 1}, require_token=False, root=str(tmp_path))
    assert old.runtime["keep_awake"]["enabled"] is False
    fresh = logic.build_config("", logic.local_owner_id(), {"kind": "none"})                   # 精靈新安裝寫的
    assert fresh["runtime"]["keep_awake"]["enabled"] is False
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config.example.json"), encoding="utf-8") as f:
        assert json.load(f)["runtime"]["keep_awake"]["enabled"] is False


def test_view_carries_the_notice_and_modern_standby_note():
    from synox.runtime.keepawake import MS_NOTE, NOTICE, TAGLINE
    for words in ("覆蓋 Windows 電源選項", "「睡眠」", "不再自動睡眠", "閒置 N 分鐘後主動關螢幕", "保護螢幕", "省電",
                  "闔上筆電蓋", "手動睡眠", "低電量", "Windows Update"):
        assert words in NOTICE, words
    assert "heartbeat" in TAGLINE and "螢幕可以暗" in TAGLINE
    ka, power = make(enabled=False)
    view = ka.view()
    assert view["notice"] == NOTICE and view["tagline"] == TAGLINE
    assert view["modern_standby"] is None and view["modern_standby_note"] == ""     # 假電源沒有這個能力：不知道
    power.modern_standby = lambda: True
    view = ka.view()
    assert view["modern_standby"] is True and view["modern_standby_note"] == MS_NOTE
    assert "現代待命" in MS_NOTE and "keep-awake-troubleshooting" in MS_NOTE
    power.modern_standby = lambda: False
    assert ka.view()["modern_standby_note"] == ""


class FakeKernel32:
    """假的 kernel32／powrprof：記下設了哪些電源請求；絕不碰真的電腦。"""

    def __init__(self, execution_ok=True, aoac=1, status=0):
        self.set, self.cleared, self.closed = [], [], []
        self.execution_ok, self.aoac, self.status = execution_ok, aoac, status
        self.PowerCreateRequest = self._fn(lambda ctx: 1234)
        self.PowerSetRequest = self._fn(self._set)
        self.PowerClearRequest = self._fn(lambda h, kind: self.cleared.append(kind) or 1)
        self.CloseHandle = self._fn(lambda h: self.closed.append(h) or 1)
        self.CallNtPowerInformation = self._fn(self._info)

    @staticmethod
    def _fn(f):
        class F:
            restype = None
            argtypes = None

            def __call__(self, *a):
                return f(*a)
        return F()

    def _set(self, handle, kind):
        self.set.append(kind)
        return 0 if (kind == 3 and not self.execution_ok) else 1

    def _info(self, level, inp, inlen, out, outlen):
        assert level == 4 and outlen == 76                       # SystemPowerCapabilities
        out._obj[20] = self.aoac                                  # AoAc
        return self.status


def _fake_dll(monkeypatch, k32):
    import ctypes
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kw: k32, raising=False)


def test_hold_sets_system_and_execution_required(monkeypatch):
    from synox.runtime.keepawake import (POWER_REQUEST_EXECUTION_REQUIRED, POWER_REQUEST_SYSTEM_REQUIRED, WinPower)
    k32 = FakeKernel32()
    _fake_dll(monkeypatch, k32)
    power = WinPower()
    assert power.hold("SYNOX") is True and power.execution is True
    assert k32.set == [POWER_REQUEST_SYSTEM_REQUIRED, POWER_REQUEST_EXECUTION_REQUIRED]
    assert power.hold("SYNOX") is True and len(k32.set) == 2                     # 已經有就不重複
    power.release()
    assert sorted(k32.cleared) == [POWER_REQUEST_SYSTEM_REQUIRED, POWER_REQUEST_EXECUTION_REQUIRED]
    assert k32.closed == [1234] and power._handle is None


def test_execution_required_is_best_effort(monkeypatch):
    from synox.runtime.keepawake import POWER_REQUEST_SYSTEM_REQUIRED, WinPower
    k32 = FakeKernel32(execution_ok=False)
    _fake_dll(monkeypatch, k32)
    power = WinPower()
    assert power.hold("SYNOX") is True and power.execution is False              # 舊版 Windows：系統清醒照樣拿著
    power.release()
    assert k32.cleared == [POWER_REQUEST_SYSTEM_REQUIRED]


def test_modern_standby_reads_aoac(monkeypatch):
    from synox.runtime.keepawake import WinPower
    _fake_dll(monkeypatch, FakeKernel32(aoac=1))
    assert WinPower().modern_standby() is True
    _fake_dll(monkeypatch, FakeKernel32(aoac=0))
    assert WinPower().modern_standby() is False
    _fake_dll(monkeypatch, FakeKernel32(status=0xC0000022))                     # 讀不到＝不知道
    assert WinPower().modern_standby() is None


def test_web_settings_toggle_and_notice(make_bot, owner, tmp_path):
    """網頁設定頁的「保持清醒」卡片：GET /api/runtime/status、POST /api/runtime/keep-awake；假電源，不碰真的睡眠設定。"""
    import json
    import os
    from synox import runtime
    from synox.runtime.keepawake import NOTICE
    from test_web import Client, ui_of
    bot = make_bot()
    rt = runtime.of(bot.app)
    rt.keep_awake.power = FakePower()
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.get("/api/runtime/status")
    assert status == 200 and data["keep_awake"]["enabled"] is False and data["keep_awake"]["notice"] == NOTICE
    status, data = c.post("/api/runtime/keep-awake", {"enabled": True, "screen_off_after_min": 10})
    assert status == 200 and data["enabled"] is True and data["holding"] is True and data["notice"] == NOTICE
    cfg = json.load(open(ui_of(bot).config_path, encoding="utf-8"))
    assert cfg["runtime"]["keep_awake"] == {"enabled": True, "screen_off_after_min": 10}
    assert c.post("/api/runtime/keep-awake", {"screen_off_after_min": -5})[0] == 400
    assert c.post("/api/runtime/keep-awake", {"screen_off_after_min": 999})[0] == 200     # 不再限 4 小時
    status, data = c.post("/api/runtime/keep-awake", {"enabled": False})
    assert data["enabled"] is False and data["holding"] is False and rt.keep_awake.power._handle is None
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "src", "synox", "web", "static", "app.html"), encoding="utf-8").read()
    assert 'id="set-awake"' in html and "/api/runtime/keep-awake" in html and NOTICE in html


def test_doctor_line_mentions_the_override_and_modern_standby(monkeypatch):
    from types import SimpleNamespace
    from synox import doctor
    from synox.runtime import keepawake
    off = doctor._keep_awake_line(SimpleNamespace(runtime={"keep_awake": {"enabled": False}}))
    assert "預設" in off and keepawake.NOTICE in off
    monkeypatch.setattr(keepawake.WinPower, "modern_standby", lambda self: True)
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    on = doctor._keep_awake_line(SimpleNamespace(runtime={"keep_awake": {"enabled": True, "screen_off_after_min": 0}}))
    assert keepawake.NOTICE in on and keepawake.MS_NOTE in on
