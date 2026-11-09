"""
核准卡：AI 想做危險的事（effect=DANGER、包著危險指令的排程、要驗證碼的）時，不直接做，送一張卡給使用者：

    ⚠️ AI 想執行：/note_clear
    全部筆記都刪掉
    （10 分鐘內有效）
    [✅ 執行] [❌ 取消]

- 按鈕綁在 agent.ai_approve 節點上（registry.bind_callback("agent_ok:", "agent.ai_approve", …)）：
  dispatcher 先以按的人身分 authorize 那個節點；ai_approve 是 DANGER，所以按鈕也有 SDK 的 button_ttl。
- 別人按了你的卡（群組、頻道裡看得到同一則訊息時）：先 take，不是他的就只回「這不是你的按鈕」，
  不拿掉按鈕、不作廢卡；過期、不認得、本人按了才拿掉按鈕。
- 卡一律送「下令的那個人」的私訊（chat_id 換成 user.tg_id）；在群組下的指令，群組裡只留一句「卡已私訊給你」。
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
IN_DM = "🔒 要你確認的卡已經私訊給你了（確認卡不在群組裡按）。"
DM_FIRST = "🔒 這個動作要你確認，但我私訊不到你：先私訊我一次（打 /start）再重做一次。"
NOT_YOURS = "這不是你的按鈕。"


class Cards(Pending):
    """SDK 的 Pending ＋ 問「這張卡還在、但主人不是你嗎」（take 對別人回 None 但留著卡，按鈕不能因此被拿掉）。"""

    def someone_elses(self, token: str, clicker_id) -> bool:
        with self._lock:
            item = self._items.get(token)
        if item is None:
            return False
        _payload, owner, expires = item
        return owner is not None and clicker_id is not None and owner != clicker_id and expires > self._clock()


class ApprovalDesk:

    def __init__(self, app, on_done: Optional[Callable[[int, str], None]] = None):
        self.app = app
        self.pending = Cards()
        self.on_done = on_done                # (chat_id, 一句話, 卡的主人) → 記進他的 AI 對話紀錄

    def request(self, api, chat_id: int, user, node, argv: List[str], why: str = "", *, grant: str = "",
                rerun: Optional[Callable] = None, header: str = "⚠️ AI 想執行", lines: Optional[List[str]] = None,
                run: Optional[Callable] = None) -> None:
        """lines＋run：schema 模式（巢狀參數）的卡——參數一行一個列在卡上，按 ✅ 叫 run(api, chat_id, 按的人)
        （同一組結構化參數，不經 argv）。"""
        ttl = self.app.timing.confirm_ttl
        where = chat_id
        chat_id = getattr(user, "tg_id", chat_id)          # 卡一律送下令那個人的私訊（不進群組）
        payload = {"path": node.path, "argv": list(argv), "chat_id": chat_id}
        if grant:
            payload.update(grant=grant, rerun=rerun)
        if run is not None:
            payload["run"] = run
        token = self.pending.put(payload, user.tg_id, ttl)
        shown = " ".join([node.command] + list(argv))
        minutes = max(1, int(ttl // 60))
        listed = ("\n參數：\n" + "\n".join(lines)) if lines else ""
        text = (f"{header}：{shown}\n{node.summary}" + listed + (f"\n{why}" if why else "") +
                f"\n（{minutes} 分鐘內有效；按 ✅ 才會執行）")
        sent = api.send_message(chat_id, text, reply_markup={"inline_keyboard": [[
            {"text": "✅ 執行", "callback_data": f"{PREFIX}go:{token}"},
            {"text": "❌ 取消", "callback_data": f"{PREFIX}no:{token}"}]]})
        if where != chat_id and getattr(api, "wanted_card", False) is not True:   # 頻道 AI 的管子攔下卡時不多說
            ok = isinstance(sent, dict) and sent.get("ok")
            api.send_message(where, IN_DM if ok else DM_FIRST)

    def on_button(self, api, cb) -> None:
        _prefix, action, token = (cb.data.split(":") + ["", ""])[:3]
        payload = self.pending.take(token, cb.clicker_id)
        if payload is None and self.pending.someone_elses(token, cb.clicker_id):
            # 別人的卡：只回這個按的人一句，**不**拿掉按鈕、不動卡（不然誰都能讓你的卡作廢）
            api.answer_callback_query(cb.cq_id, NOT_YOURS)
            return
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
            self._done(cb.chat_id, f"使用者取消了 {shown}", cb.clicker_id)
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
        elif callable(payload.get("run")):
            payload["run"](api, cb.chat_id, clicker)              # schema 模式：同一組結構化參數
        else:
            node.fn(api, cb.chat_id, clicker, list(payload["argv"]))
        self._done(cb.chat_id, f"使用者按了 ✅，已執行 {shown}", cb.clicker_id)

    def _discard(self, grant: str) -> None:
        if grant:
            from synox.packs.confirm import grants_of
            grants_of(self.app).discard(grant)

    def _done(self, chat_id: int, note: str, user_id=None) -> None:
        if self.on_done is not None:
            try:
                self.on_done(chat_id, note, user_id)
            except Exception:
                pass
