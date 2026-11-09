"""
build()：SynoxConfig → isdtelekit.build_app → 基本指令 → packs.load_all → agent.install → schedule.install。

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
from isdtelekit.packs import basics, help as help_pack

from synox import agent, schedule
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


def build(config: SynoxConfig, *, home=None, adapter=_UNSET, vault=_UNSET, pack_dirs=loader.PACK_DIRS) -> App:
    app = build_app(config, home=home)
    app.extras["synox_config"] = config
    if vault is _UNSET:
        try:
            vault = open_vault(config)
        except Exception as e:                 # 金鑰檔壞掉／換了電腦：pack 照樣載入，要保管箱的那些會報錯
            logging.error("[VAULT] cannot open: %s", e)
            app.extras["vault_error"] = str(e)
            vault = None
    app.extras["vault"] = vault
    basics.install(app, welcome=welcome)
    help_pack.install(app)
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
    app.on_start.append(lambda a: a.notify_owner(GREETING))
    return app
