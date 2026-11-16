"""提醒引擎（docs/adr/0029 §3.1）：錯過的那一分鐘下一次檢查會響；停 3 小時逐則說錯過、停 7 小時併成一則；
送不出去不刪；24 小時沒人回收掉；每天型；延後與完成；舊的 schedule.json 讀得進來；引擎停了會說。
全部用假的 deliver（送達層 W2 還沒合併），不連網、不碰真的管道。"""

import json
import os
import time
from datetime import datetime, timedelta

import pytest

from synox.notify import delivery
from synox.schedule import reminder
from synox.schedule.actions import Actions
from synox.schedule.store import ScheduleStore

UID = 1001


def ticket(msg, state=delivery.SENT, next_try=None):
    rec = delivery.DeliveryRecord("telegram", state=state, tries=1, first_try=1.0, last_try=1.0, next_try=next_try,
                                  ok_at=1.0 if state == delivery.SENT else None)
    return delivery.DeliveryTicket(msg.key, msg.uid, {"telegram": rec})


class FakeDeliver:
    def __init__(self, mode="ok"):
        self.msgs = []
        self.mode = mode

    def __call__(self, msg):
        self.msgs.append(msg)
        if self.mode == "boom":
            raise ConnectionError("送達層掛了")
        if self.mode == "fail":
            return ticket(msg, delivery.FAILED, next_try=time.time() + 30)
        return ticket(msg)

    def texts(self):
        return [m.text for m in self.msgs]


class Resolves(list):
    def __call__(self, uid, key, note="", via=""):
        self.append((uid, key, note, via))


def engine(tmp_path, mode="ok"):
    fake, res = FakeDeliver(mode), Resolves()
    eng = reminder.headless_engine(str(tmp_path), None, fake, resolve=res)
    return eng, fake, res


def seed(tmp_path, text, due, repeat="once", created=None):
    store = ScheduleStore(str(tmp_path))
    created = created if created is not None else int((due - timedelta(days=2)).timestamp())
    return store.add_reminder(lambda rid: reminder.new_reminder(rid, UID, text, due=due, repeat=repeat,
                                                                created=created))


def raw(tmp_path):
    return ScheduleStore(str(tmp_path)).raw_items()


D = datetime(2026, 11, 16)


# ── 到點 ─────────────────────────────────────────────────────────────

def test_missed_minute_rings_on_next_check(tmp_path):
    eng, fake, _ = engine(tmp_path)
    seed(tmp_path, "倒垃圾", D.replace(hour=8))
    assert eng.tick(D.replace(hour=7, minute=59, second=45)) == []
    fired = eng.tick(D.replace(hour=8, minute=1, second=5))             # 08:00 那一分鐘沒有檢查到
    assert [f["text"] for f in fired] == ["倒垃圾"]
    assert fake.texts()[0].startswith("⏰ 提醒：倒垃圾") and "晚了 1 分鐘" in fake.texts()[0]
    msg = fake.msgs[0]
    assert msg.key == delivery.message_key(1, reminder.to_iso(D.replace(hour=8)), UID)
    assert msg.ref == delivery.ReminderRef(1, reminder.to_iso(D.replace(hour=8)))
    assert [a["id"] for a in msg.actions] == ["ok", "snooze"]
    assert eng.tick(D.replace(hour=8, minute=1, second=40)) == [] and len(fake.msgs) == 1     # 冪等


def test_daily_rings_each_day_and_keeps_history(tmp_path):
    eng, fake, res = engine(tmp_path)
    seed(tmp_path, "吃藥", D.replace(hour=8), repeat="daily")
    assert len(eng.tick(D.replace(hour=8, minute=0, second=10))) == 1
    item = raw(tmp_path)[0]
    assert item["status"] == "ringing" and reminder.from_iso(item["due"]) == reminder.aware(D.replace(day=17, hour=8))
    assert item["time"] == "08:00" and item["date"] == "" and item["last_run"] == "2026-11-16"
    assert len(eng.tick(D.replace(day=17, hour=8, minute=0, second=10))) == 1           # 隔天照響
    item = raw(tmp_path)[0]
    assert [h["status"] for h in item["history"]] == ["expired"] and len(res) == 1     # 上一次沒人按：收掉
    assert len(fake.msgs) == 2 and fake.msgs[0].key != fake.msgs[1].key


def test_three_hours_late_says_missed_one_by_one(tmp_path):
    eng, fake, _ = engine(tmp_path)
    seed(tmp_path, "倒垃圾", D.replace(hour=9))
    seed(tmp_path, "收衣服", D.replace(hour=9, minute=30))
    assert eng.tick(D.replace(hour=12)) == []                            # 沒有照常響的
    assert len(fake.msgs) == 2
    assert all("你錯過了 1 個鬧鐘" in t for t in fake.texts())
    assert "今天 09:00 倒垃圾" in fake.texts()[0] and "今天 09:30 收衣服" in fake.texts()[1]
    assert all(it["status"] == "missed" for it in raw(tmp_path))
    eng.tick(D.replace(hour=12, minute=1))
    assert raw(tmp_path) == [] and len(fake.msgs) == 2                   # 送到了、處理完：拿掉，不再說


def test_seven_hours_late_folds_into_one(tmp_path):
    eng, fake, _ = engine(tmp_path)
    seed(tmp_path, "倒垃圾", D.replace(hour=1))
    seed(tmp_path, "收衣服", D.replace(hour=2))
    seed(tmp_path, "吃藥", D.replace(day=15, hour=8), repeat="daily", created=int(D.replace(day=1).timestamp()))
    eng.tick(D.replace(hour=9, minute=30))                               # 吃藥 08:00 晚 90 分鐘：一則說錯過
    texts = fake.texts()
    digest = [t for t in texts if t.startswith("⏰ 有 ")]
    assert len(digest) == 1 and "有 2 個提醒" in digest[0] and "倒垃圾" in digest[0] and "收衣服" in digest[0]
    assert any("你錯過了 1 個鬧鐘：今天 08:00 吃藥" in t for t in texts) and len(texts) == 2
    daily = next(it for it in raw(tmp_path) if it["text"] == "吃藥")
    assert reminder.from_iso(daily["due"]) == reminder.aware(D.replace(day=17, hour=8))  # 跳到明天，不補昨天的
    eng.tick(D.replace(hour=9, minute=31))
    assert len(fake.msgs) == 2


def test_daily_older_days_are_not_replayed(tmp_path):
    eng, fake, _ = engine(tmp_path)
    seed(tmp_path, "吃藥", D.replace(day=10, hour=8), repeat="daily")   # 好幾天沒開
    eng.tick(D.replace(hour=8, minute=5))
    assert len(fake.msgs) == 1 and "晚了 5 分鐘" in fake.texts()[0]       # 只響今天那一次


# ── 送不出去不刪 ─────────────────────────────────────────────────────

def test_failed_delivery_never_deletes(tmp_path):
    eng, fake, _ = engine(tmp_path, mode="fail")
    seed(tmp_path, "繳費", D.replace(hour=8))
    assert len(eng.tick(D.replace(hour=8, second=5))) == 1
    for minute in (1, 2, 3):
        eng.tick(D.replace(hour=8, minute=minute))
    items = raw(tmp_path)
    assert len(items) == 1 and items[0]["status"] == "ringing"
    assert items[0]["deliveries"]["telegram"]["state"] == "failed"
    assert len(fake.msgs) == 4 and len({m.key for m in fake.msgs}) == 1  # 每一輪再交給送達層（同一個 key）


def test_deliver_exception_retries_next_tick(tmp_path):
    eng, fake, _ = engine(tmp_path, mode="boom")
    seed(tmp_path, "繳費", D.replace(hour=8))
    assert eng.tick(D.replace(hour=8, second=5)) == []
    assert raw(tmp_path)[0]["status"] == "pending"                       # 沒送成：當作還沒處理
    fake.mode = "ok"
    assert len(eng.tick(D.replace(hour=8, second=35))) == 1


def test_failed_missed_notice_is_kept_until_settled(tmp_path):
    eng, fake, _ = engine(tmp_path, mode="fail")
    seed(tmp_path, "繳費", D.replace(hour=8))
    eng.tick(D.replace(hour=10))
    eng.tick(D.replace(hour=10, minute=1))
    assert len(raw(tmp_path)) == 1 and raw(tmp_path)[0]["status"] == "missed"


def test_ringing_expires_after_24_hours(tmp_path):
    eng, fake, res = engine(tmp_path)
    seed(tmp_path, "倒垃圾", D.replace(hour=8))
    eng.tick(D.replace(hour=8, second=5))
    eng.tick(D.replace(day=17, hour=7, minute=59))
    assert raw(tmp_path)[0]["status"] == "ringing"
    eng.tick(D.replace(day=17, hour=8, minute=0, second=6))
    assert raw(tmp_path)[0]["status"] == "expired" and res and "24 小時" in res[0][2]
    eng.tick(D.replace(day=17, hour=8, minute=1))
    assert raw(tmp_path) == []


# ── 延後與完成 ───────────────────────────────────────────────────────

def test_snooze_rings_again_and_done_is_idempotent(tmp_path):
    eng, fake, res = engine(tmp_path)
    seed(tmp_path, "倒垃圾", D.replace(hour=8))
    eng.tick(D.replace(hour=8, second=5))
    occ = reminder.to_iso(D.replace(hour=8))
    clock = [D.replace(hour=8, minute=1)]
    acts = Actions(ScheduleStore(str(tmp_path)), resolve=res, clock=lambda: clock[0])
    out = acts.act(UID, 1, occ, "snooze", typed="半小時後", via="desktop")
    assert out.ok and "08:31" in out.text and "電腦上" in out.note
    assert res[-1][1] == fake.msgs[0].key and res[-1][3] == "desktop"
    assert acts.act(UID, 1, "2026-01-01T00:00:00+08:00", "done").reason == "gone"   # 不是這一次
    assert raw(tmp_path)[0]["status"] == "snoozed"
    eng.tick(D.replace(hour=8, minute=30))
    assert len(fake.msgs) == 1
    eng.tick(D.replace(hour=8, minute=31, second=5))
    assert len(fake.msgs) == 2 and "延後第 1 次之後" in fake.texts()[1] and fake.msgs[1].key != fake.msgs[0].key
    out = acts.act(UID, 1, occ, "done", via="telegram")
    assert out.ok and "Telegram 上做完了" in out.note and res[-1][1] == fake.msgs[1].key
    assert acts.act(UID, 1, occ, "done", via="telegram").reason == "gone"
    eng.tick(D.replace(hour=8, minute=32))
    assert raw(tmp_path) == []


def test_snooze_bad_time_asks(tmp_path):
    eng, fake, res = engine(tmp_path)
    seed(tmp_path, "倒垃圾", D.replace(hour=8))
    eng.tick(D.replace(hour=8, second=5))
    acts = Actions(ScheduleStore(str(tmp_path)), resolve=res, clock=lambda: D.replace(hour=8, minute=1))
    out = acts.act(UID, 1, reminder.to_iso(D.replace(hour=8)), "snooze", typed="等等")
    assert not out.ok and out.reason == "bad_time" and "多久" in out.text
    out = acts.act(UID, 1, reminder.to_iso(D.replace(hour=8)), "snooze")       # 沒說：5 分鐘
    assert out.ok and "08:06" in out.text


def test_on_delivery_records_and_daily_done_goes_back_to_pending(tmp_path):
    eng, fake, res = engine(tmp_path)
    seed(tmp_path, "吃藥", D.replace(hour=8), repeat="daily")
    eng.tick(D.replace(hour=8, second=5))
    occ = reminder.to_iso(D.replace(hour=8))
    acts = Actions(ScheduleStore(str(tmp_path)), resolve=res, clock=lambda: D.replace(hour=8, minute=2))
    acts.on_delivery(UID, 1, occ, delivery.DeliveryRecord("desktop", state=delivery.SENT, ok_at=5.0))
    assert raw(tmp_path)[0]["deliveries"]["desktop"]["state"] == "sent"
    acts.on_delivery(UID, 99, occ, delivery.DeliveryRecord("desktop"))     # 找不到：不丟例外
    assert acts.act(UID, 1, occ, "ack", via="web").ok
    item = raw(tmp_path)[0]
    assert item["status"] == "pending" and item["history"][-1]["status"] == "done" and item["occurrence"] is None


# ── 舊資料 ───────────────────────────────────────────────────────────

def test_old_schedule_json_is_read_and_upgraded(tmp_path):
    created = int(datetime(2026, 11, 1, 12, 0).timestamp())
    old = [{"id": 1, "kind": "remind", "time": "08:00", "date": "", "text": "吃藥", "command": "", "owner": UID,
            "last_run": "2026-11-15", "created": created},
           {"id": 2, "kind": "remind", "time": "15:30", "date": "2026-11-16", "text": "繳費", "command": "",
            "owner": UID, "last_run": "", "created": created},
           {"id": 3, "kind": "remind", "time": "99:99", "date": "", "text": "壞掉的", "owner": UID, "created": created},
           {"id": 4, "kind": "command", "time": "21:00", "date": "", "command": "/money_month", "owner": UID,
            "last_run": "", "created": created}]
    with open(os.path.join(tmp_path, "schedule.json"), "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False)
    eng, fake, _ = engine(tmp_path)
    fired = eng.tick(D.replace(hour=8, second=5))
    assert [f["text"] for f in fired] == ["吃藥"]
    items = {it["id"]: it for it in raw(tmp_path)}
    assert items[1]["v"] == 2 and items[1]["source"] == "legacy" and items[1]["status"] == "ringing"
    assert items[2]["v"] == 2 and items[2]["repeat"] == "once" and items[2]["status"] == "pending"
    assert items[3] == old[2] and items[4] == old[3]                     # 讀不懂的、排程指令：原樣留著
    assert [it["text"] for it in ScheduleStore(str(tmp_path)).items("remind")] == ["吃藥", "繳費", "壞掉的"]
    assert len(eng.tick(D.replace(hour=15, minute=30, second=1))) == 1


# ── 在 App 裡（假的 deliver） ─────────────────────────────────────────

def _runner(bot):
    return bot.app.extras["synox_schedule_runner"]


def test_app_engine_calls_delivery_deliver(make_bot, owner, monkeypatch):
    fake = FakeDeliver()
    monkeypatch.setattr(delivery, "deliver", lambda app, msg: fake(msg))
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    assert len(_runner(bot).tick(datetime(2026, 11, 9, 8, 0, 10))) == 1
    assert fake.texts() == ["⏰ 提醒：吃藥"] and fake.msgs[0].uid == owner
    assert bot.app.extras[delivery.ACTIONS_EXTRA] is not None


def test_app_failed_deliver_keeps_one_shot(make_bot, owner, monkeypatch):
    fake = FakeDeliver("fail")
    monkeypatch.setattr(delivery, "deliver", lambda app, msg: fake(msg))
    bot = make_bot()
    day = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    bot.say(owner, f"/remind_add 15:30 繳費 date={day}")
    when = datetime.strptime(day + " 15:30", "%Y-%m-%d %H:%M")
    assert len(_runner(bot).tick(when)) == 1
    _runner(bot).tick(when + timedelta(minutes=5))
    store = bot.app.extras["synox_schedule_store"]
    assert [it["status"] for it in store.raw_items()] == ["ringing"]     # 沒送到：不刪


def test_engine_down_tells_the_owner(make_bot, owner, monkeypatch):
    bot = make_bot()
    runner = _runner(bot)
    store = bot.app.extras["synox_schedule_store"]

    def broken():
        raise OSError("磁碟讀不到")
    monkeypatch.setattr(store, "upgrade_all", broken)
    for _ in range(3):
        with pytest.raises(Exception):
            runner.tick(datetime(2026, 11, 9, 8, 0))
    assert any("提醒引擎停了" in t for t in bot.texts(owner))
    monkeypatch.undo()
    runner.tick(datetime(2026, 11, 9, 8, 1))
    assert any("提醒引擎恢復了" in t for t in bot.texts(owner))


def test_runtime_backoff_cap_for_reminders(make_bot):
    from synox import runtime
    from synox.runtime.loop import LONG_BACKOFF, NOTIFY_AFTER, RuntimeLoop

    class Clock:
        t = 1_800_000_000.0

        def __call__(self):
            return self.t

    clock = Clock()
    loop = RuntimeLoop(object(), clock=clock, spawn=lambda fn, name: fn(), notify=lambda text: None, state_path="")

    def boom(ctx):
        raise RuntimeError("x")
    capped = loop.register("system.capped", "c", fn=boom, interval=30, first_delay=0, max_backoff=60)
    plain = loop.register("system.plain", "p", fn=boom, interval=30, first_delay=0)
    for _ in range(NOTIFY_AFTER + 1):
        loop.run_now("system.capped")
        loop.run_now("system.plain")
    assert capped.next_due - clock.t <= 60 and plain.next_due - clock.t == LONG_BACKOFF
    bot = make_bot()
    rt = runtime.of(bot.app)
    if rt is not None:
        assert rt.loop.task("system.schedule").max_backoff == 60
