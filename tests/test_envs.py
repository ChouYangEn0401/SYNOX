# -*- coding: utf-8 -*-
"""SDK P5：依賴與環境自動建置（runtime.python／node = "auto"，packs/envs.py）。
絕對不真的 pip／npm install、不連網：命令一律交給假的 JobRunner（只記 argv、照劇本回成功／失敗），
node／npm 用假的 which 決定有沒有。"""
import argparse
import io
import json
import os
import zipfile

import pytest

from conftest import OWNER_ID

from synox.packs import admin, envs, loader
from synox.packs.manifest import ManifestError, validate

PINS = ["requests==2.32.3", "idna==3.7"]


# ── 假東西 ────────────────────────────────────────────────────────────

class FakeJob:
    def __init__(self, state, returncode, log_path):
        self.state, self.returncode, self.log_path = state, returncode, log_path


class FakeJobs:
    """假的 JobRunner.start：記下 argv／cwd／timeout，照劇本（[(state, log 內容)…]）回結果，不開任何程式。
    建 venv 那一步「成功」時，放一個空的 python 檔假裝 venv 建好了。"""

    def __init__(self, tmp_path, script=()):
        self.calls = []
        self.script = list(script)
        self.tmp = tmp_path

    def start(self, name, argv, *, cwd=None, timeout=None, on_done=None, **kw):
        assert isinstance(argv, list)                         # argv 陣列，不是 shell 字串
        self.calls.append({"name": name, "argv": list(argv), "cwd": cwd, "timeout": timeout})
        state, text = self.script.pop(0) if self.script else ("succeeded", "")
        log = os.path.join(str(self.tmp), f"fake-{len(self.calls)}.log")
        with open(log, "w", encoding="utf-8") as f:
            f.write(text)
        if state == "succeeded" and "venv" in argv and "-m" in argv:
            py = envs.venv_python(os.path.dirname(argv[-1]))
            os.makedirs(os.path.dirname(py), exist_ok=True)
            open(py, "w").close()
        job = FakeJob(state, 0 if state == "succeeded" else 1, log)
        on_done(job)
        return job


def which_all(name):
    return {"node": r"C:\fake\node.exe", "npm": r"C:\fake\npm.cmd"}.get(name)


def which_none(name):
    return None


@pytest.fixture(autouse=True)
def _fake_which():
    """預設的 Builder 用假的 which（不依賴這台有沒有 node），測完換回來。"""
    envs.set_factory(lambda d: envs.VenvBuilder(d, python="PYTHON-EXE", which=which_all))
    yield
    envs.set_factory(None)


def _raw(**over):
    raw = {"name": "tool", "title": "工具", "summary": "測試用", "version": "0.1.0", "kind": "cli",
           "capabilities": ["subprocess"], "skill": "SKILL.md",
           "runtime": {"python": "auto", "python_posix": "auto"},
           "requires": {"pip": list(PINS)},
           "cli": {"argv": ["{python}", "{pack_dir}/tool.py"],
                   "commands": [{"name": "run", "effect": "READ", "argv": ["run"], "default": True}]}}
    raw.update(over)
    return raw


def _write_pack(folder, raw=None, node=False):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw or _raw(), f, ensure_ascii=False)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: tool\ndescription: 測試\n---\n")
    with open(os.path.join(folder, "tool.py"), "w", encoding="utf-8") as f:
        f.write("print('{}')\n")
    if node:
        with open(os.path.join(folder, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "tool", "version": "0.1.0", "dependencies": {"left-pad": "1.3.0"}}, f)
        with open(os.path.join(folder, "package-lock.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "tool", "lockfileVersion": 3,
                       "packages": {"": {"name": "tool"}, "node_modules/left-pad": {"version": "1.3.0"},
                                    "node_modules/x": {"version": "1.0.0"}}}, f)
    return folder


def _node_raw(**over):
    base = {"runtime": {"node": "auto"}, "requires": {},
            "cli": {"argv": ["{node}", "{pack_dir}/tool.js"],
                    "commands": [{"name": "run", "effect": "READ", "argv": ["run"]}]}}
    return _raw(**{**base, **over})


# ── pack.json 檢查 ───────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["requests", "requests>=2.0", "requests~=2.32", "requests==2.*",
                                 "requests[socks]==2.32.3", "requests==2.32.3; python_version>'3'",
                                 "git+https://example.invalid/x.git", "--index-url=http://x", "-r other.txt",
                                 "./local.whl", "requests === 2.32.3"])
def test_auto_python_requires_pinned_versions(tmp_path, bad):
    folder = _write_pack(str(tmp_path / "p"))
    with pytest.raises(ManifestError, match="釘死"):
        validate(_raw(requires={"pip": ["idna==3.7", bad]}), folder, strict=True)


def test_auto_python_pinned_ok_and_loose_pip_still_ok_without_auto(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    assert envs.pins(m) == [("requests", "2.32.3"), ("idna", "3.7")]
    raw = _raw(requires={"pip": ["requests"]})
    raw.pop("runtime")
    validate(raw, folder, strict=True)                         # 沒寫 auto：照舊不管 requires.pip 的寫法


def test_auto_node_needs_lock_file_and_only_for_cli(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    with pytest.raises(ManifestError, match="package-lock.json"):
        validate(_node_raw(), folder, strict=True)
    folder = _write_pack(str(tmp_path / "q"), node=True)
    assert validate(_node_raw(), folder, strict=True).runtime["node"] == "auto"
    with open(os.path.join(folder, "pack.py"), "w") as f:
        f.write("def install(app, pack):\n    pass\n")
    raw = _node_raw(kind="python")
    raw.pop("cli")
    with pytest.raises(ManifestError, match="只給 kind=cli"):
        validate(raw, folder, strict=True)


def test_node_is_a_reserved_field_name(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    raw = _raw(cli={"argv": ["{python}"], "commands": [{"name": "run", "effect": "READ", "argv": ["{node}"],
                                                        "fields": [{"name": "node"}]}]})
    with pytest.raises(ManifestError, match="保留"):
        validate(raw, folder, strict=True)


def test_auto_python_conflicts_with_cli_python(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    raw = _raw()
    raw["cli"]["python"] = "venv"
    with pytest.raises(ManifestError, match="cli.python"):
        validate(raw, folder, strict=True)


# ── plan：給人看的清單＋要跑的 argv ───────────────────────────────────

def test_plan_lists_packages_and_argv(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    data = str(tmp_path / "data")
    p = envs.builder(data).plan(m)
    assert p.needed and p.python and not p.node and not p.problems
    assert p.lines() == ["Python venv、裝 2 個套件：requests 2.32.3、idna 3.7"]
    assert p.text().startswith("要建環境：Python venv、裝 2 個套件：requests 2.32.3、idna 3.7")
    env = os.path.join(data, "envs", "tool")
    venv_step, pip_step = p.steps
    assert venv_step.argv == ["PYTHON-EXE", "-m", "venv", "--clear", os.path.join(env, "venv")]
    req = os.path.join(env, "requirements.txt")
    assert pip_step.argv == [envs.venv_python(env), "-m", "pip", "install", "--no-deps", "--only-binary=:all:",
                             "--disable-pip-version-check", "--no-input", "-r", req]
    assert not os.path.exists(req)                             # plan 只看、不寫、不跑
    assert p.to_dict()["packages"] == [{"name": "requests", "version": "2.32.3"}, {"name": "idna", "version": "3.7"}]


def test_plan_without_auto_needs_nothing(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    raw = _raw()
    raw.pop("runtime")
    p = envs.builder(str(tmp_path)).plan(validate(raw, folder))
    assert not p.needed and p.text() == "" and not p.steps


# ── build：經（假的）JobRunner 一步一步跑 ────────────────────────────

def test_build_python_success(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    data = str(tmp_path / "data")
    assert envs.env_problem(m, data).startswith("環境沒建好（還沒建過）")
    jobs = FakeJobs(tmp_path)
    result = envs.builder(data).build_wait(m, jobs)
    assert result.ok, result.detail
    assert [c["argv"][1:3] for c in jobs.calls] == [["-m", "venv"], ["-m", "pip"]]
    assert all(0 < c["timeout"] <= 600 for c in jobs.calls)       # 整個最多 10 分鐘
    with open(os.path.join(data, "envs", "tool", "requirements.txt"), encoding="utf-8") as f:
        assert f.read() == "requests==2.32.3\nidna==3.7\n"
    assert envs.read_state(data, "tool")["state"] == "ok"
    assert envs.env_problem(m, data) is None
    assert sorted(os.listdir(folder)) == ["SKILL.md", "pack.json", "tool.py"]   # pack 資料夾沒被寫


def test_build_offline_gives_plain_words(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    data = str(tmp_path / "data")
    log = ("WARNING: Retrying ... after connection broken by 'NewConnectionError('<pip._vendor.urllib3.connection."
           "HTTPSConnection>: Failed to establish a new connection: [Errno 11001] getaddrinfo failed')'\n")
    jobs = FakeJobs(tmp_path, [("succeeded", ""), ("failed", log)])
    result = envs.builder(data).build_wait(m, jobs)
    assert not result.ok and result.offline
    assert "連不上網路" in result.detail and "python -m synox packs env rebuild tool" in result.detail
    assert "NewConnectionError" not in result.detail               # 不把內部訊息原樣丟給人
    problem = envs.env_problem(m, data)
    assert problem.startswith("環境沒建好：連不上網路")


@pytest.mark.parametrize("state,log,expect", [
    ("timed_out", "", "超過 10 分鐘"),
    ("failed", "ERROR: No matching distribution found for requests==9.9.9\n", "找不到套件 requests==9.9.9"),
    ("failed", "something odd\n", "失敗（代碼 1）"),
])
def test_build_failure_messages(tmp_path, state, log, expect):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    jobs = FakeJobs(tmp_path, [("succeeded", ""), (state, log)])
    result = envs.builder(str(tmp_path / "data")).build_wait(m, jobs)
    assert not result.ok and not result.offline and expect in result.detail
    assert envs.read_state(str(tmp_path / "data"), "tool")["state"] == "failed"


def test_build_stops_after_first_failed_step(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    jobs = FakeJobs(tmp_path, [("failed", "Error: venv broke\n")])
    result = envs.builder(str(tmp_path / "data")).build_wait(m, jobs)
    assert not result.ok and len(jobs.calls) == 1


def test_build_node_uses_npm_ci_ignore_scripts_outside_pack(tmp_path):
    folder = _write_pack(str(tmp_path / "p"), node=True)
    m = validate(_node_raw(), folder, strict=True)
    data = str(tmp_path / "data")
    p = envs.builder(data).plan(m)
    assert p.node and p.node_packages == 2 and "不跑套件的安裝腳本" in p.lines()[0]
    jobs = FakeJobs(tmp_path)
    result = envs.builder(data).build_wait(m, jobs)
    assert result.ok, result.detail
    env = os.path.join(data, "envs", "tool")
    assert jobs.calls == [{"name": "env-tool", "argv": [r"C:\fake\npm.cmd", "ci", "--ignore-scripts", "--no-audit",
                                                        "--no-fund"], "cwd": env, "timeout": jobs.calls[0]["timeout"]}]
    assert os.path.isfile(os.path.join(env, "package-lock.json")) and os.path.isfile(os.path.join(env, "package.json"))
    assert not os.path.exists(os.path.join(folder, "node_modules"))    # 不裝進 pack 資料夾（雜湊才對得上）
    assert envs.env_problem(m, data, which=which_all) is None
    assert envs.node_of(m, data, which=which_all) == r"C:\fake\node.exe"
    assert envs.node_env(m, data) == {"NODE_PATH": os.path.join(env, "node_modules")}


def test_node_missing_on_this_computer(tmp_path):
    envs.set_factory(lambda d: envs.VenvBuilder(d, python="PY", which=which_none))
    folder = _write_pack(str(tmp_path / "p"), node=True)
    m = validate(_node_raw(), folder, strict=True)
    data = str(tmp_path / "data")
    p = envs.builder(data).plan(m)
    assert any("沒有 Node.js" in x for x in p.problems) and "沒有 Node.js" in p.text()
    jobs = FakeJobs(tmp_path)
    result = envs.builder(data).build_wait(m, jobs)
    assert not result.ok and not jobs.calls                        # 沒 node 就不跑任何命令
    assert "沒有 Node.js" in envs.env_problem(m, data, which=which_none)


def test_env_stale_after_pip_list_changes(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    data = str(tmp_path / "data")
    m = validate(_raw(), folder, strict=True)
    assert envs.builder(data).build_wait(m, FakeJobs(tmp_path)).ok
    m2 = validate(_raw(requires={"pip": ["requests==2.32.4"]}), folder, strict=True)
    assert "對不上" in envs.env_problem(m2, data)


def test_builder_is_replaceable(tmp_path):
    calls = []

    class Other(envs.Builder):
        def plan(self, m):
            return envs.EnvPlan(m.name, python=True, packages=[("x", "1.0")])

        def build(self, m, jobs, on_done):
            calls.append(m.name)
            on_done(envs.BuildResult(m.name, True, "ok"))

    envs.set_factory(Other)
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    assert admin.env_plan(m).lines() == ["Python venv、裝 1 個套件：x 1.0"]
    assert envs.builder(str(tmp_path)).build_wait(m, None).ok and calls == ["tool"]


# ── loader 代換 {python}／{node}、沒建好＝missing ──────────────────────

def test_loader_substitutes_auto_python_and_node(tmp_path):
    folder = _write_pack(str(tmp_path / "p"))
    m = validate(_raw(), folder, strict=True)
    data = str(tmp_path / "data")
    assert loader.cli_python(m, data) == envs.venv_python(os.path.join(data, "envs", "tool"))
    folder = _write_pack(str(tmp_path / "q"), node=True)
    m = validate(_node_raw(env={"X": "1"}), folder, strict=True)
    ph = {"data_dir": data}
    assert loader.cli_env(m, ph) == {"NODE_PATH": os.path.join(data, "envs", "tool", "node_modules"), "X": "1"}
    m = validate(_node_raw(runtime={"node": "bin/node.exe"}, ), folder, strict=True)
    assert envs.node_of(m, data) == os.path.normpath(os.path.join(folder, "bin", "node.exe"))
    assert envs.node_env(m, data) == {}


def test_load_all_marks_unbuilt_env_missing_then_loads(make_bot, owner, tmp_path):
    packs = tmp_path / "packs"
    _write_pack(str(packs / "tool"))
    bot = make_bot(pack_dirs=(str(packs),))
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "tool")
    assert item.status == "missing" and "環境沒建好" in item.detail and "packs env rebuild tool" in item.detail
    m = validate(_raw(), str(packs / "tool"), strict=True)
    assert envs.builder(bot.app.config.data_dir).build_wait(m, FakeJobs(tmp_path)).ok
    report = admin.reload(bot.app, bot.app.config, bot.app.extras.get("vault"), (str(packs),))
    assert next(i for i in report.items if i.name == "tool").status == "loaded"


# ── 安裝流程：報告 → 確認 → 才建；失敗不卡安裝 ─────────────────────────

def _zip(folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in sorted(os.listdir(folder)):
            z.write(os.path.join(folder, name), name)
    return buf.getvalue()


def test_install_report_then_build_failure_keeps_pack(tmp_path):
    src = _write_pack(str(tmp_path / "src"))
    data, packs = str(tmp_path / "data"), str(tmp_path / "packs")
    token, summary = admin.stage(_zip(src), data)
    assert summary["env"]["needed"] and summary["env"]["lines"] == ["Python venv、裝 2 個套件：requests 2.32.3、idna 3.7"]
    text = admin.format_summary(summary)
    assert "🧱 要建環境（按確認之後才建）" in text and "requests 2.32.3" in text
    assert not os.path.exists(os.path.join(data, "envs"))              # 確認之前什麼都沒建
    name = admin.install_staged(token, data, packs, approved_by=OWNER_ID, via="console")
    jobs = FakeJobs(tmp_path, [("failed", "getaddrinfo failed\n")])
    results = []
    assert admin.build_env(name, data, packs, jobs, results.append) is True
    assert os.path.isfile(os.path.join(packs, "tool", "pack.json"))   # pack 照樣裝好
    assert not results[0].ok and results[0].offline
    from synox.packs import lock as pack_lock
    assert pack_lock.verify(data, "tool", os.path.join(packs, "tool"))[0] == pack_lock.LOCKED


def test_build_env_skips_packs_without_auto(tmp_path):
    raw = _raw()
    raw.pop("runtime")
    _write_pack(str(tmp_path / "packs" / "tool"), raw)
    jobs = FakeJobs(tmp_path)
    assert admin.build_env("tool", str(tmp_path / "data"), str(tmp_path / "packs"), jobs, lambda r: None) is False
    assert not jobs.calls


def _config(tmp_path, packs):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"),
                                "packs": {"dirs": [str(packs)]}}), encoding="utf-8")
    return str(path)


def test_cli_install_yes_builds_env_and_failure_still_installs(tmp_path, capsys):
    from synox import __main__ as cli
    src = _write_pack(str(tmp_path / "src"))
    blob = tmp_path / "tool.synoxpack"
    blob.write_bytes(_zip(src))
    packs = tmp_path / "packs"
    cfg = _config(tmp_path, packs)
    jobs = FakeJobs(tmp_path, [("succeeded", ""), ("failed", "ERROR: No matching distribution found for idna==3.7")])
    args = argparse.Namespace(config=cfg, file=str(blob), yes=True, packs_dir=str(packs))
    assert cli.cmd_install(args, jobs=jobs) == 0
    out = capsys.readouterr().out
    assert "要建環境" in out and "✅ 裝好了：tool" in out and "環境沒建好：找不到套件 idna==3.7" in out
    assert (packs / "tool" / "pack.json").is_file()


def test_cli_packs_env_rebuild(tmp_path, capsys):
    from synox import __main__ as cli
    packs = tmp_path / "packs"
    _write_pack(str(packs / "tool"))
    cfg = _config(tmp_path, packs)
    jobs = FakeJobs(tmp_path)
    args = argparse.Namespace(config=cfg, dirs=[str(packs)], packs_cmd="env", env_cmd="rebuild", name="tool")
    assert cli.cmd_packs(args, jobs=jobs) == 0
    out = capsys.readouterr().out
    assert "要建環境：Python venv" in out and "環境建好了" in out and len(jobs.calls) == 2
    assert envs.read_state(str(tmp_path / "data"), "tool")["state"] == "ok"
    args.name = "nope"
    assert cli.cmd_packs(args, jobs=jobs) == 2


def test_cli_parser_has_env_rebuild():
    from synox import __main__ as cli
    with pytest.raises(SystemExit):
        cli.main(["packs", "env"])                                     # 要寫 rebuild


def test_doctor_flags_unbuilt_env(tmp_path):
    from synox import doctor
    packs = tmp_path / "packs"
    _write_pack(str(packs / "tool"))
    lines = []
    doctor.run(offline=True, config_path=_config(tmp_path, packs), out=lines.append)
    hit = [x for x in lines if "tool" in x and "環境沒建好" in x]
    assert hit and "python -m synox packs env rebuild tool" in hit[0]


def test_web_install_starts_env_build_and_notifies(make_bot, owner, tmp_path):
    from test_web import Client, ui_of
    done = []

    class Failing(envs.Builder):
        def plan(self, m):
            return envs.VenvBuilder(self.data_dir, python="PY", which=which_all).plan(m)

        def build(self, m, jobs, on_done):
            done.append(m.name)
            on_done(envs.BuildResult(m.name, False, "連不上網路（下載套件要網路）"))

    envs.set_factory(Failing)
    user_packs = tmp_path / "userpacks"
    user_packs.mkdir()
    bot = make_bot(pack_dirs=(str(user_packs),))
    c = Client(ui_of(bot))
    c.login(owner)
    status, _h, body = c.raw("POST", "/api/packs/upload", _zip(_write_pack(str(tmp_path / "src"))))
    summary = json.loads(body)
    assert status == 200 and summary["env"]["needed"], summary
    status, data = c.post("/api/packs/install", {"token": summary["token"]})
    assert status == 200 and data["name"] == "tool" and data["env"] == "building" and done == ["tool"]
    assert data["status"] == "missing" and "環境沒建好" in data["detail"]
    assert any("環境沒建好" in t for t in bot.texts(owner))             # 通知了擁有者
