"""ADR 0028 的契約空殼：可以 import、資料格式來回不失真、舊資料轉換規則、回執的字、重試數字、檔案溝通格式。"""

from datetime import datetime

import pytest

from synox.notify import delivery, desk
from synox.schedule import receipt, reminder
from synox.schedule.reminder import Reminder


def test_reminder_round_trip():
    rem = reminder.new_reminder(3, 1001, "倒垃圾", due=datetime(2026, 11, 16, 0, 51), created=1763225000)
    rem.deliveries["telegram"] = delivery.DeliveryRecord("telegram", state=delivery.SENT, tries=1, ok_at=1.0,
                                                         ref={"chat_id": 1001, "message_id": 7}).to_dict()
    data = rem.to_dict()
    assert data["v"] == 2 and data["kind"] == "remind" and data["repeat"] == "once"
    assert data["time"] == "00:51" and data["date"] == "2026-11-16"            # 舊欄位照寫
    assert reminder.from_iso(data["due"]) == reminder.aware(datetime(2026, 11, 16, 0, 51))
    back = Reminder.from_dict(data)
    assert back == rem and back.to_dict() == data
    assert delivery.DeliveryRecord.from_dict(back.deliveries["telegram"]).ref["message_id"] == 7


def test_todo_has_no_due():
    todo = reminder.new_reminder(4, 1001, "繳電話費", due=None)
    assert todo.is_todo and todo.repeat == reminder.NONE
    assert todo.to_dict()["time"] == "" and Reminder.from_dict(todo.to_dict()) == todo
    with pytest.raises(ValueError):
        Reminder.from_dict({**todo.to_dict(), "repeat": "once"})
    with pytest.raises(ValueError):
        Reminder.from_dict({**todo.to_dict(), "status": "sleeping"})


def test_legacy_once_and_daily_upgrade():
    created = datetime(2026, 11, 9, 8, 10).timestamp()
    once = {"id": 1, "kind": "remind", "time": "15:30", "date": "2026-11-20", "text": "繳費", "command": "",
            "owner": 1001, "last_run": "", "created": int(created)}
    up = reminder.upgrade_item(once)
    assert up["repeat"] == "once" and up["status"] == "pending" and up["source"] == "legacy"
    assert reminder.from_iso(up["due"]) == reminder.aware(datetime(2026, 11, 20, 15, 30))
    assert reminder.upgrade_item(up) is up                                   # 冪等
    daily = {**once, "id": 2, "time": "08:00", "date": ""}                  # 08:10 才設的每天 08:00 → 明天才第一次
    assert reminder.from_iso(reminder.upgrade_item(daily)["due"]) == reminder.aware(datetime(2026, 11, 10, 8, 0))
    ran = {**daily, "last_run": "2026-11-12"}                               # 12 號跑過 → 13 號
    assert reminder.from_iso(reminder.upgrade_item(ran)["due"]) == reminder.aware(datetime(2026, 11, 13, 8, 0))
    assert reminder.upgrade_item({**once, "time": "25:00"}) is None          # 讀不懂：不猜
    command = {"id": 9, "kind": "command", "time": "21:00", "command": "/money_month"}
    assert reminder.upgrade_item(command) is command                         # /schedule_* 不在契約內
    assert Reminder.from_dict(up).text == "繳費"


def test_receipt_text_and_round_trip():
    rec = receipt.ScheduleReceipt(kind=receipt.REMIND, id=3, text="倒垃圾", repeat="once",
                                  due="2026-11-16T00:51:00+08:00", when="今天 00:51",
                                  channels=["telegram", "desktop"], channel_labels=["Telegram", delivery.DESKTOP_LABEL],
                                  not_when=["off", "asleep"])
    text = rec.reply_text()
    assert text.startswith("⏰ 排好了：今天 00:51 提醒你「倒垃圾」（只一次）。")
    assert "會送到：Telegram、這台電腦的視窗。" in text and "電腦關機時、電腦睡著時（開機後補送）" in text
    assert rec.machine_line().startswith(receipt.MARK) and "due=2026-11-16T00:51:00+08:00" in rec.machine_line()
    assert receipt.ScheduleReceipt.from_dict(rec.to_dict()) == rec
    with pytest.raises(ValueError):
        receipt.ScheduleReceipt.from_dict({**rec.to_dict(), "due": None})
    todo = receipt.ScheduleReceipt(kind=receipt.TODO, id=4, text="繳電話費", repeat="none")
    assert "不會響" in todo.reply_text()


def test_emit_hands_receipt_to_capture():
    class Api:
        def __init__(self):
            self.sent, self.receipts = [], []

        def send_message(self, chat_id, text, **kw):
            self.sent.append((chat_id, text))

    class CaptureLike(Api):
        def note_receipt(self, r):
            self.receipts.append(r)

    rec = receipt.ScheduleReceipt(kind="remind", id=1, text="喝水", repeat="daily", due="2026-11-17T09:00:00+08:00",
                                  when="明天 09:00")
    plain, capture = Api(), CaptureLike()
    receipt.emit(plain, 5, rec)
    receipt.emit(capture, 5, rec)
    assert plain.sent[0][1] == capture.sent[0][1] and capture.receipts == [rec]


def test_retry_policy_numbers():
    policy = delivery.DEFAULT_POLICY
    rec = delivery.DeliveryRecord("telegram", state=delivery.FAILED, tries=1, first_try=1000.0)
    assert policy.next_try(rec, 1000.0) == 1030.0
    rec.tries = 4
    assert policy.next_try(rec, 2000.0) == 2300.0
    rec.tries = 50
    assert policy.next_try(rec, 5000.0) == 5900.0
    assert policy.next_try(rec, 1000.0 + 6 * 3600) is None                   # 滿 6 小時放棄
    assert policy.next_try(rec, 1000.0 + 6 * 3600 - 10) == 1000.0 + 6 * 3600   # 最後一次不超過界線
    assert policy.next_try(rec, 2000.0, retry_after=7) == 2007.0
    assert delivery.DeliveryResult("telegram", delivery.FAILED, error="blocked").permanent


def test_delivery_shells_are_not_implemented_yet():
    msg = delivery.Message(key=delivery.message_key(3, "2026-11-16T00:51:00+08:00", 1001), uid=1001, text="x",
                           ref=delivery.ReminderRef(3, "2026-11-16T00:51:00+08:00"))
    assert msg.key == "rem:1001:3:2026-11-16T00:51:00+08:00"
    # W2 實作了 deliver／planned_channels／spool_at（tests/test_notify_outbox.py）；剩 W1 的 headless_engine
    for fn, args in ((reminder.headless_engine, ("x", None, print)),):
        with pytest.raises(NotImplementedError):
            fn(*args)
    ticket = delivery.DeliveryTicket(msg.key, 1001, {"web": delivery.DeliveryRecord("web", state=delivery.SENT),
                                                     "telegram": delivery.DeliveryRecord("telegram", next_try=5.0)})
    assert ticket.notified and not ticket.settled


def test_desk_spool_format():
    token = desk.make_token(1001, 3, "2026-11-16T00:51:00+08:00")
    assert token == "1001-3-202611160051" and desk.token_ok(token)
    assert desk.show_name(token) == "show-1001-3-202611160051.json"
    assert desk.is_temp(".show-x.json.tmp") and not desk.is_temp(desk.show_name(token))
    card = desk.ShowCard(token, 1001, 3, "2026-11-16T00:51:00+08:00", "倒垃圾", "今天 00:51", written_at=1.0)
    assert desk.from_dict(desk.to_dict(card)) == card
    act = desk.DeskAction(token, 3, "2026-11-16T00:51:00+08:00", "snooze", at=2.0, typed="15:30")
    assert desk.from_dict(desk.to_dict(act)) == act
    todos = desk.TodoList(1001, [{"rid": 5, "text": "繳電話費"}])
    assert desk.from_dict(desk.to_dict(todos)) == todos and desk.token_ok(desk.make_token(1001, 5, ""))
    with pytest.raises(ValueError):
        desk.from_dict({**desk.to_dict(card), "token": "../../evil"})
    with pytest.raises(ValueError):
        desk.from_dict({"type": "exec"})
