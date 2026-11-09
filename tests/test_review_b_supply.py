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


# ── #D 載入後檔案被換：每次叫 cli 前再對一次鎖 ─────────────────────────────

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _locked_folder(tmp_path):
    from test_t2_trust import _raw, _write
    folder = _write(str(tmp_path / "packs" / "bin"), _raw(publisher=None))
    data = str(tmp_path / "data")
    assert admin.approve_installed(folder, data)[2] == []
    return folder, data


def test_live_check_finds_changed_added_and_missing_files(tmp_path):
    from synox.packs import lock
    folder, data = _locked_folder(tmp_path)
    live = lock.live_check(lock.entry(data, "bin"), folder)
    assert live.changes() == [] and live.changes() == []
    path = os.path.join(folder, "tool.py")
    with open(path, "a", encoding="utf-8") as f:
        f.write("# changed\n")
    assert live.changes() == ["改了 tool.py"]
    os.remove(path)
    assert live.changes() == ["少了 tool.py"]
    with open(os.path.join(folder, "json.py"), "w", encoding="utf-8") as f:   # 會蓋過標準函式庫的同名模組
        f.write("x = 1\n")
    assert "多了 json.py" in live.changes()


def test_live_check_is_cheap_and_full_rehash_catches_reset_mtime(tmp_path, monkeypatch):
    from synox.packs import lock
    folder, data = _locked_folder(tmp_path)
    clock = Clock()
    live = lock.live_check(lock.entry(data, "bin"), folder, clock=clock)
    assert live.changes() == []
    hashed = []
    real = lock.sha256_file
    monkeypatch.setattr(lock, "sha256_file", lambda p: hashed.append(p) or real(p))
    assert live.changes() == [] and hashed == []                    # stat 沒變：一個雜湊都不算
    path = os.path.join(folder, "tool.py")
    st = os.stat(path)
    with open(path, "r+b") as f:                                     # 同樣大小、內容不同，再把修改時間改回去
        data_bytes = f.read()
        f.seek(0)
        f.write(data_bytes.replace(b"True", b"Fals"))
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    quick = live.changes()
    clock.t += lock.LiveCheck.FULL_EVERY                             # 每 10 分鐘全部重算一次
    assert "改了 tool.py" in live.changes()
    assert quick in ([], ["改了 tool.py"])                           # 快速檢查不保證抓得到（Windows 沒有 inode）


def test_cli_refuses_to_run_after_files_change(make_bot, owner, tmp_path, monkeypatch):
    from isdtelekit.jobs import cli as jobs_cli

    def boom(*a, **k):
        raise AssertionError("不准執行 pack 的程式")
    monkeypatch.setattr(jobs_cli.JsonCli, "call", boom)
    monkeypatch.setattr(jobs_cli.JsonCli, "start", boom)
    folder, _data = _locked_folder(tmp_path)
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "bin")
    assert item.status == "loaded" and item.lock == "locked"
    with open(os.path.join(folder, "tool.py"), "w", encoding="utf-8") as f:
        f.write("import os\nos.system('calc')\n")                    # 只寫字串，從來不執行
    node = bot.app.registry.node("bin.run")
    bot.say(owner, node.command)
    texts = bot.texts(owner)
    assert any("載入之後被改過" in t and "改了 tool.py" in t and "不執行" in t for t in texts), texts
    assert any("跟安裝時核准的不一樣" in t for t in texts)               # 也通知擁有者


def test_unlocked_pack_has_no_live_check(make_bot, tmp_path):
    from test_t2_trust import _raw, _write
    _write(str(tmp_path / "packs" / "bin"), _raw(publisher=None))
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "bin")
    assert pack.live is None and pack.tampered_since_load() == []
