"""
「還沒裝任何工具」時的提示，與工具庫（SYNOX_Libs）在哪裡。

SYNOX 出廠不帶工具（2026-11-12，legacy/builtin-packs.md）：工具在另一個專案「SYNOX 工具庫（SYNOX_Libs）」，
一個工具一個 .synoxpack，使用者自己挑來裝。這裡只負責「告訴人去哪裡裝」，裝的流程照舊是 packs/admin.py。

- 工具庫的位置不寫死：config.json 的 `packs.library`（資料夾路徑，相對於 SYNOX 資料夾；或 https:// 網址），沒寫就只給說明文字。
- 「裝了幾個工具」＝載入成功、而且不是出廠的（connectors/ 的那幾個不算）。
- 誰用：/help 與 /start（install）、doctor（doctor_lines）、網頁設定頁（status，web/server.py）、精靈完成頁（文字在 wizard/lang）。
"""

from __future__ import annotations

import os
from typing import List, Optional

LIBRARY_NAME = "SYNOX 工具庫（SYNOX_Libs）"
HOW_TO_INSTALL = "裝法：網頁介面「設定 → 裝功能」上傳 .synoxpack、點兩下 .synoxpack，或 python -m synox install <檔>"


def library_location(config) -> str:
    """config.json packs.library 寫的工具庫位置（資料夾換成絕對路徑；網址原樣）。沒寫時：SYNOX 資料夾旁邊附的
    `tools/`（有 index.json 才算，發佈物會帶；規則在 synox/wizard/tools.py）；都沒有回 ""。"""
    from synox.wizard import tools as library_tools
    if config is None:
        from synox.config import ROOT
        return library_tools.default_location(ROOT)
    return library_tools.configured(getattr(config, "packs", None), getattr(config, "root", "") or "")


def installed_tools(app) -> list:
    """載入成功、不是出廠的 pack（使用者自己裝的工具）。"""
    from synox.packs import loader
    return [p for p in app.extras.get("synox_packs", []) if not loader.is_bundled(p.manifest)]


def where_lines(config) -> List[str]:
    where = library_location(config)
    if where:
        first = f"工具在{LIBRARY_NAME}：{where}"
    else:
        first = (f"工具在{LIBRARY_NAME}：一個工具一個 .synoxpack 檔。位置問給你 SYNOX 的人；"
                 "知道的話寫進 config.json 的 packs.library，之後這裡就會直接顯示")
    return [first, HOW_TO_INSTALL]


def empty_hint(app) -> str:
    """還沒裝任何工具時給人看的那段話；裝了就回 ""。"""
    if installed_tools(app):
        return ""
    config = app.extras.get("synox_config") or getattr(app, "config", None)
    return "\n".join(["🧰 還沒裝任何工具（SYNOX 出廠是空的，要用什麼自己裝）。"] + where_lines(config))


def status(app) -> dict:
    """網頁用：{"installed": 幾個, "empty": bool, "library": 位置或 "", "hint": [說明…]}。"""
    config = app.extras.get("synox_config") or getattr(app, "config", None)
    n = len(installed_tools(app))
    return {"installed": n, "empty": n == 0, "library": library_location(config), "hint": where_lines(config)}


def install(app) -> None:
    """/help 在還沒裝工具時多送一則提示（SDK 的 help 不改，包一層）。"""
    node = app.registry.root.children.get("help")
    if node is None or node.fn is None:
        return
    original = node.fn

    def help_with_hint(api, chat_id, user, args):
        original(api, chat_id, user, args)
        hint = empty_hint(app)
        if hint and app.registry.is_owner(user):          # 只有擁有者裝得了工具，別人看了也沒用
            api.send_message(chat_id, hint)

    node.fn = help_with_hint


def doctor_lines(config, tool_names: List[str]) -> List[str]:
    """doctor 的「工具」那一段：tool_names＝會載入的、不是出廠的 pack 名字。"""
    where = library_location(config)
    lines: List[str] = []
    if tool_names:
        lines.append(f"• 工具：裝了 {len(tool_names)} 個（{'、'.join(tool_names)}）")
    else:
        lines.append("• 工具：還沒裝任何工具（SYNOX 出廠是空的）")
    from synox.wizard import tools as library_tools
    local = where and not library_tools.is_url(where)
    if local and not os.path.isdir(where):
        lines.append(f"  ⚠️ config.json 的 packs.library 指到 {where}，但這個資料夾不存在")
    elif local and library_tools.why_not_library(where):
        lines.append(f"  ⚠️ packs.library：{library_tools.why_not_library(where)}")
    elif where:
        lines.append(f"  工具庫：{where}")
    if not tool_names or not where:
        lines += ["  " + x for x in where_lines(config)[(1 if where else 0):]]
    return lines


def start_hint(app, user) -> Optional[str]:
    """/start 的歡迎詞後面接的那段（擁有者、還沒裝工具才有）。"""
    hint = empty_hint(app)
    return hint if hint and app.registry.is_owner(user) else None
