"""面對網際網路的請求檢查（ADR 0026 §5；計畫 K6）：parse 的每一列一壞一好；GuardedHandler 用記憶體裡的假連線（不開埠）。"""

import io
import json

import pytest

from synox.guard.http import GuardedHandler, Reject, parse, reply

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")
HOST = "quiet-river-1234.trycloudflare.com"


def h(**extra):
    base = {"Host": HOST}
    base.update(extra)
    return [(k.replace("_", "-"), v) for k, v in base.items()]


def post_headers(body=b"{}", **extra):
    base = {"Origin": f"https://{HOST}", "Content_Type": "application/json", "Content_Length": str(len(body))}
    base.update(extra)
    return h(**base)


def rejected(method, target, items, body=b""):
    with pytest.raises(Reject) as e:
        parse(method, target, items, body, host=HOST)
    return e.value.status, e.value.code


def test_good_requests():
    r = parse("GET", "/app.js?x=1", h(), b"", host=HOST)
    assert r.path == "/app.js" and r.query == {"x": "1"} and r.headers["host"] == HOST
    assert parse("POST", "/api/do/add", post_headers(b'{"values":{}}'), b'{"values":{}}', host=HOST).method == "POST"
    assert parse("GET", "/", h(Sec_Fetch_Site="none"), b"", host=HOST).path == "/"


@pytest.mark.parametrize("method,target,items,body,status", [
    ("PUT", "/", h(), b"", 405), ("OPTIONS", "/", h(), b"", 405), ("TRACE", "/", h(), b"", 405),
    ("GET", "/", [("Host", HOST)] + [(f"X-H{i}", "v") for i in range(60)], b"", 400),
    ("GET", "/", h(X_Big="v" * 5000), b"", 413),
    ("GET", "/", [("Host", HOST)] + [(f"X-H{i}", "v" * 4000) for i in range(5)], b"", 413),
    ("POST", "/api/do/a", post_headers(Transfer_Encoding="chunked"), b"{}", 400),
    ("POST", "/api/do/a", post_headers() + [("Content-Length", "2")], b"{}", 400),
    ("POST", "/api/do/a", h(Origin=f"https://{HOST}", Content_Type="application/json", Content_Length="-1"), b"{}", 400),
    ("POST", "/api/do/a", h(Origin=f"https://{HOST}", Content_Type="application/json", Content_Length="9"), b"{}", 400),
    ("POST", "/api/do/a", post_headers(b"x" * 70000), b"x" * 70000, 413),
    ("GET", "/", [("Host", HOST), ("Host", HOST)], b"", 400),
    ("GET", "/", h(Host="evil.example"), b"", 404), ("GET", "/", h(Host=HOST + ":443"), b"", 404),
    ("GET", "/", h(Host="1.2.3.4"), b"", 404),
    ("GET", "/", h(Cookie="a=1") + [("Cookie", "b=2")], b"", 400),
    ("GET", "/", h(Service_Worker="script"), b"", 400), ("GET", "/", h(Upgrade="websocket"), b"", 400),
    ("GET", "/", [("Host", HOST), ("Bad Name", "x")], b"", 400), ("GET", "/", h(X_A="a\r\nb"), b"", 400),
    ("GET", "http://evil/", h(), b"", 400), ("GET", "/" + "a" * 2100, h(), b"", 404),
    ("GET", "/../x", h(), b"", 404), ("GET", "/%2e%2e/x", h(), b"", 404),
    ("GET", "/x?" + "a=1&" * 300, h(), b"", 400), ("GET", "/x?a=1&a=2", h(), b"", 400),
    ("GET", "/x?" + "&".join(f"k{i}=1" for i in range(21)), h(), b"", 400),
    ("POST", "/api/do/a", post_headers(Origin="https://evil.example"), b"{}", 400),
    ("POST", "/api/do/a", post_headers(Sec_Fetch_Site="cross-site"), b"{}", 400),
    ("GET", "/", h(Sec_Fetch_Site="same-site"), b"", 400),
    ("POST", "/api/do/a", h(Origin=f"https://{HOST}", Content_Type="text/plain", Content_Length="2"), b"{}", 400),
    ("POST", "/api/do/a", post_headers(b"[1]"), b"[1]", 400),
    ("POST", "/api/do/a", post_headers(b'{"a":1,"a":2}'), b'{"a":1,"a":2}', 400),
])
def test_rejects(method, target, items, body, status):
    assert rejected(method, target, items, body)[0] == status


def test_reply_is_fixed():
    assert reply(404) == reply(404) and json.loads(reply(429)[2]) == {"ok": False, "code": "slow_down"}


class FakeSock:
    def __init__(self, data: bytes):
        self._in = io.BytesIO(data)
        self.out = b""

    def makefile(self, mode, *a, **k):
        return self._in if "r" in mode else io.BytesIO()

    def sendall(self, b):
        self.out += bytes(b)

    def settimeout(self, t):
        pass


class FakeServer:
    def __init__(self):
        self.calls = []

        class UI:
            def handle_raw(ui_self, method, target, items, body):
                self.calls.append((method, target, items, body))
                return 200, [("Content-Type", "text/plain")], b"ok"
        self.ui = UI()


def run(data: bytes):
    server = FakeServer()
    sock = FakeSock(data)
    GuardedHandler(sock, ("203.0.113.9", 1234), server)
    if sock.out.startswith(b"HTTP/"):
        status = int(sock.out.split(b" ", 2)[1])
    else:                                     # 看不懂的請求行＝HTTP/0.9：只送內容（還是那個固定的 JSON）
        code = json.loads(sock.out.decode("ascii"))["code"] if sock.out else ""
        status = {"bad_request": 400, "too_large": 413, "method": 405}.get(code, 0)
    return status, sock.out, server


def test_handler_passes_items_with_duplicates():
    status, out, server = run(b"GET /x HTTP/1.1\r\nHost: a\r\nX-A: 1\r\nX-A: 2\r\n\r\n")
    assert status == 200 and server.calls[0][2].count(("X-A", "1")) == 1 and ("X-A", "2") in server.calls[0][2]
    assert b"Python" not in out


@pytest.mark.parametrize("data,status", [
    (b"POST /x HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\nContent-Length: 3\r\n\r\nabc", 400),
    (b"POST /x HTTP/1.1\r\nHost: a\r\nContent-Length: 3\r\nContent-Length: 3\r\n\r\nabc", 400),
    (b"POST /x HTTP/1.1\r\nHost: a\r\nContent-Length: 99999999\r\n\r\n", 413),
    (b"GET /x HTTP/1.1\r\n" + b"".join(b"X-%d: v\r\n" % i for i in range(70)) + b"\r\n", 400),
    (b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n", 413),
    (b"DELETE /x HTTP/1.1\r\nHost: a\r\n\r\n", 405),
    (b"\x00\xff garbage\r\n\r\n", 400),
])
def test_handler_refusals(data, status):
    got, out, server = run(data)
    assert got == status and server.calls == []
    assert b"Traceback" not in out and b"Python" not in out
