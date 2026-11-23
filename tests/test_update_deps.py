"""
啟動時把套件補齊（docs/adr/0047 §2，src/synox/update/deps.py）。全部用假的：have（套件 → 版本）、requires（Requires-Dist）、
run（pip）。不跑真的 pip、不連網、不 import 那些套件。

實際發生過的情況：程式已經是新版（pyproject 的 [llm]／[llop] 指到 ntu_easy_llm 0.6.0a2 的 wheel），.venv 裡的 ntu_easy_llm 還是 0.5。
"""

from __future__ import annotations

import json
import os
import subprocess
import types

import pytest

from synox.update import deps, prepare

pytestmark = pytest.mark.usefixtures("no_sockets")

URL = ("https://github.com/ChouYangEn0401/ntu_easy_llm/releases/download/ntu_easy_llm-0.6.0a2/"
       "ntu_easy_llm-0.6.0a2-py3-none-any.whl")
PYPROJECT = f"""
[project]
name = "synox"
version = "9.0.0"
requires-python = ">=3.11"
dependencies = ["requests>=2.28", "cryptography>=41"]

[project.optional-dependencies]
dev = ["pytest>=7"]
llm = ["ntu_easy_llm @ {URL}"]
llop = ["ntu_easy_llm[llop] @ {URL}"]
"""
LLOP_REQS = ['llmop @ https://example.invalid/llmop-1.0.0-py3-none-any.whl ; extra == "llop"', "requests>=2"]


def synox(tmp_path, text=PYPROJECT):
    root = tmp_path / "SYNOX"
    (root / "data").mkdir(parents=True)
    (root / "pyproject.toml").write_text(text, encoding="utf-8")
    return str(root), str(root / "data")


class Venv:
    """假的 .venv：裝了什麼、各自的 Requires-Dist；pip（run）照要求把版本改掉（或失敗）。"""

    def __init__(self, have=None, reqs=None, *, pip_out="", pip_rc=0, raise_=None, installs=None):
        self.have = dict(have or {})
        self.reqs = dict(reqs or {})
        self.calls = []
        self.pip_out, self.pip_rc, self.raise_ = pip_out, pip_rc, raise_
        self.installs = installs if installs is not None else {}

    def version(self, name):
        return self.have.get(deps.canonical(name))

    def requires(self, name):
        return self.reqs.get(deps.canonical(name), [])

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        if self.raise_:
            raise self.raise_
        if self.pip_rc == 0:
            for k, v in self.installs.items():
                self.have[deps.canonical(k)] = v
        return types.SimpleNamespace(returncode=self.pip_rc, stdout="", stderr=self.pip_out)


BASE = {"requests": "2.32.3", "cryptography": "43.0.0"}


def sync(root, data, venv, **kw):
    kw.setdefault("environ", {})
    kw.setdefault("prefix", os.path.join(root, ".venv"))                   # 就是這個 SYNOX 自己的 .venv
    return deps.sync(root, data, say=kw.pop("say", lambda *_: None), run=venv.run, have=venv.version,
                     requires=venv.requires, python="py", **kw)


# ── 讀要求 ────────────────────────────────────────────────────────────

def test_parse_requirements_and_wheel_versions():
    r = deps.parse_req(f"ntu_easy_llm[llop] @ {URL}", "llop")
    assert (r.name, r.extras, r.url, r.group, r.need()) == ("ntu_easy_llm", ("llop",), URL, "llop", "0.6.0a2")
    r = deps.parse_req('requests >= 2.28 ; python_version < "4"')
    assert (r.name, r.spec, r.url, r.marker) == ("requests", ">=2.28", "", 'python_version < "4"')
    assert deps.parse_req("") is None and deps.parse_req("[x]") is None and deps.parse_req("x @ ") is None
    assert deps.url_version(URL + "#sha256=abc") == "0.6.0a2" and deps.url_version("https://x/pkg.tar.gz") == ""


def test_project_reads_the_real_pyproject_and_skips_dev():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proj = deps.project(root)
    assert {r.name for r in proj["base"]} >= {"requests", "cryptography"}
    assert "dev" not in proj["extras"] and {"llm", "llop"} <= set(proj["extras"])
    assert all(deps.url_version(r.url) for g in ("llm", "llop") for r in proj["extras"][g])   # 都釘在 wheel 網址
    assert deps.project(os.path.join(root, "no-such-folder")) is None


# ── 選了哪幾組 ────────────────────────────────────────────────────────

def test_extras_are_inferred_from_the_venv_and_remembered(tmp_path):
    root, data = synox(tmp_path)
    proj = deps.project(root)
    old = Venv({**BASE, "ntu-easy-llm": "0.5.0"})                           # 0.5 沒有 llop 這一組
    assert deps.inferred_extras(proj, old.version, old.requires) == ["llm"]
    both = Venv({**BASE, "ntu-easy-llm": "0.6.0a2", "llmop": "1.0.0"}, {"ntu-easy-llm": LLOP_REQS})
    assert deps.inferred_extras(proj, both.version, both.requires) == ["llm", "llop"]
    none = Venv(BASE)
    assert deps.chosen_extras(proj, {"extras": ["llop", "gone"]}, none.version, none.requires) == ["llop"]
    res = sync(root, data, Venv({**BASE, "ntu-easy-llm": "0.6.0a2"}))
    assert res["ok"] and res["extras"] == ["llm"]
    saved = json.load(open(os.path.join(data, "deps.json"), encoding="utf-8"))
    assert saved["schema_version"] == 1 and saved["extras"] == ["llm"]


def test_set_extras_add_and_remove(tmp_path):
    root, data = synox(tmp_path)
    assert deps.set_extras(data, add=["llop"]) == ["llop"]
    assert deps.set_extras(data, remove=["llop"]) == []
    venv = Venv({**BASE, "ntu-easy-llm": "0.6.0a2", "llmop": "1.0.0"}, {"ntu-easy-llm": LLOP_REQS})
    assert sync(root, data, venv)["extras"] == ["llm"]                      # 拿掉的不會因為「看得出來有裝」又回來


# ── 比 ────────────────────────────────────────────────────────────────

def test_the_real_case_old_ntu_easy_llm_with_llm_and_llop(tmp_path):
    root, data = synox(tmp_path)
    proj = deps.project(root)
    venv = Venv({**BASE, "ntu-easy-llm": "0.5.0"})
    todo = deps.plan(proj, ["llm", "llop"], venv.version, venv.requires)
    assert [(i.name, i.have, i.need, i.why) for i in todo] == [("ntu_easy_llm", "0.5.0", "0.6.0a2", "old")]
    assert deps.pip_args(todo) == [f"ntu_easy_llm[llop] @ {URL}"]          # 兩組合成一行


def test_never_downgrade_missing_and_ranges(tmp_path):
    root, data = synox(tmp_path)
    proj = deps.project(root)
    newer = Venv({**BASE, "ntu-easy-llm": "0.7.0"})
    assert deps.plan(proj, ["llm"], newer.version, newer.requires) == []     # 自己裝了更新的：不動
    gone = Venv({"requests": "2.20.0"})
    todo = {i.name: i for i in deps.plan(proj, [], gone.version, gone.requires)}
    assert todo["requests"].why == "old" and todo["cryptography"].why == "missing"
    assert sorted(deps.pip_args(todo.values())) == ["cryptography>=41", "requests>=2.28"]
    llop = Venv({**BASE, "ntu-easy-llm": "0.6.0a2"}, {"ntu-easy-llm": LLOP_REQS})   # 版本對了，llop 的相依沒有
    todo = deps.plan(proj, ["llop"], llop.version, llop.requires)
    assert [(i.name, i.why) for i in todo] == [("ntu_easy_llm", "extra_missing")]


def test_marker_that_does_not_apply_is_skipped(tmp_path):
    root, data = synox(tmp_path, '[project]\nname = "synox"\ndependencies = ["tomli>=2 ; python_version < \\"3.0\\""]\n')
    venv = Venv({})
    assert deps.plan(deps.project(root), [], venv.version, venv.requires) == []


# ── 補 ────────────────────────────────────────────────────────────────

def test_sync_installs_what_this_version_needs(tmp_path):
    root, data = synox(tmp_path)
    venv = Venv({**BASE, "ntu-easy-llm": "0.5.0"}, installs={"ntu-easy-llm": "0.6.0a2"})
    said = []
    res = sync(root, data, venv, say=said.append)
    assert res["ok"] and res["fixed"] == [{"name": "ntu_easy_llm", "need": "0.6.0a2", "have": "0.5.0", "why": "old"}]
    cmd = venv.calls[0]
    assert cmd[:4] == ["py", "-m", "pip", "install"] and cmd[-1] == f"ntu_easy_llm @ {URL}"
    assert "--timeout" in cmd and "--no-input" in cmd
    assert said[0].startswith("🔧") and "ntu_easy_llm 0.5.0 → 0.6.0a2" in said[0] and said[-1].startswith("✅")
    assert sync(root, data, venv)["ok"] and len(venv.calls) == 1                # 下次啟動：都對了，不叫 pip


@pytest.mark.parametrize("out, words", [("NewConnectionError: Failed to establish", "連不到網路"),
                                        ("[WinError 5] Access is denied", "檔案被占用"),
                                        ("something else", "pip 安裝失敗")])
def test_failure_keeps_starting_and_says_what_and_how(tmp_path, out, words):
    root, data = synox(tmp_path)
    venv = Venv({**BASE, "ntu-easy-llm": "0.5.0"}, pip_out=out, pip_rc=1)
    said = []
    res = sync(root, data, venv, say=said.append)
    assert res["ok"] is False and len(res["problems"]) == 1
    line = res["problems"][0]["line"]
    assert line.startswith("ntu_easy_llm 沒有更新到 0.6.0a2（現在是 0.5.0）") and words in line
    assert "synox deps sync" in res["how"] and "再試一次" in res["how"]
    assert any(words in s for s in said)
    assert os.path.isfile(os.path.join(data, "logs", "deps-pip.log"))
    assert json.load(open(os.path.join(data, "deps.json"), encoding="utf-8"))["last"]["ok"] is False


def test_backoff_after_a_failure_but_retry_on_request(tmp_path):
    root, data = synox(tmp_path)
    venv = Venv({**BASE, "ntu-easy-llm": "0.5.0"}, pip_out="NewConnectionError", pip_rc=1)
    t = [1000.0]
    sync(root, data, venv, clock=lambda: t[0])
    t[0] += 3600                                                                # 一小時後再啟動：不再卡在 pip
    res = sync(root, data, venv, clock=lambda: t[0])
    assert len(venv.calls) == 1 and res["ok"] is False and "連不到網路" in res["problems"][0]["line"]
    assert any("小時內" in s for s in res["lines"])
    sync(root, data, venv, clock=lambda: t[0], force=True)                     # 網頁「再試一次」、synox deps sync
    assert len(venv.calls) == 2
    t[0] += deps.BACKOFF
    sync(root, data, venv, clock=lambda: t[0])
    assert len(venv.calls) == 3


@pytest.mark.parametrize("kw, mode", [({"prefix": "/somewhere/else"}, "manual"),
                                      ({"environ": {"SYNOX_DEPS_SYNC": "off"}}, "off"),
                                      ({"environ": {"SYNOX_IN_DOCKER": "1"}}, "docker")])
def test_only_looks_when_it_is_not_synox_own_venv(tmp_path, kw, mode):
    root, data = synox(tmp_path)
    venv = Venv({**BASE, "ntu-easy-llm": "0.5.0"})
    res = sync(root, data, venv, **kw)
    assert venv.calls == [] and res["mode"] == mode and res["ok"] is False
    assert res["problems"][0]["name"] == "ntu_easy_llm" and res["how"]


def test_pip_that_cannot_start_or_hangs(tmp_path):
    root, data = synox(tmp_path)
    res = sync(root, data, Venv({**BASE, "ntu-easy-llm": "0.5.0"}, raise_=OSError("no python")))
    assert res["ok"] is False and "叫不動 pip" in res["problems"][0]["line"]
    res = sync(root, data, Venv({**BASE, "ntu-easy-llm": "0.5.0"}, raise_=subprocess.TimeoutExpired("pip", 1)),
               force=True)
    assert res["ok"] is False and "下載太久" in res["problems"][0]["line"]


def test_nothing_ever_raises(tmp_path):
    root, data = synox(tmp_path)

    def boom(_name):
        raise RuntimeError("metadata exploded")
    res = deps.sync(root, data, say=lambda *_: None, run=Venv().run, have=boom, requires=lambda n: [], environ={})
    assert res["ok"] is False and res["mode"] == "error"
    assert deps.sync(str(tmp_path / "nothing"), data, say=lambda *_: None)["mode"] == "skipped"   # 沒有 pyproject


def test_state_written_by_a_newer_synox_is_left_alone(tmp_path):
    root, data = synox(tmp_path)
    path = os.path.join(data, "deps.json")
    open(path, "w", encoding="utf-8").write(json.dumps({"schema_version": 99, "extras": ["x"]}))
    assert deps.load_state(data) == {}
    sync(root, data, Venv({**BASE, "ntu-easy-llm": "0.6.0a2"}))
    assert json.load(open(path, encoding="utf-8"))["schema_version"] == 99


# ── 接在哪裡 ──────────────────────────────────────────────────────────

def test_synox_run_checks_packages_before_the_bot_and_never_stops_it():
    from synox import __main__ as cli
    seen = []
    config = types.SimpleNamespace(root="R", data_dir="D")
    cli._deps_at_start(config, sync=lambda root, data: seen.append((root, data)))
    assert seen == [("R", "D")]

    def boom(*_a):
        raise RuntimeError("x")
    cli._deps_at_start(config, sync=boom)                                      # 不丟例外：照常啟動
    src = open(cli.__file__, encoding="utf-8").read().split("def cmd_run", 1)[1].split("\ndef ", 1)[0]
    assert src.index("load_for_run") < src.index("_deps_at_start(config)") < src.index("build(config")


def test_cli_deps_status_and_sync(tmp_path, capsys):
    from synox import __main__ as cli
    args = types.SimpleNamespace(config=str(tmp_path / "config.json"), deps_action="status", add=None, remove=None)
    rc = cli.cmd_deps(args, status=lambda root, data: {"ok": False, "extras": ["llm"], "available": ["llm", "llop"],
                                                        "todo": [{"name": "ntu_easy_llm", "need": "0.6.0a2", "have": "0.5.0"}]})
    out = capsys.readouterr().out
    assert rc == 10 and "ntu_easy_llm：要 0.6.0a2，現在是 0.5.0" in out and "synox deps sync" in out
    seen = []
    args.deps_action, args.add = "sync", ["llop"]
    rc = cli.cmd_deps(args, sync=lambda root, data, force: seen.append(force) or {"ok": True, "fixed": [{}]})
    assert rc == 0 and seen == [True] and "重新啟動" in capsys.readouterr().out
    assert json.load(open(tmp_path / "data" / "deps.json", encoding="utf-8"))["extras"] == ["llop"]
    with pytest.raises(SystemExit) as e:
        cli.main(["deps", "--help"])
    assert e.value.code == 0


def test_fingerprint_sees_every_optional_group(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    assert prepare.deps_fingerprint(str(a)) == prepare.deps_fingerprint(str(b))
    (b / "pyproject.toml").write_text(PYPROJECT.replace('llop = ["ntu_easy_llm[llop]', 'llop = ["ntu_easy_llm[llop,x]'),
                                      encoding="utf-8")
    assert prepare.deps_fingerprint(str(a)) != prepare.deps_fingerprint(str(b))   # 以前只看 llm／dev 開頭的行
    (b / "pyproject.toml").write_text(PYPROJECT.replace('version = "9.0.0"', 'version = "9.0.1"'), encoding="utf-8")
    assert prepare.deps_fingerprint(str(a)) == prepare.deps_fingerprint(str(b))   # 只有版本號不一樣


def test_prepare_refuses_a_different_version_than_the_one_clicked(tmp_path):
    from test_update import served, synox_folder
    root = synox_folder(tmp_path)
    with pytest.raises(prepare.UpdateError, match="不是你按的 8.0.0"):
        prepare.prepare(root, installed="0.2.0", opener=served(), allow_unsigned=True, say=lambda *_: None,
                        expect="8.0.0")
    assert not os.path.exists(os.path.join(root, "data", "update"))
