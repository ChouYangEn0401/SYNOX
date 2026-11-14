"""面對網際網路的請求檢查（ADR 0026 §5；計畫 K6）：手機入口閘門的第一步，一份、可以單獨測。

    req = parse(method, target, header_items, body, host="abc.trycloudflare.com")    # 不合丟 Reject(status, code)
    reply(status, code) -> Resp                                                        # 固定的小 JSON，沒有任何細節

- 方法只收 GET、POST；標頭 ≤ 60 個、合計 ≤ 16 KB、單一個 ≤ 4 KB；Transfer-Encoding 一律拒；Content-Length 出現兩次、不是純數字、
  跟實際不合一律拒（請求走私）；內容 ≤ 64 KB。
- Host 一字不差等於這次的網域（不是＝404，跟「沒有這個網站」一樣）；Host、Cookie、Content-Type、Origin、X-SYNOX-App 出現兩次＝拒；
  帶 Service-Worker、Upgrade＝拒。
- 路徑：`/` 或過得了 `guard.inputs.rel_path`（`..`、編碼過的斜線、雙重編碼、反斜線、非 ASCII…）；不合＝404。查詢參數 ≤ 1024 字、≤ 20 個、同名只准一個。
- POST：Origin 一定是 `https://<這次的網域>`；Sec-Fetch-Site 有帶就只收 same-origin（GET 另外收 none）；內容是 UTF-8 的 JSON 物件（`inputs.json_object`）。
- `GuardedHandler`：給 `web/apps/listen.py` 用的另一種薄殼（timeout 15 秒、讀內容前先對大小、同時最多 16 條連線），
  把標頭以「清單」（保留重複）交給 `server.ui.handle_raw(method, target, items, body)`。
這個檔只 import 門禁核心自己的 inputs，不 import synox 的其他部分。
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import Dict, List, Tuple
from urllib.parse import parse_qsl

from synox.guard import inputs

Resp = Tuple[int, List[Tuple[str, str]], bytes]
CODES = {400: "bad_request", 403: "forbidden", 404: "not_found", 405: "method", 413: "too_large", 429: "slow_down"}
SINGLE = ("host", "cookie", "content-type", "origin", "x-synox-app", "content-length")
BANNED = ("service-worker", "upgrade", "transfer-encoding")
_TOKEN = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
MAX_CONNECTIONS = 16


@dataclass(frozen=True)
class Limits:
    header_bytes: int = 16384
    headers: int = 60
    header_value: int = 4096
    body: int = 65536
    target: int = 2048
    query: int = 1024
    params: int = 20


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""


class Reject(Exception):
    def __init__(self, status: int, code: str = ""):
        super().__init__(code or CODES.get(status, "bad_request"))
        self.status = int(status)
        self.code = code or CODES.get(self.status, "bad_request")


def reply(status: int, code: str = "") -> Resp:
    """固定的小 JSON：同一個狀態永遠是同樣的位元組（不洩漏差在哪）。"""
    body = json.dumps({"ok": False, "code": code or CODES.get(int(status), "bad_request")}).encode("ascii")
    return int(status), [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"),
                         ("X-Content-Type-Options", "nosniff")], body


def parse(method, target, header_items, body, *, host: str, limits: Limits = Limits()) -> Request:
    method = str(method or "").upper()
    if method not in ("GET", "POST"):
        raise Reject(405)
    items = list(header_items or [])
    if len(items) > limits.headers:
        raise Reject(400)
    total = 0
    headers: Dict[str, str] = {}
    for name, value in items:
        name, value = str(name), str(value)
        total += len(name) + len(value) + 4
        if not _TOKEN.match(name) or any(c in value for c in "\r\n\x00"):
            raise Reject(400)
        if len(value) > limits.header_value:
            raise Reject(413)
        key = name.lower()
        if key in BANNED:
            raise Reject(400)
        if key in headers and key in SINGLE:
            raise Reject(400)
        headers[key] = value if key not in headers else headers[key] + ", " + value
    if total > limits.header_bytes:
        raise Reject(413)
    body = bytes(body or b"")
    if "content-length" in headers:
        cl = headers["content-length"].strip()
        if not (cl.isascii() and cl.isdigit()) or int(cl) != len(body):
            raise Reject(400)
    if len(body) > limits.body:
        raise Reject(413)
    if headers.get("host", "") != host:
        raise Reject(404)
    target = str(target or "")
    if not target.startswith("/") or len(target) > limits.target or any(not (0x21 <= ord(c) <= 0x7E) for c in target):
        raise Reject(400 if not target.startswith("/") else 404)
    path, _, query = target.partition("?")
    if path != "/":
        try:
            inputs.rel_path(path)
        except inputs.Bad:
            raise Reject(404)
    params: Dict[str, str] = {}
    if query:
        if len(query) > limits.query:
            raise Reject(400)
        try:
            pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, errors="strict")
        except (ValueError, UnicodeDecodeError):
            raise Reject(400)
        if len(pairs) > limits.params:
            raise Reject(400)
        for k, v in pairs:
            if k in params:
                raise Reject(400)
            try:
                params[inputs.text(k, max=64)] = inputs.text(v, max=limits.query)
            except inputs.Bad:
                raise Reject(400)
    site = headers.get("sec-fetch-site")
    if method == "POST":
        if headers.get("origin") != f"https://{host}":
            raise Reject(400)
        if site is not None and site != "same-origin":
            raise Reject(400)
        if not headers.get("content-type", "").lower().startswith("application/json"):
            raise Reject(400)
        try:
            inputs.json_object(body, max_bytes=limits.body, max_depth=4)
        except inputs.Bad:
            raise Reject(400)
    elif site is not None and site not in ("same-origin", "none"):
        raise Reject(400)
    return Request(method, path, params, headers, body)


class GuardedHandler(BaseHTTPRequestHandler):
    """閘門的薄殼（給 listen.open_listener(handler=GuardedHandler) 用）。任何錯誤都是固定的回應，沒有例外漏出去。"""

    server_version = "SYNOX"
    sys_version = ""
    timeout = 15
    limits = Limits()
    _slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def version_string(self) -> str:
        return "SYNOX"

    def log_message(self, fmt, *args) -> None:        # 不把對方送來的路徑寫進 log
        return

    def handle(self) -> None:
        if not GuardedHandler._slots.acquire(blocking=False):
            # 還沒讀請求行（send_response 要用到它）：直接寫一個完整、固定的回應
            self.close_connection = True
            status, headers, body = reply(429)
            head = "HTTP/1.1 429 Too Many Requests\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers) + \
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            try:
                self.wfile.write(head.encode("ascii") + body)
            except Exception:
                pass
            return
        try:
            super().handle()
        except Exception:
            self.close_connection = True
        finally:
            GuardedHandler._slots.release()

    def _write(self, resp: Resp) -> None:
        status, headers, body = resp
        self.send_response(int(status))
        for k, v in headers:
            if k.lower() not in ("content-length", "connection"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def send_error(self, code, message=None, explain=None) -> None:
        status = 405 if code == 501 else 413 if code in (413, 414, 431) else 400
        try:
            self._write(reply(status))
        except Exception:
            self.close_connection = True

    def _go(self) -> None:
        try:
            items = list(self.headers.items())
            names = [k.lower() for k, _v in items]
            if len(items) > self.limits.headers or sum(len(k) + len(v) + 4 for k, v in items) > self.limits.header_bytes:
                return self._write(reply(413 if len(items) <= self.limits.headers else 400))
            if "transfer-encoding" in names or names.count("content-length") > 1:
                return self._write(reply(400))
            raw = self.headers.get("Content-Length")
            length = 0
            if raw is not None:
                if not (raw.strip().isascii() and raw.strip().isdigit()):
                    return self._write(reply(400))
                length = int(raw.strip())
            if length > self.limits.body:
                return self._write(reply(413))                    # 內容沒有被讀
            body = self.rfile.read(length) if length else b""
            if len(body) != length:
                return self._write(reply(400))
            resp = self.server.ui.handle_raw(self.command, self.path, items, body)
            self._write(resp)
        except Exception:
            try:
                self._write(reply(400))
            except Exception:
                self.close_connection = True

    def do_GET(self) -> None:
        self._go()

    def do_POST(self) -> None:
        self._go()

    def _refuse(self) -> None:
        self._write(reply(405))

    do_PUT = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = do_PATCH = do_HEAD = _refuse
