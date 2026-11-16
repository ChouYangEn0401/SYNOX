"""提醒端到端（ADR 0028）：從「使用者說一句話」到「Telegram 跟電腦視窗都響、按了之後各處收掉」整條走一遍。

提醒引擎（schedule/）＋送達層（notify/）＋電腦視窗的檔案往返（remindwin/logic，不開畫面）＋提醒哨兵，
全部用假管道與假時鐘：不連網、不開埠、不開視窗、不開子程序。資料都是假的。
"""

from datetime import datetime

import pytest

from isdtelekit.testing import FakeChannel

from synox import notify
from synox.agent import claims
from synox.notify import delivery, desk, deskapp
from synox.notify.delivery import DESKTOP, FAILED, QUEUED, RETRACTED, SENT, TELEGRAM, WEB
from synox.remindwin import logic
from synox.schedule import commands, engine as engine_mod, reminder

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")

NIGHT = datetime(2026, 11, 16, 0, 40)                     # 使用者說話的時候：半夜 00:40
DUE = datetime(2026, 11, 16, 0, 51)


class FlakyTelegram(FakeChannel):
    """前 fails 次回 Telegram 的錯誤（伺服器 502），之後照常。"""

    def __init__(self, fails=0):
        super().__init__()
        self.fails = fails
        self.tries = 0

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.tries += 1
        if self.fails > 0:
            self.fails -= 1
            return {"ok": False, "status": 502, "description": "bad gateway"}
        return super().send_message(chat_id, text, reply_markup=reply_markup, **kw)


def setup(make_bot, monkeypatch, tmp_path, *, tg=None, script=None, now=NIGHT):
    """一支跑在記憶體裡的 SYNOX：假 Telegram、電腦視窗「上膛」（假裝在 Windows、開視窗程式＝記一筆）、假時鐘。"""
    bot = make_bot(script)
    tg = tg if tg is not None else FakeChannel()
    monkeypatch.setattr(notify.of(bot.app), "_telegram_api", lambda: tg)
    d = bot.app.extras[deskapp.DESK_EXTRA]
    d.platform, d.armed = "win32", True
    d.startup_folder = str(tmp_path / "fake-startup")
    launched = []
    d.launcher = lambda: launched.append(1)
    monkeypatch.setattr(commands, "clock", lambda: now)
    return bot, tg, launched


def runner(bot):
    return bot.app.extras["synox_schedule_runner"]


def items(bot):
    return commands.store_for(bot.app).raw_items()


def spool(bot):
    return desk.spool_at(bot.app.config.data_dir)


def desk_round(bot):
    """runtime 任務 system.notify.desk 跑一輪（讀視窗的回覆）。"""
    from synox import runtime
    runtime.of(bot.app).loop.task(deskapp.DESK_TASK_ID).fn(None)


# ── (a) 說一句話 → 回執 → 到點兩邊都響 ─────────────────────────────────────

def test_a_said_at_0040_rings_at_0051_on_telegram_and_the_window(make_bot, owner, monkeypatch, tmp_path):
    bot, tg, launched = setup(make_bot, monkeypatch, tmp_path)
    bot.say(owner, "/remind_add 12.51 倒垃圾")
    reply = bot.last(owner)
    assert reply.startswith("⏰ 排好了：今天 00:51 提醒你「倒垃圾」（只一次）。")
    assert "會送到：網頁、Telegram、這台電腦的視窗。" in reply and reply.count("倒垃圾") == 1   # 只有回執，不重複講
    (it,) = items(bot)
    assert it["status"] == "pending" and reminder.from_iso(it["due"]) == reminder.aware(DUE)

    assert runner(bot).tick(datetime(2026, 11, 16, 0, 50, 30)) == [] and tg.texts(owner) == []
    fired = runner(bot).tick(datetime(2026, 11, 16, 0, 51, 5))
    assert [f["text"] for f in fired] == ["倒垃圾"]
    assert tg.last(owner) == "⏰ 提醒：倒垃圾"
    assert {b.split(":")[1] for b in tg.buttons(owner)} == {"ok", "s5"}            # 知道了、5 分鐘後再提醒
    (card,) = spool(bot).pending_for_win()
    assert (card.text, card.when, card.late_min) == ("倒垃圾", "今天 00:51", 0) and launched == [1]
    (it,) = items(bot)
    assert it["status"] == "ringing" and it["deliveries"][TELEGRAM]["state"] == SENT
    assert it["deliveries"][DESKTOP]["state"] == QUEUED                          # 等視窗說「出現了」
    assert runner(bot).tick(datetime(2026, 11, 16, 0, 51, 40)) == [] and len(tg.texts(owner)) == 1   # 不重送


# ── (b) 視窗按「完成」→ Telegram 那則收回、提醒做完 ───────────────────────────

def test_b_done_in_the_window_retracts_telegram(make_bot, owner, monkeypatch, tmp_path):
    bot, tg, _ = setup(make_bot, monkeypatch, tmp_path)
    bot.say(owner, "/remind_add 12.51 倒垃圾")
    runner(bot).tick(datetime(2026, 11, 16, 0, 51, 5))
    model = logic.DeskModel(spool(bot))                                         # 視窗程式那一邊（不開畫面）
    card = model.poll().new[0]
    model.shown(card.token)
    ok, _msg = model.act(card.token, desk.BTN_DONE)
    assert ok
    desk_round(bot)
    (it,) = items(bot)
    assert it["status"] == "done" and it["done_via"] == DESKTOP
    assert it["deliveries"][DESKTOP]["state"] == SENT and it["deliveries"][TELEGRAM]["state"] == RETRACTED
    assert tg.last(owner).endswith("✅ 在電腦上做完了") and tg.removed                # 按鈕拿掉、字改掉
    assert not spool(bot).has_show(card.token)
    web = [x for x in notify.of(bot.app).store.since(owner)["items"] if x["kind"] == "alarm"][-1]
    assert web["actions"] == [] and web["read"]
    runner(bot).tick(datetime(2026, 11, 16, 0, 52))                              # 沒有管道還要試：從清單拿掉
    assert items(bot) == []


def test_b_snooze_from_telegram_rings_again_without_a_second_reminder(make_bot, owner, monkeypatch, tmp_path):
    """通知中心的「5 分鐘後再提醒」走 ReminderActions.act(snooze)：同一個提醒延後，不另加一筆。"""
    bot, tg, _ = setup(make_bot, monkeypatch, tmp_path)
    bot.say(owner, "/remind_add 12.51 倒垃圾")
    runner(bot).tick(datetime(2026, 11, 16, 0, 51, 5))
    s5 = next(b for b in tg.buttons(owner) if b.startswith("ntf:s5:"))
    bot.press(owner, s5)
    assert "再叫你一次" in bot.answers()[-1]
    (it,) = items(bot)
    assert it["status"] == "snoozed" and it["snooze_count"] == 1
    (closed,) = spool(bot).pending_for_win()                                     # 視窗那張也收了
    assert isinstance(closed, desk.CloseCard) and "延後到" in closed.note
    assert bot.api.removed                                   # 按過的那則：按鈕拿掉（按鍵經過的那個 api）
    logic.DeskModel(spool(bot)).poll()                                           # 視窗讀掉那張「關掉」
    until = reminder.from_iso(it["snooze_until"]).astimezone(reminder.local_tz()).replace(tzinfo=None)
    runner(bot).tick(until)
    assert tg.last(owner) == "⏰ 提醒：倒垃圾\n（延後第 1 次之後）"
    (card,) = spool(bot).pending_for_win()
    assert card.snooze_count == 1


# ── (c) 停機 3 小時再開 → 補送說錯過 ─────────────────────────────────────────

def test_c_three_hours_down_then_the_missed_notice(make_bot, owner, monkeypatch, tmp_path):
    bot, _tg, _ = setup(make_bot, monkeypatch, tmp_path)
    bot.say(owner, "/remind_add 01:00 澆花 repeat=once")
    assert "今天 01:00 提醒你「澆花」（只一次）" in bot.last(owner)
    # 這一支就此「停機」（不再 tick）；三個小時後重新開：同一份資料夾、新的一支 SYNOX
    again, tg2, _ = setup(make_bot, monkeypatch, tmp_path, now=datetime(2026, 11, 16, 4, 0))
    assert runner(again).tick(datetime(2026, 11, 16, 4, 0, 10)) == []         # 不是照響（晚超過 60 分鐘）
    assert tg2.last(owner).startswith("⏰ 你錯過了 1 個鬧鐘：今天 01:00 澆花")
    assert [b.split(":")[1] for b in tg2.buttons(owner)] == ["ok"]
    (card,) = spool(again).pending_for_win()
    assert card.text == "（錯過了）澆花" and card.buttons == [desk.BTN_DONE] and card.late_min == 180
    assert items(again)[0]["status"] == "missed"
    assert runner(again).tick(datetime(2026, 11, 16, 4, 1)) == [] and len(tg2.texts(owner)) == 1   # 只說一次
    ok = next(b for b in tg2.buttons(owner) if b.startswith("ntf:ok:"))
    again.press(owner, ok)
    assert again.answers()[-1] == "知道了" and not spool(again).has_show(card.token)     # 知道了：視窗那張也關


# ── (d) 假 Telegram 回失敗 → 不刪、退避重試、成功後 SENT ─────────────────────────

def test_d_telegram_failure_is_kept_and_retried_until_sent(make_bot, owner, monkeypatch, tmp_path):
    from synox import doctor
    tg = FlakyTelegram(fails=2)
    bot, tg, _ = setup(make_bot, monkeypatch, tmp_path, tg=tg)
    bot.say(owner, "/remind_add 12.51 倒垃圾")
    runner(bot).tick(datetime(2026, 11, 16, 0, 51, 5))
    lines, bad = doctor.remind_lines(bot.app.config, vault=bot.app.extras["vault"])     # 健康檢查看得到卡住的
    text = "\n".join(lines)
    assert "秒前（SYNOX 主程式）" in text and "1 件還沒送到" in text and "最近失敗：Telegram（連不上" in text
    assert bad == 1 and "倒垃圾" not in text                                      # 不印內容
    (it,) = items(bot)
    rec = it["deliveries"][TELEGRAM]
    assert it["status"] == "ringing" and rec["state"] == FAILED and rec["error"] == "network"
    assert rec["next_try"] - rec["last_try"] == 30                              # 30 秒後再試
    assert it["deliveries"][WEB]["state"] == SENT                               # 網頁那條有到：沒有卡住整則
    outbox = bot.app.extras[delivery.OUTBOX_EXTRA]
    runner(bot).tick(datetime(2026, 11, 16, 0, 51, 20))                          # 引擎再看一次：不重送、不刪
    assert tg.tries == 1 and len(items(bot)) == 1
    outbox.pump(rec["next_try"])
    rec = items(bot)[0]["deliveries"][TELEGRAM]
    assert rec["state"] == FAILED and rec["tries"] == 2 and rec["next_try"] - rec["last_try"] == 60   # 再退一級
    outbox.pump(rec["next_try"])
    rec = items(bot)[0]["deliveries"][TELEGRAM]
    assert rec["state"] == SENT and rec["tries"] == 3 and tg.last(owner) == "⏰ 提醒：倒垃圾"
    assert items(bot)[0]["status"] == "ringing"                                 # 等人按，不會自己刪


# ── (e) 哨兵拿著 engine.lock：主程式這一輪不跑到點檢查 ─────────────────────────

def test_e_main_program_skips_while_the_sentinel_holds_the_lock(make_bot, owner, monkeypatch, tmp_path):
    bot, tg, _ = setup(make_bot, monkeypatch, tmp_path)
    bot.say(owner, "/remind_add 12.51 倒垃圾")
    data_dir = bot.app.config.data_dir
    held = desk.engine_lock_at(data_dir)
    assert held.try_acquire(desk.WHO_SENTINEL)
    gate = bot.app.extras[deskapp.GATE_EXTRA]
    try:
        assert gate.start() is False and not delivery.is_engine(bot.app)
        r = runner(bot)
        assert r.tick(datetime(2026, 11, 16, 0, 51, 5)) == [] and r.skipped_for_sentinel == 1
        assert tg.texts(owner) == [] and items(bot)[0]["status"] == "pending"   # 哨兵在送：主程式不重複
        assert desk.yield_requested(data_dir) is not None                       # 請哨兵讓位
        held.release()
        assert gate.check() and delivery.is_engine(bot.app)
        assert len(r.tick(datetime(2026, 11, 16, 0, 51, 35))) == 1 and tg.last(owner) == "⏰ 提醒：倒垃圾"
        status = engine_mod.read_status(data_dir)
        assert status["who"] == "app" and status["failed_stores"] == 0
    finally:
        gate.stop()
        held.release()


def test_e_sentinel_rings_and_handles_the_window_button(make_bot, owner, monkeypatch, tmp_path):
    """SYNOX 沒開：哨兵拿鎖、到點跳視窗；視窗按「完成」由哨兵的引擎（act）處理；主程式開起來就讓位。"""
    from types import SimpleNamespace
    from synox.remindwin import sentinel as sentinel_mod
    bot, _tg, _ = setup(make_bot, monkeypatch, tmp_path)
    bot.say(owner, "/remind_add 12.51 倒垃圾")
    data_dir = bot.app.config.data_dir
    config = SimpleNamespace(has_token=False, owner_id=owner, data_dir=data_dir, raw={})
    vault = bot.app.extras["vault"]
    built = []

    def build():
        r = sentinel_mod.build_round(config, vault, launcher=lambda: None)
        r.desk.platform = "win32"
        built.append(r)
        return r
    s = sentinel_mod.Sentinel(data_dir, build=build)
    try:
        at = datetime(2026, 11, 16, 0, 51, 5).timestamp()
        assert s.step(at) == "engine" and s.is_engine
        r = built[0]
        assert hasattr(r.engine, "act") and hasattr(r.engine, "on_delivery") and r.actions is r.engine
        model = logic.DeskModel(desk.spool_at(data_dir))
        card = model.poll().new[0]
        assert card.text == "倒垃圾"
        model.shown(card.token)
        model.act(card.token, desk.BTN_DONE)
        assert s.step(at + 2) == "engine"
        (it,) = items(bot)
        assert it["status"] == "done" and it["done_via"] == DESKTOP and it["deliveries"][DESKTOP]["state"] == SENT
        assert engine_mod.read_status(data_dir)["who"] == "sentinel"
        desk.request_yield(data_dir, at=at + 3)                                 # 主程式開起來了
        assert s.step(at + 4) == "yielded" and not s.is_engine
    finally:
        s.release()


# ── 待辦：電腦視窗的下半部跟著變 ────────────────────────────────────────────

def test_todos_follow_the_list_and_the_window_can_tick_them_off(make_bot, owner, monkeypatch, tmp_path):
    bot, _tg, _ = setup(make_bot, monkeypatch, tmp_path)
    bot.say(owner, "/remind_todo 繳電話費")
    bot.say(owner, "/remind_todo 買燈泡")
    assert "記下了待辦：「買燈泡」" in bot.last(owner)
    model = logic.DeskModel(spool(bot))
    todos = model.poll().todos
    assert [t["text"] for t in todos] == ["繳電話費", "買燈泡"]
    bot.say(owner, "/remind_done 1")
    (left,) = spool(bot).todos_for_win(owner)[0].items
    assert left["text"] == "買燈泡"
    rid = left["rid"]
    spool(bot).put_action(desk.DeskAction(token=desk.make_token(owner, rid, ""), rid=rid, occurrence="",
                                          action="done", at=1.0))
    desk_round(bot)
    assert items(bot) == [] and spool(bot).todos_for_win(owner)[0].items == []


# ── 承諾把關：有回執才准說「會提醒你」 ─────────────────────────────────────

def test_f_promise_passes_with_a_receipt_and_is_sent_back_without(make_bot, owner, monkeypatch, tmp_path):
    said = "好，今天 00:51 會提醒你倒垃圾。"
    add = {"tool": "remind__add", "args": {"time": "12.51", "text": "倒垃圾"}}
    bot, _tg, _ = setup(make_bot, monkeypatch, tmp_path, script=[add, said])
    bot.talk(owner, "12.51 提醒我倒垃圾")
    assert bot.last(owner) == said                                              # 真的排上了（有回執）：放行
    assert len(items(bot)) == 1

    past = {"tool": "remind__add", "args": {"time": "00:30", "text": "倒垃圾", "repeat": "once"}}
    blocked, _tg2, _ = setup(make_bot, monkeypatch, tmp_path, script=[past] + [said] * 3)   # 同一份資料夾、新的一支
    before = len(items(blocked))
    blocked.talk(owner, "00:30 提醒我倒垃圾")
    sent = blocked.last(owner)
    assert sent.startswith(claims.PROMISE_PREFIX) and "沒有排上" in sent           # 時間已過被擋下：沒有回執＝退回
    assert len(items(blocked)) == before
