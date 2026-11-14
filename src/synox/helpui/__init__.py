"""
新的 /help：看得懂的三層卡片（docs/lab/2026-11-13-onboarding-help-aliases-plan.md §3.1；擁有者 2026-11-14 決定 1）。

    /help              第 0 層：一句「可以直接跟我說」＋每個工具一顆按鈕（**沒有指令清單**）
    /help 記帳｜money   第 1 層：那個工具會什麼、最常用的幾個怎麼打（例子）＋每個指令一顆按鈕
    /help money_month  第 2 層：那個指令的白話、唯讀／會寫入／危險、最多 3 個範例、要給什麼
    /help all          全部指令一次列出來（SDK 原本的總覽，照舊）
打群組名（例如 /money 是群組時）出現的那一組也換成第 1 層的字（dispatcher.group_menu）。

- vendor 不改：換掉 /help 節點的 fn（同 packs/library.py 的做法）、另外綁按鈕前綴 hp:（舊的 help: 按鈕照舊能按）。
  要在 tour.install、library.install **之前**裝（它們包在外面：/tutorial 那一行、「去哪裡裝工具」留在最後）。
- 可見性只問 registry.visible；「試試看」只給唯讀的指令，按了＝以按的人的身分把範例當成他打的字送進 dispatcher
  （同一個 authorize、速率限制、[ROUTE]）。會寫入與危險的範例永遠只是字。
- 資料在 model.py、卡片在 render.py、字在 text.py；範例與白話的格式與檢查在 examples.py（pack.json 的 help 區塊）。
"""

from __future__ import annotations

import logging
import time

from isdtelekit.core.channel import Inbound
from isdtelekit.core.registry import BUTTON, TYPED

from synox.helpui import model, render, text as T

PREFIX = render.PREFIX
ALL_WORDS = ("all", "全部")


def body(card: render.Card, channel: str):
    """同一張卡在不同通道的樣子：Telegram＝HTML；網頁＝純文字＋examples 區塊（helpdock.js 畫成可以點的小標籤）。"""
    if channel == "telegram":
        return card.html
    if channel == "web" and card.examples:
        from synox.present.web import WebText
        return WebText(card.text, [{"type": "examples", "items": card.examples}])
    return card.text


def install(app) -> None:
    registry = app.registry
    node = registry.root.children.get("help")
    if node is None or node.fn is None:
        return
    original = node.fn                                   # SDK 的 /help：/help all 照舊用它

    def has_ai(user) -> bool:
        ai = registry.node("agent.ai")
        return app.extras.get("synox_agent") is not None and ai is not None and \
            registry.authorize(user, ai, TYPED, user.tg_id).allowed

    def tutorial_ok(user) -> bool:
        t = registry.root.children.get("tutorial")
        return t is not None and t.fn is not None and registry.visible(user, t)

    def deliver(api, chat_id, card: render.Card, message_id=None):
        channel = getattr(api, "channel_name", "")
        markup = card.keyboard if (card.keyboard or {}).get("inline_keyboard") else None
        out = body(card, channel)
        if message_id is not None:
            return api.edit_message_text(chat_id, message_id, out, reply_markup=markup)
        return api.send_message(chat_id, out, reply_markup=markup)

    def home(user, page=0):
        return render.home(app, user, page, has_ai=has_ai(user), tutorial=tutorial_ok(user))

    def cmd_help(api, chat_id, user, args):
        private = chat_id == user.tg_id          # 共用的頻道／群組：一律正式的 /指令（不改別人看到的東西）
        if args and str(args[0]).lower() in ALL_WORDS:
            return original(api, chat_id, user, args)
        if args:
            query = " ".join(str(a) for a in args)
            kind, found = model.find(app, user, query)
            if kind == "tool":
                return deliver(api, chat_id, render.tool_card(app, user, found, 0, private))
            if kind == "command":
                return deliver(api, chat_id, render.command_card(app, user, found, render.tool_for(app, user, found),
                                                                 private))
            api.send_message(chat_id, T.NOT_FOUND.format(q=query))
            return
        deliver(api, chat_id, home(user))

    def run_example(api, cb, user, path: str, index: str) -> None:
        target = registry.node(path)
        if target is None or target.is_group or not registry.visible(user, target):
            api.answer_callback_query(cb.cq_id, text=T.GONE)
            return
        info = model.command(app, target, user, cb.chat_id == user.tg_id)
        try:
            ex = info["examples"][int(index)]
        except (ValueError, IndexError):
            ex = None
        if ex is None or not ex["try"]:
            api.answer_callback_query(cb.cq_id, text=T.TRY_REFUSED)
            return
        api.answer_callback_query(cb.cq_id)
        channel = getattr(api, "channel_name", "") or "button"
        app.dispatcher.handle(api, Inbound(channel, cb.clicker_id, cb.chat_id, ex["run"],
                                           username=getattr(user, "username", "") or "", sent_at=time.time()))

    def on_button(api, cb):
        user = app.users.get_or_create(cb.clicker_id)
        private = cb.chat_id == user.tg_id
        parts = cb.data[len(PREFIX):].split(":")
        what = parts[0] if parts else ""
        arg = lambda i, default="": parts[i] if len(parts) > i else default   # noqa: E731

        def page(i):
            try:
                return max(0, int(arg(i, "0")))
            except ValueError:
                return 0

        card = None
        if what == "h":
            card = home(user, page(1))
        elif what == "t":
            tool = model.tool_of(app, user, arg(1))
            card = render.tool_card(app, user, tool, page(2), private) if tool else None
        elif what == "c":
            target = registry.node(arg(1))
            if target is not None and not target.is_group and registry.visible(user, target):
                card = render.command_card(app, user, target, render.tool_for(app, user, target), private)
        elif what == "x":
            return run_example(api, cb, user, arg(1), arg(2))
        elif what == "tour":
            t = registry.root.children.get("tutorial")
            if t is not None and registry.authorize(user, t, BUTTON, cb.chat_id).allowed:
                api.answer_callback_query(cb.cq_id)
                t.fn(api, cb.chat_id, user, [])
                return
        if card is None:
            api.answer_callback_query(cb.cq_id, text=T.GONE)
            return
        deliver(api, cb.chat_id, card, cb.message_id)
        api.answer_callback_query(cb.cq_id)

    def group_menu(user, group):
        tool = model.tool_of(app, user, group.name) if group.parent is registry.root else None
        if tool is None:
            leaves = [n for n in group.walk() if not n.is_group and registry.visible(user, n)]
            return "\n".join([group.title, ""] + [f"• {model.title_of(app, n)}　{n.command}" for n in leaves])
        card = render.tool_card(app, user, tool, 0, private=False, buttons=False)
        return card.text + "\n" + T.GROUP_HINT.format(id=tool.id)

    node.fn = cmd_help
    node.summary = node.title = "看你有哪些工具、怎麼用（/help all 看全部指令）"
    registry.bind_callback(PREFIX, "help", on_button)
    app.dispatcher.group_menu = group_menu
    logging.debug("[HELP] help cards installed")
