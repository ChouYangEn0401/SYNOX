"""遠端閘門（ADR 0026 §3–§5；計畫 K7）：進門、進門之後、白名單、標頭、次數。直接呼叫 handle_raw，不開埠、不開子程序。"""

import json

import pytest

from synox import guard
from synox.web.remote.gate import COOKIE

from remote_helpers import make_phone

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")


def counter_calls():
    import sys
    return sys.modules["synox_pack_counter"].CALLS


@pytest.fixture
def opened(counter, owner):
    phone = make_phone(counter, owner)
    out = phone.open()
    return phone, out


def headers_ok(headers):
    h = dict(headers)
    assert h["Strict-Transport-Security"].startswith("max-age=") and "noindex" in h["X-Robots-Tag"]
    assert not any(k.lower().startswith("access-control-") for k in h)


def test_enter_page_is_synox_own(opened):
    phone, out = opened
    c = phone.client()
    c.host = phone.manager.link.host
    status, headers, body = c.raw("GET", "/")
    assert status == 200 and "SYNOX 手機入口".encode() in body and b"counter" not in body and "計數".encode() not in body
    headers_ok(headers)
    assert c.raw("GET", "/_synox/enter.js")[0] == 200 and c.raw("GET", "/app.js")[0] == 404


def test_enter_success_cookie_flags_and_ticket(opened, owner):
    phone, out = opened
    c = phone.client()
    status, headers, body = c.knock(out["url"], phone.code())
    assert status == 200
    cookie = dict(headers)["Set-Cookie"]
    assert cookie.startswith(COOKIE + "=") and all(x in cookie for x in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"))
    assert json.loads(body)["next"].startswith("/#t=")
    assert any("有人從手機進來了" in t for t in phone.bot.texts(owner))


def test_same_code_as_open_does_not_enter(counter, owner):
    phone = make_phone(counter, owner)
    user = phone.bot.app.users.get_or_create(owner)
    code = phone.code()
    out = phone.manager.open("counter", user, code, origin=phone.tg)
    assert phone.client().knock(out["url"], code)[0] == 403


def test_key_once_expired_and_identical_failures(opened, owner):
    phone, out = opened
    c = phone.client()
    bad = c.knock(out["url"].replace("#k=", "#k=x"), phone.code())
    worse = phone.client().knock(out["url"], "000000" if phone.code(False) != "000000" else "111111")
    assert bad[0] == worse[0] == 403 and bad[2] == worse[2]
    assert c.knock(out["url"], phone.code())[0] == 200
    again = phone.client().knock(out["url"], phone.code())
    assert again[0] == 403 and again[2] == bad[2]


def test_key_expires_closes_entry(counter, owner):
    phone = make_phone(counter, owner)
    out = phone.open()
    phone.clock.t += 301
    assert phone.client().knock(out["url"], phone.code())[0] == 403
    phone.manager.tick()
    assert phone.manager.link.state == "closed"


def test_five_bad_codes_close_and_notify_once(opened, owner):
    phone, out = opened
    for _ in range(5):
        phone.client().knock(out["url"], "12345x")
    assert phone.manager.link.state == "closed"
    assert len([t for t in phone.bot.texts(owner) if "亂敲門" in t]) == 1


def test_after_entering(opened, owner):
    phone, out = opened
    c = phone.client()
    me = c.enter(out["url"], phone.code())
    assert me["remote"] is True and me.get("remote_until")
    assert c.do("add", {"n": "3"})[0] == 200
    phone.bot.say(owner, "/counter_show")
    assert phone.bot.last(owner) == "現在是 3"
    assert c.read("state")[1]["data"] == {"n": 3}
    before = counter_calls()["reset"]
    status, data = c.do("reset", {}, confirmed=True)
    assert status == 403 and data["code"] == "remote_no_danger" and counter_calls()["reset"] == before
    for path in ("/api/keep", "/api/apps", "/login", "/api/export/state_csv", "/api/settings"):
        assert c.post(path, {})[0] == 404, path
    assert c.get("/api/apps")[0] == 404
    rows = phone.apps.audit.tail(50)
    assert any(r["event"] == "action" and r["via"] == "remote" for r in rows)


def test_cookie_and_host_and_origin_checks(opened):
    phone, out = opened
    c = phone.client()
    c.enter(out["url"], phone.code())
    good = c.cookie
    nothing = c.get("/api/me", headers={"Cookie": None})
    assert nothing[0] == 404
    for cookie in (f"{COOKIE}=nope", f"{good}; {good}"):
        assert c.get("/api/me", headers={"Cookie": cookie})[0] == 404
    assert c.get("/api/me", headers={"User-Agent": "Other/2.0"})[0] == 404
    assert c.get("/api/me", headers={"Host": "other.trycloudflare.com"})[0] == 404
    assert c.post("/api/do/add", {"values": {"n": "1"}}, headers={"Origin": "https://evil.example"})[0] == 400
    status, headers, _b = c.raw("GET", "/api/me")
    assert status == 200
    headers_ok(headers)
    assert "Set-Cookie" not in dict(headers)


def test_forwarded_headers_are_whitelisted(opened):
    phone, out = opened
    c = phone.client()
    c.enter(out["url"], phone.code())
    seen = {}
    site = phone.manager.gate.app_site
    real = site.handle

    def spy(method, target, headers, body=b""):
        seen.update(headers)
        from synox.guard import origin
        seen["_origin"] = origin.current().kind
        return real(method, target, headers, body)
    site.handle = spy
    c.get("/api/me", headers={"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "1.2.3.4"})
    assert not any(k.startswith(("cf-", "x-forwarded-")) for k in seen) and "cookie" not in seen
    assert seen["host"] == site.host_header and seen["_origin"] == "remote"


def test_rate_limits(opened):
    phone, out = opened
    c = phone.client()
    c.host = phone.manager.link.host
    statuses = [c.raw("GET", "/")[0] for _ in range(61)]
    assert statuses[-1] == 429 and statuses[0] == 200
    raw = open(guard.of(phone.bot.app).audit.path, encoding="utf-8").read()
    assert "remote_reject" in raw


def test_too_many_rejects_close(opened):
    phone, out = opened
    c = phone.client()
    c.host = phone.manager.link.host
    for _ in range(300):
        c.raw("GET", "/%2e%2e/secret-path-XYZ")
        phone.clock.t += 1
    assert phone.manager.link.state == "closed"
    assert "secret-path-XYZ" not in open(guard.of(phone.bot.app).audit.path, encoding="utf-8").read()


def test_closed_means_404_for_everything(opened):
    phone, out = opened
    c = phone.client()
    c.enter(out["url"], phone.code())
    phone.manager.close("owner")
    assert c.get("/api/me")[0] == 404 and c.raw("GET", "/")[0] == 404
