"""範圍測試（tests/test_scope.py）：/scoped_mine 只收人（callers）、/scoped_vault 一定要解鎖（stepup）、
/scoped_open 沒收緊、/scoped_who 回 kit.caller()、/scoped_self 用 kit.require_human() 自己再檢查一次。"""

from isdtelekit.core.registry import DANGER, READ

from synox.packs import kit


def install(app, pack):
    g = pack.group

    def say(text):
        return lambda api, chat_id, user, values: api.send_message(chat_id, text)

    def who(api, chat_id, user, values):
        c = kit.caller()
        api.send_message(chat_id, f"caller={c.kind} human={c.human}")

    def self_check(api, chat_id, user, values):
        kit.require_human()
        api.send_message(chat_id, "self ok")

    kit.command(g, "mine", say("mine ok"), "只收人", effect=READ)
    kit.command(g, "vault", say("vault ok"), "一定要解鎖", effect=DANGER)
    kit.command(g, "open", say("open ok"), "沒收緊", effect=READ)
    kit.command(g, "who", who, "誰叫的", effect=READ)
    kit.command(g, "self", self_check, "自己檢查", effect=READ)
