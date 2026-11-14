"""獨立安全審查第 1 輪（2026-11-14）的回歸測試：每一條在修之前會失敗。不開埠、不開子程序。"""

import io
import json
import threading

import pytest

from isdtelekit.core.registry import AI, TYPED, WRITE

from synox import guard, policy
from synox.guard.origin import Origin, using
from synox.guard.testing import Clock, code_for, enroll
from synox.web.remote import RemoteError

from remote_helpers import make_phone
from test_web import Client

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")


# 1 ── pack.json 的 stepup 列了的指令（不是危險的），AI 叫的時候也要經確認卡，按 ✅ 時以人的身分要求解鎖
def test_ai_call_of_stepup_command_needs_card_and_unlock(make_bot, owner):
    bot = make_bot([{"tool": "probe__vault", "args": {}}, "好"])
    ran = []
    node = bot.app.registry.ensure_group("probe", "probe").leaf(
        "vault", lambda api, chat_id, user, args: (ran.append(1), api.send_message(chat_id, "done")), "w", effect=WRITE)
    g = guard.of(bot.app)
    g.scope.restrict(node.path, stepup=True)
    clock = Clock()
    secret = enroll(g, owner, clock)
    bot.talk(owner, "跑 vault")
    assert not ran                                               # 沒有直接執行
    go = [b for b in bot.buttons(owner) if b.startswith("agent_ok:go:")]
    assert go, "應該送確認卡"
    bot.press(owner, go[0])
    assert not ran and "解鎖" in bot.last(owner)
    bot.say(owner, f"/unlock {code_for(secret, clock)}")
    bot.press(owner, go[0])
    assert ran


# 2 ── 正在開的時候再開一次：第二次是 busy，第一次照常完成，沒有留下沒人管的通道或閘門
def test_second_open_during_slow_start_is_busy_and_nothing_leaks(counter, owner):
    phone = make_phone(counter, owner)
    user = phone.bot.app.users.get_or_create(owner)
    m = phone.manager
    inner = {}

    class SlowTunnel:
        stopped = 0

        def start(self, url, timeout=45.0):
            try:
                m.open("counter", user, phone.code(), origin=phone.tg)
            except RemoteError as e:
                inner["code"] = e.code
            return "https://quiet-river-1234.trycloudflare.com"

        def stop(self):
            SlowTunnel.stopped += 1

        def alive(self):
            return True
    m.tunnel_factory = SlowTunnel()
    out = m.open("counter", user, phone.code(), origin=phone.tg)
    assert inner == {"code": "busy"} and out["url"] and m.link.state == "waiting"
    assert len(phone.listen.calls) == 1 and SlowTunnel.stopped == 0


def test_failure_after_tunnel_start_stops_everything(counter, owner):
    phone = make_phone(counter, owner)
    m = phone.manager
    original = m._audit

    def boom(event, *a, **k):
        if event == "remote_open":
            raise RuntimeError("boom")
        return original(event, *a, **k)
    m._audit = boom
    with pytest.raises(RuntimeError):
        phone.open()
    assert phone.tunnel.stopped == 1 and phone.listen.listeners[0].closed == 1
    assert m.link is None and phone.apps.running() == []


# 3 ── 「本機的請求」要對方真的是 loopback；有對外網址或在容器裡就不算
def test_is_local_needs_loopback_peer_and_no_public_url(make_bot, owner):
    bot = make_bot()
    ui = bot.app.extras["synox_web"]
    c = Client(ui)
    c.login(owner)
    h = {"Host": c.host, "Cookie": c.cookie, "X-SYNOX-CSRF": c.csrf}
    status, _h, body = ui.handle("POST", "/api/stepup/begin", h, b"{}", peer="203.0.113.7")
    assert status == 403 and b"otpauth" not in body                # nginx 改寫了 Host、沒帶代理標頭
    status, _h, body = ui.handle("POST", "/api/stepup/begin", h, b"{}", peer="127.0.0.1")
    assert status == 200
    bot2 = make_bot(raw={"web": {"public_url": "https://synox.example.com"}})
    ui2 = bot2.app.extras["synox_web"]
    c2 = Client(ui2)
    c2.login(owner)
    assert c2.post("/api/stepup/begin")[0] == 403


# 4 ── 不是 ASCII 的數字：閘門回固定的、有計次的失敗；/unlock 不會出錯
def test_nonascii_digits_are_a_counted_fixed_failure(counter, owner):
    phone = make_phone(counter, owner)
    out = phone.open()
    good_fail = phone.client().knock(out["url"], "000000" if phone.code(False) != "000000" else "111111")
    r = phone.client().knock(out["url"], "١٢٣٤٥٦")
    assert r[0] == 403 and r[2] == good_fail[2]
    assert phone.manager.enter_attempts.count(phone.manager.link.id) == 2
    g = guard.of(phone.bot.app)
    assert g.stepup.verify(owner, "١٢٣٤٥٦", origin=phone.tg).code == "bad"
    from synox.guard.http import Reject, parse
    host = phone.manager.link.host
    with pytest.raises(Reject):
        parse("POST", "/x", [("Host", host), ("Origin", f"https://{host}"), ("Content-Type", "application/json"),
                             ("Content-Length", "٢")], b"{}", host=host)


# 5 ── 保管箱讀不出來 ≠ 沒設定：擋住、說清楚、不能重新設定
def test_unreadable_store_fails_closed(make_bot, owner):
    bot = make_bot()
    g = guard.of(bot.app)
    clock = Clock()
    enroll(g, owner, clock)
    node = bot.app.registry.ensure_group("probe", "probe").leaf(
        "rm", lambda api, chat_id, user, args: api.send_message(chat_id, "done"), "x", effect="danger")
    g.stepup.set_protect(owner, True, origin=Origin("web", owner, surface="web:x"))

    def broken(uid):
        raise ValueError("decrypt failed")
    g.stepup.store.load = broken
    assert g.stepup.enrolled(owner) and g.stepup.protects_danger(owner)
    user = bot.app.users.get_or_create(owner)
    with using(Origin("telegram", owner, surface="telegram")):
        d = policy.decide(bot.app, user, node, via=TYPED, chat_id=owner)
    assert not d.allowed and "讀不出來" in d.message
    with pytest.raises(ValueError):
        g.stepup.begin(owner)


# 6 ── 擁有者進門之後，外人敲 /_synox/enter 或亂送請求都踢不掉他
def test_outsider_cannot_close_an_entered_session(counter, owner):
    phone = make_phone(counter, owner)
    out = phone.open()
    me = phone.client()
    me.enter(out["url"], phone.code())
    stranger = phone.client(ua="curl")
    stranger.host = phone.manager.link.host
    for _ in range(10):
        stranger.raw("POST", "/_synox/enter", body=json.dumps({"k": "x" * 20, "code": "000000"}).encode())
    phone.manager.rate_out.allow = lambda key: True
    for _ in range(400):
        stranger.raw("GET", "/%2e%2e/x")
    assert phone.manager.link.state == "entered" and me.get("/api/me")[0] == 200


# 7 ── 敏感動作預設就擋：pack-secrets、重新載入、上傳、runtime 的 PUT、配對
@pytest.mark.parametrize("method,path", [("POST", "/api/pack-secrets/money"), ("POST", "/api/packs/reload"),
                                         ("POST", "/api/packs/upload"), ("PUT", "/api/runtime/heartbeat"),
                                         ("POST", "/api/settings/channels/telegram/pair")])
def test_sensitive_routes_are_deny_by_default(make_bot, owner, method, path):
    bot = make_bot()
    ui = bot.app.extras["synox_web"]
    c = Client(ui)
    c.login(owner)
    g = guard.of(bot.app)
    enroll(g, owner, Clock(), protect=True)
    status, _h, body = c.raw(method, path, b"{}")
    assert status == 403 and json.loads(body)["code"] == "stepup"


# 8 ── kit.number 不收 nan／inf；positive_int 不收「²」
def test_kit_number_rejects_nonfinite_and_nonascii():
    from synox.packs import kit
    for bad in ("nan", "inf", "-inf", "1e999", "١٢"):
        assert kit.number(bad), bad
    assert kit.positive_int("²") and kit.hhmm("²²:00")
    assert kit.number("1,200.5") is None and kit.positive_int("3") is None


# 9 ── 連線太多：真的送出 429（固定的回應），不是什麼都沒寫
def test_too_many_connections_gets_a_real_429():
    from synox.guard import http as guard_http

    class Sock:
        def __init__(self):
            self._in, self.out = io.BytesIO(b"GET / HTTP/1.1\r\nHost: a\r\n\r\n"), b""

        def makefile(self, mode, *a, **k):
            return self._in if "r" in mode else io.BytesIO()

        def sendall(self, b):
            self.out += bytes(b)

        def settimeout(self, t):
            pass

    class Server:
        class ui:
            @staticmethod
            def handle_raw(*a):
                return 200, [], b"ok"
    taken = []
    while guard_http.GuardedHandler._slots.acquire(blocking=False):
        taken.append(1)
    try:
        sock = Sock()
        guard_http.GuardedHandler(sock, ("203.0.113.9", 1), Server())
        assert sock.out.startswith(b"HTTP/1.1 429") and b"slow_down" in sock.out
    finally:
        for _ in taken:
            guard_http.GuardedHandler._slots.release()
