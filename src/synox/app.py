"""
build()：SynoxConfig → isdtelekit.build_app → 基本指令（伺服器版多 accounts、limits）→ packs.load_all
→ agent.install → schedule.install → web.install（本機網頁介面）。

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

from synox import agent, schedule, web
from synox.config import SynoxConfig
from synox.llm import make_adapter
from synox.llm.base import LLMError
from synox.packs import loader
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


def build(config: SynoxConfig, *, home=None, adapter=_UNSET, vault=_UNSET, pack_dirs=loader.PACK_DIRS,
          config_path: Optional[str] = None) -> App:
    app = build_app(config, home=home)
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
    if server:
        basics.install(app, welcome=lambda u: welcome(u) if app.registry.is_owner(u) else welcome_server(u))
    else:
        basics.install(app, welcome=welcome)
    help_pack.install(app)
    if server:
        install_server_packs(app)
    loader.load_all(app, config, vault, dirs=pack_dirs)
    if adapter is _UNSET:
        try:
            adapter = make_adapter(config, vault)
        except LLMError as e:
            logging.error("[LLM] %s", e)
            app.extras["llm_error"] = str(e)
            adapter = None
    agent.install(app, adapter, config)
    schedule.install(app)
    web.install(app, config, vault, pack_dirs=pack_dirs, config_path=config_path)
    app.on_start.append(lambda a: a.notify_owner(GREETING))
    return app
