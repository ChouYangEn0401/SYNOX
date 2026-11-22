"""
備援的「先問我」卡（llm.waterfall.mode = ask，docs/adr/0046）：AI 來源因為額度用完、金鑰失效…不能用時，問要不要換。

    ⚠️ 主要來源：額度用完。要改用別的來源嗎？
    按「改用」會用那個來源把剛剛那句重送一次。
    （10 分鐘內有效）
    [改用 本地模型 重送]
    [改用 LLOP 重送]
    [❌ 不用]

- 跟核准卡（agent/approve.py）同一套：按鈕綁在 agent.ai_approve 節點（dispatcher 先用按的人 authorize）、
  卡的資料在 Pending（隨機 token、有主人、有期限、用一次就沒了；別人按＝「這不是你的按鈕」、不作廢）。
- 卡一律送下令那個人的私訊（跟核准卡一樣）；期限＝核准卡的期限與 router 給的期限取短的。
- 按「改用 X 重送」：在 `RouterAdapter.pinned(X)` 裡重跑剛剛那一輪（同一句話）。只在**這一輪還沒做任何事**時才給重送
  （loop 判斷：第一步就失敗、沒有附件或圖）；做到一半的只說明、不出按鈕（不重複執行已經做過的工具）。
- 這張卡**不經 AI**：AI 看不到、也按不到（ai_approve 是 ai=False）。
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from synox.agent.approve import EXPIRED, NOT_YOURS, Cards

PREFIX = "agent_fb:"
HALFWAY = ("這一句已經做了一部分（或帶了附件），所以不自動換來源重送，免得重複做。"
           "請再說一次要接著做什麼；備援的設定會照常決定下一句用哪個來源。")


class FallbackDesk:

    def __init__(self, app):
        self.app = app
        self.pending = Cards()

    def ttl_for(self, error) -> float:
        import time
        ttl = float(self.app.timing.confirm_ttl)
        expires = float(getattr(getattr(error, "pending", None), "expires_at", 0) or 0)
        if expires:
            ttl = max(1.0, min(ttl, expires - time.time()))
        return ttl

    def offer(self, api, chat_id: int, user, error, resend: Optional[Callable[[], None]]) -> None:
        """error：llm.router.FallbackAsk。resend：重跑剛剛那一輪的函式（None＝做到一半，不給重送）。"""
        if resend is None or not error.choices:
            api.send_message(chat_id, f"⚠️ AI 沒有回應：{error}\n{HALFWAY}")
            return
        ttl = self.ttl_for(error)
        where = chat_id
        chat_id = getattr(user, "tg_id", chat_id)               # 跟核准卡一樣：一律送下令那個人的私訊
        token = self.pending.put({"error": error, "resend": resend}, user.tg_id, ttl)
        rows = [[{"text": f"改用 {label} 重送", "callback_data": f"{PREFIX}use:{token}:{i}"}]
                for i, (_mid, label) in enumerate(error.choices)]
        rows.append([{"text": "❌ 不用", "callback_data": f"{PREFIX}no:{token}"}])
        minutes = max(1, int(ttl // 60))
        api.send_message(chat_id, f"⚠️ {error}\n按「改用」會用那個來源把剛剛那句重送一次。\n（{minutes} 分鐘內有效）",
                         reply_markup={"inline_keyboard": rows})
        if where != chat_id:
            from synox.agent.approve import IN_DM
            api.send_message(where, IN_DM)

    def on_button(self, api, cb) -> None:
        parts = (cb.data.split(":") + ["", "", ""])[:4]
        _prefix, action, token, index = parts
        payload = self.pending.take(token, cb.clicker_id)
        if payload is None and self.pending.someone_elses(token, cb.clicker_id):
            api.answer_callback_query(cb.cq_id, NOT_YOURS)
            return
        api.answer_callback_query(cb.cq_id)
        api.remove_buttons(cb.chat_id, cb.message_id)
        if payload is None:
            api.send_message(cb.chat_id, EXPIRED)
            return
        error = payload["error"]
        if action != "use":
            api.send_message(cb.chat_id, "好，不換來源。")
            return
        try:
            member_id, label = error.choices[int(index)]
        except (ValueError, IndexError):
            api.send_message(cb.chat_id, EXPIRED)
            return
        pending = getattr(error, "pending", None)
        if pending is not None and callable(getattr(pending, "expired", None)) and pending.expired():
            api.send_message(cb.chat_id, EXPIRED)
            return
        adapter = error.adapter
        current = self.app.extras.get("synox_agent")
        if current is None or getattr(current, "adapter", None) is not adapter:
            api.send_message(cb.chat_id, "AI 來源的設定剛換過，這張卡不能用了；請再說一次。")
            return
        api.send_message(cb.chat_id, f"好，改用 {label}，重送剛剛那句…")
        resend = payload["resend"]

        def run() -> None:
            try:
                with adapter.pinned(member_id):
                    resend()
            except Exception:
                logging.exception("[AGENT] fallback resend failed")
                api.send_message(cb.chat_id, f"⚠️ 改用 {label} 重送失敗了，請再說一次。")
        self.app.tasks.run(run, name="agent-fallback")
