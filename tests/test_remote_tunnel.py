"""通道程式（ADR 0026 §7）：**不執行任何真的程式**——subprocess.Popen 換成假的類別，記下收到的參數、吐出預先寫好的輸出行。"""

import io
import os
import subprocess

import pytest

from synox.web.remote import binary
from synox.web.remote.tunnel import CloudflaredTunnel, TunnelError

from remote_helpers import make_phone

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")


class FakeProc:
    def __init__(self, lines, exits_on_terminate=True):
        self.stdout = io.BytesIO("".join(lines).encode("utf-8"))
        self.calls = []
        self._alive = True
        self.exits_on_terminate = exits_on_terminate

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.calls.append("terminate")
        if self.exits_on_terminate:
            self._alive = False

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self._alive:
            raise subprocess.TimeoutExpired("cloudflared", timeout)
        return 0

    def kill(self):
        self.calls.append("kill")
        self._alive = False


class FakePopen:
    def __init__(self, lines, **kw):
        self.lines, self.kw, self.seen = lines, kw, None

    def __call__(self, argv, **kw):
        self.seen = (argv, kw)
        self.proc = FakeProc(self.lines, **self.kw)
        return self.proc


def test_argv_env_and_url(monkeypatch):
    monkeypatch.setenv("SYNOX_VAULT_KEY", "secret-vault")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    fake = FakePopen(["INF Starting tunnel\n", "INF |  https://quiet-river-1234.trycloudflare.com  |\n"])
    t = CloudflaredTunnel("C:/tools/cloudflared.exe", popen=fake)
    assert t.start("http://127.0.0.2:8861", timeout=2) == "https://quiet-river-1234.trycloudflare.com"
    argv, kw = fake.seen
    assert argv == ["C:/tools/cloudflared.exe", "tunnel", "--no-autoupdate", "--url", "http://127.0.0.2:8861"]
    assert kw["shell"] is False and kw["stdin"] == subprocess.DEVNULL
    assert not any(("VAULT" in k or "TOKEN" in k or "SYNOX" in k) for k in kw["env"])
    assert kw["env"]["USERPROFILE"] == kw["cwd"] and os.path.isdir(kw["cwd"]) and os.listdir(kw["cwd"]) == []
    assert t.alive()
    t.stop()
    assert fake.proc.calls[0] == "terminate" and not t.alive()


@pytest.mark.parametrize("line", ["https://evil.example/\n", "http://quiet-river-1234.trycloudflare.com\n",
                                  "https://quiet-river-1234.trycloudflare.com/path\n",
                                  "https://QUIET.trycloudflare.com\n"])
def test_bad_urls_are_not_taken_and_timeout_stops(line):
    fake = FakePopen([line])
    t = CloudflaredTunnel("cf", popen=fake)
    with pytest.raises(TunnelError) as e:
        t.start("http://127.0.0.2:8861", timeout=0.2)
    assert e.value.code == "timeout" and "terminate" in fake.proc.calls


def test_stop_two_steps():
    fake = FakePopen(["https://a-b.trycloudflare.com\n"], exits_on_terminate=False)
    t = CloudflaredTunnel("cf", popen=fake)
    t.start("http://127.0.0.2:8861", timeout=2)
    t.stop()
    assert fake.proc.calls[:3] == ["terminate", ("wait", 5), "kill"]


def test_no_binary_path():
    with pytest.raises(TunnelError):
        CloudflaredTunnel("").start("http://127.0.0.2:8861")


def test_binary_find_describe_approved(tmp_path, counter, owner):
    exe = tmp_path / "cloudflared.exe"
    exe.write_bytes(b"MZ fake binary")
    phone = make_phone(counter, owner)
    phone.bot.app.config.web["remote"]["tunnel"]["path"] = str(exe)
    assert binary.find(phone.bot.app.config) == str(exe)
    info = binary.describe(str(exe))
    assert info["size"] == 14 and len(info["sha256"]) == 64 and info["signer"] == ""
    record = {"path": info["path"], "sha256": info["sha256"], "size": info["size"]}
    assert binary.approved(str(exe), record)
    exe.write_bytes(b"MZ fake binarY")
    assert not binary.approved(str(exe), record)
    phone.bot.app.config.web["remote"]["tunnel"]["path"] = str(tmp_path / "missing.exe")
    assert binary.find(phone.bot.app.config) is None


def test_manager_checks_binary_before_running(tmp_path, counter, owner, monkeypatch):
    exe = tmp_path / "cloudflared.exe"
    exe.write_bytes(b"MZ v1")
    phone = make_phone(counter, owner)
    m = phone.manager
    m.binary_check = None
    phone.bot.app.config.web["remote"]["tunnel"]["path"] = str(exe)
    from synox.web.remote import RemoteError
    with pytest.raises(RemoteError) as e:
        phone.open()
    assert e.value.code == "no_binary"
    from synox.guard.origin import Origin
    web = Origin("web", owner, surface="web:x")
    with pytest.raises(RemoteError) as e:
        m.approve_binary(phone.bot.app.users.get_or_create(owner), web)
    assert e.value.code == "stepup"
    assert phone.manager.guard.stepup.unlock(owner, phone.code(), origin=web).ok
    out = m.approve_binary(phone.bot.app.users.get_or_create(owner), web)
    assert out["binary"]["sha256"] == binary.describe(str(exe))["sha256"]
    assert phone.open()["url"]
    m.close("owner")
    exe.write_bytes(b"MZ v2")
    started = len(phone.tunnel.started)
    with pytest.raises(RemoteError) as e:
        phone.open()
    assert e.value.code == "binary_changed" and len(phone.tunnel.started) == started
    with pytest.raises(RemoteError) as e:
        m.approve_binary(phone.bot.app.users.get_or_create(owner), Origin("ai", owner, surface="ai"))
    assert e.value.code == "not_human"


def test_doctor_remote_lines(tmp_path):
    from synox import doctor
    from synox.config import SynoxConfig

    def cfg(enabled):
        return SynoxConfig.from_dict({"owner_id": 1, "data_dir": str(tmp_path / "data"),
                                      "web": {"remote": {"enabled": enabled}}}, require_token=False, root=str(tmp_path))
    assert doctor.remote_lines(cfg(False), home=str(tmp_path))[0].startswith("  手機入口：關")
    assert "找不到通道程式" in doctor.remote_lines(cfg(True), home=str(tmp_path), find=lambda c: None)[0]
    exe = tmp_path / "cf.exe"
    exe.write_bytes(b"x")
    assert "還沒核准" in doctor.remote_lines(cfg(True), home=str(tmp_path), find=lambda c: str(exe))[0]
    (tmp_path / ".cloudflared").mkdir()
    (tmp_path / ".cloudflared" / "config.yml").write_text("x", encoding="utf-8")
    assert any("config.yml" in line for line in doctor.remote_lines(cfg(True), home=str(tmp_path), find=lambda c: str(exe)))
