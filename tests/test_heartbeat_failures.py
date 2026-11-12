# -*- coding: utf-8 -*-
"""心跳：失敗狀態沒變就不再叫 AI、同一批失敗只通知一次（docs/adr/0001 §3「沒事別吵」規則 1 的 2026-11 修訂）。

全部離線：假時鐘、同步執行、假的常駐助理（只計次、回固定的 Verdict）、假 app（通知收進 list）；
不連網、不開埠、不叫 Telegram／AI／claude。每個測試用自己的暫存資料夾放 state.json。
"""

import json
import re
from datetime import datetime, timedelta

import pytest

from synox.runtime import heartbeat as hbmod
from synox.runtime.heartbeat import TASK_ID as HB, Heartbeat, failure_key
from synox.runtime.loop import RuntimeLoop
from synox.runtime.mother import Verdict

T0 = datetime(2026, 11, 12, 14, 0, 0)
SETTINGS = {"enabled": True, "interval_min": 45, "quiet_hours": "23:00-08:00",
            "daily_max_notify": 4, "daily_max_calls": 40}


class Clock:
    """假時鐘：epoch 秒與 datetime 一起走。"""

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
    owner_id = 1

    def __init__(self):
        self.sent = []
        self.extras = {}              # 沒有提醒、沒有對話助理：快照只有任務

    def notify_owner(self, text):
        self.sent.append(text)


class FakeMother:
    """假的常駐助理：只計次，每次回一個 Verdict（每次措辭都不一樣，才測得到「同一批失敗」的去重）。"""

    enabled = True
    soul = None

    def __init__(self, notify="有任務壞了（第 {n} 次看）"):
        self.notify = notify
        self.calls = 0

    @property
    def state(self):
        return "idle"

    def supervise(self, facts, *, summary="", when=""):
        self.calls += 1
        text = self.notify.format(n=self.calls) if self.notify else ""
        return Verdict(notify=text, raw=text, called=True)


class Env:
    """一個 SYNOX 的心跳：loop＋Heartbeat 共用一份 state.json；start() 再呼叫一次＝重開。"""

    def __init__(self, tmp_path, settings=None, saved=None, start=T0):
        self.clock = Clock(start)
        self.path = tmp_path / "state.json"
        if saved is not None:
            self.path.write_text(saved if isinstance(saved, str) else json.dumps(saved), encoding="utf-8")
        self.app = FakeApp()
        self.mother = FakeMother()
        self.settings = dict(SETTINGS, **(settings or {}))
        self.start()

    def start(self):
        self.loop = RuntimeLoop(self.app, clock=self.clock, spawn=sync, state_path=str(self.path))
        self.hb = Heartbeat(self.app, self.loop, self.mother, settings=self.settings, now=self.clock.now)
        self.hb.register()

    def fail(self, message="API 回 503", task="pack.weather"):
        assert self.loop.report(task, "failed", message) is not None

    def ok(self, task="pack.weather"):
        assert self.loop.report(task, "ok", "好了") is not None

    def beat(self, manual=False, minutes=45):
        self.clock.advance(minutes=minutes)
        assert self.loop.run_now(HB, manual=manual)
        assert self.loop.task(HB).state == "ok", self.loop.task(HB).last_message
        return self.hb.last_result

    @property
    def calls(self):
        return self.mother.calls

    @property
    def notified(self):
        return [m for m in self.app.sent if "常駐助理" in m]


# ── 失敗指紋 ─────────────────────────────────────────────────────────

def test_failure_key_drops_numbers_spaces_and_is_cut():
    assert failure_key("第 3 次重試失敗，等了 12 秒") == failure_key("第 4 次重試失敗，等了 30 秒")
    assert failure_key("  連不上\n\t伺服器   ") == "連不上 伺服器"
    assert failure_key("2026-11-12 14:00 逾時") == "#-#-# #:# 逾時"
    assert failure_key("API 回 503") != failure_key("API 金鑰過期")
    assert len(failure_key("壞" * 500)) == hbmod.FAIL_CUT
    assert failure_key(None) == "" and failure_key("") == ""


# ── 1、2：失敗沒變就不叫 AI ───────────────────────────────────────────

def test_same_failure_ten_beats_calls_ai_once_and_notifies_once(tmp_path):
    env = Env(tmp_path)
    env.fail()
    results = [env.beat() for _ in range(10)]
    assert env.calls == 1 and len(env.notified) == 1
    assert results[0].startswith("通知了你")
    for r in results[1:]:
        assert "失敗狀態沒有變化" in r and "1 個失敗" in r and "沒有叫 AI" in r


def test_only_numbers_changed_is_not_a_change(tmp_path):
    env = Env(tmp_path)
    env.fail("第 3 次重試失敗，等了 12 秒")
    env.beat()
    env.fail("第 4 次重試失敗，等了 30 秒")
    assert "失敗狀態沒有變化" in env.beat()
    env.fail("第 15 次重試失敗，等了 1800 秒")
    env.beat()
    assert env.calls == 1 and len(env.notified) == 1


# ── 3、4：組成變了才再叫 ─────────────────────────────────────────────

def test_changed_reason_or_new_failed_task_calls_ai_again(tmp_path):
    env = Env(tmp_path)
    env.fail("API 回 503")
    env.beat()
    env.fail("API 金鑰過期")                              # 原因真的變了
    assert env.beat().startswith("通知了你")
    assert env.calls == 2 and len(env.notified) == 2
    env.fail("連不上", task="pack.mail")                   # 多了一個壞掉的任務
    assert env.beat().startswith("通知了你")
    assert env.calls == 3 and len(env.notified) == 3
    assert "2 個失敗" in env.beat()                        # 之後又不變了
    assert env.calls == 3


def test_recovery_is_one_change_then_quiet(tmp_path):
    env = Env(tmp_path)
    env.fail()
    env.beat()
    env.ok()
    env.beat()                                           # 恢復＝一次變化
    assert env.calls == 2
    assert env.beat() == hbmod.R_QUIET_FACTS             # 之後沒事
    assert env.calls == 2
    env.fail()                                           # 又壞了（新的一輪）：會再叫、可以再通知
    assert env.beat().startswith("通知了你")
    assert env.calls == 3 and len(env.notified) == 3


# ── 5：換日 ──────────────────────────────────────────────────────────

def test_new_day_calls_at_most_once_and_does_not_renotify(tmp_path):
    env = Env(tmp_path)
    env.fail()
    env.beat()
    env.clock.dt = datetime(2026, 11, 13, 9, 0)          # 隔天（安靜時段之外）
    result = env.beat(minutes=0)
    assert env.calls == 2 and "這批失敗之前已經通知過" in result
    env.beat()
    env.beat()
    assert env.calls == 2 and len(env.notified) == 1


# ── 6：手動 ──────────────────────────────────────────────────────────

def test_manual_always_calls_ai_but_same_failures_notify_once(tmp_path):
    env = Env(tmp_path)
    env.fail()
    env.beat()
    assert "這批失敗之前已經通知過" in env.beat(manual=True)
    env.beat(manual=True)
    assert env.calls == 3 and len(env.notified) == 1
    env.fail("pack 掛了", task="pack.mail")              # 組成變了：手動那次可以通知
    assert env.beat(manual=True).startswith("通知了你")
    assert len(env.notified) == 2


class FakeAgent:
    """對話助理的最近紀錄（只給 latest_history）。"""

    def __init__(self):
        self.history = []

    def latest_history(self, owner):
        return list(self.history)


class Msg:
    def __init__(self, role, content):
        self.role, self.content = role, content


def test_same_failures_do_not_block_news_from_chat(tmp_path):
    env = Env(tmp_path)
    agent = env.app.extras["synox_agent"] = FakeAgent()
    env.fail()
    env.beat()
    agent.history.append(Msg("user", "明天提醒我繳費"))     # 對話變了：AI 可能在講這件事，不擋
    assert env.beat().startswith("通知了你")
    assert env.calls == 2 and len(env.notified) == 2
    assert "這批失敗之前已經通知過" in env.beat(manual=True)   # 之後什麼都沒變：照樣擋
    assert len(env.notified) == 2


# ── 7：重開 ──────────────────────────────────────────────────────────

def test_restart_with_same_save_does_not_call_again(tmp_path):
    env = Env(tmp_path)
    env.fail("第 1 次：API 回 503")
    env.beat()
    saved = json.loads(env.path.read_text(encoding="utf-8"))["heartbeat"]
    assert set(saved) >= {"last_result", "last_hash", "notified_failures"}
    assert re.fullmatch(r"[0-9a-f]{64}", saved["last_hash"])
    assert list(saved["notified_failures"]) == ["pack.weather"]                    # 只有任務 id＋雜湊
    assert all(re.fullmatch(r"[0-9a-f]{16}", v) for v in saved["notified_failures"].values())
    assert "API" not in env.path.read_text(encoding="utf-8").replace(saved["last_result"], "")   # 訊息原文不落地
    env.start()                                         # 重開：新的 loop、新的 Heartbeat，同一份存檔
    env.fail("第 2 次：API 回 503")                       # pack 重開後再回報一次（只有數字不同）
    assert "失敗狀態沒有變化" in env.beat()
    assert env.calls == 1
    env.beat(manual=True)                                # 手動一定叫，但通知過的那批不再通知
    assert env.calls == 2 and len(env.notified) == 1


def test_restart_before_pack_reports_again_does_not_renotify(tmp_path):
    env = Env(tmp_path)
    env.fail()
    env.beat()
    env.start()                                          # 重開後 pack 還沒回報：任務暫時不在清單裡
    env.mother.notify = ""                               # （這時候 AI 看不到失敗，沒什麼好說）
    env.beat()
    env.mother.notify = "有任務壞了（第 {n} 次看）"
    env.fail()                                           # 回報了同一個失敗
    assert "這批失敗之前已經通知過" in env.beat()
    assert len(env.notified) == 1


# ── 8：上限、安靜時段照舊 ───────────────────────────────────────────

def test_daily_max_calls_still_applies(tmp_path):
    env = Env(tmp_path, settings={"daily_max_calls": 2})
    env.fail("原因甲")
    env.beat()
    env.fail("原因乙")
    env.beat()
    env.fail("原因丙")
    assert "次數用完" in env.beat()
    assert "次數用完" in env.beat(manual=True)
    assert env.calls == 2


def test_daily_max_notify_still_applies(tmp_path):
    env = Env(tmp_path, settings={"daily_max_notify": 1})
    env.fail("原因甲")
    env.beat()
    env.fail("原因乙")
    assert "通知的次數到上限" in env.beat()
    assert env.calls == 2 and len(env.notified) == 1


def test_quiet_hours_hold_then_ask_once_after_they_end(tmp_path):
    env = Env(tmp_path, settings={"quiet_hours": "13:00-15:00"}, start=datetime(2026, 11, 12, 14, 0))
    env.fail()
    assert "在安靜時段" in env.beat(minutes=15)           # 14:15 有事，但安靜時段不通知
    assert "失敗狀態沒有變化" in env.beat(minutes=15)      # 14:30 還在安靜時段：不再叫
    assert env.calls == 1 and env.notified == []
    assert env.beat(minutes=45).startswith("通知了你")    # 15:15 安靜時段過了：再叫一次、通知
    assert env.calls == 2 and len(env.notified) == 1
    env.beat()
    assert env.calls == 2


def test_quiet_hours_do_not_hold_manual(tmp_path):
    env = Env(tmp_path, start=datetime(2026, 11, 12, 23, 0))
    env.fail()
    assert "在安靜時段" in env.beat(minutes=15)
    assert env.beat(manual=True, minutes=1).startswith("通知了你")
    assert env.calls == 2 and len(env.notified) == 1


def test_quiet_hold_survives_restart(tmp_path):
    env = Env(tmp_path, settings={"quiet_hours": "13:00-15:00"}, start=datetime(2026, 11, 12, 14, 0))
    env.fail()
    env.beat(minutes=15)
    env.start()
    env.fail()
    env.beat(minutes=15)                                 # 14:30 還在安靜時段
    assert env.calls == 1
    assert env.beat(minutes=45).startswith("通知了你")
    assert len(env.notified) == 1


def test_no_failures_behaves_as_before(tmp_path):
    env = Env(tmp_path)
    env.mother.notify = ""
    assert env.beat() == hbmod.R_NOTHING
    assert env.beat() == hbmod.R_QUIET_FACTS
    env.beat(manual=True)
    assert env.calls == 2


# ── 9：壞掉的存檔 ────────────────────────────────────────────────────

@pytest.mark.parametrize("saved", [
    "{oops",
    {"heartbeat": [1, 2]},
    {"heartbeat": "x"},
    {"heartbeat": None},
    {"heartbeat": {"last_result": 3, "last_hash": 5, "notified_failures": "abc", "held_failures": [1]}},
    {"heartbeat": {"last_hash": "不是雜湊", "notified_failures": {"pack.weather": 7}, "held_failures": {"": "x"}}},
    {"heartbeat": {"last_hash": "f" * 64, "notified_failures": {"pack.weather": ["x"]}}},
])
def test_broken_save_does_not_break_heartbeat(tmp_path, saved):
    env = Env(tmp_path, saved=saved)
    env.fail()
    assert env.beat().startswith("通知了你")
    assert env.calls == 1 and len(env.notified) == 1
    assert "失敗狀態沒有變化" in env.beat()
