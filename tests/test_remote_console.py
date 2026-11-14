"""主機台的手機入口（ADR 0026；計畫 K7）：/api/remote… 的形狀、權限、要先解鎖；JS 的字。不開埠、不開子程序。"""

import os

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID
from remote_helpers import make_phone
from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def console(phone, who):
    c = Client(phone.bot.app.extras["synox_web"])
    c.login(who)
    return c


def test_status_shape_and_open(counter, owner):
    phone = make_phone(counter, owner)
    c = console(phone, owner)
    status, data = c.get("/api/remote")
    assert status == 200 and set(data) == {"available", "code", "why", "enabled", "stepup", "binary", "tools", "open"}
    assert data["tools"]["counter"] == {"title": "🔢 計數器", "declared": True, "allowed": True}
    assert c.post("/api/remote/open", {"name": "counter"})[0] == 400
    status, data = c.post("/api/remote/open", {"name": "counter", "code": "000000"})
    assert status == 409 and data["code"] == "bad_code"
    status, data = c.post("/api/remote/open", {"name": "counter", "code": phone.code()})
    assert status == 200 and data["url"].startswith("https://") and isinstance(data["qr"], list)
    assert c.get("/api/remote")[1]["open"]["name"] == "counter"
    assert c.post("/api/remote/close")[1] == {"ok": True}


@pytest.mark.parametrize("path,body", [("/api/remote/enabled", {"on": False}), ("/api/remote/allow", {"name": "counter", "on": False}),
                                       ("/api/remote/binary/approve", {})])
def test_switches_need_unlock(counter, owner, path, body):
    phone = make_phone(counter, owner)
    c = console(phone, owner)
    status, data = c.post(path, body)
    assert status == 403 and data["code"] == "stepup"
    c.post("/api/stepup/unlock", {"code": phone.code()})
    status, data = c.post(path, body)
    assert status in (200, 409), data


def test_members_are_refused(counter, owner):
    phone = make_phone(counter, owner, raw={"mode": "server"})
    phone.bot.make(OTHER_ID, BasicRoles.MEMBER)
    m = console(phone, OTHER_ID)
    assert m.get("/api/remote")[0] == 403 and m.post("/api/remote/open", {"name": "counter", "code": "1"})[0] == 403


def test_js_texts_and_rules():
    js = open(os.path.join(ROOT, "src", "synox", "web", "static", "apps.js"), encoding="utf-8").read()
    assert "remoteOpen" in js and "remoteMissing" in js
    sec = open(os.path.join(ROOT, "src", "synox", "web", "static", "security.js"), encoding="utf-8").read()
    assert "remoteSwitch" in sec and "binaryCheck" in sec
    # JS 的行為測試在 tests/js/test_apps.js、test_security.js（node；test_app_console.py、test_stepup_web.py 跑）
