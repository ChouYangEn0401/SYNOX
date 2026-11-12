# -*- coding: utf-8 -*-
"""連動（activator，docs/adr/0004）：任務狀態一變就照規則做下一件事；防循環、防暴衝；留給心跳；網頁 API。

全部用假時鐘、同步執行（spawn）、假通道；不連網、不開埠。
"""

import json
import os
import shutil

import pytest

from synox import runtime
from synox.config import SynoxConfig
from synox.llm.fake import FakeAdapter
from synox.runtime import settings as rs
from synox.runtime.activator import Activator, Rule, RuleError
from synox.runtime.loop import NOTIFY_AFTER, RuntimeLoop

from conftest import OTHER_ID
from test_runtime import FIXTURES, Clock, FakeApp, api, rt_bot, sync   # noqa: F401（fixture）
from test_web import Client, ui_of


def make(tmp_path, **settings):
    clock = Clock()
    app = FakeApp()
    loop = RuntimeLoop(app, clock=clock, spawn=sync, state_path=str(tmp_path / "state.json"))
    act = Activator(loop, settings=settings)
    return app, loop, act, clock


def rule(rid, on, **kw):
    kw.setdefault("owner", "system")
    return Rule(id=rid, on=on, **kw)


# ── 設定（config.json 的 runtime.activator）───────────────────────────────

def test_config_defaults_and_rule_validation(tmp_path):
    cfg = SynoxConfig.from_dict({"owner_id": 1}, require_token=False, root=str(tmp_path))
    act = cfg.runtime["activator"]
    assert act["enabled"] is True and act["max_depth"] == 5 and act["max_chain_actions"] == 20
    assert act["max_fanout"] == 10 and act["budget_window_min"] == 10 and act["budget_max_actions"] == 60
    assert act["rules"] == []
    good = {"id": "weather-back", "on": "pack.weather", "state": "ok", "from": "failed", "notify": "天氣恢復了"}
    parsed = rs.parse({"activator": {"rules": [good]}})["activator"]["rules"][0]
    assert parsed["state"] == ["ok"] and parsed["from"] == ["failed"] and parsed["timing"] == "now"
    assert parsed["max_per_hour"] == 30 and parsed["cooldown_s"] == 0 and parsed["tag"] is None
    bads = [
        {"id": "x", "on": "pack.a"},                                                     # 沒有動作
        {"id": "x", "on": "pack.a", "notify": "a", "run_task": "pack.b"},                # 兩個動作
        {"id": "system.x", "on": "pack.a", "notify": "a"},                               # 保留的前綴
        {"id": "x", "on": "pack.a", "notify": "a", "state": "done"},
        {"id": "x", "on": "pack.a", "notify": "a", "timing": "later"},
        {"id": "x", "on": "pack.a", "notify": "a", "max_per_hour": 0},
        {"id": "x", "on": "pack.a", "notify": "a", "tag": "Bad Tag"},
        {"id": "x", "on": "pack.a", "notify": "a", "do": "os.system"},                   # 不收程式
        {"id": "X", "on": "pack.a", "notify": "a"},
    ]
    for bad in bads:
        with pytest.raises(Exception) as e:
            SynoxConfig.from_dict({"owner_id": 1, "runtime": {"activator": {"rules": [bad]}}},
                                  require_token=False, root=str(tmp_path))
        assert "runtime" in str(e.value)
    with pytest.raises(rs.RuntimeConfigError):
        rs.parse({"activator": {"max_depth": 0}})
    with pytest.raises(rs.RuntimeConfigError):
        rs.parse({"activator": {"rules": [good, good]}})                                 # 同 id 兩條


def test_config_cycles_are_rejected_at_load():
    """靜態找循環：A 跑 Y、B 聽 Y 跑 X、A 聽 X → 不收；自己觸發自己也不收。"""
    loop2 = [{"id": "a", "on": "system.x", "run_task": "system.y"}, {"id": "b", "on": "system.y", "run_task": "system.x"}]
    with pytest.raises(rs.RuntimeConfigError) as e:
        rs.parse({"activator": {"rules": loop2}})
    assert "a → b → a" in str(e.value)
    with pytest.raises(rs.RuntimeConfigError):
        rs.parse({"activator": {"rules": [{"id": "self", "on": "system.x", "state": "failed", "run_task": "system.x"}]}})
    # 跑任務做完沒有標籤：聽特定標籤的規則接不到，不算循環
    ok = [{"id": "a", "on": "pack.p", "tag": "img", "run_task": "system.y"},
          {"id": "b", "on": "system.y", "notify": "好了"}]
    assert len(rs.parse({"activator": {"rules": ok}})["activator"]["rules"]) == 2


def test_find_cycle_respects_tags():
    # (id, 聽的任務, 聽的標籤, [(會讓哪個任務有新狀態, 標籤)])
    assert rs.find_cycle([("a", "pack.d", "image", [("pack.d", "asked")])]) == []
    assert rs.find_cycle([("a", "pack.d", "image", [("pack.d", None)])]) == ["a", "a"]       # 不知道標籤＝當作可能
    assert rs.find_cycle([("a", "pack.d", None, [("pack.d", "asked")])]) == ["a", "a"]


# ── 馬上連動、因果串 ─────────────────────────────────────────────────────

def test_report_triggers_rule_immediately_and_chain_carries_through_run_task(tmp_path):
    app, loop, act, clock = make(tmp_path)
    ran = []
    loop.register("system.sync", "同步", fn=lambda ctx: ran.append(1) or "好", interval=3600)
    act.add(rule("system.after-weather", "pack.weather", states=("ok",), run_task="system.sync"))
    act.add(rule("system.after-sync", "system.sync", notify="同步做完了（{task} {state}）"))
    loop.report("pack.weather", "ok", "晴天", owner="weather")
    assert ran == [1]                                                  # 不等心跳、不等排程
    assert app.sent == ["🔗 同步做完了（system.sync ok）"]
    events = act.view()["events"]
    sync_ev, weather_ev = events[0], events[1]
    assert weather_ev["task"] == "pack.weather" and weather_ev["fired"] == ["system.after-weather"]
    assert sync_ev["task"] == "system.sync" and sync_ev["depth"] == 1 and sync_ev["chain"] == weather_ev["chain"]
    assert sync_ev["prev"] == "idle"
    assert any("（連動）" in line for line in loop.task("system.sync").log)


def test_from_state_tag_and_when_conditions(tmp_path):
    app, loop, act, clock = make(tmp_path)
    seen = []
    act.add(rule("system.recovered", "pack.w", states=("ok",), from_states=("failed",), do=lambda ev: seen.append("back")))
    act.add(rule("system.tagged", "pack.w", tag="img", do=lambda ev: seen.append("img")))
    act.add(rule("system.cond", "pack.w", states=("failed",), when=lambda ev: "503" in ev.message,
                 do=lambda ev: seen.append("503")))
    loop.report("pack.w", "ok", owner="w")                  # idle → ok：不是從失敗恢復、沒有標籤
    assert seen == []
    loop.report("pack.w", "failed", "回 500", owner="w")
    loop.report("pack.w", "failed", "回 503", owner="w")
    assert seen == ["503"]
    loop.report("pack.w", "ok", owner="w", tag="img")       # failed → ok、標籤 img
    assert seen == ["503", "back", "img"]


def test_nothing_listening_records_nothing(tmp_path):
    app, loop, act, clock = make(tmp_path)
    loop.report("pack.w", "ok", owner="w")
    assert act.view()["events"] == []


# ── 防無限連動 ───────────────────────────────────────────────────────────

def test_code_rule_cycle_rejected_when_registered(tmp_path):
    app, loop, act, clock = make(tmp_path)
    act.add(rule("system.a", "system.x", run_task="system.y"))
    with pytest.raises(RuleError) as e:
        act.add(rule("system.b", "system.y", run_task="system.x"))
    assert "system.a → system.b → system.a" in str(e.value) or "system.b → system.a → system.b" in str(e.value)
    assert act.add(rule("system.b", "system.y", run_task="system.x"), strict=False) is None
    assert act.view()["rejected"][0]["id"] == "system.b"
    with pytest.raises(RuleError):                          # 宣告 emits 的程式動作也一樣看
        act.add(rule("system.c", "pack.p", do=lambda ev: None, emits=["pack.p"]))


def test_runtime_cycle_through_code_is_caught_and_tripped_once(tmp_path):
    """程式動作沒宣告 emits（靜態看不到）：A 回報 pack.b、B 回報 pack.a → 第二次走到 A＝循環 → 暫停 A、通知一次。"""
    app, loop, act, clock = make(tmp_path)
    calls = []

    def a(ev):
        calls.append("a")
        loop.report("pack.b", "ok", owner="b")

    def b(ev):
        calls.append("b")
        loop.report("pack.a", "ok", owner="a")

    act.add(rule("system.a", "pack.a", do=a))
    act.add(rule("system.b", "pack.b", do=b))
    loop.report("pack.a", "ok", owner="a")
    assert calls == ["a", "b"]
    view = {r["id"]: r for r in act.view()["rules"]}
    assert view["system.a"]["status"] == "tripped" and "循環" in view["system.a"]["reason"]
    assert view["system.b"]["status"] == "active"
    assert len(app.sent) == 1 and "暫停" in app.sent[0]
    loop.report("pack.a", "ok", owner="a")                  # 暫停中：不再動、不再通知
    assert calls == ["a", "b"] and len(app.sent) == 1
    assert act.reset_rule("system.a") is True
    assert {r["id"]: r for r in act.view()["rules"]}["system.a"]["status"] == "active"


def test_depth_limit_trips(tmp_path):
    app, loop, act, clock = make(tmp_path, max_depth=2)
    hops = []
    for i in range(4):
        act.add(rule(f"system.h{i}", f"pack.t{i}",
                     do=lambda ev, i=i: (hops.append(i), loop.report(f"pack.t{i + 1}", "ok", owner="t"))))
    loop.report("pack.t0", "ok", owner="t")
    assert hops == [0, 1]                                    # 第 0、1 層做了，第 2 層擋下
    view = {r["id"]: r for r in act.view()["rules"]}
    assert view["system.h2"]["status"] == "tripped" and "2 層" in view["system.h2"]["reason"]


def test_chain_action_cap_trips_fanout_tree(tmp_path):
    """一個事件觸發很多條、每條又觸發很多條：同一串做的總件數有上限。"""
    app, loop, act, clock = make(tmp_path, max_chain_actions=5)
    done = []
    for i in range(3):
        act.add(rule(f"system.f{i}", "pack.root", do=lambda ev, i=i: (done.append(i), loop.report(f"pack.leaf{i}", "ok", owner="x"))))
        for j in range(3):
            act.add(rule(f"system.l{i}{j}", f"pack.leaf{i}", do=lambda ev: done.append("leaf")))
    loop.report("pack.root", "ok", owner="x")
    assert len(done) == 5
    assert any(r["status"] == "tripped" and "超過 5 件" in r["reason"] for r in act.view()["rules"])


def test_fanout_limit_skips_extra_rules(tmp_path):
    app, loop, act, clock = make(tmp_path, max_fanout=2)
    done = []
    for i in range(3):
        act.add(rule(f"system.r{i}", "pack.x", do=lambda ev, i=i: done.append(i)))
    loop.report("pack.x", "ok", owner="x")
    assert done == [0, 1]
    ev = act.view()["events"][0]
    assert ev["fired"] == ["system.r0", "system.r1"] and ev["skipped"][0]["rule"] == "system.r2"
    assert {r["id"]: r for r in act.view()["rules"]}["system.r2"]["status"] == "active"     # 只略過，不暫停


def test_cooldown_skips_quietly_and_rate_limit_trips(tmp_path):
    app, loop, act, clock = make(tmp_path)
    done = []
    act.add(rule("system.cool", "pack.x", do=lambda ev: done.append("c"), cooldown_s=60))
    act.add(rule("system.rate", "pack.y", do=lambda ev: done.append("r"), max_per_hour=3))
    loop.report("pack.x", "ok", owner="x")
    loop.report("pack.x", "ok", owner="x")
    assert done == ["c"] and app.sent == []
    clock.advance(seconds=61)
    loop.report("pack.x", "ok", owner="x")
    assert done == ["c", "c"]
    for _ in range(4):
        loop.report("pack.y", "ok", owner="y")
    assert done.count("r") == 3
    rate = {r["id"]: r for r in act.view()["rules"]}["system.rate"]
    assert rate["status"] == "tripped" and "3 次" in rate["reason"] and len(app.sent) == 1
    clock.advance(hours=2)                                   # 時間過了也不會自己恢復（要人按重設）
    loop.report("pack.y", "ok", owner="y")
    assert done.count("r") == 3


def test_global_budget_pauses_everything_until_resumed(tmp_path):
    app, loop, act, clock = make(tmp_path, budget_max_actions=4, budget_window_min=10)
    done = []
    for i in range(3):
        act.add(rule(f"system.g{i}", f"pack.g{i}", do=lambda ev, i=i: done.append(i)))
    for _ in range(2):
        for i in range(3):
            loop.report(f"pack.g{i}", "ok", owner="g")
    assert len(done) == 4
    view = act.view()
    assert view["paused"] and "4 件" in view["paused"]["reason"] and view["budget_used"] == 4
    assert sum("全部暫停" in t for t in app.sent) == 1
    assert act.resume() is True and act.view()["paused"] is None
    loop.report("pack.g0", "ok", owner="g")
    assert len(done) == 5


def test_action_failures_trip_after_five(tmp_path):
    app, loop, act, clock = make(tmp_path)

    def boom(ev):
        raise RuntimeError("壞了")

    act.add(rule("system.boom", "pack.x", do=boom))
    for _ in range(NOTIFY_AFTER + 2):
        loop.report("pack.x", "ok", owner="x")
    r = act.view()["rules"][0]
    assert r["status"] == "tripped" and f"連續失敗 {NOTIFY_AFTER} 次" in r["reason"] and r["failures"] == NOTIFY_AFTER
    assert len(app.sent) == 1


def test_trip_notifications_are_throttled(tmp_path):
    app, loop, act, clock = make(tmp_path)
    for i in range(3):
        act.add(rule(f"system.t{i}", "pack.x", do=lambda ev: None, max_per_hour=1))
    loop.report("pack.x", "ok", owner="x")
    loop.report("pack.x", "ok", owner="x")                  # 三條同時超過 → 只通知一則
    assert len(app.sent) == 1
    assert sum(r["status"] == "tripped" for r in act.view()["rules"]) == 3
    clock.advance(minutes=11)
    act.add(rule("system.t9", "pack.y", do=lambda ev: None, max_per_hour=1))
    loop.report("pack.y", "ok", owner="y")
    loop.report("pack.y", "ok", owner="y")
    assert len(app.sent) == 2 and "另外還有 2 條" in app.sent[1]


def test_single_mode_skips_while_running(tmp_path):
    """上一次還沒做完（真的執行緒時）：這次略過，不疊。"""
    app, loop, act, clock = make(tmp_path)
    queued = []
    loop._spawn = lambda fn, name: queued.append(fn)        # 開始了但還沒做完
    done = []
    act.add(rule("system.slow", "pack.x", do=lambda ev: done.append(1)))
    loop.report("pack.x", "ok", owner="x")
    loop.report("pack.x", "ok", owner="x")
    assert len(queued) == 1
    assert "還沒做完" in act.view()["events"][0]["skipped"][0]["reason"]
    queued[0]()
    assert done == [1]


def test_tripped_state_and_pending_survive_restart(tmp_path):
    app, loop, act, clock = make(tmp_path)
    act.add(rule("system.rate", "pack.y", do=lambda ev: None, max_per_hour=1))
    act.add(rule("system.later", "pack.z", notify="晚點說", timing="heartbeat"))
    loop.report("pack.y", "ok", owner="y")
    loop.report("pack.y", "ok", owner="y")
    loop.report("pack.z", "ok", "私人內容", owner="z")
    saved = json.load(open(tmp_path / "state.json", encoding="utf-8"))["activator"]
    assert saved["rules"]["system.rate"]["tripped"] and len(saved["pending"]) == 1
    assert "私人內容" not in json.dumps(saved, ensure_ascii=False)          # 訊息不落地
    loop2 = RuntimeLoop(FakeApp(), clock=clock, spawn=sync, state_path=str(tmp_path / "state.json"))
    act2 = Activator(loop2)
    act2.add(rule("system.rate", "pack.y", do=lambda ev: None, max_per_hour=1))
    act2.add(rule("system.later", "pack.z", notify="晚點說", timing="heartbeat"))
    view = act2.view()
    assert {r["id"]: r for r in view["rules"]}["system.rate"]["status"] == "tripped"
    assert len(view["pending"]) == 1 and view["events"]


# ── 留給心跳 ─────────────────────────────────────────────────────────────

def test_heartbeat_timing_waits_for_heartbeat(rt_bot):
    bot, rt, clock = rt_bot(adapter=FakeAdapter(["QUIET"]))
    rt.activator.add(rule("system.later", "pack.weather", states=("failed",), notify="天氣壞了（不急）",
                          timing="heartbeat"))
    runtime.report(bot.app, "weather", "failed", "API 回 503")
    assert not any("天氣壞了" in t for t in bot.texts())
    pending = rt.status()["activator"]["pending"]
    assert len(pending) == 1 and pending[0]["rule"] == "system.later" and pending[0]["task"] == "pack.weather"
    result = rt.heartbeat.run()
    assert any("🔗 天氣壞了（不急）" in t for t in bot.texts())
    assert "處理了 1 件" in result and rt.status()["activator"]["pending"] == []


def test_pending_kept_while_tripped_and_dropped_after_a_day(tmp_path):
    app, loop, act, clock = make(tmp_path)
    act.add(rule("system.later", "pack.z", notify="晚點說", timing="heartbeat"))
    loop.report("pack.z", "ok", owner="z")
    act._st["system.later"].tripped = "測試"
    assert act.drain() == 0 and len(act.pending) == 1        # 暫停中：留著
    clock.advance(hours=25)
    act.reset_rule("system.later")
    assert act.drain() == 0 and act.pending == []            # 超過一天：丟掉
    assert app.sent == []


# ── pack 定義的規則（例子：日記圖片好了 → 問要不要打卡）────────────────────────

def test_example_diary_image_done_asks_checkin_via_pack(rt_bot, tmp_path):
    packs = tmp_path / "packs"
    shutil.copytree(os.path.join(FIXTURES, "chain_pack"), packs / "diarydemo")
    bot, rt, clock = rt_bot(pack_dirs=(str(packs),))
    owner = bot.app.owner_id
    rules = {r["id"]: r for r in rt.status()["activator"]["rules"]}
    assert "pack.diarydemo.ask-checkin" in rules and rules["pack.diarydemo.ask-checkin"]["owner"] == "diarydemo"
    bot.say(owner, "/diarydemo_image")
    asks = [t for t in bot.texts() if "要打卡今天的日記嗎" in t]
    assert len(asks) == 1 and "pack.diarydemo#diary-image" in asks[0] and "第 0 層" in asks[0]
    task = rt.loop.task("pack.diarydemo")
    assert task.state == "ok" and any("#checkin-asked" in line for line in task.log)
    asked_ev = rt.status()["activator"]["events"]
    assert asked_ev[0]["fired"] == ["pack.diarydemo.ask-checkin"]
    bot.say(owner, "/diarydemo_image failed")                # 圖片失敗：不問
    bot.say(owner, "/diarydemo_image")                       # 60 秒冷卻內：不再問
    assert len([t for t in bot.texts() if "要打卡今天的日記嗎" in t]) == 1
    clock.advance(seconds=61)
    bot.say(owner, "/diarydemo_image")
    assert len([t for t in bot.texts() if "要打卡今天的日記嗎" in t]) == 2


def test_example_diary_chain_as_system_rule(tmp_path):
    """同一個例子用系統程式定義（另一個 bot 可以照這樣寫）：標籤分得出「圖片好了」與「問過了」，不會自己觸發自己。"""
    app, loop, act, clock = make(tmp_path)
    asked = []

    def ask(ev):
        asked.append(ev.task)
        loop.report("pack.diary", "ok", "問過了", owner="diary", tag="checkin-asked")

    act.add(rule("system.diary-checkin", "pack.diary", tag="diary-image", do=ask, emits=["pack.diary#checkin-asked"]))
    loop.report("pack.diary", "ok", "圖片好了", owner="diary", tag="diary-image")
    assert asked == ["pack.diary"] and app.sent == []
    assert act.view()["rules"][0]["status"] == "active"


def test_pack_rule_permissions_and_message_privacy(tmp_path):
    app, loop, act, clock = make(tmp_path)
    with pytest.raises(RuleError):                           # 工具只能跑自己的任務
        act.add(Rule(id="pack.foo.x", on="pack.bar", run_task="system.heartbeat", owner="foo"))
    with pytest.raises(RuleError):                           # id 要用自己的前綴
        act.add(Rule(id="pack.bar.x", on="pack.bar", do=lambda ev: None, owner="foo"))
    with pytest.raises(RuleError):                           # config 的規則不收程式
        act.add(Rule(id="mine", on="pack.bar", do=lambda ev: None, owner="config"))
    got = {}
    act.add(Rule(id="pack.foo.peer", on="pack.bar", do=lambda ev: got.setdefault("bar", ev.message), owner="foo"))
    act.add(Rule(id="pack.foo.self", on="pack.foo", do=lambda ev: got.setdefault("foo", ev.message), owner="foo"))
    loop.report("pack.bar", "ok", "別人的私事", owner="bar")
    loop.report("pack.foo", "ok", "自己的", owner="foo")
    assert got == {"bar": "", "foo": "自己的"}                # 別人的事件看不到訊息（跟 peer_status 一樣）


def test_pack_rule_queued_before_runtime_and_cycle_rejected_not_fatal(rt_bot):
    from synox.runtime import activator as act_mod
    bot, rt, clock = rt_bot()
    # 會繞回自己的 pack 規則：不收、主控面板看得到，不丟例外（不讓整個 pack 載入失敗）
    bad = Rule(id="pack.foo.loop", on="pack.foo", do=lambda ev: None, emits=["pack.foo"], owner="foo")
    assert runtime.add_rule(bot.app, bad) is None
    assert rt.status()["activator"]["rejected"][0]["id"] == "pack.foo.loop"
    with pytest.raises(act_mod.RuleError):                   # 形狀錯：照樣丟給寫的人
        runtime.add_rule(bot.app, Rule(id="pack.foo.bad", on="pack.foo", owner="foo"))


def test_cli_envelope_tag_reaches_rules(rt_bot):
    bot, rt, clock = rt_bot()
    seen = []
    rt.activator.add(rule("system.cli-tag", "pack.syncer", tag="nightly", do=lambda ev: seen.append(ev.tag)))
    assert runtime.ingest_envelope(bot.app, "syncer", {"status": {"state": "ok", "message": "", "tag": "nightly"}})
    assert runtime.ingest_envelope(bot.app, "syncer", {"status": {"state": "ok", "tag": "Not Valid!"}})
    assert seen == ["nightly"]


def test_config_rules_installed_from_config(make_bot):
    raw = {"runtime": {"activator": {"rules": [
        {"id": "weather-back", "on": "pack.weather", "state": "ok", "from": "failed", "notify": "天氣恢復了"}]}}}
    bot = make_bot(raw=raw)
    rt = runtime.of(bot.app)
    rt.use_fakes(spawn=sync)
    runtime.report(bot.app, "weather", "failed", "503")
    runtime.report(bot.app, "weather", "ok", "")
    assert any("🔗 天氣恢復了" in t for t in bot.texts())
    assert rt.status()["activator"]["rules"][0]["owner"] == "config"


def test_disabled_activator_skips_everything(tmp_path):
    app, loop, act, clock = make(tmp_path, enabled=False)
    done = []
    act.add(rule("system.x", "pack.x", do=lambda ev: done.append(1)))
    loop.report("pack.x", "ok", owner="x")
    assert done == [] and "關著" in act.view()["events"][0]["skipped"][0]["reason"]
    assert act.view()["rules"][0]["status"] == "off"


# ── 網頁 API ─────────────────────────────────────────────────────────────

def test_api_activator_status_reset_resume_pending(api):
    bot, rt, clock, client = api()
    act = rt.activator
    act.add(rule("system.rate", "pack.y", do=lambda ev: None, max_per_hour=1))
    act.add(rule("system.later", "pack.z", notify="晚點說", timing="heartbeat"))
    runtime.report(bot.app, "y", "ok")
    runtime.report(bot.app, "y", "ok")
    runtime.report(bot.app, "z", "ok")
    runtime.report(bot.app, "z", "ok")
    status, data = client.get("/api/runtime/status")
    a = data["activator"]
    assert status == 200 and set(a) == {"enabled", "paused", "limits", "budget_used", "rules", "rejected", "pending", "events"}
    assert set(a["limits"]) == {"max_depth", "max_chain_actions", "max_fanout", "budget_window_min", "budget_max_actions"}
    r = {x["id"]: x for x in a["rules"]}["system.rate"]
    assert r["status"] == "tripped" and r["reason"] and r["tripped_at"]
    assert {"id", "name", "owner", "on", "states", "from", "tag", "action", "timing", "status", "reason", "tripped_at",
            "last_fired_at", "fired_last_hour", "max_per_hour", "cooldown_s", "failures", "skipped", "last_note"} == set(r)
    assert len(a["pending"]) == 2
    status, data = client.post("/api/runtime/activator/rules/system.rate/reset")
    assert status == 200 and data["ok"] is True
    assert client.post("/api/runtime/activator/rules/system.nope/reset")[0] == 404
    pid = a["pending"][0]["id"]
    assert client.post(f"/api/runtime/activator/pending/{pid}/dismiss") == (200, {"ok": True})
    assert client.post(f"/api/runtime/activator/pending/{pid}/dismiss")[0] == 404
    status, data = client.post("/api/runtime/activator/pending/run")
    assert status == 200 and data["count"] == 1
    assert any("🔗 晚點說" in t for t in bot.texts())
    status, data = client.post("/api/runtime/activator/resume")
    assert status == 200 and data["ok"] is True
    assert client.post("/api/runtime/activator/nope")[0] == 404


def test_api_activator_owner_only(api):
    bot, rt, clock, client = api()
    other = Client(ui_of(bot))
    bot.app.users.get_or_create(OTHER_ID)
    other.login(OTHER_ID)
    for path in ("/api/runtime/activator/resume", "/api/runtime/activator/pending/run"):
        assert other.post(path)[0] == 403
    status, _h, _b = client.raw("POST", "/api/runtime/activator/resume", b"{}", headers={"X-SYNOX-CSRF": "bad"})
    assert status == 403


def test_sdk_report_status_tag(monkeypatch):
    import io
    from synox.sdk import author
    monkeypatch.setattr(author, "_REGISTRY", list(author._REGISTRY))

    def tagged():
        """帶標籤回報。"""
        author.report_status("ok", "好了", tag="nightly")
        return "hi"

    def badtag():
        """標籤格式不對。"""
        author.report_status("ok", tag="Bad Tag!")

    tools = [author.tool("READ")(f) for f in (tagged, badtag)]
    out = io.StringIO()
    author.run_cli(["tagged", "--json"], out=out, tools=tools)
    assert json.loads(out.getvalue().splitlines()[-1])["status"] == {"state": "ok", "message": "好了", "tag": "nightly"}
    out = io.StringIO()
    author.run_cli(["badtag", "--json"], out=out, tools=tools)
    assert json.loads(out.getvalue().splitlines()[-1])["ok"] is False


def test_doctor_shows_activator(tmp_path):
    from synox import doctor
    cfg = {"owner_id": 1, "data_dir": str(tmp_path / "data"), "vault": {"mode": "file"}, "llm": {"kind": "none"},
           "runtime": {"activator": {"rules": [{"id": "a", "on": "pack.x", "notify": "好了"}]}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    state = tmp_path / "data" / "runtime"
    state.mkdir(parents=True)
    (state / "state.json").write_text(json.dumps({"activator": {
        "rules": {"pack.foo.loop": {"tripped": "循環", "tripped_at": 1.0}}, "paused": None,
        "pending": [{"id": "abcd1234"}]}}), encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "連動：開（config.json 裡 1 條規則" in text and "pack.foo.loop" in text and "等心跳處理：1 件" in text
