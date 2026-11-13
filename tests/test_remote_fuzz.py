"""手機入口的模糊測試（ADR 0026 §5 的清單＋固定種子的亂數）：每一條都要回固定的拒絕、不丟例外、不呼叫到工具的函式、
回應裡沒有輸入的任何片段。直接餵給 handle_raw 與 GuardedHandler，不開埠、不開子程序。"""

import io
import json
import random
import sys

import pytest

from synox.guard.http import GuardedHandler

from remote_helpers import make_phone

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")
ALLOWED = {400, 404, 405, 413, 429}
FRAGMENTS = ["/../", "/..%2f", "/%2e%2e/", "/.%2e/", "/%252e%252e/", "/..;/", "//etc/passwd", "/\\..\\", "/C:/",
             "/app/../../config.json", "%00", "\x00", "\r\n", "．．／", "e\u0301", "\u202e", "\ud800", "/api/export/x",
             "/api/keep", "/api/apps", "/login", "GET http://other/", "Content-Length: -1", "Transfer-Encoding: chunked",
             '{"a":1,"a":2}', "[1,2]", "{" * 100, "\xff\xfe"]
CASES = [
    ("GET", "/../", {}), ("GET", "/..%2f", {}), ("GET", "/%2e%2e/", {}), ("GET", "/.%2e/", {}), ("GET", "/%252e%252e/", {}),
    ("GET", "/..;/", {}), ("GET", "//etc/passwd", {}), ("GET", "/\\..\\", {}), ("GET", "/C:/", {}),
    ("GET", "/app/../../config.json", {}), ("GET", "/a%00", {}), ("GET", "/a\x00", {}), ("GET", "/．．／", {}),
    ("GET", "/e\u0301", {}), ("GET", "/\u202e", {}), ("GET", "http://other/", {}), ("OPTIONS", "/", {}), ("PUT", "/", {}),
    ("DELETE", "/", {}), ("TRACE", "/", {}), ("CONNECT", "/", {}), ("GET", "/", {"Host": "evil.example"}),
    ("GET", "/", {"Host": "1.2.3.4"}), ("GET", "/", {"Host": "{host}:443"}), ("GET", "/api/me", {}),
    ("POST", "/_synox/enter", {"_body": b"[1,2]"}), ("POST", "/_synox/enter", {"_body": b'{"k":1,"k":2}'}),
    ("POST", "/_synox/enter", {"_body": b'{"a":' * 100 + b"1" + b"}" * 100}),
    ("POST", "/_synox/enter", {"_body": b'{"k":"' + b"x" * (1 << 20) + b'"}'}),
    ("POST", "/_synox/enter", {"_body": b"\xff\xfe"}),
    ("GET", "/api/me", {"Cookie": "__Host-synox_remote=a; __Host-synox_remote=b"}),
    ("GET", "/api/me", {"Cookie": "__Host-synox_remote=expired"}),
]


def snapshot():
    return dict(sys.modules["synox_pack_counter"].CALLS)


@pytest.fixture
def gate(counter, owner):
    phone = make_phone(counter, owner)
    phone.open()
    phone.manager.rate_ok = lambda link, entered: True              # 這裡測的是解析與白名單，不是次數
    phone.manager.rejected = lambda link, code: None
    return phone


def call(phone, method, target, extra):
    host = phone.manager.link.host
    body = extra.pop("_body", b"")
    items = [("Host", extra.pop("Host", host).replace("{host}", host)), ("User-Agent", "Fuzz/1.0")]
    if method == "POST":
        items += [("Origin", f"https://{host}"), ("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    items += list(extra.items())
    return phone.manager.gate.handle_raw(method, target, items, body)


@pytest.mark.parametrize("method,target,extra", CASES)
def test_listed_cases(gate, method, target, extra):
    before = snapshot()
    status, _h, body = call(gate, method, target, dict(extra))
    assert status in ALLOWED | {403}, (method, target, status)
    assert snapshot() == before
    for piece in ("passwd", "config.json", "evil.example"):
        assert piece.encode() not in body


def test_random_requests_to_the_gate(gate):
    rng = random.Random(20261114)
    before = snapshot()
    for _ in range(1000):
        target = "/" + "".join(rng.choice(FRAGMENTS + ["a", "b", "/", "?", "=", "&"]) for _ in range(rng.randint(1, 6)))
        method = rng.choice(["GET", "POST", "PUT", "OPTIONS", "get", ""])
        body = bytes(rng.randrange(256) for _ in range(rng.randint(0, 40))) if rng.random() < .5 \
            else "".join(rng.choice(FRAGMENTS) for _ in range(3)).encode("utf-8", "surrogatepass")
        extra = {}
        if rng.random() < .3:
            extra["X-" + str(rng.randint(0, 9))] = rng.choice(FRAGMENTS)[:20]
        try:
            status, _h, out = call(gate, method, target, dict(extra, _body=body))
        except Exception as e:                            # 不准有例外漏出來
            pytest.fail(f"exception {type(e).__name__} for {method!r} {target!r}")
        entry_page = status == 200 and target.split("?")[0] == "/" and method == "GET"    # 進門頁（SYNOX 自己的）
        assert status in ALLOWED | {403} or entry_page, (method, target, status)
        for piece in ("passwd", "config.json", "secret"):
            assert piece.encode() not in out
    assert snapshot() == before


def test_random_bytes_to_the_handler(gate):
    rng = random.Random(1114)
    calls = []

    class Server:
        class ui:
            @staticmethod
            def handle_raw(method, target, items, body):
                calls.append(1)
                return gate.manager.gate.handle_raw(method, target, items, body)

    class Sock:
        def __init__(self, data):
            self._in, self.out = io.BytesIO(data), b""

        def makefile(self, mode, *a, **k):
            return self._in if "r" in mode else io.BytesIO()

        def sendall(self, b):
            self.out += bytes(b)

        def settimeout(self, t):
            pass

    before = snapshot()
    for _ in range(1000):
        if rng.random() < .5:
            data = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
        else:
            parts = ["GET ", rng.choice(FRAGMENTS), " HTTP/1.1\r\n", "Host: x\r\n", rng.choice(FRAGMENTS), "\r\n\r\n"]
            data = "".join(rng.sample(parts, len(parts)) if rng.random() < .3 else parts).encode("utf-8", "surrogatepass")
        sock = Sock(data)
        try:
            GuardedHandler(sock, ("203.0.113.9", 1), Server())
        except Exception as e:
            pytest.fail(f"handler leaked {type(e).__name__}")
        if sock.out.startswith(b"HTTP/"):
            assert int(sock.out.split(b" ", 2)[1]) in ALLOWED | {403}
        assert b"Traceback" not in sock.out and b"passwd" not in sock.out
    assert snapshot() == before
