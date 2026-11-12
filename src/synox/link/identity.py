"""
節點身分（SYNOX Link，架構 v1 §L1）：每一台 SYNOX 一組長期金鑰，存在保管箱 data/link_identity.json.enc。

    ident = load_or_create(vault, name="客廳那台")   # 第一次產生、之後都同一組
    ident.node_id                                   # "3f2a-9c1e-…"（24 個十六進位字，6 組）：給人看、給 to/from 用
    ident.card()                                    # NodeCard：給對方的「名片」（只有公鑰，可以公開）

兩把金鑰、各做各的事（照 libsodium／Signal 的做法，不用 Ed25519→X25519 轉換，cryptography 套件也沒提供）：
- Ed25519：簽章（身分）。node_id ＝ SHA-256(簽章公鑰) 的前 12 bytes。
- X25519：金鑰交換（加密）。名片上的 X25519 公鑰由 Ed25519 簽過（card["sig"]），所以拿到名片就能確認兩把是同一台的。

私鑰永遠不離開保管箱；名片（NodeCard）只有公鑰。配對（pairing.py）交換的就是名片。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

VAULT_NAME = "link_identity"
CARD_VERSION = 1
ID_BYTES = 12
NODE_ID_RE = re.compile(r"^[0-9a-f]{4}(-[0-9a-f]{4}){5}$")
NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,40}$")
_CARD_SIGNED = ("v", "node_id", "name", "sign_pub", "box_pub")


class IdentityError(Exception):
    """身分／名片壞掉（給人看的訊息）。"""


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unb64(text: str) -> bytes:
    if not isinstance(text, str):
        raise IdentityError("不是 base64 文字")
    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + pad)
    except (ValueError, TypeError) as e:
        raise IdentityError(f"base64 解不開：{e}")


def node_id_of(sign_pub: bytes) -> str:
    digest = hashlib.sha256(sign_pub).digest()[:ID_BYTES].hex()
    return "-".join(digest[i:i + 4] for i in range(0, len(digest), 4))


def _signed_bytes(fields: dict) -> bytes:
    """名片被簽的那一段：固定欄位、固定順序的 JSON。"""
    return json.dumps({k: fields[k] for k in _CARD_SIGNED}, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class NodeCard:
    """一台 SYNOX 的名片：node_id、名字、兩把公鑰、Ed25519 對 X25519 公鑰的簽章。可以公開，但要完整。"""
    node_id: str
    name: str
    sign_pub: bytes
    box_pub: bytes
    sig: bytes

    def to_dict(self) -> dict:
        return {"v": CARD_VERSION, "node_id": self.node_id, "name": self.name, "sign_pub": b64(self.sign_pub),
                "box_pub": b64(self.box_pub), "sig": b64(self.sig)}

    def to_text(self) -> str:
        """一行文字（給人複製貼上：`synox link trust <這一行>`）。"""
        return "SYNOX-CARD-1:" + b64(json.dumps(self.to_dict(), separators=(",", ":")).encode("utf-8"))

    @classmethod
    def from_dict(cls, raw: dict) -> "NodeCard":
        if not isinstance(raw, dict) or raw.get("v") != CARD_VERSION:
            raise IdentityError("名片版本不對（要 v=1）")
        for key in ("node_id", "name", "sign_pub", "box_pub", "sig"):
            if not isinstance(raw.get(key), str):
                raise IdentityError(f"名片少了 {key}")
        card = cls(node_id=raw["node_id"], name=raw["name"], sign_pub=unb64(raw["sign_pub"]),
                   box_pub=unb64(raw["box_pub"]), sig=unb64(raw["sig"]))
        card.verify()
        return card

    @classmethod
    def from_text(cls, text: str) -> "NodeCard":
        text = (text or "").strip()
        if not text.startswith("SYNOX-CARD-1:"):
            raise IdentityError("這不是 SYNOX 名片（要以 SYNOX-CARD-1: 開頭）")
        try:
            raw = json.loads(unb64(text.split(":", 1)[1]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise IdentityError(f"名片解不開：{e}")
        return cls.from_dict(raw)

    def verify(self) -> None:
        """node_id 要對得上簽章公鑰、X25519 公鑰要有 Ed25519 的簽章、名字要合法。不合丟 IdentityError。"""
        if not NODE_ID_RE.match(self.node_id) or node_id_of(self.sign_pub) != self.node_id:
            raise IdentityError("名片的 node_id 跟公鑰對不上")
        if not NAME_RE.match(self.name):
            raise IdentityError("名片的名字不合法（1–40 字、不能有控制字元）")
        if len(self.sign_pub) != 32 or len(self.box_pub) != 32:
            raise IdentityError("名片的公鑰長度不對")
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(self.sign_pub).verify(
                self.sig, _signed_bytes({"v": CARD_VERSION, "node_id": self.node_id, "name": self.name,
                                         "sign_pub": b64(self.sign_pub), "box_pub": b64(self.box_pub)}))
        except (InvalidSignature, ValueError):
            raise IdentityError("名片的簽章不對（被改過，或不是同一台產生的）")

    @property
    def box_key(self) -> x25519.X25519PublicKey:
        return x25519.X25519PublicKey.from_public_bytes(self.box_pub)

    @property
    def sign_key(self) -> ed25519.Ed25519PublicKey:
        return ed25519.Ed25519PublicKey.from_public_bytes(self.sign_pub)


class NodeIdentity:
    """這一台的兩把私鑰。只在 load_or_create（保管箱）與測試裡產生。"""

    def __init__(self, sign_priv: ed25519.Ed25519PrivateKey, box_priv: x25519.X25519PrivateKey, name: str):
        if not NAME_RE.match(name or ""):
            raise IdentityError("節點名字不合法（1–40 字、不能有控制字元）")
        self._sign = sign_priv
        self._box = box_priv
        self.name = name
        self.sign_pub = sign_priv.public_key().public_bytes(serialization.Encoding.Raw,
                                                           serialization.PublicFormat.Raw)
        self.box_pub = box_priv.public_key().public_bytes(serialization.Encoding.Raw,
                                                          serialization.PublicFormat.Raw)
        self.node_id = node_id_of(self.sign_pub)

    @classmethod
    def generate(cls, name: str) -> "NodeIdentity":
        return cls(ed25519.Ed25519PrivateKey.generate(), x25519.X25519PrivateKey.generate(), name)

    def card(self) -> NodeCard:
        fields = {"v": CARD_VERSION, "node_id": self.node_id, "name": self.name,
                  "sign_pub": b64(self.sign_pub), "box_pub": b64(self.box_pub)}
        sig = self._sign.sign(_signed_bytes(fields))
        return NodeCard(self.node_id, self.name, self.sign_pub, self.box_pub, sig)

    # ── 給 envelope.py 用 ──────────────────────────────────────────────

    def sign(self, data: bytes) -> bytes:
        return self._sign.sign(data)

    def exchange(self, peer_box_pub: bytes) -> bytes:
        return self._box.exchange(x25519.X25519PublicKey.from_public_bytes(peer_box_pub))

    # ── 保管箱 ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        raw = serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        return {"v": CARD_VERSION, "name": self.name,
                "sign_priv": b64(self._sign.private_bytes(*raw)), "box_priv": b64(self._box.private_bytes(*raw))}

    @classmethod
    def from_dict(cls, raw: dict) -> "NodeIdentity":
        if not isinstance(raw, dict) or raw.get("v") != CARD_VERSION:
            raise IdentityError("link_identity 的格式不對")
        try:
            sign = ed25519.Ed25519PrivateKey.from_private_bytes(unb64(raw["sign_priv"]))
            box = x25519.X25519PrivateKey.from_private_bytes(unb64(raw["box_priv"]))
        except (KeyError, ValueError, TypeError) as e:
            raise IdentityError(f"link_identity 的金鑰讀不出來：{e}")
        return cls(sign, box, str(raw.get("name") or "SYNOX"))


def load_or_create(vault, name: str) -> NodeIdentity:
    """保管箱裡有就讀（名字以 config 的為準、改了就存回），沒有就產生一組新的存進去。"""
    raw = vault.load_json(VAULT_NAME, None)
    if raw is None:
        ident = NodeIdentity.generate(name)
        vault.save_json(VAULT_NAME, ident.to_dict())
        return ident
    ident = NodeIdentity.from_dict(raw)
    if ident.name != name:
        ident.name = name
        vault.save_json(VAULT_NAME, ident.to_dict())
    return ident


def short_id(node_id: str) -> str:
    """給訊息裡用的短寫：前兩組（例如 3f2a-9c1e）。"""
    return "-".join(node_id.split("-")[:2]) if node_id else "?"


__all__ = ["IdentityError", "NodeCard", "NodeIdentity", "load_or_create", "node_id_of", "short_id", "b64", "unb64",
           "NODE_ID_RE", "VAULT_NAME"]
