"""工具服務的管理員（計畫 WP2、C1、C7、C10–C12；ADR 0026 對接 f）：假 listener、假時鐘、真的執行緒，不開埠。"""

import json
import threading

import pytest

from isdtelekit.users.roles import BasicRoles

from synox.web import apps
from synox.web.apps import AppsError, listen as listen_mod
from synox.web.apps.testing import AppClient, FakeListen

from conftest import OTHER_ID

pytestmark = pytest.mark.usefixtures("no_sockets")


class Clock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t


def timed(manager):
    clock = Clock()
    manager.clock = clock
    manager.audit.clock = clock
    manager.tickets.clock = clock
    return clock


def notes(bot):
    return [t for t in bot.texts(bot.app.config.owner_id) if t.startswith("🧩")]


@pytest.mark.parametrize("raw,ok", [({"web": {"apps": {"enabled": False}}}, False), ({"web": {"enabled": False}}, False),
                                    ({}, True)])
def test_available_by_config(counter, raw, ok):
    _bot, manager = counter(raw=raw)
    assert manager.available()[0] is ok


def test_available_container_and_web_off(counter):
    bot, manager = counter()
    manager.environ = {"SYNOX_IN_CONTAINER": "1"}
    assert manager.available() == (False, "容器版還沒開放工具服務。")
    manager.environ = {"SYNOX_WEB_BIND": "0.0.0.0", "HOST": "0.0.0.0"}
    assert manager.available()[0]
    manager.exists = lambda p: p == "/.dockerenv"
    assert not manager.available()[0]
    manager.exists = lambda p: False
    bot.app.extras["synox_web"].turn_off()
    assert not manager.available()[0]


def test_address_is_always_127_0_0_2(counter, owner):
    bot, manager = counter(raw={"web": {"host": "0.0.0.0", "bind": "0.0.0.0"}})
    manager.environ = {"SYNOX_WEB_BIND": "0.0.0.0"}
    manager.start("counter", by=owner, via="web")
    assert manager.listen.calls == [("127.0.0.2", 8841)]


def test_open_listener_uses_fake_server_class(monkeypatch):
    seen = {}

    class FakeServer:
        def __init__(self, addr, handler):
            seen["addr"], seen["handler"] = addr, handler

        def serve_forever(self):
            seen["served"] = True

    from synox.web import server
    monkeypatch.setattr(server, "_Server", FakeServer)
    site = object()
    lst = listen_mod.open_listener(site, 8899)
    assert seen["addr"] == ("127.0.0.2", 8899) and seen["handler"] is server._Handler
    srv = lst._server
    assert srv.ui is site and srv.daemon_threads is True
    marker = type("H", (), {})
    listen_mod.open_listener(site, 8898, handler=marker)
    assert seen["handler"] is marker


@pytest.mark.parametrize("via,ok", [("web", True), ("telegram", True), ("system", False), ("app", False), ("ai", False),
                                    ("", False), ("remote", False)])
def test_start_via(counter, owner, via, ok):
    _bot, manager = counter()
    if ok:
        manager.start("counter", by=owner, via=via)
        assert manager.running() == ["counter"]
    else:
        with pytest.raises(AppsError) as e:
            manager.start("counter", by=owner, via=via)
        assert e.value.code == "forbidden" and manager.listen.calls == []


def test_not_owner_and_unknown(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.ADMIN)
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=OTHER_ID, via="web")
    assert e.value.code == "forbidden"
    with pytest.raises(AppsError) as e:
        manager.start("money", by=owner, via="web")
    assert e.value.status == 404


def test_effect_mismatch_is_a_problem(counter, owner):
    bot, manager = counter()
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "counter")
    pack.manifest.web["app"]["actions"]["add"] = "danger"
    try:
        assert "counter" in manager.problems() and "counter" not in manager.specs()
        with pytest.raises(AppsError):
            manager.start("counter", by=owner, via="web")
    finally:
        pack.manifest.web["app"]["actions"]["add"] = "write"


def test_ports(counter, owner):
    bot, manager = counter()
    manager.start("counter", by=owner, via="web")
    manager.start("counter", by=owner, via="web")
    assert manager.listen.calls == [("127.0.0.2", 8841)]
    data = json.load(open(manager.apps_path, encoding="utf-8"))
    assert data["ports"] == {"counter": 8841}
    manager.stop("counter", by=owner, via="web")
    manager.start("counter", by=owner, via="web")
    assert manager.listen.calls[-1] == ("127.0.0.2", 8841)
    manager.stop("counter", by=owner, via="web")
    manager.listen.busy = {8841}
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=owner, via="web")
    assert e.value.status == 503 and "8841" in e.value.message
    assert manager.view("counter")["state"] == "error"
    assert json.load(open(manager.apps_path, encoding="utf-8"))["ports"] == {"counter": 8841}
    assert [c[1] for c in manager.listen.calls] == [8841, 8841, 8841]


def test_port_never_reused(counter, owner):
    bot, manager = counter()
    stored = manager._data()
    stored["ports"] = {"gone": 8841}
    manager._save_data(stored)
    manager.start("counter", by=owner, via="web")
    assert manager.listen.calls[-1] == ("127.0.0.2", 8842)


def test_port_range_full(counter, owner):
    _bot, manager = counter(raw={"web": {"apps": {"port_count": 1, "max_running": 1}}})
    stored = manager._data()
    stored["ports"] = {"gone": 8841}
    manager._save_data(stored)
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=owner, via="web")
    assert "port_count" in e.value.message


def test_max_running(counter, owner):
    bot, manager = counter(raw={"web": {"apps": {"max_running": 1}}})
    manager.start("counter", by=owner, via="web")
    manager._states["other"] = manager._states["counter"].__class__("other", status="on")
    manager._states["counter"].status = "off"
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=owner, via="web")
    assert e.value.code == "max_running" and "other" in e.value.message


def test_concurrent_start_and_busy(counter, owner):
    _bot, manager = counter()
    hold = threading.Event()
    manager.listen = FakeListen(hold=hold)
    errors = []

    def go():
        try:
            manager.start("counter", by=owner, via="web")
        except AppsError as e:
            errors.append(e.code)
    t1 = threading.Thread(target=go)
    t1.start()
    manager.listen.entered.wait(5)
    t2 = threading.Thread(target=go)
    t2.start()
    t2.join(5)
    with pytest.raises(AppsError) as e:
        manager.stop("counter", by=owner, via="web")
    assert e.value.code == "busy"
    hold.set()
    t1.join(5)
    assert errors == ["busy"] and len(manager.listen.calls) == 1 and manager.running() == ["counter"]


def test_concurrent_redeem(counter, owner):
    _bot, manager = counter()
    manager.start("counter", by=owner, via="web")
    ticket = manager.issue_ticket("counter", owner, None)
    port = manager.port_of("counter")
    results = []
    threads = [threading.Thread(target=lambda: results.append(manager.redeem_ticket("counter", port, ticket)))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len([r for r in results if r is not None]) == 1


def test_stop_while_close_is_slow_and_stuck(counter, owner):
    _bot, manager = counter()
    block = threading.Event()
    manager.listen = FakeListen(block_close=block)
    manager.start("counter", by=owner, via="web")
    t = threading.Thread(target=lambda: manager.stop("counter", by=owner, via="web"))
    t.start()
    import time
    time.sleep(0.05)
    assert manager._states["counter"].status == "stopping"
    manager.touch("counter")                                      # 不會卡住
    block.set()
    t.join(5)
    assert manager._states["counter"].status == "off"
    manager.listen = FakeListen(close_ok=False)
    manager.start("counter", by=owner, via="web")
    manager.stop("counter", by=owner, via="web")
    assert manager._states["counter"].status == "error" and manager._states["counter"].reason == "stuck"
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=owner, via="web")
    assert e.value.code in ("port", "busy")


def test_stop_invalidates_logins_and_tickets(counter, owner):
    bot, manager = counter()
    manager.start("counter", by=owner, via="web")
    c = AppClient(manager, "counter")
    c.enter(c.open_from_console(owner))
    ticket = c.open_from_console(owner)
    token = c.token
    site = c.site
    manager.stop("counter", by=owner, via="web")
    manager.start("counter", by=owner, via="web")
    assert c.get("/api/me", token=token)[0] == 401
    assert c.post("/api/enter", {"ticket": ticket})[0] == 401
    assert site.sessions.get(token) is None
    events = [r["event"] for r in manager.audit.tail(50)]
    assert "stop" in events


def test_idle_default(counter, owner):
    bot, manager = counter()
    clock = timed(manager)
    manager.start("counter", by=owner, via="web")
    clock.t += 29 * 60
    manager.tick()
    assert not notes(bot)
    clock.t += 60
    manager.tick()
    manager.tick()
    assert len(notes(bot)) == 1 and "再 90 分鐘我會自己關" in notes(bot)[0]
    manager.touch("counter")
    clock.t += 30 * 60
    manager.tick()
    assert len(notes(bot)) == 2
    clock.t += 90 * 60
    manager.tick()
    assert manager.running() == [] and "先關掉了" in notes(bot)[-1]
    rows = manager.audit.tail(20)
    assert any(r["event"] == "auto_stop" and r["reason"] == "idle" for r in rows)
    assert any(r["event"] == "suggest" for r in rows)


@pytest.mark.parametrize("policy,minutes,expect", [
    ({"mode": "auto", "close_min": 30}, [30], ["closed"]),
    ({"mode": "auto", "close_min": 45}, [30, 15], ["suggest", "closed"]),
    ({"mode": "suggest"}, [30, 500], ["suggest_keep", None]),
    ({"mode": "keep", "understood": True}, [30, 1000], [None, None]),
])
def test_policies(counter, owner, policy, minutes, expect):
    bot, manager = counter()
    clock = timed(manager)
    manager.set_policy("counter", policy, by=owner)
    manager.start("counter", by=owner, via="web")
    for m, e in zip(minutes, expect):
        before = len(notes(bot))
        clock.t += m * 60
        manager.tick()
        new = notes(bot)[before:]
        if e is None:
            assert not new and manager.running() == ["counter"]
        elif e == "closed":
            assert new and "先關掉了" in new[-1] and manager.running() == []
        elif e == "suggest_keep":
            assert new and "一直開著" in new[-1]
        else:
            assert new and "再 15 分鐘" in new[-1]


@pytest.mark.parametrize("data", [{"mode": "keep"}, {"mode": "auto", "close_min": 4}, {"mode": "auto", "close_min": 1441},
                                  {"mode": "auto", "close_min": 30.5}, {"mode": "auto", "close_min": "30"},
                                  {"mode": "nope"}, "auto"])
def test_bad_policies(counter, owner, data):
    _bot, manager = counter()
    with pytest.raises(AppsError) as e:
        manager.set_policy("counter", data, by=owner)
    assert e.value.status == 400


def test_blocked_and_member_and_persistence(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    manager.start("counter", by=owner, via="web")
    with pytest.raises(AppsError) as e:
        manager.set_policy("counter", {"mode": "auto", "close_min": 60}, by=OTHER_ID)
    assert e.value.status == 403
    manager.set_policy("counter", {"mode": "blocked"}, by=owner)
    assert manager.running() == []
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=owner, via="web")
    assert e.value.code == "blocked"
    manager.set_policy("counter", {"mode": "keep", "understood": True}, by=owner)
    rows = [r for r in manager.audit.tail(50) if r["event"] == "policy"]
    assert rows and rows[0]["mode"] == "keep"
    fresh = apps.AppManager(bot.app, bot.app.extras["synox_config"], bot.app.extras["synox_web"], listen=FakeListen())
    assert fresh.policy_of("counter")["mode"] == "keep" and fresh.running() == []


def test_no_app_no_surface(counter, owner):
    _bot, manager = counter()
    for name in ("money", "notes"):
        assert name not in manager.specs() and name not in manager.problems()
        assert name not in [a["name"] for a in manager.views(_bot.app.users.get_or_create(owner))["apps"]]
        with pytest.raises(AppsError) as e:
            manager.start(name, by=owner, via="web")
        assert e.value.status == 404
        with pytest.raises(AppsError):
            manager.set_policy(name, {"mode": "blocked"}, by=owner)
        with pytest.raises(AppsError):
            manager.issue_ticket(name, owner, None)
    assert manager.listen.calls == []


def test_runtime_task_only_when_running(counter, owner):
    bot, manager = counter()
    from synox import runtime
    task = runtime.of(bot.app).loop.tasks.get("system.tool_apps")
    assert task is not None and task.next_due is None
    manager.start("counter", by=owner, via="web")
    assert task.next_due is not None
    manager.stop("counter", by=owner, via="web")
    assert task.next_due is None


@pytest.mark.parametrize("how", ["owner", "idle", "reload", "web_off", "spec_gone", "shutdown"])
def test_on_stopped_every_way(counter, owner, how):
    bot, manager = counter()
    seen = []
    manager.on_stopped(lambda name, reason: seen.append((name, reason)))
    clock = timed(manager)
    manager.start("counter", by=owner, via="web")
    ui = bot.app.extras["synox_web"]
    if how == "owner":
        manager.stop("counter", by=owner, via="web")
    elif how == "idle":
        clock.t += 121 * 60
        manager.tick()
    elif how == "reload":
        ui._reload()
    elif how == "web_off":
        ui.turn_off()
    elif how == "spec_gone":
        bot.app.extras["synox_packs"][:] = [p for p in bot.app.extras["synox_packs"] if p.name != "counter"]
        manager.tick()
    else:
        for fn in bot.app.on_stop:
            fn(bot.app)
    assert len(seen) == 1 and seen[0][0] == "counter" and manager.running() == []


def test_state_file_and_views_have_no_address(counter, owner):
    bot, manager = counter()
    state = json.load(open(manager.state_path, encoding="utf-8"))
    assert state["running"] == []
    manager.start("counter", by=owner, via="web")
    state = json.load(open(manager.state_path, encoding="utf-8"))
    assert state["running"][0]["name"] == "counter" and state["running"][0]["port"] == 8841
    views = manager.views(bot.app.users.get_or_create(owner))
    assert "127.0.0.2" not in json.dumps(views) and "url" not in views["apps"][0]
    assert views["apps"][0]["open"] == "/apps/counter/open" and views["can_manage"] is True


def test_resolve(counter):
    _bot, manager = counter()
    for text in ("counter", "COUNTER", "計數器", "🔢 計數器", " 計數器 "):
        assert manager.resolve(text) == "counter", text
    assert manager.resolve("money") is None and manager.resolve("") is None
