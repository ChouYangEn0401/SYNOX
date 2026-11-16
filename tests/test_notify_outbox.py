"""送達層（ADR 0028 §3.3；synox/notify/outbox.py、channels.py、deskapp.py）：管道回報成功才算送到、失敗照
30／60／120 秒退避重試、blocked 不重試、存檔（重開照樣重試）、加密、冪等；電腦視窗寫了 show 60 秒沒有 shown 算
no_window；視窗按了 → 引擎 5 秒內讀到、Telegram 那則收回；Telegram／網頁的按鈕有登記 ReminderActions 就交給它。
全部用假管道：不連網、不開埠、不開視窗、不碰真的啟動資料夾。"""

import os

import pytest

from isdtelekit.testing import FakeChannel

from synox import notify
from synox.notify import delivery, desk, deskapp
from synox.notify.channels import DesktopAdapter
from synox.notify.delivery import (DESKTOP, FAILED, GAVE_UP, QUEUED, RETRACTED, SENT, SKIPPED, TELEGRAM, WEB,
                                   ActionOutcome, DeliveryResult, Message, ReminderRef)
from synox.notify.outbox import FileOutbox
from synox.remindwin import logic

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")

OCC = "2026-11-16T00:51:00+08:00"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeAdapter:
    """回事先排好的結果（用完就一直回最後一個）。"""

    def __init__(self, name, results, available=True):
        self.name = name
        self.results = list(results)
        self.sent = []
        self.retracted = []
        self._available = available

    def available(self, uid):
        return self._available

    def send(self, msg):
        self.sent.append(msg)
        res = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        return res

    def retract(self, record, note):
        self.retracted.append((record.channel, note))
        return True


def make_outbox(tmp_path, adapters, clock, listener=None, vault=None):
    return FileOutbox(str(tmp_path / "outbox"), vault, adapters=adapters, plan=lambda m: list(adapters),
                      clock=clock, listener=listener)


def msg(key="rem:1:3:x", uid=1, ref=True, **kw):
    return Message(key=key, uid=uid, text="⏰ 提醒：倒垃圾", ref=ReminderRef(3, OCC) if ref else None, **kw)


# ── 佇列：確認、退避、放棄 ─────────────────────────────────────────────

def test_failed_channel_stays_queued_and_backs_off_30_60_120_then_sent(tmp_path):
    clock = Clock()
    t0 = clock.t
    fail = DeliveryResult(TELEGRAM, FAILED, error="network")
    tg = FakeAdapter(TELEGRAM, [fail, fail, fail, DeliveryResult(TELEGRAM, SENT, ref={"message_id": 9})])
    seen = []
    box = make_outbox(tmp_path, {TELEGRAM: tg}, clock, listener=lambda m, r: seen.append(r.state))
    ticket = box.submit(msg())
    rec = ticket.records[TELEGRAM]
    assert rec.state == FAILED and rec.error == "network" and rec.next_try == t0 + 30 and not ticket.notified
    clock.t = t0 + 29
    assert box.pump() == [] and len(tg.sent) == 1                         # 還沒到：不試
    clock.t = t0 + 30
    box.pump()
    assert box.status(1, "rem:1:3:x").records[TELEGRAM].next_try == t0 + 30 + 60
    clock.t = t0 + 90
    box.pump()
    assert box.status(1, "rem:1:3:x").records[TELEGRAM].next_try == t0 + 90 + 120
    clock.t = t0 + 210
    changed = box.pump()
    rec = changed[0].records[TELEGRAM]
    assert rec.state == SENT and rec.tries == 4 and rec.ok_at == t0 + 210 and rec.next_try is None
    assert rec.ref == {"message_id": 9} and changed[0].notified and changed[0].settled
    assert seen == [FAILED, FAILED, FAILED, SENT]
    clock.t = t0 + 9999
    assert box.pump() == [] and len(tg.sent) == 4                         # 送到了就不再送


def test_blocked_is_not_retried_and_gives_up_after_six_hours(tmp_path):
    clock = Clock()
    blocked = FakeAdapter(TELEGRAM, [DeliveryResult(TELEGRAM, FAILED, error="blocked")])
    flaky = FakeAdapter("discord", [DeliveryResult("discord", FAILED, error="network")])
    box = make_outbox(tmp_path, {TELEGRAM: blocked, "discord": flaky}, clock)
    ticket = box.submit(msg())
    assert ticket.records[TELEGRAM].state == GAVE_UP and ticket.records[TELEGRAM].next_try is None
    for _ in range(60):                                                   # 一直壞：6 小時後放棄
        clock.t += 900
        box.pump()
    assert len(blocked.sent) == 1
    rec = box.status(1, "rem:1:3:x").records["discord"]
    assert rec.state == GAVE_UP and rec.next_try is None and rec.last_try - rec.first_try <= 6 * 3600


def test_rate_limited_uses_retry_after_and_skipped_is_not_a_failure(tmp_path):
    clock = Clock()
    t0 = clock.t
    tg = FakeAdapter(TELEGRAM, [DeliveryResult(TELEGRAM, FAILED, error="rate_limited", retry_after=7),
                                DeliveryResult(TELEGRAM, SENT)])
    off = FakeAdapter("discord", [DeliveryResult("discord", SENT)], available=False)
    box = make_outbox(tmp_path, {TELEGRAM: tg, "discord": off}, clock)
    ticket = box.submit(msg())
    assert ticket.records[TELEGRAM].next_try == t0 + 7 and ticket.records["discord"].state == SKIPPED
    assert off.sent == []


def test_queue_survives_restart_and_deliver_is_idempotent(tmp_path):
    clock = Clock()
    t0 = clock.t
    tg = FakeAdapter(TELEGRAM, [DeliveryResult(TELEGRAM, FAILED, error="network")])
    box = make_outbox(tmp_path, {TELEGRAM: tg}, clock)
    box.submit(msg())
    assert box.submit(msg()).records[TELEGRAM].tries == 1 and len(tg.sent) == 1     # 同一個 key：不重送
    ok = FakeAdapter(TELEGRAM, [DeliveryResult(TELEGRAM, SENT)])
    again = make_outbox(tmp_path, {TELEGRAM: ok}, clock)                             # 「重開」：新的物件、同一份檔
    clock.t = t0 + 30
    assert [t.key for t in again.pump()] == ["rem:1:3:x"]
    assert again.status(1, "rem:1:3:x").records[TELEGRAM].state == SENT and len(ok.sent) == 1


def test_resolve_stops_retries_and_retracts_other_channels(tmp_path):
    clock = Clock()
    tg = FakeAdapter(TELEGRAM, [DeliveryResult(TELEGRAM, FAILED, error="network")])
    web = FakeAdapter(WEB, [DeliveryResult(WEB, SENT)])
    box = make_outbox(tmp_path, {WEB: web, TELEGRAM: tg}, clock)
    box.submit(msg())
    box.resolve(1, "rem:1:3:x", note="✅ 在電腦上做完了", via=WEB)
    ticket = box.status(1, "rem:1:3:x")
    assert ticket.records[TELEGRAM].state == RETRACTED and ticket.settled
    assert tg.retracted == [(TELEGRAM, "⏰ 提醒：倒垃圾\n✅ 在電腦上做完了")] and web.retracted == []
    clock.t += 3600
    box.pump()
    assert len(tg.sent) == 1


def test_queue_file_is_encrypted_with_the_users_key(make_bot, owner):
    bot = make_bot()
    ticket = delivery.deliver(bot.app, msg(key="rem:secret", uid=owner))
    assert ticket.records[WEB].state == SENT
    outbox = bot.app.extras[delivery.OUTBOX_EXTRA]
    path = outbox.path(owner)
    assert path.endswith(".enc") and os.path.exists(path)
    with open(path, "rb") as f:
        assert "倒垃圾".encode("utf-8") not in f.read()


# ── 接上通知中心（真的 Hub、假的 Telegram）─────────────────────────────

class FlakyTelegram(FakeChannel):
    """前 n 次回 {"ok": False}（status 給的那種），之後正常。"""

    def __init__(self, fails=1, failure=None):
        super().__init__()
        self.fails = fails
        self.failure = failure or {"ok": False, "error": "connection reset"}

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        if self.fails > 0:
            self.fails -= 1
            return dict(self.failure)
        return super().send_message(chat_id, text, reply_markup=reply_markup, **kw)


def with_telegram(bot, monkeypatch, tg):
    hub = notify.of(bot.app)
    monkeypatch.setattr(hub, "_telegram_api", lambda: tg)
    return hub


def reminder_msg(owner, rid=3, occ=OCC, **kw):
    kw.setdefault("actions", [{"id": "ok", "label": "知道了"}, {"id": "snooze", "label": "5 分鐘後再提醒"}])
    return Message(key=delivery.message_key(rid, occ, owner), uid=owner, text="⏰ 提醒：倒垃圾",
                   data={"text": "倒垃圾"}, ref=ReminderRef(rid, occ), **kw)


def test_hub_channels_retry_telegram_until_it_reports_ok(make_bot, owner, monkeypatch):
    bot = make_bot()
    tg = FlakyTelegram(fails=1)
    with_telegram(bot, monkeypatch, tg)
    assert delivery.planned_channels(bot.app, owner) == [WEB, TELEGRAM]
    m = reminder_msg(owner)
    ticket = delivery.deliver(bot.app, m)
    assert ticket.records[WEB].state == SENT and ticket.records[TELEGRAM].state == FAILED
    assert ticket.records[TELEGRAM].error == "network" and ticket.notified and not ticket.settled
    assert tg.texts(owner) == []
    outbox = bot.app.extras[delivery.OUTBOX_EXTRA]
    outbox.pump(ticket.records[TELEGRAM].next_try)
    ticket = delivery.status(bot.app, owner, m.key)
    assert ticket.records[TELEGRAM].state == SENT and ticket.records[TELEGRAM].ref["message_id"] == 1
    assert tg.last(owner) == "⏰ 提醒：倒垃圾" and any(b.startswith("ntf:s5:") for b in tg.buttons(owner))
    item = [it for it in notify.of(bot.app).store.since(owner)["items"]][-1]
    assert item["data"]["remind"] == {"rid": 3, "occurrence": OCC, "key": m.key}
    assert notify.of(bot.app).notify(owner, "x", key=m.key).get("skipped") == "dup"   # 通知中心的去重也認得


def test_telegram_errors_are_classified(make_bot, owner, monkeypatch):
    bot = make_bot()
    tg = FlakyTelegram(fails=1, failure={"ok": False, "status": 403, "description": "bot was blocked"})
    with_telegram(bot, monkeypatch, tg)
    ticket = delivery.deliver(bot.app, reminder_msg(owner))
    assert ticket.records[TELEGRAM].state == GAVE_UP and ticket.records[TELEGRAM].error == "blocked"
    tg = FlakyTelegram(fails=1, failure={"ok": False, "error": "duplicate"})
    with_telegram(bot, monkeypatch, tg)
    m = reminder_msg(owner, rid=4)
    ticket = delivery.deliver(bot.app, m)
    assert ticket.records[TELEGRAM].error == "duplicate_text"
    bot.app.extras[delivery.OUTBOX_EXTRA].pump(ticket.records[TELEGRAM].next_try)
    assert tg.last(owner) == "⏰ 提醒：倒垃圾（第 2 次）"                     # 重試時字尾加次數，不會再被當成重複


def test_without_chat_channels_falls_back_to_home(make_bot, owner):
    bot = make_bot()
    ticket = delivery.deliver(bot.app, reminder_msg(owner))
    assert set(ticket.records) == {WEB, "chat"} and ticket.records["chat"].state == SENT
    assert bot.last(owner) == "⏰ 提醒：倒垃圾"


# ── 按鈕回頭叫提醒引擎 ───────────────────────────────────────────────

class FakeActions:
    def __init__(self, ok=True, note="✅ 在別處做完了"):
        self.calls = []
        self.deliveries = []
        self.ok = ok
        self.note = note

    def act(self, uid, rid, occurrence, action, *, until=None, typed="", via=""):
        self.calls.append({"uid": uid, "rid": rid, "occurrence": occurrence, "action": action, "until": until,
                           "typed": typed, "via": via})
        return ActionOutcome(ok=self.ok, reason="" if self.ok else "gone", text="收到" if self.ok else "",
                             note=self.note)

    def on_delivery(self, uid, rid, occurrence, record):
        self.deliveries.append((rid, occurrence, record.channel, record.state))


def test_chat_button_calls_reminder_actions_when_registered(make_bot, owner):
    bot = make_bot()
    actions = FakeActions()
    bot.app.extras[delivery.ACTIONS_EXTRA] = actions
    m = reminder_msg(owner)
    delivery.deliver(bot.app, m)
    assert (3, OCC, WEB, SENT) in actions.deliveries                      # on_delivery：送達紀錄回給引擎
    data = next(b for b in bot.api.buttons(owner) if b.startswith("ntf:s5:"))
    bot.press(owner, data)
    call = actions.calls[-1]
    assert call["action"] == "snooze" and call["rid"] == 3 and call["occurrence"] == OCC and call["until"]
    assert bot.answers()[-1] == "收到"
    assert delivery.status(bot.app, owner, m.key).settled
    from synox.schedule.commands import store_for
    assert store_for(bot.app).of(owner).items("remind") == []             # 沒走舊的「另加一筆提醒」


def test_web_done_and_read_go_to_reminder_actions(make_bot, owner):
    from test_web import Client, ui_of
    bot = make_bot()
    actions = FakeActions()
    bot.app.extras[delivery.ACTIONS_EXTRA] = actions
    delivery.deliver(bot.app, reminder_msg(owner))
    c = Client(ui_of(bot))
    c.login(owner)
    nid = c.get("/api/notifications")[1]["items"][-1]["id"]
    status, r = c.post(f"/api/notifications/{nid}/done")
    assert status == 200 and r["message"] == "收到" and actions.calls[-1]["action"] == "done"
    assert actions.calls[-1]["via"] == "web"
    delivery.deliver(bot.app, reminder_msg(owner, rid=5))
    nid = c.get("/api/notifications")[1]["items"][-1]["id"]
    c.post("/api/notifications/read", {"id": nid})
    assert actions.calls[-1]["action"] == "ack" and actions.calls[-1]["rid"] == 5


def test_buttons_without_actions_never_add_a_reminder(make_bot, owner):
    """舊的「5 分鐘後再提醒＝另加一筆提醒」拿掉了（ADR 0028 整合）：沒有提醒引擎時按了只收掉按鈕、說已經處理過。"""
    bot = make_bot()
    bot.app.extras.pop(delivery.ACTIONS_EXTRA, None)
    delivery.deliver(bot.app, reminder_msg(owner))
    data = next(b for b in bot.api.buttons(owner) if b.startswith("ntf:s5:"))
    bot.press(owner, data)
    assert bot.answers()[-1] == notify.hub.T["gone"]
    from synox.schedule.commands import store_for
    assert store_for(bot.app).of(owner).items("remind") == []


# ── 電腦提醒視窗 ─────────────────────────────────────────────────────

def armed_desk(bot, tmp_path):
    d = bot.app.extras[deskapp.DESK_EXTRA]
    d.platform = "win32"
    d.armed = True
    d.startup_folder = str(tmp_path / "fake-startup")
    launched = []
    d.launcher = lambda: launched.append(1)
    return d, launched


def test_desktop_no_shown_in_60s_is_no_window_and_retried(tmp_path):
    clock = Clock()
    t0 = clock.t
    spool = desk.spool_at(str(tmp_path))
    launched = []
    adapter = DesktopAdapter(spool, available=lambda uid: True, launch=lambda: launched.append(clock.t), clock=clock)
    box = make_outbox(tmp_path, {DESKTOP: adapter}, clock)
    m = msg(key="rem:1:3:d", desktop={"when": "今天 00:51", "late_min": 2})
    rec = box.submit(m).records[DESKTOP]
    token = desk.make_token(1, 3, OCC)
    assert rec.state == QUEUED and rec.ref == {"token": token} and rec.next_try == t0 + 60
    shows = spool.pending_for_win()
    assert [s.token for s in shows] == [token] and shows[0].when == "今天 00:51" and shows[0].late_min == 2
    clock.t = t0 + 59
    box.pump()
    assert box.status(1, m.key).records[DESKTOP].state == QUEUED
    clock.t = t0 + 60
    box.pump()
    rec = box.status(1, m.key).records[DESKTOP]
    assert rec.state == FAILED and rec.error == "no_window" and rec.next_try == t0 + 90 and rec.tries == 1
    clock.t = t0 + 90
    box.pump()                                                             # 重試＝重寫卡片、再開一次視窗程式
    assert launched == [t0, t0 + 90] and box.status(1, m.key).records[DESKTOP].state == QUEUED
    spool.put_shown(desk.ShownAck(token=token, at=clock.t))
    d = deskapp.DeskService(str(tmp_path), owner_id=1)
    d.process(box, None)
    assert box.status(1, m.key).records[DESKTOP].state == SENT


def test_snoozed_re_ring_uses_the_engines_key(tmp_path):
    """延後之後再響：同一個 token、引擎給的 key 帶 #s1；視窗按了要收的是還沒處理掉的那一張。"""
    clock = Clock()
    spool = desk.spool_at(str(tmp_path))
    adapter = DesktopAdapter(spool, available=lambda uid: True, clock=clock)
    box = make_outbox(tmp_path, {DESKTOP: adapter}, clock)
    first = msg(key="rem:1:3:x")
    box.submit(first)
    box.resolve(1, first.key, via=DESKTOP)
    clock.t += 600
    again = msg(key="rem:1:3:x#s1")
    box.submit(again)
    token = desk.make_token(1, 3, OCC)
    assert box.find(1, DESKTOP, "token", token) == "rem:1:3:x#s1"
    spool.put_action(desk.DeskAction(token=token, rid=3, occurrence=OCC, action="done", at=clock.t))
    deskapp.DeskService(str(tmp_path), owner_id=1).process(box, FakeActions())
    assert box.status(1, "rem:1:3:x#s1").settled


def test_window_action_reaches_engine_and_retracts_telegram(make_bot, owner, monkeypatch, tmp_path):
    bot = make_bot()
    tg = FakeChannel()
    with_telegram(bot, monkeypatch, tg)
    d, launched = armed_desk(bot, tmp_path)
    actions = FakeActions(note="✅ 在電腦上做完了")
    bot.app.extras[delivery.ACTIONS_EXTRA] = actions
    assert delivery.planned_channels(bot.app, owner) == [WEB, TELEGRAM, DESKTOP]
    m = reminder_msg(owner, desktop={"when": "今天 00:51"})
    ticket = delivery.deliver(bot.app, m)
    assert ticket.records[DESKTOP].state == QUEUED and launched == [1]
    # 視窗那一邊（不開畫面）：讀到卡 → 回 shown → 按「完成」
    model = logic.DeskModel(desk.spool_at(bot.app.config.data_dir))
    card = model.poll().new[0]
    assert card.text == "倒垃圾" and card.when == "今天 00:51"
    model.shown(card.token)
    assert model.act(card.token, desk.BTN_DONE)[0]
    # 引擎那一邊：runtime 任務每 ≤5 秒跑一次
    from synox import runtime
    task = runtime.of(bot.app).loop.task(deskapp.DESK_TASK_ID)
    assert task is not None and task.interval <= desk.POLL_ENGINE_S
    task.fn(None)
    assert actions.calls[-1]["action"] == "done" and actions.calls[-1]["via"] == DESKTOP
    ticket = delivery.status(bot.app, owner, m.key)
    assert ticket.records[DESKTOP].state == SENT and ticket.records[TELEGRAM].state == RETRACTED
    assert tg.texts(owner)[-1].endswith("✅ 在電腦上做完了") and tg.removed
    assert not desk.spool_at(bot.app.config.data_dir).has_show(card.token)


def test_telegram_done_closes_the_window_card(make_bot, owner, monkeypatch, tmp_path):
    bot = make_bot()
    tg = FakeChannel()
    with_telegram(bot, monkeypatch, tg)
    armed_desk(bot, tmp_path)
    bot.app.extras[delivery.ACTIONS_EXTRA] = FakeActions(note="✅ 在 Telegram 上做完了")
    m = reminder_msg(owner, actions=[{"id": "done", "label": "完成"}])
    delivery.deliver(bot.app, m)
    model = logic.DeskModel(desk.spool_at(bot.app.config.data_dir))
    token = model.poll().new[0].token
    data = next(b for b in tg.buttons(owner) if b.startswith("ntf:d:"))
    bot.press(owner, data)
    changes = model.poll()
    assert changes.closed == [(token, "✅ 在 Telegram 上做完了")] and model.cards == {}


def test_desktop_only_when_armed_and_on(make_bot, owner, tmp_path):
    bot = make_bot()
    d = bot.app.extras[deskapp.DESK_EXTRA]
    assert DESKTOP not in delivery.planned_channels(bot.app, owner)       # 只 build、沒有 start：不跳視窗
    d.platform, d.armed = "win32", True
    assert DESKTOP in delivery.planned_channels(bot.app, owner)
    d.save_settings(window=False)
    assert DESKTOP not in delivery.planned_channels(bot.app, owner)
    d.save_settings(window=True)
    d.platform = "linux"
    assert DESKTOP not in delivery.planned_channels(bot.app, owner)
    off = make_bot(raw={"notify": {"desktop": False}})
    d2 = off.app.extras[deskapp.DESK_EXTRA]
    d2.platform, d2.armed = "win32", True
    assert DESKTOP not in delivery.planned_channels(off.app, owner) and d2.view()["locked_off"]


def test_web_settings_toggle_window_and_sentinel_in_a_fake_startup_folder(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    bot = make_bot()
    d, _ = armed_desk(bot, tmp_path)
    c = Client(ui_of(bot))
    c.login(owner)
    status, p = c.get("/api/notifications/prefs")
    assert status == 200 and p["desk"]["window"] and p["desk"]["sentinel"] and not p["desk"]["sentinel_installed"]
    status, r = c.post("/api/notifications/desk", {"sentinel": True})
    folder = tmp_path / "fake-startup"
    assert status == 200 and (folder / (desk.SENTINEL_STARTUP_NAME + ".cmd")).exists()
    assert r["desk"]["sentinel_installed"]
    status, r = c.post("/api/notifications/desk", {"window": False, "sentinel": False})
    assert status == 200 and not r["desk"]["window"] and not list(folder.iterdir())
    assert c.post("/api/notifications/desk", {"window": "yes"})[0] == 400
    d.platform = "linux"
    assert "desk" not in c.get("/api/notifications/prefs")[1]
    assert c.post("/api/notifications/desk", {"window": True})[0] == 403


# ── 誰是引擎 ─────────────────────────────────────────────────────────

def test_engine_gate_yields_to_running_sentinel(make_bot, tmp_path):
    bot = make_bot()
    data_dir = bot.app.config.data_dir
    assert delivery.is_engine(bot.app)                                    # 還沒 start：沒有人搶
    sentinel_lock = desk.engine_lock_at(data_dir)
    assert sentinel_lock.try_acquire(desk.WHO_SENTINEL)
    gate = bot.app.extras[deskapp.GATE_EXTRA]
    assert gate.start() is False and not delivery.is_engine(bot.app)
    assert desk.yield_requested(data_dir) is not None                      # 請哨兵讓位
    pumped = []
    bot.app.extras[delivery.OUTBOX_EXTRA].pump = lambda *a: pumped.append(1)
    from synox import runtime
    runtime.of(bot.app).loop.task(delivery.PUMP_TASK_ID).fn(None)
    assert pumped == []                                                    # 不是引擎：不重送（哨兵在送）
    sentinel_lock.release()
    assert gate.check() and delivery.is_engine(bot.app) and desk.yield_requested(data_dir) is None
    runtime.of(bot.app).loop.task(delivery.PUMP_TASK_ID).fn(None)
    assert pumped == [1]
    assert gate.view()["holder"]["who"] == desk.WHO_APP
    gate.stop()
