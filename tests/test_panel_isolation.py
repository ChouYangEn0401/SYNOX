"""工具頁面板隔開（ADR 0028 §5）＋安裝報告的標章、「送去安裝頁檢查」（§3、§4）的網頁那一層。

面板在 <iframe sandbox="allow-scripts"> 裡跑（opaque origin）：網址自己帶一張票（綁 pack＋登入＋人、8 小時），
伺服器只認票、不看 cookie；票不能拿去打 /api/。瀏覽器裡真的怎麼跑（opaque origin 的 fetch、CORS null）這裡測不到，
只測伺服器回什麼（ADR 0028 §10 要擁有者在自己的電腦上看一次）。
"""

import json
import os
import re
import sys
import time
import types

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.packs.admin import GateRefused, PackAdminError
from synox.web import server as web_server

from conftest import OTHER_ID
from test_web import Client, ui_of

pytestmark = pytest.mark.usefixtures("no_sockets")

STATIC = os.path.join(os.path.dirname(web_server.__file__), "static")


def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def owner_client(make_bot, owner):
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    return bot, c


def ticket_of(c, name="money"):
    status, data = c.post(f"/api/packs/{name}/panel-ticket")
    assert status == 200, data
    assert re.fullmatch(r"[A-Za-z0-9_-]{22}", data["ticket"])          # urlsafe 128 bit
    return data["ticket"]


def bare(ui, path, **headers):
    """沒有 cookie 的請求（隔開的面板送出來的就是這樣）。"""
    return ui.handle("GET", path, {"Host": "127.0.0.1:8830", **headers})


# ── 拿票 ─────────────────────────────────────────────────────────────

def test_ticket_needs_login_and_csrf(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    assert c.raw("POST", "/api/packs/money/panel-ticket", b"{}", headers={"X-SYNOX-CSRF": ""})[0] == 403
    assert ui.handle("POST", "/api/packs/money/panel-ticket", {"Host": c.host}, b"{}")[0] == 401
    assert c.raw("POST", "/api/packs/money/panel-ticket", b"{}",
                 headers={"Origin": "http://evil.example"})[0] == 403
    assert c.post("/api/packs/notes/panel-ticket")[0] == 404             # notes 沒有面板
    assert c.post("/api/packs/nope/panel-ticket")[0] == 404
    assert c.raw("GET", "/api/packs/money/panel-ticket")[0] == 404        # 只收 POST


def test_ticket_needs_the_pack_to_be_visible(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.say(777, "/start")
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    guest, member = Client(ui_of(bot)), Client(ui_of(bot))
    guest.login(777)
    member.login(OTHER_ID)
    assert guest.post("/api/packs/money/panel-ticket")[0] == 404
    member.say("tools", "/money 30 早餐")
    t = ticket_of(member)
    status, headers, body = bare(ui_of(bot), f"/packs/money/panel/{t}/api/summary")
    assert status == 200 and json.loads(body)["total"] == 30               # 以發票的那個人的身分


# ── 面板頁：只認票 ────────────────────────────────────────────────────

def test_panel_page_is_served_only_with_a_valid_ticket(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    t = ticket_of(c)
    status, headers, body = bare(ui, f"/packs/money/panel/{t}/")
    h = dict(headers)
    assert status == 200 and b"<title>" in body
    csp = h["Content-Security-Policy"]
    assert csp.startswith("sandbox allow-scripts;") and "allow-same-origin" not in csp
    assert "connect-src 'self'" in csp and "frame-ancestors 'self'" in csp and "form-action 'none'" in csp
    assert h["X-Frame-Options"] == "SAMEORIGIN" and h["Cache-Control"] == "no-store"
    assert h["Referrer-Policy"] == "no-referrer"
    assert "Set-Cookie" not in h
    assert bare(ui, f"/packs/money/panel/{t}")[0] == 404                  # 一定要有結尾的 /
    assert bare(ui, "/packs/money/panel/" + "A" * 22 + "/")[0] == 404     # 亂猜的票
    assert bare(ui, f"/packs/notes/panel/{t}/")[0] == 404                 # 別的 pack
    assert bare(ui, f"/packs/money/panel/{t}x/")[0] == 404
    assert c.raw("GET", "/packs/money/panel")[0] == 404                   # 舊的同源網址：不再提供
    assert c.raw("POST", f"/packs/money/panel/{t}/")[0] == 404            # 只收 GET


def test_ticket_expires_after_8_hours(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    t = ticket_of(c)
    assert ui.panel_tickets.ttl == 8 * 3600
    now = time.time()
    ui.panel_tickets._clock = lambda: now + 8 * 3600 + 1
    assert bare(ui, f"/packs/money/panel/{t}/")[0] == 404
    assert bare(ui, f"/packs/money/panel/{t}/api/summary")[0] == 404


def test_ticket_dies_with_its_login(owner_client, owner):
    bot, c = owner_client
    ui = ui_of(bot)
    t = ticket_of(c)
    other = Client(ui)
    other.login(owner)                                                   # 同一個人、另一個登入
    t2 = ticket_of(other)
    assert c.post("/api/logout")[0] == 200
    assert bare(ui, f"/packs/money/panel/{t}/")[0] == 404                 # 登出 → 那個登入的票作廢
    assert bare(ui, f"/packs/money/panel/{t2}/")[0] == 200                # 別的登入的票不受影響
    ui.sessions.drop_all()                                               # 沒走 drop_session 的路：用的時候也會查登入還在不在
    assert bare(ui, f"/packs/money/panel/{t2}/")[0] == 404


def test_web_off_drops_every_ticket(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    t = ticket_of(c)
    ui.turn_off()
    ui.disabled = False
    assert bare(ui, f"/packs/money/panel/{t}/")[0] == 404


# ── 面板讀資料：api/<route> ──────────────────────────────────────────

def test_panel_api_works_without_cookie_from_an_opaque_origin(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    c.say("tools", "/money 120 午餐")
    t = ticket_of(c)
    status, headers, body = bare(ui, f"/packs/money/panel/{t}/api/summary", Origin="null",
                                 **{"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"})
    h = dict(headers)
    assert status == 200 and json.loads(body)["total"] == 120
    assert h["Access-Control-Allow-Origin"] == "null" and h["Vary"] == "Origin"
    assert "Access-Control-Allow-Credentials" not in h
    assert "Cross-Origin-Resource-Policy" not in h
    assert h["Content-Type"].startswith("application/json") and h["Cache-Control"] == "no-store"


def test_panel_api_only_serves_declared_routes(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    t = ticket_of(c)
    assert bare(ui, f"/packs/money/panel/{t}/api/secret")[0] == 404
    assert bare(ui, f"/packs/money/panel/{t}/api/summary/x")[0] == 404
    assert bare(ui, f"/packs/money/panel/{t}/api/")[0] == 404


def test_a_panel_ticket_is_not_a_login(owner_client):
    bot, c = owner_client
    ui = ui_of(bot)
    t = ticket_of(c)
    for path in ("/api/me", "/api/packs/money/summary", "/api/settings"):
        assert bare(ui, path)[0] == 401
        assert bare(ui, path, Origin="null")[0] == 401
        assert ui.handle("GET", path, {"Host": c.host, "Cookie": f"synox_session={t}"})[0] == 401
        assert bare(ui, path + f"?ticket={t}")[0] == 401
    status, _h, _b = ui.handle("POST", "/api/packs/install", {"Host": c.host, "Origin": "null",
                                                              "Cookie": f"synox_session={t}"}, b"{}")
    assert status == 401
    assert bare(ui, f"/packs/money/panel/{t}/../../../api/me")[0] == 404


def test_tools_js_never_gives_panels_the_same_origin():
    js = _read("tools.js")
    assert "allow-same-origin" not in js
    joined = re.sub(r'" \+\s+"', "", js)                                # 長字串分兩行寫
    assert 'setAttribute("sandbox", "allow-scripts")' in js
    assert "/panel-ticket" in js and 'setAttribute("referrerpolicy", "no-referrer")' in js
    assert "這個小畫面是工具作者做的。SYNOX 把它隔開了：它碰不到你的登入，只能讀這個工具自己的資料；" \
           "畫面裡的字和按鈕都是作者寫的，不是 SYNOX 的。" in joined
    assert "tp-panel-note" in js
    for label in ("✅ 官方", "✍️ 作者簽章", "⚠️ 不是官方"):
        assert label in js


# ── 標章（從鎖讀）───────────────────────────────────────────────────

def test_tools_and_settings_carry_the_signature_from_the_lock(owner_client, monkeypatch):
    bot, c = owner_client
    from synox.packs import lock as pack_lock
    real = pack_lock.entry
    fake = {"money": {"signature": {"status": "official", "key_id": "k"}}, "notes": {"signature": {"status": "evil"}}}
    monkeypatch.setattr(pack_lock, "entry", lambda data_dir, name: fake.get(name) or real(data_dir, name))
    packs = {p["name"]: p for p in c.get("/api/tools")[1]["packs"]}
    assert packs["money"]["signature"] == "official"
    assert packs["notes"]["signature"] == "none"                          # 看不懂的值＝不是官方
    rows = {p["name"]: p for p in c.get("/api/settings")[1]["packs"]}
    assert rows["money"]["signature"] == "official" and rows["notes"]["signature"] == "none"


# ── 送去安裝頁檢查（adopt）───────────────────────────────────────────

@pytest.fixture
def fake_adopt(monkeypatch):
    calls = {"stage": [], "install": []}
    mod = types.ModuleType("synox.packs.adopt")

    def stage_unlocked(name, packs_dir, data_dir, config=None):
        calls["stage"].append((name, packs_dir, data_dir))
        if name == "bad":
            raise GateRefused("⛔ 被改過", {"name": "bad", "signature": {"status": "invalid"}})
        if name == "gone":
            raise PackAdminError("找不到這個工具。")
        return "tok12345678", {"token": "tok12345678", "name": name, "adopt": name,
                               "signature": {"status": "none", "label": "⚠️ 不是官方"}}

    def install(token, data_dir, packs_dir, approved_by=None, via="web", trust=None, trust_publisher=None,
                runtime=None, accept_warnings=None):
        calls["install"].append({"token": token, "approved_by": approved_by, "via": via})
        return "money"

    mod.stage_unlocked, mod.install = stage_unlocked, install
    import synox.packs
    monkeypatch.setitem(sys.modules, "synox.packs.adopt", mod)
    monkeypatch.setattr(synox.packs, "adopt", mod, raising=False)
    return calls


def test_adopt_stages_and_installs_through_the_adopt_module(owner_client, fake_adopt, owner):
    bot, c = owner_client
    status, data = c.post("/api/packs/adopt", {"name": "money"})
    assert status == 200 and data["adopt"] == "money" and data["token"] == "tok12345678"
    assert "upgrade" not in data                                         # 跟自己比版本沒有意義
    assert fake_adopt["stage"][0][0] == "money"
    status, data = c.post("/api/packs/install", {"token": "tok12345678", "adopt": True, "upgrade": True})
    assert status == 200 and data["ok"] and data["name"] == "money"
    assert fake_adopt["install"] == [{"token": "tok12345678", "approved_by": owner, "via": "web"}]


def test_adopt_refusals(owner_client, fake_adopt):
    bot, c = owner_client
    status, data = c.post("/api/packs/adopt", {"name": "bad"})
    assert status == 400 and data["refused"]["signature"]["status"] == "invalid"
    status, data = c.post("/api/packs/adopt", {"name": "gone"})
    assert status == 400 and "找不到" in data["error"]
    assert c.post("/api/packs/adopt", {"name": "../x"})[0] == 400
    assert c.raw("POST", "/api/packs/adopt", b'{"name": "money"}', headers={"X-SYNOX-CSRF": ""})[0] == 403


def test_adopt_is_owner_only(make_bot, fake_adopt):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = Client(ui_of(bot))
    m.login(OTHER_ID)
    assert m.post("/api/packs/adopt", {"name": "money"})[0] == 403
    assert m.post("/api/packs/install", {"token": "tok12345678", "adopt": True})[0] == 403
    assert fake_adopt["stage"] == [] and fake_adopt["install"] == []


def test_adopt_without_the_module_says_what_to_do(owner_client, monkeypatch):
    bot, c = owner_client
    import synox.packs
    monkeypatch.setitem(sys.modules, "synox.packs.adopt", None)          # import 會失敗
    monkeypatch.delattr(synox.packs, "adopt", raising=False)
    status, data = c.post("/api/packs/adopt", {"name": "money"})
    assert status == 400 and "上傳並檢查" in data["error"]


def test_adopt_integration_with_the_real_module(make_bot, owner, tmp_path):
    adopt = pytest.importorskip("synox.packs.adopt")                    # 合併 sec/loader 之後才有
    assert hasattr(adopt, "stage_unlocked") and hasattr(adopt, "install")
    bot = make_bot()
    c = Client(ui_of(bot))
    c.login(owner)
    status, data = c.post("/api/packs/adopt", {"name": "no-such-pack"})
    assert status == 400 and data.get("error")


# ── 網頁（app.html）：報告的順序、清單的按鈕 ───────────────────────────

def _function(src, name):
    start = src.index("function " + name + "(")
    nxt = re.search(r"\n  function |\n  var [A-Z]", src[start + 10:])
    return src[start:start + 10 + (nxt.start() if nxt else len(src))]


def test_report_draws_the_badge_before_the_packs_own_text():
    html = _read("app.html")
    review = _function(html, "showReview")
    assert review.index("signature.label") < review.index("s.title +")
    assert review.index("lookalike") < review.index("s.title +")
    assert review.index("safety_notice") < review.index('"確認升級" : "確認安裝"')
    assert "body.adopt = true" in review
    failed = _function(html, "reviewFailed")
    assert "invalid" in failed


def test_pack_list_offers_the_adopt_button():
    html = _read("app.html")
    assert 'unapproved: "沒有經過安裝頁，先不開"' in html
    fill = _function(html, "fillPacks")
    assert "送去安裝頁檢查" in fill and "adoptPack(p" in fill and 'p.status === "unapproved"' in fill
    assert "/api/packs/adopt" in _function(html, "adoptPack") and "showReview(s, true)" in _function(html, "adoptPack")
    assert "sigChip(p.signature)" in fill
    assert "建議開「沙盒模式」執行" not in html
    for cls in (".sig-official", ".sig-author", ".sig-none"):
        assert cls in html
