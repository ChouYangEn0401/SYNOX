# -*- coding: utf-8 -*-
"""P5 × P6 的接縫：升級之後照樣建／重建環境（runtime.python／node = auto），退回時提示重建。
絕對不真的 pip／npm、不連網：命令一律交給 test_envs 的假 JobRunner，node／npm 用假的 which。"""
import argparse
import json
import os

import pytest

from conftest import OWNER_ID

from synox.packs import admin, envs, upgrade
from synox.packs import lock as pack_lock

from test_envs import PUB, FakeJobs, _config, _node_raw, _raw, _write_pack, _zip, which_all


@pytest.fixture(autouse=True)
def _fake_which():
    envs.set_factory(lambda d: envs.VenvBuilder(d, python="PYTHON-EXE", which=which_all))
    yield
    envs.set_factory(None)


def _no_env(**over):
    raw = _raw(**over)
    raw.pop("runtime")
    return raw


def _install(tmp_path, raw, node=False, build=True):
    """裝第一版（install_staged），build=True 再用假 JobRunner 把環境建好。回 (data, packs)。"""
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, _s = admin.stage(_zip(_write_pack(str(tmp_path / "src" / "v1"), raw, node=node)), data)
    name = admin.install_staged(token, data, packs, approved_by=OWNER_ID, via="test", trust_publisher=PUB)
    if build and envs.needs_env(admin.read(os.path.join(packs, name))):
        results = []
        assert admin.build_env(name, data, packs, FakeJobs(tmp_path), results.append) and results[0].ok
    return data, packs


def _stage(tmp_path, tag, raw, data, node=False, lock_text=None):
    src = _write_pack(str(tmp_path / "src" / tag), raw, node=node)
    if lock_text is not None:
        with open(os.path.join(src, "package-lock.json"), "w", encoding="utf-8") as f:
            f.write(lock_text)
    return admin.stage(_zip(src), data)


# ── 升級報告：要不要建／重建 ──────────────────────────────────────────

def test_report_old_without_env_new_auto_needs_build(tmp_path):
    data, packs = _install(tmp_path, _no_env())
    token, _s = _stage(tmp_path, "v2", _raw(version="0.2.0"), data)
    upg = upgrade.staged_upgrade(token, data, packs)
    env = upg["env"]
    assert env["needed"] and not env["rebuild"] and not env["keep"] and "舊版不用" in env["reason"]
    assert env["lines"] == ["Python venv、裝 2 個套件：requests 2.32.3、idna 3.7"]     # 跟安裝報告同一份清單
    text = upgrade.format_upgrade(upg)
    assert "🧱 要建環境（按確認升級之後才建）" in text and "requests 2.32.3" in text and "data/envs/tool/" in text
    assert not os.path.exists(os.path.join(data, "envs"))                       # 看報告不建


def test_report_same_pins_keeps_env(tmp_path):
    data, packs = _install(tmp_path, _raw())
    token, _s = _stage(tmp_path, "v2", _raw(version="0.2.0"), data)
    env = upgrade.staged_upgrade(token, data, packs)["env"]
    assert not env["needed"] and env["keep"] and env["text"] == ""
    assert "沿用 data/envs/tool/（不重建）" in upgrade.format_upgrade(upgrade.staged_upgrade(token, data, packs))


def test_report_changed_pins_needs_rebuild(tmp_path):
    data, packs = _install(tmp_path, _raw())
    token, _s = _stage(tmp_path, "v2", _raw(version="0.2.0", requires={"pip": ["requests==2.32.4"]}), data)
    env = upgrade.staged_upgrade(token, data, packs)["env"]
    assert env["needed"] and env["rebuild"] and "requires.pip" in env["reason"]
    assert "🧱 要重建環境" in upgrade.format_upgrade(upgrade.staged_upgrade(token, data, packs))


def test_report_changed_package_lock_needs_rebuild(tmp_path):
    data, packs = _install(tmp_path, _node_raw(), node=True)
    token, _s = _stage(tmp_path, "v2", _node_raw(version="0.2.0"), data, node=True,
                       lock_text=json.dumps({"name": "tool", "lockfileVersion": 3,
                                             "packages": {"": {"name": "tool"}, "node_modules/y": {"version": "2.0.0"}}}))
    env = upgrade.staged_upgrade(token, data, packs)["env"]
    assert env["needed"] and env["rebuild"] and env["node"] and env["node_packages"] == 1


def test_report_same_pins_but_env_never_built_needs_build(tmp_path):
    data, packs = _install(tmp_path, _raw(), build=False)
    token, _s = _stage(tmp_path, "v2", _raw(version="0.2.0"), data)
    env = upgrade.staged_upgrade(token, data, packs)["env"]
    assert env["needed"] and not env["rebuild"] and "沒建好" in env["reason"]


def test_report_new_without_env_says_nothing(tmp_path):
    data, packs = _install(tmp_path, _raw())
    token, _s = _stage(tmp_path, "v2", _no_env(version="0.2.0"), data)
    upg = upgrade.staged_upgrade(token, data, packs)
    assert not upg["env"]["needed"] and not upg["env"]["keep"] and "🧱" not in upgrade.format_upgrade(upg)


# ── CLI install --yes：升級完等環境建好；失敗不退回升級 ──────────────────

def _cli_install(tmp_path, tag, raw, jobs):
    from synox import __main__ as cli
    blob = tmp_path / f"{tag}.synoxpack"
    blob.write_bytes(_zip(_write_pack(str(tmp_path / "src" / tag), raw)))
    packs = tmp_path / "packs"
    args = argparse.Namespace(config=_config(tmp_path, packs), file=str(blob), yes=True, packs_dir=str(packs),
                              trust_publisher=PUB)
    return cli.cmd_install(args, jobs=jobs, is_up=lambda port: False)


def test_cli_upgrade_yes_builds_env(tmp_path, capsys):
    assert _cli_install(tmp_path, "v1", _no_env(), FakeJobs(tmp_path)) == 0
    capsys.readouterr()
    jobs = FakeJobs(tmp_path)
    assert _cli_install(tmp_path, "v2", _raw(version="0.2.0"), jobs) == 0
    out = capsys.readouterr().out
    assert "升級好了" in out and "🧱 要建環境（按確認升級之後才建）" in out and "環境建好了" in out
    assert "🧱 要建環境（按確認之後才建）" not in out                           # 安裝摘要那段不重複印
    assert [c["argv"][1:3] for c in jobs.calls] == [["-m", "venv"], ["-m", "pip"]]
    data = str(tmp_path / "data")
    m = admin.read(str(tmp_path / "packs" / "tool"))
    assert envs.env_problem(m, data) is None


def test_cli_upgrade_env_failure_keeps_upgrade(tmp_path, capsys):
    assert _cli_install(tmp_path, "v1", _raw(), FakeJobs(tmp_path)) == 0
    capsys.readouterr()
    jobs = FakeJobs(tmp_path, [("succeeded", ""), ("failed", "getaddrinfo failed\n")])
    assert _cli_install(tmp_path, "v2", _raw(version="0.2.0", requires={"pip": ["requests==2.32.4"]}), jobs) == 0
    out = capsys.readouterr().out
    assert "🧱 要重建環境" in out and "升級好了，但環境沒建好：連不上網路" in out
    packs, data = tmp_path / "packs", str(tmp_path / "data")
    assert json.loads((packs / "tool" / "pack.json").read_text(encoding="utf-8"))["version"] == "0.2.0"   # 沒退回
    assert pack_lock.verify(data, "tool", str(packs / "tool"))[0] == pack_lock.LOCKED
    assert envs.env_problem(admin.read(str(packs / "tool")), data).startswith("環境沒建好：連不上網路")


def test_cli_upgrade_same_pins_runs_nothing(tmp_path, capsys):
    assert _cli_install(tmp_path, "v1", _raw(), FakeJobs(tmp_path)) == 0
    jobs = FakeJobs(tmp_path)
    assert _cli_install(tmp_path, "v2", _raw(version="0.2.0"), jobs) == 0
    assert not jobs.calls and "沿用" in capsys.readouterr().out


# ── rollback：舊版的環境對不上 → 只提示 ──────────────────────────────

def test_rollback_hints_rebuild_without_building(tmp_path, capsys):
    from synox import __main__ as cli
    assert _cli_install(tmp_path, "v1", _raw(), FakeJobs(tmp_path)) == 0
    assert _cli_install(tmp_path, "v2", _raw(version="0.2.0", requires={"pip": ["requests==2.32.4"]}),
                        FakeJobs(tmp_path)) == 0
    capsys.readouterr()
    packs, data = str(tmp_path / "packs"), str(tmp_path / "data")
    state_before = envs.read_state(data, "tool")
    args = argparse.Namespace(config=_config(tmp_path, tmp_path / "packs"), packs_cmd="rollback", name="tool",
                              packs_dir=packs, dirs=None)
    assert cli.cmd_packs(args) == 0
    out = capsys.readouterr().out
    assert "退回了" in out and "舊版的環境" in out and "python -m synox packs env rebuild tool" in out
    assert envs.read_state(data, "tool") == state_before                        # 沒有自動建


def test_rollback_env_none_when_matching_or_not_needed(tmp_path):
    data, packs = _install(tmp_path, _raw())
    token, _s = _stage(tmp_path, "v2", _raw(version="0.2.0"), data)            # 同一份套件：環境沿用
    upgrade.upgrade_staged(token, data, packs)                                  # 同一個 publisher、沒變多：沿用確認
    assert upgrade.rollback("tool", packs, data)["env"] is None
    data2, packs2 = _install(tmp_path / "b", _no_env())
    token, _s = _stage(tmp_path / "b", "v2", _raw(version="0.2.0"), data2)
    upgrade.upgrade_staged(token, data2, packs2, trust_publisher=PUB)            # T1 → T2：要確認
    assert upgrade.rollback("tool", packs2, data2)["env"] is None                # 舊版不用環境


# ── Web：確認升級 → 背景建、完成通知 ─────────────────────────────────

def test_web_upgrade_starts_env_build_and_notifies(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    built = []

    class Failing(envs.Builder):
        def plan(self, m):
            return envs.VenvBuilder(self.data_dir, python="PY", which=which_all).plan(m)

        def build(self, m, jobs, on_done):
            built.append(m.version)
            on_done(envs.BuildResult(m.name, False, "連不上網路（下載套件要網路）"))

    envs.set_factory(Failing)
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    bot = make_bot(pack_dirs=(str(user_packs),))
    c = Client(ui_of(bot))
    c.login(owner)

    def upload(tag, raw):
        status, _h, body = c.raw("POST", "/api/packs/upload", _zip(_write_pack(str(tmp_path / "src" / tag), raw)))
        assert status == 200, body
        return json.loads(body)

    s1 = upload("v1", _no_env())
    status, data = c.post("/api/packs/install", {"token": s1["token"]})
    assert status == 200 and data["env"] == "" and not built
    s2 = upload("v2", _raw(version="0.2.0"))
    assert s2["upgrade"]["env"]["needed"] and s2["upgrade"]["env"]["lines"]
    assert s2["upgrade"]["tier"]["needs_publisher"]                              # T1 → T2：要重新確認
    status, data = c.post("/api/packs/install", {"token": s2["token"], "upgrade": True, "trust_publisher": PUB})
    assert status == 200 and data["upgraded"] and data["env"] == "building" and built == ["0.2.0"], data
    assert data["to"] == "0.2.0" and data["status"] == "missing" and "環境沒建好" in data["detail"]
    assert any("升級好了，但環境沒建好" in t for t in bot.texts(owner))
