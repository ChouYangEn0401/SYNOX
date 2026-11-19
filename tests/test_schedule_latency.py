# -*- coding: utf-8 -*-
"""提醒準時（排程延遲）：runtime 睡到下一件事、next_hint、poke；提醒引擎的 next_wake；哨兵睡到下一件事。

全部假時鐘、同步執行；不開視窗、不連網。
"""

from datetime import datetime, timedelta

import pytest

from synox import runtime
from synox.runtime import loop as loopmod
from synox.runtime.loop import RuntimeLoop
from synox.schedule import engine as E
from synox.schedule import reminder as R
from synox.schedule.store import ScheduleStore

T0 = datetime(2026, 11, 12, 13, 59, 50)


class Clock:
    def __init__(self, start=T0):
        self.dt = start

    def __call__(self):
        return self.dt.timestamp()

    def now(self):
        return self.dt

    def advance(self, **kw):
        self.dt += timedelta(**kw)


def sync(fn, name):
    fn()


class FakeApp:
    def __init__(self):
        self.extras = {}

    def notify_owner(self, text):
        pass


def make_loop(tmp_path, clock):
    return RuntimeLoop(FakeApp(), clock=clock, spawn=sync, state_path=str(tmp_path / "state.json"))


# ── runtime loop ────────────────────────────────────────────────────

def test_loop_sleeps_until_the_earliest_due_task(tmp_path):
    clock = Clock()
    loop = make_loop(tmp_path, clock)
    assert loop.sleep_for() == loopmod.TICK_SECONDS                     # 沒有任務：最多睡 TICK_SECONDS
    loop.register("a.slow", "慢", fn=lambda ctx: "ok", interval=3600)
    loop.register("a.fast", "快", fn=lambda ctx: "ok", interval=10, first_delay=1.5)
    assert loop.sleep_for() == pytest.approx(1.5)                       # 睡到 1.5 秒後那一個，不是 5 秒一格
    clock.advance(seconds=2)
    assert loop.sleep_for() == loopmod.MIN_SLEEP                        # 已經過了：馬上
    assert loop.tick() == ["a.fast"]
    assert loop.sleep_for() == loopmod.TICK_SECONDS                     # 下一個在 10 秒後：最多睡 5 秒（看逾時）


def test_other_tasks_keep_their_own_interval(tmp_path):
    clock = Clock()
    loop = make_loop(tmp_path, clock)
    runs = {"hint": 0, "weekly": 0}
    loop.register("system.schedule", "提醒", fn=lambda ctx: runs.__setitem__("hint", runs["hint"] + 1) or "ok",
                  interval=10, first_delay=0, next_hint=lambda now: now + 2)
    loop.register("system.update", "每週", fn=lambda ctx: runs.__setitem__("weekly", runs["weekly"] + 1) or "ok",
                  interval=6 * 3600)
    for _ in range(600):                                                # 走 10 分鐘，每 1 秒看一次
        loop.tick()
        clock.advance(seconds=1)
    assert runs["weekly"] == 0                                          # 6 小時的不會因為別人常跑就跟著跑
    assert 295 <= runs["hint"] <= 301                                    # 提醒那個照 hint 每 2 秒


def test_next_hint_pulls_the_next_run_earlier_but_never_later(tmp_path):
    clock = Clock()
    loop = make_loop(tmp_path, clock)
    hint = [None]
    t = loop.register("system.schedule", "提醒", fn=lambda ctx: "ok", interval=10, first_delay=0,
                      next_hint=lambda now: hint[0])
    hint[0] = clock() + 3.25
    loop.tick()
    assert t.next_due == pytest.approx(clock() + 3.25)
    clock.advance(seconds=4)
    hint[0] = clock() + 60                                              # 比間隔晚：照間隔（間隔是上限）
    loop.tick()
    assert t.next_due == pytest.approx(clock() + 10)
    clock.advance(seconds=10)
    hint[0] = clock() - 5                                               # 回了過去的時間：不空轉
    loop.tick()
    assert t.next_due == pytest.approx(clock() + loopmod.HINT_MIN_GAP)
    clock.advance(seconds=1)

    def boom(now):
        raise RuntimeError("x")
    t.next_hint = boom                                                  # hint 壞了：照間隔，任務不算失敗
    loop.tick()
    assert t.state == "ok" and t.next_due == pytest.approx(clock() + 10)


def test_poke_runs_the_task_now_and_wakes_the_loop(tmp_path):
    clock = Clock()
    loop = make_loop(tmp_path, clock)
    seen = []
    t = loop.register("system.schedule", "提醒", fn=lambda ctx: seen.append(1) or "ok", interval=10)
    loop._wake.clear()
    assert loop.poke("system.schedule") and loop._wake.is_set()
    assert t.next_due == clock()
    assert loop.tick() == ["system.schedule"] and seen == [1]
    assert not loop.poke("nope")
    t.running_since = clock()                                           # 正在跑：不管（做完時的 hint 會看到新的）
    assert not loop.poke("system.schedule")


# ── 提醒引擎：下一件事幾點 ───────────────────────────────────────────

def _rem(**kw):
    base = dict(id=1, owner=1, text="喝水", created=0, repeat=R.ONCE, due=R.to_iso(datetime(2026, 11, 12, 14, 0)))
    base.update(kw)
    return R.Reminder(**base)


def test_wake_at_for_each_state():
    now = R.aware(T0)
    assert E.wake_at(_rem(), now) == R.aware(datetime(2026, 11, 12, 14, 0))
    assert E.wake_at(_rem(due=R.to_iso(datetime(2026, 11, 12, 13, 0))), now) is None     # 一次性、過了：tick 會處理
    daily_old = _rem(repeat=R.DAILY, due=R.to_iso(datetime(2026, 11, 10, 8, 30)))
    assert E.wake_at(daily_old, now) == R.aware(datetime(2026, 11, 13, 8, 30))           # 每天型：下一個牆上時刻
    snoozed = _rem(status=R.SNOOZED, occurrence=R.to_iso(datetime(2026, 11, 12, 13, 50)),
                   snooze_until=R.to_iso(datetime(2026, 11, 12, 14, 5)), snooze_count=1)
    assert E.wake_at(snoozed, now) == R.aware(datetime(2026, 11, 12, 14, 5))
    ringing = _rem(status=R.RINGING, occurrence=R.to_iso(datetime(2026, 11, 12, 13, 0)),
                   rang_at=R.to_iso(datetime(2026, 11, 12, 13, 0)))
    assert E.wake_at(ringing, now) == R.aware(datetime(2026, 11, 13, 13, 0))             # 24 小時沒人回要收掉
    assert E.wake_at(_rem(status=R.DONE), now) is None
    assert E.wake_at(_rem(due=None, repeat=R.NONE), now) is None                          # 待辦


def test_engine_next_wake_reads_all_lists(tmp_path):
    store = ScheduleStore(str(tmp_path))
    eng = E.ReminderEngine(store, deliver=lambda msg: None)
    assert eng.next_wake(T0) is None
    store.add_reminder(lambda i: R.new_reminder(i, 1, "晚", due=datetime(2026, 11, 12, 18, 0)))
    store.add_reminder(lambda i: R.new_reminder(i, 1, "早", due=datetime(2026, 11, 12, 14, 0, 30)))
    assert eng.next_wake(T0) == R.aware(datetime(2026, 11, 12, 14, 0, 30))


def test_store_listener_fires_on_every_write(tmp_path):
    store = ScheduleStore(str(tmp_path), per_user=True)
    calls = []
    store.add_listener(lambda: calls.append(1))
    mine = store.of(42)                                                 # 伺服器版每人一份：共用同一串 listener
    mine.add_reminder(lambda i: R.new_reminder(i, 42, "x", due=datetime(2026, 11, 12, 14, 0)))
    mine.update_reminder(1, lambda r: r)
    assert len(calls) == 2


# ── 整個串起來：主程式的 system.schedule ───────────────────────────────

@pytest.fixture
def rt_app(make_bot):
    bot = make_bot()
    clock = Clock()
    rt = runtime.of(bot.app)
    rt.use_fakes(clock=clock, now=clock.now, spawn=sync)
    rt.loop.started = True
    runner = bot.app.extras["synox_schedule_runner"]
    runner._clock = clock.now
    return bot, rt, clock, runner


def test_alarm_fires_on_the_second(rt_app):
    bot, rt, clock, runner = rt_app
    task = rt.loop.task("system.schedule")
    assert task.interval == 10
    due = datetime(2026, 11, 12, 14, 0, 0)
    runner.store.add_reminder(lambda i: R.new_reminder(i, bot.app.owner_id, "喝水", due=due))
    assert task.next_due == clock()                                     # 新增＝poke：馬上重看一次
    rt.loop.tick()
    assert task.next_due == pytest.approx(R.aware(due).timestamp())     # 睡到 14:00:00，不是 +30 秒
    clock.advance(seconds=9)                                            # 13:59:59
    assert "system.schedule" not in rt.loop.tick() and not any("喝水" in m for m in bot.texts())
    assert rt.loop.sleep_for() <= 1.0
    clock.advance(seconds=1)                                            # 14:00:00
    assert "system.schedule" in rt.loop.tick()
    assert any("喝水" in m and "晚了" not in m for m in bot.texts())


def test_snooze_from_another_thread_is_picked_up(rt_app):
    bot, rt, clock, runner = rt_app
    task = rt.loop.task("system.schedule")
    clock.advance(seconds=10)                                           # 14:00:00
    due = datetime(2026, 11, 12, 14, 0, 0)
    runner.store.add_reminder(lambda i: R.new_reminder(i, bot.app.owner_id, "喝水", due=due))
    rt.loop.tick()                                                      # 響了
    item = runner.store.raw_items()[0]
    assert item["status"] == R.RINGING
    until = R.aware(datetime(2026, 11, 12, 14, 3, 0))
    runner.store.update_reminder(1, lambda r: R.Reminder.from_dict({**r.to_dict(), "status": R.SNOOZED,
                                                                    "snooze_until": R.to_iso(until),
                                                                    "snooze_count": 1}))
    assert task.next_due == clock()                                     # 延後（別的執行緒寫的）＝poke
    rt.loop.tick()
    assert task.next_due == pytest.approx(until.timestamp())


# ── 哨兵 ─────────────────────────────────────────────────────────────

class _Lock:
    held = True

    def beat(self):
        pass

    def release(self):
        self.held = False


class _Engine:
    def __init__(self, wake):
        self.wake = wake
        self.ticks = []

    def tick(self, at):
        self.ticks.append(at)

    def next_wake(self, at):
        return self.wake


class _Nop:
    def pump(self, now=None):
        pass

    def process(self, outbox, actions):
        pass


def test_sentinel_ticks_at_the_next_wake(tmp_path):
    from synox.remindwin import sentinel as S
    clock = Clock()
    eng = _Engine(datetime(2026, 11, 12, 14, 0, 0))
    s = S.Sentinel(str(tmp_path), build=lambda: None, clock=clock)
    s.lock = _Lock()
    s.round = S.Round(engine=eng, outbox=_Nop(), desk=_Nop())
    s._round(clock())
    assert len(eng.ticks) == 1
    assert s.sleep_for(step_s=2.0) == 2.0                               # 14:00 還有 10 秒：照常每 2 秒一步
    clock.advance(seconds=9)
    s._round(clock())
    assert len(eng.ticks) == 1                                          # 還沒到、也還沒滿 ENGINE_TICK_S
    assert s.sleep_for(step_s=2.0) == pytest.approx(1.0)               # 睡到 14:00:00 就好
    clock.advance(seconds=1)
    s._round(clock())
    assert len(eng.ticks) == 2                                          # 到了：不等 ENGINE_TICK_S
