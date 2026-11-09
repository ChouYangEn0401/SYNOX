"""
config.json 的 channels.discord → 一串 BotSpec（純函式，不連網；設定錯丟 ConfigError，訊息給人看）。

新寫法（多個 bot；名字只能小寫英數、- 和 _）：
    "channels": {"discord": {"bots": {
        "synox":  {"token": "vault:discord_bot_token:synox", "surface": "dm", "packs": "all", "ai": true},
        "lookup": {"token": "vault:discord_bot_token:lookup", "surface": "channel", "packs": ["dict"],
                   "max_effect": "read", "guilds": {...}, "trigger": "mention", "ai": {"enabled": true, "pool_usd_month": 5}}}}}
舊寫法（一個 bot）：{"enabled": true, "bot_token": "vault:discord_bot_token"} ＝ bots.default = {surface: dm, packs: all}。

- token：只收 "vault:<名字>" 或 "env:<名字>"（新寫法不准把 token 直接寫在檔案裡）；沒寫 → default 用
  vault:discord_bot_token，其他用 vault:discord_bot_token:<名字>（`python -m synox discord token --bot <名字>` 存的地方）。
- surface：dm（私訊，預設）｜channel（伺服器頻道；這一版只解析、不連線，頻道收訊是 PERM-5）。
- packs："all" 或 pack 名字清單；max_effect：read｜write｜danger（沒寫：dm 不設上限、channel 是 read；channel 設 danger 一律拒）。
  synox/policy.py 的 decide 用它們擋（PERM-4）：清單外的 pack 對這個 bot 不存在，超過 max_effect 的指令被拒。
- ai：true／false 或 {"enabled": …, "pool_usd_month": …}。關掉＝這個 bot 上沒有 AI（agent 群組不存在、打字不交給 AI）；
  pool_usd_month 這一版只存起來（PERM-6）。
- 兩個 bot 不能用同一個 token（同一個 bot 開兩條 Gateway 會互搶事件）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from isdtelekit.host.config import ConfigError

DM, CHANNEL = "dm", "channel"
SURFACES = (DM, CHANNEL)
EFFECTS = ("read", "write", "danger")
DEFAULT = "default"
VAULT_BASE = "discord_bot_token"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
BOT_KEYS = {"token", "surface", "packs", "max_effect", "ai", "guilds", "trigger", "persona", "enabled"}


@dataclass(frozen=True)
class BotSpec:
    name: str
    token: str                                   # "vault:…" 或 "env:…"（舊寫法也可能是直接寫的 token）
    surface: str = DM
    packs: Union[str, Tuple[str, ...]] = "all"
    max_effect: Optional[str] = None             # None＝不設上限
    ai: dict = field(default_factory=lambda: {"enabled": True, "pool_usd_month": None})
    guilds: dict = field(default_factory=dict)
    trigger: str = "mention"
    persona: str = ""
    enabled: bool = True
    legacy: bool = False                         # 舊寫法來的（hub 名字維持 "discord"，狀態頁、指令照舊）

    @property
    def hub_name(self) -> str:
        return "discord" if self.legacy else f"discord:{self.name}"

    @property
    def vault_name(self) -> Optional[str]:
        return self.token[len("vault:"):] if self.token.startswith("vault:") else None


def default_vault_name(name: str) -> str:
    return VAULT_BASE if name == DEFAULT else f"{VAULT_BASE}:{name}"


def _err(name: str, msg: str) -> ConfigError:
    return ConfigError(f"config.json 的 channels.discord.bots.{name}：{msg}")


def _packs(name: str, value) -> Union[str, Tuple[str, ...]]:
    if value is None or value == "all":
        return "all"
    if isinstance(value, list) and all(isinstance(p, str) and p.strip() for p in value):
        return tuple(p.strip() for p in value)
    raise _err(name, 'packs 要寫 "all" 或 pack 名字的清單（例如 ["dict", "weather"]）。')


def _ai(name: str, value) -> dict:
    if value is None or isinstance(value, bool):
        return {"enabled": True if value is None else value, "pool_usd_month": None}
    if not isinstance(value, dict):
        raise _err(name, 'ai 要寫 true／false 或 {"enabled": true, "pool_usd_month": 5}。')
    pool = value.get("pool_usd_month")
    if pool is not None:
        try:
            pool = float(pool)
        except (TypeError, ValueError):
            raise _err(name, "ai.pool_usd_month 要是數字（美元）。")
        if pool < 0:
            raise _err(name, "ai.pool_usd_month 不能是負的。")
    return {"enabled": bool(value.get("enabled", True)), "pool_usd_month": pool}


def _one(name: str, raw) -> BotSpec:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ConfigError(f"config.json 的 channels.discord.bots 裡的名字 {name!r} 不行：只能用小寫英文、數字、- 和 _（最多 32 字）。")
    if not isinstance(raw, dict):
        raise _err(name, "要是一個 {…} 物件。")
    unknown = sorted(set(raw) - BOT_KEYS)
    if unknown:
        raise _err(name, f"不認得的欄位 {'、'.join(unknown)}（可以用：{'、'.join(sorted(BOT_KEYS))}）。")
    token = raw.get("token")
    if token in (None, ""):
        token = f"vault:{default_vault_name(name)}"
    if not isinstance(token, str) or not (token.startswith("vault:") or token.startswith("env:")) \
            or not token.split(":", 1)[1].strip():
        raise _err(name, 'token 只能寫保管箱的名字（"vault:discord_bot_token:<名字>"）或 "env:<環境變數>"，'
                         "不要把 token 直接寫進 config.json（用 python -m synox discord token --bot <名字> 存）。")
    surface = str(raw.get("surface") or DM).strip().lower()
    if surface not in SURFACES:
        raise _err(name, f"surface 只能是 dm（私訊）或 channel（伺服器頻道）（現在是 {raw.get('surface')!r}）。")
    max_effect = raw.get("max_effect")
    if max_effect is not None:
        max_effect = str(max_effect).strip().lower()
        if max_effect not in EFFECTS:
            raise _err(name, f"max_effect 只能是 read、write 或 danger（現在是 {raw.get('max_effect')!r}）。")
    if surface == CHANNEL:
        max_effect = max_effect or "read"
        if max_effect == "danger":
            raise _err(name, "頻道型 bot 的 max_effect 不能是 danger（危險動作只能在私訊做）；最多 write。")
    guilds = raw.get("guilds") or {}
    if not isinstance(guilds, dict):
        raise _err(name, 'guilds 要是 {"<伺服器 id>": {"channels": [...]}} 這樣的物件。')
    if guilds and surface != CHANNEL:
        raise _err(name, "guilds 只有 surface 是 channel 的 bot 才能寫。")
    trigger = raw.get("trigger") or "mention"
    persona = raw.get("persona") or ""
    if not isinstance(trigger, str) or not isinstance(persona, str):
        raise _err(name, "trigger、persona 要是文字。")
    return BotSpec(name=name, token=token, surface=surface, packs=_packs(name, raw.get("packs")),
                   max_effect=max_effect, ai=_ai(name, raw.get("ai")), guilds=dict(guilds), trigger=trigger,
                   persona=persona, enabled=bool(raw.get("enabled", True)))


def parse(d) -> List[BotSpec]:
    """channels.discord → BotSpec 清單（照 config 的順序；含 enabled=false 的）。沒寫 Discord → []。"""
    if not d:
        return []
    if not isinstance(d, dict):
        raise ConfigError("config.json 的 channels.discord 要是一個 {…} 物件。")
    if "bots" not in d:
        token = d.get("bot_token") or f"vault:{VAULT_BASE}"
        if not isinstance(token, str):
            raise ConfigError("config.json 的 channels.discord.bot_token 要是文字（例如 \"vault:discord_bot_token\"）。")
        return [BotSpec(name=DEFAULT, token=token, legacy=True)]
    if d.get("bot_token"):
        raise ConfigError("config.json 的 channels.discord 同時寫了 bot_token 和 bots：兩種寫法擇一"
                          "（多個 bot 時把 bot_token 搬進 bots.<名字>.token）。")
    bots = d.get("bots")
    if not isinstance(bots, dict) or not bots:
        raise ConfigError("config.json 的 channels.discord.bots 要是至少有一個 bot 的物件，例如 "
                          '{"synox": {"surface": "dm"}}。')
    specs = [_one(name, raw) for name, raw in bots.items()]
    seen = {}
    for s in specs:
        if s.token in seen:
            raise ConfigError(f"config.json 的 channels.discord.bots.{seen[s.token]} 和 {s.name} 用同一個 token（{s.token}）："
                              "一個 bot 只能有一條連線，每個 bot 要各自的 token。")
        seen[s.token] = s.name
    return specs


def active(d) -> List[BotSpec]:
    """要開的 bot（channels.discord.enabled 沒關、各自 enabled 沒關）。"""
    if not isinstance(d, dict) or not d:
        return []
    specs = parse(d)
    if specs and specs[0].legacy:
        return specs if bool(d.get("enabled", bool(d.get("bot_token")))) else []
    if not bool(d.get("enabled", True)):
        return []
    return [s for s in specs if s.enabled]


def find(specs: List[BotSpec], name: Optional[str]) -> Optional[BotSpec]:
    """依名字找；name 沒給 → default（舊寫法的那一個），沒有 default 就第一個私訊型。"""
    if name:
        return next((s for s in specs if s.name == name), None)
    return (next((s for s in specs if s.name == DEFAULT), None)
            or next((s for s in specs if s.surface == DM), None))
