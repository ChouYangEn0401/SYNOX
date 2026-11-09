"""
帳號：自己看自己的（me 群組）、申請升級，以及管理員那一半（user 群組）——申請和審核是同一條流程的兩端。

    /me                      查看自己的帳號資訊（任何人）
    /me_upgrade              申請升一級 → 每個管理員和擁有者收到申請＋按鈕（✅ 接受／❌ 拒絕／🔇 靜音 N 日）
    /me_role <角色>          請管理員改成指定等級（升或降）→ 收到附 /user_role 指令的通知
    /me_op [角色]            擁有者把自己設成某個角色（測試別人看到什麼；擁有者指令照樣能用）
    /user_list               列出所有人，標出待審的申請
    /user_role <id> <角色|up> 改角色（不認識的 id 先建立；待審的申請一併結案）
    /user_deny <id>          拒絕待審的申請
    按鈕 promote:<accept|deny|mute>:<id>[:天數]   綁在 user.role 上：按得動的人＝能用 /user_role 的人

兩條特別的規則（從 ClawBot 帶過來）：
- 機器擁有者受保護：別人想把他降級，動手的人反過來被降成最低一級。
- 給別人最高一級（管理員）、拿掉別人的最高一級：只有擁有者能做，有接 /sudo 的話還要先解鎖——
  這是 handler 裡唯一一個看參數決定的權限檢查（同一個 /user_role 改其他等級不需要）。

upgrades=False：只要 /me、/me_op、/user_list、/user_role（範本 B：成員靠通行證進來，不用申請）。
"""

from __future__ import annotations

from typing import Optional

from isdtelekit.core.registry import DANGER, WRITE
from isdtelekit.packs._util import NOTICE_END, NOTICE_START, parse_id, role_name, tell
from isdtelekit.users.roles import by_name, choices, next_up


def install(app, *, me_group: str = "me", admin_group: str = "user", upgrades: bool = True,
            admin_role: Optional[int] = None) -> None:
    """admin_role：誰能改別人的角色、會收到升級申請（預設角色階梯最高一級）。"""
    registry, users, limiter = app.registry, app.users, app.limiter
    roles = users.roles
    top, lowest = users.top_role, users.lowest_role
    admin_role = top if admin_role is None else admin_role
    role_choices = choices(roles)
    registry.ensure_group(me_group, "👤 我的帳號", "查看自己的等級、申請升級")
    registry.ensure_group(admin_group, "🛡 使用者", "列出使用者、改角色、審核申請", role=admin_role)

    # ── 共用 ─────────────────────────────────────────────────────────

    def protected_set(api, chat_id, actor, target_id: int, new_role) -> bool:
        """set_role，再加上擁有者保護：別人想把機器擁有者降級，動手的人被降成最低一級並通知他。"""
        owner = users.machine_owner_id
        if owner is not None and target_id == owner and new_role < top and actor.tg_id != owner:
            users.get_or_create(actor.tg_id)
            users.set_role(actor.tg_id, lowest)
            api.send_message(chat_id, f"❌ 不可降級機器擁有者 {target_id}。執行者 {actor.tg_id} 已被降為 "
                                      f"{role_name(lowest)} 作為懲罰。")
            tell(api, actor.tg_id, NOTICE_START + f"你嘗試降級機器擁有者，已被降為 {role_name(lowest)} 作為懲罰。"
                 + NOTICE_END)
            return False
        return users.set_role(target_id, new_role, actor_id=actor.tg_id)

    def top_change_refusal(actor, target_id: int, old_role, new_role) -> Optional[str]:
        """給或拿掉最高一級：只有擁有者，接了 /sudo 的話還要先解鎖。動到擁有者本人的交給 protected_set。"""
        if top not in (old_role, new_role) or old_role == new_role or target_id == registry.owner_id:
            return None
        if not registry.is_owner(actor):
            return f"❌ 只有機器擁有者能給或拿掉 {role_name(top)}。"
        if app.stepup is not None:
            if not app.stepup.configured:
                return app.stepup.unset_message
            if not registry.is_elevated(actor):
                return app.stepup.need_message
        return None

    def target_of(api, chat_id, args, usage: str) -> Optional[int]:
        if not args:
            api.send_message(chat_id, f"用法：{usage}")
            return None
        target_id = parse_id(args[0])
        if target_id is None:
            api.send_message(chat_id, "❌ 使用者 id 必須是整數。")
        return target_id

    def blocked_from_requesting(api, chat_id, user) -> bool:
        if users.has_pending_promotion(user.tg_id):
            api.send_message(chat_id, "你已有一個尚未處理的申請，請等待管理員處理或稍後再試。")
            return True
        if limiter is not None and limiter.is_penalized(user.tg_id, "no_promote"):
            api.send_message(chat_id, "🔒 你暫時被禁止提出申請，請聯絡管理員。")
            return True
        return False

    # ── 自己的帳號 ────────────────────────────────────────────────────

    def cmd_me(api, chat_id, user, args):
        api.send_message(chat_id, f"Telegram ID : {user.tg_id}\nUsername    : @{user.username}\n"
                                  f"Role        : {role_name(user.role)}")

    def cmd_upgrade(api, chat_id, user, args):
        wanted = next_up(roles, user.role)
        if wanted is None:
            api.send_message(chat_id, "你的帳號已是最高等級，無需申請升級。")
            return
        if blocked_from_requesting(api, chat_id, user):
            return
        users.mark_pending_promotion(user.tg_id)
        text = (f"📬 升級申請\n使用者：@{user.username or '(無 username)'}\nID：{user.tg_id}\n"
                f"目前等級：{role_name(user.role)}（想升到 {role_name(wanted)}）\n\n"
                f"按下面的按鈕處理，或打指令：\n  升一級：/{admin_group}_role {user.tg_id} up\n"
                f"  指定等級：/{admin_group}_role {user.tg_id} <{role_choices}>\n  拒絕：/{admin_group}_deny {user.tg_id}")
        keyboard = {"inline_keyboard": [
            [{"text": "✅ 接受", "callback_data": f"promote:accept:{user.tg_id}"},
             {"text": "❌ 拒絕", "callback_data": f"promote:deny:{user.tg_id}"}],
            [{"text": f"🔇 靜音 {days} 日", "callback_data": f"promote:mute:{user.tg_id}:{days}"} for days in (1, 3, 7)],
        ]}
        for admin in users.admins(admin_role):
            tell(api, admin, text, keyboard)
        api.send_message(chat_id, "✅ 已送出升級申請，請等待管理員審核。")

    def cmd_request_role(api, chat_id, user, args):
        if not args:
            api.send_message(chat_id, f"用法：/{me_group}_role <{role_choices}>")
            return
        wanted = by_name(roles, args[0])
        if wanted is None:
            api.send_message(chat_id, f"❌ 無效角色，選項：{role_choices}")
            return
        if blocked_from_requesting(api, chat_id, user):
            return
        users.mark_pending_promotion(user.tg_id, requested_to=int(wanted))
        notice = (f"🔔🔔🔔【權限請求】🔔🔔🔔\n使用者：@{user.username or '(無 username)'}\nID：{user.tg_id}\n"
                  f"目前等級：{role_name(user.role)}\n要求等級：{role_name(wanted)}\n\n"
                  f"管理操作：/{admin_group}_role {user.tg_id} {role_name(wanted).lower()}  或  "
                  f"/{admin_group}_deny {user.tg_id}\n────────────────────────")
        for admin in users.admins(admin_role):
            tell(api, admin, notice)
        api.send_message(chat_id, "✅ 已向管理員送出等級更動請求，請等待回覆。")

    def cmd_op(api, chat_id, user, args):
        new_role = by_name(roles, args[0]) if args else top
        if new_role is None:
            api.send_message(chat_id, f"❌ 無效角色，選項：{role_choices}")
            return
        users.get_or_create(user.tg_id)
        users.set_role(user.tg_id, new_role, actor_id=user.tg_id)
        api.send_message(chat_id, f"✅ 你的角色已設為 {role_name(new_role)}。")

    me = registry.group(me_group)
    me.leaf("info", cmd_me, "查看自己的帳號資訊", default=True)
    if upgrades:
        me.leaf("upgrade", cmd_upgrade, "申請升級一個等級，通知管理員審核", effect=WRITE)
        me.leaf("role", cmd_request_role, "請管理員把自己的等級改成指定等級（升或降）", usage=f"<{role_choices}>",
                effect=WRITE)
    me.leaf("op", cmd_op, "把自己設為某個角色（測試用；擁有者指令照樣能用）", usage=f"[{role_choices}]",
            effect=WRITE, owner_only=True)

    # ── 管理員 ───────────────────────────────────────────────────────

    def cmd_list(api, chat_id, user, args):
        everyone = users.list_all()
        if not everyone:
            api.send_message(chat_id, "目前沒有任何已知使用者。")
            return
        lines = []
        for u in everyone:
            line = f"{u.tg_id}  @{u.username or '(無)'}  [{role_name(u.role)}]"
            if users.has_pending_promotion(u.tg_id):
                _from, wanted, _ts = users.get_pending_promotion(u.tg_id)
                line += f"  ⏳ 申請{role_name(roles(wanted)) if wanted else '升一級'}"
            lines.append(line)
        api.send_message(chat_id, "\n".join(lines))

    def cmd_role(api, chat_id, user, args):
        usage = f"/{admin_group}_role <id> <{role_choices}|up>"
        target_id = target_of(api, chat_id, args, usage)
        if target_id is None:
            return
        if len(args) < 2:
            api.send_message(chat_id, f"用法：{usage}")
            return
        old_role = users.get_or_create(target_id).role
        if args[1].lower() == "up":
            new_role = next_up(roles, old_role)
            if new_role is None:
                api.send_message(chat_id, f"ℹ️ 使用者 {target_id} 已經是最高等級：{role_name(old_role)}。")
                return
        else:
            new_role = by_name(roles, args[1])
            if new_role is None:
                api.send_message(chat_id, f"❌ 無效角色：{args[1]}。可選：{role_choices}，或 up（升一級）")
                return
        refusal = top_change_refusal(user, target_id, old_role, new_role)
        if refusal:
            api.send_message(chat_id, refusal)
            return
        if not protected_set(api, chat_id, user, target_id, new_role):
            return
        api.send_message(chat_id, f"✅ 使用者 {target_id}：{role_name(old_role)} → {role_name(new_role)}")
        tell(api, target_id, NOTICE_START + f"你的帳號權限已被設定為：{role_name(new_role)}（由管理員 {user.tg_id} 操作）"
             + NOTICE_END)

    def cmd_deny(api, chat_id, user, args):
        target_id = target_of(api, chat_id, args, f"/{admin_group}_deny <id>")
        if target_id is None:
            return
        if not any(users.pop_pending_promotion(target_id)):
            api.send_message(chat_id, f"ℹ️ 使用者 {target_id} 沒有待審的申請。")
            return
        api.send_message(chat_id, f"✅ 已拒絕使用者 {target_id} 的申請。")
        tell(api, target_id, NOTICE_START + "❌ 你的申請已被拒絕。如有疑問，請聯繫管理員。" + NOTICE_END)

    adm = registry.group(admin_group)
    adm.leaf("list", cmd_list, "列出所有已知使用者（標出待審的申請）")
    adm.leaf("role", cmd_role, "設定角色或升一級（不認識的 id 會先建立；待審的申請一併結案）",
             usage=f"<id> <{role_choices}|up>", effect=DANGER)
    if not upgrades:
        return
    adm.leaf("deny", cmd_deny, "拒絕待審的申請", usage="<id>", effect=WRITE)

    # ── 審核按鈕 ─────────────────────────────────────────────────────

    def wanted_role(pending_from: int, requested: int):
        if requested:
            return roles(requested)
        return next_up(roles, roles(pending_from) if pending_from in {int(r) for r in roles} else lowest)

    def on_promote_button(api, cb):
        parts = cb.data.split(":")
        try:
            action, target_id = parts[1], int(parts[2])
            days = int(parts[3]) if len(parts) > 3 else 1
        except (IndexError, ValueError):
            api.answer_callback_query(cb.cq_id, text="資料格式錯誤。")
            return
        label = "📬 升級申請"
        clicker = users.get_or_create(cb.clicker_id)
        if action == "accept":
            # 先看再取：被擋下（例如申請成為管理員、按的人不是擁有者）時申請還留著
            peek = users.get_pending_promotion(target_id)
            wanted = wanted_role(peek[0], peek[1]) if any(peek) else None
            refusal = wanted is not None and top_change_refusal(clicker, target_id, users.get_or_create(target_id).role,
                                                                wanted)
            if refusal:
                api.answer_callback_query(cb.cq_id, text=refusal)
                return
        pending_from, requested, ts = users.pop_pending_promotion(target_id)   # 兩個人同時按只有一個拿到
        if not (pending_from or requested or ts):
            api.answer_callback_query(cb.cq_id, text="此申請已被處理或不存在。")
            api.remove_buttons(cb.chat_id, cb.message_id)
            return
        if action == "mute":
            if limiter is None:
                api.answer_callback_query(cb.cq_id, text="速率限制模組未啟用。")
                return
            expiry = limiter.mute_user(target_id, days)
            api.edit_message_text(cb.chat_id, cb.message_id,
                                  f"{label} — 已處理\nID：{target_id}\n\n結果：已靜音 {days} 日（到期：{expiry}）。")
            tell(api, target_id, f"🔕 你已被管理員靜音 {days} 日，期間無法使用指令。到期日：{expiry}")
            api.answer_callback_query(cb.cq_id, text=f"已靜音 {days} 日。")
        elif action == "deny":
            api.edit_message_text(cb.chat_id, cb.message_id,
                                  f"{label} — 已拒絕\nID：{target_id}\n\n結果：管理員拒絕此申請。")
            tell(api, target_id, "🔔 你的升級申請已被管理員拒絕。")
            api.answer_callback_query(cb.cq_id, text="已拒絕。")
        elif action == "accept":
            new_role = wanted_role(pending_from, requested)
            if new_role is None:
                api.answer_callback_query(cb.cq_id, text="目標已是最高等級。")
                return
            if protected_set(api, cb.chat_id, clicker, target_id, new_role):
                api.edit_message_text(cb.chat_id, cb.message_id,
                                      f"{label} — 已接受\nID：{target_id}\n\n結果：已升級為 {role_name(new_role)}")
                tell(api, target_id, "🔔 你的升級申請已被接受，權限已更新。")
                api.answer_callback_query(cb.cq_id, text="已接受。")
            else:
                api.answer_callback_query(cb.cq_id, text="升級失敗。")
        else:
            api.answer_callback_query(cb.cq_id, text="未知操作。")

    registry.bind_callback("promote:", f"{admin_group}.role", on_promote_button)
