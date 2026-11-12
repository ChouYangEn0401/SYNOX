# -*- coding: utf-8 -*-
"""網頁工具頁的工具健康（docs/tool-health.md）：每張指令卡的狀態徽章與原因、擁有者的「重新檢查」「解除隔離」
（POST /api/tools/health：CSRF、只有擁有者）；重新檢查不叫 AI；別人的 scope=user 紀錄不給。用 WebUI.route()，不開 HTTP 伺服器。"""
import json
import os

from conftest import OTHER_ID, OWNER_ID
from test_health_wiring import _ai, _bot, _break

from synox import health
from synox.health import BROKEN, HEALTHY, QUARANTINED

HOST = {"host": "127.0.0.1:8830"}


def _web(bot):
    from synox.web.server import WebUI
    return WebUI(bot.app, bot.app.config, bot.app.extras.get("vault"))


def _session(ui, tg_id):
    _sid, session = ui.sessions.create(tg_id)
    return session


def _api(ui, session, method, path, body=None):
    headers = dict(HOST)
    if method != "GET":
        headers["x-synox-csrf"] = session.csrf
    status, _h, raw = ui.route(method, path, headers, json.dumps(body or {}).encode("utf-8"), session)
    return status, json.loads(raw.decode("utf-8"))


def _card(data, path):
    pack = next(p for p in data["packs"] if p["name"] == "demo")
    return pack, next(c for c in pack["commands"] if c["path"] == path)


def test_tool_page_shows_state_and_owner_buttons(make_bot, tmp_path):
    bot, folder, _clock = _bot(make_bot, tmp_path, None)
    entry = _break(bot, folder)
    ui = _web(bot)
    owner = _session(ui, OWNER_ID)
    status, data = _api(ui, owner, "GET", "/api/tools")
    pack, cmd = _card(data, "demo.price")
    mark = cmd["health"][0]
    assert status == 200 and pack["health_admin"] is True
    assert mark["state"] == BROKEN and mark["label"] == "暫停（冷卻中）" and mark["code"] == "upstream_unavailable"
    assert mark["reason"].startswith("資料來源壞了 key=***") and mark["next_check"] and "diag" in mark
    assert "health" not in _card(data, "demo.ping")[1]                         # 正常的不帶

    bot.app.users.get_or_create(OTHER_ID)
    other = _session(ui, OTHER_ID)
    for action in ("release", "recheck"):                                       # 非擁有者不能按
        status, _data = _api(ui, other, "POST", "/api/tools/health", {"key": "demo.price", "action": action})
        assert status == 403
    assert entry.state == BROKEN
    status, _data = _api(ui, owner, "POST", "/api/tools/health", {"key": "demo.price"})
    assert status == 404
    status, _data = _api(ui, owner, "POST", "/api/tools/health", {"key": "nope.tool", "action": "release"})
    assert status == 404
    status, data = _api(ui, owner, "POST", "/api/tools/health", {"key": "demo.price", "action": "recheck"})
    assert status == 200 and data["queued"] and bot.app.tasks.wait(10)
    assert entry.state == HEALTHY and len(_ai(bot).calls) == 0                # 自我檢查過了；沒有叫 AI
    entry.state = QUARANTINED
    status, _data = _api(ui, owner, "POST", "/api/tools/health", {"key": "demo.price", "action": "recheck"})
    assert status == 409                                                        # 隔離中：要先解除
    status, data = _api(ui, owner, "POST", "/api/tools/health", {"key": "demo.price", "action": "release"})
    assert status == 200 and data["state"] == HEALTHY
    status, _h, _raw = ui.route("POST", "/api/tools/health", dict(HOST), b"{}", owner)
    assert status == 403                                                        # 沒有 CSRF header：擋


def test_other_peoples_records_are_not_shown(make_bot, tmp_path):
    bot, _folder, _clock = _bot(make_bot, tmp_path, None)
    reg = health.of(bot.app)
    reg.record_failure("demo.price", health.failures.normalize(
        {"ok": False, "error": "你的 token 過期了", "code": "auth_expired"}), pack="demo", user=OWNER_ID)
    ui = _web(bot)
    bot.app.users.get_or_create(OTHER_ID)
    _status, mine = _api(ui, _session(ui, OWNER_ID), "GET", "/api/tools")
    assert _card(mine, "demo.price")[1]["health"][0]["personal"] is True
    other = _session(ui, OTHER_ID)
    status, data = _api(ui, other, "GET", "/api/tools")
    assert status == 200 and not [p for p in data["packs"] if p["name"] == "demo"]   # 個人版：別人本來就看不到 pack
    row = {"commands": [{"path": "demo.price"}]}
    ui._health_marks(row, bot.app.users.get_or_create(OTHER_ID))
    assert "health" not in row["commands"][0] and row["health_admin"] is False       # 他自己沒有紀錄、也不能按


def test_disabled_health_hides_admin_buttons(make_bot, tmp_path):
    bot, _folder, _clock = _bot(make_bot, tmp_path, None, raw={"health": {"enabled": False}})
    ui = _web(bot)
    owner = _session(ui, OWNER_ID)
    _status, data = _api(ui, owner, "GET", "/api/tools")
    assert _card(data, "demo.price")[0]["health_admin"] is False
    status, _data = _api(ui, owner, "POST", "/api/tools/health", {"key": "demo.price", "action": "release"})
    assert status == 409


def test_tools_js_uses_text_content_only():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "src", "synox", "web", "static", "tools.js")
    with open(path, encoding="utf-8") as f:
        js = f.read()
    assert "healthBlock" in js and "/api/tools/health" in js
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js
