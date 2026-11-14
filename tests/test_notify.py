"""通知中心（synox/notify、docs/notifications.md）：一則通知同時送網頁、Telegram、Discord；一條壞掉不擋別條；
同一個 key 不重送；每一類可以關；鬧鐘：帶按鈕、5 分鐘後再提醒、晚了照叫、錯過了會說；設鬧鐘時說會在哪裡響；網頁 API。
全部用假的通道，不連網。"""

import os
from datetime import datetime, timedelta

import pytest

from isdtelekit.testing import FakeChannel

from synox import notify
from synox.notify import alarms

from conftest import OTHER_ID
from test_web import Client, ui_of


class FakeBots:
    """DiscordBots 的替身：can_reach／pick。"""

    def __init__(self, reach=True, boom=False):
        self.channels = {"synox": object()}
        self.reach = reach
        self.ch = FakeChannel()
        self.boom = boom

    def can_reach(self, uid):
        return self.reach

    def pick(self, uid, message_id=None):
        if self.boom:
            raise RuntimeError("discord down")
        return self.ch


def with_channels(bot, monkeypatch, *, tg=True, dc=True, tg_boom=False, dc_boom=False):
    hub = notify.of(bot.app)
    tg_ch = FakeChannel()
    if tg_boom:
        def boom(*a, **kw):
            raise ConnectionError("telegram down")
        tg_ch.send_message = boom
    monkeypatch.setattr(hub, "_telegram_api", lambda: tg_ch if tg else None)
    bots = FakeBots(boom=dc_boom)
    if dc:
        bot.app.extras["discord_bots"] = bots
    return hub, tg_ch, bots.ch


def web_items(bot, uid):
    return [it for it in notify.of(bot.app).store.since(uid)["items"] if not it["data"].get("hidden")]


# ── 送到每一個地方 ───────────────────────────────────────────────────

def test_notify_owner_fans_out_to_web_telegram_and_discord(make_bot, owner, monkeypatch):
    bot = make_bot()
    hub, tg, dc = with_channels(bot, monkeypatch)
    out = bot.app.notify_owner("🆕 SYNOX 有新版", kind="update")
    assert out["web"] and out["telegram"] and out["discord"] and not out["chat"]
    assert tg.last(owner) == "🆕 SYNOX 有新版" and dc.last(owner) == "🆕 SYNOX 有新版"
    assert [it["text"] for it in web_items(bot, owner)][-1] == "🆕 SYNOX 有新版"
    assert not bot.api.sent                                         # 有聊天通道就不走舊的 app.home


def test_one_channel_failing_does_not_block_others(make_bot, owner, monkeypatch):
    from synox.notify import hub as hub_mod
    logged = []
    monkeypatch.setattr(hub_mod.logging, "warning", lambda msg, *a: logged.append(msg % a))
    bot = make_bot()
    hub, tg, dc = with_channels(bot, monkeypatch, tg_boom=True)
    out = hub.notify_owner("提醒你一件事 secret-ish", kind="general")
    assert out["web"] and out["discord"] and out["telegram"] is False
    assert dc.last(owner) == "提醒你一件事 secret-ish"
    text = "\n".join(logged)
    assert "ConnectionError" in text and "secret-ish" not in text          # log 不記內容
    hub, tg, dc = with_channels(bot, monkeypatch, dc_boom=True)
    out = hub.notify_owner("第二則", kind="general")
    assert out["telegram"] and out["web"] and not out["discord"]


def test_without_chat_channels_falls_back_to_home(make_bot, owner):
    bot = make_bot()
    out = bot.app.notify_owner("只有舊的 home")
    assert out["chat"] and bot.last(owner) == "只有舊的 home" and out["web"]


def test_dedupe_by_key(make_bot, owner, monkeypatch):
    bot = make_bot()
    hub, tg, _dc = with_channels(bot, monkeypatch, dc=False)
    hub.notify_owner("一樣的事", key="same")
    out = hub.notify_owner("一樣的事", key="same")
    assert out.get("skipped") == "dup" and tg.texts(owner) == ["一樣的事"] and len(web_items(bot, owner)) == 1
    hub.notify_owner("一樣的事", key="other")
    assert len(tg.texts(owner)) == 2


def test_mute_per_kind_and_safety_web_cannot_be_muted(make_bot, owner, monkeypatch):
    bot = make_bot()
    hub, tg, dc = with_channels(bot, monkeypatch)
    hub.save_prefs(owner, {"update": ["telegram", "web"], "safety": ["web", "discord"]})
    out = hub.notify_owner("新版", kind="update")
    assert out["telegram"] is False and out["web"] is None and out["discord"]
    out = hub.notify_owner("pack 被改過", kind="safety")
    assert out["web"] and out["telegram"] and not out["discord"]
    view = {k["kind"]: k for k in hub.prefs_view(owner)["kinds"]}
    assert view["update"]["off"] == ["telegram", "web"] and view["safety"]["off"] == ["discord"]


def test_greeting_skips_web_by_default(make_bot, owner):
    bot = make_bot()
    out = notify.owner(bot.app, "👋 我在了", kind="greeting")
    assert out["web"] is None and out["chat"]


def test_web_list_is_encrypted_and_capped(make_bot, owner):
    bot = make_bot()
    hub = notify.of(bot.app)
    for i in range(105):
        hub.notify_owner(f"第 {i} 則吃藥提醒")
    items = hub.store.since(owner)["items"]
    assert len(items) == 100 and items[-1]["text"] == "第 104 則吃藥提醒"
    path = hub.store.path(owner)
    assert path.endswith(".enc") and os.path.exists(path)
    with open(path, "rb") as f:
        assert "吃藥".encode("utf-8") not in f.read()


# ── 鬧鐘 ─────────────────────────────────────────────────────────────

def _runner(bot):
    return bot.app.extras["synox_schedule_runner"]


def test_remind_add_says_when_and_where(make_bot, owner, monkeypatch):
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    text = bot.last(owner)
    assert "每天 08:00 提醒你：吃藥" in text and "會在網頁提醒你" in text and alarms.NOTE in text
    with_channels(bot, monkeypatch)
    bot.say(owner, "/remind_add 09:00 喝水")
    assert "會在網頁、Telegram、Discord 提醒你" in bot.last(owner)


def test_remind_add_today_in_the_past_is_refused(make_bot, owner):
    now = datetime.now()
    if now.hour == 0 and now.minute == 0:
        pytest.skip("剛好午夜")
    bot = make_bot()
    bot.say(owner, f"/remind_add 00:00 太早了 date={now.strftime('%Y-%m-%d')}")
    assert "已經過了" in bot.last(owner)


def test_alarm_fires_everywhere_with_buttons_and_snooze(make_bot, owner, monkeypatch):
    bot = make_bot()
    hub, tg, dc = with_channels(bot, monkeypatch)
    bot.say(owner, "/remind_add 08:00 吃藥")
    assert len(_runner(bot).tick(datetime(2026, 11, 9, 8, 0, 10))) == 1
    assert tg.last(owner) == "⏰ 提醒：吃藥" and dc.last(owner) == "⏰ 提醒：吃藥"
    assert any("ntf:s5:" in b for b in tg.buttons(owner))
    item = web_items(bot, owner)[-1]
    assert item["kind"] == "alarm" and [a["id"] for a in item["actions"]] == ["ok", "snooze"]
    hhmm = hub.snooze(owner, item["id"])
    from synox.schedule.commands import store_for
    snoozed = [it for it in store_for(bot.app).of(owner).items("remind") if it.get("date")]
    assert snoozed and snoozed[0]["time"] == hhmm and snoozed[0]["text"] == "吃藥"
    assert hub.store.get(owner, item["id"])["read"] and hub.snooze(owner, item["id"]) is None   # 只能按一次


def test_alarm_button_in_chat_snoozes(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/remind_add 08:00 吃藥")
    _runner(bot).tick(datetime(2026, 11, 9, 8, 0, 10))
    data = next(b for b in bot.api.buttons(owner) if b.startswith("ntf:s5:"))
    bot.press(owner, data)
    assert "再叫你一次" in (bot.answers()[-1] or "")
    from synox.schedule.commands import store_for
    assert len(store_for(bot.app).of(owner).items("remind")) == 2


def test_late_alarm_still_rings_and_old_one_is_missed(make_bot, owner):
    bot = make_bot()
    hub = notify.of(bot.app)
    from synox.schedule.commands import store_for
    store = store_for(bot.app).of(owner)
    store.add("remind", "08:00", owner, text="吃藥")
    store.add("remind", "06:00", owner, text="運動")
    items = store.items("remind")
    for it in items:                                              # 假裝很久以前設的
        it["created"] = 0
    store._save(items)
    fired = _runner(bot).tick(datetime(2026, 11, 9, 8, 20))
    assert [it["text"] for it in fired] == ["吃藥"]
    texts = [it["text"] for it in web_items(bot, owner)]
    assert any("⏰ 提醒：吃藥" in t and "晚了 20 分鐘" in t for t in texts)
    assert any("你錯過了 1 個鬧鐘：今天 06:00 運動" in t for t in texts)
    assert _runner(bot).tick(datetime(2026, 11, 9, 8, 21)) == []   # 不會再叫、不會再說錯過
    assert len(web_items(bot, owner)) == 2
    assert hub is not None


def test_alarm_set_after_its_time_waits_for_tomorrow(make_bot, owner):
    bot = make_bot()
    from synox.schedule.commands import store_for
    store = store_for(bot.app).of(owner)
    store.add("remind", "08:00", owner, text="吃藥")
    items = store.items("remind")
    items[0]["created"] = datetime(2026, 11, 9, 8, 10).timestamp()
    store._save(items)
    assert _runner(bot).tick(datetime(2026, 11, 9, 8, 20)) == [] and web_items(bot, owner) == []
    assert len(_runner(bot).tick(datetime(2026, 11, 10, 8, 0))) == 1


def test_upcoming_and_friendly():
    now = datetime(2026, 11, 14, 9, 0)
    assert alarms.friendly(datetime(2026, 11, 14, 10, 0), now) == "今天 10:00"
    assert alarms.friendly(datetime(2026, 11, 15, 8, 0), now) == "明天 08:00"
    assert alarms.friendly(datetime(2026, 11, 20, 8, 0), now) == "11 月 20 日（五）08:00"
    assert alarms.next_at({"time": "08:00"}, now) == datetime(2026, 11, 15, 8, 0)
    assert alarms.next_at({"time": "08:00", "date": "2026-11-14"}, now) is None


def test_warnings_web_only_and_sleep(make_bot, owner):
    bot = make_bot()
    w = alarms.warnings(bot.app, owner, True, platform="linux")
    assert [x["id"] for x in w] == ["web_only"] and w[0]["fix"]["href"] == "#settings:channels"
    from synox import runtime
    rt = runtime.of(bot.app)
    if rt is not None and rt.keep_awake is not None:
        w = alarms.warnings(bot.app, owner, True, platform="win32", autostart=lambda: False)
        assert {x["id"] for x in w} >= {"web_only", "sleep", "autostart"}
        assert next(x for x in w if x["id"] == "sleep")["fix"]["action"] == "keep_awake"
    hub = notify.of(bot.app)
    hub.save_prefs(owner, {"alarm": ["web"]})
    assert alarms.warnings(bot.app, owner, True, platform="linux")[0]["id"] == "nowhere"


def test_ai_alarm_from_chat_still_works_and_says_where(make_bot, owner):
    day = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    bot = make_bot([{"tool": "remind__add", "args": {"time": "08:00", "text": "吃藥", "date": day}},
                    "好，明天早上 8 點提醒你吃藥。"])
    bot.talk(owner, "明天早上 8 點提醒我吃藥")
    from synox.schedule.commands import store_for
    items = store_for(bot.app).of(owner).items("remind")
    assert [(it["time"], it["text"], it["date"]) for it in items] == [("08:00", "吃藥", day)]
    assert bot.last(owner) == "好，明天早上 8 點提醒你吃藥。"
    seen = "\n".join(str(getattr(m, "content", m)) for m in bot.app.extras["synox_agent"].adapter.calls[-1][0])
    assert "明天 08:00，會在網頁提醒你" in seen and alarms.NOTE in seen     # AI 拿到的結果講清楚什麼時候、在哪裡響


def test_server_mode_alarm_goes_to_the_member_only(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.say(owner, f"/user_role {OTHER_ID} member")
    bot.say(OTHER_ID, "/start")
    bot.say(OTHER_ID, "/remind_add 07:00 交報告")
    _runner(bot).tick(datetime(2026, 11, 9, 7, 0, 5))
    assert [it["text"] for it in web_items(bot, OTHER_ID)] == ["⏰ 提醒：交報告"]
    assert not any("交報告" in it["text"] for it in web_items(bot, owner))


# ── 工具畫面 ─────────────────────────────────────────────────────────

def test_tool_idle_notice_has_close_and_keep_buttons(make_bot, owner):
    bot = make_bot()
    manager = bot.app.extras["synox_apps"]
    from synox.web.apps.manager import TEXT
    manager._notify(TEXT["idle_suggest"].format(title="記帳", n=30, name="money", m=90), "money",
                    {"suggest_min": 30})
    item = web_items(bot, owner)[-1]
    assert item["kind"] == "tool_idle" and "再 90 分鐘我會自己關" in item["text"]
    assert [(a["id"], a["label"]) for a in item["actions"]] == [("app_stop", "現在關掉"), ("app_keep", "再給我 30 分鐘")]
    assert any(b == "ntfa:stop:money" for b in bot.api.buttons(owner))
    for word in ("服務", "網址", "埠", "閒置"):
        assert word not in item["text"]


# ── 網頁 API ─────────────────────────────────────────────────────────

def test_web_api_list_read_snooze_prefs_alarms(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    bot.say(owner, "/remind_add 08:00 吃藥")
    _runner(bot).tick(datetime(2026, 11, 9, 8, 0, 10))
    status, d = c.get("/api/notifications")
    assert status == 200 and d["unread"] == 1 and d["next"]["text"] == "吃藥"
    nid = d["items"][-1]["id"]
    status, d2 = c.get(f"/api/notifications?since={d['rev']}")
    assert d2["items"] == []
    status, r = c.post(f"/api/notifications/{nid}/snooze")
    assert status == 200 and "再叫你一次" in r["message"]
    status, d = c.get("/api/notifications")
    assert d["unread"] == 0
    status, a = c.get("/api/alarms")
    assert status == 200 and len(a["items"]) == 2 and a["where"] == ["網頁"] and a["note"] == alarms.NOTE
    status, r = c.post("/api/alarms/test")
    assert status == 200 and r["sent"] == ["網頁"]
    status, r = c.post(f"/api/alarms/{a['items'][0]['id']}/delete")
    assert status == 200 and len(c.get("/api/alarms")[1]["items"]) == 1
    status, r = c.post("/api/alarms/999/delete")
    assert status == 404
    hub = notify.of(bot.app)
    hub.notify_owner("另一則")
    status, _ = c.post("/api/notifications/read")
    assert c.get("/api/notifications")[1]["unread"] == 0
    status, p = c.post("/api/notifications/prefs", {"off": {"update": ["web"], "nope": ["web"]}})
    assert status == 200 and next(k for k in p["kinds"] if k["kind"] == "update")["off"] == ["web"]
    status, _ = c.post("/api/notifications/prefs", {"off": "x"})
    assert status == 400


def test_web_api_needs_login_and_is_per_user(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    ui = ui_of(bot)
    status, _ = Client(ui).get("/api/notifications")
    assert status == 401
    notify.of(bot.app).notify_owner("只給擁有者")
    bot.say(owner, f"/user_role {OTHER_ID} member")
    c = Client(ui)
    c.login(OTHER_ID)
    status, d = c.get("/api/notifications")
    assert status == 200 and d["items"] == [] and d["unread"] == 0
