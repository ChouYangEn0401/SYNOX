# -*- coding: utf-8 -*-
"""S2：安裝報告「🧱 執行環境」、用容器／不用記進 packs.lock、--runtime、packs runtime、升級紅字、
伺服器版第三方 pack 的可見性、doctor 的引擎偵測（只用 which）。**不執行任何容器引擎**。"""
import argparse
import io
import json
import os
import zipfile

import pytest

from conftest import OWNER_ID

from synox import sandbox
from synox.packs import admin, lock, upgrade
from synox.packs.manifest import read

from test_container import BASE, IMAGE, TOOL, _write, cli_raw

IMAGE2 = "ghcr.io/example/weather@sha256:" + "c" * 64


@pytest.fixture(autouse=True)
def _reset():
    yield
    sandbox.set_factory(None)
    sandbox.set_engine_which(None)
    sandbox.set_container_factory(None)


def _which(*found):
    return lambda name: f"/usr/bin/{name}" if name in found else None


def _zip(folder) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for base, _dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(base, name)
                z.write(path, os.path.relpath(path, folder).replace(os.sep, "/"))
    return buf.getvalue()


def _src(tmp_path, tag, container=None, version="0.1.0", **extra):
    raw = cli_raw("weather", container, **extra)
    raw["version"] = version
    return _write(str(tmp_path / "src" / tag), raw, {"tool.py": TOOL})


def _stage(tmp_path, tag, container=None, **kw):
    return admin.stage(_zip(_src(tmp_path, tag, container, **kw)), str(tmp_path / "data"))


# ── 安裝報告與 packs.lock ──────────────────────────────────────────────

def test_report_offers_container_and_lock_records_it(tmp_path):
    sandbox.set_engine_which(_which("podman"))
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, summary = _stage(tmp_path, "a", {"image": IMAGE, "resources": {"mem_mb": 256}})
    rt = summary["runtime"]
    assert rt["offered"] and rt["default"] == "container" and rt["engines"] == {"podman": True, "docker": False}
    assert [c["value"] for c in rt["choices"]] == ["container", "host"]
    text = admin.format_summary(summary)
    assert "🧱 執行環境" in text and IMAGE in text and "podman ✅" in text and "--runtime container" in text
    admin.install_staged(token, data, packs, approved_by=OWNER_ID, via="test")
    rec = lock.entry(data, "weather")
    assert rec["runtime"]["mode"] == "container" and rec["runtime"]["image"] == IMAGE
    assert rec["runtime"]["digest"] == "sha256:" + "a" * 64 and rec["runtime"]["network"] is False
    assert rec["runtime"]["chosen_by"] == OWNER_ID and rec["trust"] == "third-party"   # 跟 trust 並列
    assert lock.runtime_mode(data, "weather") == "container"


def test_install_host_choice_and_refusals(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _ = _stage(tmp_path, "a", {"image": IMAGE})
    with pytest.raises(admin.PackAdminError, match="runtime"):
        admin.install_staged(token, data, packs, runtime="vm")
    admin.install_staged(token, data, packs, runtime="host")
    assert lock.entry(data, "weather")["runtime"]["mode"] == "host"
    token2, summary = admin.stage(_zip(_src(tmp_path, "plain")), str(tmp_path / "data2"))
    assert not summary["runtime"]["offered"] and "沒有提供容器" in admin.format_summary(summary)
    with pytest.raises(admin.PackAdminError, match="沒有提供容器"):
        admin.install_staged(token2, str(tmp_path / "data2"), str(tmp_path / "packs2"), runtime="container")
    admin.install_staged(token2, str(tmp_path / "data2"), str(tmp_path / "packs2"))
    assert "runtime" not in lock.entry(str(tmp_path / "data2"), "weather")   # 沒提供容器：鎖不多寫


def test_dockerfile_pack_records_build_inputs(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    folder = _src(tmp_path, "d", {"dockerfile": "Dockerfile", "base": BASE})
    with open(os.path.join(folder, "Dockerfile"), "w", encoding="utf-8") as f:
        f.write(f"FROM {BASE}\nCOPY . /pack\n")
    token, _ = admin.stage(_zip(folder), data)
    admin.install_staged(token, data, packs)
    rt = lock.entry(data, "weather")["runtime"]
    assert rt["mode"] == "container" and rt["image"].startswith("localhost/synox-weather:")
    assert len(rt["dockerfile_sha256"]) == 64 and rt["base"] == BASE and rt["digest"] == ""


def test_cli_install_runtime_flag_and_packs_runtime(tmp_path, capsys):
    from synox import __main__ as cli
    blob = tmp_path / "weather.synoxpack"
    blob.write_bytes(_zip(_src(tmp_path, "c", {"image": IMAGE})))
    packs = tmp_path / "packs"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data")}), encoding="utf-8")
    args = argparse.Namespace(config=str(cfg), file=str(blob), yes=True, packs_dir=str(packs), trust_publisher=None,
                              runtime="host")
    assert cli.cmd_install(args) == 0
    assert "不用容器" in capsys.readouterr().out
    data = str(tmp_path / "data")
    assert lock.runtime_mode(data, "weather") == "host"
    before = dict(lock.entry(data, "weather")["files"])
    ns =argparse.Namespace(config=str(cfg), packs_cmd="runtime", name="weather", mode="container", dirs=[str(packs)],
                            packs_dir="")
    assert cli.cmd_packs(ns) == 0
    assert lock.runtime_mode(data, "weather") == "container"
    assert lock.entry(data, "weather")["files"] == before                  # 只改 runtime，雜湊不動
    assert "用容器" in capsys.readouterr().out


def test_packs_runtime_refuses_without_container_or_lock(tmp_path, capsys):
    from synox import __main__ as cli
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data")}), encoding="utf-8")
    plain = os.path.dirname(_src(tmp_path / "one", "p"))
    ns = argparse.Namespace(config=str(cfg), packs_cmd="runtime", name="weather", mode="container", dirs=[plain],
                            packs_dir="")
    assert cli.cmd_packs(ns) == 2 and "沒有提供容器" in capsys.readouterr().out
    boxed = os.path.dirname(_src(tmp_path / "two", "b", {"image": IMAGE}))
    ns.dirs = [boxed]
    assert cli.cmd_packs(ns) == 2 and "packs lock --approve" in capsys.readouterr().out


# ── 升級 ───────────────────────────────────────────────────────────────

def _install_then_stage_upgrade(tmp_path, old, new):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _ = _stage(tmp_path, "v1", old)
    admin.install_staged(token, data, packs)
    token2, _ = _stage(tmp_path, "v2", new, version="0.2.0",
                       caps=["network"] if (new or {}).get("network") else None)
    return data, packs, token2


def test_upgrade_flags_container_changes(tmp_path):
    data, packs, token = _install_then_stage_upgrade(tmp_path, {"image": IMAGE},
                                                     {"image": IMAGE2, "network": True})
    upg = upgrade.staged_upgrade(token, data, packs)
    alerts = [c["text"] for c in upg["changes"] if c["alert"]]
    assert any("network false → true" in t for t in alerts) and any("映像換了" in t for t in alerts)
    assert any("runtime" in t for t in alerts)                             # 執行方式改了（runtime.container）
    assert upg["installed_runtime"] == "container" and upg["runtime"] == "container"
    assert "🧱 執行環境：裝著的是 用容器" in upgrade.format_upgrade(upg)
    upgrade.upgrade_staged(token, data, packs)
    assert lock.entry(data, "weather")["runtime"]["digest"] == "sha256:" + "c" * 64


def test_upgrade_dropping_container_is_red_and_goes_host(tmp_path):
    data, packs, token = _install_then_stage_upgrade(tmp_path, {"image": IMAGE}, None)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert any("容器 → 直接在這台跑" in c["text"] and c["alert"] for c in upg["changes"])
    with pytest.raises(admin.PackAdminError, match="沒有提供容器"):
        upgrade.upgrade_staged(token, data, packs, runtime="container")
    upgrade.upgrade_staged(token, data, packs)
    assert lock.runtime_mode(data, "weather") == "host"


def test_upgrade_keeps_host_choice(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _ = _stage(tmp_path, "v1", {"image": IMAGE})
    admin.install_staged(token, data, packs, runtime="host")
    token2, _ = _stage(tmp_path, "v2", {"image": IMAGE}, version="0.2.0")
    upgrade.upgrade_staged(token2, data, packs)
    assert lock.runtime_mode(data, "weather") == "host"                    # 沒選＝沿用


def test_approve_installed_keeps_runtime(tmp_path):
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _ = _stage(tmp_path, "v1", {"image": IMAGE})
    admin.install_staged(token, data, packs)
    m, _r, problems = admin.approve_installed(os.path.join(packs, "weather"), data)
    assert problems == [] and lock.runtime_mode(data, "weather") == "container"
    admin.approve_installed(os.path.join(packs, "weather"), data, runtime="host")
    assert lock.runtime_mode(data, "weather") == "host"


# ── 伺服器版可見性、doctor ─────────────────────────────────────────────

def test_server_member_visibility_follows_runtime_and_engine(make_bot, tmp_path):
    from isdtelekit.users.roles import BasicRoles
    from conftest import OTHER_ID
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _ = _stage(tmp_path, "a", {"image": IMAGE}, access="member")
    admin.install_staged(token, data, packs, approved_by=OWNER_ID, via="web")
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())

    sandbox.set_engine_which(_which("podman"))
    bot = make_bot(raw={"mode": "server"}, pack_dirs=(packs,))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    reg = bot.app.registry
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "weather")
    assert reg.visible(bot.app.users.get_or_create(OTHER_ID), reg.node("weather")) and item.detail == ""
    sandbox.set_engine_which(_which())                                    # 引擎不見了：重新載入時只給擁有者
    reason = sandbox.restricted_reason(bot.app.config, read(os.path.join(packs, "weather")))
    assert "只對擁有者開放" in reason and "找不到 podman 或 docker" in reason


def test_doctor_shows_engines_without_running_them(tmp_path):
    from synox import doctor
    called = []
    sandbox.set_engine_which(lambda name: called.append(name) or ("/usr/bin/podman" if name == "podman" else None))
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "mode": "server",
                                "llm": {"kind": "none"}}), encoding="utf-8")
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "• 容器引擎（engine=auto）：podman ✅（/usr/bin/podman）、docker —" in text and "沒有執行引擎" in text
    assert set(called) <= {"podman", "docker"}


def test_runtime_note_lines(tmp_path):
    from synox.config import SynoxConfig
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _ = _stage(tmp_path, "a", {"image": IMAGE})
    admin.install_staged(token, data, packs)
    cfg = SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": data}, require_token=False, root=str(tmp_path))
    m = read(os.path.join(packs, "weather"))
    sandbox.set_engine_which(_which("docker"))
    assert sandbox.runtime_note(cfg, m) == f"🧱 容器（docker）：{IMAGE}"
    sandbox.set_engine_which(_which())
    assert "找不到" in sandbox.runtime_note(cfg, m)
