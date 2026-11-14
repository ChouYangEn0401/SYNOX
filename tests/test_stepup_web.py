"""主機台的驗證器 API（計畫 K5）＋敏感動作的門（SENSITIVE）＋命令列＋doctor＋JS。直接呼叫 WebUI.handle，不開埠。"""

import dataclasses
import json
import os
import shutil
import subprocess

import pytest

from isdtelekit.users.roles import BasicRoles

from synox import guard
from synox.guard import cli as stepup_cli
from synox.guard.origin import Origin
from synox.guard.stepup import SENSITIVE
from synox.guard.testing import Clock, code_for, enroll, use_clock
from synox.vault import Vault

from conftest import OTHER_ID
from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = "synox.example.com"


def web(bot, host="127.0.0.1:8830", who=None):
    ui = bot.app.extras["synox_web"]
    c = Client(ui, host=host)
    c.login(who if who is not None else bot.app.config.owner_id)
    return ui, c


def hub_of(bot):
    return guard.of(bot.app).stepup


def setup_web(bot, c):
    """在網頁上走完設定：begin → confirm（開關預設勾）→ 回 (金鑰, 備用碼, 時鐘)。"""
    clock = Clock()
    use_clock(hub_of(bot), clock)
    status, data = c.post("/api/stepup/begin")
    assert status == 200, data
    secret = data["secret"].replace(" ", "")
    status, done = c.post("/api/stepup/confirm", {"code": code_for(secret, clock), "protect": True})
    assert status == 200 and done["ok"], done
    clock.t += 30
    return secret, done["recovery"], clock


def test_routes_need_login_and_csrf(make_bot, owner):
    bot = make_bot()
    ui = bot.app.extras["synox_web"]
    assert ui.handle("GET", "/api/stepup", {"Host": "127.0.0.1:8830"})[0] == 401
    _ui, c = web(bot)
    for path in ("/api/stepup/begin", "/api/stepup/confirm", "/api/stepup/unlock", "/api/stepup/lock",
                 "/api/stepup/protect", "/api/stepup/recovery", "/api/stepup/disable"):
        status, _h, _b = c.raw("POST", path, b"{}", headers={"X-SYNOX-CSRF": "nope"})
        assert status == 403, path


def test_status_shape_and_local_begin(make_bot, owner):
    bot = make_bot()
    _ui, c = web(bot)
    status, s = c.get("/api/stepup")
    assert status == 200
    assert set(s) == {"enrolled", "protect_danger", "unlocked", "unlock_left_s", "recovery_left", "locked_for_s",
                      "minutes", "can_enroll_here", "why_not"}
    assert s["enrolled"] is False and s["can_enroll_here"] is True and s["minutes"] == 15
    status, d = c.post("/api/stepup/begin")
    assert status == 200 and d["expires_in"] == 600 and d["uri"].startswith("otpauth://totp/")
    assert len(d["secret"].split(" ")) >= 8 and isinstance(d["qr"], list) and set(d["qr"][0]) <= {"0", "1"}


def test_begin_refused_when_not_local(make_bot, owner):
    bot = make_bot()
    _ui, c = web(bot)
    status, _h, body = c.raw("POST", "/api/stepup/begin", b"{}", headers={"X-Forwarded-For": "203.0.113.9"})
    assert status == 403 and b"otpauth" not in body and json.loads(body)["code"] == "not_here"
    _ui, c2 = web(bot, host=PUBLIC)
    status, d = c2.post("/api/stepup/begin")
    assert status == 403 and "secret" not in d
    assert c2.get("/api/stepup")[1]["can_enroll_here"] is False


def test_server_member_from_https_fresh_login(make_bot, owner):
    bot = make_bot(raw={"mode": "server", "web": {"public_url": "https://" + PUBLIC}})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    ui, c = web(bot, host=PUBLIC, who=OTHER_ID)
    status, d = c.post("/api/stepup/begin")
    assert status == 200 and d["secret"]
    with ui.sessions._lock:
        for key, s in list(ui.sessions._items.items()):
            ui.sessions._items[key] = dataclasses.replace(s, created=s.created - 700)
    status, d = c.post("/api/stepup/begin")
    assert status == 403 and "secret" not in d
    _ui, oc = web(bot, host=PUBLIC)                      # 擁有者從對外網址：一律不行
    assert oc.post("/api/stepup/begin")[0] == 403


def test_confirm_then_status_and_recovery_only_once(make_bot, owner):
    bot = make_bot()
    _ui, c = web(bot)
    secret, recovery, clock = setup_web(bot, c)
    assert len(recovery) == 10
    status, s = c.get("/api/stepup")
    assert s["enrolled"] and s["protect_danger"] and s["recovery_left"] == 10 and not s["unlocked"]
    text = json.dumps(s)
    assert not any(r in text for r in recovery) and secret not in text
    status, d = c.post("/api/stepup/unlock", {"code": code_for(secret, clock)})
    assert status == 200 and d["ok"] and d["left_s"] == 900
    clock.t += 30
    status, d = c.post("/api/stepup/recovery", {"code": code_for(secret, clock)})
    assert status == 200 and len(d["recovery"]) == 10 and d["recovery"] != recovery
    status, d = c.post("/api/stepup/unlock", {"code": "000000"})
    assert status == 403 and d["code"] in ("bad", "replay")
    assert c.post("/api/stepup/lock")[1] == {"ok": True, "left_s": 0}


def test_disable_with_recovery_local_only(make_bot, owner):
    bot = make_bot()
    _ui, c = web(bot)
    secret, recovery, clock = setup_web(bot, c)
    status, _h, body = c.raw("POST", "/api/stepup/disable", json.dumps({"code": recovery[0]}).encode(),
                             headers={"X-Forwarded-For": "203.0.113.9"})
    assert status == 403 and json.loads(body)["code"] == "recovery_here"
    status, d = c.post("/api/stepup/disable", {"code": recovery[0]})
    assert status == 200 and d["ok"] and not hub_of(bot).enrolled(owner)


def test_protect_off_needs_unlock(make_bot, owner):
    bot = make_bot()
    _ui, c = web(bot)
    secret, _r, clock = setup_web(bot, c)
    status, d = c.post("/api/stepup/protect", {"on": False})
    assert status == 403 and d["code"] == "need"
    c.post("/api/stepup/unlock", {"code": code_for(secret, clock)})
    assert c.post("/api/stepup/protect", {"on": False}) == (200, {"ok": True, "protect_danger": False})
    assert c.post("/api/stepup/protect", {"on": "yes"})[0] == 400


@pytest.mark.parametrize("path", sorted(SENSITIVE))
def test_sensitive_routes(make_bot, owner, path):
    bot = make_bot(raw={"mode": "server"})
    _ui, c = web(bot)
    status, _h, body = c.raw("POST", path, b"{}")
    assert not (status == 403 and b'"stepup"' in body)                          # 沒設定：照舊
    secret, _r, clock = setup_web(bot, c)
    status, d = c.post(path, {})
    assert status == 403 and d["code"] == "stepup"
    hub = hub_of(bot)
    assert hub.unlock(owner, code_for(secret, clock), origin=Origin("telegram", owner, surface="telegram")).ok
    status, d = c.post(path, {})
    assert status == 403 and d["code"] == "stepup"                              # Telegram 解鎖不會讓網頁過
    clock.t += 30
    c.post("/api/stepup/unlock", {"code": code_for(secret, clock)})
    status, _h, body = c.raw("POST", path, b"{}")
    assert not (status == 403 and b'"stepup"' in body)


def test_sensitive_action_does_not_happen(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    _ui, c = web(bot)
    setup_web(bot, c)
    status, d = c.post("/api/accounts/role", {"id": OTHER_ID, "role": "admin"})
    assert status == 403 and d["code"] == "stepup"
    assert bot.app.users.get(OTHER_ID).role == BasicRoles.MEMBER


def test_cli_setup_status_reset(tmp_path, make_bot):
    bot = make_bot()
    config = bot.app.extras["synox_config"]
    vault = Vault(b"k" * 32, str(tmp_path / "v"))
    clock = Clock()
    out = []
    secret = {}

    def say(line):
        out.append(line)
        if line.startswith("    ") and len(line.strip().replace(" ", "")) == 32:
            secret["s"] = line.strip().replace(" ", "")

    answers = iter(["000000", None, ""])

    def ask(prompt):
        a = next(answers)
        return code_for(secret["s"], clock) if a is None else a
    assert stepup_cli.run("setup", config, vault, ask=ask, out=say, clock=clock) == 0
    joined = "\n".join(out)
    assert "驗證碼不對" in joined and "備用碼" in joined and "危險的動作要先解鎖" in joined
    assert any(ch in joined for ch in "█▀▄")
    out.clear()
    assert stepup_cli.run("status", config, vault, out=out.append, clock=clock) == 0
    assert "已設定" in out[0] and secret["s"] not in "\n".join(out)
    assert stepup_cli.run("reset", config, vault, ask=lambda p: "y", out=out.append, clock=clock) == 0
    out.clear()
    stepup_cli.run("status", config, vault, out=out.append, clock=clock)
    assert out == ["手機驗證器：沒設定"]


def test_doctor_three_lines():
    assert "沒設定" in stepup_cli.doctor_line(None)
    assert stepup_cli.doctor_line({"protect_danger": True}).endswith("已設定，危險的動作要先解鎖")
    assert "沒有開保護" in stepup_cli.doctor_line({"protect_danger": False})


def test_app_page_still_only_nonce_scripts(make_bot):
    from synox.web.server import render_app
    html = render_app("NONCE123")
    assert "SynoxStepUp" in html and 'data-tab="security"' in html
    import re
    for tag in re.findall(r"<(script|style)\b([^>]*)>", html):
        assert 'nonce="NONCE123"' in tag[1], tag


def test_security_js_with_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("這台沒有 node：tests/js/test_security.js 沒跑")
    proc = subprocess.run([node, os.path.join(ROOT, "tests", "js", "test_security.js")], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_first_danger_hint_once(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/note 買牛奶")
    bot.say(owner, "/note_clear")
    texts = bot.texts(owner)
    assert any("多一道手機驗證" in t for t in texts)
    assert "多一道手機驗證" not in bot.last(owner)              # 指令自己的回覆仍是最後一則
    n = len([t for t in texts if "多一道手機驗證" in t])
    bot.say(owner, "/note 再一筆")
    bot.say(owner, "/note_clear")
    assert len([t for t in bot.texts(owner) if "多一道手機驗證" in t]) == n
