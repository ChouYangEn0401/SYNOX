# -*- coding: utf-8 -*-
"""新手教學（synox/tour）：步驟檔的格式與檢查、位置清單與 app.html 對得起來、每人的進度（接著走、複習）、
/tutorial 與別的叫法、Telegram／Discord 的步驟卡、網頁的 /api/tour、教學畫面的安全限制（static/tour.js 不按任何東西）。
全部在暫存資料夾，不連網、不開埠。"""
import json
import os
import re

import pytest

from isdtelekit.core.channel import Inbound
from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID

from synox.config import ROOT
from synox.packs import library
from synox.tour import BUILTIN_DIR, Engine, anchors, chat as tour_chat, engine, schema
from synox.web import server as web_server
from synox.web.channel import WebChannel

from test_web import Client, ui_of

STATIC = os.path.join(ROOT, "src", "synox", "web", "static")
BASICS = os.path.join(BUILTIN_DIR, "basics.json")


def good(**over):
    raw = {"schema": 1, "id": "demo", "title": "示範", "version": "1.0.0", "minutes": 2,
           "steps": [{"id": "a", "title": "第一步", "body": "按「對話」。", "where": {"anchor": "nav.chat"},
                      "done_when": {"event": "view", "value": "chat"}},
                     {"id": "b", "title": "第二步", "body": "打 /help。", "try": {"text": "/help"}}]}
    raw.update(over)
    return raw


# ── 步驟檔 ────────────────────────────────────────────────────────────

def test_builtin_tutorial_loads_and_is_plain():
    tour = schema.load_file(BASICS)
    assert tour.id == "basics" and tour.source == ""
    owner, member = tour.steps_for(True), tour.steps_for(False)
    assert 8 <= len(owner) <= 12 and 5 <= len(member) <= 12
    assert owner[-1].id == "done-owner" and "現在你可以自己挑想要的工具了" in owner[-1].body
    assert owner[-1].go == {"view": "settings", "tab": "packs"}            # 最後一步連到工具庫
    ids = [s.id for s in owner]
    for need in ("open-chat", "open-settings", "catalog", "read-report", "remove", "get-help"):
        assert need in ids
    assert "確認安裝" in tour.step("read-report").body                       # 教他看報告、自己按確認
    assert not any(s.audience == "owner" for s in member)


@pytest.mark.parametrize("bad, why", [
    ({"schema": 2}, "schema"),
    ({"id": "Bad Id"}, "id"),
    ({"version": "1"}, "version"),
    ({"steps": []}, "steps"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "where": {"anchor": "#composer"}}]}, "不認得的位置"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "where": {"selector": "#x"}}]}, "where"),
    ({"steps": [{"id": "a", "title": "t", "body": "看 https://evil.example"}]}, "連結"),
    ({"steps": [{"id": "a", "title": "t", "body": "<b>x</b>"}]}, "連結"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "done_when": {"event": "click"}}]}, "done_when"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "go": {"view": "control"}}]}, "go"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "go": {"view": "settings", "tab": "x"}}]}, "go.tab"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "try": {"text": "/x", "send": True}}]}, "try"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "script": "alert(1)"}]}, "不認得"),
    ({"steps": [{"id": "a", "title": "t", "body": "b"}, {"id": "a", "title": "t", "body": "b"}]}, "重複"),
    ({"steps": [{"id": "a", "title": "t" * 31, "body": "b"}]}, "太長"),
    ({"steps": [{"id": "a", "title": "t", "body": "b", "audience": "admin"}]}, "audience"),
])
def test_bad_steps_are_refused_whole(bad, why):
    with pytest.raises(schema.StepsError) as e:
        schema.parse(good(**bad))
    assert why in str(e.value)


def test_bad_file_is_skipped_not_half_loaded(tmp_path, caplog):
    (tmp_path / "a.json").write_text(json.dumps(good()), encoding="utf-8")
    broken = good(id="broken")
    broken["steps"][1]["where"] = {"anchor": "nope.nope"}
    (tmp_path / "b.json").write_text(json.dumps(broken), encoding="utf-8")
    (tmp_path / "c.json").write_text("{not json", encoding="utf-8")
    tours = schema.load_dir(str(tmp_path))
    assert [t.id for t in tours] == ["demo"]


def test_renamed_anchor_still_resolves(monkeypatch):
    monkeypatch.setitem(anchors.RENAMED, "nav.old", "nav.chat")
    step = schema.parse_step({"id": "a", "title": "t", "body": "b", "where": {"anchor": "nav.old"}}, "x")
    assert step.anchors == ("nav.chat",)


# ── 位置清單 ↔ 畫面 ───────────────────────────────────────────────────

def test_anchor_list_matches_app_html_exactly():
    html = open(os.path.join(STATIC, "app.html"), encoding="utf-8").read()
    found = re.findall(r'data-tour="([^"]+)"', html)
    assert len(found) == len(set(found)), "同一個位置名在 app.html 出現兩次"
    assert set(found) == set(anchors.ANCHORS)


def test_every_builtin_anchor_is_known_and_no_confirm_buttons_are_listed():
    tour = schema.load_file(BASICS)
    for s in tour.steps:
        assert all(a in anchors.ANCHORS for a in s.anchors)
    html = open(os.path.join(STATIC, "app.html"), encoding="utf-8").read()
    for name in anchors.ANCHORS:
        tag = re.search(r'<[^>]*data-tour="' + re.escape(name) + r'"[^>]*>', html).group(0)
        assert "danger" not in tag and 'type="password"' not in tag and "確認" not in tag


# ── 進度 ──────────────────────────────────────────────────────────────

def test_progress_resume_restart_and_major_version(make_bot, owner):
    bot = make_bot()
    eng = engine(bot.app)
    user = bot.app.users.get_or_create(owner)
    assert eng.should_offer(user)
    tour, at = eng.start(user)
    assert tour.id == "basics" and at == 0 and not eng.should_offer(user)
    steps = eng.steps(user, tour)
    eng.save(user, "basics", step=steps[3].id, state="paused", done=[s.id for s in steps[:3]])
    assert eng.start(user)[1] == 3                                          # 接著上次
    eng.save(user, "basics", step=steps[-1].id, state="finished")
    assert eng.finished(user, tour) == 1
    assert eng.start(user)[1] == 0                                          # 走完了＝從頭複習
    eng.save(user, "basics", step=steps[5].id, state="paused")
    assert eng.start(user, restart=True)[1] == 0
    assert not eng.record(user, tour).get("done")                          # 從頭來：做過的清掉
    assert eng.finished(user, tour) == 1                                    # 從頭來不會忘記走完過幾次
    data = eng.prefs.get(user.tg_id, "tours")
    data["basics"]["version"] = "0.9.0"                                     # 第一個數字不同＝當作沒走過
    eng.prefs.set(user.tg_id, "tours", data)
    assert eng.record(user, tour) == {}


def test_progress_is_per_user_and_encrypted(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    eng = engine(bot.app)
    me, other = bot.app.users.get_or_create(owner), bot.app.users.get_or_create(OTHER_ID)
    eng.start(me)
    eng.save(me, "basics", step="open-settings", state="paused")
    assert eng.record(other, eng.default()) == {} and eng.should_offer(other)
    folder = os.path.join(bot.app.config.data_dir, "tour")
    files = os.listdir(folder)
    assert files and all(f.endswith(".enc") for f in files)
    assert b"open-settings" not in open(os.path.join(folder, files[0]), "rb").read()


def test_content_update_keeps_done_steps(tmp_path, make_bot, owner):
    bot = make_bot()
    folder = tmp_path / "tours"
    folder.mkdir()
    (folder / "demo.json").write_text(json.dumps(good()), encoding="utf-8")
    eng = Engine(bot.app, engine(bot.app).prefs, builtin_dir=str(folder))
    user = bot.app.users.get_or_create(owner)
    eng.start(user, "demo")
    eng.save(user, "demo", step="b", state="paused", done=["a"])
    newer = good(version="1.1.0")
    newer["steps"].insert(1, {"id": "new", "title": "新的一步", "body": "多一步。"})
    newer["steps"] = [s for s in newer["steps"] if s["id"] != "b"]          # 上次停的那步被拿掉了
    (folder / "demo.json").write_text(json.dumps(newer), encoding="utf-8")
    os.utime(folder / "demo.json", (1, 2))                                  # 讓快取知道檔案變了
    tour, at = eng.start(user, "demo")
    assert tour.version == "1.1.0" and eng.steps(user, tour)[at].id == "new"   # 做過的 a 跳過，新的補上


def test_pack_can_bring_its_own_tutorial(tmp_path, make_bot, owner):
    bot = make_bot()
    pack = bot.app.extras["synox_packs"][0]
    tours = os.path.join(pack.manifest.folder, "tours")
    created = not os.path.isdir(tours)
    os.makedirs(tours, exist_ok=True)
    path = os.path.join(tours, "zz-demo.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(good(id="pack-demo"), f)
        eng = engine(bot.app)
        ids = [t.id for t in eng.tours()]
        assert ids[0] == "basics" and "pack-demo" in ids
        assert eng.get("pack-demo").source == pack.manifest.name
        bot.say(owner, "/tutorial list")
        assert "pack-demo" in bot.last(owner) and pack.manifest.name in bot.last(owner)
    finally:
        os.remove(path)
        if created:
            os.rmdir(tours)


def test_tutorial_is_core_not_a_tool(make_bot, owner, tmp_path):
    """出廠就有教學，但它不是工具：沒有任何 pack 時，「還沒裝任何工具」照樣成立。"""
    bot = make_bot(pack_dirs=[str(tmp_path / "nothing")])
    assert library.installed_tools(bot.app) == [] and library.status(bot.app)["empty"]
    assert engine(bot.app).default().id == "basics"
    assert bot.app.registry.node("tutorial") is not None


# ── 指令（Telegram／Discord 的樣子） ─────────────────────────────────────

def test_tutorial_command_step_cards_and_buttons(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/tutorial")
    text = bot.last(owner)
    assert text.startswith("🎓 SYNOX 新手教學（1／") and "嗨，我是 SYNOX" in text
    buttons = bot.buttons(owner)
    assert buttons[0] == "tour:go:basics:1" and buttons[-1].startswith("tour:x:basics:")
    bot.press(owner, "tour:go:basics:1")
    assert "這裡是「對話」" in bot.last(owner) and "tour:go:basics:0" in bot.buttons(owner)
    bot.press(owner, "tour:go:basics:2")
    assert "可以直接打：/help" in bot.last(owner)
    bot.press(owner, "tour:x:basics:2")
    assert "之後打 /tutorial 就會從這裡接著走" in bot.last(owner)
    bot.say(owner, "/tutorial")
    assert "（3／" in bot.last(owner)                                     # 接著走
    bot.say(owner, "/tutorial restart")
    assert "（1／" in bot.last(owner)
    eng = engine(bot.app)
    n = len(eng.steps(bot.app.users.get_or_create(owner), eng.default()))
    card = bot.api.sent[-1].message_id                                      # 按鈕上的「第幾步」是直接跳（同一則卡片原地改）
    bot.press(owner, f"tour:go:basics:{n - 1}", message_id=card)
    assert bot.buttons(owner)[-2] == "tour:end:basics"
    bot.press(owner, "tour:end:basics")
    assert "走完了" in bot.last(owner) and "/tutorial" in bot.last(owner)


def test_web_only_steps_tell_chat_users_to_open_the_web(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/tutorial")
    user = bot.app.users.get_or_create(owner)
    eng = engine(bot.app)
    steps = eng.steps(user, eng.default())
    at = next(i for i, s in enumerate(steps) if s.anchors and not s.chat)
    bot.press(owner, f"tour:go:basics:{at}", message_id=bot.api.sent[-1].message_id)
    assert tour_chat.WEB_NOTE in bot.last(owner)


@pytest.mark.parametrize("text", ["開始教學", "start tutorial", "Start Tutorial!", "教學", "/tour", "/start tutorial"])
def test_other_ways_to_start(make_bot, owner, text):
    bot = make_bot()
    bot.say(owner, text)
    assert "SYNOX 新手教學（1／" in bot.last(owner)


def test_phrase_inside_a_sentence_is_not_rewritten(make_bot, owner):
    bot = make_bot(["好的"])
    bot.talk(owner, "我想要教學怎麼做蛋糕")
    assert "新手教學（" not in bot.last(owner)


def test_member_gets_member_steps_and_tutorial_is_not_an_ai_tool(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.say(OTHER_ID, "/tutorial list")
    assert "/tutorial basics" in bot.last(OTHER_ID)
    eng = engine(bot.app)
    steps = eng.steps(bot.app.users.get_or_create(OTHER_ID), eng.default())
    assert steps[-1].id == "done-member" and not any(s.id == "catalog" for s in steps)
    assert bot.app.registry.node("tutorial").ai is False


def test_help_points_to_tutorial(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/help")
    assert bot.texts(owner)[0].startswith("📖") and tour_chat.HELP_LINE in bot.texts(owner)
    bot.clear()
    bot.say(owner, "/help all")
    assert tour_chat.HELP_LINE not in bot.texts(owner)


def test_help_line_comes_before_the_empty_hint(make_bot, owner, tmp_path):
    bot = make_bot(pack_dirs=[str(tmp_path / "nothing")])
    bot.say(owner, "/help")
    texts = bot.texts(owner)
    assert texts[0].startswith("📖") and texts[1] == tour_chat.HELP_LINE and "還沒裝任何工具" in texts[-1]


# ── 網頁 ──────────────────────────────────────────────────────────────

def test_web_tutorial_reply_carries_a_tour_block(make_bot, owner):
    bot = make_bot()
    ui = ui_of(bot)
    chat = ui.chats.new_chat(owner)["id"]
    api = WebChannel(ui.chats, owner, chat, home=bot.api)
    bot.app.dispatcher.handle(api, Inbound("web", owner, owner, "開始教學"))
    msg = ui.chats.events(owner, chat)[0][-1]
    assert msg["blocks"] == [{"type": "tour", "tour": "basics", "step": "welcome"}]
    assert "看畫面上亮起來的地方" in msg["text"] and not msg["buttons"]


def test_web_api_tour_state_progress_and_offer(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    c = Client(ui_of(bot))
    c.login(owner)
    status, d = c.get("/api/tour")
    assert status == 200 and d["offer"] is True and d["default"] == "basics" and d["progress"] == {}
    tour = d["tours"][0]
    assert tour["steps"][0]["id"] == "welcome" and all("audience" not in s for s in tour["steps"])
    assert any(s.get("anchors") == ["nav.chat"] for s in tour["steps"])
    assert c.post("/api/tour/offer", {"answer": "later"})[0] == 200
    assert c.get("/api/tour")[1]["offer"] is False
    status, r = c.post("/api/tour/progress", {"tour": "basics", "step": "open-chat", "state": "active",
                                               "done": ["welcome"]})
    assert status == 200 and r["progress"]["step"] == "open-chat" and r["progress"]["done"] == ["welcome"]
    assert c.get("/api/tour")[1]["progress"]["basics"]["state"] == "active"
    assert c.post("/api/tour/progress", {"tour": "nope", "step": "a"})[0] == 404
    assert c.post("/api/tour/progress", {"tour": "basics", "step": "nope"})[0] == 400
    assert c.post("/api/tour/progress", {"tour": "basics", "state": "hacked"})[0] == 400
    assert c.post("/api/tour/progress", {"tour": "basics", "done": "welcome"})[0] == 400
    assert c.post("/api/tour/offer", {"answer": "maybe"})[0] == 400
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    md = m.get("/api/tour")[1]
    assert md["offer"] is True and md["progress"] == {}                     # 每人一份
    assert not any(s["id"] == "catalog" for s in md["tours"][0]["steps"])
    status, _h, _b = c.raw("POST", "/api/tour/progress", b'{"tour": "basics"}', headers={"X-SYNOX-CSRF": "x"})
    assert status == 403                                                    # 跟其他改東西的 API 一樣要 CSRF


def test_app_page_includes_tour_ui():
    html = web_server.render_app("n0nce")
    assert "window.SynoxTour" in html and ".tour-ring" in html
    assert html.count('<script nonce="n0nce">') >= 3


# ── 教學畫面的安全限制（static/tour.js）───────────────────────────────

def test_tour_js_never_presses_anything():
    js = open(os.path.join(STATIC, "tour.js"), encoding="utf-8").read()
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = "\n".join(line.split("//")[0] for line in code.splitlines())
    assert ".click(" not in code and "requestSubmit" not in code and ".submit(" not in code
    assert "innerHTML" not in code and "eval(" not in code and "fetch(" not in code
    calls = re.findall(r'ctx\.api\("([A-Z]+)",\s*"([^"]+)"', code)
    assert set(calls) == {("GET", "/api/tour"), ("POST", "/api/tour/progress"), ("POST", "/api/tour/offer")}
    css = open(os.path.join(STATIC, "tour.css"), encoding="utf-8").read()
    ring = re.search(r"\.tour-ring \{[^}]*\}", css).group(0)
    assert "pointer-events: none" in ring
    assert "prefers-reduced-motion" in css


def test_language_follows_lang_txt_with_fallback(tmp_path, make_bot, owner):
    """同一個 id 好幾個語言：照 SYNOX 資料夾的 lang.txt 挑，沒有就退回 en、再退回 zh-TW（同安裝精靈）。"""
    bot = make_bot()
    folder = tmp_path / "tours"
    folder.mkdir()
    (folder / "demo.json").write_text(json.dumps(good()), encoding="utf-8")
    (folder / "demo.en.json").write_text(json.dumps(good(lang="en", title="Demo")), encoding="utf-8")
    eng = Engine(bot.app, engine(bot.app).prefs, builtin_dir=str(folder))
    root = bot.app.extras["synox_config"].root
    assert eng.get("demo").lang == "zh-TW"                                  # 沒有 lang.txt
    with open(os.path.join(root, "lang.txt"), "w", encoding="utf-8") as f:
        f.write("ja")
    assert eng.get("demo").title == "Demo"                                  # 沒有日文 → en
    with pytest.raises(schema.StepsError):
        schema.parse(good(lang="xx"))
