"""
信封（SYNOX Link，架構 v1 §L2）：兩台 SYNOX 之間的每一則訊息都是一個「封好的信封」，跟它走哪條路無關。
同一個信封可以走區域網路 TCP、共用資料夾、MQTT、序列埠……傳輸層只搬 bytes，看不懂內容、也改不了內容。

    env = seal(me, peer_card, "task.offer", {"id": "…", "command": "/note 買牛奶"}, seq=12)
    msg = open_envelope(me, peers, env, guard)          # Message(kind, body, sender, seq, ts)

格式（JSON，欄位都是文字；傳輸層可以再包一層、也可以直接 base64 貼進聊天）：
    {"v": 1, "from": "<寄件者 node_id>", "to": "<收件者 node_id>", "seq": 12, "ts": 1760000000,
     "eph": "<一次性的 X25519 公鑰>", "salt": "<16 bytes>", "ct": "<密文>", "sig": "<Ed25519 簽章>"}

金鑰：每一封信換一把（所以 nonce 固定全零也安全）：
    shared = X25519(eph_priv, peer_box_pub) ‖ X25519(my_box_priv, peer_box_pub)
    key    = HKDF-SHA256(shared, salt, info="synox-link-v1|from|to")            → ChaCha20-Poly1305
    AAD    = 表頭（v、from、to、seq、ts、eph、salt）的固定順序 JSON
    sig    = Ed25519(寄件者簽章私鑰, AAD ‖ ct)
- 第一段 DH 用一次性金鑰：舊信不會因為之後私鑰外洩而被解開（前向保密）。
- 第二段 DH 用寄件者長期金鑰：只有寄件者或收件者算得出 key（對方確認是誰寄的）。
- 簽章再確認一次寄件者、而且收件者可以留存證據；信封被改一個字（含 to／seq／ts）簽章與 AEAD 都會失敗。
重放防護（ReplayGuard）：ts 要在 ±WINDOW 秒內；同一個寄件者的 seq 只能往上（上一個看到的存在 PeerStore）；
視窗內看過的 (from, salt) 不收第二次。
配對（pairing.py）時寄件者還不在名單上：信封多一個 "card" 欄位（寄件者名片），open_envelope 只在呼叫者明確
允許（allow_card=True）時才拿它來驗簽，而且解出來的 kind 一定要是 pair.request——其他情況一律「不認識的寄件者」。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

from synox.link.identity import IdentityError, NodeCard, NodeIdentity, b64, unb64

VERSION = 1
INFO_PREFIX = b"synox-link-v1"
WINDOW = 300                           # 秒：ts 跟現在差超過這麼多＝拒（兩台的時鐘要大致對）
MAX_FRAME = 1024 * 1024                # 一封信最多 1 MB（傳輸層也用這個數）
NONCE = b"\x00" * 12                   # 每封信的 key 都不同（salt＋一次性金鑰），nonce 固定沒有關係
PAIR_REQUEST = "pair.request"
_HEADER = ("v", "from", "to", "seq", "ts", "eph", "salt")


class LinkError(Exception):
    """信封不收（原因給人看；log 用）。"""


@dataclass
class Message:
    kind: str
    body: dict
    sender: str
    seq: int
    ts: int
    card: Optional[NodeCard] = None    # 配對請求帶的名片（只有 pair.request 會有）


def _aad(env: dict) -> bytes:
    return json.dumps({k: env[k] for k in _HEADER}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _key(shared: bytes, salt: bytes, sender: str, receiver: str) -> bytes:
    info = INFO_PREFIX + b"|" + sender.encode("ascii") + b"|" + receiver.encode("ascii")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(shared)


def seal(me: NodeIdentity, peer: NodeCard, kind: str, body: dict, *, seq: int, now: Optional[float] = None,
         card: Optional[NodeCard] = None) -> dict:
    """封一封給 peer 的信。card：配對請求才帶（自己的名片，給還不認識我的對方）。"""
    if not isinstance(kind, str) or not kind or not isinstance(body, dict):
        raise LinkError("kind 要是字串、body 要是 dict")
    import os
    eph = x25519.X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    salt = os.urandom(16)
    env = {"v": VERSION, "from": me.node_id, "to": peer.node_id, "seq": int(seq),
           "ts": int(now if now is not None else time.time()), "eph": b64(eph_pub), "salt": b64(salt)}
    shared = eph.exchange(peer.box_key) + me.exchange(peer.box_pub)
    key = _key(shared, salt, me.node_id, peer.node_id)
    plain = json.dumps({"kind": kind, "body": body}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    aad = _aad(env)
    ct = ChaCha20Poly1305(key).encrypt(NONCE, plain, aad)
    env["ct"] = b64(ct)
    env["sig"] = b64(me.sign(aad + ct))
    if card is not None:
        env["card"] = card.to_dict()
    return env


class ReplayGuard:
    """視窗內看過的 (from, salt) 不收第二次；每個寄件者的 seq 只能往上（last_seq 由 PeerStore 持久化）。"""

    def __init__(self, window: int = WINDOW, clock: Callable[[], float] = time.time):
        self.window = window
        self._clock = clock
        self._seen: Dict[tuple, int] = {}
        self._lock = threading.Lock()

    def check(self, sender: str, salt: str, ts: int, seq: int, last_seq: Optional[int]) -> None:
        now = int(self._clock())
        if abs(now - int(ts)) > self.window:
            raise LinkError(f"時間差太大（{abs(now - int(ts))} 秒；兩台的時鐘要對）")
        if last_seq is not None and int(seq) <= int(last_seq):
            raise LinkError(f"seq {seq} 不比上一封（{last_seq}）新：重放或亂序")
        with self._lock:
            for key, when in list(self._seen.items()):
                if now - when > self.window:
                    del self._seen[key]
            if (sender, salt) in self._seen:
                raise LinkError("同一封信收過了（重放）")
            self._seen[(sender, salt)] = int(ts)


def open_envelope(me: NodeIdentity, lookup: Callable[[str], Optional[NodeCard]], env: dict, guard: ReplayGuard,
                  *, last_seq: Callable[[str], Optional[int]] = lambda _s: None,
                  allow_card: bool = False) -> Message:
    """驗收一封信。lookup(node_id)→NodeCard（不認識回 None）。allow_card：寄件者不認識時准用信封上的名片
    （只在等配對的時候），而且解出來一定要是 pair.request。任何一步不過＝LinkError（不解釋太細，log 才有）。"""
    if not isinstance(env, dict) or env.get("v") != VERSION:
        raise LinkError("不是 v1 的信封")
    for key in _HEADER + ("ct", "sig"):
        if key not in env:
            raise LinkError(f"信封少了 {key}")
    sender, receiver = env["from"], env["to"]
    if not isinstance(sender, str) or not isinstance(receiver, str):
        raise LinkError("from／to 要是字串")
    if receiver != me.node_id:
        raise LinkError("不是寄給這一台的")
    if sender == me.node_id:
        raise LinkError("寄件者是自己")
    try:
        seq, ts = int(env["seq"]), int(env["ts"])
    except (TypeError, ValueError):
        raise LinkError("seq／ts 要是整數")
    card = lookup(sender)
    pairing = False
    if card is None:
        if not allow_card or not isinstance(env.get("card"), dict):
            raise LinkError(f"不認識的寄件者 {sender}")
        try:
            card = NodeCard.from_dict(env["card"])
        except IdentityError as e:
            raise LinkError(f"配對名片不對：{e}")
        if card.node_id != sender:
            raise LinkError("配對名片的 node_id 跟 from 不一樣")
        pairing = True
    try:
        eph_pub, salt, ct, sig = unb64(env["eph"]), unb64(env["salt"]), unb64(env["ct"]), unb64(env["sig"])
    except IdentityError as e:
        raise LinkError(str(e))
    if len(ct) > MAX_FRAME:
        raise LinkError("信太大")
    aad = _aad(env)
    try:
        card.sign_key.verify(sig, aad + ct)
    except (InvalidSignature, ValueError):
        raise LinkError("簽章不對")
    try:
        shared = me.exchange(eph_pub) + me.exchange(card.box_pub)
    except ValueError:
        raise LinkError("一次性公鑰不對")
    key = _key(shared, salt, sender, receiver)
    try:
        plain = ChaCha20Poly1305(key).decrypt(NONCE, ct, aad)
        inner = json.loads(plain.decode("utf-8"))
    except Exception:
        raise LinkError("解不開（金鑰不對或被改過）")
    if not isinstance(inner, dict) or not isinstance(inner.get("kind"), str) or not isinstance(inner.get("body"), dict):
        raise LinkError("內容格式不對")
    if pairing and inner["kind"] != PAIR_REQUEST:
        raise LinkError("不認識的寄件者只能送配對請求")
    guard.check(sender, env["salt"], ts, seq, None if pairing else last_seq(sender))
    return Message(kind=inner["kind"], body=inner["body"], sender=sender, seq=seq, ts=ts,
                   card=card if pairing else None)


def encode(env: dict) -> bytes:
    return json.dumps(env, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode(frame: bytes) -> dict:
    if len(frame) > MAX_FRAME + 4096:
        raise LinkError("信太大")
    try:
        env = json.loads(frame.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise LinkError("不是 JSON")
    if not isinstance(env, dict):
        raise LinkError("不是 JSON 物件")
    return env


__all__ = ["LinkError", "Message", "ReplayGuard", "seal", "open_envelope", "encode", "decode", "WINDOW", "MAX_FRAME",
           "PAIR_REQUEST"]
