"""
Telegram 輸入框旁的指令選單（setMyCommands）：不用每次都把指令打完。

每個人看到的是**自己能用的**指令（同一個 registry.authorize）：
  - default scope：還沒登記過的人（最低一級）看到的那份
  - 每個比最低一級高的人、以及機器擁有者：各一份 chat scope（只在跟 bot 的私訊裡出現）
🔐 的指令照樣列出（說明前面標 🔐），點了沒解鎖會照常被擋、附「先 /sudo」。

Telegram 一份選單最多 100 個。超過 TARGET 時，照 registry.menu_collapse_order（bot 的 layout 宣告；沒宣告就照
群組定義順序倒過來）把比較少用的群組收成一個入口（`/limit` 這種群組名本身就是指令，點了列出那組的指令），
所以每個指令都還是點得到。有主要動作（default 葉節點）的群組沒辦法收成入口，就只留那個主要動作。

什麼時候同步：開始收 Telegram 時一次（背景執行緒），有人的角色改變時那個人一次（host/app.py 接好了）。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from isdtelekit.core.registry import TYPED, CommandRegistry, Node
from isdtelekit.users.models import User

MAX_COMMANDS = 100
TARGET = 90                  # 留一點空間
DESCRIPTION_MAX = 60         # Telegram 上限 256；太長在手機上會被截掉，反而看不懂

Entry = Tuple[str, str]      # (指令名，不含 /, 說明)


def _visible(registry: CommandRegistry, user: User, node: Node) -> bool:
    decision = registry.authorize(user, node, TYPED, user.tg_id)
    return decision.allowed or decision.needs_sudo


def _describe(node: Node) -> str:
    text = " ".join((node.summary or node.title or "").split())
    if len(text) > DESCRIPTION_MAX:
        text = text[:DESCRIPTION_MAX - 1] + "…"
    return ("🔐 " if node.policy.elevated else "") + (text or node.command)


def collapse_order(registry: CommandRegistry) -> Tuple[str, ...]:
    """塞不下時先收哪些群組：registry 有宣告就照它；沒宣告就照群組定義的順序倒過來。"""
    declared = tuple(getattr(registry, "menu_collapse_order", ()) or ())
    if declared:
        return declared
    return tuple(name for name, node in reversed(list(registry.root.children.items())) if node.is_group)


def menu_for(registry: CommandRegistry, user: User, target: int = TARGET) -> List[Entry]:
    """這個人的選單（照 /help 的群組順序）。"""
    groups: Dict[str, List[Node]] = {}
    for node in registry.leaves():
        if not _visible(registry, user, node):
            continue
        top = node.path.split(".")[0] if "." in node.path else ""
        groups.setdefault(top, []).append(node)
    collapsed: Dict[str, Optional[Node]] = {}

    def count() -> int:
        return sum(1 if g in collapsed else len(nodes) for g, nodes in groups.items())

    for name in collapse_order(registry):
        if count() <= target:
            break
        if name not in groups or len(groups[name]) <= 1:
            continue
        collapsed[name] = next((n for n in groups[name] if n.default), None)   # None → 收成「/群組」入口
    entries: List[Entry] = []
    for name, nodes in groups.items():
        if name in collapsed:
            keep = collapsed[name]
            if keep is not None:
                entries.append((keep.command.lstrip("/"), _describe(keep)))
            else:
                group = registry.node(name)
                title = (group.title if group is not None else name) or name
                entries.append((name, f"{title}（{len(nodes)} 個指令，點了列出）"[:DESCRIPTION_MAX + 20]))
            continue
        entries += [(n.command.lstrip("/"), _describe(n)) for n in nodes]
    return entries[:MAX_COMMANDS]


def _push(api, entries: List[Entry], scope: dict) -> bool:
    result = api.set_my_commands(entries, scope=scope) or {}
    ok = bool(result.get("ok")) if isinstance(result, dict) else False
    if not ok:
        logging.warning("[MENU] setMyCommands %s failed: %s", scope, result)
    return ok


def sync_user(api, registry: CommandRegistry, user: User) -> bool:
    return _push(api, menu_for(registry, user), {"type": "chat", "chat_id": user.tg_id})


def sync_menus(api, registry: CommandRegistry, user_manager, owner_id: Optional[int]) -> Dict[str, int]:
    """全部同步一次。回傳 {"default": 幾個, "users": 幾個人, "failed": 幾份失敗}。"""
    report = {"default": 0, "users": 0, "failed": 0}
    newcomer = User(tg_id=0, username="", role=registry.lowest_role)
    default = menu_for(registry, newcomer)
    report["default"] = len(default)
    if not _push(api, default, {"type": "default"}):
        report["failed"] += 1
    for user in user_manager.list_all():
        if user.tg_id <= 0 or (user.role <= registry.lowest_role and user.tg_id != owner_id):
            continue
        if sync_user(api, registry, user):
            report["users"] += 1
        else:
            report["failed"] += 1
    logging.info("[MENU] synced: default=%s users=%s failed=%s", report["default"], report["users"], report["failed"])
    return report
