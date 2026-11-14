"""Web UI：直接呼叫 WebUI.handle（不開埠）＋ WebChannel 走 SDK BotHarness 的 dispatcher。"""

import io
import json
import os
import re
import zipfile

import pytest

from isdtelekit.core.channel import Inbound
from isdtelekit.users.roles import BasicRoles

from synox import backup
from synox.web import server as web_server
from synox.web.channel import WebChannel
from synox.web.tokens import LoginTokens, Sessions, digest

from conftest import OTHER_ID

GUEST_ID = 777


def form_of(body: bytes) -> str:
    return re.search(rb'name="f" value="([^"]+)"', body).group(1).decode()


def confirm_login(ui, page_headers, page_body, host="127.0.0.1:8830", extra=None):
    """按確認頁的「登入」：帶確認頁發的 synox_login cookie 與表單 token，從同一個 Origin POST。"""
    binder = next(v for k, v in page_headers if k == "Set-Cookie" and v.startswith("synox_login=")).split(";")[0]
    headers = {"Host": host, "Origin": f"http://{host}", "Cookie": binder,
               "Content-Type": "application/x-www-form-urlencoded", **(extra or {})}
    return ui.handle("POST", "/login", headers, f"f={form_of(page_body)}".encode())


class Client:
    """假瀏覽器：記 cookie、帶 CSRF。"""

    def __init__(self, ui, host="127.0.0.1:8830"):
        self.ui = ui
        self.cookie = ""
        self.csrf = ""
        self.host = host

    def login(self, tg_id):
        status, headers, body = self.ui.handle("GET", f"/login?t={self.ui.tokens.issue(tg_id)}", {"Host": self.host})
        assert status == 200                                            # 確認頁（還沒登入）
        status, headers, _ = confirm_login(self.ui, headers, body, host=self.host)
        assert status == 303
        cookie = dict(headers)["Set-Cookie"]
        self.cookie = cookie.split(";")[0]
        self.csrf = self.get("/api/me")[1]["csrf"]
        return cookie

    def raw(self, method, path, body=b"", headers=None):
        h = {"Host": self.host, "Cookie": self.cookie}
        if method != "GET":
            h["X-SYNOX-CSRF"] = self.csrf
        h.update(headers or {})
        return self.ui.handle(method, path, h, body)

    def get(self, path):
        status, headers, body = self.raw("GET", path)
        ctype = dict(headers).get("Content-Type", "")
        return status, (json.loads(body) if ctype.startswith("application/json") else body)

    def post(self, path, data=None, **kw):
        status, _headers, body = self.raw("POST", path, json.dumps(data or {}).encode("utf-8"), **kw)
        return status, json.loads(body)

    def say(self, chat, text, wait=True):
        status, data = self.post(f"/api/chat/{chat}/send", {"text": text})
        assert status == 200, data
        if wait:
            self.ui.app.tasks.wait(10)
        return data

    def events(self, chat, since=0):
        status, data = self.get(f"/api/chat/{chat}/events?since={since}")
        assert status == 200, data
        return data["messages"]


def ui_of(bot):
    return bot.app.extras["synox_web"]


@pytest.fixture
def owner_client(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    return bot, c


# ── 登入 ─────────────────────────────────────────────────────────────

def test_login_link_is_one_time_and_sets_safe_cookie(make_bot, owner):
    bot = make_bot()
    ui = ui_of(bot)
    token = ui.tokens.issue(owner)
    with open(ui.tokens.path, encoding="utf-8") as f:
        stored = json.load(f)
    assert token not in json.dumps(stored) and digest(token) in stored           # 檔案裡只有雜湊
    page = ui.handle("GET", f"/login?t={token}", {"Host": "127.0.0.1:8830"})
    assert page[0] == 200
    status, headers, _ = confirm_login(ui, page[1], page[2])
    h = dict(headers)
    assert status == 303 and h["Location"] == "/#chat"
    assert "HttpOnly" in h["Set-Cookie"] and "SameSite=Lax" in h["Set-Cookie"]
    status, _h, body = ui.handle("GET", f"/login?t={token}", {})                # 第二次用：不行
    assert status == 403 and "用過了".encode() in body
    assert ui.handle("GET", "/login?t=nope", {})[0] == 403


def test_login_link_get_only_shows_who_and_needs_a_same_browser_post(make_bot, owner):
    """審查 A #6（login CSRF）：別人把他的登入連結塞給你 → GET 不會讓你登入成他；先看到「你將以 <名字> 登入」。"""
    bot = make_bot()
    ui = ui_of(bot)
    bot.app.users.get_or_create(GUEST_ID, "mallory")
    token = ui.tokens.issue(GUEST_ID)
    status, headers, body = ui.handle("GET", f"/login?t={token}", {"Host": "127.0.0.1:8830"})
    assert status == 200 and "mallory".encode() in body and "你將以".encode() in body
    assert not any(v.startswith("synox_session=") for k, v in headers if k == "Set-Cookie")   # 還沒登入
    assert ui.tokens.peek(token) == GUEST_ID                                    # 連結還沒用掉
    binder = next(v for k, v in headers if k == "Set-Cookie" and v.startswith("synox_login="))
    assert "SameSite=Strict" in binder and "HttpOnly" in binder
    f = form_of(body)
    post = {"Host": "127.0.0.1:8830", "Content-Type": "application/x-www-form-urlencoded"}
    assert ui.handle("POST", "/login", post, f"f={f}".encode())[0] == 403            # 沒有這個瀏覽器的 cookie
    assert ui.handle("POST", "/login", {**post, "Origin": "https://evil.example", "Cookie": binder.split(";")[0]},
                     f"f={f}".encode())[0] == 403                                  # 跨站送出
    assert ui.handle("POST", "/login", {**post, "Sec-Fetch-Site": "cross-site", "Cookie": binder.split(";")[0]},
                     f"f={f}".encode())[0] == 403
    assert ui.tokens.peek(token) == GUEST_ID                                    # 擋下的都沒有用掉連結
    status, headers, _ = confirm_login(ui, headers, body)                       # 本人在同一個瀏覽器按「登入」
    assert status == 303
    assert confirm_login(ui, headers, body)[0] == 403                           # 表單 token 只能用一次


def test_cookie_secure_only_behind_https(make_bot, owner):
    """審查 A #8：public_url 是 https 時 cookie 加 Secure（HttpOnly、SameSite 照留）；本機 http 不加。"""
    plain = Client(ui_of(make_bot()))
    assert "Secure" not in plain.login(owner)
    bot = make_bot(raw={"web": {"public_url": "https://synox.example.org/"}})
    ui = ui_of(bot)
    page = ui.handle("GET", f"/login?t={ui.tokens.issue(owner)}", {"Host": "synox.example.org"})
    binder = next(v for k, v in page[1] if k == "Set-Cookie" and v.startswith("synox_login="))
    assert "; Secure" in binder
    status, headers, _ = confirm_login(ui, page[1], page[2], host="synox.example.org")
    session = dict(headers)["Set-Cookie"]
    assert status == 303 and "; Secure" in session and "HttpOnly" in session and "SameSite=Lax" in session


def test_login_page_warns_when_switching_account(make_bot, owner):
    bot = make_bot()
    ui = ui_of(bot)
    c = Client(ui)
    c.login(owner)
    status, _h, body = c.raw("GET", f"/login?t={ui.tokens.issue(GUEST_ID)}")
    assert status == 200 and "現在登入的是".encode() in body and f"id {owner}".encode() in body


def test_login_token_expires_after_seven_days(tmp_path):
    now = [1000.0]
    tokens = LoginTokens(str(tmp_path / "t.json"), clock=lambda: now[0])
    token = tokens.issue(5)
    now[0] += 7 * 24 * 3600 + 1
    assert tokens.redeem(token) is None
    fresh = tokens.issue(5)
    assert tokens.redeem(fresh) == 5


def test_sessions_survive_restart_and_store_only_hashes(tmp_path):
    path = str(tmp_path / "s.json")
    sid, session = Sessions(path).create(42)
    assert sid not in open(path, encoding="utf-8").read()
    again = Sessions(path).get(sid)
    assert again is not None and again.tg_id == 42 and again.csrf == session.csrf


def test_api_needs_session_and_csrf(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    assert ui.handle("GET", "/api/me", {})[0] == 401
    status, data = c.post("/api/chats", {}, headers={"X-SYNOX-CSRF": "wrong"})
    assert status == 403 and "CSRF" in data["error"]
    status, data = c.post("/api/chats", {}, headers={"Origin": "http://evil.example"})
    assert status == 403 and "Origin" in data["error"]
    status, data = c.post("/api/chats", {}, headers={"Origin": "http://127.0.0.1:8830"})
    assert status == 200
    status, data = c.post("/api/logout")
    assert status == 200 and c.get("/api/me")[0] == 401


def test_app_page_has_nonce_csp_and_no_inline_handlers(make_bot):
    ui = ui_of(make_bot())
    status, headers, body = ui.handle("GET", "/", {})
    h = dict(headers)
    html = body.decode("utf-8")
    nonce = re.search(r"script-src 'nonce-([^']+)'", h["Content-Security-Policy"]).group(1)
    assert status == 200 and f'nonce="{nonce}"' in html and "{{NONCE}}" not in html
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"] and h["X-Frame-Options"] == "DENY"
    assert not re.search(r"<[^>]+\son[a-z]+\s*=", html)                       # 沒有 onclick= 之類
    assert not re.search(r"<(script|link|img|iframe)[^>]+(src|href)=\"https?:", html)   # 沒有外部資源
    assert "cdn" not in html.lower()


# ── 對話頁 ───────────────────────────────────────────────────────────

def test_chat_command_and_ai_and_approval_card(make_bot, owner):
    bot = make_bot([{"tool": "note__clear", "args": {}}])
    c = Client(ui_of(bot))
    c.login(owner)
    chat = c.post("/api/chats")[1]["id"]
    c.say(chat, "/note 買牛奶")
    msgs = c.events(chat)
    assert msgs[0]["from"] == "me" and any("買牛奶" in m["text"] for m in msgs if m["from"] == "bot")
    c.say(chat, "把筆記全部刪掉")                                            # 自由文字 → AI（FakeAdapter）
    msgs = c.events(chat)
    card = [m for m in msgs if "AI 想執行：/note_clear" in m["text"]][0]
    datas = [b["data"] for row in card["buttons"] for b in row]
    go = [d for d in datas if d.startswith("agent_ok:go:")][0]
    assert any(d.startswith("agent_ok:no:") for d in datas)
    status, data = c.post(f"/api/chat/{chat}/press", {"message_id": card["id"], "data": "agent_ok:go:forged"})
    assert status == 409                                                      # 不在那則訊息上的按鈕
    status, data = c.post(f"/api/chat/{chat}/press", {"message_id": card["id"], "data": go})
    assert status == 200
    bot.app.tasks.wait(5)
    msgs = c.events(chat)
    assert any("全部筆記都刪掉了（1 筆）" in m["text"] for m in msgs)
    assert [m for m in msgs if m["id"] == card["id"]][0]["buttons"] == []        # 按過就拿掉按鈕
    listed = c.get("/api/chats")[1]["chats"]
    assert listed[0]["id"] == chat and listed[0]["title"] == "/note 買牛奶"


def test_chats_are_per_user_and_encrypted(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    a, b = Client(ui_of(bot)), Client(ui_of(bot))
    a.login(owner)
    b.login(OTHER_ID)
    chat = a.post("/api/chats")[1]["id"]
    a.say(chat, "/note 擁有者的秘密")
    assert b.get("/api/chats")[1]["chats"] == []
    assert b.get(f"/api/chat/{chat}/events?since=0")[0] == 404
    path = os.path.join(bot.app.config.data_dir, "web_chats", f"{owner}.json.enc")
    assert os.path.isfile(path) and "秘密".encode() not in open(path, "rb").read()


def test_events_since_returns_only_newer(owner_client):
    bot, c = owner_client
    chat = c.post("/api/chats")[1]["id"]
    c.say(chat, "/help")
    first = c.get(f"/api/chat/{chat}/events?since=0")[1]
    assert first["messages"] and c.events(chat, first["rev"]) == []


def test_web_channel_through_harness(make_bot, owner):
    """WebChannel 實作 SDK Channel：自己的訊息進紀錄、按鈕變成可以按的資料；送給別人的交給 home（Telegram）。"""
    bot = make_bot()
    ui = ui_of(bot)
    chat = ui.chats.new_chat(owner)["id"]
    api = WebChannel(ui.chats, owner, chat, home=bot.api)
    bot.app.dispatcher.handle(api, Inbound("web", owner, owner, "/help"))
    msgs = ui.chats.events(owner, chat)[0]
    page = msgs[0]                                   # /help 的第一則是指令選單（後面多一行指到 /tutorial）
    assert page["buttons"] and all("data" in b for row in page["buttons"] for b in row)
    api.send_message(OTHER_ID, "給別人的")
    assert bot.last(OTHER_ID) == "給別人的"
    mid = api.send_message(owner, "改我", reply_markup={"inline_keyboard": [[{"text": "x", "callback_data": "y"}]]})
    mid = mid["result"]["message_id"]
    api.edit_message_text(owner, mid, "改好了")
    api.remove_buttons(owner, mid)
    _chat, msg = ui.chats.find(owner, mid)
    assert msg["text"] == "改好了" and msg["buttons"] == []


def test_chat_keeps_last_50(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    chat = ui.chats.new_chat(bot.app.owner_id)["id"]
    for i in range(60):
        ui.chats.append(bot.app.owner_id, chat, "bot", str(i))
    msgs = ui.chats.events(bot.app.owner_id, chat)[0]
    assert len(msgs) == 50 and msgs[0]["text"] == "10"


# ── 工具頁與面板 ─────────────────────────────────────────────────────

def test_tools_page_owner_sees_packs_and_panel(owner_client):
    bot, c = owner_client
    status, data = c.get("/api/tools")
    packs = {p["name"]: p for p in data["packs"]}
    assert {"notes", "money"} <= set(packs) and "remind" not in packs
    remind = next(g for g in data["groups"] if g["id"] == "remind")            # ⏰ 提醒（系統）：系統群組，不是 pack
    assert remind["title"] == "⏰ 提醒（系統）" and remind["category"] == "系統"
    assert packs["money"]["panel"] == "/packs/money/panel" and packs["money"]["status"] == "已連接"
    assert any(cmd["command"] == "/money" and cmd["usage"] for cmd in packs["money"]["commands"])
    c.say("tools", "/money 120 午餐")
    assert any("記了：午餐 120 元" in m["text"] for m in c.events("tools"))
    status, summary = c.get("/api/packs/money/summary")
    assert status == 200 and summary["total"] == 120
    status, headers, body = c.raw("GET", "/packs/money/panel")
    h = dict(headers)
    assert status == 200 and b"/api/packs/money/summary" in body
    assert h["X-Frame-Options"] == "SAMEORIGIN" and "connect-src 'self'" in h["Content-Security-Policy"]
    assert c.get("/api/packs/money/secret")[0] == 404                        # 沒宣告的 route


def test_guest_sees_no_packs_member_only_theirs(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.say(GUEST_ID, "/start")
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    g, m = Client(ui_of(bot)), Client(ui_of(bot))
    g.login(GUEST_ID)
    m.login(OTHER_ID)
    assert g.get("/api/tools")[1]["packs"] == []
    assert g.get("/packs/money/panel")[0] == 404 and g.get("/api/packs/money/summary")[0] == 404
    names = {p["name"] for p in m.get("/api/tools")[1]["packs"]}
    assert {"notes", "money"} <= names and "notion" not in names
    assert "remind" in {grp["id"] for grp in m.get("/api/tools")[1]["groups"]}   # 成員看得到 ⏰ 提醒（系統）
    assert "remind" not in {grp["id"] for grp in g.get("/api/tools")[1]["groups"]}  # 訪客沒有
    g.say("tools", "/note 想偷用")
    assert not os.path.exists(os.path.join(bot.app.config.data_dir, "users", str(GUEST_ID), "notes.json.enc"))
    m.say("tools", "/money 30 早餐")
    assert m.get("/api/packs/money/summary")[1]["total"] == 30


# ── 設定頁 ───────────────────────────────────────────────────────────

def test_owner_only_settings(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    settings = m.get("/api/settings")[1]
    assert settings["owner"] is False and "llm" not in settings and "ai_budget" in settings
    for path, body in [("/api/settings/llm", {"choice": "none"}), ("/api/packs/reload", {}),
                       ("/api/packs/remove", {"name": "money"}), ("/api/backup", {}),
                       ("/api/packs/install", {"token": "x" * 10}), ("/api/packs/discard", {"token": "x" * 10})]:
        assert m.post(path, body)[0] == 403, path
    assert m.get("/api/packs/staged")[0] == 403
    assert m.post("/api/accounts/role", {"id": GUEST_ID, "role": "admin"})[0] == 403
    assert m.raw("POST", "/api/packs/upload", b"PK")[0] == 403


def test_save_llm_puts_key_in_vault(make_bot, owner, tmp_path):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.post("/api/settings/llm", {"choice": "keys", "provider": "openai", "api_key": "sk-test-123",
                                                "model": "gpt-x"})
    assert status == 200, data
    with open(tmp_path / "config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    assert cfg["llm"]["kind"] == "openai" and cfg["llm"]["api_key"] == "vault:llm_api_key"
    assert "sk-test" not in json.dumps(cfg) and bot.app.extras["vault"].secret("llm_api_key") == "sk-test-123"
    status, data = c.post("/api/settings/llm", {"choice": "keys", "provider": "openai", "api_key": "",
                                                "model": "gpt-y"})                # 留空＝沿用
    assert status == 200 and bot.app.extras["vault"].secret("llm_api_key") == "sk-test-123"
    assert c.post("/api/settings/llm", {"choice": "keys", "provider": "gemini"})[0] == 400


def test_llm_test_gives_download_url_when_claude_missing(make_bot, owner, monkeypatch):
    from synox.llm import claude_code
    from synox.wizard import logic
    monkeypatch.setattr(claude_code, "find_claude", lambda: None)
    c = Client(ui_of(make_bot()))
    c.login(owner)
    status, data = c.post("/api/settings/llm/test", {"choice": "claude_code"})
    assert status == 200 and data["ok"] is False and data["download_url"] == logic.CLAUDE_DOWNLOAD_URL
    status, data = c.post("/api/settings/llm/test", {"choice": "none"})
    assert "download_url" not in data


def test_saving_llm_applies_immediately_without_restart(make_bot, owner):
    """設定頁選 Claude Code 並存起來：對話助理與常駐助理馬上有 AI（不用重開）；改回「不用 AI」馬上拿掉。"""
    from synox.llm.claude_code import ClaudeCodeAdapter
    from synox import runtime
    bot = make_bot(llm={"kind": "none"})
    app = bot.app
    assert app.extras["synox_agent"] is None and app.dispatcher.fallback is None
    rt = runtime.of(app)
    assert rt.mother.adapter is None and rt.status()["mother"]["ai"] is False

    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.get("/api/settings")
    cc = next(x for x in data["llm_choices"] if x["choice"] == "claude_code")
    assert [m["value"] for m in cc["models"]] == ["", "sonnet", "opus", "haiku"]

    status, data = c.post("/api/settings/llm", {"choice": "claude_code", "model": "sonnet"})
    assert status == 200 and data["applied"] is True, data
    loop = app.extras["synox_agent"]
    assert loop is not None and isinstance(loop.adapter, ClaudeCodeAdapter) and loop.adapter.model == "sonnet"
    assert app.dispatcher.fallback is not None                      # 私訊打字會進 AI
    assert rt.mother.adapter is loop.adapter and rt.status()["mother"]["ai"] is True
    assert c.get("/api/settings")[1]["llm"]["model"] == "sonnet"

    status, data = c.post("/api/settings/llm", {"choice": "claude_code", "model": "opus"})     # 換模型：同一個 loop
    assert app.extras["synox_agent"] is loop and loop.adapter.model == "opus"

    status, data = c.post("/api/settings/llm", {"choice": "none"})
    assert status == 200 and app.extras["synox_agent"] is None and app.dispatcher.fallback is None
    assert rt.mother.adapter is None


def test_saving_llm_that_cannot_connect_still_saves_and_says_why(make_bot, owner, tmp_path, monkeypatch):
    from synox.llm.base import LLMError

    def boom(*a, **k):
        raise LLMError("缺了 ntu_easy_llm")
    monkeypatch.setattr("synox.llm.make_adapter", boom)
    bot = make_bot(llm={"kind": "none"})
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.post("/api/settings/llm", {"choice": "keys", "provider": "openai", "api_key": "sk-x", "model": "m"})
    assert status == 200 and data["applied"] is False and "缺了 ntu_easy_llm" in data["message"]
    assert bot.app.extras["synox_agent"] is None
    with open(tmp_path / "config.json", encoding="utf-8") as f:
        assert json.load(f)["llm"]["kind"] == "openai"              # 設定存了，只是還沒接上


def test_llm_test_tells_how_to_log_in_when_claude_not_signed_in(make_bot, owner, monkeypatch):
    monkeypatch.setattr("synox.wizard.logic.probe_llm", lambda llm, make=None: "Claude Code 回了錯誤：x。是不是還沒登入？")
    c = Client(ui_of(make_bot()))
    c.login(owner)
    status, data = c.post("/api/settings/llm/test", {"choice": "claude_code"})
    assert "claude" in data["message"] and "登入" in data["message"] and "download_url" not in data


def _pack_zip(name="hello", top=None, extra=None):
    buf = io.BytesIO()
    prefix = f"{top}/" if top else ""
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(prefix + "pack.json", json.dumps({"name": name, "title": "👋 打招呼", "summary": "說嗨",
                                                     "version": "0.1.0", "kind": "python", "access": "owner"}))
        z.writestr(prefix + "SKILL.md", f"---\nname: {name}\ndescription: d\n---\n")
        z.writestr(prefix + "pack.py", "def install(app, pack):\n"
                   "    pack.group.leaf('hi', lambda api, c, u, a: api.send_message(c, 'hi there'), '打招呼', "
                   "default=True)\n")
        for path, data in (extra or {}).items():
            z.writestr(path, data)
    return buf.getvalue()


def test_pack_upload_install_remove_reload(make_bot, owner, tmp_path):
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    from synox.packs import loader
    bot = make_bot(pack_dirs=(str(user_packs),) + loader.PACK_DIRS)
    c = Client(ui_of(bot))
    c.login(owner)
    status, _h, body = c.raw("POST", "/api/packs/upload", _pack_zip(top="hello-pack"))
    summary = json.loads(body)
    assert status == 200 and summary["name"] == "hello" and summary["warnings"]
    bot.say(owner, "/hello")
    assert "hi there" not in bot.last(owner)                                  # 還沒按確認：沒裝
    status, data = c.post("/api/packs/install", {"token": summary["token"]})
    assert status == 200 and data["status"] == "loaded", data
    bot.say(owner, "/hello")
    assert bot.last(owner) == "hi there"
    status, _h, body = c.raw("POST", "/api/packs/upload", _pack_zip())
    assert c.post("/api/packs/install", {"token": json.loads(body)["token"]})[0] == 400   # 同名：不蓋
    packs = {p["name"]: p for p in c.get("/api/settings")[1]["packs"]}
    assert packs["hello"]["removable"] and not packs["money"]["removable"]
    status, data = c.post("/api/packs/remove", {"name": "hello"})
    assert status == 200 and data["moved_to"].startswith(os.path.join("userpacks", "_removed", "hello-"))
    assert not (user_packs / "hello").exists()
    bot.clear()
    bot.say(owner, "/hello")
    assert bot.last(owner) != "hi there"
    status, data = c.post("/api/packs/reload")
    assert status == 200 and "money" in {p["name"] for p in data["packs"]}
    bot.say(owner, "/money 10 茶")
    assert "記了" in bot.last(owner)


@pytest.mark.parametrize("bad", [{"../evil.py": "x"}, {"/abs.py": "x"}, {"C:/win.py": "x"}])
def test_pack_upload_rejects_unsafe_paths(owner_client, bad):
    bot, c = owner_client
    status, _h, body = c.raw("POST", "/api/packs/upload", _pack_zip(extra=bad))
    assert status == 400, body
    staging = os.path.join(bot.app.config.data_dir, "web_uploads")
    assert not os.path.isdir(staging) or not any(
        os.path.exists(os.path.join(staging, d, "pack")) for d in os.listdir(staging))


def test_pack_upload_rejects_non_zip_and_bad_manifest(owner_client):
    bot, c = owner_client
    assert c.raw("POST", "/api/packs/upload", b"not a zip")[0] == 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pack.json", json.dumps({"name": "Bad Name"}))
    status, _h, body = c.raw("POST", "/api/packs/upload", buf.getvalue())
    assert status == 400 and "pack.json" in json.loads(body)["error"]


def test_staged_packs_are_listed_without_token_and_can_be_discarded(make_bot, owner, tmp_path):
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    from synox.packs import loader
    bot = make_bot(pack_dirs=(str(user_packs),) + loader.PACK_DIRS)
    c = Client(ui_of(bot))
    c.login(owner)
    assert c.get("/api/packs/staged")[1]["staged"] == []
    first = json.loads(c.raw("POST", "/api/packs/upload", _pack_zip())[2])["token"]
    second = json.loads(c.raw("POST", "/api/packs/upload", _pack_zip(name="howdy"))[2])["token"]
    status, data = c.get("/api/packs/staged")                    # 沒有 ?pack=<token> 也看得到等核准的
    assert status == 200 and data["max_age_days"] == 7
    rows = {s["token"]: s for s in data["staged"]}
    assert set(rows) == {first, second}
    assert rows[first]["name"] == "hello" and rows[first]["version"] == "0.1.0" and rows[first]["title"] == "👋 打招呼"
    assert 0 < rows[first]["expires_in"] <= 7 * 86400
    assert c.post("/api/packs/discard", {"token": first}) == (200, {"ok": True})
    assert not os.path.exists(os.path.join(bot.app.config.data_dir, "web_uploads", first))
    assert c.post("/api/packs/discard", {"token": first})[0] == 404
    assert c.post("/api/packs/discard", {"token": "../../etc"})[0] == 404
    assert c.get("/api/pack-staged/" + first)[0] == 404
    assert [s["token"] for s in c.get("/api/packs/staged")[1]["staged"]] == [second]
    assert c.post("/api/packs/install", {"token": second})[0] == 200
    assert c.get("/api/packs/staged")[1]["staged"] == []          # 裝好了＝不在待核准清單


def test_stale_and_half_done_staged_uploads_are_cleaned(tmp_path):
    import time
    from synox.packs import admin
    data = str(tmp_path / "data")
    token, _summary = admin.stage(_pack_zip(), data)
    root = admin.staging_root(data)
    half = os.path.join(root, "HalfDoneToken123")                 # 解到一半就當機：沒有 staged.json
    os.makedirs(os.path.join(half, "pack"))
    fresh_half = os.path.join(root, "StillUnpacking12")
    os.makedirs(fresh_half)
    other = os.path.join(root, "not a token")                     # 不像 token 的不碰
    os.makedirs(other)
    old = time.time() - 2 * admin.STAGED_HALF_DONE
    os.utime(half, (old, old))
    listed = admin.list_staged(data)
    assert [s["token"] for s in listed] == [token]
    assert not os.path.exists(half) and os.path.isdir(fresh_half) and os.path.isdir(other)
    later = time.time() + admin.STAGED_MAX_AGE + 60               # 7 天沒處理：過期清掉
    assert admin.list_staged(data, now=later) == []
    assert not os.path.exists(os.path.join(root, token)) and os.path.isdir(other)
    with pytest.raises(admin.PackAdminError):
        admin.discard_staged("..", data)


def _settings_html():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "src", "synox", "web", "static", "app.html"), encoding="utf-8") as f:
        return f.read()


def test_settings_page_is_split_into_tabs():
    html = _settings_html()
    section = html.split('<section id="view-settings"')[1].split("</section>")[0]
    panels = re.split(r'<div class="tab-panel hidden" data-tab="([a-z]+)" role="tabpanel">', section)
    where = {}
    for tab, body in zip(panels[1::2], panels[2::2]):
        for card in re.findall(r'<div id="(set-[a-z]+)" class="card', body):
            where[card] = tab
    assert where == {"set-llm": "ai", "set-usage": "ai", "set-channels": "channels", "set-install": "packs",
                     "set-packs": "packs", "set-library": "packs", "set-skills": "packs", "set-sandbox": "packs",
                     "set-accounts": "accounts", "set-security": "security", "set-awake": "system",
                     "set-backup": "system", "set-help": "help",
                     "set-look": "appearance", "set-custom": "appearance", "set-mode": "appearance",
                     "set-commands": "commands"}
    tabs = re.findall(r'<a href="(#[a-z:]+)" data-tab="([a-z]+)" role="tab"[^>]*>', section)   # [^>]*：教學的 data-tour
    assert {t for _h, t in tabs} == set(where.values())
    assert ("#packs", "packs") in tabs                              # 安裝頁的穩定網址（拖放之類的入口也用它）
    assert section.index('id="set-install"') < section.index('id="set-packs"')   # 報告在清單上面，不用往下找


def test_install_view_flow_and_hooks():
    html = _settings_html()
    for needle in ('id="install-steps"', 'id="staged-list"', "/api/packs/staged", "/api/packs/discard",
                   '"synox:install-step"', "window.SynoxInstall", "history.replaceState",
                   'location.pathname + "#packs"', "@keyframes flow-pulse"):
        assert needle in html, needle
    order = re.search(r'var STEP_ORDER = \[([^\]]+)\]', html).group(1)
    assert [s.strip().strip('"') for s in order.split(",")] == ["check", "review", "confirm", "installing", "done"]


def test_accounts_page(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.say(GUEST_ID, "/start")
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.get("/api/accounts")
    ids = {u["id"]: u for u in data["users"]}
    assert status == 200 and GUEST_ID in ids and ids[GUEST_ID]["role"] == "guest"
    assert "messages_limit" in ids[GUEST_ID] and ids[GUEST_ID]["ai_limit_usd"] == 2.0
    status, data = c.post("/api/accounts/role", {"id": GUEST_ID, "role": "member"})
    assert status == 200 and data["role"] == "member"
    assert bot.app.users.get(GUEST_ID).role == BasicRoles.MEMBER
    # 管理員想從網頁降級擁有者：走的是 SDK accounts 同一個指令，同一套保護（動手的人反被降級）
    bot.make(OTHER_ID, BasicRoles.ADMIN)
    admin = Client(ui_of(bot))
    admin.login(OTHER_ID)
    assert admin.get("/api/accounts")[0] == 200
    status, data = admin.post("/api/accounts/role", {"id": owner, "role": "guest"})
    assert "不可降級機器擁有者" in data["message"]
    assert bot.app.users.get(owner).role == BasicRoles.ADMIN
    assert bot.app.users.get(OTHER_ID).role == BasicRoles.GUEST
    assert admin.get("/api/accounts")[0] == 403                              # 降成訪客之後就看不到了


def test_accounts_absent_in_personal_mode(owner_client):
    _bot, c = owner_client
    assert c.get("/api/accounts")[0] == 404 and c.get("/api/me")[1]["accounts"] is False


def test_backup_is_encrypted_zip_of_data(owner_client):
    bot, c = owner_client
    bot.say(bot.app.owner_id, "/note 備份裡的筆記")
    status, headers, blob = c.raw("POST", "/api/backup", b"{}")
    h = dict(headers)
    assert status == 200 and h["Content-Type"] == "application/zip"
    assert re.search(r'filename="synox-backup-\d{8}\.zip"', h["Content-Disposition"])
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert set(z.namelist()) == {"README.txt", "data.zip.enc"}
        assert b"notes" not in z.read("data.zip.enc")
    inner = backup.read_backup(blob, bot.app.extras["vault"])
    with zipfile.ZipFile(io.BytesIO(inner)) as z:
        names = set(z.namelist())
    assert "notes.json.enc" in names and "web_sessions.json" not in names and "web_tokens.json" not in names
    from synox.vault import Vault, VaultError
    with pytest.raises(VaultError):
        backup.read_backup(blob, Vault(b"x" * 32, str(bot.app.config.data_dir)))


# ── /web、/web_off、開不起來 ─────────────────────────────────────────

def test_web_command_gives_link(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/web")
    link = re.search(r"http://127\.0\.0\.1:8830/login\?t=(\S+)", bot.last(owner))
    assert link
    page = ui_of(bot).handle("GET", f"/login?t={link.group(1)}", {"Host": "127.0.0.1:8830"})
    assert page[0] == 200 and confirm_login(ui_of(bot), page[1], page[2])[0] == 303
    bot.say(GUEST_ID, "/web")                                                 # 個人版：別人沒有
    assert "login" not in bot.last(GUEST_ID)


def test_web_command_in_server_mode_for_guests(make_bot, owner):
    bot = make_bot(raw={"mode": "server", "web": {"public_url": "https://synox.example.org/"}})
    bot.say(GUEST_ID, "/web")
    assert "https://synox.example.org/login?t=" in bot.last(GUEST_ID)
    c = Client(ui_of(bot))
    c.login(GUEST_ID)
    me = c.get("/api/me")[1]
    assert me["role"] == "guest" and me["owner"] is False and me["ai"] is False


def test_web_off(owner_client):
    bot, c = owner_client
    bot.say(bot.app.owner_id, "/web_off")
    assert "關掉了" in bot.last(bot.app.owner_id)
    assert c.raw("GET", "/api/me")[0] == 503
    bot.say(bot.app.owner_id, "/web")
    assert "/web_off" in bot.last(bot.app.owner_id)


def test_bind_failure_keeps_bot_running(make_bot, owner, monkeypatch):
    def refuse(*a, **kw):
        raise OSError(10048, "address already in use")
    monkeypatch.setattr(web_server, "_Server", refuse)
    bot = make_bot(raw={"web": {"port": 8830}})
    ui = ui_of(bot)
    assert ui.start() is False
    assert "8830" in ui.error and "web.port" in ui.error
    bot.say(owner, "/note 照常")
    assert "照常" in bot.last(owner) or "記" in bot.last(owner)
    bot.say(owner, "/web")
    assert "沒有在跑" in bot.last(owner)


def test_port_already_in_use_is_a_bind_failure(make_bot):
    """Windows 的 SO_REUSEADDR 會讓第二支綁上同一個埠還說成功（登入連結被送到別支 SYNOX）：要失敗。"""
    import socket
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)      # 跟另一支（舊版）SYNOX 的網頁一樣
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        ui = ui_of(make_bot(raw={"web": {"port": port}}))
        assert ui.start() is False and str(port) in ui.error
    finally:
        holder.close()


def test_disabled_web_does_not_start(make_bot, owner):
    bot = make_bot(raw={"web": {"enabled": False}})
    assert ui_of(bot).start() is False
    bot.say(owner, "/web")
    assert "enabled" in bot.last(owner)


def test_bad_web_port_is_config_error(tmp_path):
    from isdtelekit.host.config import ConfigError
    from synox.config import SynoxConfig
    with pytest.raises(ConfigError):
        SynoxConfig.from_dict({"owner_id": 1, "web": {"port": "abc"}}, require_token=False, root=str(tmp_path))
    assert SynoxConfig.from_dict({"owner_id": 1}, require_token=False, root=str(tmp_path)).web["port"] == 8830


# ── 本機擁有者直接開網址就進 ───────────────────────────────────────────

NAV = {"Host": "127.0.0.1:8830", "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate",
       "Sec-Fetch-Dest": "document"}


def test_local_owner_typing_the_url_logs_in(make_bot, owner):
    ui = ui_of(make_bot())
    status, headers, _ = ui.handle("GET", "/", dict(NAV))
    cookie = dict(headers)["Set-Cookie"].split(";")[0]
    assert status == 200 and cookie.startswith("synox_session=")
    c = Client(ui)
    c.cookie = cookie
    status, me = c.get("/api/me")
    assert status == 200 and me["owner"] is True


@pytest.mark.parametrize("change", [
    {"Sec-Fetch-Site": "cross-site"},                    # 別的網站的連結／重新導向
    {"Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Mode": "cors"},                          # fetch
    {"Sec-Fetch-Dest": "iframe"},
    {"Host": "evil.example.com:8830"},                   # DNS rebinding
    {"Host": "127.0.0.1:9999"},
    {"Origin": "http://evil.example.com"},
    {"Sec-Fetch-Site": None},                            # 沒有標頭（curl／舊瀏覽器）
])
def test_local_auto_login_refuses_anything_but_a_typed_navigation(make_bot, change):
    ui = ui_of(make_bot())
    headers = {**NAV, **change}
    headers = {k: v for k, v in headers.items() if v is not None}
    status, resp_headers, _ = ui.handle("GET", "/", headers)
    assert status == 200 and "Set-Cookie" not in dict(resp_headers)
    assert ui.handle("GET", "/api/me", {"Host": "127.0.0.1:8830"})[0] == 401


def test_local_auto_login_is_off_for_server_mode_public_url_and_the_switch(make_bot):
    for raw in ({"mode": "server"}, {"web": {"public_url": "https://x.example.com"}},
                {"web": {"local_auto_login": False}}):
        ui = ui_of(make_bot(raw=raw))
        ui.port = 8830
        _s, resp_headers, _b = ui.handle("GET", "/", dict(NAV))
        assert "Set-Cookie" not in dict(resp_headers), raw


# ── 真瀏覽器的登入：同源表單 POST 會帶 Origin: null（Referrer-Policy: no-referrer）──────

def _login_page_for(ui, owner):
    page = ui.handle("GET", f"/login?t={ui.tokens.issue(owner)}", {"Host": "127.0.0.1:8830"})
    assert page[0] == 200
    return page


def test_login_confirm_works_with_the_origin_null_a_real_browser_sends(make_bot, owner):
    ui = ui_of(make_bot())
    page = _login_page_for(ui, owner)
    status, _h, _b = confirm_login(ui, page[1], page[2], extra={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
    assert status == 303


@pytest.mark.parametrize("extra", [
    {"Origin": "null"},                                              # 沒有 Sec-Fetch-Site：分不出是不是自己
    {"Origin": "null", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "null", "Sec-Fetch-Site": "same-site"},
    {"Origin": "http://evil.example.com", "Sec-Fetch-Site": "same-origin"},
])
def test_login_confirm_still_refuses_foreign_or_unproven_origins(make_bot, owner, extra):
    ui = ui_of(make_bot())
    page = _login_page_for(ui, owner)
    status, _h, body = confirm_login(ui, page[1], page[2], extra=extra)
    assert status == 403 and "登入沒有完成".encode() in body


def test_login_page_lets_the_browser_send_the_real_origin(make_bot, owner):
    ui = ui_of(make_bot())
    headers = _login_page_for(ui, owner)[1]
    policies = [v for k, v in headers if k == "Referrer-Policy"]
    assert policies == ["same-origin"]


def test_discord_pair_api_manual_id_and_owner_only(make_bot, owner, tmp_path):
    from synox.discord.events import DISCORD
    from synox.identity import Identities
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    assert c.post("/api/settings/channels/discord/pair", {"action": "manual", "user_id": "abc"})[0] == 400
    assert c.post("/api/settings/channels/discord/pair", {"action": "start"})[0] == 409           # Discord 沒開：不能用 bot 收碼
    status, data = c.post("/api/settings/channels/discord/pair", {"action": "manual", "user_id": " 123456789012345678 "})
    assert status == 200 and data["paired_as"] == "123456789012345678"
    assert Identities(str(tmp_path / "data" / "identities.json")).external(DISCORD, bot.app.config.owner_id) == "123456789012345678"
    assert c.get("/api/settings/channels/discord/pair")[1]["paired_as"] == "123456789012345678"
    from tests.test_web import GUEST_ID
    m = Client(ui_of(bot))
    m.login(GUEST_ID)
    assert m.post("/api/settings/channels/discord/pair", {"action": "manual", "user_id": "123456789012345678"})[0] == 403
    assert m.get("/api/settings/channels/discord/pair")[0] == 403
