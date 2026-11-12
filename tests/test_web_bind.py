# -*- coding: utf-8 -*-
"""網頁綁哪個位址（web/server.py 的 bind_host）：預設只綁 127.0.0.1；只有 SYNOX 的容器裡（SYNOX_IN_CONTAINER=1＋看得到容器的證據）
才收 SYNOX_WEB_BIND=0.0.0.0；其他值一律拒、網頁不開。docs/docker.md「為什麼容器裡綁 0.0.0.0 是安全的」。

不開任何埠：WebUI.start 的測試把 server._Server 換成只記位址的假類別。"""
import functools

import pytest

from synox.web import server
from synox.web.server import HOST, BindError, bind_host

IN_BOX = {"SYNOX_IN_CONTAINER": "1", "SYNOX_WEB_BIND": "0.0.0.0"}


def box(path):
    return path == "/.dockerenv"


def nothing(path):
    return False


# ── 預設不變 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("environ", [{}, {"SYNOX_WEB_BIND": ""}, {"SYNOX_WEB_BIND": "  "},
                                     {"SYNOX_WEB_BIND": "127.0.0.1"}, {"SYNOX_IN_CONTAINER": "1"},
                                     {"SYNOX_IN_CONTAINER": "1", "SYNOX_WEB_BIND": "127.0.0.1"}])
def test_default_is_loopback(environ):
    assert bind_host(environ, exists=box, platform="posix") == HOST == "127.0.0.1"
    assert bind_host(environ, exists=nothing, platform="nt") == HOST       # Windows、沒有容器證據也一樣


def test_default_reads_real_environment_without_the_variables(monkeypatch):
    monkeypatch.delenv("SYNOX_WEB_BIND", raising=False)
    monkeypatch.delenv("SYNOX_IN_CONTAINER", raising=False)
    assert bind_host() == "127.0.0.1"


# ── 開關生效 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("marker", server.CONTAINER_MARKERS)
def test_container_switch_binds_all_interfaces_inside_the_container(marker):
    assert bind_host(IN_BOX, exists=lambda p: p == marker, platform="posix") == "0.0.0.0"
    assert bind_host({**IN_BOX, "SYNOX_WEB_BIND": " 0.0.0.0 "}, exists=lambda p: p == marker,
                     platform="posix") == "0.0.0.0"


# ── 非法值被拒 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["192.168.1.10", "10.0.0.5", "::", "0", "localhost", "*", "0.0.0.0:8830",
                                   "0.0.0.0,127.0.0.1", "example.invalid"])
def test_other_addresses_are_refused_even_in_a_container(value):
    with pytest.raises(BindError, match="SYNOX_WEB_BIND"):
        bind_host({**IN_BOX, "SYNOX_WEB_BIND": value}, exists=box, platform="posix")


@pytest.mark.parametrize("flag", [None, "", "0", "true", "yes", "1 1"])
def test_all_interfaces_needs_the_container_flag(flag):
    environ = {"SYNOX_WEB_BIND": "0.0.0.0"}
    if flag is not None:
        environ["SYNOX_IN_CONTAINER"] = flag
    with pytest.raises(BindError, match="SYNOX_IN_CONTAINER"):
        bind_host(environ, exists=box, platform="posix")


def test_flag_without_container_evidence_is_refused():
    """一般電腦照抄容器的環境變數：沒有 /.dockerenv 之類的證據 → 拒。"""
    with pytest.raises(BindError, match="不是容器"):
        bind_host(IN_BOX, exists=nothing, platform="posix")


def test_windows_never_binds_all_interfaces():
    with pytest.raises(BindError):
        bind_host(IN_BOX, exists=lambda p: True, platform="nt")


# ── WebUI.start 用 bind_host（假的 server，不開埠） ───────────────────

class FakeServer:
    made = []

    def __init__(self, address, handler):
        self.server_address = address
        FakeServer.made.append(address)

    def serve_forever(self):
        pass

    def shutdown(self):
        pass

    def server_close(self):
        pass


@pytest.fixture
def fake_server(monkeypatch):
    FakeServer.made = []
    monkeypatch.setattr(server, "_Server", FakeServer)
    return FakeServer


def ui_of(bot):
    return bot.app.extras["synox_web"]


def test_start_binds_loopback_by_default(make_bot, fake_server, monkeypatch):
    monkeypatch.delenv("SYNOX_WEB_BIND", raising=False)
    monkeypatch.delenv("SYNOX_IN_CONTAINER", raising=False)
    ui = ui_of(make_bot(raw={"web": {"port": 8830}}))
    assert ui.start() is True
    assert fake_server.made == [("127.0.0.1", 8830)]
    assert ui.login_link(1).startswith("http://127.0.0.1:8830/login?t=")     # 連結永遠給宿主用的 127.0.0.1
    ui.stop()


def test_start_in_container_binds_all_interfaces(make_bot, fake_server, monkeypatch):
    monkeypatch.setenv("SYNOX_WEB_BIND", "0.0.0.0")
    monkeypatch.setenv("SYNOX_IN_CONTAINER", "1")
    ui = ui_of(make_bot(raw={"web": {"port": 8830}}))
    ui.bind_host = functools.partial(bind_host, exists=box, platform="posix")      # 環境變數照真的讀
    assert ui.start() is True
    assert fake_server.made == [("0.0.0.0", 8830)]
    assert ui.login_link(1).startswith("http://127.0.0.1:8830/login?t=")
    ui.stop()


def test_start_refuses_bad_bind_and_does_not_open_anything(make_bot, fake_server, monkeypatch):
    monkeypatch.setenv("SYNOX_WEB_BIND", "192.168.1.10")
    monkeypatch.setenv("SYNOX_IN_CONTAINER", "1")
    ui = ui_of(make_bot(raw={"web": {"port": 8830}}))
    assert ui.start() is False
    assert fake_server.made == [] and not ui.running
    assert "SYNOX_WEB_BIND" in ui.error and "192.168.1.10" in ui.error
