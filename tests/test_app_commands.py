"""工具服務的 Telegram 指令與 doctor（計畫 C9、WP5；ADR 0026 對接 g）。假 listener，不開埠。"""

import json
import os
from datetime import datetime

import pytest

from isdtelekit.users.roles import BasicRoles

from synox import doctor
from synox.config import SynoxConfig

from conftest import OTHER_ID

pytestmark = pytest.mark.usefixtures("no_sockets")


def test_apps_list_and_open_close(counter, owner):
    bot, manager = counter()
    bot.say(owner, "/apps")
    assert "計數器：關著" in bot.last(owner) and "120 分鐘沒用就關" in bot.last(owner)
    bot.say(owner, "/app_open counter")
    text = bot.last(owner)
    assert "服務開好了" in text and "http://127.0.0.1:8830/#tools" in text and "127.0.0.2" not in text
    assert "第一次用" in text and manager.running() == ["counter"]
    assert manager.tickets.count("counter") == 0
    bot.say(owner, "/app_open 計數器")
    assert "第一次用" not in bot.last(owner)
    bot.say(owner, "/apps")
    assert "計數器：開著" in bot.last(owner) and "/app_open" in bot.last(owner)
    bot.say(owner, "/app_close 🔢 計數器")
    assert bot.last(owner).startswith("關好了") and manager.running() == []
    bot.say(owner, "/app_open nope")
    assert "沒有叫「nope」" in bot.last(owner) and "counter" in bot.last(owner)
    bot.say(owner, "/app_open COUNTER")
    bot.say(owner, "/app_close all")
    assert "全部關好了（1 個）" in bot.last(owner)


def test_blocked_reply(counter, owner):
    bot, manager = counter()
    manager.set_policy("counter", {"mode": "blocked"}, by=owner)
    bot.say(owner, "/app_open counter")
    assert "設成不開放了" in bot.last(owner) and manager.running() == []


def test_group_chat_and_member(counter, owner):
    bot, manager = counter(raw={"mode": "server"})
    bot.say(owner, "/app_open counter", chat_id=-100)
    assert manager.running() == []
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    bot.say(OTHER_ID, "/app_open counter")
    assert manager.running() == [] and "未知指令" in bot.last(OTHER_ID)
    bot.say(OTHER_ID, "/apps")
    assert "計數器" in bot.last(OTHER_ID) and "/app_open" not in bot.last(OTHER_ID)


def test_remote_word_points_to_app_remote(counter, owner):
    bot, manager = counter()
    bot.say(owner, "/app_open counter remote")                   # S14 起直接轉給 /app_remote：先問一組碼
    assert "6 位數" in bot.last(owner) and manager.running() == []


def test_schedule_and_ai_cannot_open(counter, owner):
    bot, manager = counter([{"tool": "apps__app_close", "args": {"target": "all"}}, "好"])
    bot.say(owner, "/schedule_add 03:00 /app_open counter")
    bot.say(owner, "/schedule_list")
    assert "/app_open" not in bot.last(owner)
    runner = bot.app.extras["synox_schedule_runner"]
    from synox.schedule.store import ScheduleStore
    ScheduleStore(bot.app.config.data_dir, bot.app.extras["vault"]).add("command", "03:00", owner,
                                                                       command="/app_open counter")
    fired = runner.tick(datetime(2026, 11, 9, 3, 0, 5))
    assert fired and manager.running() == []
    assert any("沒有跑成" in t for t in bot.texts(owner))
    bot.say(owner, "/schedule_add 03:00 /app_close all")
    assert "03:00" in bot.last(owner)
    bot.talk(owner, "把工具服務都關掉")
    adapter = bot.app.extras["synox_agent"].adapter
    names = [t.name for t in adapter.calls[0][1]]
    assert "apps__apps" in names and "apps__app_close" in names and "apps__app_open" not in names


def test_internal_system_start_is_forbidden(counter, owner):
    from synox.web.apps import AppsError
    _bot, manager = counter()
    with pytest.raises(AppsError) as e:
        manager.start("counter", by=owner, via="system")
    assert e.value.code == "forbidden"


def _config(tmp_path, **web):
    raw = {"owner_id": 1, "data_dir": str(tmp_path / "data"), "web": web}
    return SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path))


def test_doctor_lines(tmp_path):
    cfg = _config(tmp_path)
    lines = doctor.apps_lines(cfg, environ={}, exists=lambda p: False)
    assert lines[0].startswith("  工具服務：開放（本機位址 127.0.0.2，埠 8841–8856，最多同時 3 個")
    assert doctor.apps_lines(_config(tmp_path, apps={"enabled": False}), environ={}, exists=lambda p: False) == \
        ["  工具服務：關（web.apps.enabled=false）"]
    assert doctor.apps_lines(cfg, environ={"SYNOX_IN_CONTAINER": "1"}, exists=lambda p: False) == \
        ["  工具服務：容器版還沒開放"]
    os.makedirs(cfg.data_dir, exist_ok=True)
    with open(os.path.join(cfg.data_dir, "apps_state.json"), "w", encoding="utf-8") as f:
        json.dump({"pid": 1234, "running": [{"name": "money", "port": 8841}]}, f)
    with open(os.path.join(cfg.data_dir, "apps.json"), "w", encoding="utf-8") as f:
        json.dump({"policy": {"money": {"mode": "keep"}}}, f)
    lines = doctor.apps_lines(cfg, environ={}, exists=lambda p: False)
    assert "money 開在 8841" in lines[1] and "1234" in lines[1] and "一直開著" in lines[2]


def test_help_page(counter, owner):
    bot, _m = counter()
    bot.say(owner, "/help apps")
    text = bot.last(owner)
    assert "/app_open" in text or "工具服務" in text
