"""提醒視窗的新動作（「我知道了」≠「我完成了」、稍後 5／15／60／自選、改到別天）：引擎（schedule/actions.py）
與視窗邏輯（remindwin/logic.py）。假的 deliver、假時鐘；不開視窗、不連網。"""

import json
import os
from datetime import date, datetime, timedelta

from synox.notify import delivery
from synox.notify import desk
from synox.remindwin import logic
from synox.schedule import actions as A
from synox.schedule import reminder as R
from synox.schedule.actions import Actions
from synox.schedule.store import ScheduleStore

UID = 1001
D = datetime(2026, 11, 18, 0, 0)


def ticket(msg):
    rec = delivery.DeliveryRecord("telegram", state=delivery.SENT, tries=1, first_try=1.0, last_try=1.0, ok_at=1.0)
    return delivery.DeliveryTicket(msg.key, msg.uid, {"telegram": rec})


class Fake:
    def __init__(self):
        self.msgs, self.resolved = [], []

    def deliver(self, msg):
        self.msgs.append(msg)
        return ticket(msg)

    def resolve(self, uid, key, note="", via=""):
        self.resolved.append((uid, key, note, via))


def setup(tmp_path, due, repeat="once"):
    fake = Fake()
    eng = R.headless_engine(str(tmp_path), None, fake.deliver, resolve=fake.resolve)
    ScheduleStore(str(tmp_path)).add_reminder(
        lambda rid: R.new_reminder(rid, UID, "倒垃圾", due=due, repeat=repeat, created=int((due - timedelta(days=1)).timestamp())))
    eng.tick(due + timedelta(seconds=1))
    return eng, fake


def acts(tmp_path, fake, at):
    return Actions(ScheduleStore(str(tmp_path)), resolve=fake.resolve, clock=lambda: at)


def item(tmp_path):
    return ScheduleStore(str(tmp_path)).raw_items()[0]


# ── 引擎 ─────────────────────────────────────────────────────────────

def test_ack_is_dismissed_not_done(tmp_path):
    due = D.replace(hour=14, minute=46)
    eng, fake = setup(tmp_path, due)
    out = acts(tmp_path, fake, due + timedelta(minutes=1)).act(UID, 1, R.to_iso(due), "ack", via="desktop")
    assert out.ok and "知道了" in out.note
    it = item(tmp_path)
    assert it["status"] == R.DISMISSED and it["done_via"] == "desktop"
    assert not ScheduleStore(str(tmp_path)).items("remind")                    # 清單上看不到了（跟完成一樣收掉）
    assert fake.resolved and fake.resolved[-1][3] == "desktop"


def test_done_is_done(tmp_path):
    due = D.replace(hour=14, minute=46)
    eng, fake = setup(tmp_path, due)
    assert acts(tmp_path, fake, due + timedelta(minutes=1)).act(UID, 1, R.to_iso(due), "done", via="web").ok
    assert item(tmp_path)["status"] == R.DONE


def test_reschedule_defaults_to_same_time_tomorrow_and_rings_fresh(tmp_path):
    due = D.replace(hour=14, minute=46)
    eng, fake = setup(tmp_path, due)
    out = acts(tmp_path, fake, due + timedelta(minutes=2)).act(UID, 1, R.to_iso(due), "reschedule", via="desktop")
    assert out.ok and "明天 14:46" in out.text and out.note.startswith("📅")
    it = item(tmp_path)
    assert it["status"] == R.PENDING and it["due"] == R.to_iso(due + timedelta(days=1))
    assert it["occurrence"] is None and it["snooze_count"] == 0 and it["deliveries"] == {}
    assert ScheduleStore(str(tmp_path)).items("remind")                        # 回到清單上
    assert eng.tick(due + timedelta(hours=23)) == []                            # 還沒到
    fired = eng.tick(due + timedelta(days=1, seconds=3))
    assert len(fired) == 1 and "延後" not in fake.msgs[-1].text and "晚了" not in fake.msgs[-1].text


def test_reschedule_to_a_picked_time_or_typed(tmp_path):
    due = D.replace(hour=9)
    eng, fake = setup(tmp_path, due)
    pick = R.to_iso(datetime(2026, 11, 21, 8, 30))
    assert acts(tmp_path, fake, due).act(UID, 1, R.to_iso(due), "reschedule", until=pick).ok
    assert item(tmp_path)["due"] == pick


def test_reschedule_typed_and_bad_time(tmp_path):
    due = D.replace(hour=9)
    eng, fake = setup(tmp_path, due)
    a = acts(tmp_path, fake, due)
    past = R.to_iso(due - timedelta(hours=1))
    out = a.act(UID, 1, R.to_iso(due), "reschedule", until=past)
    assert not out.ok and out.reason == "bad_time" and item(tmp_path)["status"] == R.RINGING
    assert a.act(UID, 1, R.to_iso(due), "reschedule", typed="明天 9 點").ok
    assert item(tmp_path)["due"] == R.to_iso(datetime(2026, 11, 19, 9, 0))


def test_daily_reschedule_only_before_the_next_one(tmp_path):
    due = D.replace(hour=8)
    eng, fake = setup(tmp_path, due, repeat="daily")
    a = acts(tmp_path, fake, due + timedelta(minutes=1))
    out = a.act(UID, 1, R.to_iso(due), "reschedule")                           # 明天同一時間：本來就會響
    assert not out.ok and out.text == A.DAILY_LATER and item(tmp_path)["status"] == R.RINGING
    out = a.act(UID, 1, R.to_iso(due), "reschedule", until=R.to_iso(due.replace(hour=20)))
    assert out.ok and item(tmp_path)["status"] == R.SNOOZED                     # 今天晚上：延後這一次


def test_ring_carries_buttons_for_each_kind(tmp_path):
    due = D.replace(hour=8)
    eng, fake = setup(tmp_path, due)
    assert fake.msgs[-1].desktop["buttons"] == list(desk.DEFAULT_BUTTONS)
    assert [a["id"] for a in fake.msgs[-1].actions] == ["ok", "done", "snooze"]
    eng2, fake2 = setup(tmp_path / "d", due, repeat="daily")
    assert fake2.msgs[-1].desktop["buttons"] == list(desk.DAILY_BUTTONS)
    assert desk.BTN_RESCHEDULE_TOMORROW not in desk.DAILY_BUTTONS


def test_unknown_action_is_refused(tmp_path):
    due = D.replace(hour=8)
    eng, fake = setup(tmp_path, due)
    assert acts(tmp_path, fake, due).act(UID, 1, R.to_iso(due), "explode").reason == "bad_action"


# ── 視窗邏輯 ─────────────────────────────────────────────────────────

class Clock:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return self.dt.timestamp()


def window(tmp_path, occ=datetime(2026, 11, 18, 14, 46)):
    spool = desk.spool_at(str(tmp_path))
    o = occ.astimezone().isoformat()
    card = desk.ShowCard(token=desk.make_token(UID, 1, o), uid=UID, rid=1, occurrence=o, text="倒垃圾",
                         when="今天 14:46")
    spool.put_show(card)
    model = logic.DeskModel(spool, clock=Clock(occ + timedelta(minutes=1)))
    model.poll()
    return spool, model, card


def last_action(tmp_path):
    folder = os.path.join(str(tmp_path), "remind", "desk", "from_win")
    names = sorted(n for n in os.listdir(folder) if n.startswith("act-"))
    with open(os.path.join(folder, names[-1]), encoding="utf-8") as f:
        return json.load(f)


def test_window_ack_and_presets(tmp_path):
    spool, model, card = window(tmp_path)
    assert model.act(card.token, desk.BTN_ACK) == (True, logic.T["ack"])
    assert last_action(tmp_path)["action"] == "ack"
    spool, model, card = window(tmp_path / "b")
    ok, text = model.act(card.token, desk.BTN_SNOOZE_15)
    act = last_action(tmp_path / "b")
    assert ok and "15:02" in text and act["action"] == "snooze"
    assert datetime.fromisoformat(act["until"]).replace(tzinfo=None) == datetime(2026, 11, 18, 15, 2)


def test_window_reschedule_tomorrow_and_pick(tmp_path):
    spool, model, card = window(tmp_path)
    ok, text = model.act(card.token, desk.BTN_RESCHEDULE_TOMORROW)
    act = last_action(tmp_path)
    assert ok and "明天 14:46" in text and act["action"] == "reschedule"
    assert datetime.fromisoformat(act["until"]).replace(tzinfo=None) == datetime(2026, 11, 19, 14, 46)
    spool, model, card = window(tmp_path / "b")
    assert model.act(card.token, desk.BTN_RESCHEDULE_PICK) == (False, logic.T["pick_bad"])
    assert model.act(card.token, desk.BTN_RESCHEDULE_PICK, at=datetime(2026, 11, 1, 9, 0)) == (False, logic.T["pick_past"])
    ok, text = model.act(card.token, desk.BTN_RESCHEDULE_PICK, at=datetime(2026, 11, 21, 9, 30))
    assert ok and "09:30" in text
    assert datetime.fromisoformat(last_action(tmp_path / "b")["until"]).replace(tzinfo=None) == datetime(2026, 11, 21, 9, 30)


def test_logic_helpers():
    now = datetime(2026, 11, 18, 10, 0)
    assert logic.parse_typed("20", now) == datetime(2026, 11, 18, 10, 20)        # 只打數字＝幾分鐘後
    days = logic.day_choices(now)
    assert days[0] == (date(2026, 11, 19), "明天") and days[1][1] == "後天" and days[2][1] == "11/21（六）"
    assert len(days) == logic.PICK_DAYS
    assert logic.pick_at(date(2026, 11, 21), "下午 3 點") == datetime(2026, 11, 21, 15, 0)
    assert logic.pick_at(date(2026, 11, 21), "09:15") == datetime(2026, 11, 21, 9, 15)
    assert logic.pick_at(date(2026, 11, 21), "等等") is None
    assert logic.same_time_tomorrow("2026-11-17T08:00:00", now) == datetime(2026, 11, 19, 8, 0)    # 過了就再往後
    pos = logic.stack_heights([400, 400, 400], 1920, 1080, 380)
    assert pos[0][1] > pos[1][1] and pos[2][0] < pos[0][0]                      # 往上疊；放不下往左開一欄
    for button in desk.DEFAULT_BUTTONS + desk.MISSED_BUTTONS:
        assert logic.LABELS.get(button)                                          # 每一顆都有字
