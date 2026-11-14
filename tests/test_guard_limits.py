"""門禁核心：次數（ADR 0025 §4）。假時鐘。"""

import pytest

from synox.guard.limits import Attempts, Rate

pytestmark = pytest.mark.usefixtures("no_sockets")


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_four_fails_do_not_lock_fifth_does_then_unlocks():
    clock = Clock()
    a = Attempts(clock=clock)
    assert [a.fail("u") for _ in range(4)] == [False] * 4 and a.locked("u") == 0
    assert a.fail("u") is True
    assert a.locked("u") == 900
    assert a.fail("u") is False                # 鎖著時再錯不會再「剛被鎖」一次
    clock.t += 899
    assert a.locked("u") > 0
    clock.t += 2
    assert a.locked("u") == 0


def test_ok_resets_and_window_expires():
    clock = Clock()
    a = Attempts(clock=clock)
    for _ in range(4):
        a.fail("u")
    a.ok("u")
    assert a.fail("u") is False and a.count("u") == 1
    clock.t += 901                             # 窗口外的錯不算
    for _ in range(4):
        assert a.fail("u") is False
    assert a.count("u") == 4
    assert a.fail("v") is False                # 每個鍵各算


def test_rate():
    clock = Clock()
    r = Rate(3, clock=clock)
    assert [r.allow("k") for _ in range(4)] == [True, True, True, False]
    clock.t += 60
    assert r.allow("k")
