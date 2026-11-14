"""🔐 解鎖：/unlock [6 位數]（舊名 /sudo）、/unlock_off（ADR 0025 §5.3）。

- 只在私訊、不給 AI、不能排程（interactive）、只收人（scope callers=human）；伺服器版每個人都能用（解自己的）。
- 只打 /unlock：接下來 120 秒內的下一則訊息當成碼（**不會送給 AI**）。
- 被 🔐 擋下的指令，解鎖之後附一顆「▶ 繼續」（重用 SDK 的 SudoContinue）。
- 人直接打 6 個數字而他有設定驗證器：不送給 AI，回一句＋一顆「🔓 拿來解鎖」（`intercept_code`，對話助理呼叫）。
"""

from __future__ import annotations

import re

from isdtelekit.core.registry import DANGER, WRITE
from isdtelekit.core.timing import Pending
from isdtelekit.packs.basics import EXPIRED_CHOICE
from isdtelekit.packs.sudo import SudoContinue

from synox.guard import origin as origin_mod
from synox.guard.stepup import TEXT as STEPUP_TEXT

GROUP = "unlock"
CODE_ONLY = re.compile(r"^\s*\d{3} ?\d{3}\s*$", re.ASCII)
TEXT = {
    "not_set": "還沒設定手機驗證器。到 SYNOX 網頁 → 設定 → 🔐 安全 設定（危險的動作可以多一道手機驗證）。",
    "prompt": "🔐 貼上手機驗證器現在顯示的 6 位數（{s} 秒內）。\n（/exit 取消）",
    "already": "🔓 已解鎖，還剩 {m} 分鐘。",
    "retry": "\n\n再試一次就直接打 /unlock <6 位數>。",
    "off": "🔒 已鎖回去。",
    "was_off": "本來就沒解鎖。",
    "looks_like": "這看起來是驗證碼，要拿來解鎖嗎？（我不會把它交給 AI。）",
    "use_it": "🔓 拿來解鎖",
    "hint": "💡 這類動作可以多一道手機驗證：SYNOX 網頁 → 設定 → 安全。",
}
HINTS_FILE = "stepup_hints.json"


class FirstDangerHint:
    """第一次自己做危險的動作而沒設定驗證器：提示一次（每人一次，記在 data/stepup_hints.json）。"""

    def __init__(self, app, hub):
        self.app, self.hub = app, hub
        import os
        self.path = os.path.join(str(getattr(app.config, "data_dir", ".") or "."), HINTS_FILE)

    def around(self, kind, api, inbound, user, node, run) -> None:
        """提示放在指令的回覆**之前**：指令自己的回覆仍是最後一則（工具的測試與使用者看到的順序都不變）。"""
        if kind == "command" and getattr(node, "effect", "") == DANGER and origin_mod.current().human:
            self._hint_once(api, inbound, user)
        run(api)

    def _hint_once(self, api, inbound, user) -> None:
        uid = int(getattr(user, "tg_id", 0) or 0)
        try:
            from isdtelekit.core import jsonstore
            seen = jsonstore.load_json(self.path, [])
            seen = seen if isinstance(seen, list) else []
            if uid in seen or self.hub.enrolled(uid):
                return
            jsonstore.save_json(self.path, seen + [uid])
        except Exception:
            return
        api.send_message(inbound.chat_id, TEXT["hint"])


def install(app, hub, scope=None) -> None:
    registry, conv = app.registry, app.conversations
    registry.ensure_group(GROUP, "🔐 解鎖", "用手機驗證器解鎖危險的動作一段時間", private_only=True)
    cont = SudoContinue(app)
    app.dispatcher.add_observer(cont)
    app.dispatcher.add_observer(FirstDangerHint(app, hub))
    codes = Pending()

    def try_code(api, chat_id, user, code: str) -> None:
        r = hub.unlock(user.tg_id, code, origin=origin_mod.current())
        api.send_message(chat_id, r.text if r.ok else r.text + TEXT["retry"])
        if r.ok:
            cont.offer(api, chat_id, user.tg_id)

    def cmd_unlock(api, chat_id, user, args):
        if not hub.enrolled(user.tg_id):
            api.send_message(chat_id, TEXT["not_set"])
            return
        if args:
            try_code(api, chat_id, user, args[0])
            return
        left = hub.remaining(user.tg_id, origin_mod.current())
        if left:
            api.send_message(chat_id, TEXT["already"].format(m=left // 60 + 1))
            return
        conv.supersede(api, chat_id)
        wait = conv.timing.code_prompt

        def on_code(api2, chat2, user2, text):
            conv.end(chat2)
            parts = text.strip().split()
            try_code(api2, chat2, user2, "".join(parts[:2]) if len(parts) == 2 and CODE_ONLY.match(text)
                     else (parts[0] if parts else ""))
        conv.start(chat_id, user.tg_id, "unlock", on_code, idle_seconds=wait, label="/unlock")
        api.send_message(chat_id, TEXT["prompt"].format(s=int(wait)))

    def cmd_off(api, chat_id, user, args):
        api.send_message(chat_id, TEXT["off"] if hub.lock(user.tg_id, origin_mod.current()) else TEXT["was_off"])

    def on_code_button(api, cb) -> None:
        token = cb.data.split(":", 1)[1] if ":" in cb.data else ""
        code = codes.take(token, cb.clicker_id)
        api.answer_callback_query(cb.cq_id)
        api.remove_buttons(cb.chat_id, cb.message_id)
        if code is None:
            api.send_message(cb.chat_id, EXPIRED_CHOICE)
            return
        user = app.users.get_or_create(cb.clicker_id)
        try_code(api, cb.chat_id, user, code)

    g = registry.group(GROUP)
    on = g.leaf("on", cmd_unlock, "用手機驗證器的 6 位數解鎖危險的動作一段時間", default=True, usage="<6 位數>",
                effect=WRITE, ai=False, interactive=True, legacy=("/sudo",))
    off = g.leaf("off", cmd_off, "馬上鎖回去", effect=WRITE, ai=False, interactive=True, legacy=("/sudo_off",))
    registry.bind_callback("sudo_go:", on.path, cont.on_button)
    registry.bind_callback("unlock_code:", on.path, on_code_button)
    if scope is not None:
        for node in (on, off):
            scope.restrict(node.path, callers=("human",))

    def intercept(api, chat_id, user, text) -> bool:
        if not CODE_ONLY.match(text or "") or not hub.enrolled(user.tg_id):
            return False
        code = re.sub(r"\D", "", text)
        token = codes.put(code, user.tg_id, conv.timing.code_prompt)
        api.send_message(chat_id, TEXT["looks_like"], reply_markup={"inline_keyboard": [[
            {"text": TEXT["use_it"], "callback_data": f"unlock_code:{token}"}]]})
        return True

    app.extras["synox_unlock_intercept"] = intercept


def intercept_code(app, api, chat_id, user, text) -> bool:
    """對話助理收到的自由文字只有 6 個數字、而這個人有設定驗證器 → 不送 AI（回 True）。"""
    fn = (getattr(app, "extras", None) or {}).get("synox_unlock_intercept")
    return bool(fn and fn(api, chat_id, user, text))


__all__ = ["install", "intercept_code", "STEPUP_TEXT"]
