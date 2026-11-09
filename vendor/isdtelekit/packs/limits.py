"""
限制與配額：管理員的 /limit_*，以及使用者「請擁有者幫我解除」的兩個申請（/me_quota_reset、/me_quota_free）。

    /limit_list                          現在被封鎖、處罰、靜音的人
    /limit_unblock <id>                  解除自動封鎖
    /limit_penalize <id> <種類> <15m|1h|1d>   ignore_messages（當作沒收到）／no_self_service／no_promote
    /limit_unpenalize <id> [種類]
    /limit_mute <id> <天數> / /limit_unmute <id>   不能用指令（自由文字照收）
    /limit_free <id> <天數>              N 天不受任何配額（只有擁有者）
    /limit_reset <id>                    清掉今天的用量（只有擁有者）
    /me_quota_reset、/me_quota_free <天數>  使用者申請 → 只有擁有者收到按鈕（free:／reset:，綁在 limit.free／limit.reset）

申請的兩個指令標了 quota_exempt：今天的訊息用完了也送得出去（不然用完了就沒辦法申請解除）；
靜音與 no_self_service 罰則照樣擋（limits/rate_limiter.py 的 admit）。
"""

from __future__ import annotations

from typing import Optional

from isdtelekit.core.registry import DANGER, WRITE
from isdtelekit.limits.rate_limiter import PENALTY_KINDS
from isdtelekit.packs._util import parse_duration, parse_id, tell


def install(app, *, group: str = "limit", me_group: str = "me", admin_role: Optional[int] = None,
            self_service: bool = True) -> None:
    """self_service=False：不要 /me_quota_reset、/me_quota_free。"""
    limiter, registry, users = app.limiter, app.registry, app.users
    if limiter is None:
        raise ValueError("packs.limits 需要 build_app(use_limiter=True)。")
    admin_role = users.top_role if admin_role is None else admin_role
    registry.ensure_group(group, "🚦 限制", "封鎖、罰則、靜音、配額", role=admin_role)
    kinds = "|".join(PENALTY_KINDS)

    def target(api, chat_id, args, usage: str) -> Optional[int]:
        if not args:
            api.send_message(chat_id, f"用法：{usage}")
            return None
        target_id = parse_id(args[0])
        if target_id is None:
            api.send_message(chat_id, "❌ 使用者 id 必須是整數。")
        return target_id

    def days_of(api, chat_id, text) -> Optional[int]:
        days = parse_id(text)
        if days is None:
            api.send_message(chat_id, "❌ 天數必須是整數。")
            return None
        if days <= 0:
            api.send_message(chat_id, "❌ 天數必須大於 0。")
            return None
        return days

    # ── 管理員 ───────────────────────────────────────────────────────

    def cmd_list(api, chat_id, user, args):
        blocked, penalties, muted = limiter.list_blocked(), limiter.list_penalties(), limiter.list_muted()
        if not (blocked or penalties or muted):
            api.send_message(chat_id, "目前沒有人被封鎖、處罰或靜音。")
            return
        lines = []
        if blocked:
            lines.append(f"🚫 速率封鎖（解除：/{group}_unblock <id>）")
            lines += [f"  {r['tg_id']}  @{r.get('username') or '(無)'}  attacks={r['attack_count']}  "
                      f"blocked_at={r['blocked_at']}" for r in blocked]
        if penalties:
            lines.append(f"⚠️ 罰則（移除：/{group}_unpenalize <id> [種類]）")
            lines += [f"  {tg}: " + ", ".join(f"{k} 到 {v}" for k, v in ent.items()) for tg, ent in penalties.items()]
        if muted:
            lines.append(f"🔕 靜音（解除：/{group}_unmute <id>）")
            lines += [f"  {tg}: 到 {until}" for tg, until in muted.items()]
        api.send_message(chat_id, "\n".join(lines))

    def cmd_unblock(api, chat_id, user, args):
        target_id = target(api, chat_id, args, f"/{group}_unblock <id>")
        if target_id is None:
            return
        api.send_message(chat_id, f"✅ 使用者 {target_id} 已解除封鎖。" if limiter.unblock(target_id)
                         else f"❌ 找不到封鎖紀錄：{target_id}。")

    def cmd_penalize(api, chat_id, user, args):
        usage = f"/{group}_penalize <id> <{kinds}> <15m|1h|1d>"
        if len(args) < 3:
            api.send_message(chat_id, f"用法：{usage}")
            return
        target_id, kind, seconds = parse_id(args[0]), args[1], parse_duration(args[2])
        if target_id is None:
            api.send_message(chat_id, "❌ 使用者 id 必須是整數。")
            return
        if kind not in PENALTY_KINDS:
            api.send_message(chat_id, f"❌ 罰則種類只有：{kinds}")
            return
        if seconds is None:
            api.send_message(chat_id, "❌ 時間格式錯誤，請用數字加單位：s/m/h/d，例如 15m、1h、1d")
            return
        expiry = limiter.set_penalty(target_id, kind, seconds)
        api.send_message(chat_id, f"✅ 已對使用者 {target_id} 設定 {kind}，到期：{expiry}")
        tell(api, target_id, f"⚠️ 你已被管理員設定 {kind}（持續至 {expiry}），期間部分功能會被限制。")

    def cmd_unpenalize(api, chat_id, user, args):
        target_id = target(api, chat_id, args, f"/{group}_unpenalize <id> [種類]")
        if target_id is None:
            return
        kind = args[1] if len(args) > 1 else None
        if limiter.clear_penalty(target_id, kind):
            api.send_message(chat_id, f"✅ 已移除使用者 {target_id} 的罰則{(' ' + kind) if kind else '（全部）'}。")
        else:
            api.send_message(chat_id, "❌ 找不到目標或罰則不存在。")

    def cmd_mute(api, chat_id, user, args):
        if len(args) < 2:
            api.send_message(chat_id, f"用法：/{group}_mute <id> <天數>")
            return
        target_id = parse_id(args[0])
        if target_id is None:
            api.send_message(chat_id, "❌ 使用者 id 必須是整數。")
            return
        days = days_of(api, chat_id, args[1])
        if days is None:
            return
        expiry = limiter.mute_user(target_id, days)
        api.send_message(chat_id, f"✅ 使用者 {target_id} 靜音到 {expiry}。")
        tell(api, target_id, f"🔕 你已被管理員靜音 {days} 日，期間無法使用指令。到期日：{expiry}")

    def cmd_unmute(api, chat_id, user, args):
        target_id = target(api, chat_id, args, f"/{group}_unmute <id>")
        if target_id is None:
            return
        api.send_message(chat_id, f"✅ 使用者 {target_id} 解除靜音。" if limiter.unmute_user(target_id)
                         else f"ℹ️ 使用者 {target_id} 沒有被靜音。")

    def cmd_free(api, chat_id, user, args):
        if len(args) < 2:
            api.send_message(chat_id, f"用法：/{group}_free <id> <天數>")
            return
        target_id = parse_id(args[0])
        if target_id is None:
            api.send_message(chat_id, "❌ 使用者 id 必須是整數。")
            return
        days = days_of(api, chat_id, args[1])
        if days is None:
            return
        expiry = limiter.free_rate_limit(target_id, days)
        api.send_message(chat_id, f"✅ 使用者 {target_id} 已獲得 {days} 天速率限制豁免（到期日：{expiry}）。")
        tell(api, target_id, f"🎁 你已獲得 {days} 天速率限制豁免，所有每日配額豁免至 {expiry}。")

    def cmd_reset(api, chat_id, user, args):
        target_id = target(api, chat_id, args, f"/{group}_reset <id>")
        if target_id is None:
            return
        limiter.reset_rate_limit(target_id)
        api.send_message(chat_id, f"✅ 使用者 {target_id} 今日配額使用量已重置為零。")
        tell(api, target_id, "🔄 你今日的速率限制配額已被管理員重置。")

    g = registry.group(group)
    g.leaf("list", cmd_list, "現在被封鎖、處罰、靜音的人")
    g.leaf("unblock", cmd_unblock, "解除使用者封鎖", usage="<id>", effect=DANGER)
    g.leaf("penalize", cmd_penalize, "設定臨時罰則", usage=f"<id> <{kinds}> <15m|1h|1d>", effect=DANGER)
    g.leaf("unpenalize", cmd_unpenalize, "移除罰則（或全部）", usage="<id> [種類]", effect=DANGER)
    g.leaf("mute", cmd_mute, "靜音 N 天（不能用指令）", usage="<id> <天數>", effect=DANGER)
    g.leaf("unmute", cmd_unmute, "解除靜音", usage="<id>", effect=DANGER)
    g.leaf("free", cmd_free, "授予使用者 N 天速率限制豁免", usage="<id> <天數>", effect=DANGER, owner_only=True)
    g.leaf("reset", cmd_reset, "重置使用者今日配額", usage="<id>", effect=DANGER, owner_only=True)
    if not self_service:
        return

    # ── 使用者的申請（只有擁有者收到按鈕：limit.free / limit.reset 是 owner_only）────────────────

    registry.ensure_group(me_group, "👤 我的帳號", "查看自己的等級、申請升級")

    def request(api, user, title: str, extra: str, prefix: str, tail: str) -> None:
        note = f"🔔 {title} 請求通知\n使用者：@{user.username or '(無 username)'}\nID：{user.tg_id}\n{extra}\n管理員請選擇："
        keyboard = {"inline_keyboard": [
            [{"text": "✅ 接受", "callback_data": f"{prefix}:accept:{user.tg_id}{tail}"},
             {"text": "❌ 拒絕", "callback_data": f"{prefix}:deny:{user.tg_id}{tail}"}],
            [{"text": f"🔇 靜音 {d} 日", "callback_data": f"{prefix}:mute:{user.tg_id}:{d}"} for d in (1, 3)],
        ]}
        tell(api, app.owner_id, note, keyboard)

    def cmd_quota_reset(api, chat_id, user, args):
        request(api, user, f"/{group}_reset", "", "reset", "")
        api.send_message(chat_id, "✅ 已向機器擁有者送出重置配額請求，請等待確認。")

    def cmd_quota_free(api, chat_id, user, args):
        if not args:
            api.send_message(chat_id, f"用法：/{me_group}_quota_free <天數>")
            return
        days = days_of(api, chat_id, args[0])
        if days is None:
            return
        request(api, user, f"/{group}_free", f"申請天數：{days}\n", "free", f":{days}")
        api.send_message(chat_id, "✅ 已向機器擁有者送出豁免申請，請等待確認。")

    me = registry.group(me_group)
    me.leaf("quota_reset", cmd_quota_reset, "請擁有者重置自己今日的配額", effect=WRITE, quota_exempt=True)
    me.leaf("quota_free", cmd_quota_free, "申請 N 天不受速率限制", usage="<天數>", effect=WRITE, quota_exempt=True)

    def on_quota_button(kind: str):
        label = "🔔 豁免申請" if kind == "free" else "🔔 重置請求"

        def handler(api, cb):
            parts = cb.data.split(":")
            try:
                action, target_id = parts[1], int(parts[2])
                days = int(parts[3]) if len(parts) > 3 else 1
            except (IndexError, ValueError):
                api.answer_callback_query(cb.cq_id, text="資料格式錯誤。")
                return
            if action == "mute":
                expiry = limiter.mute_user(target_id, days)
                api.edit_message_text(cb.chat_id, cb.message_id,
                                      f"{label} — 已處理\nID：{target_id}\n\n結果：已靜音 {days} 日（到期：{expiry}）。")
                tell(api, target_id, f"🔕 你已被管理員靜音 {days} 日，期間無法使用指令。到期日：{expiry}")
                api.answer_callback_query(cb.cq_id, text=f"已靜音 {days} 日。")
            elif action == "deny":
                api.edit_message_text(cb.chat_id, cb.message_id,
                                      f"{label} — 已拒絕\nID：{target_id}\n\n結果：管理員拒絕此申請。")
                tell(api, target_id, "❌ 你的申請已被管理員拒絕。")
                api.answer_callback_query(cb.cq_id, text="已拒絕。")
            elif action == "accept" and kind == "free":
                expiry = limiter.free_rate_limit(target_id, days)
                api.edit_message_text(cb.chat_id, cb.message_id,
                                      f"{label} — 已接受\nID：{target_id}\n\n結果：已授予 {days} 天豁免（到期：{expiry}）。")
                tell(api, target_id, f"🎉 你的豁免已被授予：{days} 天（到期：{expiry}）。")
                api.answer_callback_query(cb.cq_id, text="已授予豁免。")
            elif action == "accept":
                limiter.reset_rate_limit(target_id)
                api.edit_message_text(cb.chat_id, cb.message_id,
                                      f"{label} — 已接受\nID：{target_id}\n\n結果：今日配額已被重置。")
                tell(api, target_id, "🔄 你的今日配額已被管理員重置。")
                api.answer_callback_query(cb.cq_id, text="已重置。")
            else:
                api.answer_callback_query(cb.cq_id, text="未知操作。")
        return handler

    registry.bind_callback("free:", f"{group}.free", on_quota_button("free"))
    registry.bind_callback("reset:", f"{group}.reset", on_quota_button("reset"))
