"""
config.json 的 link 區塊（純函式、不連網；錯了丟 ConfigError，訊息給人看）：

    "link": {
      "enabled": true,
      "role": "console",                     console（主控台：派任務）｜worker（哨兵：接任務）
      "name": "客廳那台",                     名片上的名字（1–40 字）；沒寫＝主機名
      "transport": {"kind": "tcp", "listen": "0.0.0.0:8831"},          主控台在區域網路聽（E2E 加密，但只建議內網）
                   {"kind": "tcp", "connect": "192.168.1.10:8831"},    哨兵主動連過去（只要能出去、不用開埠）
                   {"kind": "folder", "dir": "Z:/synox-link"},         共用資料夾（SMB／Syncthing／USB）：兩邊都輪詢
      "max_effect": "write",                 哨兵：接受的指令最多到這個效果（read｜write｜danger；預設 write）
      "task_timeout": 120,                   哨兵：一個任務最多跑幾秒
      "heartbeat": 30,                       幾秒送一次心跳（0＝不送）
      "poll": 2                              folder 傳輸每幾秒看一次資料夾
    }
tcp 的 listen 預設只聽 127.0.0.1（跟 Web UI 一樣要明寫才對外）；對外的位址只建議區域網路或 WireGuard 內。
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from typing import Optional, Tuple

from isdtelekit.host.config import ConfigError

ROLES = ("console", "worker")
KINDS = ("tcp", "folder", "memory")        # memory 只給測試（set_transport_factory）
EFFECTS = ("read", "write", "danger")
DEFAULT_PORT = 8831
DEFAULT_TASK_TIMEOUT = 120
DEFAULT_HEARTBEAT = 30
DEFAULT_POLL = 2.0
LINK_KEYS = {"enabled", "role", "name", "transport", "max_effect", "task_timeout", "heartbeat", "poll"}
TRANSPORT_KEYS = {"kind", "listen", "connect", "dir"}


@dataclass(frozen=True)
class Transport:
    kind: str
    listen: Optional[Tuple[str, int]] = None
    connect: Optional[Tuple[str, int]] = None
    folder: str = ""


@dataclass(frozen=True)
class LinkSettings:
    enabled: bool = False
    role: str = "console"
    name: str = ""
    transport: Transport = field(default_factory=lambda: Transport("tcp", listen=("127.0.0.1", DEFAULT_PORT)))
    max_effect: str = "write"
    task_timeout: int = DEFAULT_TASK_TIMEOUT
    heartbeat: int = DEFAULT_HEARTBEAT
    poll: float = DEFAULT_POLL

    @property
    def is_console(self) -> bool:
        return self.role == "console"


def _hostport(value, what: str) -> Tuple[str, int]:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"config.json 的 link.transport.{what} 要寫成 \"主機:埠\"（例如 192.168.1.10:{DEFAULT_PORT}）。")
    host, _, port = value.strip().rpartition(":")
    if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ConfigError(f"config.json 的 link.transport.{what} 要寫成 \"主機:埠\"（現在是 {value!r}）。")
    return host.strip("[]"), int(port)


def parse(raw) -> LinkSettings:
    """config.json 的 link → LinkSettings；沒寫或 enabled=false ＝ 沒開。"""
    if raw is None:
        return LinkSettings()
    if not isinstance(raw, dict):
        raise ConfigError("config.json 的 link 要是一個 {…} 物件。")
    extra = set(raw) - LINK_KEYS
    if extra:
        raise ConfigError(f"config.json 的 link 有不認識的欄位：{', '.join(sorted(extra))}。")
    enabled = bool(raw.get("enabled", False))
    role = str(raw.get("role") or "console").strip().lower()
    if role not in ROLES:
        raise ConfigError(f"config.json 的 link.role 只能是 console（主控台）或 worker（哨兵）（現在是 {raw.get('role')!r}）。")
    name = str(raw.get("name") or "").strip() or socket.gethostname()[:40] or "SYNOX"
    if len(name) > 40:
        raise ConfigError("config.json 的 link.name 最多 40 字。")
    max_effect = str(raw.get("max_effect") or "write").strip().lower()
    if max_effect not in EFFECTS:
        raise ConfigError("config.json 的 link.max_effect 只能是 read、write 或 danger。")
    try:
        task_timeout = int(raw.get("task_timeout", DEFAULT_TASK_TIMEOUT))
        heartbeat = int(raw.get("heartbeat", DEFAULT_HEARTBEAT))
        poll = float(raw.get("poll", DEFAULT_POLL))
    except (TypeError, ValueError):
        raise ConfigError("config.json 的 link.task_timeout／heartbeat／poll 要是數字（秒）。")
    if task_timeout < 1 or heartbeat < 0 or poll <= 0:
        raise ConfigError("config.json 的 link.task_timeout 要 ≥ 1、heartbeat ≥ 0、poll > 0。")
    t = raw.get("transport")
    if t is None:
        transport = Transport("tcp", listen=("127.0.0.1", DEFAULT_PORT)) if role == "console" else None
        if transport is None:
            if enabled:
                raise ConfigError("config.json 的 link.role 是 worker 時要寫 link.transport（connect 到主控台，或 folder）。")
            transport = Transport("tcp", connect=("127.0.0.1", DEFAULT_PORT))
    else:
        if not isinstance(t, dict):
            raise ConfigError("config.json 的 link.transport 要是一個 {…} 物件。")
        extra = set(t) - TRANSPORT_KEYS
        if extra:
            raise ConfigError(f"config.json 的 link.transport 有不認識的欄位：{', '.join(sorted(extra))}。")
        kind = str(t.get("kind") or "tcp").strip().lower()
        if kind not in KINDS:
            raise ConfigError("config.json 的 link.transport.kind 只能是 tcp 或 folder。")
        if kind == "tcp":
            if "listen" in t and "connect" in t:
                raise ConfigError("config.json 的 link.transport 只能有 listen 或 connect 其中一個。")
            if "connect" in t:
                transport = Transport("tcp", connect=_hostport(t["connect"], "connect"))
            elif "listen" in t:
                transport = Transport("tcp", listen=_hostport(t["listen"], "listen"))
            elif role == "console":
                transport = Transport("tcp", listen=("127.0.0.1", DEFAULT_PORT))
            else:
                raise ConfigError("config.json 的 link.transport 是 tcp 時，哨兵要寫 connect（主控台的 主機:埠）。")
        elif kind == "folder":
            folder = str(t.get("dir") or "").strip()
            if not folder:
                raise ConfigError("config.json 的 link.transport.kind 是 folder 時要寫 dir（兩台都看得到的資料夾）。")
            transport = Transport("folder", folder=folder)
        else:
            transport = Transport("memory")
    return LinkSettings(enabled=enabled, role=role, name=name, transport=transport, max_effect=max_effect,
                        task_timeout=task_timeout, heartbeat=heartbeat, poll=poll)


__all__ = ["LinkSettings", "Transport", "parse", "ROLES", "KINDS", "EFFECTS", "DEFAULT_PORT"]
