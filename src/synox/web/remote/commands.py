"""📱 `/app_remote <名字> [分鐘]`（ADR 0026 §3；計畫 K7）：開手機入口。

群組 `apps`；只有擁有者、只在私訊、`interactive`（排程與 AI 都不行）、`ai=False`、`callers=("human",)`。
問一組碼（120 秒內的下一則訊息；不會送給 AI），照 SDK `sudo` 的寫法 → `manager.open`。回覆不讓 Telegram 抓網址預覽（一次性連結被預覽就用掉了）。
"""

from __future__ import annotations

from isdtelekit.core.registry import WRITE

from synox.guard import origin as origin_mod
from synox.web.remote.manager import TEXT as REMOTE_TEXT, RemoteError

TEXT = {
    "usage": "要開哪一個？例如 /app_remote money（後面可以加分鐘，例如 /app_remote money 20）。",
    "ask": "🔐 貼上手機驗證器現在顯示的 6 位數（{s} 秒內），我就開{title}的手機入口。\n（/exit 取消）",
    "unknown": "沒有叫「{text}」的工具畫面。",
}


def install(app, manager) -> None:
    from synox import guard
    from synox.web import apps
    registry, conv = app.registry, app.conversations
    tool_apps = apps.of(app)

    def opened(api, chat_id, user, name, code, minutes):
        try:
            out = manager.open(name, user, code, origin=origin_mod.current(), minutes=minutes)
        except RemoteError as e:
            api.send_message(chat_id, "❌ " + e.text)
            return
        api.send_message(chat_id, REMOTE_TEXT["opened"].format(title=out["title"], m=out["minutes"], url=out["url"],
                                                               name=name), link_preview=False)

    def cmd_remote(api, chat_id, user, args):
        if not args:
            api.send_message(chat_id, TEXT["usage"])
            return
        minutes = None
        words = list(args)
        if len(words) >= 2 and words[-1].isascii() and words[-1].isdigit():
            minutes = int(words.pop())
        name = tool_apps.resolve(" ".join(words))
        if name is None:
            api.send_message(chat_id, TEXT["unknown"].format(text=" ".join(words)[:40]))
            return
        conv.supersede(api, chat_id)
        wait = conv.timing.code_prompt

        def on_code(api2, chat2, user2, text):
            conv.end(chat2)
            parts = text.strip().split()
            opened(api2, chat2, user2, name, "".join(parts[:2]) if len(parts) == 2 else (parts[0] if parts else ""),
                   minutes)
        conv.start(chat_id, user.tg_id, "app_remote", on_code, idle_seconds=wait, label="/app_remote")
        api.send_message(chat_id, TEXT["ask"].format(s=int(wait), title=tool_apps._title(name)))

    g = registry.group("apps")
    node = g.leaf("app_remote", cmd_remote, "開一個工具的手機入口（要手機驗證器；只有你本人、只在私訊）", usage="<名字> [分鐘]",
                  effect=WRITE, owner_only=True, private_only=True, interactive=True, ai=False)
    gate = guard.of(app)
    if gate is not None and gate.scope is not None:
        gate.scope.restrict(node.path, callers=("human",))
    app.extras["synox_remote_open_command"] = cmd_remote          # /app_open <名字> remote 直接轉過來（對接 g）
