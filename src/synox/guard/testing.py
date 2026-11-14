"""給測試用的小工具（正式程式不要 import）。

    with as_origin("ai", user_id=42): ...      # 這段的來源是 AI
"""

from __future__ import annotations

import contextlib

from synox.guard.origin import Origin, using


@contextlib.contextmanager
def as_origin(kind: str, user_id: int = 0, surface: str = "", on_behalf=None):
    with using(Origin(kind, user_id, surface=surface or kind, on_behalf=on_behalf)) as o:
        yield o


class Clock:
    """假時鐘：clock() 回現在；clock.t += 30 跳到下一組碼。"""

    def __init__(self, t: float = 1_700_000_000.0):
        self.t = float(t)

    def __call__(self) -> float:
        return self.t


def code_for(secret: str, clock) -> str:
    """這把金鑰在 clock() 這一刻的 6 位數。"""
    from isdtelekit.security import totp
    return totp.code_at(secret, totp.counter_now(clock()))


def use_clock(guard, clock) -> None:
    """把門禁核心的驗證器換成假時鐘（解鎖視窗、錯誤次數一起換）。"""
    hub = getattr(guard, "stepup", guard)
    hub.clock = clock
    hub.attempts.clock = clock


def enroll(guard, user_id: int, clock=None, *, protect: bool = False) -> str:
    """幫 user_id 設定好驗證器（在本機網頁設定的樣子），回金鑰。clock 給了就換成它；設定完把時鐘往後推 30 秒。"""
    hub = getattr(guard, "stepup", guard)
    if clock is not None:
        use_clock(hub, clock)
    data = hub.begin(user_id)
    with as_origin("web", user_id, surface="web:enroll"):
        hub.confirm(user_id, code_for(data["secret"], hub.clock))
        if protect:
            hub.set_protect(user_id, True, origin=Origin("web", user_id, surface="web:enroll"))
    if clock is not None:
        clock.t += 30
    return data["secret"]
