"""
LinkNode（SYNOX Link，架構 v1 §L7）：把身分、名單、傳輸層、事件匯流排接在一起的那個東西。一台 SYNOX 一個。

    node = LinkNode(identity, peers, transport, bus, vault, settings)
    node.start()                                   # app.on_start
    node.send(peer_id, "task.offer", {...})        # 封信 → transport
    bus.subscribe("link.in.task.*", handler)       # 收到、驗過的信都變成事件：link.in.<kind>（event: msg, peer, conn）

收信：transport 給 bytes → decode → open_envelope（名單裡的人才收；主控台在「等配對」時多收 pair.request）
→ peers.saw(seq)（重放防護的持久化）→ transport.bind（這條連線是它的）→ 更新在線狀態 → bus.publish。
驗不過的：transport.bad(conn)（TCP 累計三次就斷）＋ bus.publish("link.rejected")，不回任何東西。

內建會自己回的：ping → pong；hello／heartbeat → 只更新在線。心跳執行緒每 heartbeat 秒送一次 heartbeat 給每個
peer（0＝不送），同一條執行緒順便做哨兵的配對請求（link_join 保管箱裡有東西就送 pair.request，每 15 秒最多一次）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional

from synox.link import pairing, protocol
from synox.link.envelope import LinkError, Message, ReplayGuard, decode, encode, open_envelope, seal
from synox.link.identity import NodeIdentity, short_id

TICK = 5.0
PAIR_RETRY = 15.0


class LinkNode:

    def __init__(self, identity: NodeIdentity, peers, transport, bus, vault, settings,
                 clock: Callable[[], float] = time.time):
        self.identity = identity
        self.peers = peers
        self.transport = transport
        self.bus = bus
        self.vault = vault
        self.settings = settings
        self._clock = clock
        self.guard = ReplayGuard(clock=clock)
        self._seen: Dict[str, float] = {}
        self._online: Dict[str, bool] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_pair_try = 0.0
        self._lock = threading.RLock()
        self.started = False

    @property
    def node_id(self) -> str:
        return self.identity.node_id

    # ── 生命週期 ─────────────────────────────────────────────────

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self._stop.clear()
        self.transport.start(self._on_frame, self._on_connect)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Link-node")
        self._thread.start()
        logging.info("[LINK] %s %s (%s) started", self.settings.role, short_id(self.node_id), self.identity.name)

    def stop(self) -> None:
        self._stop.set()
        self.transport.stop()
        self.started = False

    def _loop(self) -> None:
        last_beat = 0.0
        while not self._stop.is_set():
            try:
                now = self._clock()
                if self.settings.heartbeat and now - last_beat >= self.settings.heartbeat:
                    last_beat = now
                    for peer_id in self.peers.ids():
                        self.send(peer_id, protocol.HEARTBEAT, {})
                self.tick(now)
            except Exception:
                logging.exception("[LINK] tick failed")
            self._stop.wait(min(TICK, self.settings.heartbeat or TICK))

    def tick(self, now: Optional[float] = None) -> None:
        """每幾秒做一次的事（測試直接叫）：在線狀態過期、哨兵的配對請求。"""
        now = self._clock() if now is None else now
        timeout = max(3 * (self.settings.heartbeat or 0), 2 * TICK)
        with self._lock:
            for peer_id, seen in list(self._seen.items()):
                if self._online.get(peer_id) and now - seen > timeout:
                    self._online[peer_id] = False
                    self.bus.publish("link.peer.offline", peer=peer_id)
        if not self.settings.is_console and now - self._last_pair_try >= PAIR_RETRY:
            self._last_pair_try = now
            self.try_pairing()

    # ── 送 ───────────────────────────────────────────────────────

    def send(self, peer_id: str, kind: str, body: dict, *, conn=None, card=None) -> bool:
        peer = self.peers.get(peer_id)
        if peer is None:
            logging.info("[LINK] send: unknown peer %s", peer_id)
            return False
        try:
            seq = self.peers.next_seq(peer_id)
            env = seal(self.identity, peer, kind, body, seq=seq, now=self._clock(), card=card)
        except (LinkError, KeyError) as e:
            logging.warning("[LINK] seal failed: %s", e)
            return False
        ok = self.transport.send(peer_id, encode(env), conn=conn)
        self.bus.publish("link.out." + kind, peer=peer_id, kind=kind, sent=ok)
        return ok

    def _on_connect(self, conn) -> None:
        for peer_id in self.peers.ids():
            self.send(peer_id, protocol.HELLO, {"name": self.identity.name, "role": self.settings.role}, conn=conn)

    # ── 收 ───────────────────────────────────────────────────────

    def _on_frame(self, frame: bytes, conn) -> None:
        sender = "?"
        try:
            env = decode(frame)
            sender = env.get("from", "?") if isinstance(env.get("from"), str) else "?"
            allow_card = (self.settings.is_console and self.peers.get(sender) is None
                          and pairing.pending(self.vault, now=self._clock()) is not None)
            msg = open_envelope(self.identity, self.peers.get, env, self.guard, last_seq=self.peers.last_seen_seq,
                                allow_card=allow_card)
        except LinkError as e:
            logging.info("[LINK] rejected frame from %s: %s", sender, e)
            self.transport.bad(conn)
            self.bus.publish("link.rejected", peer=sender, reason=str(e))
            return
        if msg.card is not None:
            self._pair_request(msg, conn)
            return
        self.peers.saw(msg.sender, msg.seq)
        self.transport.bind(msg.sender, conn)
        self._mark_seen(msg.sender)
        self.handle(msg, conn)

    def handle(self, msg: Message, conn=None) -> None:
        """驗過的信：內建的回應＋發事件。"""
        if msg.kind == protocol.PING:
            self.send(msg.sender, protocol.PONG, {}, conn=conn)
        elif msg.kind == protocol.PAIR_OK and not self.settings.is_console:
            pairing.clear_join(self.vault)
            self.bus.publish("link.paired", peer=msg.sender, role="console")
        self.bus.publish("link.in." + msg.kind, msg=msg, peer=msg.sender, conn=conn)

    def _mark_seen(self, peer_id: str) -> None:
        with self._lock:
            self._seen[peer_id] = self._clock()
            was = self._online.get(peer_id, False)
            self._online[peer_id] = True
        if not was:
            self.bus.publish("link.peer.online", peer=peer_id)

    def online(self, peer_id: str) -> bool:
        with self._lock:
            return bool(self._online.get(peer_id))

    def last_seen(self, peer_id: str) -> Optional[float]:
        with self._lock:
            return self._seen.get(peer_id)

    # ── 配對 ─────────────────────────────────────────────────────

    def _pair_request(self, msg: Message, conn) -> None:
        """主控台：收到帶名片的 pair.request。mac 對得上等著的配對碼才收；不回任何錯誤。"""
        secret = pairing.pending(self.vault, now=self._clock())
        card = msg.card
        if secret is None or card is None or msg.kind != protocol.PAIR_REQUEST:
            return
        if not pairing.verify_request(secret, card, self.node_id, msg.body.get("mac")):
            logging.info("[LINK] pair.request from %s: bad mac", short_id(card.node_id))
            self.transport.bad(conn)
            self.bus.publish("link.rejected", peer=card.node_id, reason="配對碼不對")
            return
        self.peers.add(card, role="worker", via="pair")
        self.peers.saw(card.node_id, msg.seq)
        pairing.clear_pending(self.vault)
        self.transport.bind(card.node_id, conn)
        self._mark_seen(card.node_id)
        self.send(card.node_id, protocol.PAIR_OK, {"name": self.identity.name}, conn=conn)
        logging.info("[LINK] paired worker %s (%s)", short_id(card.node_id), card.name)
        self.bus.publish("link.paired", peer=card.node_id, role="worker", name=card.name)

    def try_pairing(self) -> bool:
        """哨兵：保管箱裡有 `synox link join` 存的配對碼就送 pair.request（主控台的名片在 join 時已經進名單）。"""
        found = pairing.pending_join(self.vault, now=self._clock())
        if found is None:
            return False
        console_card, secret = found
        if self.peers.get(console_card.node_id) is None:
            self.peers.add(console_card, role="console", via="join")
        mac = pairing.mac_of(secret, self.identity.card(), console_card.node_id)
        return self.send(console_card.node_id, protocol.PAIR_REQUEST,
                         {"mac": mac, "name": self.identity.name, "role": self.settings.role},
                         card=self.identity.card())

    # ── 狀態 ─────────────────────────────────────────────────────

    def status(self) -> dict:
        peers = []
        for entry in self.peers.entries():
            pid = entry["node_id"]
            peers.append({"node_id": pid, "name": (entry.get("card") or {}).get("name", ""),
                          "role": entry.get("role"), "online": self.online(pid), "last_seen": self.last_seen(pid)})
        return {"node_id": self.node_id, "name": self.identity.name, "role": self.settings.role,
                "transport": self.transport.status(), "peers": peers, "started": self.started}


__all__ = ["LinkNode", "TICK"]
