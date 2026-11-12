# -*- coding: utf-8 -*-
"""doctor 的「工具健康」一段：每個不正常的工具一行（狀態、類別碼、原因、下次檢查）；讀不開／沒有金鑰說一聲；設定關掉照實說。
只讀（不產生金鑰、不寫檔）。暫存資料夾，不連網。"""
import json
import os

from conftest import OWNER_ID

from synox import doctor
from synox.health import HealthRegistry
from synox.health import failure as F
from synox.health import settings as hs
from synox.health.store import FOLDER, HealthStore
from synox.vault import Vault
from synox.vault.keyring import load_or_create


def _config(tmp_path, **extra):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(data), "vault": {"mode": "file"}, **extra}),
                   encoding="utf-8")
    return str(cfg), data


def _doctor(cfg):
    lines = []
    doctor.run(offline=True, config_path=cfg, out=lines.append)
    return lines


def test_doctor_lists_unhealthy_tools(tmp_path):
    cfg, data = _config(tmp_path)
    assert "• 工具健康：✅ 沒有被暫停或隔離的工具" in _doctor(cfg)             # 沒有紀錄
    vault = Vault(load_or_create(str(data), "file"), str(data))
    reg = HealthRegistry(hs.defaults(), HealthStore(vault))
    for _ in range(2):
        reg.record_failure("demo.price", F.from_text("服務 503", "upstream_unavailable"), pack="demo", untrusted=True)
    reg.record_failure("demo.login", F.normalize({"ok": False, "error": "token 過期", "code": "auth_expired"}),
                       pack="demo", user=7)
    lines = _doctor(cfg)
    assert "• 工具健康：2 個不正常（網頁工具頁看得到原因；擁有者可以按「重新檢查」「解除隔離」）" in lines
    row = next(ln for ln in lines if "demo.price" in ln)
    assert "暫停（冷卻中）" in row and "upstream_unavailable" in row and "服務 503" in row and "下次檢查" in row
    row = next(ln for ln in lines if "demo.login" in ln)
    assert "（只對 7）" in row and "要人處理" in row and "auth_expired" in row
    reg.release("demo.price")
    reg.release("demo.login@7")
    assert "• 工具健康：✅ 沒有被暫停或隔離的工具" in _doctor(cfg)


def test_doctor_says_when_the_store_is_unreadable_or_health_is_off(tmp_path):
    cfg, data = _config(tmp_path)
    load_or_create(str(data), "file")
    os.makedirs(os.path.join(str(data), FOLDER))
    with open(os.path.join(str(data), FOLDER, "tools.json.enc"), "wb") as f:
        f.write(b"garbage\n")
    lines = _doctor(cfg)
    assert any(ln.startswith("• 工具健康：⚠️ 健康紀錄的檔讀不開") for ln in lines)
    with open(os.path.join(str(data), FOLDER, "tools.json.enc"), "rb") as f:
        assert f.read() == b"garbage\n"                                       # doctor 不改檔
    cfg, _data = _config(tmp_path, health={"enabled": False})
    assert "• 工具健康：關（health.enabled=false；每個工具都當成正常）" in _doctor(cfg)
