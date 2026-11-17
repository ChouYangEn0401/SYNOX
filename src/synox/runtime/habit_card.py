"""
`soul__propose_habit`：AI 把使用者口頭講的習慣**提議**寫進 soul.md「習慣與規則」段——一律出卡，擁有者按 ✅ 才寫
（核心統一規劃 11.4；寫法與解析在 runtime/habits.py）。

    📜 想把這一條加進你的「習慣與規則」（soul.md）：
    - 一天最多排兩部。〔schedule.plan.per_day=2〕
    這會影響：行事曆
    🔴 放寬：schedule.plan.per_day 1 → 2（比現在寬鬆）
    （10 分鐘內有效；按 ✅ 才會寫進去）
    [✅ 寫進去] [❌ 不要]

邊界（ADR 0002／0005 不變：對話助理不能直接寫 soul.md）：
- 系統群組 `soul`（owner_only＋private_only）：成員、訪客、頻道看不到也叫不到；權限照常只經 policy.decide。
- 誰能叫：門禁的範圍只收「人」與「AI」（guard/scope.py）——排程、常駐助理（system）、手機入口都不行。
  常駐助理本來就沒有工具；它的 `SOUL+:` 只進「助理筆記」段，工具不讀那一段。
- 鍵一定要是已載入工具宣告過的（pack.json agent.prefs），值過型別與範圍檢查；比現值寬鬆＝卡上紅字「放寬」。
- 按 ✅＝`SoulStore.set_habit`（by=owner）；按 ❌＝記進 soul 帳本的 suppress（只存雜湊），之後再提同一行直接擋。
- 卡片背後的資料在記憶體（approve.Cards：隨機 token、有主人、有期限），重開後舊卡按不動；別人按＝「這不是你的按鈕」。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from isdtelekit.core.registry import WRITE, Field

from synox.packs import kit
from synox.runtime import habits

GROUP = "soul"
NODE = "soul.propose_habit"
PREFIX = "soul_habit:"
TITLE = "📜 習慣與規則（系統）"
SUMMARY = "把你口頭講的習慣記下來（AI 只能提議，你按了才寫）"
RETIRED = ("「soul」是系統的群組名（📜 習慣與規則）：工具不能用這個群組名。")
EXPIRED = "⌛ 這張卡過期了（或不是你的），請再跟 AI 說一次。"
NOT_YOURS = "這不是你的按鈕。"
NO_SOUL = "📜 soul.md 現在讀寫不了（保管箱沒有打開；python -m synox doctor 看原因）。"


def _ledger(app):
    from synox import runtime
    return getattr(runtime.of(app), "ledger", None)


def _soul(app):
    from synox import runtime
    return getattr(runtime.of(app), "soul", None)


def describe(app, line: str) -> dict:
    """要加的那一行 → 卡上要講的事：{line, keys, affects, looser, replaced, shadowed, risks}。
    鍵沒宣告、值不合型別、語法壞掉 → HabitError（給 AI 看的一句話）。"""
    decls = habits.declarations(app)
    line, values = habits.check_line(line, decls)
    unknown = [k for k, _v in values if k not in decls]
    if unknown:
        known = "、".join(sorted(decls)) or "（現在沒有工具宣告任何鍵）"
        raise habits.HabitError(f"{'、'.join(unknown)} 不是任何已載入工具宣告的鍵。可以用的鍵：{known}")
    soul = _soul(app)
    current = soul.prefs() if soul is not None else {}
    users = habits.users_of(app)
    affects: List[str] = []
    looser: List[str] = []
    for key, value in values:
        for name in users.get(key, []):
            if name not in affects:
                affects.append(name)
        pref = decls[key]
        old = current.get(key, pref.default)
        if habits.is_looser(pref, old, value):
            looser.append(f"{key} {habits.format_value(old)} → {habits.format_value(value)}")
    _text, replaced, shadowed = habits.insert(soul.text() if soul is not None else "", line)
    from synox.runtime.ledger import risk_flags
    risks = [f for f in risk_flags(habits.split_line(line)[0]) if f != "寫了習慣的〔鍵=值〕"]
    return {"line": line, "keys": [k for k, _v in values], "affects": affects, "looser": looser,
            "replaced": replaced, "shadowed": shadowed, "risks": risks}


def card_text(info: dict, minutes: int) -> str:
    lines = ["📜 想把這一條加進你的「習慣與規則」（soul.md）：", info["line"],
             "這會影響：" + ("、".join(info["affects"]) or "（沒有工具讀；只給 AI 參考）")]
    for item in info["looser"]:
        lines.append(f"🔴 放寬：{item}（比現在寬鬆）")
    for old in info["replaced"]:
        lines.append(f"取代：{old}")
    for old in info["shadowed"]:
        lines.append(f"同一個鍵也寫在：{old}（這一條放在後面，以這一條為準）")
    if info["risks"]:
        lines.append("⚠️ 看一下：" + "；".join(info["risks"]))
    lines.append(f"（{minutes} 分鐘內有效；按 ✅ 才會寫進去）")
    return "\n".join(lines)


def install(app) -> None:
    """在 packs.load_all **之前**掛（群組名先佔住，跟 ⏰ 提醒一樣）。"""
    from synox.agent import index
    from synox.agent.approve import Cards
    from synox.packs.loader import SYSTEM_GROUPS_KEY

    registry = app.registry
    group = registry.define_group(GROUP, TITLE, SUMMARY, owner_only=True, private_only=True)
    cards = Cards()
    app.extras["synox_habit_cards"] = cards

    def propose(api, chat_id, user, values):
        soul = _soul(app)
        if soul is None or not soul.available:
            api.send_message(chat_id, NO_SOUL)
            return
        text = (values.get("text") or "").strip()
        key = (values.get("key") or "").strip()
        value = values.get("value")
        if bool(key) != (value is not None and str(value).strip() != ""):
            api.send_message(chat_id, "❌ key 與 value 要一起給（例：key=schedule.plan.per_day value=2）。")
            return
        line = text + (f"〔{key}={str(value).strip()}〕" if key else "")
        try:
            info = describe(app, line)
        except habits.HabitError as e:
            api.send_message(chat_id, f"❌ 這一條不能提：{e}")
            return
        ledger = _ledger(app)
        if ledger is not None and ledger.is_suppressed(info["line"]):
            api.send_message(chat_id, "❌ 使用者之前說過不要這一條，不再提。")
            return
        if info["line"] in [ln.line for ln in soul.habits().lines]:
            api.send_message(chat_id, "✅ 這一條本來就在「習慣與規則」裡了，不用再加。")
            return
        ttl = app.timing.confirm_ttl
        token = cards.put({"line": info["line"]}, user.tg_id, ttl)
        sent = api.send_message(user.tg_id, card_text(info, max(1, int(ttl // 60))), reply_markup={"inline_keyboard": [[
            {"text": "✅ 寫進去", "callback_data": f"{PREFIX}go:{token}"},
            {"text": "❌ 不要", "callback_data": f"{PREFIX}no:{token}"}]]})
        if user.tg_id != chat_id and not (isinstance(sent, dict) and sent.get("ok") is False):
            api.send_message(chat_id, "🔒 卡片私訊給你了。")
        mark = getattr(type(api), "mark_carded", None)      # 經 AI（CaptureApi）：這一輪停在這裡，等人按
        if callable(mark):
            mark(api)

    kit.command(group, "propose_habit", propose,
                "提議把使用者口頭講的習慣或規則記進「習慣與規則」（一定出卡，使用者按 ✅ 才寫；鍵要是工具宣告過的）",
                effect=WRITE, positional=1,
                fields=[Field("text", "這條習慣的一句人話（例：一天最多排兩部，不要切段）", required=True),
                        Field("key", "要設定的鍵（只能用工具宣告過的，例：schedule.plan.per_day）"),
                        Field("value", "那個鍵的值（JSON 字面值或純字串，例：2、true、\"20:00\"）")])

    def on_button(api, cb) -> None:
        _prefix, action, token = (cb.data.split(":") + ["", ""])[:3]
        payload = cards.take(token, cb.clicker_id)
        if payload is None and cards.someone_elses(token, cb.clicker_id):
            api.answer_callback_query(cb.cq_id, NOT_YOURS)
            return
        api.answer_callback_query(cb.cq_id)
        api.remove_buttons(cb.chat_id, cb.message_id)
        if payload is None:
            api.send_message(cb.chat_id, EXPIRED)
            return
        line = payload["line"]
        if action != "go":
            ledger = _ledger(app)
            remembered = False
            try:
                if ledger is not None:
                    ledger.suppress_line(line, what="不要這一條習慣：" + line)
                    remembered = True
            except Exception:                         # 帳本寫不了（保管箱壞了）：照樣不寫，但老實說記不住
                logging.exception("[SOUL] could not remember a rejected habit (ignored)")
            api.send_message(cb.chat_id, "好，不寫。" + ("之後再提一模一樣的一條會直接擋掉。" if remembered
                                                     else "（這次沒記成「不要」，AI 之後可能會再提一次。）"))
            _note(app, cb.chat_id, cb.clicker_id, f"使用者不要這一條習慣：{line}")
            return
        soul = _soul(app)
        if soul is None or not soul.available:
            api.send_message(cb.chat_id, NO_SOUL)
            return
        from synox.runtime.soul import SoulError
        try:
            describe(app, line)                       # 按下去的這一刻再對一次（工具可能被拿掉、宣告可能改了）
            done = soul.set_habit(line, by="owner")
        except (habits.HabitError, SoulError) as e:
            api.send_message(cb.chat_id, f"❌ 沒有寫進去：{e}")
            return
        tail = f"\n（取代了 {len(done['replaced'])} 行）" if done["replaced"] else ""
        api.send_message(cb.chat_id, f"✅ 寫進「習慣與規則」了：\n{done['line']}{tail}")
        _note(app, cb.chat_id, cb.clicker_id, f"使用者按了 ✅，習慣寫進「習慣與規則」了：{done['line']}")

    registry.bind_callback(PREFIX, NODE, on_button)
    from synox import guard
    gate = guard.of(app)
    if gate is not None and gate.scope is not None:          # 只收人與 AI：排程、常駐助理（system）、手機入口都不行
        gate.scope.restrict(NODE, callers=("human", "ai"))
    app.extras.setdefault(SYSTEM_GROUPS_KEY, {})[GROUP] = RETIRED
    index.register_system(app, GROUP, title=TITLE, group=GROUP, load="on_trigger",
                          index="使用者講了以後都要照做的習慣或規則：提議記下來（他按了才寫）",
                          triggers=["習慣", "以後都", "以後不要", "規則", "每次都"],
                          provides=["soul.propose_habit"])


def _note(app, chat_id: int, user_id: Optional[int], text: str) -> None:
    """記進 AI 的對話記憶（下一輪知道使用者按了什麼）。"""
    agent = app.extras.get("synox_agent")
    if agent is None:
        return
    try:
        agent.note(chat_id, text, user_id)
    except Exception:
        pass
