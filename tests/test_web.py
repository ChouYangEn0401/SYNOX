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


class Client:
    """假瀏覽器：記 cookie、帶 CSRF。"""

    def __init__(self, ui, host="127.0.0.1:8830"):
        self.ui = ui
        self.cookie = ""
        self.csrf = ""
        self.host = host

    def login(self, tg_id):
        status, headers, _ = self.ui.handle("GET", f"/login?t={self.ui.tokens.issue(tg_id)}", {"Host": self.host})
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
    status, headers, _ = ui.handle("GET", f"/login?t={token}", {})
    h = dict(headers)
    assert status == 303 and h["Location"] == "/#chat"
    assert "HttpOnly" in h["Set-Cookie"] and "SameSite=Lax" in h["Set-Cookie"]
    status, _h, body = ui.handle("GET", f"/login?t={token}", {})                # 第二次用：不行
    assert status == 403 and "用過了".encode() in body
    assert ui.handle("GET", "/login?t=nope", {})[0] == 403


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
    assert msgs and msgs[-1]["buttons"] and all("data" in b for row in msgs[-1]["buttons"] for b in row)
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
    assert {"notes", "money", "remind"} <= set(packs)
    assert packs["money"]["panel"] == "/packs/money/panel" and packs["money"]["status"] == "已連接"
    assert packs["notion"]["status"] == "要先設定"
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
    assert {"notes", "money", "remind"} <= names and "notion" not in names
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
                       ("/api/packs/install", {"token": "x" * 10})]:
        assert m.post(path, body)[0] == 403, path
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
    assert ui_of(bot).handle("GET", f"/login?t={link.group(1)}", {})[0] == 303
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
    monkeypatch.setattr(web_server, "ThreadingHTTPServer", refuse)
    bot = make_bot(raw={"web": {"port": 8830}})
    ui = ui_of(bot)
    assert ui.start() is False
    assert "8830" in ui.error and "web.port" in ui.error
    bot.say(owner, "/note 照常")
    assert "照常" in bot.last(owner) or "記" in bot.last(owner)
    bot.say(owner, "/web")
    assert "沒有在跑" in bot.last(owner)


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
