"""
/help：依指令樹分頁——第一頁是根下的基本指令，之後每個群組一頁（順序就是群組定義的順序）。

只列「這個人現在能用」的指令：可見性直接問 registry.visible()，跟實際執行時用的是同一個 authorize()，
所以不會有「/help 看得到但按了被拒」或反過來的情況，也不需要另外維護隱藏清單。

也支援 /help <群組>（例 /help remind、/help 筆記）、/help all。裝了這個 pack，直接打群組名（/user）
顯示的那組指令也換成這裡的版面（dispatcher.group_menu）。

callback_data：help:pg:<idx>（idx 是這個人可見頁面的索引）、help:menu。
"""

from __future__ import annotations

from typing import List, Tuple

from isdtelekit.core.registry import DANGER, CommandRegistry, Node

BASIC_TITLE = "🔰 基本"


def _line(node: Node) -> str:
    usage = f" {node.usage}" if node.usage else ""
    mark = (" 🔐" if node.policy.elevated else "") + (" ⚠️" if node.effect == DANGER else "")
    return f"  {node.command}{usage} — {node.summary}{mark}"


def pages(registry: CommandRegistry, user) -> List[Tuple[str, str, List[Node]]]:
    """[(key, 標題, [可用的葉節點…]), …]"""
    out = []
    basics = [n for n in registry.root.children.values() if not n.is_group and registry.visible(user, n)]
    if basics:
        out.append(("basic", BASIC_TITLE, basics))
    for group in registry.root.children.values():
        if not group.is_group:
            continue
        leaves = [n for n in group.walk() if not n.is_group and registry.visible(user, n)]
        if leaves:
            out.append((group.name, group.title, leaves))
    return out


def render_group(registry: CommandRegistry, user, group: Node) -> str:
    leaves = [n for n in group.walk() if not n.is_group and registry.visible(user, n)]
    if not leaves:
        return "你沒有這個群組裡的任何指令。"
    head = f"{group.title}" + (f"\n{group.summary}" if group.summary else "")
    return "\n".join([head, ""] + [_line(n) for n in leaves])


def _render_page(all_pages, idx: int) -> Tuple[str, dict]:
    n = len(all_pages)
    idx %= n
    _key, title, leaves = all_pages[idx]
    lines = [f"📖 指令選單  ({idx + 1}/{n})", "", title] + [_line(x) for x in leaves]
    lines += ["", "💡 /help <分類> 直接跳，/help all 看全部；⚠️ 表示會對外產生影響，🔐 表示要先 /sudo 解鎖。"]
    keyboard = {"inline_keyboard": [
        [{"text": "◀️ 上一頁", "callback_data": f"help:pg:{idx - 1}"},
         {"text": f"{idx + 1}/{n}", "callback_data": "help:menu"},
         {"text": "下一頁 ▶️", "callback_data": f"help:pg:{idx + 1}"}],
        [{"text": "☰ 分類目錄", "callback_data": "help:menu"}],
    ]}
    return "\n".join(lines), keyboard


def _render_menu(all_pages) -> Tuple[str, dict]:
    rows, row = [], []
    for i, (_key, title, leaves) in enumerate(all_pages):
        row.append({"text": f"{title} ({len(leaves)})", "callback_data": f"help:pg:{i}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return "📖 指令選單 · 分類目錄\n選一個分類：", {"inline_keyboard": rows}


def _find(all_pages, query: str) -> int:
    q = query.strip().lower()
    for i, (key, title, _leaves) in enumerate(all_pages):
        if q == key or q in title.lower():
            return i
    return -1


def install(app) -> None:
    registry = app.registry

    def cmd_help(api, chat_id, user, args):
        all_pages = pages(registry, user)
        if not all_pages:
            api.send_message(chat_id, "目前沒有可用指令。")
            return
        if args and args[0].lower() in ("all", "全部"):
            out = ["📖 指令總覽（你能用的全部指令）"]
            for _key, title, leaves in all_pages:
                out += ["", title] + [_line(x) for x in leaves]
            api.send_message(chat_id, "\n".join(out))
            return
        idx = 0
        if args:
            idx = _find(all_pages, args[0])
            if idx < 0:
                names = "、".join(key for key, _t, _l in all_pages)
                api.send_message(chat_id, f"找不到分類「{args[0]}」。\n可用分類：{names}\n（或 /help all 看全部）")
                return
        text, keyboard = _render_page(all_pages, idx)
        api.send_message(chat_id, text, reply_markup=keyboard)

    def on_help_button(api, cb):
        user = app.users.get_or_create(cb.clicker_id)
        all_pages = pages(registry, user)
        if not all_pages:
            api.answer_callback_query(cb.cq_id, text="目前沒有可用指令。")
            return
        parts = cb.data.split(":")
        if len(parts) > 1 and parts[1] == "menu":
            text, keyboard = _render_menu(all_pages)
        else:
            try:
                idx = int(parts[2])
            except (IndexError, ValueError):
                idx = 0
            text, keyboard = _render_page(all_pages, idx)
        api.edit_message_text(cb.chat_id, cb.message_id, text, reply_markup=keyboard)
        api.answer_callback_query(cb.cq_id)

    registry.root_leaf("help", cmd_help, "顯示可用指令（依分類分頁）", usage="[分類|all]")
    registry.bind_callback("help:", "help", on_help_button)
    app.dispatcher.group_menu = lambda user, node: render_group(registry, user, node)
