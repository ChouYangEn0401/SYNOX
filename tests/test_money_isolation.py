# -*- coding: utf-8 -*-
"""伺服器版：A 的第一筆帳絕對不能出現在 B 的帳裡（2026-11-10 的淺拷貝 bug 的回歸測試）。"""
from isdtelekit.users.roles import BasicRoles


def test_first_entries_do_not_leak_between_users(make_bot, owner):
    bot = make_bot(raw={"mode": "server"})
    bot.make(77, BasicRoles.MEMBER, "a")
    bot.make(78, BasicRoles.MEMBER, "b")
    bot.say(77, "/money 50 咖啡 祕密備註A", chat_id=77)
    bot.say(78, "/money 20 茶", chat_id=78)
    bot.say(78, "/money_list", chat_id=78)
    b_view = "\n".join(bot.texts(chat_id=78))
    assert "咖啡" not in b_view and "祕密備註A" not in b_view and "茶" in b_view
    bot.say(77, "/money_list", chat_id=77)
    a_view = "\n".join(bot.texts(chat_id=77))
    assert "茶" not in a_view and "咖啡" in a_view
