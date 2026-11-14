"""工具服務的主機台這一側（計畫 C7、WP4）：/api/apps… 與「打開」的交接。tests/test_web.py 的假瀏覽器＋假 listener，不開埠。"""

import os
import re
import shutil
import subprocess

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.web.apps.testing import AppClient

from conftest import OTHER_ID
from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def console(bot, who):
    c = Client(bot.app.extras["synox_web"])
    c.login(who)
    return c


def form_post(c, path, fields, headers=None):
    from urllib.parse import urlencode
    h = {"Content-Type": "application/x-www-form-urlencoded", "Origin": f"http://{c.host}",
         "Sec-Fetch-Site": "same-origin", **(headers or {})}
    return c.raw("POST", path, urlencode(fields).encode(), headers=h)


def test_member_permissions_and_list(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = console(bot, OTHER_ID)
    status, data = m.get("/api/apps")
    assert status == 200 and data["can_manage"] is False
    assert [a["name"] for a in data["apps"]] == ["counter"] and "policy" in data["apps"][0]
    for path, body in (("/api/apps/counter/start", {}), ("/api/apps/counter/stop", {}),
                       ("/api/apps/counter/policy", {"mode": "suggest"}), ("/api/apps/stop-all", {})):
        assert m.post(path, body)[0] == 403, path
    assert m.get("/api/apps/log")[0] == 403
    bot.make(777, BasicRoles.GUEST)
    g = console(bot, 777)
    assert g.get("/api/apps")[1]["apps"] == []


def test_owner_routes(counter, owner):
    bot, manager = counter()
    c = console(bot, owner)
    status, data = c.get("/api/apps")
    assert status == 200 and data["available"] and data["can_manage"] and data["explained"] is False
    assert set(data["apps"][0]) >= {"name", "title", "app_title", "state", "open", "port", "since", "last_used", "idle_min",
                                    "suggest_close", "auto_close_in_min", "error", "policy", "actions", "exports",
                                    "problem"}
    assert data["apps"][0]["actions"] == {"write": 2, "danger": 1}
    status, data = c.post("/api/apps/counter/start", {"explained": True})
    assert status == 200 and data["app"]["state"] == "on" and data["app"]["open"] == "/apps/counter/open"
    assert c.get("/api/apps")[1]["explained"] is True
    assert c.post("/api/apps/counter/keep")[0] == 200
    for body, ok in (({"mode": "auto", "close_min": 45}, 200), ({"mode": "suggest"}, 200), ({"mode": "keep"}, 400),
                     ({"mode": "keep", "understood": True}, 200), ({"mode": "nope"}, 400), ({"mode": "blocked"}, 200)):
        assert c.post("/api/apps/counter/policy", body)[0] == ok, body
    assert manager.running() == []
    status, data = c.post("/api/apps/counter/start")
    assert status == 409 and data["code"] == "blocked"
    c.post("/api/apps/counter/policy", {"mode": "suggest"})
    assert c.post("/api/apps/counter/start")[0] == 200
    assert c.post("/api/apps/stop-all")[1] == {"ok": True, "stopped": ["counter"]}
    events = c.get("/api/apps/log?limit=500")[1]["events"]
    assert 0 < len(events) <= 200 and events[0]["event"] in ("stop", "auto_stop")
    assert c.post("/api/apps/zzz/start")[0] == 404
    assert c.raw("POST", "/api/apps/counter/start", b"{}", headers={"X-SYNOX-CSRF": "bad"})[0] == 403


def test_start_errors(counter, owner):
    bot, manager = counter(raw={"web": {"apps": {"enabled": False}}})
    c = console(bot, owner)
    assert c.post("/api/apps/counter/start")[1]["code"] == "unavailable"
    bot2, m2 = counter()
    m2.listen.busy = {8841}
    c2 = console(bot2, owner)
    status, data = c2.post("/api/apps/counter/start")
    assert status == 503 and data["code"] == "port"


def test_tools_api_has_app_flag(counter, owner):
    bot, _m = counter()
    c = console(bot, owner)
    tools = c.get("/api/tools")[1]
    rows = {t["name"]: t for t in tools.get("packs", tools.get("tools", []))} if isinstance(tools, dict) else {}
    flat = rows or {t["name"]: t for t in tools}
    assert flat["counter"]["app"] is True and flat["money"]["app"] is False


def test_handoff(counter, owner):
    bot, manager = counter()
    c = console(bot, owner)
    csrf = c.csrf
    ui = bot.app.extras["synox_web"]
    # 沒登入
    assert ui.handle("POST", "/apps/counter/open", {"Host": c.host}, b"csrf=x")[0] == 401
    # 服務關著：白話頁、沒有發票、沒有開起來
    status, headers, body = form_post(c, "/apps/counter/open", {"csrf": csrf})
    assert status == 200 and "沒有開".encode() in body and manager.running() == [] and manager.tickets.count("counter") == 0
    manager.start("counter", by=owner, via="web")
    assert form_post(c, "/apps/counter/open", {})[0] == 403
    assert form_post(c, "/apps/counter/open", {"csrf": "bad"})[0] == 403
    assert form_post(c, "/apps/counter/open", {"csrf": csrf}, {"Origin": "http://evil.example"})[0] == 403
    for site in ("cross-site", "same-site"):
        assert form_post(c, "/apps/counter/open", {"csrf": csrf}, {"Sec-Fetch-Site": site})[0] == 403
    status, headers, _b = form_post(c, "/apps/counter/open", {"csrf": csrf}, {"Origin": "null"})
    assert status == 303
    h = dict(headers)
    assert h["Location"].startswith(f"http://127.0.0.2:{manager.port_of('counter')}/#t=")
    assert h["Referrer-Policy"] == "no-referrer" and h["Cache-Control"] == "no-store"
    ticket = h["Location"].split("#t=", 1)[1]
    app = AppClient(manager, "counter")
    assert app.enter(ticket)["app"]["name"] == "counter"
    assert app.post("/api/enter", {"ticket": ticket})[0] == 401
    tickets = [dict(form_post(c, "/apps/counter/open", {"csrf": csrf})[1])["Location"].split("#t=")[1] for _ in range(21)]
    assert AppClient(manager, "counter").post("/api/enter", {"ticket": tickets[0]})[0] == 401
    assert AppClient(manager, "counter").post("/api/enter", {"ticket": tickets[-1]})[0] == 200
    raw = open(manager.audit.path, encoding="utf-8").read()
    assert '"handoff"' in raw and ticket not in raw
    assert c.raw("GET", "/apps/counter/open")[0] in (404, 405)


def test_handoff_member_who_cannot_see(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    manager.start("counter", by=owner, via="web")
    bot.make(777, BasicRoles.GUEST)
    g = console(bot, 777)
    status, _h, body = form_post(g, "/apps/counter/open", {"csrf": g.csrf})
    assert status == 200 and "沒有開".encode() in body


def test_apps_js_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_apps.js 沒跑")
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_apps.js")], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_console_page_still_nonce_only():
    from synox.web.server import render_app
    html = render_app("N0NCE")
    assert "SynoxApps" in html and 'id="apps-side"' in html
    for attrs in re.findall(r"<(?:script|style)\b([^>]*)>", html):
        assert 'nonce="N0NCE"' in attrs
