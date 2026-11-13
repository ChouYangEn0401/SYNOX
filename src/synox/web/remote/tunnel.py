"""通道的小介面（ADR 0026 §1、§7；計畫 K7）。之後要換別家只換這一個檔。

    class Tunnel(Protocol):
        start(target_url, timeout=45.0) -> str     公開網址（https://<隨機>.trycloudflare.com）；失敗丟 TunnelError(code)
        stop()                                     先請它結束，5 秒沒結束就強制結束
        alive() -> bool

測試一律用 `web/remote/testing.py` 的 FakeTunnel：這台開發機永遠不執行通道程式。
"""

from __future__ import annotations

import re
from typing import Protocol

URL_RE = re.compile(r"^https://[a-z0-9-]{1,63}\.trycloudflare\.com$")


class TunnelError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Tunnel(Protocol):
    def start(self, target_url: str, timeout: float = 45.0) -> str: ...

    def stop(self) -> None: ...

    def alive(self) -> bool: ...


def make(config, binary_path: str = "") -> Tunnel:
    """照設定建通道。這一版只有 cloudflared（S14 的 CloudflaredTunnel）；還沒有的時候丟 TunnelError("unavailable")。"""
    raise TunnelError("unavailable")
