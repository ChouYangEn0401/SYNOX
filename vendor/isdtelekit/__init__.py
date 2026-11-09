"""
ISDTeleKitSDK——從 ClawBot（MyFirstTelegramClawBot）抽出來的 bot 底層。

三層，各管各的：

    channel（telegram/、host/console.py）   把平台的訊息轉成 Inbound，提供回覆用的管子（Channel）
        ▼
    Dispatcher（core/dispatcher.py）       分流：指令 → 進行中的對話 → 自由文字的出口；全部經 registry.authorize()
        ▼
    功能（指令樹的葉節點）                  handler(api, chat_id, user, args)；packs/ 是現成的幾組

最常用的幾個名字從這裡拿就好：

    from isdtelekit import BotConfig, build_app, Field, READ, WRITE, DANGER

用法見 README.md；給 AI／接手的人看的地圖在 AGENT.md。
"""

__version__ = "0.2.1"

from isdtelekit.core.registry import DANGER, READ, WRITE, Field  # noqa: E402
from isdtelekit.host.app import App, build_app  # noqa: E402
from isdtelekit.host.config import BotConfig, ConfigError  # noqa: E402

__all__ = ["App", "BotConfig", "ConfigError", "DANGER", "Field", "READ", "WRITE", "build_app", "__version__"]
