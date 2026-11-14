"""手機入口的管理員（ADR 0026；計畫 K7）：開的每個前提、開了之後、時間、關。假時鐘、假 listener、假通道，不開埠、不開子程序。"""

import json
import os

import pytest

from synox import guard
from synox.guard.origin import Origin
from synox.web.remote import RemoteError
from synox.web.remote.testing import FakeTunnel

from remote_helpers import make_phone

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")


def audit_rows(phone):
    return guard.of(phone.bot.app).audit.tail(200)


def refused(phone, code, **kw):
    with pytest.raises(RemoteError) as e:
        phone.open(**kw)
    assert e.value.code == code, e.value.code
    assert any(r["event"] == "remote_refused" and r["code"] == code for r in audit_rows(phone))
    return e.value


def test_open_success(counter, owner):
    phone = make_phone(counter, owner)
    out = phone.open()
    assert out["url"].startswith("https://quiet-river-1234.trycloudflare.com/#k=") and out["minutes"] == 30
    assert phone.listen.calls == [("127.0.0.2", 8861)]
    from synox.guard.http import GuardedHandler
    assert phone.listen.handler is GuardedHandler
    assert phone.tunnel.started == ["http://127.0.0.2:8861"]
    key = out["url"].split("#k=")[1]
    data_dir = phone.bot.app.config.data_dir
    for root, _d, files in os.walk(data_dir):
        for f in files:
            if f.endswith((".json", ".jsonl")):
                assert key not in open(os.path.join(root, f), encoding="utf-8", errors="ignore").read(), f
    assert phone.apps.running() == ["counter"] and phone.manager.link.started_here


@pytest.mark.parametrize("kind", ["ai", "schedule", "unknown", "remote", "system"])
def test_not_human_and_code_not_used(counter, owner, kind):
    phone = make_phone(counter, owner)
    code = phone.code()
    user = phone.bot.app.users.get_or_create(owner)
    with pytest.raises(RemoteError) as e:
        phone.manager.open("counter", user, code, origin=Origin(kind, owner, surface=kind))
    assert e.value.code == "not_human"
    assert phone.manager.open("counter", user, code, origin=phone.tg)["url"]      # 那組碼沒被消耗


@pytest.mark.parametrize("case", ["disabled", "container", "stepup_unset", "bad_code", "no_binary", "binary_changed",
                                  "tool_not_allowed", "not_remote_tool", "busy", "port"])
def test_each_precondition(counter, owner, case):
    raw = {"web": {"remote": {"enabled": False}}} if case == "disabled" else None
    phone = make_phone(counter, owner, raw=raw, allow=case != "tool_not_allowed", enrolled=case != "stepup_unset")
    if case == "stepup_unset":
        phone.secret = "JBSWY3DPEHPK3PXP"
    if case == "container":
        phone.manager.environ = {"SYNOX_IN_CONTAINER": "1"}
    if case in ("no_binary", "binary_changed"):
        phone.manager.binary_check = lambda: case
    if case == "busy":
        phone.open()
    if case == "port":
        phone.listen.busy = {8861}
    if case == "bad_code":
        user = phone.bot.app.users.get_or_create(owner)
        with pytest.raises(RemoteError) as e:
            phone.manager.open("counter", user, "000000" if phone.code() != "000000" else "111111", origin=phone.tg)
        assert e.value.code == "bad_code"
        return
    if case == "not_remote_tool":
        pack = next(p for p in phone.bot.app.extras["synox_packs"] if p.name == "counter")
        pack.manifest.web["app"]["remote"] = False
        try:
            refused(phone, case)
        finally:
            pack.manifest.web["app"]["remote"] = True
        return
    refused(phone, case)
    if case == "port":
        assert phone.apps.running() == []


def test_not_owner(counter, owner):
    from isdtelekit.users.roles import BasicRoles
    from conftest import OTHER_ID
    phone = make_phone(counter, owner, raw={"mode": "server"})
    phone.bot.make(OTHER_ID, BasicRoles.ADMIN)
    with pytest.raises(RemoteError) as e:
        phone.manager.open("counter", phone.bot.app.users.get_or_create(OTHER_ID), phone.code(),
                           origin=Origin("telegram", OTHER_ID, surface="telegram"))
    assert e.value.code == "not_owner"


def test_tunnel_fails_cleans_up(counter, owner):
    phone = make_phone(counter, owner, tunnel=FakeTunnel(fail="timeout"))
    refused(phone, "tunnel_failed")
    assert phone.apps.running() == [] and phone.listen.listeners[0].closed == 1
    assert phone.manager.link is None and phone.tunnel.stopped == 1


def test_tunnel_bad_url(counter, owner):
    phone = make_phone(counter, owner, tunnel=FakeTunnel(url="https://evil.example.com"))
    refused(phone, "tunnel_failed")


def test_already_running_service_stays_on(counter, owner):
    phone = make_phone(counter, owner)
    phone.apps.start("counter", by=owner, via="web")
    phone.open()
    assert not phone.manager.link.started_here
    phone.manager.close("owner")
    assert phone.apps.running() == ["counter"]


def test_minutes_clamped_and_time(counter, owner):
    phone = make_phone(counter, owner)
    out = phone.open(minutes=999)
    assert out["minutes"] == 120
    phone.manager.close("owner")
    phone.open()
    phone.clock.t += 26 * 60
    link = phone.manager.link
    link.state = "entered"
    link.last_activity = phone.clock.t
    phone.manager.tick()
    assert any("再 5 分鐘" in t for t in phone.bot.texts(owner))
    n = len([t for t in phone.bot.texts(owner) if "再 5 分鐘" in t])
    phone.manager.tick()
    assert len([t for t in phone.bot.texts(owner) if "再 5 分鐘" in t]) == n
    phone.clock.t += 5 * 60
    phone.manager.tick()
    assert link.state == "closed" and "時間到了" in phone.bot.last(owner)


def test_idle_no_entry_and_tunnel_down(counter, owner):
    phone = make_phone(counter, owner)
    phone.open()
    phone.clock.t += 301
    phone.manager.tick()
    assert phone.manager.link.state == "closed" and "沒有人進門" in phone.bot.last(owner)
    phone.open()
    link = phone.manager.link
    link.state, link.last_activity = "entered", phone.clock.t
    phone.clock.t += 9 * 60
    phone.manager.tick()
    assert link.state == "entered"
    phone.clock.t += 61
    phone.manager.tick()
    assert link.state == "closed" and "一陣子沒有用" in phone.bot.last(owner)
    phone.tunnel.stopped = 0
    phone.tunnel.dies_after = phone.tunnel.checks
    phone.open()
    phone.manager.tick()
    assert phone.manager.link.state == "closed" and "通道斷了" in phone.bot.last(owner)


@pytest.mark.parametrize("how", ["app_close", "service_stopped", "stepup_disable", "web_off", "shutdown"])
def test_close_hooks(counter, owner, how):
    phone = make_phone(counter, owner)
    phone.open()
    link = phone.manager.link
    if how == "app_close":
        phone.bot.say(owner, "/app_close counter")
    elif how == "service_stopped":
        phone.apps.stop("counter", by=owner, via="web")
    elif how == "stepup_disable":
        g = guard.of(phone.bot.app)
        assert g.stepup.disable(owner, phone.code(), origin=Origin("web", owner, surface="web:x")).ok
    elif how == "web_off":
        phone.bot.app.extras["synox_web"].turn_off()
    else:
        for fn in phone.bot.app.on_stop:
            fn(phone.bot.app)
    assert link.state == "closed" and phone.tunnel.stopped == 1 and phone.listen.listeners[0].closed == 1
    assert phone.apps.running() == []
    assert any(r["event"] == "remote_close" for r in audit_rows(phone))


def test_runtime_task_only_when_open(counter, owner):
    phone = make_phone(counter, owner)
    from synox import runtime
    task = runtime.of(phone.bot.app).loop.tasks.get("system.remote")
    assert task is not None and task.next_due is None
    phone.open()
    assert task.next_due is not None
    phone.manager.close("owner")
    assert task.next_due is None
