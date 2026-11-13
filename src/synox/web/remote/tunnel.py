"""通道的小介面（ADR 0026 §1、§7；計畫 K7）。之後要換別家只換這一個檔。

    class Tunnel(Protocol):
        start(target_url, timeout=45.0) -> str     公開網址（https://<隨機>.trycloudflare.com）；失敗丟 TunnelError(code)
        stop()                                     先請它結束，5 秒沒結束就強制結束
        alive() -> bool

測試一律用 `web/remote/testing.py` 的 FakeTunnel：這台開發機永遠不執行通道程式。
"""

from __future__ import annotations

import atexit
import os
import re
import subprocess
import tempfile
import threading
import time
from typing import List, Optional, Protocol

URL_RE = re.compile(r"^https://[a-z0-9-]{1,63}\.trycloudflare\.com$")


class TunnelError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Tunnel(Protocol):
    def start(self, target_url: str, timeout: float = 45.0) -> str: ...

    def stop(self) -> None: ...

    def alive(self) -> bool: ...


FIND_RE = re.compile(r"https://[a-z0-9-]{1,63}\.trycloudflare\.com(?=[\s|\"'<>]|$)")
KEEP_ENV = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA")     # Windows 連網要的最少幾個；沒有任何金鑰
_RUNNING: List["CloudflaredTunnel"] = []


def _stop_all_at_exit() -> None:
    for t in list(_RUNNING):
        try:
            t.stop()
        except Exception:
            pass


atexit.register(_stop_all_at_exit)          # 第二層保險（第一層是 app.on_stop → manager.close）


def minimal_env(home: str) -> dict:
    """給通道程式的環境：只有 Windows 連網要的那幾個，HOME／USERPROFILE 指到空的暫存資料夾
    （不讀使用者資料夾裡的 cloudflared 設定檔、不繼承任何金鑰、token、保管箱的變數）。"""
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update({"HOME": home, "USERPROFILE": home, "TEMP": home, "TMP": home})
    return env


class CloudflaredTunnel:
    """跑 cloudflared 的 quick tunnel（ADR 0026 §7）：參數清單、不經 shell、空的工作資料夾、最小的環境、沒有標準輸入；
    讀輸出的執行緒只留符合 URL_RE 的那一段。**這台開發機的測試永遠不執行它**（subprocess.Popen 換成假的）。"""

    def __init__(self, path: str, *, popen=None, clock=time.monotonic):
        self.path = path
        self._popen = popen
        self.clock = clock
        self.proc = None
        self.url = ""
        self._found = threading.Event()
        self._home: Optional[str] = None

    def argv(self, target_url: str) -> List[str]:
        return [self.path, "tunnel", "--no-autoupdate", "--url", target_url]

    def start(self, target_url: str, timeout: float = 45.0) -> str:
        if not self.path:
            raise TunnelError("no_binary")
        self._home = tempfile.mkdtemp(prefix="synox-tunnel-")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        popen = self._popen or subprocess.Popen
        try:
            self.proc = popen(self.argv(target_url), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, cwd=self._home, env=minimal_env(self._home), shell=False,
                              creationflags=flags)
        except OSError:
            raise TunnelError("start")
        _RUNNING.append(self)
        threading.Thread(target=self._read, daemon=True, name="tunnel-output").start()
        if not self._found.wait(timeout):
            self.stop()
            raise TunnelError("timeout")
        return self.url

    def _read(self) -> None:
        proc = self.proc
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
                for m in FIND_RE.finditer(line):
                    if URL_RE.match(m.group(0)) and not self._found.is_set():
                        self.url = m.group(0)
                        self._found.set()
        except Exception:
            pass

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if self in _RUNNING:
            _RUNNING.remove(self)
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)
        except Exception:
            pass


def make(config, binary_path: str = "") -> Tunnel:
    """照設定建通道（這一版只有 cloudflared）。binary_path＝核准過的那個檔。"""
    kind = (((getattr(config, "web", {}) or {}).get("remote") or {}).get("tunnel") or {}).get("kind", "cloudflared")
    if kind != "cloudflared":
        raise TunnelError("unavailable")
    if not binary_path:
        from synox.web.remote import binary
        binary_path = binary.find(config) or ""
    return CloudflaredTunnel(binary_path)
