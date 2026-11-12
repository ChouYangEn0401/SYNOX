"""
配對（SYNOX Link，架構 v1 §L6）：兩台互相拿到對方的名片，之後才收得了對方的信。一次複製貼上：

    主控台電腦：  python -m synox link pair          → 印一行配對碼（10 分鐘內有效、只能用一次）
    哨兵電腦：    python -m synox link join "<配對碼>"  → 存起來；哨兵一跑起來（或已經在跑）就送配對請求

配對碼 = SYNOX-PAIR-1:<主控台名片>:<一次性秘密 16 bytes>
- 哨兵從碼裡拿到主控台的名片（公鑰）→ 可以封信給主控台（信封的 to／簽章都照常）。
- 哨兵的名片放在信封的 card 欄位（主控台還不認識它）；body 帶 mac = HMAC-SHA256(秘密, 哨兵名片 ‖ 主控台 node_id)。
- 主控台：pair.request 只在「有等著的配對碼」時收；mac 對了才把哨兵的名片寫進名單，回 pair.ok（已經封給哨兵）。
  mac 不對、過期、用過＝丟掉（不回任何東西：拿到舊碼的人什麼都探不到）。
- 哨兵收到 pair.ok（簽章與金鑰都對得上碼裡的名片）→ 把主控台寫進名單、清掉 pending。
拿到配對碼的人能做什麼：在 10 分鐘內以「哨兵」身分加進名單（主控台之後可能派任務給它；它拿不到主控台的任何資料，
也不能對主控台下指令——哨兵的信只會被當成任務的回報）。配對碼仍然要當祕密對待、只在自己的電腦上貼。
沒有網路也能配：`python -m synox link card` 印名片、對方 `python -m synox link trust "<名片>" --role worker`。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional, Tuple

from synox.link.identity import IdentityError, NodeCard, b64, unb64

PENDING_NAME = "link_pairing"          # 主控台：等著的配對碼（保管箱）
JOIN_NAME = "link_join"                # 哨兵：還沒送出的配對請求（保管箱）
TTL = 600
PREFIX = "SYNOX-PAIR-1:"


class PairingError(Exception):
    pass


def mac_of(secret: bytes, card: NodeCard, console_id: str) -> str:
    return b64(hmac.new(secret, card.to_text().encode("ascii") + b"|" + console_id.encode("ascii"),
                        hashlib.sha256).digest())


def make_code(console_card: NodeCard, secret: Optional[bytes] = None) -> Tuple[str, bytes]:
    secret = secret or os.urandom(16)
    return PREFIX + console_card.to_text() + ":" + b64(secret), secret


def parse_code(code: str) -> Tuple[NodeCard, bytes]:
    code = (code or "").strip()
    if not code.startswith(PREFIX):
        raise PairingError("這不是配對碼（要以 SYNOX-PAIR-1: 開頭）")
    rest = code[len(PREFIX):]
    card_text, _, secret = rest.rpartition(":")
    try:
        card = NodeCard.from_text(card_text)
        secret_bytes = unb64(secret)
    except IdentityError as e:
        raise PairingError(f"配對碼壞掉：{e}")
    if len(secret_bytes) != 16:
        raise PairingError("配對碼壞掉：秘密長度不對")
    return card, secret_bytes


# ── 主控台這一邊 ─────────────────────────────────────────────────

def issue(vault, console_card: NodeCard, *, now: Optional[float] = None) -> str:
    """產生一個配對碼存進保管箱（蓋掉舊的）。"""
    code, secret = make_code(console_card)
    vault.save_json(PENDING_NAME, {"v": 1, "secret": b64(secret), "issued": int(now or time.time())})
    return code


def pending(vault, *, now: Optional[float] = None) -> Optional[bytes]:
    raw = vault.load_json(PENDING_NAME, None)
    if not raw:
        return None
    if int(now or time.time()) - int(raw.get("issued") or 0) > TTL:
        return None
    try:
        return unb64(raw["secret"])
    except (KeyError, IdentityError):
        return None


def clear_pending(vault) -> None:
    if vault.exists(PENDING_NAME):
        vault.save_json(PENDING_NAME, {})


def verify_request(secret: bytes, card: NodeCard, console_id: str, mac: str) -> bool:
    return isinstance(mac, str) and hmac.compare_digest(mac_of(secret, card, console_id), mac)


# ── 哨兵這一邊 ───────────────────────────────────────────────────

def save_join(vault, code: str, *, now: Optional[float] = None) -> NodeCard:
    card, secret = parse_code(code)
    vault.save_json(JOIN_NAME, {"v": 1, "card": card.to_dict(), "secret": b64(secret), "saved": int(now or time.time())})
    return card


def pending_join(vault, *, now: Optional[float] = None) -> Optional[Tuple[NodeCard, bytes]]:
    raw = vault.load_json(JOIN_NAME, None)
    if not raw:
        return None
    if int(now or time.time()) - int(raw.get("saved") or 0) > TTL:
        return None
    try:
        return NodeCard.from_dict(raw["card"]), unb64(raw["secret"])
    except (KeyError, IdentityError):
        return None


def clear_join(vault) -> None:
    if vault.exists(JOIN_NAME):
        vault.save_json(JOIN_NAME, {})


__all__ = ["PairingError", "make_code", "parse_code", "mac_of", "issue", "pending", "clear_pending", "verify_request",
           "save_join", "pending_join", "clear_join", "TTL", "PENDING_NAME", "JOIN_NAME"]
