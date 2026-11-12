"""保持清醒（docs/adr/0006）：假的 Windows 電源，不碰真的電腦睡眠設定。"""

import pytest

from synox.runtime import settings as rs
from synox.runtime.keepawake import R_UNSUPPORTED, TASK_ID, KeepAwake


class FakePower:
    available = True

    def __init__(self, idle=0.0, hold_ok=True):
        self._handle = None
        self.idle = idle
        self.hold_ok = hold_ok
        self.blanks = 0

    def hold(self, reason):
        if not self.hold_ok:
            return False
        self._handle = 1
        return True

    def release(self):
        self._handle = None

    def idle_seconds(self):
        return self.idle

    def screen_off(self):
        self.blanks += 1


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
    for bad in ({"enabled": "yes"}, {"screen_off_after_min": 241}, {"screen_off_after_min": -1},
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


def test_screen_off_follows_windows_unless_asked():
    ka, power = make(minutes=0, idle=99999)
    ka.run()
    assert power.blanks == 0


def test_screen_off_after_idle_only_once_per_idle_period():
    ka, power = make(minutes=5, idle=299)
    ka.run()
    assert power.blanks == 0
    power.idle = 301
    ka.run()
    ka.run()
    assert power.blanks == 1                       # 同一段閒置只關一次，不然一動滑鼠又被關掉
    power.idle = 2                                 # 有人用過
    ka.run()
    power.idle = 400
    ka.run()
    assert power.blanks == 2


def test_update_toggles_and_validates():
    ka, power = make(enabled=False)
    assert ka.update(enabled=True)["holding"] is True
    assert ka.loop.intervals[TASK_ID] == 60.0
    assert ka.update(screen_off_after_min=15)["screen_off_after_min"] == 15
    for bad in (-1, 241, 1.5, True, "5"):
        with pytest.raises(ValueError):
            ka.update(screen_off_after_min=bad)
    assert ka.update(enabled=False)["holding"] is False
    assert power._handle is None and ka.loop.intervals[TASK_ID] is None


def test_unsupported_platform_is_not_a_failure():
    ka, power = make()
    power.available = False
    assert ka.run() == R_UNSUPPORTED
