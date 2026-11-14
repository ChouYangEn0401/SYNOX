"""通道程式（下載來的執行檔）怎麼管（ADR 0026 §7）：SYNOX **不下載、不更新、不執行來檢查**它，只讀檔算雜湊。

    find(config) -> 路徑或 None           config.json 的 web.remote.tunnel.path；沒寫就找系統路徑上的 cloudflared
    describe(path) -> {"path", "size", "sha256", "signer"}
    approved(path, record) -> bool        路徑、大小、SHA-256 都跟核准時一樣

簽署者：Windows 上要另外跑程式才讀得到（**待實測**），這一版不跑任何程式，回 ""（畫面上說「讀不到，請自己對雜湊」）。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
from typing import Optional


def find(config) -> Optional[str]:
    remote = ((getattr(config, "web", {}) or {}).get("remote") or {})
    path = str(((remote.get("tunnel") or {}).get("path")) or "").strip()
    if path:
        return os.path.abspath(path) if os.path.isfile(path) else None
    found = shutil.which("cloudflared")
    return os.path.abspath(found) if found else None


def describe(path: str) -> dict:
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return {"path": os.path.abspath(path), "size": size, "sha256": h.hexdigest(), "signer": ""}


def approved(path: Optional[str], record: Optional[dict]) -> bool:
    if not path or not isinstance(record, dict) or not os.path.isfile(path):
        return False
    if os.path.normcase(os.path.abspath(path)) != os.path.normcase(str(record.get("path") or "")):
        return False
    info = describe(path)
    return info["size"] == record.get("size") and hmac.compare_digest(info["sha256"], str(record.get("sha256") or ""))
