# -*- coding: utf-8 -*-
"""審查 B #C（pip 雜湊／來源）、#D（cli 執行前再對一次鎖）、#E（zip 裡的 Windows 保留名、NTFS 資料流）。
不真的 pip／npm、不開任何程式：JobRunner 是假的（只記 argv 與 env），cli 子程序用假的 JsonCli 擋下來。"""
import io
import json
import os
import zipfile

import pytest

from synox.packs import admin, envs, tier
from synox.packs.manifest import ManifestError, validate

from test_envs import FakeJob, _raw as _env_raw, _write_pack

H1 = "a" * 64
H2 = "B" * 64


class RecordingJobs:
    """假的 JobRunner.start：記下 argv 與 env，照樣回成功（建 venv 那一步放一個空的 python 檔）。不開任何程式。"""

    def __init__(self, tmp_path):
        self.calls = []
        self.tmp = tmp_path

    def start(self, name, argv, *, cwd=None, timeout=None, on_done=None, env=None, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env) if env is not None else None})
        if "venv" in argv and "-m" in argv:
            py = envs.venv_python(os.path.dirname(argv[-1]))
            os.makedirs(os.path.dirname(py), exist_ok=True)
            open(py, "w").close()
        log = os.path.join(str(self.tmp), f"fake-{len(self.calls)}.log")
        open(log, "w").close()
        job = FakeJob("succeeded", 0, log)
        on_done(job)
        return job


@pytest.fixture(autouse=True)
def _fake_builder():
    envs.set_factory(lambda d: envs.VenvBuilder(d, python="PYTHON-EXE", which=lambda n: None))
    yield
    envs.set_factory(None)


# ── #C requires.pip 的 --hash ─────────────────────────────────────────

def test_hash_syntax_accepted_and_mixed_refused(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_env_raw(requires={"pip": [f"requests==2.32.3 --hash=sha256:{H1}",
                                            f"idna==3.7 --hash=sha256:{H1} --hash=sha256:{H2}"]}), folder, strict=True)
    assert envs.pins(m) == [("requests", "2.32.3"), ("idna", "3.7")]
    assert envs.pin_hashes(m) == {"requests": [H1], "idna": [H1, H2.lower()]}
    with pytest.raises(ManifestError, match="--hash"):
        validate(_env_raw(requires={"pip": [f"requests==2.32.3 --hash=sha256:{H1}", "idna==3.7"]}), folder, strict=True)
    for bad in (f"requests==2.32.3 --hash=md5:{H1[:32]}", "requests==2.32.3 --index-url=https://evil.invalid",
                f"requests==2.32.3 --hash=sha256:{H1} --extra-index-url=https://evil.invalid"):
        with pytest.raises(ManifestError, match="釘死"):
            validate(_env_raw(requires={"pip": [bad]}), folder, strict=True)


def test_plan_with_hashes_requires_hashes_and_writes_them(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_env_raw(requires={"pip": [f"requests==2.32.3 --hash=sha256:{H1}"]}), folder, strict=True)
    data = str(tmp_path / "data")
    p = envs.builder(data).plan(m)
    pip_step = p.steps[1]
    assert "--require-hashes" in pip_step.argv and "--isolated" in pip_step.argv
    assert pip_step.argv[pip_step.argv.index("--index-url") + 1] == envs.PYPI_INDEX
    assert p.to_dict()["hashed"] == {"requests": True}
    pip_step.prepare()
    with open(os.path.join(data, "envs", "tool", "requirements.txt"), encoding="utf-8") as f:
        assert f.read() == f"requests==2.32.3 --hash=sha256:{H1}\n"


def test_build_subprocess_env_is_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("PIP_INDEX_URL", "https://evil.invalid/simple")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://evil.invalid/extra")
    monkeypatch.setenv("PIP_CONFIG_FILE", "C:/evil/pip.ini")
    monkeypatch.setenv("npm_config_registry", "https://evil.invalid/npm")
    monkeypatch.setenv("PYTHONPATH", "C:/evil")
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_env_raw(), folder, strict=True)
    jobs = RecordingJobs(tmp_path)
    result = envs.builder(str(tmp_path / "data")).build_wait(m, jobs)
    assert result.ok, result.detail
    assert len(jobs.calls) == 2
    for call in jobs.calls:
        env = call["env"]
        assert env is not None and env.get("PYTHONIOENCODING") == "utf-8"
        assert not [k for k in env if k.upper().startswith(("PIP_", "NPM_CONFIG", "PYTHONPATH"))], env
        if "PATH" in os.environ:
            assert env.get("PATH") == os.environ["PATH"]


def test_report_marks_hashes_and_warns_when_missing(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    loose = validate(_env_raw(), folder, strict=True)
    lines = tier.warning_lines(tier.assess(loose))
    assert tier.PIN_NOT_SOURCE in lines
    assert any("requests 2.32.3（沒有雜湊）" in x and "idna 3.7（沒有雜湊）" in x for x in lines)
    hashed = validate(_env_raw(requires={"pip": [f"requests==2.32.3 --hash=sha256:{H1}",
                                                 f"idna==3.7 --hash=sha256:{H2}"]}), folder, strict=True)
    lines = tier.warning_lines(tier.assess(hashed))
    assert tier.PIN_NOT_SOURCE not in lines and any("requests 2.32.3（有雜湊）" in x for x in lines)
    text = "\n".join(admin.format_tier(admin.tier_of(loose, None)))     # 終端機的安裝報告（紅字那一段）
    assert "版本釘選不等於來源可信" in text and "🔴" in text
