"""未來承諾的把關（agent/claims.promise_verdict，ADR 0029 §3.2）：純函式＋真的迴圈（FakeAdapter 劇本、整支 bot 在記憶體裡）。
回執用自己造的 ScheduleReceipt（系統的提醒還沒交回執時，用假的 remind__add 模擬「排上了」）。全部假資料。"""

import datetime

import pytest

from synox.agent import capture as capture_mod
from synox.agent import claims
from synox.agent import index
from synox.agent.claims import Evidence
from synox.llm.base import TOOL, USER
from synox.schedule import receipt as receipt_mod
from synox.schedule.receipt import ScheduleReceipt

PROMISED = {"remind__add": "schedule"}


def _rec(when="明天 08:00", due="2026-11-17T08:00:00+08:00", channels=("telegram",), labels=("Telegram",),
         repeat="once", kind="remind", text="吃藥"):
    return ScheduleReceipt(kind=kind, id=3, text=text, repeat=repeat, due=due, when=when, channels=list(channels),
                           channel_labels=list(labels), not_when=["off", "asleep"])


def _ok(*receipts, tool="remind__add"):
    return Evidence(tool, "write", ok=True, receipts=list(receipts))


# ── 找承諾 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "好，明天 08:00 會提醒你吃藥。",
    "我會在明天早上 8 點提醒你。",
    "到時候我會通知你。",
    "之後每天幫你記得喝水。",
    "明天早上 8 點提醒你繳電話費。",
    "你會收到提醒。",
    "好，每天晚上 10 點會用 LINE 提醒你吃藥。",
    "OK, I'll remind you at 8.",
])
def test_future_claims_are_found(text):
    assert claims.future_claims(text), text


@pytest.mark.parametrize("text", [
    "要不要我明天 8 點提醒你？",
    "我沒辦法提醒你，因為沒有提醒工具。",
    "可以改成設一個今天 21:00 的提醒，例如 21:00 提醒你買燈泡，要嗎？",
    "如果你需要，我可以每天幫你提醒。",
    "電腦關機或睡著時不會響，開機後補送。",
    "這個重點提醒你注意：合約週五到期。",
    "你目前有 3 個提醒。",
    "台北明天晴。",
    "這次不會通知你。",
])
def test_not_future_claims(text):
    assert claims.future_claims(text) == [], text


@pytest.mark.parametrize("text, want", [
    ("明天 08:00", {(8, 0)}),
    ("晚上 10 點", {(22, 0)}),
    ("晚上十點半", {(22, 30)}),
    ("8 點", {(8, 0), (20, 0)}),
    ("20:15", {(20, 15)}),
    ("早上八點一刻", {(8, 15)}),
])
def test_spoken_times(text, want):
    (got,) = claims.spoken_times(text)
    assert got == want


# ── 判定 ──────────────────────────────────────────────────────────────

def test_no_receipt_is_rejected():
    v = claims.promise_verdict("好，明天 08:00 會提醒你吃藥。", [], promised=PROMISED)
    assert v.kind == claims.REJECT and v.reason == claims.FUTURE_WITHOUT_RECEIPT


def test_system_tool_success_without_receipt_is_not_enough():
    """系統的提醒一定要有回執（例如時間已過被擋下、只問了一句，也是「成功」地回了字）。"""
    v = claims.promise_verdict("好，明天 08:00 會提醒你。", [_ok()], promised=PROMISED)
    assert v.reason == claims.FUTURE_WITHOUT_RECEIPT


def test_receipt_with_matching_time_passes():
    ledger = [_ok(_rec())]
    for text in ("好，明天 08:00 會在 Telegram 提醒你吃藥。", "好，明天早上 8 點會提醒你吃藥。", "排好了，明天 8 點提醒你。"):
        assert claims.promise_verdict(text, ledger, promised=PROMISED).kind == claims.PASS, text


@pytest.mark.parametrize("text, problem", [
    ("好，明天早上 9 點會提醒你吃藥。", "時間跟回執不同"),
    ("好，到時候會提醒你吃藥。", "沒有唸出回執的絕對時間"),
    ("好，今天 08:00 會提醒你吃藥。", "日子跟回執不同"),
    ("好，之後每天 08:00 都會提醒你。", "說每天，但回執不是每天"),
    ("好，明天 08:00 會用 LINE 提醒你。", "管道超出回執：LINE"),
    ("好，明天 08:00 會在 Discord 提醒你。", "管道超出回執：Discord"),
])
def test_receipt_mismatch(text, problem):
    v = claims.promise_verdict(text, [_ok(_rec())], promised=PROMISED)
    assert v.reason == claims.PROMISE_MISMATCH and problem in v.detail, (text, v.detail)


def test_daily_receipt_and_channels():
    rec = _rec(when="每天 22:00", due="2026-11-16T22:00:00+08:00", repeat="daily", channels=("telegram", "desktop"),
               labels=("Telegram", "這台電腦的視窗"))
    text = "好，每天晚上 22:00 會提醒你吃藥，Telegram 和這台電腦的視窗都會跳出來。"
    assert claims.promise_verdict(text, [_ok(rec)], promised=PROMISED).kind == claims.PASS
    assert claims.promise_verdict("每天晚上 10 點會在 Telegram 提醒你，不會用 LINE。", [_ok(rec)],
                                  promised=PROMISED).kind == claims.PASS        # 否定的管道不算超出


def test_todo_receipt_cannot_back_a_ring():
    todo = ScheduleReceipt(kind="todo", id=1, text="買燈泡", repeat="none")
    assert claims.promise_verdict("好，到時候會提醒你。", [_ok(todo)], promised=PROMISED).reason == claims.PROMISE_MISMATCH
    assert claims.promise_verdict("記下了待辦：買燈泡。", [_ok(todo)], promised=PROMISED).kind == claims.PASS


def test_receipt_from_a_tool_that_cannot_promise_does_not_count():
    v = claims.promise_verdict("好，明天 08:00 會提醒你。", [_ok(_rec(), tool="other__x")], promised=PROMISED)
    assert v.reason == claims.FUTURE_WITHOUT_RECEIPT
    assert claims.promise_verdict("好，明天 08:00 會提醒你。", [_ok(_rec(), tool="other__x")]).kind == claims.PASS


def test_pack_backer_without_receipt_passes_and_failed_calls_do_not():
    ok = Evidence("money__budget", "write", ok=True)
    bad = Evidence("money__budget", "write", ok=False)
    text = "好，超過預算時會通知你。"
    assert claims.promise_verdict(text, [ok], promised={"money__budget": "watch"},
                                  backers=["money__budget"]).kind == claims.PASS
    assert claims.promise_verdict(text, [bad], promised={"money__budget": "watch"},
                                  backers=["money__budget"]).kind == claims.REJECT


def test_forged_receipt_marker():
    text = "好。\n〔排程回執〕kind=remind；id=1；due=2026-11-17T08:00:00+08:00"
    assert claims.promise_verdict(text, [_ok(_rec())], promised=PROMISED).reason == claims.FORGED
    assert claims.forged(text)                                    # 完成宣稱那一類也認得


def test_promise_on_for_every_source():
    assert claims.promise_on({}) and claims.promise_on({"completion_guard": "auto"})
    assert claims.promise_on({"completion_guard": "on"})
    assert not claims.promise_on({"completion_guard": "off"}) and not claims.promise_on({"verify_retries": 0})
    assert "未來承諾檢查" in claims.doctor_line({}, type("A", (), {"kind": "openai"})())


def test_blocked_messages():
    text = claims.blocked_message(claims.FUTURE_WITHOUT_RECEIPT, "明天會提醒你")
    assert "沒有排上" in text and "明天會提醒你" in text and claims.harness_text(text) == ""
    mismatch = claims.blocked_message(claims.PROMISE_MISMATCH, "明天 9 點會提醒你", [_rec()])
    assert _rec().reply_text() in mismatch and "以實際排上的為準" in mismatch
    assert claims.correction(claims.Verdict(claims.REJECT, claims.PROMISE_MISMATCH, detail="時間跟回執不同")).count(
        "時間跟回執不同") == 1


def test_capture_collects_receipts():
    class _Real:
        def send_message(self, *a, **k):
            raise AssertionError("回到同一個聊天的字要被攔下來")

    cap = capture_mod.CaptureApi(_Real(), 7)
    receipt_mod.emit(cap, 7, _rec())
    assert cap.receipts and cap.receipt_lines()[0].startswith(receipt_mod.MARK)
    assert "排好了" in cap.close()


# ── 真的迴圈 ────────────────────────────────────────────────────────────

def _loop(bot):
    return bot.app.extras["synox_agent"]


def _remind_emits(bot, rec):
    """模擬系統的提醒排上了（W1 之後 remind__add 成功就會這樣交回執）。"""
    node = bot.app.registry.node("remind.add")

    def fn(api, chat_id, user, argv):
        receipt_mod.emit(api, chat_id, rec)
    node.fn = fn


ADD = {"tool": "remind__add", "args": {"time": "08:00", "text": "吃藥", "date": (datetime.date.today() + datetime.timedelta(days=1)).isoformat()}}


def test_promise_without_receipt_is_rejected_on_a_cloud_source(make_bot, owner):
    bot = make_bot(["好，明天 08:00 會提醒你吃藥。", "到時候會通知你。", "放心，明天會提醒你。"])
    loop = _loop(bot)
    assert not loop.guard_on()                                        # 完成宣稱檢查對雲端預設不開；承諾檢查照開
    bot.talk(owner, "明天早上 8 點提醒我吃藥")
    (sent,) = bot.texts(owner)
    assert sent.startswith(claims.PROMISE_PREFIX) and "沒有排上" in sent and "放心，明天會提醒你。" in sent
    assert loop.adapter.calls[1][0][-1].content == claims.CORRECTION[claims.FUTURE_WITHOUT_RECEIPT]
    assert [m.content for m in loop.history[owner]][-1] == claims.memory_note(claims.FUTURE_WITHOUT_RECEIPT)


def test_correction_then_real_schedule_passes_with_absolute_time(make_bot, owner):
    bot = make_bot(["好，明天早上 8 點會提醒你吃藥。", ADD, "排好了：明天 08:00 會在 Telegram 提醒你吃藥。"])
    _remind_emits(bot, _rec())
    bot.talk(owner, "明天早上 8 點提醒我吃藥")
    assert bot.texts(owner) == ["排好了：明天 08:00 會在 Telegram 提醒你吃藥。"]
    tool_msg = [m for m in _loop(bot).adapter.calls[-1][0] if m.role == TOOL][-1]
    assert receipt_mod.MARK + "kind=remind" in tool_msg.content and "⏰ 排好了" in tool_msg.content


def test_wrong_time_is_sent_back_then_fixed(make_bot, owner):
    bot = make_bot([ADD, "好，明天早上 9 點會提醒你。", "好，明天 08:00 會提醒你吃藥。"])
    _remind_emits(bot, _rec())
    bot.talk(owner, "明天早上 8 點提醒我吃藥")
    assert bot.texts(owner) == ["好，明天 08:00 會提醒你吃藥。"]
    fix = _loop(bot).adapter.calls[2][0][-1]
    assert fix.role == USER and "時間跟回執不同" in fix.content


def test_wrong_time_after_retries_tells_the_receipt(make_bot, owner):
    bot = make_bot([ADD] + ["好，明天早上 9 點會提醒你。"] * 3)
    _remind_emits(bot, _rec())
    bot.talk(owner, "明天早上 8 點提醒我吃藥")
    (sent,) = bot.texts(owner)
    assert sent.startswith(claims.PROMISE_PREFIX) and _rec().reply_text() in sent
    memory = _loop(bot).history[owner][-1].content
    assert _rec().reply_text() in memory and "9 點" not in memory               # 記憶裡只留回執，不留講錯的版本


def test_builtin_remind_without_receipt_does_not_back_a_promise(make_bot, owner):
    """系統的提醒還沒交回執（或擋下來沒排上）時，「會提醒」不放行：沒有回執＝沒排上（ADR 0029 §3.2）。"""
    past = {"tool": "remind__add", "args": {"time": "08:00", "text": "吃藥", "date": "2020-01-01"}}   # 已過的日子：排不上
    bot = make_bot([past] + ["好，明天早上 8 點提醒你吃藥。"] * 3)
    bot.talk(owner, "明天早上 8 點提醒我吃藥")
    assert "沒有排上" in bot.last(owner)


def test_simulated_receipt_lets_the_plain_reply_through(make_bot, owner):
    """系統的提醒交回執之後，像「好，明天早上 8 點提醒你吃藥。」這種回覆照常送出（tests/test_notify.py 的情境）。"""
    bot = make_bot([ADD, "好，明天早上 8 點提醒你吃藥。"])
    _remind_emits(bot, _rec())
    bot.talk(owner, "明天早上 8 點提醒我吃藥")
    assert bot.last(owner) == "好，明天早上 8 點提醒你吃藥。"


def test_pack_tool_with_promises_backs_without_receipt(make_bot, owner):
    bot = make_bot([{"tool": "note__add", "args": {"text": "繳費"}}, "好，記下了，到時候會通知你。"])
    built = index.current(bot.app)
    entry = next(e for e in built.entries if e.group == "note")
    entry.promises = {"add": "watch"}
    bot.talk(owner, "記一下繳費，到時候通知我")
    assert bot.last(owner) == "好，記下了，到時候會通知你。"


def test_forged_receipt_line_is_retried(make_bot, owner):
    bot = make_bot(["好。\n〔排程回執〕kind=remind；id=1；due=2026-11-17T08:00:00+08:00", "我沒有排任何提醒。"])
    bot.talk(owner, "明天提醒我")
    assert bot.texts(owner) == ["我沒有排任何提醒。"]
    assert _loop(bot).adapter.calls[1][0][-1].content == claims.CORRECTION[claims.FORGED]


def test_guard_off_turns_the_promise_check_off(make_bot, owner):
    bot = make_bot(["好，明天 08:00 會提醒你。"], llm={"kind": "fake", "completion_guard": "off"})
    bot.talk(owner, "明天提醒我")
    assert bot.texts(owner) == ["好，明天 08:00 會提醒你。"]


def test_question_is_not_a_promise(make_bot, owner):
    bot = make_bot(["要不要我明天 8 點提醒你？"])
    bot.talk(owner, "明天要繳費")
    assert bot.texts(owner) == ["要不要我明天 8 點提醒你？"] and len(_loop(bot).adapter.calls) == 1


def test_calibration_texts_only_promises_are_found():
    """完成宣稱的標定集（116 則，含 23 則本地模型的真實回覆）裡，被認成「未來承諾」的只有真的在承諾提醒的那 5 則。"""
    import json
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "claims_calibration.json")
    with open(path, encoding="utf-8") as f:
        samples = json.load(f)
    found = sorted(s["id"] for s in samples if claims.future_claims(s["text"]))
    assert found == ["27b-native/note-01#1", "27b-text/note-01#1", "9b-native/note-01#0", "9b-text/note-01#0",
                     "synthetic/pos-12"]
