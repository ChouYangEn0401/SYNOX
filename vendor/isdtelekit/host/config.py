"""
config.json：bot 的設定。SDK 自己只讀這幾個欄位，其餘整份放在 BotConfig.raw，功能自己讀自己的：

    {
      "bot_token": "123456:AAH…",          跟 @BotFather 拿的 token（只在本機，不進 git）
      "owner_id": 123456789,               你的 Telegram user id（機器擁有者；舊名 machine_owner_id 也認得）
      "poll_interval_seconds": 3,          getUpdates 失敗時的退避起點
      "data_dir": "data",                  執行期資料放哪（users.json、配額、收訊進度…）
      "stepup_minutes": 30,                /sudo 解鎖多久
      "conversation_idle_minutes": 10, …   時效（core/timing.py 的 Timing.from_config）
    }

讀不到、少欄位、還是範本值時丟 ConfigError，訊息直接告訴人要改哪裡（不要讓人看 KeyError 的 traceback）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


class ConfigError(ValueError):
    """config.json 有問題；訊息是給人看的（說要改哪個欄位）。"""


@dataclass
class BotConfig:
    bot_token: str = ""
    owner_id: int = 0
    poll_interval_seconds: float = 3.0
    data_dir: str = "data"
    stepup_minutes: int = 30
    raw: dict = field(default_factory=dict, repr=False)   # 整份 config.json

    @property
    def has_token(self) -> bool:
        return bool(TOKEN_RE.match(self.bot_token or ""))

    def path(self, *parts: str) -> str:
        """data_dir 底下的路徑：config.path("users.json") → data/users.json。"""
        return os.path.join(self.data_dir, *parts)

    @classmethod
    def from_dict(cls, raw: dict, *, require_token: bool = True) -> "BotConfig":
        owner = raw.get("owner_id", raw.get("machine_owner_id"))
        try:
            owner_id = int(owner)
        except (TypeError, ValueError):
            raise ConfigError("config.json 的 owner_id 要填你的 Telegram user id（一串數字；問 @userinfobot 就知道）。")
        token = str(raw.get("bot_token") or "").strip()
        config = cls(bot_token=token, owner_id=owner_id,
                     poll_interval_seconds=float(raw.get("poll_interval_seconds", 3)),
                     data_dir=str(raw.get("data_dir") or "data"),
                     stepup_minutes=int(raw.get("stepup_minutes", 30)), raw=dict(raw))
        if require_token and not config.has_token:
            raise ConfigError("config.json 的 bot_token 還不是真的 token（跟 @BotFather 拿，長得像 123456:AAH…）。"
                              "只想在終端機試試看的話，用 --console 不需要 token。")
        return config

    @classmethod
    def load(cls, path: str = "config.json", *, require_token: bool = True) -> "BotConfig":
        if not os.path.exists(path):
            raise ConfigError(f"找不到 {path}：複製 config.example.json 成 {os.path.basename(path)}，填 bot_token 和 owner_id。")
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except ValueError as e:
            raise ConfigError(f"{path} 不是合法的 JSON：{e}")
        if not isinstance(raw, dict):
            raise ConfigError(f"{path} 最外層要是一個 {{…}} 物件。")
        return cls.from_dict(raw, require_token=require_token)

    def get(self, key: str, default=None):
        """功能自己的欄位：config.get("service_dir", "C:/…")。"""
        return self.raw.get(key, default)


def env_or(config: Optional[BotConfig], key: str, env: str, default=None):
    """先看環境變數 env，再看 config 的 key，都沒有就 default（部署時不想把值寫進檔案用）。"""
    value = os.environ.get(env)
    if value:
        return value
    return config.get(key, default) if config is not None else default
