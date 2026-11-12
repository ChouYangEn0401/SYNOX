# -*- coding: utf-8 -*-
"""工具健康的存檔（src/synox/health/store.py）：data/health/tools.json.enc 經保管箱加密（檔案裡找不到原因的明文）、
重開還在、diag 不存；讀不開＝當作全部正常而且不蓋掉；doctor 用的唯讀版不產生金鑰。暫存資料夾、假時鐘。"""
import os

from synox.health import BROKEN, NEEDS_ACTION, HealthRegistry
from synox.health import failure as F
from synox.health import settings as hs
from synox.health.store import FOLDER, HealthStore, read_only
from synox.vault import Vault

TOOL = "demo.price"


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def fail(code="upstream_unavailable", reason="服務 503", **block):
    env = {"ok": False, "error": reason, "code": code}
    if block:
        env["failure"] = {"v": 1, **block}
    return F.normalize(env)


def reg(clock=None, store=None):
    return HealthRegistry(hs.defaults(), store, clock=clock or Clock())


def _vault(tmp_path, key=b"h"):
    return Vault(key * 32, str(tmp_path / "data"))


def test_state_survives_restart_and_is_encrypted(tmp_path):
    clock = Clock()
    r = reg(clock, HealthStore(_vault(tmp_path)))
    marker = "PLAINTEXT-REASON-MARK"
    for _ in range(3):
        r.record_failure(TOOL, fail(reason=f"{marker} 服務掛了", scope="tool", diag={"upstream": "DIAG-MARK"}), pack="demo")
    r.record_failure("demo.login", fail("auth_expired", "token 過期"), pack="demo", user=7)
    path = os.path.join(str(tmp_path / "data"), FOLDER, "tools.json.enc")
    with open(path, "rb") as f:
        blob = f.read()
    assert b"PLAINTEXT" not in blob and marker.encode() not in blob and b"demo.price" not in blob   # 密文
    again = reg(clock, HealthStore(_vault(tmp_path)))                 # 重開
    entry = again.hidden(TOOL)
    assert entry is not None and entry.state == BROKEN and entry.count == 3 and entry.reason.startswith(marker)
    assert entry.diag == {}                                           # diag 不存檔
    assert again.hidden("demo.login", 7).state == NEEDS_ACTION
    entries, problem = read_only(str(tmp_path / "data"))              # doctor 的唯讀版：沒有金鑰檔＝說一聲
    assert entries is None and "金鑰" in problem
    assert not os.path.exists(os.path.join(str(tmp_path / "data"), ".synox.key"))   # 也不會產生金鑰


def test_broken_store_fails_open_and_is_not_overwritten(tmp_path):
    folder = os.path.join(str(tmp_path / "data"), FOLDER)
    os.makedirs(folder)
    path = os.path.join(folder, "tools.json.enc")
    with open(path, "wb") as f:
        f.write(b"not a vault file\n")
    store = HealthStore(_vault(tmp_path))
    r = reg(None, store)
    assert store.broken and r.entries == {} and r.hidden(TOOL) is None   # 讀不開：全部當成正常
    for _ in range(3):
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
    with open(path, "rb") as f:
        assert f.read() == b"not a vault file\n"                       # 不蓋掉


def test_wrong_key_fails_open(tmp_path):
    r = reg(None, HealthStore(_vault(tmp_path)))
    for _ in range(3):
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
    other = HealthStore(_vault(tmp_path, b"z"))                         # 金鑰不對（換了電腦）
    assert reg(None, other).entries == {} and other.broken


def test_no_vault_means_memory_only(tmp_path):
    r = reg(None, None)
    for _ in range(3):
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
    assert r.hidden(TOOL) is not None and not os.path.exists(str(tmp_path / "data"))
