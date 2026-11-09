# -*- coding: utf-8 -*-
"""PERM-7 沙盒介面：synox/sandbox.py。只驗證組出來的 argv、grants 與可見性；
不真的跑 bwrap／systemd-run／AppContainer，jobobject 用假的 kernel32（不呼叫 Windows）。"""
import json
import os
import sys

import pytest

from isdtelekit.host.config import ConfigError
from isdtelekit.users.roles import BasicRoles
from isdtelekit.users.models import User

from conftest import OTHER_ID, OWNER_ID

from synox import sandbox
from synox.config import SynoxConfig
from synox.packs import lock, loader
from synox.packs.manifest import read


@pytest.fixture(autouse=True)
def _reset_factory():
    yield
    sandbox.set_factory(None)


class Recording(sandbox.Sandbox):
    """假後端：記下每次 wrap 拿到什麼，argv 原樣交回（子程序照常跑）。"""

    def __init__(self, isolates=False, name="fake"):
        self.isolates = isolates
        self.name = name
        self.calls = []

    def wrap(self, argv, env, cwd, grants):
        self.calls.append({"argv": list(argv), "env": dict(env or {}), "cwd": cwd, "grants": grants})
        return list(argv), dict(env or {})


def _which(*found):
    return lambda name: f"/usr/bin/{name}" if name in found else None


def _cfg(tmp_path, **raw):
    return SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), **raw},
                                 require_token=False, root=str(tmp_path))


def _write(folder, raw, files=None):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {raw['name']}\ndescription: d\n---\n")
    for rel, text in (files or {}).items():
        with open(os.path.join(folder, rel), "w", encoding="utf-8") as f:
            f.write(text)
    return folder


ECHO_PY = "import json, sys\nprint(json.dumps({'message': 'argv=' + ' '.join(sys.argv[1:])}))\n"


def _cli_pack(base, name="echo", caps=None, access="member", env=None):
    raw = {"name": name, "title": name, "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "group": name, "access": access, "capabilities": caps or [],
           "cli": {"argv": ["{python}", "./echo.py"], "json_flag": None, "env": env or {},
                   "commands": [{"name": "show", "effect": "READ", "default": True, "argv": ["show", "{text}"],
                                 "fields": [{"name": "text"}]}]}}
    return _write(os.path.join(base, name), raw, {"echo.py": ECHO_PY})


# ── 設定 ──────────────────────────────────────────────────────────────

def test_settings_defaults_and_errors(tmp_path):
    cfg = _cfg(tmp_path)
    s = sandbox.settings_of(cfg)
    assert (s["backend"], s["required_for"], s["mem_mb"], s["max_procs"]) == ("auto", "third-party", 1024, 64)
    with pytest.raises(ConfigError, match="backend"):
        _cfg(tmp_path, policy={"sandbox": {"backend": "docker"}})
    with pytest.raises(ConfigError, match="required_for"):
        _cfg(tmp_path, policy={"sandbox": {"required_for": "everyone"}})
    with pytest.raises(ConfigError, match="mem_mb"):
        _cfg(tmp_path, policy={"sandbox": {"mem_mb": "lots"}})
    assert sandbox.settings_of(_cfg(tmp_path, policy={"sandbox": {"mem_mb": 256}}))["mem_mb"] == 256


def test_resolve_backends():
    auto = {"backend": "auto"}
    assert sandbox.resolve(auto, "personal", platform="linux", which=_which("bwrap")).name == "none"
    assert sandbox.resolve(auto, "server", platform="win32", which=_which("bwrap")).name == "none"
    assert sandbox.resolve(auto, "server", platform="linux", which=_which("bwrap", "systemd-run")).name == "bwrap"
    assert sandbox.resolve(auto, "server", platform="linux", which=_which("systemd-run")).name == "systemd"
    nothing = sandbox.resolve(auto, "server", platform="linux", which=_which())
    assert nothing.name == "none" and not nothing.isolates and "找不到" in nothing.problem
    missing = sandbox.resolve({"backend": "bwrap"}, "server", platform="linux", which=_which())
    assert missing.name == "none" and "bwrap" in missing.problem         # 明寫卻用不了：fail closed
    assert sandbox.resolve({"backend": "bwrap"}, "server", platform="win32", which=_which("bwrap")).name == "none"
    job = sandbox.resolve({"backend": "jobobject"}, "server", platform="win32")
    assert job.name == "jobobject" and not job.isolates                  # 只限資源，不算真隔離
    ac = sandbox.resolve({"backend": "appcontainer"}, "server", platform="win32")
    assert ac.name == "none" and "還沒做" in ac.problem


def test_appcontainer_is_interface_only():
    box = sandbox.AppContainerSandbox()
    assert not box.available()
    with pytest.raises(NotImplementedError, match="appcontainer"):
        box.wrap(["x"], {}, "/", sandbox.Grants())


# ── 後端組出來的 argv ─────────────────────────────────────────────────

GRANTS = sandbox.Grants(read=("/srv/synox/packs/echo", "/srv/synox/data/envs/echo"),
                        write=("/srv/synox/data/users/7/echo",), network=False, mem_mb=256, procs=16,
                        timeout=30, pass_env=("ECHO_API_KEY",), hide=("/srv/synox/data",))


def _pairs(argv, flag):
    return [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == flag]


def test_bwrap_argv():
    box = sandbox.BwrapSandbox(which=_which("bwrap", "prlimit"))
    argv, env = box.wrap(["/py", "echo.py"], {"A": "1"}, "/srv/synox/packs/echo", GRANTS)
    assert argv[:4] == ["/usr/bin/prlimit", f"--as={256 * 1024 * 1024}", "--nproc=16", "--"]
    assert argv[4] == "/usr/bin/bwrap"
    assert "--unshare-net" in argv and "--unshare-pid" in argv and "--die-with-parent" in argv
    assert ("/srv/synox/packs/echo", "/srv/synox/packs/echo") in _pairs(argv, "--ro-bind-try")
    assert _pairs(argv, "--bind") == [("/srv/synox/data/users/7/echo", "/srv/synox/data/users/7/echo")]
    assert not any("/srv/synox/data" == a for a in argv)                 # 整個 data 不在裡面
    assert argv[-3:] == ["--", "/py", "echo.py"] and env == {"A": "1"}   # 以原本的 argv 結尾
    assert argv[argv.index("--chdir") + 1] == "/srv/synox/packs/echo"
    net, _ = box.wrap(["/py"], {}, "/", sandbox.Grants(network=True))
    assert "--unshare-net" not in net and ("/etc/resolv.conf", "/etc/resolv.conf") in _pairs(net, "--ro-bind-try")
    bare, _ = sandbox.BwrapSandbox(which=_which("bwrap")).wrap(["/py"], {}, "/", GRANTS)
    assert bare[0] == "/usr/bin/bwrap"                                   # 沒有 prlimit＝不限（doctor 說明）
    assert "prlimit" in sandbox.BwrapSandbox(which=_which("bwrap")).describe()


def test_systemd_argv_keeps_secrets_out():
    box = sandbox.SystemdSandbox(which=_which("systemd-run"))
    argv, env = box.wrap(["/py", "echo.py"], {"ECHO_TOKEN": "s3cret"}, "/srv/synox/packs/echo", GRANTS)
    props = [argv[i + 1] for i, a in enumerate(argv) if a == "--property"]
    assert argv[0] == "/usr/bin/systemd-run" and "--pipe" in argv and "--wait" in argv and "--user" not in argv
    for p in ("MemoryMax=256M", "TasksMax=16", "RuntimeMaxSec=30", "PrivateNetwork=yes", "IPAddressDeny=any",
              "ProtectSystem=strict", "InaccessiblePaths=-/srv/synox/data",
              "BindPaths=/srv/synox/data/users/7/echo"):
        assert p in props
    assert "BindReadOnlyPaths=-/srv/synox/packs/echo -/srv/synox/data/envs/echo" in props
    assert "--setenv=ECHO_TOKEN" in argv and "--setenv=ECHO_API_KEY" in argv
    assert not any("s3cret" in a for a in argv)                          # 值不進 argv
    assert argv[-3:] == ["--", "/py", "echo.py"] and env == {"ECHO_TOKEN": "s3cret"}
    net, _ = box.wrap(["/py"], {}, "/", sandbox.Grants(network=True))
    assert "PrivateNetwork=yes" not in net
    user, _ = sandbox.SystemdSandbox(which=_which("systemd-run"), scope="user").wrap(["/py"], {}, "/", GRANTS)
    assert "--user" in user


def test_jobobject_argv_and_launcher_args():
    box = sandbox.JobObjectSandbox(python="C:\\py.exe", script="C:\\synox\\sandbox.py")
    argv, _ = box.wrap(["C:\\venv\\python.exe", "x.py"], {}, "C:\\", GRANTS)
    assert argv == ["C:\\py.exe", "-I", "C:\\synox\\sandbox.py", "jobobject", "--mem-mb", "256", "--procs", "16",
                    "--", "C:\\venv\\python.exe", "x.py"]
    assert sandbox.parse_launcher(argv[3:]) == (256, 16, ["C:\\venv\\python.exe", "x.py"])
    with pytest.raises(ValueError):
        sandbox.parse_launcher(["jobobject", "--mem-mb", "1"])


class FakeKernel32:
    """假的 kernel32：記錄呼叫，什麼都不真的做。"""

    def __init__(self, fail=""):
        self.fail = fail
        self.calls = []

    def CreateJobObjectW(self, attrs, name):
        self.calls.append("create")
        return 0 if self.fail == "create" else 1234

    def SetInformationJobObject(self, job, cls, ptr, size):
        self.calls.append(("set", job, cls, size))
        return self.fail != "set"

    def GetCurrentProcess(self):
        return -1

    def AssignProcessToJobObject(self, job, proc):
        self.calls.append(("assign", job, proc))
        return True


def test_job_limits_with_fake_ctypes():
    import ctypes
    k = FakeKernel32()
    job, info = sandbox.apply_job_limits(256, 16, kernel32=k)
    assert job == 1234 and info.JobMemoryLimit == 256 * 1024 * 1024
    basic = info.BasicLimitInformation
    assert basic.ActiveProcessLimit == 17                                # launcher 自己也算一個
    for flag in (sandbox.JOB_OBJECT_LIMIT_JOB_MEMORY, sandbox.JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
                 sandbox.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE):
        assert basic.LimitFlags & flag
    assert k.calls[1] == ("set", 1234, 9, ctypes.sizeof(info)) and k.calls[2] == ("assign", 1234, -1)


def test_launcher_refuses_to_run_without_limits(capsys):
    ran = []
    code = sandbox.main(["jobobject", "--mem-mb", "64", "--", "prog"], kernel32=FakeKernel32(fail="set"),
                        run=lambda argv: ran.append(argv) or 0)
    assert code == 126 and ran == []                                     # 設不起來就不跑
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["ok"] is False
    assert sandbox.main(["jobobject", "--", "prog", "a"], kernel32=FakeKernel32(),
                        run=lambda argv: ran.append(argv) or 3) == 3 and ran == [["prog", "a"]]


# ── 宣告 → grants ─────────────────────────────────────────────────────

def test_data_scope_inference(tmp_path):
    base = str(tmp_path / "p")
    user = read(_cli_pack(base, "u1", env={"HOME_DIR": "{user_data_dir}/u1"}))
    shared = read(_cli_pack(base, "s1", env={"HOME_DIR": "{data_dir}/x"}))
    none = read(_cli_pack(base, "n1"))
    assert [sandbox.data_scope(m) for m in (user, shared, none)] == ["user", "shared", "none"]
    none.raw["data"] = "user"                                            # PERM-2 的 data 欄位優先
    assert sandbox.data_scope(none) == "user"


def test_trust_from_lock(tmp_path):
    cfg = _cfg(tmp_path)
    m = read(_cli_pack(str(tmp_path / "p"), "t1"))
    assert sandbox.trust_of(cfg.data_dir, m) == "core"                   # 沒鎖（出廠／工程師放的）
    lock.approve(cfg.data_dir, m, None, OWNER_ID, via="cli", trust="core")
    assert sandbox.trust_of(cfg.data_dir, m) == "core"                   # packs lock --approve --trust core
    lock.approve(cfg.data_dir, m, None, OWNER_ID, via="cli")
    assert sandbox.trust_of(cfg.data_dir, m) == "third-party"            # PERM-2：沒選 trust ＝ third-party
    lock.approve(cfg.data_dir, m, None, OWNER_ID, via="web")
    assert sandbox.trust_of(cfg.data_dir, m) == "third-party"            # 從檔案裝進來的
    data = lock.load(cfg.data_dir)
    data["packs"]["t1"].pop("trust", None)
    with open(lock.lock_path(cfg.data_dir), "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert sandbox.trust_of(cfg.data_dir, m) == "third-party"            # 舊鎖沒有 trust 欄位：照 via 推斷
    data = lock.load(cfg.data_dir)
    data["packs"]["t1"]["trust"] = "core"
    with open(lock.lock_path(cfg.data_dir), "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert sandbox.trust_of(cfg.data_dir, m) == "core"                   # 擁有者選的 trust 優先


def test_grants_for_server_user(tmp_path):
    cfg = _cfg(tmp_path, mode="server", policy={"sandbox": {"mem_mb": 300, "max_procs": 8}})
    m = read(_cli_pack(str(tmp_path / "p"), "g1", caps=["network"], env={"H": "{user_data_dir}/g1"}))
    ph = loader.placeholders(m, cfg, User(77, "m", BasicRoles.MEMBER))
    g = sandbox.grants_for(m, cfg, ph, pass_env=("K",))
    assert g.write == (os.path.join(cfg.data_dir, "users", "77", "g1"),)
    assert os.path.normpath(m.folder) in g.read and os.path.join(cfg.data_dir, "envs", "g1") in g.read
    assert g.network is True and (g.mem_mb, g.procs, g.timeout, g.pass_env) == (300, 8, 120.0, ("K",))
    assert g.hide == (os.path.normpath(cfg.data_dir),)
    m2 = read(_cli_pack(str(tmp_path / "p"), "g2"))
    g2 = sandbox.grants_for(m2, cfg, loader.placeholders(m2, cfg, None))
    assert g2.write == () and g2.network is False                        # data=none、沒宣告 network → 斷網


# ── loader：make_cli 過沙盒、可見性 ──────────────────────────────────

def test_make_cli_goes_through_sandbox(make_bot, owner, tmp_path):
    base = str(tmp_path / "packs")
    _cli_pack(base, "echo", env={"H": "{user_data_dir}/echo"})
    box = Recording()
    sandbox.set_factory(lambda config: box)
    bot = make_bot(pack_dirs=(base,))
    bot.say(owner, "/echo text=hi")
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "echo")
    assert pack.cli_bridge.wait(30) and bot.app.tasks.wait(30)
    assert bot.last(owner) == "argv=show hi"
    call = box.calls[-1]
    assert call["argv"][1].endswith("echo.py") and call["env"]["SYNOX_PACK_NAME"] == "echo"
    assert call["grants"].write == (os.path.join(bot.app.config.data_dir, "echo"),)
    assert os.path.isdir(call["grants"].write[0])                         # 要掛的可寫資料夾先建好
    assert call["grants"].network is False


def _third_party_server(make_bot, tmp_path, box):
    base = str(tmp_path / "packs")
    folder = _cli_pack(base, "ext", access="member")
    lock.approve(str(tmp_path / "data"), read(folder), None, OWNER_ID, via="web")
    sandbox.set_factory(lambda config: box)
    bot = make_bot(raw={"mode": "server"}, pack_dirs=(base,))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    return bot


def _sees(bot, tg_id):
    reg = bot.app.registry
    return reg.visible(bot.app.users.get_or_create(tg_id), reg.node("ext"))


def test_third_party_cli_owner_only_without_isolation(make_bot, tmp_path):
    bot = _third_party_server(make_bot, tmp_path, sandbox.NoneSandbox())
    item = next(i for i in bot.app.extras["synox_pack_report"].items if i.name == "ext")
    assert item.status == "loaded" and "只對擁有者開放" in item.detail and "none" in item.detail
    assert _sees(bot, OWNER_ID) and not _sees(bot, OTHER_ID)


def test_third_party_cli_open_with_real_isolation(make_bot, tmp_path):
    bot = _third_party_server(make_bot, tmp_path, Recording(isolates=True, name="bwrap"))
    assert _sees(bot, OTHER_ID)


def test_jobobject_does_not_count_and_personal_unaffected(make_bot, tmp_path):
    bot = _third_party_server(make_bot, tmp_path, sandbox.JobObjectSandbox())
    assert not _sees(bot, OTHER_ID)
    cfg = _cfg(tmp_path)                                                  # 個人版：不受影響
    m = read(os.path.join(str(tmp_path / "packs"), "ext"))
    assert sandbox.restricted_reason(cfg, m, sandbox.NoneSandbox()) == ""
    server_none = _cfg(tmp_path, mode="server", policy={"sandbox": {"required_for": "none"}})
    assert sandbox.restricted_reason(server_none, m, sandbox.NoneSandbox()) == ""
    server_all = _cfg(tmp_path, mode="server", policy={"sandbox": {"required_for": "all"}})
    core = read(_cli_pack(str(tmp_path / "other"), "corecli"))
    assert sandbox.restricted_reason(server_all, core, sandbox.NoneSandbox())


def test_doctor_shows_backend(tmp_path, monkeypatch):
    from synox import doctor
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), "mode": "server",
                                "llm": {"kind": "none"}}), encoding="utf-8")
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    lines = []
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    text = "\n".join(lines)
    assert "• 沙盒：後端 none" in text and "真隔離：否" in text and "只對擁有者開放" in text
    sandbox.set_factory(lambda config: sandbox.BwrapSandbox(which=_which("bwrap", "prlimit")))
    lines.clear()
    doctor.run(offline=True, config_path=str(path), out=lines.append)
    assert "真隔離：是" in "\n".join(lines)
