# -*- coding: utf-8 -*-
"""S0：pack.json 的 runtime.container（第 1 關）與 Dockerfile（第 2 關）。只讀字串與檔案，
不叫 podman／docker、不拉映像、不 build（docs/discussions/2026-11-10-isolation-howto.md）。"""
import json
import os

import pytest

from synox.packs import container as pack_container
from synox.packs import tier as pack_tier
from synox.packs.manifest import ManifestError, read
from synox.packs.scan import scan

DIGEST = "a" * 64
IMAGE = f"ghcr.io/example/weather@sha256:{DIGEST}"
BASE = f"docker.io/library/python@sha256:{'b' * 64}"
TOOL = "import json\nprint(json.dumps({'message': 'ok'}))\n"


def _write(folder, raw, files=None):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(f"---\nname: {raw['name']}\ndescription: d\n---\n")
    for rel, text in (files or {}).items():
        path = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return folder


def cli_raw(name="box", container=None, caps=None, **extra):
    raw = {"name": name, "title": name, "summary": "s", "version": "0.1.0", "kind": "cli", "skill": "SKILL.md",
           "access": "member", "publisher": "Example", "capabilities": caps or [],
           "cli": {"argv": ["{python}", "./tool.py"], "json_flag": None,
                   "commands": [{"name": "show", "effect": "READ", "argv": ["show"]}]}}
    if container is not None:
        raw["runtime"] = {"container": container}
    raw.update(extra)
    return raw


def make(tmp_path, container, caps=None, files=None, name="box", **extra):
    folder = str(tmp_path / name)
    return _write(folder, cli_raw(name, container, caps, **extra), {"tool.py": TOOL, **(files or {})})


def problems(tmp_path, container, **kw):
    problems.n = getattr(problems, "n", 0) + 1                              # 每次一個新資料夾
    with pytest.raises(ManifestError) as e:
        read(make(tmp_path, container, name=f"box{problems.n}", **kw), strict=True)
    return str(e.value)


# ── 第 1 關：合格的寫法 ────────────────────────────────────────────────

def test_minimal_image_ok(tmp_path):
    m = read(make(tmp_path, {"image": IMAGE}), strict=True)
    spec = m.runtime["container"]
    assert spec["image"] == IMAGE and spec["network"] is False and spec["user"] == "nonroot"
    assert spec["mounts"] == {"pack": "/pack", "user_data": "/data/user", "shared_data": "/data/shared"}
    assert spec["python"] == "python3" and spec["resources"] == {}
    assert pack_container.image_ref(m) == IMAGE


def test_full_spec_ok(tmp_path):
    spec = {"image": IMAGE, "network": True, "resources": {"mem_mb": 256, "cpus": 0.5, "pids": 32},
            "mounts": {"pack": "/app", "user_data": "/srv/user"}, "env_passthrough": ["WEATHER_KEY"],
            "user": "1000:1000", "python": "/usr/local/bin/python3", "entry": "stdio"}
    m = read(make(tmp_path, spec, caps=["network"], requires={"env": ["WEATHER_KEY"]}), strict=True)
    got = m.runtime["container"]
    assert got["resources"] == {"mem_mb": 256, "cpus": 0.5, "pids": 32}
    assert got["mounts"]["pack"] == "/app" and got["mounts"]["shared_data"] == "/data/shared"
    assert got["env_passthrough"] == ["WEATHER_KEY"] and got["user"] == "1000:1000"


def test_dockerfile_ok_and_local_image_name(tmp_path):
    folder = make(tmp_path, {"dockerfile": "./Dockerfile", "base": BASE},
                  files={"Dockerfile": f"FROM {BASE}\nCOPY . /pack\nUSER 65534\n"})
    m = read(folder, strict=True)
    assert m.runtime["container"]["dockerfile"] == "Dockerfile"
    ref = pack_container.image_ref(m)
    assert ref.startswith("localhost/synox-box:") and len(ref.split(":")[-1]) == 12
    assert not scan(m).problems(m)


def test_mcp_stdio_allows_container(tmp_path):
    raw = {"name": "mcpbox", "title": "t", "summary": "s", "version": "0.1.0", "kind": "mcp", "skill": "SKILL.md",
           "capabilities": ["subprocess"], "publisher": "Example",
           "mcp": {"transport": "stdio", "argv": ["{python}", "./server.py"], "tools_allow": ["a"],
                   "effects": {"a": "READ"}},
           "runtime": {"container": {"image": IMAGE}}}
    m = read(_write(str(tmp_path / "mcpbox"), raw, {"server.py": TOOL}), strict=True)
    assert m.runtime["container"]["image"] == IMAGE


# ── 第 1 關：危險設定一律拒 ────────────────────────────────────────────

@pytest.mark.parametrize("image, why", [
    ("ghcr.io/example/weather:latest", "digest"),
    ("ghcr.io/example/weather", "digest"),
    (f"ghcr.io/example/weather@sha256:{'A' * 64}", "digest"),                 # 大寫不是合法 digest
    (f"https://ghcr.io/example/weather@sha256:{DIGEST}", "網址"),
    (f"localhost/weather@sha256:{DIGEST}", "localhost"),
    (f"localhost:5000/weather@sha256:{DIGEST}", "localhost"),
    (f"10.0.0.5:5000/weather@sha256:{DIGEST}", "IP"),
    (f"evil.example.com/weather@sha256:{DIGEST}", "白名單"),
    (f"weather@sha256:{DIGEST}", "主機一定要寫"),
])
def test_image_without_digest_or_bad_registry_refused(tmp_path, image, why):
    assert why in problems(tmp_path, {"image": image})


@pytest.mark.parametrize("key, value, why", [
    ("privileged", True, "--privileged"),
    ("cap_add", ["SYS_ADMIN"], "--cap-add"),
    ("devices", ["/dev/kvm"], "--device"),
    ("volumes", ["/var/run/docker.sock:/var/run/docker.sock"], "本機資料夾"),
    ("security_opt", ["seccomp=unconfined"], "seccomp"),
    ("network_mode", "host", "host"),
    ("pid", "host", "--pid=host"),
    ("args", ["--privileged"], "任意"),
    ("ports", ["8080:80"], "不開埠"),
    ("whatever", 1, "不認得"),
])
def test_dangerous_keys_refused(tmp_path, key, value, why):
    assert why in problems(tmp_path, {"image": IMAGE, key: value})


def test_host_network_refused(tmp_path):
    assert "host" in problems(tmp_path, {"image": IMAGE, "network": "host"}, caps=["network"])


def test_network_must_match_capabilities(tmp_path):
    assert "一致" in problems(tmp_path, {"image": IMAGE, "network": True})               # 沒宣告 network
    assert "一致" in problems(tmp_path, {"image": IMAGE}, caps=["network"])              # 宣告了但容器說不連


@pytest.mark.parametrize("mounts, why", [
    ({"pack": "../pack"}, "絕對路徑"),
    ({"pack": "pack"}, "絕對路徑"),
    ({"pack": "/data/../etc"}, ".."),
    ({"pack": "/"}, "不能是 /"),
    ({"pack": "/proc/self"}, "/proc"),
    ({"pack": "/etc/x"}, "/etc"),
    ({"pack": "/var/run/docker.sock"}, "socket"),
    ({"user_data": "/srv/podman.sock"}, "socket"),
    ({"pack": "C:\\Users\\x"}, "本機路徑"),
    ({"pack": "//server/share"}, "本機路徑"),
    ({"host": "/srv/synox/data"}, "不收"),
    ({"/var/run/docker.sock": "/sock"}, "不收"),
    ({"pack": "/data/user"}, "重疊"),
    ({"pack": "/data/user/pack"}, "重疊"),
    ({"pack": "/a b"}, "英數字"),
    ({"pack": "/a,readonly=false"}, "英數字"),
])
def test_mount_escape_refused(tmp_path, mounts, why):
    assert why in problems(tmp_path, {"image": IMAGE, "mounts": mounts})


@pytest.mark.parametrize("user", ["root", "0", "0:0", "1000:0", "0:1000", "nobody", 1000])
def test_root_user_refused(tmp_path, user):
    assert "root" in problems(tmp_path, {"image": IMAGE, "user": user})


@pytest.mark.parametrize("resources", [{"mem_mb": 0}, {"mem_mb": "lots"}, {"pids": 1.5}, {"cpus": 1000},
                                       {"mem_mb": True}, {"swap": 1}])
def test_bad_resources_refused(tmp_path, resources):
    assert "resources" in problems(tmp_path, {"image": IMAGE, "resources": resources})


def test_env_passthrough_only_declared_secrets(tmp_path):
    assert "env_passthrough" in problems(tmp_path, {"image": IMAGE, "env_passthrough": ["AWS_SECRET"]})


def test_needs_image_or_dockerfile_and_base(tmp_path):
    assert "image" in problems(tmp_path, {"network": False})
    assert "base" in problems(tmp_path, {"dockerfile": "Dockerfile"}, files={"Dockerfile": f"FROM {BASE}\n"})
    assert "digest" in problems(tmp_path, {"dockerfile": "Dockerfile", "base": "docker.io/library/python:3.12"},
                                files={"Dockerfile": "FROM docker.io/library/python:3.12\n"})
    assert ".." in problems(tmp_path, {"dockerfile": "../Dockerfile", "base": BASE})
    assert "找不到" in problems(tmp_path, {"dockerfile": "Dockerfile", "base": BASE})
    assert "檔名" in problems(tmp_path, {"dockerfile": "build.sh", "base": BASE}, files={"build.sh": "x"})
    assert "entry" in problems(tmp_path, {"image": IMAGE, "entry": "http"})


def test_unc_dockerfile_refused_before_touching_filesystem(tmp_path):
    assert "網路路徑" in problems(tmp_path, {"dockerfile": "\\\\evil\\share\\Dockerfile", "base": BASE})


def test_python_pack_cannot_use_container(tmp_path):
    raw = {"name": "py", "title": "t", "summary": "s", "version": "0.1.0", "kind": "python", "skill": "SKILL.md",
           "runtime": {"container": {"image": IMAGE}}}
    with pytest.raises(ManifestError, match="容器包不到"):
        read(_write(str(tmp_path / "py"), raw, {"pack.py": "def install(app, pack):\n    pass\n"}), strict=True)


# ── 第 2 關：Dockerfile ───────────────────────────────────────────────

def _gate2(tmp_path, dockerfile):
    folder = make(tmp_path, {"dockerfile": "Dockerfile", "base": BASE}, files={"Dockerfile": dockerfile})
    m = read(folder, strict=True)
    report = scan(m)
    return report.problems(m), report


def test_dockerfile_single_from_with_digest(tmp_path):
    bad, _ = _gate2(tmp_path, f"FROM {BASE} AS a\nFROM docker.io/library/alpine@sha256:{'c' * 64}\n")
    assert any("一個 FROM" in p for p in bad)
    bad, _ = _gate2(tmp_path, "FROM docker.io/library/python:3.12\n")
    assert any("一字不差" in p for p in bad) and any("一個 FROM" not in p for p in bad)


def test_dockerfile_add_url_and_run_network_refused(tmp_path):
    bad, _ = _gate2(tmp_path, f"FROM {BASE}\nADD https://evil.example.com/x.tar.gz /opt/\n")
    assert any("網址" in p for p in bad)
    bad, _ = _gate2(tmp_path, f"FROM {BASE}\nRUN --network=host pip install x\n")
    assert any("--network" in p for p in bad)
    bad, _ = _gate2(tmp_path, f"FROM {BASE}\nCOPY --from=docker.io/library/busybox:latest /bin/sh /sh\n")
    assert any("digest" in p for p in bad)
    bad, _ = _gate2(tmp_path, f"FROM {BASE}\nONBUILD RUN echo\n")
    assert any("ONBUILD" in p for p in bad)


def test_dockerfile_run_downloads_listed_not_blocking(tmp_path):
    bad, report = _gate2(tmp_path, f"# comment\nFROM {BASE}\nRUN pip install \\\n    requests==2.32.3\nUSER root\n")
    assert bad == []
    notes = [f for f in report.findings if f.kind == "container_note"]
    assert any("pip install" in f.snippet and f.line == 3 for f in notes)
    assert any("USER root" in f.detail for f in notes)


def test_tier_unchanged_but_reports_container(tmp_path):
    m = read(make(tmp_path, {"image": IMAGE}), strict=True)
    info = pack_tier.assess(m)
    assert info["tier"] == pack_tier.T1                                    # 容器不改層級
    assert info["container"]["image"] == IMAGE and info["container"]["network"] is False
    plain = read(make(tmp_path, None, name="plain"), strict=True)
    assert pack_tier.assess(plain)["container"] == {}
