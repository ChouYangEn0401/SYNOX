"""
build()：SynoxConfig → isdtelekit.build_app → 基本指令（伺服器版多 accounts、limits；還沒裝工具時 /start、/help
多一段「去哪裡裝」，packs/library.py）→ ⏰ 提醒（系統）（schedule.install_system_remind）→ packs.load_all
→ agent.install → runtime.install（排程迴圈、心跳、常駐助理）→ schedule.install → web.install（本機網頁介面）。

    config = SynoxConfig.load()
    app = build(config)
    app.run()              # 收 Telegram（Start.bat）；app.run_console() 在終端機試（Console.bat）

測試：build(config, home=FakeChannel(), adapter=FakeAdapter([...]), vault=Vault(...)) 再包成 SDK 的 BotHarness。
"""

from __future__ import annotations

import logging
from typing import Optional

from isdtelekit import build_app
from isdtelekit.host.app import App
from isdtelekit.packs import accounts, basics, help as help_pack, limits

from synox import agent, discord, policy, runtime, schedule, web
from synox.config import SynoxConfig
from synox.llm import make_adapter
from synox.llm.base import LLMError
from synox.packs import library, loader
from synox.vault import open_vault

GREETING = "👋 我在了，按 /help 看我會什麼。"
_UNSET = object()


def welcome(user) -> str:
    return ("👋 嗨！我是 SYNOX，在你自己電腦上跑的小助手。\n"
            "按 /help 看我會什麼；也可以直接跟我說人話（例如「幫我記一筆 80 元咖啡」）。")


def welcome_server(user) -> str:
    return ("👋 嗨！這是一支 SYNOX 小助手。\n"
            "按 /help 看你現在能用什麼；/me 看自己的帳號，/me_upgrade 請管理員讓你用更多功能。")


def install_server_packs(app) -> None:
    """伺服器版（mode=server）才裝：帳號（/me、/me_upgrade、/user_list、/user_role…）與限制（/limit_*）。"""
    accounts.install(app)
    limits.install(app)


def build(config: SynoxConfig, *, home=None, adapter=_UNSET, vault=_UNSET, pack_dirs=None,
          config_path: Optional[str] = None) -> App:
    if pack_dirs is None:                      # 沒指定＝SYNOX 的 packs/（安裝的落點）＋ config.json 的 packs.dirs
        pack_dirs = config.pack_dirs() if hasattr(config, "pack_dirs") else loader.PACK_DIRS
    app = build_app(config, home=home)
    policy.install(app)                        # SDK 的 authorize 改走 synox/policy.py 的 decide（能力上限、bot 範圍）
    app.extras["synox_config"] = config
    app.extras["synox_pack_dirs"] = tuple(pack_dirs)
    if vault is _UNSET:
        try:
            vault = open_vault(config)
        except Exception as e:                 # 金鑰檔壞掉／換了電腦：pack 照樣載入，要保管箱的那些會報錯
            logging.error("[VAULT] cannot open: %s", e)
            app.extras["vault_error"] = str(e)
            vault = None
    app.extras["vault"] = vault
    server = getattr(config, "mode", "personal") == "server"

    def greet(u) -> str:
        text = welcome(u) if not server or app.registry.is_owner(u) else welcome_server(u)
        hint = library.start_hint(app, u)            # 出廠不帶工具：還沒裝的話告訴擁有者去哪裡裝
        return f"{text}\n\n{hint}" if hint else text

    basics.install(app, welcome=greet)
    help_pack.install(app)
    library.install(app)                       # /help 在還沒裝工具時多一則「去哪裡裝」
    if server:
        install_server_packs(app)
    schedule.install_system_remind(app)        # ⏰ 提醒（系統）：系統指令，先佔住群組名再載入 pack（QL5）
    loader.load_all(app, config, vault, dirs=pack_dirs)
    if adapter is _UNSET:
        try:
            adapter = make_adapter(config, vault)
        except LLMError as e:
            logging.error("[LLM] %s", e)
            app.extras["llm_error"] = str(e)
            adapter = None
    agent.install(app, adapter, config)
    discord.install(app, config, vault)      # 有開 Discord 才做事；要在 schedule/web 之前（它們用 app.home）
    runtime.install(app, config, vault, config_path=config_path or "")   # 要在 agent 之後（拿 adapter）、schedule 之前
    schedule.install(app)                    # 排程登記成 runtime 的任務 system.schedule
    web.install(app, config, vault, pack_dirs=pack_dirs, config_path=config_path)
    app.on_start.append(lambda a: a.notify_owner(GREETING))
    return app
