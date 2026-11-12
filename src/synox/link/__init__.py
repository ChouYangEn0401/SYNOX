"""
⚠️ EXPERIMENTAL（實驗品，2026-11-12）：這一包不是 SYNOX 核心的一部分。擁有者的方向是讓 SYNOX 核心維持空殼、
指令盡量少；link 之後很可能整包搬出去變成獨立的套件（或 pack），也可能直接拿掉。所以：
- config.json 沒開 link 時，install() 什麼都不做：沒有指令、沒有執行緒、沒有檔案——核心不會被它汙染。
- 它只碰 SYNOX 的這幾個介面（搬出去時就是這幾條線要接）：
    app.extras["vault"]（保管箱：Vault.load_json／save_json／exists）、app.registry（ensure_group／leaf）、
    app.dispatcher.handle＋isdtelekit.core.channel.Inbound（哨兵跑指令）、synox.policy.decide（哨兵的權限）、
    synox.packs.loader.group_policy（指令群組權限）、app.notify／app.on_start／app.on_stop／app.extras、
    synox.config（link 區塊的解析掛在 SynoxConfig.from_dict）、doctor 的一行、__main__ 的 link 子指令。
- 不要在核心其他地方 import synox.link（只有 app.py、config.py、doctor.py、__main__.py 各一處）。

SYNOX Link：兩台（以上）SYNOX 之間的安全連線——主控台（console）派任務、哨兵（worker）做任務、回報、重做、交接。
調查與設計：docs/discussions/2026-11-12-link-architecture.html；使用說明：docs/link.md。

    config.json  "link": {"enabled": true, "role": "console", "transport": {"kind": "tcp", "listen": "0.0.0.0:8831"}}
                 "link": {"enabled": true, "role": "worker",  "transport": {"kind": "tcp", "connect": "192.168.1.10:8831"}}

分層（每一層只認識下一層）：
    commands.py（Telegram 指令）／roles.py（ConsoleRole、WorkerRole）
        ↓ 只碰 bus 與 node.send
    node.py（LinkNode：信封進出、名單、在線、配對）        bus.py（EventBus：link.in.*、link.out.*、task.*、link.peer.*）
        ↓
    envelope.py（端對端加密＋簽章＋重放防護）  identity.py（金鑰、名片）  peers.py（名單，保管箱）  pairing.py（配對碼）
        ↓
    transport.py（只搬 bytes：memory／folder／tcp）

install(app, config, vault)：link.enabled 才做事；沒有保管箱＝開不了（link_error）。transport 由 set_transport_factory
換（測試用 MemoryTransport；**測試不綁埠**）。app.on_start 才啟動傳輸層（終端機模式不開連線）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from synox.link import commands as link_commands
from synox.link import settings as link_settings
from synox.link.bus import EventBus
from synox.link.identity import NodeIdentity, load_or_create
from synox.link.node import LinkNode
from synox.link.peers import PeerStore
from synox.link.protocol import TaskBook
from synox.link.roles import ConsoleRole, WorkerRole
from synox.link.settings import LinkSettings
from synox.link.transport import FolderTransport, TcpTransport

EXTRA = "synox_link"
EXPERIMENTAL = "實驗品：之後可能搬成獨立套件或拿掉（docs/link.md）"


@dataclass
class Link:
    settings: LinkSettings
    identity: NodeIdentity
    peers: PeerStore
    bus: EventBus
    node: LinkNode
    console: Optional[ConsoleRole]
    worker: Optional[WorkerRole]
    book: Optional[TaskBook]


def default_transport(settings: LinkSettings, node_id: str):
    t = settings.transport
    if t.kind == "folder":
        return FolderTransport(t.folder, node_id, poll=settings.poll)
    if t.kind == "tcp":
        return TcpTransport(listen=t.listen, connect=t.connect)
    raise ValueError(f"no transport for {t.kind!r}（memory 只給測試：set_transport_factory）")


_factory: Callable[[LinkSettings, str], object] = default_transport


def set_transport_factory(factory: Optional[Callable[[LinkSettings, str], object]]) -> None:
    """測試換傳輸層（MemoryTransport）。None＝還原。"""
    global _factory
    _factory = factory or default_transport


def settings_of(config) -> LinkSettings:
    raw = getattr(config, "link", None)
    return raw if isinstance(raw, LinkSettings) else link_settings.parse(raw)


def enabled(config) -> bool:
    try:
        return settings_of(config).enabled
    except Exception:
        return False


def build(config, vault, *, app=None, settings: Optional[LinkSettings] = None, transport=None) -> Link:
    """組起來但不啟動（CLI 的 pair／join／card 也用：不需要 app）。"""
    settings = settings or settings_of(config)
    identity = load_or_create(vault, settings.name)
    peers = PeerStore(vault)
    bus = EventBus()
    transport = transport or _factory(settings, identity.node_id)
    node = LinkNode(identity, peers, transport, bus, vault, settings)
    console = worker = book = None
    if app is not None:
        if settings.is_console:
            book = TaskBook(vault)
            console = ConsoleRole(node, book, app.notify)
        else:
            worker = WorkerRole(node, app, settings)
    return Link(settings, identity, peers, bus, node, console, worker, book)


def install(app, config, vault) -> Optional[Link]:
    settings = settings_of(config)
    if not settings.enabled:
        return None
    if vault is None:
        app.extras["link_error"] = "保管箱打不開，link 開不了（身分金鑰在保管箱裡）"
        logging.error("[LINK] %s", app.extras["link_error"])
        return None
    try:
        link = build(config, vault, app=app, settings=settings)
    except Exception as e:
        app.extras["link_error"] = f"{type(e).__name__}: {e}"
        logging.exception("[LINK] cannot build")
        return None
    app.extras[EXTRA] = link
    logging.warning("[LINK] %s", EXPERIMENTAL)
    link_commands.install(app, link)
    app.on_start.append(lambda _a: link.node.start())
    app.on_stop.append(lambda _a: link.node.stop())
    return link


__all__ = ["Link", "build", "install", "enabled", "settings_of", "set_transport_factory", "default_transport", "EXTRA"]
