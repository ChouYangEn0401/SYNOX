"""
Web UI（架構 v1 §5）：本機 127.0.0.1 的網頁介面——對話頁、工具頁、設定頁。網頁只是另一條 channel（WebChannel），
走同一個 dispatcher、同一個 authorize。

  /web       拿一個一次性登入連結（7 天、只給你、只能用一次）。個人版：擁有者；伺服器版：每個人（看到的只有自己的）
  /web_off   擁有者：關掉網頁介面、登出所有網頁 session，到重開 bot 之前不再開

config.json：
  "web": {"enabled": true, "port": 8830, "public_url": ""}
  public_url：營運者自己架了反向代理（要有 TLS）時，登入連結用這個網址開頭；沒填就是 http://127.0.0.1:<port>。

開不起來（埠被占用）只記錯誤，bot 其他部分照常跑；/web 會說原因。
"""

from __future__ import annotations

import os
from typing import Optional

from isdtelekit.core.registry import WRITE

from synox.packs.loader import group_policy
from synox.web.server import HOST, WebUI, login_link


def install(app, config, vault=None, *, pack_dirs=None, config_path: Optional[str] = None) -> WebUI:
    ui = WebUI(app, config, vault, pack_dirs=pack_dirs, config_path=config_path)
    app.extras["synox_web"] = ui
    registry = app.registry
    server = getattr(config, "mode", "personal") == "server"
    registry.ensure_group("webui", "🌐 網頁介面", "在電腦的瀏覽器裡用 SYNOX：對話、工具、設定", bare=True,
                          **group_policy(app, "everyone" if server else "owner", server))
    g = registry.group("webui")

    def cmd_web(api, chat_id, user, args):
        if not ui.enabled:
            api.send_message(chat_id, "🌐 網頁介面沒有開（config.json 的 web.enabled 是 false）。")
            return
        if ui.disabled:
            api.send_message(chat_id, "🌐 網頁介面被 /web_off 關掉了，重開 SYNOX 才會再開。")
            return
        link = ui.login_link(user.tg_id)
        where = "" if (config.web or {}).get("public_url") else \
            "\n要在跑 SYNOX 的那台電腦上打開（只聽 127.0.0.1）。"
        warn = f"\n⚠️ 現在網頁介面沒有在跑：{ui.error}" if ui.error else ""
        api.send_message(chat_id, f"🌐 網頁介面的登入連結（只能用一次、7 天內有效、只給你，不要轉給別人）：\n{link}"
                                  f"{where}{warn}")

    def cmd_off(api, chat_id, user, args):
        ui.turn_off()
        api.send_message(chat_id, "🌐 網頁介面關掉了，所有網頁登入都登出了。重開 SYNOX 才會再開。")

    g.leaf("web", cmd_web, "拿網頁介面的登入連結（一次性、7 天）", private_only=True, ai=False)
    g.leaf("web_off", cmd_off, "關掉網頁介面（重開 bot 才會再開）", owner_only=True, effect=WRITE, ai=False)
    if ui.enabled:
        app.on_start.append(lambda _app: ui.start())
        app.on_stop.append(lambda _app: ui.stop())
    return ui


def issue_owner_link(config) -> str:
    """精靈最後一頁用：bot 還沒開起來也能產生擁有者的登入連結（寫進 data/web_tokens.json）。"""
    from synox.web.tokens import LoginTokens
    tokens = LoginTokens(os.path.join(config.data_dir, "web_tokens.json"))
    return login_link(config, tokens.issue(config.owner_id))


__all__ = ["HOST", "WebUI", "install", "issue_owner_link", "login_link"]
