"""
核准卡：AI 想做危險的事（effect=DANGER、包著危險指令的排程、要驗證碼的）時，不直接做，送一張卡給使用者：

    ⚠️ AI 想執行：/note_clear
    全部筆記都刪掉
    （10 分鐘內有效）
    [✅ 執行] [❌ 取消]

- 按鈕綁在 agent.ai_approve 節點上（registry.bind_callback("agent_ok:", "agent.ai_approve", …)）：
  dispatcher 先以按的人身分 authorize 那個節點；ai_approve 是 DANGER，所以按鈕也有 SDK 的 button_ttl。
- 卡片背後的資料放在 SDK 的 Pending：隨機 token、有主人、有期限（Timing.confirm_ttl）、用一次就沒了；重啟後舊卡按不動。
- 按 ✅：再用 via=BUTTON 對**要執行的那個節點** authorize 一次（這時是人按的，不是 AI），通過才用真的 api 執行——
  輸出直接給使用者；要驗證碼的指令這時會照常問碼（驗證碼永遠不經 AI）。
- 工具自己要確認（needs_confirm，SDK P3；packs/confirm.py）：request_tool_confirm() 出同一種卡（why＝工具給的 summary，
  人打字或 AI 呼叫都一樣），payload 多一個一次性確認憑證與 rerun。按 ✅ 一樣先 authorize，再 rerun（同一組參數，
  帶憑證；loader 驗過才給子程序 SYNOX_CONFIRMED=1）；按 ❌ 作廢憑證。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from isdtelekit.core.registry import BUTTON
from isdtelekit.core.timing import Pending

PREFIX = "agent_ok:"
EXPIRED = "⌛ 這張確認卡過期了（或不是你的），請重新跟 AI 說一次。"


class ApprovalDesk:

    def __init__(self, app, on_done: Optional[Callable[[int, str], None]] = None):
        self.app = app
        self.pending = Pending()
        self.on_done = on_done                # (chat_id, 一句話) → 記進 AI 的對話紀錄

    def request(self, api, chat_id: int, user, node, argv: List[str], why: str = "", *, grant: str = "",
                rerun: Optional[Callable] = None, header: str = "⚠️ AI 想執行") -> None:
        ttl = self.app.timing.confirm_ttl
        payload = {"path": node.path, "argv": list(argv), "chat_id": chat_id}
        if grant:
            payload.update(grant=grant, rerun=rerun)
        token = self.pending.put(payload, user.tg_id, ttl)
        shown = " ".join([node.command] + list(argv))
        minutes = max(1, int(ttl // 60))
        text = (f"{header}：{shown}\n{node.summary}" + (f"\n{why}" if why else "") +
                f"\n（{minutes} 分鐘內有效；按 ✅ 才會執行）")
        api.send_message(chat_id, text, reply_markup={"inline_keyboard": [[
            {"text": "✅ 執行", "callback_data": f"{PREFIX}go:{token}"},
            {"text": "❌ 取消", "callback_data": f"{PREFIX}no:{token}"}]]})

    def on_button(self, api, cb) -> None:
        _prefix, action, token = (cb.data.split(":") + ["", ""])[:3]
        payload = self.pending.take(token, cb.clicker_id)
        api.answer_callback_query(cb.cq_id)
        api.remove_buttons(cb.chat_id, cb.message_id)
        if payload is None:
            api.send_message(cb.chat_id, EXPIRED)
            return
        registry = self.app.registry
        node = registry.node(payload["path"])
        shown = " ".join([node.command if node else payload["path"]] + payload["argv"])
        grant = payload.get("grant") or ""
        if action != "go":
            self._discard(grant)
            api.send_message(cb.chat_id, f"好，不執行 {shown}。")
            self._done(cb.chat_id, f"使用者取消了 {shown}")
            return
        if node is None or node.is_group:
            self._discard(grant)
            api.send_message(cb.chat_id, f"❌ {payload['path']} 已經不存在了。")
            return
        clicker = self.app.users.get_or_create(cb.clicker_id)
        decision = registry.authorize(clicker, node, BUTTON, cb.chat_id)
        if not decision.allowed:
            self._discard(grant)
            api.send_message(cb.chat_id, decision.message)
            return
        if grant and callable(payload.get("rerun")):
            payload["rerun"](api, cb.chat_id, clicker, grant)     # 同一組參數重跑，帶一次性憑證（loader 驗）
        else:
            node.fn(api, cb.chat_id, clicker, list(payload["argv"]))
        self._done(cb.chat_id, f"使用者按了 ✅，已執行 {shown}")

    def _discard(self, grant: str) -> None:
        if grant:
            from synox.packs.confirm import grants_of
            grants_of(self.app).discard(grant)

    def _done(self, chat_id: int, note: str) -> None:
        if self.on_done is not None:
            try:
                self.on_done(chat_id, note)
            except Exception:
                pass
