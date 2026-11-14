"""📱 /app_remote（ADR 0026 §3；計畫 K7）：問碼 → 開；擋群組、成員、AI、排程；每個前提的白話；/app_close；/apps。不開埠、不開子程序。"""

import pytest

from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID
from remote_helpers import make_phone

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")


def test_app_remote_asks_then_opens(counter, owner):
    phone = make_phone(counter, owner)
    phone.bot.say(owner, "/app_remote counter")
    assert "6 位數" in phone.bot.last(owner)
    phone.bot.say(owner, phone.code())
    text = phone.bot.last(owner)
    assert "https://quiet-river-1234.trycloudflare.com/#k=" in text
    assert "只能用一次" in text and "分鐘後自動關" in text and "/app_close counter" in text
    sent = phone.bot.api.sent[-1]
    assert sent.chat_id == owner


def test_link_preview_is_off(counter, owner, monkeypatch):
    phone = make_phone(counter, owner)
    seen = {}
    real = phone.bot.api.send_message

    def spy(chat_id, text, reply_markup=None, quiet=False, link_preview=True, **kw):
        if "trycloudflare" in text:
            seen["preview"] = link_preview
        return real(chat_id, text, reply_markup=reply_markup, quiet=quiet, link_preview=link_preview, **kw)
    monkeypatch.setattr(phone.bot.api, "send_message", spy)
    phone.bot.say(owner, "/app_remote counter 20")
    phone.bot.say(owner, phone.code())
    assert seen == {"preview": False} and phone.manager.link is not None


def test_open_with_remote_word_forwards(counter, owner):
    phone = make_phone(counter, owner)
    phone.bot.say(owner, "/app_open counter remote")
    assert "6 位數" in phone.bot.last(owner)


def test_group_member_ai_schedule(counter, owner):
    phone = make_phone(counter, owner, raw={"mode": "server"})
    phone.bot.say(owner, "/app_remote counter", chat_id=-100)
    assert phone.manager.link is None
    phone.bot.make(OTHER_ID, BasicRoles.MEMBER)
    phone.bot.say(OTHER_ID, "/app_remote counter")
    assert "未知指令" in phone.bot.last(OTHER_ID)
    phone.bot.say(owner, "/schedule_add 03:00 /app_remote counter")
    phone.bot.say(owner, "/schedule_list")
    assert "/app_remote" not in phone.bot.last(owner)


def test_ai_has_no_app_remote(counter, owner):
    bot, _apps = counter(["好"])
    bot.talk(owner, "幫我開手機入口")
    names = [t.name for t in bot.app.extras["synox_agent"].adapter.calls[0][1]]
    assert not any("remote" in n for n in names)


@pytest.mark.parametrize("case,needle", [("disabled", "總開關"), ("no_binary", "cloudflared"), ("tool_not_allowed", "可以從手機用"),
                                         ("bad_code", "驗證碼")])
def test_plain_reasons(counter, owner, case, needle):
    raw = {"web": {"remote": {"enabled": False}}} if case == "disabled" else None
    phone = make_phone(counter, owner, raw=raw, allow=case != "tool_not_allowed")
    if case == "no_binary":
        phone.manager.binary_check = lambda: "no_binary"
    phone.bot.say(owner, "/app_remote counter")
    phone.bot.say(owner, "000000" if case == "bad_code" else phone.code())
    assert needle in phone.bot.last(owner) and phone.bot.last(owner).startswith("❌")


def test_app_close_and_apps_line(counter, owner):
    phone = make_phone(counter, owner)
    phone.bot.say(owner, "/app_remote counter")
    phone.bot.say(owner, phone.code())
    phone.bot.say(owner, "/apps")
    assert "手機入口開著" in phone.bot.last(owner)
    phone.bot.say(owner, "/app_close counter")
    assert phone.manager.link.state == "closed" and phone.apps.running() == []
