"""
發佈的簽章（docs/adr/0023 §7、決定 U5）：維護者用 Ed25519 私鑰簽 `release.json`，SYNOX 用寫在這裡的公鑰驗。

- 附檔：`release.json`（版本、日期、每個附檔的 sha256 與大小；`scripts/release.py sign` 產生）＋
  `release.json.sig`（對 release.json **原本的位元組**簽，base64 一行）。
- 公鑰：`RELEASE_PUBLIC_KEYS`（base64 的 32 位元組原始公鑰，可以有好幾把：換鑰匙時新舊並存一陣子）。
  **私鑰只在創始維護者手上、離線保存，絕不進 repo**（docs/release-build.md「簽章金鑰」）。
- 到現在還**沒有**公鑰（創始維護者還沒產生金鑰）：`public_keys()` 是空的 → 每一版都算「沒有簽章」→
  Update.bat 不自動換檔，除非使用者明確加 `-AllowUnsigned`（並照實說「信任的只有 HTTPS＋GitHub 這個 repo」）。
- 簽章對不上一律拒絕（就算加了 -AllowUnsigned 也一樣）：那代表檔案被動過。
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Iterable, List, Optional, Sequence

MANIFEST_ASSET = "release.json"
SIG_ASSET = "release.json.sig"
SUMS_ASSET = "SHA256SUMS.txt"

# 創始維護者產生金鑰之後，把公鑰加在這裡：32 位元組原始公鑰的 base64（44 個字，結尾是 =）。
# `python scripts/release.py keygen` 產生一對、`python scripts/release.py sign --key <私鑰檔> --show-public` 印公鑰。
RELEASE_PUBLIC_KEYS: Sequence[str] = ()


class SignatureError(Exception):
    pass


def public_keys(keys: Optional[Iterable[str]] = None) -> List[bytes]:
    """可以用的公鑰（32 位元組）；寫壞的那把不算。keys=None＝用 RELEASE_PUBLIC_KEYS。"""
    out = []
    for k in (RELEASE_PUBLIC_KEYS if keys is None else keys):
        try:
            raw = base64.b64decode(str(k).strip(), validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(raw) == 32:
            out.append(raw)
    return out


def verify(manifest: bytes, signature: bytes, keys: Optional[Iterable[str]] = None) -> bool:
    """release.json 的位元組＋.sig 的內容（base64 文字）→ 有沒有一把公鑰驗得過。沒有公鑰＝False。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        sig = base64.b64decode(signature.decode("ascii").strip(), validate=True)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    if len(sig) != 64:
        return False
    for raw in public_keys(keys):
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(sig, manifest)
            return True
        except (InvalidSignature, ValueError):
            continue
    return False


def parse_manifest(blob: bytes) -> dict:
    """release.json → dict（version、assets{名字: {sha256, size}}）；格式不對丟 SignatureError。"""
    try:
        raw = json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SignatureError("release.json 看不懂")
    if not isinstance(raw, dict) or not isinstance(raw.get("version"), str) or not isinstance(raw.get("assets"), dict):
        raise SignatureError("release.json 少了 version 或 assets")
    for name, info in raw["assets"].items():
        if not (isinstance(info, dict) and isinstance(info.get("sha256"), str) and len(info["sha256"]) == 64):
            raise SignatureError(f"release.json 的 {name} 沒有 sha256")
    return raw


def parse_sums(text: str) -> dict:
    """SHA256SUMS.txt（`<64 個十六進位字>  <檔名>`，檔名前可以有 *）→ {檔名: sha256}。"""
    out = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64 and all(c in "0123456789abcdefABCDEF" for c in parts[0]):
            out[parts[1].strip().lstrip("*")] = parts[0].lower()
    return out
