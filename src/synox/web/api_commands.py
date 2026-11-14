"""
網頁的「說明與範例」與「我的指令」：

    GET  /api/help              「💡 範例」面板（static/helpdock.js）：這個人看得到的工具 → 指令的白話與範例（照他的叫法）
    GET  /api/aliases           設定 →「⌨️ 我的指令」（static/aliases.js）：他的符號、名字、可以取名字的指令、工具附的建議名字
    POST /api/aliases           存：{"prefix": "@", "names": {路徑: [名字…]}}｜{"reset": true}；錯了回 400＋每一格的白話原因
    POST /api/aliases/preview   試打：{"prefix", "names", "text"} → 照**還沒存**的表，這句話會變成什麼（不執行、不存）

只動這個人自己的那一份（session 的人；沒有「改別人的」參數）。POST 都經 server.route 的 CSRF 檢查。
規則都在 synox/aliases.py（這裡只是轉接）。
"""

from __future__ import annotations

import logging
from typing import Tuple

from synox import aliases
from synox.helpui import model

PREFIX_LABELS = {"/": "/（原本的）", "$": "$", "!": "!", ".": ".", "~": "~", ";": ";", ",": ",", "@": "@", "+": "+",
                 aliases.NONE: "不用符號（進階）"}


def help_view(app, user) -> dict:
    return model.help_json(app, user)


def targets(app, user) -> list:
    """可以取名字的指令：這個人看得到的葉節點（＋沒有主要動作的群組：打群組名＝那一組的選單）。"""
    out = []
    for t in model.tools(app, user):
        group = app.registry.node(t.id) if t.id != model.BASICS_ID else None
        if group is not None and group.is_group and not any(c.default for c in group.children.values()):
            out.append({"path": group.path, "command": aliases.command_of(group), "title": "整組的選單",
                        "tool": t.title})
        for n in t.nodes:
            out.append({"path": n.path, "command": n.command, "title": model.title_of(app, n), "tool": t.title})
    return out


def suggestions(app, user, tab: aliases.Table) -> list:
    """工具附的建議名字（pack.json 的 help.commands.<指令>.alias_suggest）：還沒用、也不撞名的才列。按了才變成他的。"""
    used = set(tab.lookup())
    out = []
    for t in model.tools(app, user):
        for n in t.nodes:
            for name in model.ex_mod.doc_of(app, n).get("alias_suggest") or []:
                key = aliases.normalize(name)
                if key in used or app.registry.is_known(key) or name in (tab.names.get(n.path) or ()):
                    continue
                out.append({"path": n.path, "name": name, "command": n.command, "title": model.title_of(app, n)})
                used.add(key)
    return out


def get(app, user) -> Tuple[int, dict]:
    st = aliases.store(app)
    if st is None:
        return 404, {"error": "這一版沒有自訂指令。"}
    out = {"prefixes": [{"value": p, "label": PREFIX_LABELS.get(p, p)} for p in aliases.PREFIXES],
           "warnings": aliases.PREFIX_WARNINGS, "escape": aliases.ESCAPE,
           "limits": {"name": aliases.MAX_NAME, "per_command": aliases.MAX_PER_NODE, "total": aliases.MAX_TOTAL},
           "targets": targets(app, user)}
    try:
        tab = st.table(user.tg_id)
    except Exception as e:                  # 保管箱解不開：給畫面看、但存檔會被擋（不蓋掉原本的檔）
        logging.warning("[WEB] aliases of %s unreadable: %s", user.tg_id, type(e).__name__)
        out.update(prefix=aliases.DEFAULT_PREFIX, names={}, suggestions=[], conflicts=[],
                   load_error="你的自訂指令讀不到（保管箱解不開），先照原本的 / 用；存檔前請先看 doctor。")
        return 200, out
    out.update(prefix=tab.prefix, names={p: list(n) for p, n in tab.names.items()},
               suggestions=suggestions(app, user, tab), conflicts=aliases.conflicts(app, tab))
    return 200, out


def save(app, user, data: dict) -> Tuple[int, dict]:
    st = aliases.store(app)
    if st is None:
        return 404, {"error": "這一版沒有自訂指令。"}
    try:
        st.table(user.tg_id)                # 讀不到就不准存（絕不當成空的再蓋過去）
    except Exception:
        return 409, {"error": "你的自訂指令讀不到（保管箱解不開），為了不蓋掉原本的設定，這次沒有存。"}
    if data.get("reset") is True:
        st.save(user.tg_id, aliases.EMPTY)
        logging.info("[WEB] %s reset custom commands", user.tg_id)
        return 200, {"ok": True, "prefix": aliases.DEFAULT_PREFIX, "names": {}}
    tab, errors = aliases.check(app, user, data)
    if tab is None:
        return 400, {"error": errors[0]["error"] if len(errors) == 1 else f"有 {len(errors)} 個地方要改", "errors": errors}
    st.save(user.tg_id, tab)
    logging.info("[WEB] %s saved custom commands (prefix %r, %d names)", user.tg_id, tab.prefix,
                 sum(len(n) for n in tab.names.values()))
    return 200, {"ok": True, "prefix": tab.prefix, "names": {p: list(n) for p, n in tab.names.items()}}


def preview(app, user, data: dict) -> Tuple[int, dict]:
    text = str(data.get("text") or "")[:200]
    tab, errors = aliases.check(app, user, data)
    if tab is None:
        return 400, {"error": errors[0]["error"], "errors": errors}
    new = aliases.rewrite_with(app, tab, text)
    result = text.strip() if new is None else new
    command = result.startswith("/") and app.registry.resolve(result)[0] is not None
    return 200, {"text": text, "result": result, "command": bool(command)}
