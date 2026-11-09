"""
AI 助理（v0 只給機器擁有者）：

  /ai <人話>     跟 AI 說（私訊裡直接打字也一樣：dispatcher 的 fallback，只收擁有者）
  /ai_usage      用了多少（data/llm_usage.json）
  /ai_reset      忘掉這個聊天的對話紀錄
  /ai_approve    確認卡按鈕綁的節點（不用自己打）

群組 agent 是 bare＋owner_only：別人看不到、打了跟不存在一樣；agent 群組本身不給 AI 當工具（HIDDEN_GROUPS）。
"""

from __future__ import annotations

from typing import Optional

from isdtelekit.core.dispatcher import FALLBACK, Route
from isdtelekit.core.registry import DANGER, ROUTINE, WRITE

from synox.agent.approve import PREFIX, ApprovalDesk
from synox.agent.loop import AgentLoop, ai_decision
from synox.llm.base import ChatAdapter

NOT_SET = ("🤖 還沒設定 AI（config.json 的 llm.kind 是 none）。\n"
           "重跑 Setup.bat 選一個 AI 來源；不用 AI 也可以，指令照樣能用（/help）。")


class AgentFallback:
    """私訊裡的自由文字 → AI（只收擁有者；排程造的不收）。AI 一輪丟到 app.tasks，不卡收訊的執行緒。"""

    def __init__(self, app, loop: AgentLoop):
        self.app = app
        self.loop = loop

    def accepts(self, user, chat_id: int, via: str) -> bool:
        return via != ROUTINE and self.app.registry.is_owner(user)

    def handle(self, api, inbound, user, text: str, age: float) -> Route:
        route = self.app.dispatcher.log_route(inbound, text, Route(FALLBACK, "agent.ai"))
        self.app.tasks.run(lambda: self.loop.run_turn(api, inbound.chat_id, user, text), name="agent-turn")
        return route


def install(app, adapter: Optional[ChatAdapter], config) -> Optional[AgentLoop]:
    registry = app.registry
    registry.ensure_group("agent", "🤖 AI 助理", "跟 AI 說人話，它替你按指令（危險的會先問你）", owner_only=True,
                          bare=True)
    g = registry.group("agent")
    llm = getattr(config, "llm", {}) or {}
    loop: Optional[AgentLoop] = None
    desk = ApprovalDesk(app)
    if adapter is not None:
        loop = AgentLoop(app, adapter, max_steps=int(llm.get("max_steps", 6)),
                         history_turns=int(llm.get("history_turns", 6)), desk=desk)
        desk.on_done = loop.note
        app.dispatcher.fallback = AgentFallback(app, loop)
    app.extras["synox_agent"] = loop

    def cmd_ai(api, chat_id, user, args):
        if loop is None:
            api.send_message(chat_id, NOT_SET)
            return
        if not args:
            api.send_message(chat_id, "跟我說人話就好，例如：/ai 幫我記一筆 80 元咖啡\n（私訊裡直接打字也可以）")
            return
        app.tasks.run(lambda: loop.run_turn(api, chat_id, user, " ".join(args)), name="agent-turn")

    def cmd_usage(api, chat_id, user, args):
        if loop is None:
            api.send_message(chat_id, NOT_SET)
            return
        s = loop.usage.summary()

        def line(label, b):
            return f"{label}：{b.get('calls', 0)} 次，輸入 {b.get('input', 0):,} / 輸出 {b.get('output', 0):,} token"

        api.send_message(chat_id, "\n".join([f"🤖 {adapter.name}（每輪最多 {loop.max_steps} 步）",
                                             line("今天", s["today"]), line("這個月", s["month"]),
                                             line("全部", s["total"])]))

    def cmd_reset(api, chat_id, user, args):
        n = loop.reset(chat_id) if loop is not None else 0
        api.send_message(chat_id, f"🤖 好，忘掉這裡的對話紀錄了（{n // 2} 輪）。")

    def cmd_approve(api, chat_id, user, args):
        api.send_message(chat_id, "這是 AI 確認卡的按鈕用的，不用自己打。")

    g.leaf("ai", cmd_ai, "跟 AI 說人話", usage="<你想做的事>", effect=WRITE)
    g.leaf("ai_usage", cmd_usage, "AI 用了多少")
    g.leaf("ai_reset", cmd_reset, "忘掉這裡的對話紀錄", effect=WRITE)
    g.leaf("ai_approve", cmd_approve, "（確認卡的按鈕，不用自己打）", effect=DANGER, ai=False)
    registry.bind_callback(PREFIX, "agent.ai_approve", desk.on_button)
    return loop


__all__ = ["AgentLoop", "ApprovalDesk", "ai_decision", "install"]
