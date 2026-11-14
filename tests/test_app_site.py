"""工具服務的站（計畫 C4–C6.1、C8、C11；ADR 0026 對接 d、e）：AppClient 直接呼叫 site.handle，不開埠。"""

import json
import logging
import os

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.guard.origin import Origin, using
from synox.web.apps.testing import AppClient

from conftest import OTHER_ID

pytestmark = pytest.mark.usefixtures("no_sockets")
CSP_PART = "worker-src 'none'"


def counter_pack():
    import sys
    return sys.modules["synox_pack_counter"]


@pytest.fixture
def on(counter, owner):
    bot, manager = counter()
    manager.start("counter", by=owner, via="web")
    client = AppClient(manager, "counter")
    return bot, manager, client


def entered(on, owner):
    bot, manager, client = on
    client.enter(client.open_from_console(owner))
    return bot, manager, client


def all_headers_ok(headers):
    h = dict(headers)
    assert "Set-Cookie" not in h and not any(k.lower().startswith("access-control-") for k in h)
    assert CSP_PART in h["Content-Security-Policy"] and h["X-Frame-Options"] == "DENY"
    assert h["Cross-Origin-Opener-Policy"] == "same-origin" and h["Cross-Origin-Resource-Policy"] == "same-origin"


@pytest.mark.parametrize("host", ["127.0.0.1:{p}", "localhost:{p}", "127.0.0.2:1", None])
def test_host_must_be_exact(on, host):
    bot, manager, client = on
    port = manager.port_of("counter")
    status, headers, body = client.raw("GET", "/", headers={"Host": host.format(p=port) if host else None})
    assert status == 403 and "計數" not in body.decode("utf-8", "ignore")
    all_headers_ok(headers)


@pytest.mark.parametrize("name,value", [("X-Forwarded-For", "1.2.3.4"), ("X-Forwarded-Host", "x"),
                                        ("Forwarded", "for=1"), ("Via", "1.1 x"), ("Service-Worker", "script")])
def test_proxy_and_worker_refused(on, name, value):
    _bot, _m, client = on
    assert client.raw("GET", "/app.js", headers={name: value})[0] == 403


def test_no_cookie_at_all(on, owner):
    bot, manager, client = on
    ui = bot.app.extras["synox_web"]
    sid, _ = ui.sessions.create(owner)
    for method, path in (("GET", "/api/me"), ("GET", "/api/read/state"), ("POST", "/api/do/add")):
        status, headers, _b = client.raw(method, path, headers={"Cookie": f"synox_session={sid}"},
                                         body=b'{"values":{"n":"1"}}' if method == "POST" else b"")
        assert status == 401
        all_headers_ok(headers)
    for path in ("/", "/app.js", "/_synox/kit.js", "/nope", "/api/zzz"):
        all_headers_ok(client.raw("GET", path)[1])


def test_entry_and_ticket_rules(on, owner):
    bot, manager, client = on
    status, headers, body = client.raw("GET", "/")
    assert status == 200 and b"/_synox/kit.js" in body and dict(headers).get("Clear-Site-Data") == '"storage"'
    assert "Clear-Site-Data" not in dict(client.raw("GET", "/")[1])
    ticket = client.open_from_console(owner)
    me = client.enter(ticket)
    assert me["app"]["name"] == "counter" and client.token
    assert client.post("/api/enter", {"ticket": ticket})[0] == 401
    assert client.post("/api/enter", {"ticket": "x" * 43})[0] == 401
    port = manager.port_of("counter")
    other = manager.tickets.issue("counter", port + 1, owner, None)
    assert client.post("/api/enter", {"ticket": other})[0] == 401
    late = client.open_from_console(owner)
    manager.tickets.clock = lambda: __import__("time").time() + 31
    assert client.post("/api/enter", {"ticket": late})[0] == 401
    manager.tickets.clock = __import__("time").time
    t2 = client.open_from_console(owner)
    bot.app.extras["synox_web"].sessions.drop(client.console_sid)          # 發票之後主機台登出
    assert client.post("/api/enter", {"ticket": t2})[0] == 401


def test_member_who_cannot_see_the_tool(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    from conftest import trust_core, APP_PACKS
    manager.start("counter", by=owner, via="web")
    bot.make(OTHER_ID, BasicRoles.GUEST)
    c = AppClient(manager, "counter")
    assert c.post("/api/enter", {"ticket": c.open_from_console(OTHER_ID)})[0] == 401


def test_login_is_checked_every_time(on, owner):
    bot, manager, client = entered(on, owner)
    assert client.get("/api/me")[0] == 200
    site = client.site
    session = site.sessions.get(client.token)
    session.expires = 0
    assert client.get("/api/me")[0] == 401 and site.sessions.get(client.token) is None
    client.enter(client.open_from_console(owner))
    bot.app.extras["synox_web"].sessions.drop(client.console_sid)
    assert client.get("/api/me")[0] == 401
    client.enter(client.open_from_console(owner))
    assert client.post("/api/leave")[0] == 200 and client.get("/api/me")[0] == 401
    tokens = []
    for _ in range(6):
        client.enter(client.open_from_console(owner))
        tokens.append(client.token)
    assert client.get("/api/me", token=tokens[0])[0] == 401 and client.get("/api/me", token=tokens[-1])[0] == 200


def test_role_change_takes_effect_on_next_request(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    from conftest import APP_PACKS, trust_core
    manager.start("counter", by=owner, via="web")
    c = AppClient(manager, "counter")
    status, _d = c.post("/api/enter", {"ticket": c.open_from_console(OTHER_ID)})
    if status == 200:
        c.token = _d["token"]
        assert c.get("/api/me")[0] == 200
        bot.app.users.set_role(OTHER_ID, BasicRoles.GUEST, actor_id=owner)
        assert c.get("/api/me")[0] == 401


@pytest.mark.parametrize("headers,status", [
    ({"Sec-Fetch-Site": "same-site"}, 403), ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Origin": "http://127.0.0.1:8830"}, 403), ({"Origin": "null"}, 403),
    ({"Origin": "null", "Sec-Fetch-Site": "same-origin"}, 200), ({"Sec-Fetch-Site": "same-origin"}, 200),
])
def test_origin_rules(on, owner, headers, status):
    _bot, manager, client = entered(on, owner)
    assert client.get("/api/me", headers=headers)[0] == status
    if headers.get("Origin") == "http://127.0.0.1:8830":
        assert client.get("/api/me", headers={"Origin": f"http://{client.site.host_header}"})[0] == 200


def test_post_needs_json_and_options_is_405(on, owner):
    _bot, _m, client = entered(on, owner)
    assert client.raw("POST", "/api/do/add", headers={"Content-Type": "text/plain"}, body=b'{"values":{}}')[0] == 400
    status, headers, _b = client.raw("OPTIONS", "/api/me")
    assert status == 405
    all_headers_ok(headers)


def test_clear_site_data_again_after_reopen(on, owner):
    _bot, manager, client = on
    assert "Clear-Site-Data" in dict(client.raw("GET", "/")[1])
    manager.stop("counter", by=owner, via="web")
    manager.start("counter", by=owner, via="web")
    assert "Clear-Site-Data" in dict(client.raw("GET", "/")[1])


@pytest.mark.parametrize("path", ["/../pack.py", "/%2e%2e/pack.py", "/app/../../config.json", "/pack.json",
                                  "/pack.py", "/app/app.js"])
def test_static_paths(on, path):
    _bot, _m, client = on
    assert client.raw("GET", path)[0] == 404


def test_static_bytes(on):
    _bot, _m, client = on
    status, headers, body = client.raw("GET", "/app.js")
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "app_pack", "counter", "app")
    assert status == 200 and body == open(os.path.join(folder, "app.js"), "rb").read()
    assert dict(headers)["Content-Type"].startswith("text/javascript")
    status, _h, kit = client.raw("GET", "/_synox/kit.js")
    assert status == 200 and b"http://127.0.0.1:8830/#tools" in kit and b"{{CONSOLE_URL}}" not in kit


def test_tampered_file_refuses_to_start(counter, owner, tmp_path):
    bot, manager = counter()
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "counter")
    pack.locked_files = {f: "0" * 64 for f in pack.manifest.web["app"]["files"]}
    from synox.web.apps import AppsError
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=owner, via="web")
    assert e.value.code == "tampered" and "app/" in e.value.message


def test_read_and_action_match_typing(on, owner):
    bot, _m, client = entered(on, owner)
    assert client.read("state") == (200, {"ok": True, "data": {"n": 0}})
    assert client.do("add", {"n": "3"}) == (200, {"ok": True, "data": {"n": 3}})
    bot.say(owner, "/counter 3")
    assert bot.last(owner) == "現在是 6"
    assert client.read("state")[1]["data"] == {"n": 6}
    assert client.read("nope")[0] == 404


@pytest.mark.parametrize("values,needle", [({"zzz": "1"}, "不認得"), ({"n": 3}, "要是文字"), ({"n": "1" * 2001}, "太長"),
                                           ({"n": "a\x00"}, "空字元")])
def test_action_bad_values(on, owner, values, needle):
    _bot, _m, client = entered(on, owner)
    status, data = client.do("add", values)
    assert status == 400 and data["code"] == "invalid" and needle in data["error"]


def test_action_message_same_as_telegram(on, owner):
    bot, _m, client = entered(on, owner)
    status, data = client.do("add", {"n": "abc"})
    bot.say(owner, "/counter abc")
    assert status == 400 and data["fields"]["n"] in bot.last(owner)
    status, data = client.do("add", {})
    assert status == 400 and data["fields"] == {"n": "這一欄一定要填"}


def test_danger_needs_confirmed_true(on, owner):
    _bot, _m, client = entered(on, owner)
    client.do("add", {"n": "5"})
    before = counter_pack().CALLS["reset"]
    for confirmed in (False, "true", 1):
        status, data = client.do("reset", {}, confirmed=confirmed)
        assert status == 409 and data["confirm"] == {"text": "把數字歸零？", "button": "確定"}
    assert counter_pack().CALLS["reset"] == before and client.read("state")[1]["data"]["n"] == 5
    assert client.do("reset", {}, confirmed=True)[0] == 200 and client.read("state")[1]["data"]["n"] == 0


def test_tool_errors(on, owner, caplog):
    _bot, manager, client = entered(on, owner)
    assert client.do("poke", {"how": "refuse"}) == (409, {"ok": False, "code": "refused", "error": "沒有這筆"})
    with caplog.at_level(logging.DEBUG):
        status, data = client.do("poke", {"how": "boom"})
    assert status == 500 and data["error"] == "出錯了：ValueError"
    assert "秘密字串" not in caplog.text and "ValueError" in caplog.text and "pack.py:" in caplog.text
    assert "秘密字串" not in open(manager.audit.path, encoding="utf-8").read()


def test_action_permission(on, owner):
    bot, _m, client = entered(on, owner)
    from isdtelekit.core.registry import Decision
    called = []
    orig = bot.app.registry.authorize

    def authorize(user, node, via, chat_id=None):
        called.append(node.path)
        return Decision(False, "role") if node.path == "counter.add" else orig(user, node, via, chat_id)
    bot.app.registry.authorize = authorize
    status, data = client.do("add", {"n": "1"})
    assert status == 403 and data["code"] == "forbidden" and "counter.add" in called
    assert client.read("state")[1]["data"]["n"] == 0


def test_me_shape(on, owner):
    _bot, _m, client = entered(on, owner)
    status, me = client.get("/api/me")
    assert status == 200 and "csrf" not in me and "token" not in json.dumps(me)
    assert set(me) >= {"ok", "user", "app", "reads", "actions", "exports", "console_url", "policy", "alive_every_s",
                       "remote"}
    assert me["actions"]["add"]["fields"][0]["name"] == "n" and me["actions"]["reset"]["effect"] == "danger"
    assert me["exports"]["state_csv"] == {"available": True, "reason": ""} and me["remote"] is False
    assert me["policy"]["text"] == "120 分鐘沒用就關，30 分鐘先提醒"


def test_close_service(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    manager.start("counter", by=owner, via="web")
    c = AppClient(manager, "counter")
    c.enter(c.open_from_console(owner))
    assert c.post("/api/close-service")[0] == 200
    bot.app.tasks.wait(5)
    assert manager.running() == []


def test_export_personal(on, owner):
    _bot, _m, client = entered(on, owner)
    status, _h, body = client.export("state_csv")
    data = json.loads(body)
    assert status == 409 and data["confirm"]["text"].startswith("匯出的檔案沒有加密")
    status, headers, body = client.export("state_csv", confirmed=True)
    assert status == 200 and dict(headers)["Content-Disposition"] == 'attachment; filename="counter.csv"'
    assert body.startswith(b"\xef\xbb\xbfn\r\n0")
    all_headers_ok(headers)
    assert client.export("state_csv", token="nope", confirmed=True)[0] == 401
    assert client.export("state_csv", confirmed=True, headers={"Sec-Fetch-Site": "same-site"})[0] == 403
    assert client.export("state_csv", confirmed=True,
                         headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})[0] == 200


def test_export_server_is_refused_without_calling(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    manager.start("counter", by=owner, via="web")
    c = AppClient(manager, "counter")
    c.enter(c.open_from_console(owner))
    before = counter_pack().CALLS["export"]
    for confirmed in (False, True):
        status, _h, body = c.export("state_csv", confirmed=confirmed)
        assert status == 403 and json.loads(body)["code"] == "export_encrypted_only"
    assert counter_pack().CALLS["export"] == before


def test_export_bad_download(on, owner):
    from synox.packs import kit
    _bot, _m, client = entered(on, owner)
    pack = client.site.spec.pack
    pack.app_exports["state_csv"] = lambda u, p: "not a download"
    assert client.export("state_csv", confirmed=True)[0] == 500
    pack.app_exports["state_csv"] = lambda u, p: kit.Download("x.zip", "application/zip", b"x")
    assert client.export("state_csv", confirmed=True)[0] == 500
    pack.app_exports["state_csv"] = lambda u, p: kit.Download("../中文 報表", "text/csv; charset=utf-8", b"x")
    status, headers, _b = client.export("state_csv", confirmed=True)
    assert status == 200 and dict(headers)["Content-Disposition"] == 'attachment; filename="_____.csv"'


def test_in_use_definition(on, owner):
    _bot, manager, client = entered(on, owner)
    st = manager._states["counter"]
    st.last_used = 1.0
    for _ in range(100):
        client.raw("GET", "/")
        client.raw("GET", "/app.js")
        client.raw("GET", "/_synox/kit.js")
    assert st.last_used == 1.0
    client.read("state")
    assert st.last_used > 1.0
    session = client.site.sessions.get(client.token)
    session.last_alive = 0
    st.last_used = 1.0
    assert client.post("/api/alive")[0] == 200 and st.last_used > 1.0
    st.last_used = 1.0
    assert client.post("/api/alive")[0] == 200 and st.last_used == 1.0          # 60 秒內第二次：200 但不算
    session.last_alive -= 61
    client.post("/api/alive")
    assert st.last_used > 1.0
    st.last_used = 1.0
    assert client.post("/api/alive", token="nope")[0] == 401 and st.last_used == 1.0
    lines = open(manager.audit.path, encoding="utf-8").read()
    assert '"event":"alive"' not in lines


def test_audit_lines(on, owner):
    _bot, manager, client = entered(on, owner)
    client.do("add", {"n": "777123"})
    client.do("add", {"n": "x"})
    client.export("state_csv", confirmed=True)
    client.raw("GET", "/", headers={"Host": "127.0.0.1:1"})
    manager.audit.write("stop", "counter", reason="bad reason with words")
    raw = open(manager.audit.path, encoding="utf-8").read()
    rows = [json.loads(line) for line in raw.splitlines()]
    from synox.web.apps.audit import FIELDS
    assert all(set(r) == set(FIELDS) for r in rows)
    events = [r["event"] for r in rows]
    for e in ("start", "enter", "action", "export", "denied"):
        assert e in events, e
    assert "777123" not in raw and client.token not in raw and rows[-1]["reason"] == "other"


def test_remote_origin(on, owner):
    """對接 d、e：外面包 remote 的來源直接呼叫 site.handle。"""
    _bot, manager, client = entered(on, owner)
    remote = Origin("remote", owner, surface="remote:x")
    with using(remote):
        assert client.get("/api/me")[1]["remote"] is True
        assert client.do("add", {"n": "2"})[0] == 200
        before = counter_pack().CALLS["reset"]
        status, data = client.do("reset", {}, confirmed=True)
        assert status == 403 and data["code"] == "remote_no_danger" and counter_pack().CALLS["reset"] == before
        exp = counter_pack().CALLS["export"]
        status, _h, body = client.export("state_csv", confirmed=True)
        assert status == 403 and json.loads(body)["code"] == "remote_no_export" and counter_pack().CALLS["export"] == exp
    rows = [json.loads(x) for x in open(manager.audit.path, encoding="utf-8").read().splitlines()]
    assert any(r["event"] == "action" and r["via"] == "remote" and r["ok"] for r in rows)
    assert client.get("/api/me")[1]["remote"] is False


def test_parent_alive_drives_login(on, owner):
    """上一層的 alive() 變 False → 下一個請求 401（對接 d）。"""
    _bot, manager, client = on

    class Parent:
        surface = "remote:p"
        ok = True

        def alive(self):
            return self.ok
    parent = Parent()
    ticket = manager.issue_ticket("counter", owner, parent)
    client.enter(ticket)
    assert client.get("/api/me")[0] == 200
    parent.ok = False
    assert client.get("/api/me")[0] == 401


def test_handler_origin_is_web(on, owner):
    _bot, _m, client = entered(on, owner)
    seen = []
    pack = client.site.spec.pack
    from synox.guard import origin
    pack.app_reads["state"] = lambda u, p: seen.append(origin.current()) or {}
    client.read("state")
    assert seen[-1].kind == "web" and seen[-1].surface.startswith("web:")
