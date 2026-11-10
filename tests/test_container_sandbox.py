# -*- coding: utf-8 -*-
"""S1：ContainerSandbox 只組 argv（podman／docker）、引擎選擇、容器裡的路徑、loader／mcp 走容器。
**絕不執行 podman／docker**：which 是假的（回一個不存在的路徑）、loader／mcp 的整合測試用記錄 argv 的假後端，
真正跑的是測試自己寫的 Python（docs/handoff/container-verification.md 是真機清單）。"""
import json
import os
import sys

import pytest

from isdtelekit.host.config import ConfigError
from isdtelekit.users.roles import BasicRoles

from conftest import OTHER_ID, OWNER_ID

from synox import sandbox
from synox.config import SynoxConfig
from synox.packs import lock
from synox.packs.manifest import read

DIGEST = "a" * 64
IMAGE = f"ghcr.io/example/weather@sha256:{DIGEST}"
SPEC = {"image": IMAGE, "network": False, "resources": {}, "user": "nonroot", "python": "python3", "node": "node",
        "mounts": {"pack": "/pack", "user_data": "/data/user", "shared_data": "/data/shared"}}
GRANTS = sandbox.Grants(read=("/srv/synox/packs/weather", "/srv/synox/data/envs/weather", "/usr"),
                        write=("/srv/synox/data/users/7/weather",), network=False, mem_mb=1024, procs=64,
                        timeout=30, pass_env=("WEATHER_API_KEY", "OTHER_TOKEN"), hide=("/srv/synox/data",))


@pytest.fixture(autouse=True)
def _reset():
    yield
    sandbox.set_factory(None)
    sandbox.set_engine_which(None)
    sandbox.set_container_factory(None)


def _which(*found):
    return lambda name: f"/usr/bin/{name}" if name in found else None


def _box(engine="podman", spec=None, **kw):
    kw.setdefault("platform", "linux")
    return sandbox.ContainerSandbox(engine, {**SPEC, **(spec or {})}, pack="weather",
                                    pack_dir="/srv/synox/packs/weather", scope=kw.pop("scope", "user"),
                                    which=_which("podman", "docker"), nonce=lambda: "ab12cd34", **kw)


def _wrap(box, grants=GRANTS, env=None, argv=("python3", "/pack/tool.py"), cwd="/srv/synox/packs/weather"):
    env = {"SYNOX_TG_ID": "7", "SYNOX_USER_DATA_DIR": "/data/user", "SECRET_VALUE_X": "s3cret"} if env is None else env
    return box.wrap(list(argv), env, cwd, grants)


def _after(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


# ── 每個旗標都有斷言 ──────────────────────────────────────────────────

def test_podman_argv_every_flag():
    argv, env = _wrap(_box())
    assert argv[:6] == ["/usr/bin/podman", "run", "--rm", "-i", "--pull=never", "--name"]
    assert _after(argv, "--name") == ["synox-weather-7-ab12cd34"]
    assert _after(argv, "--label") == ["synox.pack=weather"]
    assert _after(argv, "--network") == ["none"]                          # 沒宣告 network：斷網
    assert "--read-only" in argv
    assert _after(argv, "--tmpfs") == ["/tmp:rw,noexec,nosuid,nodev,size=64m"]
    assert _after(argv, "--cap-drop") == ["ALL"]
    assert _after(argv, "--security-opt") == ["no-new-privileges"]
    assert _after(argv, "--pids-limit") == ["64"]
    assert _after(argv, "--memory") == ["1024m"] and _after(argv, "--memory-swap") == ["1024m"]
    assert "--cpus" not in argv                                           # pack 沒寫 cpus＝不加
    assert "--userns=keep-id" in argv and "--user" not in argv            # rootless：SYNOX 帳號的 uid，不是 root
    assert _after(argv, "--mount") == [
        "type=bind,source=" + os.path.normpath("/srv/synox/packs/weather") + ",target=/pack,readonly",
        "type=bind,source=" + os.path.normpath("/srv/synox/data/users/7/weather") + ",target=/data/user/weather"]
    assert _after(argv, "--workdir") == ["/pack"]
    envs = _after(argv, "--env")
    assert envs[0] == "HOME=/tmp"
    assert set(envs[1:]) == {"SYNOX_TG_ID", "SYNOX_USER_DATA_DIR", "SECRET_VALUE_X", "WEATHER_API_KEY", "OTHER_TOKEN"}
    assert not any("s3cret" in a for a in argv)                           # 值不進 argv
    assert argv[-3:] == [IMAGE, "python3", "/pack/tool.py"]               # 映像＋原本的 argv 結尾
    assert env["SECRET_VALUE_X"] == "s3cret"                              # 值留在環境（引擎從這裡拿）


@pytest.mark.parametrize("engine", ["podman", "docker"])
def test_never_dangerous_flags(engine):
    argv, _ = _wrap(_box(engine, {"network": True}), sandbox.Grants(network=True, write=("/w",)))
    text = " ".join(argv)
    for bad in ("--privileged", "--network host", "--net=host", "docker.sock", "podman.sock", "--cap-add",
                "--device", "--pid", "--ipc host", "-v ", "--volume", "-p ", "--publish", "seccomp=unconfined"):
        assert bad not in text, bad
    assert "--network" not in argv                                        # 宣告 network：用引擎預設的網路（不是 host）


def test_docker_user_flags():
    linux, _ = _wrap(_box("docker", uid=1001, gid=1002))
    assert linux[0] == "/usr/bin/docker" and _after(linux, "--user") == ["1001:1002"]
    assert "--userns=keep-id" not in linux
    as_root, _ = _wrap(_box("docker", uid=0, gid=0))
    assert _after(as_root, "--user") == ["65534:65534"]                   # SYNOX 用 root 跑也不給容器 root
    win, _ = _wrap(_box("docker", platform="win32"))
    assert _after(win, "--user") == ["65534:65534"]
    explicit, _ = _wrap(_box("podman", {"user": "1000:1000"}))
    assert _after(explicit, "--user") == ["1000:1000"] and "--userns=keep-id" not in explicit


def test_limits_take_the_smaller_and_cpus():
    argv, _ = _wrap(_box(spec={"resources": {"mem_mb": 256, "pids": 500, "cpus": 0.5}}))
    assert _after(argv, "--memory") == ["256m"] and _after(argv, "--pids-limit") == ["64"]
    assert _after(argv, "--cpus") == ["0.5"]
    bigger, _ = _wrap(_box(spec={"resources": {"mem_mb": 4096}}))
    assert _after(bigger, "--memory") == ["1024m"]                        # pack 寫大的：照政策
    none, _ = _wrap(_box(), sandbox.Grants())
    assert "--memory" not in none and "--pids-limit" not in none


def test_shared_scope_custom_mounts_and_cwd():
    box = _box(spec={"mounts": {"pack": "/app", "user_data": "/u", "shared_data": "/s"}}, scope="shared")
    g = sandbox.Grants(write=("/srv/synox/data/packs/weather",))
    argv, _ = _wrap(box, g, cwd="/srv/synox/packs/weather/sub")
    assert _after(argv, "--mount")[1].endswith(",target=/s/packs/weather")
    assert _after(argv, "--workdir") == ["/app/sub"]
    outside, _ = _wrap(box, g, cwd="/somewhere/else")
    assert _after(outside, "--workdir") == ["/app"]                       # 不在掛進來的資料夾裡：pack 的路徑
    nothing, _ = _wrap(_box(scope="none"), sandbox.Grants())
    assert len(_after(nothing, "--mount")) == 1                           # data=none：只掛 pack（唯讀）


def test_only_pack_folder_and_write_dir_are_mounted():
    argv, _ = _wrap(_box())
    mounted = " ".join(_after(argv, "--mount"))
    assert "envs" not in mounted and "source=/usr" not in mounted and os.path.normpath("/srv/synox/data") + "," not in mounted


def test_env_passthrough_filters_secrets():
    argv, _ = _wrap(_box(spec={"env_passthrough": ["WEATHER_API_KEY"]}))
    envs = _after(argv, "--env")
    assert "WEATHER_API_KEY" in envs and "OTHER_TOKEN" not in envs


def test_mount_path_with_comma_refused():
    g = sandbox.Grants(write=("/srv/a,b",))
    with pytest.raises(ValueError, match="逗號"):
        _wrap(_box(), g)


def test_view_maps_placeholders():
    ph = {"python": "/venv/python", "node": "/usr/bin/node", "pack_dir": "/srv/p", "data_dir": "/srv/d",
          "user_data_dir": "/srv/d/users/7", "tg_id": "7"}
    view = _box(spec={"python": "/usr/local/bin/python3"}).view(ph)
    assert view == {"python": "/usr/local/bin/python3", "node": "node", "pack_dir": "/pack", "data_dir": "/data/shared",
                    "user_data_dir": "/data/user", "tg_id": "7"}
    assert sandbox.view_for(sandbox.NoneSandbox(), ph) is ph               # 其他後端原樣


def test_available_uses_which_only():
    assert _box().available()
    assert not sandbox.ContainerSandbox("podman", SPEC, which=_which()).available()
    with pytest.raises(ValueError):
        sandbox.ContainerSandbox("lxc", SPEC)
    assert "container" in sandbox.REAL_ISOLATION and _box().isolates and "podman" in _box().describe()


# ── 引擎選擇（resolve 的 auto 順序） ────────────────────────────────────

TARGET = {"spec": SPEC, "image": IMAGE, "pack": "weather", "pack_dir": "/srv/p", "scope": "user"}


def test_resolve_with_container_engine_order():
    auto = {"backend": "auto", "engine": "auto"}
    both = sandbox.resolve(auto, "server", platform="linux", which=_which("podman", "docker", "bwrap"), container=TARGET)
    assert both.name == "container" and both.engine == "podman"           # rootless podman 優先
    docker = sandbox.resolve(auto, "server", platform="linux", which=_which("docker", "bwrap"), container=TARGET)
    assert docker.engine == "docker"
    forced = sandbox.resolve({**auto, "engine": "docker"}, "server", platform="linux",
                             which=_which("podman", "docker"), container=TARGET)
    assert forced.engine == "docker"
    fallback = sandbox.resolve(auto, "server", platform="linux", which=_which("bwrap"), container=TARGET)
    assert fallback.name == "bwrap" and "找不到 podman 或 docker" in fallback.problem
    none = sandbox.resolve(auto, "server", platform="linux", which=_which(), container=TARGET)
    assert none.name == "none" and not none.isolates and "找不到" in none.problem
    win = sandbox.resolve(auto, "personal", platform="win32", which=_which("docker"), container=TARGET)
    assert win.name == "container" and win.engine == "docker"             # Windows 的 Docker Desktop、個人版也可以
    # 沒選容器：host 的順序不變（bwrap → systemd → none）
    assert sandbox.resolve(auto, "server", platform="linux", which=_which("podman", "bwrap")).name == "bwrap"


def test_engine_setting_validated(tmp_path):
    with pytest.raises(ConfigError, match="engine"):
        SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"),
                               "policy": {"sandbox": {"engine": "lxc"}}}, require_token=False, root=str(tmp_path))


# ── box_for：packs.lock 的 runtime.mode ─────────────────────────────────

TOOL = ("import json, os, sys\nprint(json.dumps({'message': json.dumps({'argv': sys.argv[1:], "
        "'pack_dir': os.environ.get('SYNOX_PACK_DIR'), 'h': os.environ.get('H')})}))\n")


def _pack(base, name="boxed", access="member", spec=None):
    folder = os.path.join(str(base), name)
    os.makedirs(folder, exist_ok=True)
    raw = {"name": name, "title": name, "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "group": name, "access": access, "capabilities": [], "publisher": "Example",
           "runtime": {"container": spec or {"image": IMAGE}},
           "cli": {"argv": ["{python}", "./tool.py"], "json_flag": None, "env": {"H": "{user_data_dir}/" + name},
                   "commands": [{"name": "show", "effect": "READ", "default": True, "argv": ["show", "{text}"],
                                 "fields": [{"name": "text"}]}]}}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\ndescription: d\n---\n")
    with open(os.path.join(folder, "tool.py"), "w", encoding="utf-8") as f:
        f.write(TOOL)
    return folder


def _choose(data_dir, folder, mode="container", trust=None):
    m = read(folder)
    lock.approve(str(data_dir), m, None, OWNER_ID, via="web", trust=trust)
    data = lock.load(str(data_dir))
    data["packs"][m.name]["runtime"] = {"mode": mode}
    with open(lock.lock_path(str(data_dir)), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return m


def _cfg(tmp_path, **raw):
    return SynoxConfig.from_dict({"owner_id": OWNER_ID, "data_dir": str(tmp_path / "data"), **raw},
                                 require_token=False, root=str(tmp_path))


def test_box_for_follows_lock_and_engine(tmp_path):
    cfg = _cfg(tmp_path, mode="server")
    m = _choose(tmp_path / "data", _pack(tmp_path / "packs"))
    sandbox.set_factory(lambda config: sandbox.NoneSandbox())
    sandbox.set_engine_which(_which("podman"))
    box = sandbox.box_for(cfg, m)
    assert box.name == "container" and box.engine == "podman" and box.image == IMAGE and box.pack == "boxed"
    assert sandbox.restricted_reason(cfg, m) == ""                       # 第三方＋選了容器＋有引擎＝給成員
    sandbox.set_engine_which(_which())
    assert sandbox.box_for(cfg, m).name == "none"                         # 找不到引擎：退回 host
    reason = sandbox.restricted_reason(cfg, m)
    assert "只對擁有者開放" in reason and "找不到 podman 或 docker" in reason
    _choose(tmp_path / "data", m.folder, mode="host")
    sandbox.set_engine_which(_which("podman"))
    assert sandbox.box_for(cfg, m).name == "none"                         # 選了「不用容器」
    assert "packs runtime boxed container" in sandbox.restricted_reason(cfg, m)
    assert "不用容器" in sandbox.runtime_note(cfg, m)


def test_python_t2_stays_owner_only_even_with_engine(tmp_path):
    from synox.packs import tier
    cfg = _cfg(tmp_path, mode="server")
    folder = os.path.join(str(tmp_path), "pyt2")
    os.makedirs(folder)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "pyt2", "title": "t", "summary": "s", "version": "0.1.0", "kind": "python",
                   "skill": "SKILL.md", "capabilities": ["exec"]}, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: pyt2\ndescription: d\n---\n")
    with open(os.path.join(folder, "pack.py"), "w", encoding="utf-8") as f:
        f.write("def install(app, pack):\n    pass\n")
    with open(os.path.join(folder, "helper.dll"), "wb") as f:
        f.write(b"MZ" + b"\0" * 62)
    m = read(folder)
    assert tier.is_t2(m)
    sandbox.set_engine_which(_which("podman"))
    assert "T2 python pack" in sandbox.restricted_reason(cfg, m)


class Recorder(sandbox.Sandbox):
    """假的容器後端：記下 argv／env，交回「用本機 Python 跑 pack 裡的 tool.py」（測試自己寫的程式，不叫引擎）。"""
    name, isolates = "container", True

    def __init__(self, folder, script):
        self.folder, self.script, self.calls = folder, script, []

    def view(self, ph):
        return {**ph, "pack_dir": "/pack", "user_data_dir": "/data/user", "data_dir": "/data/shared",
                "python": "python3"}

    def wrap(self, argv, env, cwd, grants):
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "grants": grants})
        return [sys.executable, os.path.join(self.folder, self.script)] + list(argv[2:]), dict(env)


def test_loader_runs_cli_through_container(make_bot, tmp_path):
    folder = _pack(tmp_path / "packs")
    _choose(tmp_path / "data", folder)
    rec = Recorder(folder, "tool.py")
    sandbox.set_engine_which(_which("podman"))
    sandbox.set_container_factory(lambda config, target, engine: rec)
    bot = make_bot(raw={"mode": "server"}, pack_dirs=(str(tmp_path / "packs"),))
    bot.make(OTHER_ID, BasicRoles.MEMBER)
    reg = bot.app.registry
    assert reg.visible(bot.app.users.get_or_create(OTHER_ID), reg.node("boxed"))   # 第三方＋容器＝成員看得到
    bot.say(OTHER_ID, "/boxed text=hi")
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "boxed")
    assert pack.cli_bridge.wait(30) and bot.app.tasks.wait(30)
    call = rec.calls[-1]
    assert call["argv"] == ["python3", "/pack/tool.py"]                   # 容器裡的路徑
    assert call["env"]["SYNOX_PACK_DIR"] == "/pack" and call["env"]["SYNOX_USER_DATA_DIR"] == "/data/user"
    assert call["env"]["H"] == "/data/user/boxed"
    data_dir = bot.app.config.data_dir
    assert call["grants"].write == (os.path.join(data_dir, "users", str(OTHER_ID), "boxed"),)   # 掛的是本機路徑
    assert call["cwd"] == os.path.normpath(folder)                        # 引擎用戶端在本機的 pack 資料夾跑
    out = json.loads(bot.last(OTHER_ID))
    assert out["pack_dir"] == "/pack" and out["argv"] == ["show", "hi"]


def test_mcp_stdio_runs_through_container(make_bot, tmp_path):
    from test_mcp_stdio import FAKE, ALLOW, EFFECTS
    folder = os.path.join(str(tmp_path / "packs"), "demo")
    os.makedirs(folder)
    with open(os.path.join(folder, "server.py"), "w", encoding="utf-8") as f:
        f.write(FAKE)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: demo\ndescription: d\n---\n")
    raw = {"name": "demo", "title": "假 MCP", "summary": "s", "version": "0.1.0", "kind": "mcp",
           "capabilities": ["subprocess"], "data": "user", "skill": "SKILL.md", "runtime": {"container": {"image": IMAGE}},
           "mcp": {"transport": "stdio", "argv": ["{python}", "./server.py"], "timeout": 5, "tools_allow": ALLOW,
                   "effects": EFFECTS}}
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    _choose(tmp_path / "data", folder, trust="core")
    rec = Recorder(folder, "server.py")
    sandbox.set_engine_which(_which("docker"))
    sandbox.set_container_factory(lambda config, target, engine: rec)
    bot = make_bot(pack_dirs=(str(tmp_path / "packs"),))
    try:
        bot.say(OWNER_ID, "/demo_echo hi")
        assert bot.app.tasks.wait(20)
        reply = json.loads(bot.last(OWNER_ID))
        assert reply["env"]["SYNOX_USER_DATA_DIR"] == "/data/user"         # 長駐程序拿到的是容器裡的路徑
        (call,) = rec.calls
        assert call["argv"] == ["python3", "/pack/server.py"] and call["grants"].timeout is None
    finally:
        for hook in list(bot.app.on_stop):
            hook(bot.app)
