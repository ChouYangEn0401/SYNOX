# -*- coding: utf-8 -*-
"""runtime（docs/adr/0001、docs/runtime-api.md）：排程迴圈、心跳、常駐助理、soul.md、pack 狀態回報、網頁 API。

全部用假時鐘、同步執行（spawn）、假 AI（FakeAdapter）、假通道（FakeChannel）；不連網、不開埠、不叫 Telegram／claude。
不靠內建的 money／notes／remind pack（pack_dirs 只放 tests/fixtures 的假 pack 或空的）。
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta

import pytest

from synox import runtime
from synox.config import SynoxConfig
from synox.llm.fake import FakeAdapter
from synox.runtime import settings as rs
from synox.runtime.heartbeat import TASK_ID as HB
from synox.runtime.loop import NOTIFY_AFTER, RuntimeLoop
from synox.runtime.soul import DEFAULT_SOUL, NOTES_HEADING, SoulError, SoulStore

from conftest import OTHER_ID
from test_web import Client, ui_of

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
T0 = datetime(2026, 11, 12, 14, 0, 0)
FAKE_KEY = "sk-" + "abcdefghijklmnopqrstuvwxyz0123"     # 假的、拼起來的（像密鑰的樣式，測遮罩用）


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


@pytest.fixture
def rt_bot(make_bot):
    """回 (bot, runtime, clock)。adapter 可給；沒有內建 pack。"""
    def factory(script=None, *, adapter=None, raw=None, llm=None, pack_dirs=()):
        bot = make_bot(script, adapter=adapter, raw=raw, llm=llm, pack_dirs=pack_dirs)
        clock = Clock()
        rt = runtime.of(bot.app)
        rt.use_fakes(clock=clock, now=clock.now, spawn=sync)
        rt.loop.started = True                       # 當作 App.run 了（next_run_at 才有值）
        return bot, rt, clock
    return factory


# ── 設定 ─────────────────────────────────────────────────────────────

def test_runtime_settings_defaults_and_validation(tmp_path):
    cfg = SynoxConfig.from_dict({"owner_id": 1}, require_token=False, root=str(tmp_path))
    assert cfg.runtime["heartbeat"]["enabled"] is True and cfg.runtime["heartbeat"]["interval_min"] == 45
    assert cfg.runtime["mother"]["soul_append"] is True
    for bad in ({"heartbeat": {"interval_min": 5}}, {"heartbeat": {"interval_min": 45.5}},
                {"heartbeat": {"interval_min": "45"}}, {"heartbeat": {"enabled": "yes"}},
                {"heartbeat": {"quiet_hours": "25:00-08:00"}}, {"mother": {"memory_turns": -1}}, []):
        with pytest.raises(Exception) as e:
            SynoxConfig.from_dict({"owner_id": 1, "runtime": bad}, require_token=False, root=str(tmp_path))
        assert "runtime" in str(e.value)
    ok = SynoxConfig.from_dict({"owner_id": 1, "runtime": {"heartbeat": {"interval_min": 15, "quiet_hours": ""}}},
                               require_token=False, root=str(tmp_path))
    assert ok.runtime["heartbeat"]["interval_min"] == 15 and ok.runtime["heartbeat"]["daily_max_notify"] == 4


def test_quiet_hours_cross_midnight():
    q = rs.parse_quiet("23:00-08:00")
    assert rs.in_quiet(q, 23 * 60) and rs.in_quiet(q, 3 * 60) and not rs.in_quiet(q, 8 * 60)
    assert not rs.in_quiet(rs.parse_quiet("09:00-09:00"), 9 * 60)
    assert rs.parse_quiet("") is None


def test_wizard_writes_runtime_defaults():
    from synox.wizard import logic
    cfg = logic.build_config("1:x", 1, {"kind": "none"})
    assert cfg["runtime"]["heartbeat"]["interval_min"] == 45
    kept = logic.build_config("1:x", 1, {"kind": "none"}, existing={"runtime": {"heartbeat": {"interval_min": 60}}})
    assert kept["runtime"]["heartbeat"]["interval_min"] == 60


# ── 迴圈：逾時、退避、通知、不疊 ─────────────────────────────────────────

class FakeApp:
    def __init__(self):
        self.sent = []
        self.extras = {}

    def notify_owner(self, text):
        self.sent.append(text)


def test_loop_runs_due_task_and_records_state(tmp_path):
    clock = Clock()
    loop = RuntimeLoop(FakeApp(), clock=clock, spawn=sync, state_path=str(tmp_path / "state.json"))
    calls = []
    loop.register("system.demo", "示範", fn=lambda ctx: (calls.append(1), ctx.log("hello"), "好了")[-1], interval=60)
    assert loop.tick() == []                                  # 還沒到
    clock.advance(seconds=61)
    assert loop.tick() == ["system.demo"]
    t = loop.task("system.demo")
    assert t.state == "ok" and t.last_message == "好了" and calls == [1]
    assert any("hello" in line for line in t.log)
    saved = json.load(open(tmp_path / "state.json", encoding="utf-8"))
    assert saved["tasks"]["system.demo"]["state"] == "ok"
    assert "好了" not in json.dumps(saved, ensure_ascii=False)   # 訊息不落地


def test_loop_failure_backoff_and_single_notify(tmp_path):
    app = FakeApp()
    clock = Clock()
    loop = RuntimeLoop(app, clock=clock, spawn=sync, state_path=str(tmp_path / "s.json"))
    state = {"fail": True}

    def flaky(ctx):
        if state["fail"]:
            raise RuntimeError("壞了")
        return "ok"

    loop.register("system.flaky", "會壞的", fn=flaky, interval=45 * 60, first_delay=0)
    loop.tick()
    t = loop.task("system.flaky")
    assert t.state == "failed" and t.failures == 1 and "RuntimeError" in t.last_message
    assert t.next_due - clock() == 60                         # 第一次失敗：1 分鐘後重試（不用等 45 分鐘）
    clock.advance(seconds=60)
    loop.tick()
    assert t.failures == 2 and t.next_due - clock() == 120
    for _ in range(NOTIFY_AFTER - 2):
        clock.dt = datetime.fromtimestamp(t.next_due)
        loop.tick()
    assert t.failures == NOTIFY_AFTER and len(app.sent) == 1 and "連續失敗" in app.sent[0]
    clock.dt = datetime.fromtimestamp(t.next_due)
    loop.tick()
    assert len(app.sent) == 1                                 # 同一串失敗只通知一次
    state["fail"] = False
    clock.dt = datetime.fromtimestamp(t.next_due)
    loop.tick()
    assert t.state == "ok" and t.failures == 0 and "恢復" in app.sent[-1]


def test_loop_timeout_marks_failed_and_ignores_late_result(tmp_path):
    clock = Clock()
    pending = []
    loop = RuntimeLoop(FakeApp(), clock=clock, spawn=lambda fn, name: pending.append(fn),
                       state_path=str(tmp_path / "s.json"))
    loop.register("system.slow", "慢的", fn=lambda ctx: "晚到的結果", interval=60, timeout=30, first_delay=0)
    assert loop.tick() == ["system.slow"]
    t = loop.task("system.slow")
    assert t.state == "running"
    assert loop.run_now("system.slow") is False               # 還在跑：不疊
    clock.advance(seconds=31)
    loop.tick()
    assert t.state == "failed" and "逾時" in t.last_message
    pending[0]()                                              # 晚回來
    assert t.state == "failed" and t.last_message != "晚到的結果"


def test_loop_exception_does_not_break_other_tasks(tmp_path):
    clock = Clock()
    loop = RuntimeLoop(FakeApp(), clock=clock, spawn=sync, state_path=str(tmp_path / "s.json"))
    loop.register("system.bad", "壞的", fn=lambda ctx: 1 / 0, interval=30, first_delay=0)
    loop.register("system.good", "好的", fn=lambda ctx: "ok", interval=30, first_delay=0)
    loop.tick()
    assert loop.task("system.bad").state == "failed" and loop.task("system.good").state == "ok"


def test_loop_restores_saved_state(tmp_path):
    path = str(tmp_path / "s.json")
    clock = Clock()
    loop = RuntimeLoop(FakeApp(), clock=clock, spawn=sync, state_path=path)
    loop.register("system.x", "X", fn=lambda ctx: "ok", interval=60, first_delay=0)
    loop.tick()
    again = RuntimeLoop(FakeApp(), clock=clock, spawn=sync, state_path=path)
    t = again.register("system.x", "X", fn=lambda ctx: "ok", interval=60)
    assert t.state == "ok" and t.last_run_at == clock() and t.last_message is None


def test_report_rejects_bad_state_and_masks_tokens(tmp_path):
    loop = RuntimeLoop(FakeApp(), clock=Clock(), spawn=sync, state_path=str(tmp_path / "s.json"))
    assert loop.report("pack.x", "exploded", "?") is None
    t = loop.report("pack.x", "failed", "key " + FAKE_KEY + " 壞了")
    assert t.state == "failed" and "sk-abcdef" not in t.last_message and "***" in t.last_message
    assert loop.peer_states()["pack.x"] == {"state": "failed", "at": t.view()["last_run_at"]}


# ── 排程整合 ──────────────────────────────────────────────────────────

def test_schedule_is_a_runtime_task(rt_bot):
    bot, rt, clock = rt_bot()
    t = rt.loop.task("system.schedule")
    assert t is not None and t.schedule == "每 30 秒" and t.next_due is not None
    runner = bot.app.extras["synox_schedule_runner"]
    runner._clock = clock.now
    runner.store.add("remind", "14:00", bot.app.owner_id, text="喝水")
    rt.loop.tick()
    assert t.state == "ok" and t.last_message == "做了 1 項"
    assert any("喝水" in m for m in bot.texts())


# ── 心跳 ─────────────────────────────────────────────────────────────

def test_heartbeat_default_interval_and_next_run(rt_bot):
    bot, rt, clock = rt_bot()
    view = rt.heartbeat.view()
    assert view["enabled"] is True and view["interval_min"] == 45
    assert view["next_run_at"] == datetime.fromtimestamp(clock() + 45 * 60).astimezone().isoformat(timespec="seconds")
    assert view["last_run_at"] is None and view["last_result"] is None


def test_heartbeat_calls_mother_and_notifies_once(rt_bot):
    adapter = FakeAdapter(["NOTIFY: 天氣工具壞了，要看一下", "NOTIFY: 天氣工具壞了，要看一下"])
    bot, rt, clock = rt_bot(adapter=adapter)
    runtime.report(bot.app, "weather", "failed", "API 回 503", title="🌤 天氣")
    clock.advance(minutes=45)
    assert HB in rt.loop.tick()
    assert any("🫀 常駐助理：天氣工具壞了" in m for m in bot.texts())
    assert rt.heartbeat.last_result.startswith("通知了你")
    sys_prompt, facts = adapter.calls[0][0][0].content, adapter.calls[0][0][-1].content
    assert "常駐助理" in sys_prompt and "API 回 503" in facts and "SYNOX-TOOL" in facts   # 快照包在分隔符裡
    n = len(bot.texts())
    clock.advance(minutes=45)
    rt.loop.tick()
    assert len(adapter.calls) == 1 and "失敗狀態沒有變化" in rt.heartbeat.last_result   # 失敗沒變：不再叫 AI
    runtime.report(bot.app, "weather", "failed", "API 金鑰過期", title="🌤 天氣")       # 原因變了：再叫一次
    clock.advance(minutes=45)
    rt.loop.tick()
    assert len(adapter.calls) == 2
    assert len(bot.texts()) == n and "上次說過" in rt.heartbeat.last_result      # 同一句不再送
    assert rt.mother.state == "idle" and rt.mother.last_active_at is not None


def test_heartbeat_skips_llm_when_nothing_changed(rt_bot):
    adapter = FakeAdapter(["QUIET", "QUIET"])
    bot, rt, clock = rt_bot(adapter=adapter)
    clock.advance(minutes=45)
    rt.loop.tick()
    assert len(adapter.calls) == 1 and "沒有要通知" in rt.heartbeat.last_result
    clock.advance(minutes=45)
    rt.loop.tick()
    assert len(adapter.calls) == 1 and "沒有叫 AI" in rt.heartbeat.last_result
    assert rt.loop.run_now(HB) is True                       # 手動那一次一定叫
    assert len(adapter.calls) == 2


def test_heartbeat_quiet_hours_hold_notification_but_manual_does_not(rt_bot):
    adapter = FakeAdapter(["NOTIFY: 半夜的事", "NOTIFY: 半夜的事 2"])
    bot, rt, clock = rt_bot(adapter=adapter)
    clock.dt = datetime(2026, 11, 12, 23, 30)
    rt.heartbeat.update(interval_min=15)
    clock.advance(minutes=16)
    rt.loop.tick()
    assert "安靜時段" in rt.heartbeat.last_result and not any("常駐助理" in m for m in bot.texts())
    rt.loop.run_now(HB)
    assert any("半夜的事 2" in m for m in bot.texts())


def test_heartbeat_daily_caps(rt_bot):
    adapter = FakeAdapter([f"NOTIFY: 事情 {i}" for i in range(10)])
    bot, rt, clock = rt_bot(adapter=adapter, raw={"runtime": {"heartbeat": {"daily_max_notify": 1,
                                                                             "daily_max_calls": 2}}})
    for _ in range(3):
        rt.loop.run_now(HB)
    assert sum("常駐助理" in m for m in bot.texts()) == 1
    assert len(adapter.calls) == 2 and "次數用完" in rt.heartbeat.last_result


def test_heartbeat_without_ai_is_rules_only(rt_bot):
    bot, rt, clock = rt_bot(llm={"kind": "none"})
    assert rt.mother.state == "off"
    rt.loop.run_now(HB)
    assert "沒有可用的 AI" in rt.heartbeat.last_result and rt.loop.task(HB).state == "ok"


def test_heartbeat_disabled_has_no_next_run_and_llm_error_backs_off(rt_bot):
    def boom(messages, tools):
        raise RuntimeError("AI 掛了")
    bot, rt, clock = rt_bot(adapter=FakeAdapter([boom]))
    rt.loop.run_now(HB)
    t = rt.loop.task(HB)
    assert t.state == "failed" and t.next_due - clock() == 60 and rt.mother.state == "idle"
    view = rt.heartbeat.update(enabled=False)
    assert view["enabled"] is False and view["next_run_at"] is None and t.schedule == "關閉"


def test_heartbeat_reads_owner_chat_and_reminders(rt_bot):
    adapter = FakeAdapter(["好喔", "QUIET"])
    bot, rt, clock = rt_bot(adapter=adapter)
    bot.talk(bot.app.owner_id, "明天記得幫我看報告")
    runner = bot.app.extras["synox_schedule_runner"]
    runner.store.add("remind", "18:00", bot.app.owner_id, text="去接小孩")
    rt.loop.run_now(HB)
    facts = adapter.calls[-1][0][-1].content
    assert "明天記得幫我看報告" in facts and "18:00 去接小孩" in facts


def test_mother_memory_persists_and_reset(rt_bot):
    adapter = FakeAdapter(["QUIET", "QUIET"])
    bot, rt, clock = rt_bot(adapter=adapter)
    rt.loop.run_now(HB)
    assert len(rt.mother.memory()) == 1
    rt.mother._memory = None                                 # 模擬重開：從保管箱讀回來
    assert len(rt.mother.memory()) == 1
    rt.loop.run_now(HB)
    msgs = adapter.calls[-1][0]
    assert len(msgs) == 4                                    # system + 上一次（user, assistant）+ 這一次
    assert rt.mother.reset_memory() == 2 and rt.mother.memory() == []
    rt.mother._memory = None
    assert rt.mother.memory() == []
    assert not any(f.startswith("runtime_mother") and f.endswith(".json") for f in os.listdir(bot.app.config.data_dir))


# ── soul.md ──────────────────────────────────────────────────────────

def test_soul_default_write_reset_and_secret_guard(tmp_path):
    from synox.vault import Vault
    soul = SoulStore(Vault(b"k" * 32, str(tmp_path)), clock=Clock())
    assert soul.text() == DEFAULT_SOUL and soul.updated_at() is None
    saved = soul.write("# soul.md\r\n## 偏好\r\n- 早上不要吵")
    assert saved["text"] == "# soul.md\n## 偏好\n- 早上不要吵\n" and soul.updated_at() is not None
    with pytest.raises(SoulError):
        soul.write("token 123456789:AAHabcdefghijklmnopqrstuvwxyz01234")
    with pytest.raises(SoulError):
        soul.write("x" * 6001)
    assert soul.write("   ")["text"] == DEFAULT_SOUL
    assert [a["by"] for a in soul.audit()] == ["owner", "owner"]
    assert not any(n.endswith(".md") for n in os.listdir(tmp_path))      # 不落明文


def test_soul_append_rules(tmp_path):
    from synox.vault import Vault
    soul = SoulStore(Vault(b"k" * 32, str(tmp_path)), clock=Clock())
    soul.write("# soul.md\n## 偏好\n- 喜歡簡短\n" + NOTES_HEADING + "\n- 舊的筆記\n## 其他\n- 我寫的\n")
    added = soul.append_notes(["週末不想被提醒工作", "- 喜歡簡短", FAKE_KEY,
                               "x" * 201, "第四行不會加", "第五行"])
    assert added == ["- 週末不想被提醒工作"]
    text = soul.text()
    notes = text.split(NOTES_HEADING)[1].split("## 其他")[0]
    assert "- 舊的筆記\n- 週末不想被提醒工作" in notes and "- 我寫的" in text.split("## 其他")[1]
    assert soul.append_notes(["週末不想被提醒工作"]) == []                 # 重複不加
    assert soul.audit()[-1]["by"] == "mother"


def test_soul_unavailable_without_vault():
    soul = SoulStore(None)
    with pytest.raises(SoulError):
        soul.text()


def test_heartbeat_soul_append_respects_setting(rt_bot):
    bot, rt, clock = rt_bot(adapter=FakeAdapter(["SOUL+: 他晚上不看工作訊息\nQUIET"]))
    rt.loop.run_now(HB)
    assert "他晚上不看工作訊息" in rt.soul.text() and "記進 soul.md 1 行" in rt.heartbeat.last_result
    bot2, rt2, _ = rt_bot(adapter=FakeAdapter(["SOUL+: 不該加\nQUIET"]),
                          raw={"runtime": {"mother": {"soul_append": False}}})
    rt2.loop.run_now(HB)
    assert "不該加" not in rt2.soul.text()


def test_soul_goes_into_mother_prompt(rt_bot):
    adapter = FakeAdapter(["QUIET"])
    bot, rt, clock = rt_bot(adapter=adapter)
    rt.soul.write("# soul.md\n## 語氣\n- 用台語腔\n")
    rt.loop.run_now(HB)
    assert "用台語腔" in adapter.calls[0][0][0].content


# ── pack 回報狀態 ─────────────────────────────────────────────────────

def test_python_pack_reports_and_reads_peers(rt_bot, tmp_path):
    packs = tmp_path / "packs"
    shutil.copytree(os.path.join(FIXTURES, "status_pack"), packs / "statusdemo")
    bot, rt, clock = rt_bot(pack_dirs=(str(packs),))
    owner = bot.app.owner_id
    bot.say(owner, "/statusdemo_report failed 連不上")
    assert "reported=True" in bot.texts()[-1]
    task = rt.loop.task("pack.statusdemo")
    assert task.state == "failed" and task.last_message == "連不上" and task.name == "🧪 狀態回報示範"
    bot.say(owner, "/statusdemo_report exploded")
    assert "reported=False" in bot.texts()[-1]
    bot.say(owner, "/statusdemo_peers")
    assert "pack.statusdemo:failed" in bot.texts()[-1] and "system.heartbeat:" in bot.texts()[-1]
    assert "連不上" not in bot.texts()[-1]                       # 別人只看得到狀態，看不到訊息


STATUS_TOOL = r'''
import json
from synox_sdk import tool, serve, report_status, peer_status

@tool("READ")
def sync(fail: bool = False):
    """同步一次。"""
    peers = peer_status()
    if fail:
        report_status("failed", "同步失敗：伺服器 503")
        return "失敗了"
    report_status("ok", "同步了 3 筆")
    return "peers=" + ",".join(sorted(peers))

if __name__ == "__main__":
    serve()
'''


def _cli_status_pack(folder):
    os.makedirs(folder, exist_ok=True)
    shutil.copy(os.path.join(HERE, "..", "sdk", "synox_sdk.py"), os.path.join(folder, "synox_sdk.py"))
    with open(os.path.join(folder, "tool.py"), "w", encoding="utf-8") as f:
        f.write(STATUS_TOOL)
    manifest = {"name": "syncer", "title": "🔄 同步", "summary": "測試用", "version": "0.1.0", "kind": "cli",
                "access": "owner", "capabilities": ["subprocess"], "skill": "SKILL.md",
                "cli": {"python": sys.executable, "argv": ["{python}", "{pack_dir}/tool.py"], "json_flag": "--json",
                        "timeout": 60,
                        "commands": [{"name": "sync", "default": True, "effect": "READ", "summary": "同步",
                                      "argv": ["sync", "--fail={fail}"],
                                      "fields": [{"name": "fail", "ask": "要不要失敗", "kind": "bool",
                                                  "default": "false"}]}]}}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: syncer\ndescription: 測試\n---\n")


def test_cli_pack_status_via_sdk_envelope_and_peer_env(rt_bot, tmp_path):
    _cli_status_pack(str(tmp_path / "packs" / "syncer"))
    bot, rt, clock = rt_bot(pack_dirs=(str(tmp_path / "packs"),))
    owner = bot.app.owner_id
    bot.say(owner, "/syncer")
    bot.app.tasks.wait(30)
    task = rt.loop.task("pack.syncer")
    assert task is not None and task.state == "ok" and task.last_message == "同步了 3 筆", bot.texts()
    assert any("system.heartbeat" in m and "system.schedule" in m for m in bot.texts())   # SYNOX_PEER_STATUS 收到了
    bot.say(owner, "/syncer fail=true")
    bot.app.tasks.wait(30)
    assert task.state == "failed" and "503" in task.last_message


def test_sdk_report_status_envelope_and_peer_status(monkeypatch):
    import io
    from synox.sdk import author
    monkeypatch.setattr(author, "_REGISTRY", list(author._REGISTRY))      # 不污染別的測試的 @tool 清單
    monkeypatch.setenv("SYNOX_PEER_STATUS", json.dumps({"pack.a": {"state": "ok", "at": None}, "bad": 3}))
    assert author.peer_status() == {"pack.a": {"state": "ok", "at": None}}
    assert author.peer_status("pack.a")["state"] == "ok" and author.peer_status("nope") == {}
    monkeypatch.setenv("SYNOX_PEER_STATUS", "{oops")
    assert author.peer_status() == {}

    def good():
        """回報 running。"""
        author.report_status("running", "x" * 300)
        return "hi"

    def plain():
        """不回報。"""
        return "hi"

    def bad():
        """回報不合法的狀態。"""
        author.report_status("exploded")

    tools = [author.tool("READ")(f) for f in (good, plain, bad)]
    out = io.StringIO()
    author.run_cli(["good", "--json"], out=out, tools=tools)
    env = json.loads(out.getvalue().splitlines()[-1])
    assert env["status"]["state"] == "running" and len(env["status"]["message"]) == 200
    out = io.StringIO()
    author.run_cli(["plain", "--json"], out=out, tools=tools)
    assert "status" not in json.loads(out.getvalue().splitlines()[-1])       # 沒回報＝跟以前一樣
    out = io.StringIO()
    author.run_cli(["bad", "--json"], out=out, tools=tools)
    assert json.loads(out.getvalue().splitlines()[-1])["ok"] is False


def test_ingest_envelope_ignores_garbage(rt_bot):
    bot, rt, clock = rt_bot()
    for env in (None, {}, {"status": "ok"}, {"status": {"state": 1}}, {"status": {"state": "ok", "message": 3}}):
        assert runtime.ingest_envelope(bot.app, "x", env) is False
    assert runtime.ingest_envelope(bot.app, "x", {"status": {"state": "idle"}}) is True


# ── 網頁 API（docs/runtime-api.md）────────────────────────────────────

@pytest.fixture
def api(rt_bot):
    def factory(**kw):
        bot, rt, clock = rt_bot(**kw)
        client = Client(ui_of(bot))
        client.login(bot.app.owner_id)
        return bot, rt, clock, client
    return factory


def put(client, path, data):
    status, _h, body = client.raw("PUT", path, json.dumps(data).encode("utf-8"))
    return status, json.loads(body)


def test_api_status_shape(api):
    bot, rt, clock, client = api(adapter=FakeAdapter(["QUIET"]))
    runtime.report(bot.app, "weather", "failed", "API 回 503", title="🌤 天氣")
    status, data = client.get("/api/runtime/status")
    assert status == 200
    assert set(data) == {"heartbeat", "mother", "tasks", "activator", "keep_awake"}       # activator：連動（docs/adr/0004）
    assert {"enabled", "interval_min", "last_run_at", "next_run_at", "last_result"} <= set(data["heartbeat"])
    assert set(data["mother"]) == {"state", "ai", "last_active_at", "soul_updated_at"}
    assert data["mother"]["ai"] is True
    assert data["mother"]["state"] == "idle"
    ids = [t["id"] for t in data["tasks"]]
    assert ids == ["system.health", "system.heartbeat", "system.remote", "system.schedule", "system.soul_tidy",
                   "system.tool_apps", "pack.weather"]   # system.tool_apps／system.remote：工具服務、手機入口（只有開著時才排）
    for t in data["tasks"]:
        assert set(t) == {"id", "name", "owner", "schedule", "state", "last_run_at", "last_message"}
        assert t["state"] in ("ok", "running", "failed", "idle")
    weather = data["tasks"][-1]
    assert weather["owner"] == "weather" and weather["state"] == "failed" and weather["schedule"] == "自己回報"
    datetime.fromisoformat(weather["last_run_at"])


def test_api_heartbeat_update_persists_to_config(api):
    bot, rt, clock, client = api()
    status, data = client.post("/api/runtime/heartbeat", {"interval_min": 60})
    assert status == 200 and data["interval_min"] == 60 and data["enabled"] is True
    cfg = json.load(open(ui_of(bot).config_path, encoding="utf-8"))
    assert cfg["runtime"]["heartbeat"] == {"enabled": True, "interval_min": 60}
    for bad in ({"interval_min": 5}, {"interval_min": 45.5}, {"interval_min": "45"}, {"enabled": "no"}):
        status, data = client.post("/api/runtime/heartbeat", bad)
        assert status == 400 and data["error"]
    status, data = client.post("/api/runtime/heartbeat", {"enabled": False})
    assert data["enabled"] is False and data["next_run_at"] is None
    cfg = json.load(open(ui_of(bot).config_path, encoding="utf-8"))
    assert cfg["runtime"]["heartbeat"] == {"enabled": False, "interval_min": 60}


def test_api_run_now_and_busy(api):
    bot, rt, clock, client = api(adapter=FakeAdapter(["NOTIFY: 手動巡到的事"]))
    status, data = client.post("/api/runtime/heartbeat/run-now")
    assert status == 200 and data["ok"] is True and data["message"]
    assert "手動巡到的事" in client.get("/api/runtime/status")[1]["heartbeat"]["last_result"]
    rt.loop._spawn = lambda fn, name: None                     # 開始了但還沒做完
    client.post("/api/runtime/heartbeat/run-now")
    status, data = client.post("/api/runtime/heartbeat/run-now")
    assert status == 200 and data["ok"] is False


def test_api_reset_memory_soul_and_log(api):
    bot, rt, clock, client = api(adapter=FakeAdapter(["QUIET"]))
    client.post("/api/runtime/heartbeat/run-now")
    assert len(rt.mother.memory()) == 1
    assert client.post("/api/runtime/mother/reset-memory") == (200, {"ok": True})
    assert rt.mother.memory() == []
    status, data = client.get("/api/runtime/soul")
    assert status == 200 and data == {"text": DEFAULT_SOUL, "updated_at": None}
    status, data = put(client, "/api/runtime/soul", {"text": "# soul.md\n## 偏好\n- 少吵\n"})
    assert status == 200 and data["ok"] is True and data["updated_at"]
    assert client.get("/api/runtime/soul")[1]["text"] == "# soul.md\n## 偏好\n- 少吵\n"
    assert put(client, "/api/runtime/soul", {"text": 3})[0] == 400
    assert put(client, "/api/runtime/soul", {"text": FAKE_KEY})[0] == 400
    assert put(client, "/api/runtime/soul", {"text": ""})[1]["text"] == DEFAULT_SOUL
    status, data = client.get("/api/runtime/tasks/system.heartbeat/log")
    assert status == 200 and any("開始" in line for line in data["lines"])
    assert client.get("/api/runtime/tasks/nope/log")[0] == 404
    assert client.get("/api/runtime/tasks/..%2F/log")[0] == 404


def test_api_owner_only_and_csrf(api):
    bot, rt, clock, client = api()
    status, _h, _b = client.raw("POST", "/api/runtime/mother/reset-memory", b"{}", headers={"X-SYNOX-CSRF": "bad"})
    assert status == 403
    status, _h, _b = client.raw("PUT", "/api/runtime/soul", b'{"text": "x"}', headers={"X-SYNOX-CSRF": ""})
    assert status == 403
    anon = Client(ui_of(bot))
    assert anon.get("/api/runtime/status")[0] == 401
    other = Client(ui_of(bot))
    bot.app.users.get_or_create(OTHER_ID)
    other.login(OTHER_ID)
    for path in ("/api/runtime/status", "/api/runtime/soul", "/api/runtime/tasks/system.heartbeat/log"):
        assert other.get(path)[0] == 403
    assert other.post("/api/runtime/heartbeat/run-now")[0] == 403
    assert put(other, "/api/runtime/soul", {"text": "x"})[0] == 403


def test_api_server_mode_non_owner_is_forbidden(api):
    bot, rt, clock, client = api(raw={"mode": "server"})
    assert client.get("/api/runtime/status")[0] == 200
    c = Client(ui_of(bot))
    c.login(OTHER_ID)
    assert c.get("/api/runtime/status")[0] == 403


# ── doctor ───────────────────────────────────────────────────────────

def test_doctor_shows_heartbeat(tmp_path):
    from synox import doctor
    cfg = {"owner_id": 1, "data_dir": str(tmp_path / "data"), "vault": {"mode": "file"}, "llm": {"kind": "none"},
           "runtime": {"heartbeat": {"interval_min": 30}}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    state = tmp_path / "data" / "runtime"
    state.mkdir(parents=True)
    (state / "state.json").write_text(json.dumps({"tasks": {"system.heartbeat": {"state": "ok", "last_run_at": T0.timestamp(),
                                                                                  "failures": 0}},
                                                  "heartbeat": {"last_result": "巡過了，沒有要通知你的事。"}}),
                                      encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "心跳：開，每 30 分鐘" in text and "巡過了，沒有要通知你的事。" in text


def test_heartbeat_default_is_45_everywhere():
    """決定 Q10（docs/adr/0001 §3）：預設 45 分鐘（擁有者：搭得上約 1 小時的 prompt 快取），最短 15 分鐘。各處要一致。"""
    import re
    root = os.path.dirname(HERE)
    assert rs.DEFAULT_RUNTIME["heartbeat"]["interval_min"] == 45
    assert rs.MIN_INTERVAL_MIN == 15 and rs.MAX_INTERVAL_MIN == 1440
    with open(os.path.join(root, "config.example.json"), encoding="utf-8") as f:
        assert json.load(f)["runtime"]["heartbeat"]["interval_min"] == 45
    with open(os.path.join(root, "src", "synox", "web", "static", "control.js"), encoding="utf-8") as f:
        js = f.read()
    assert re.search(r"INTERVAL_MIN = 15, INTERVAL_MAX = 1440, INTERVAL_DEFAULT = 45;", js)
