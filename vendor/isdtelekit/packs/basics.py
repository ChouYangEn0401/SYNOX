"""
基本款：/start、/exit，以及「bot 離線時累積的舊指令先問」（StaleGuard）。

- /start [參數]：歡迎訊息。Telegram 的深連結 t.me/<bot>?start=<參數> 會變成「/start <參數>」，
  其他 pack 可以用 add_start_handler(app, fn) 接走參數（例如 passes 的通行證碼）。
- /exit：結束進行中的問答。對話的 session.state["on_exit"] 是函式的話先呼叫它（例如存檔），由開對話的功能決定。
  /exit 是最低一級就能用的根指令：任何人卡在任何問答裡都要出得來。
- StaleGuard：bot 離線時（重啟、斷網）累積、現在才收到的非唯讀指令（core/timing.py：超過 stale_message 秒），
  不直接執行，先問「這是 N 分鐘前傳的 /xxx，要現在執行嗎？[▶ 現在執行][略過]」。按「現在執行」＝把原本那則訊息
  重新送一次（送出時間改成現在），權限、/sudo、速率限制全部照常重新檢查；所以這顆按鈕綁在誰都能按的 /exit 上，
  真正的檢查在重送那一次。只有原本傳訊息的人按得動（Pending 有主人）。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Callable, List, Optional

from isdtelekit.core.channel import Inbound
from isdtelekit.core.timing import Pending

EXPIRED_CHOICE = "⌛ 這個選擇已經過期了（或不是你的），請重新來一次。"
StartHandler = Callable[[object, int, object, List[str]], bool]


def add_start_handler(app, handler: StartHandler) -> None:
    """handler(api, chat_id, user, args) 回 True＝這個 /start 參數它處理掉了（不再顯示歡迎訊息）。"""
    app.extras.setdefault("start_handlers", []).append(handler)


def install(app, *, welcome: Optional[Callable[[object], str]] = None, stale_guard: bool = True) -> None:
    """welcome(user) → 歡迎訊息；沒給就用預設（ID、角色、提示 /help）。"""

    def cmd_start(api, chat_id, user, args):
        if args:
            for handler in app.extras.get("start_handlers", []):
                if handler(api, chat_id, user, args):
                    return
        text = welcome(user) if welcome else (
            f"👋 歡迎！你的 Telegram ID 是 {user.tg_id}。\n"
            f"目前角色：{getattr(user.role, 'name', user.role)}\n\n輸入 /help 查看可用指令。")
        api.send_message(chat_id, text)

    def cmd_exit(api, chat_id, user, args):
        session = app.conversations.end(chat_id)
        if session is None:
            api.send_message(chat_id, "目前沒有進行中的對話。")
            return
        on_exit = session.state.get("on_exit")
        if callable(on_exit):
            on_exit(api, chat_id, user, session)
            return
        api.send_message(chat_id, f"✅ 已結束「{session.name}」。")

    app.registry.root_leaf("start", cmd_start, "開始使用、顯示歡迎訊息")
    # READ（預設）：離線時累積的 /exit 不用先問，結束問答本來就無害
    app.registry.root_leaf("exit", cmd_exit, "結束進行中的問答")
    if stale_guard:
        guard = StaleGuard(app)
        app.dispatcher.stale = guard
        app.registry.bind_callback("stale:", "exit", guard.on_button)


class StaleGuard:
    """core/dispatcher.py 的 StaleHandler：舊指令先問，按了才重送。"""

    def __init__(self, app, clock=None):
        self._app = app
        self._clock = clock or app.dispatcher._clock
        self.pending = Pending(self._clock)

    def stale_command(self, api, inbound: Inbound, node, age: float) -> None:
        token = self.pending.put(inbound, inbound.user_id, self._app.timing.confirm_ttl)
        sent = datetime.fromtimestamp(inbound.sent_at) if inbound.sent_at else None
        when = f"{int(age // 60)} 分鐘前" + (f"（{sent:%m/%d %H:%M}）" if sent else "")
        api.send_message(inbound.chat_id,
                         f"⏸ 這是{when}傳的 {inbound.text.split()[0]}，那時 bot 沒在收訊息。\n要現在執行嗎？",
                         reply_markup={"inline_keyboard": [[
                             {"text": "▶ 現在執行", "callback_data": f"stale:go:{token}"},
                             {"text": "略過", "callback_data": f"stale:skip:{token}"},
                         ]]})

    def on_button(self, api, cb) -> None:
        _p, action, token = (cb.data.split(":") + ["", ""])[:3]
        inbound = self.pending.take(token, cb.clicker_id)
        api.answer_callback_query(cb.cq_id)
        api.remove_buttons(cb.chat_id, cb.message_id)
        if inbound is None:
            api.send_message(cb.chat_id, EXPIRED_CHOICE)
            return
        if action != "go":
            api.send_message(cb.chat_id, f"好，{inbound.text.split()[0]} 不執行。")
            return
        # 重送一次：送出時間改成現在，權限、/sudo、速率限制全部重新檢查
        self._app.dispatcher.handle(api, replace(inbound, sent_at=self._clock(), edited=False))
