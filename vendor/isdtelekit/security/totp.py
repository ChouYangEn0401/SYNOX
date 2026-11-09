"""
RFC 6238 TOTP（手機驗證器 App 用的 6 位數、30 秒一換），只用標準函式庫。

跟 Google Authenticator / Microsoft Authenticator / 1Password 相容：SHA-1、6 位數、30 秒。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

DIGITS = 6
STEP = 30


def new_secret() -> str:
    """160-bit 隨機密鑰，base32（驗證器 App 手動輸入時用的格式）。"""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def counter_now(now: Optional[float] = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def match(secret: str, code: str, now: Optional[float] = None, window: int = 1) -> Optional[int]:
    """code 對得上就回傳它所屬的 counter（給呼叫端擋重放），否則 None。容許前後各 window 個時段的時鐘誤差。"""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = counter_now(now)
    for counter in range(base - window, base + window + 1):
        if hmac.compare_digest(code_at(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret: str, account: str, issuer: str = "ISDTeleKit") -> str:
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"
