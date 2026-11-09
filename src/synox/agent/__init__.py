"""
AI 助理：

  /ai <人話>     跟 AI 說（私訊裡直接打字也一樣：dispatcher 的 fallback）
  /ai_usage      用了多少（擁有者：data/llm_usage.json 全部；成員：自己這個月與額度）
  /ai_reset      忘掉這個聊天的對話紀錄
  /ai_approve    確認卡按鈕綁的節點（不用自己打）
  /ai_budget     伺服器版、管理員：替某個人設每月 AI 額度（美元）

誰能用：個人版只有擁有者（群組 agent 是 owner_only）；伺服器版成員以上（群組 role=成員，訪客看不到）。
只能在私訊用（agent 群組 private_only）：Telegram 群組裡打 /ai、/ai_reset 一律被 SDK 擋（Discord 頻道 AI 另走 agent/room.py）。
「這個人的自由文字要不要交給 AI」也問同一個 authorize（AgentFallback.accepts），不另外寫一套判斷。
伺服器版成員有每月額度（agent/budget.py）；AI 拿到的工具只有 ai_decision 對「他」放行的（loop.ai_decision）。
agent 群組本身不給 AI 當工具（HIDDEN_GROUPS）。
"""

from __future__ import annotations

from typing import Optional

from isdtelekit.core.dispatcher import FALLBACK, Route
from isdtelekit.core.registry import DANGER, ROUTINE, TYPED, WRITE

from synox import policy
from synox.agent.approve import PREFIX, ApprovalDesk
from synox.agent.budget import EXHAUSTED, MemberBudget
from synox.agent.loop import AgentLoop, ai_decision
from synox.llm.base import ChatAdapter
from synox.packs.loader import group_policy

NOT_SET = ("🤖 還沒設定 AI（config.json 的 llm.kind 是 none）。\n"
           "重跑 Setup.bat 選一個 AI 來源；不用 AI 也可以，指令照樣能用（/help）。")


class AgentFallback:
    """私訊裡的自由文字 → AI（authorize 過 /ai 那個節點的人；排程造的不收）。AI 一輪丟到 app.tasks，不卡收訊的執行緒。"""

    def __init__(self, app, loop: AgentLoop):
        self.app = app
        self.loop = loop

    def accepts(self, user, chat_id: int, via: str) -> bool:
        if via == ROUTINE:
            return False
        node = self.app.registry.node("agent.ai")
        return node is not None and self.app.registry.authorize(user, node, TYPED, chat_id).allowed

    def handle(self, api, inbound, user, text: str, age: float) -> Route:
        route = self.app.dispatcher.log_route(inbound, text, Route(FALLBACK, "agent.ai"))
        bot = policy.current_bot()                   # 收訊的 bot：AI 那一輪在別的執行緒，要帶過去（工具清單照它過濾）
        self.app.tasks.run(lambda: policy.run_as(bot, self.loop.run_turn, api, inbound.chat_id, user, text),
                           name="agent-turn")
        return route


def install(app, adapter: Optional[ChatAdapter], config) -> Optional[AgentLoop]:
    from synox.packs import kit
    kit.install_log_redaction()                     # [ROUTE]／[AGENT] 行的 token 樣式一律遮掉（審查 A #7）
    registry = app.registry
    server = getattr(config, "mode", "personal") == "server"
    # private_only：群組裡打 /ai 不行（跟 /web 一樣）——AI 拿得到這個人的私人工具與記憶，不能在多人看得到的地方用
    registry.ensure_group("agent", "🤖 AI 助理", "跟 AI 說人話，它替你按指令（危險的會先問你）", bare=True,
                          private_only=True, **group_policy(app, "member", server))
    g = registry.group("agent")
    llm = getattr(config, "llm", {}) or {}
    loop: Optional[AgentLoop] = None
    desk = ApprovalDesk(app)
    app.extras["synox_approval_desk"] = desk        # cli pack 的 needs_confirm 也用這張卡（packs/loader.py、packs/confirm.py）
    budget = MemberBudget(app, config) if server else None
    app.extras["synox_budget"] = budget
    if adapter is not None:
        loop = AgentLoop(app, adapter, max_steps=int(llm.get("max_steps", 6)),
                         history_turns=int(llm.get("history_turns", 6)), desk=desk, budget=budget)
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
        bot = policy.current_bot()
        app.tasks.run(lambda: policy.run_as(bot, loop.run_turn, api, chat_id, user, " ".join(args)), name="agent-turn")

    def line(label, b):
        return f"{label}：{b.get('calls', 0)} 次，輸入 {b.get('input', 0):,} / 輸出 {b.get('output', 0):,} token"

    def cmd_usage(api, chat_id, user, args):
        if loop is None:
            api.send_message(chat_id, NOT_SET)
            return
        if budget is not None and not budget.exempt(user):
            s = budget.book(user.tg_id).summary()
            used, limit = budget.month_usd(user.tg_id), budget.limit(user.tg_id)
            api.send_message(chat_id, "\n".join([
                f"🤖 {adapter.name}", line("今天", s["today"]), line("這個月", s["month"]),
                f"這個月的額度：用了約 US${used:.2f}／US${limit:.2f}" + ("（用完了）" if used >= limit else "")]))
            return
        s = loop.usage.summary()
        api.send_message(chat_id, "\n".join([f"🤖 {adapter.name}（每輪最多 {loop.max_steps} 步）",
                                             line("今天", s["today"]), line("這個月", s["month"]),
                                             line("全部", s["total"])]))

    def cmd_reset(api, chat_id, user, args):
        n = loop.reset(chat_id, user) if loop is not None else 0
        api.send_message(chat_id, f"🤖 好，忘掉這裡的對話紀錄了（{n // 2} 輪）。")

    def cmd_approve(api, chat_id, user, args):
        api.send_message(chat_id, "這是 AI 確認卡的按鈕用的，不用自己打。")

    def cmd_budget(api, chat_id, user, args):
        if len(args) != 2 or not args[0].isdigit():
            api.send_message(chat_id, "用法：/ai_budget <使用者 id> <每月美元>（例如 /ai_budget 12345 5；"
                                      "default＝改回預設）")
            return
        target = int(args[0])
        if args[1].lower() == "default":
            budget.set_limit(target, None)
        else:
            try:
                usd = float(args[1])
            except ValueError:
                api.send_message(chat_id, "❌ 金額要是數字（美元）。")
                return
            if usd < 0:
                api.send_message(chat_id, "❌ 金額不能是負的。")
                return
            budget.set_limit(target, usd)
        api.send_message(chat_id, f"🤖 {target} 每月 AI 額度：US${budget.limit(target):.2f}"
                                  f"（這個月用了約 US${budget.month_usd(target):.2f}）")

    g.leaf("ai", cmd_ai, "跟 AI 說人話", usage="<你想做的事>", effect=WRITE)
    g.leaf("ai_usage", cmd_usage, "AI 用了多少")
    g.leaf("ai_reset", cmd_reset, "忘掉這裡的對話紀錄", effect=WRITE)
    g.leaf("ai_approve", cmd_approve, "（確認卡的按鈕，不用自己打）", effect=DANGER, ai=False)
    if server:
        g.leaf("ai_budget", cmd_budget, "設某個人每月的 AI 額度（美元）", usage="<id> <美元|default>",
               effect=WRITE, role=app.users.top_role, ai=False)
    registry.bind_callback(PREFIX, "agent.ai_approve", desk.on_button)
    return loop


__all__ = ["AgentLoop", "ApprovalDesk", "EXHAUSTED", "MemberBudget", "ai_decision", "install"]
