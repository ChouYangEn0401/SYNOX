"""主機台加固（工具服務計畫 WP0）：別的網頁送來的 /api/ 請求擋掉、同名 cookie、COOP／CORP、Sessions.has。"""

import pytest

from synox.web.tokens import Sessions, digest

from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")


def owner_client(make_bot):
    bot = make_bot()
    ui = bot.app.extras["synox_web"]
    c = Client(ui)
    c.login(bot.app.config.owner_id)
    return bot, ui, c


@pytest.mark.parametrize("site", ["same-site", "cross-site"])
def test_api_from_other_sites_is_refused(make_bot, site):
    _bot, _ui, c = owner_client(make_bot)
    status, _h, body = c.raw("GET", "/api/me", headers={"Sec-Fetch-Site": site})
    assert status == 403 and "來源不對".encode() in body
    status, _h, _b = c.raw("POST", "/api/chats", b"{}", headers={"Sec-Fetch-Site": site})
    assert status == 403


@pytest.mark.parametrize("site", ["same-origin", "none", None])
def test_api_same_origin_or_no_header_is_fine(make_bot, site):
    _bot, _ui, c = owner_client(make_bot)
    headers = {"Sec-Fetch-Site": site} if site else {}
    assert c.raw("GET", "/api/me", headers=headers)[0] == 200


def test_pages_are_not_affected(make_bot):
    _bot, ui, c = owner_client(make_bot)
    for path in ("/", "/login", "/tutorials/x/"):
        status, _h, _b = c.raw("GET", path, headers={"Sec-Fetch-Site": "cross-site"})
        assert status == c.raw("GET", path)[0], path


def test_duplicate_session_cookies(make_bot):
    _bot, ui, c = owner_client(make_bot)
    real = c.cookie
    for cookie in (f"synox_session=fake; {real}", f"{real}; synox_session=fake"):
        status, _h, _b = ui.handle("GET", "/api/me", {"Host": c.host, "Cookie": cookie})
        assert status == 200, cookie
    assert ui.session_key({"Cookie": f"synox_session=fake; {real}"}) == digest(real.split("=", 1)[1])
    assert ui.session_key({"Cookie": "synox_session=fake"}) is None


def test_coop_everywhere_corp_on_json(make_bot):
    _bot, ui, c = owner_client(make_bot)
    for method, path in (("GET", "/"), ("GET", "/api/me"), ("GET", "/nope"), ("GET", "/api/zzz"),
                         ("GET", "/login?t=bad")):
        status, headers, _b = c.raw(method, path)
        h = dict(headers)
        assert h.get("Cross-Origin-Opener-Policy") == "same-origin", (path, status)
        if h.get("Content-Type", "").startswith("application/json"):
            assert h.get("Cross-Origin-Resource-Policy") == "same-origin", path
    status, headers, _b = ui.handle("GET", "/api/me", {"Host": c.host})          # 沒登入的 401 也有
    assert dict(headers)["Cross-Origin-Resource-Policy"] == "same-origin"


def test_sessions_has(tmp_path):
    clock = [1000.0]
    s = Sessions(str(tmp_path / "s.json"), clock=lambda: clock[0], ttl=60)
    sid, _sess = s.create(1)
    key = digest(sid)
    assert s.has(key) and not s.has("nope") and not s.has("")
    s.drop(sid)
    assert not s.has(key)
    sid2, _ = s.create(1)
    clock[0] += 61
    assert not s.has(digest(sid2))
    sid3, _ = s.create(2)
    s.drop_all()
    assert not s.has(digest(sid3))
