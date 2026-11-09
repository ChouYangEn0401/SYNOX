"""
SYNOX 的設定：SDK 的 BotConfig 欄位（bot_token、owner_id、data_dir、時效…）＋ SYNOX 自己多的三塊。

    {
      "bot_token": "123456:AAH…", "owner_id": 123456789,
      "llm":   {"kind": "openai_compat", "base_url": "https://…/v1", "api_key": "vault:llm_api_key",
                "model": "…", "tools": true, "max_steps": 6, "max_tokens": 1024},
      "vault": {"mode": "dpapi"},              dpapi（Windows 預設）｜file（金鑰明文存在 data/.synox.key）
      "packs": {"enabled": "all", "disabled": []}
    }

- 路徑一律相對於 SYNOX 資料夾（不管從哪裡啟動）：data_dir 沒寫就是 <SYNOX>/data。
- api_key 可以直接寫，也可以寫 "vault:<名字>"：真正的值放在 data/secrets.json.enc（精靈就是這樣存的）。
- 換 LLM 只改 llm 這一塊（invariant 2）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from isdtelekit.host.config import BotConfig, ConfigError

ROOT = os.environ.get("SYNOX_HOME") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(ROOT, "config.json")

LLM_KINDS = ("openai_compat", "anthropic", "claude_code", "fake", "none")
DEFAULT_LLM = {"kind": "none", "max_steps": 6, "max_tokens": 1024}
DEFAULT_VAULT = {"mode": "dpapi" if os.name == "nt" else "file"}
DEFAULT_PACKS = {"enabled": "all", "disabled": []}


@dataclass
class SynoxConfig(BotConfig):
    llm: dict = field(default_factory=lambda: dict(DEFAULT_LLM))
    vault: dict = field(default_factory=lambda: dict(DEFAULT_VAULT))
    packs: dict = field(default_factory=lambda: dict(DEFAULT_PACKS))
    root: str = ROOT

    @classmethod
    def from_dict(cls, raw: dict, *, require_token: bool = True, root: Optional[str] = None) -> "SynoxConfig":
        base = BotConfig.from_dict(raw, require_token=require_token)
        root = os.path.abspath(root or ROOT)
        data_dir = base.data_dir if os.path.isabs(base.data_dir) else os.path.join(root, base.data_dir)
        llm = {**DEFAULT_LLM, **(raw.get("llm") or {})}
        if llm.get("kind") not in LLM_KINDS:
            raise ConfigError(f"config.json 的 llm.kind 只能是 {'、'.join(LLM_KINDS)}（現在是 {llm.get('kind')!r}）。")
        vault = {**DEFAULT_VAULT, **(raw.get("vault") or {})}
        if vault.get("mode") not in ("dpapi", "file"):
            raise ConfigError("config.json 的 vault.mode 只能是 dpapi 或 file。")
        packs = {**DEFAULT_PACKS, **(raw.get("packs") or {})}
        return cls(bot_token=base.bot_token, owner_id=base.owner_id,
                   poll_interval_seconds=base.poll_interval_seconds, data_dir=data_dir,
                   stepup_minutes=base.stepup_minutes, raw=dict(raw), llm=llm, vault=vault, packs=packs, root=root)

    @classmethod
    def load(cls, path: Optional[str] = None, *, require_token: bool = True,
             root: Optional[str] = None) -> "SynoxConfig":
        path = path or CONFIG_PATH
        if not os.path.exists(path):
            raise ConfigError(f"找不到 {path}：先雙擊 Setup.bat 跑安裝精靈（或複製 config.example.json 成 config.json）。")
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
        except ValueError as e:
            raise ConfigError(f"{path} 不是合法的 JSON：{e}")
        if not isinstance(raw, dict):
            raise ConfigError(f"{path} 最外層要是一個 {{…}} 物件。")
        return cls.from_dict(raw, require_token=require_token, root=root or os.path.dirname(os.path.abspath(path)))

    def pack_enabled(self, name: str) -> bool:
        enabled = self.packs.get("enabled", "all")
        if name in (self.packs.get("disabled") or []):
            return False
        return enabled == "all" or name in (enabled or [])


def redacted(raw: dict) -> dict:
    """doctor 印設定用：拿掉 token、金鑰（只說有沒有）。"""
    out = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[key] = redacted(value)
        elif any(s in key.lower() for s in ("token", "key", "secret", "password")):
            out[key] = "（有填）" if value else "（空）"
        else:
            out[key] = value
    return out
