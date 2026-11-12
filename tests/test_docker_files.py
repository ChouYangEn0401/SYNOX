# -*- coding: utf-8 -*-
"""Docker 相關檔案的關鍵規則（docs/docker.md「檢查表」）：只讀檔案字串與 JSON，不需要 Docker、不執行任何東西。
改 Dockerfile／docker-compose.yml／.devcontainer 時，這些是不能退的底線。"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), "r", encoding="utf-8") as f:
        return f.read()


def code_lines(text):
    """去掉註解與空行（# 開頭的整行）。"""
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


# ── docker-compose.yml ──────────────────────────────────────────────

def test_compose_publishes_only_on_host_loopback():
    lines = code_lines(read("docker-compose.yml"))
    start = lines.index("    ports:")
    published = []
    for line in lines[start + 1:]:
        if not line.startswith("      - "):
            break
        published.append(line.strip()[2:].strip('"'))
    assert published, "compose 要發佈網頁的埠"
    for item in published:
        assert item.startswith("127.0.0.1:"), f"埠只能發佈到宿主的 127.0.0.1：{item}"


def test_compose_has_hardening_and_no_dangerous_options():
    text = "\n".join(code_lines(read("docker-compose.yml")))
    for needed in ("read_only: true", "cap_drop:", "- ALL", "no-new-privileges:true", "tmpfs:", "init: true",
                   "mem_limit:", "pids_limit:", "cpus:", 'SYNOX_WEB_BIND: "0.0.0.0"', "synox-home:/synox"):
        assert needed in text, needed
    for banned in ("docker.sock", "privileged", "network_mode", "cap_add", "devices:", "pid: host", "ipc: host",
                   "userns_mode: host", "seccomp:unconfined", "apparmor:unconfined"):
        assert banned not in text, banned


# ── Dockerfile ──────────────────────────────────────────────────────

def test_dockerfile_basics():
    text = read("Dockerfile")
    lines = code_lines(text)
    froms = [line for line in lines if line.startswith("FROM ")]
    assert len(froms) == 2, "兩段式建置"
    assert "python:3.11-slim" in text and ":latest" not in text
    users = [line for line in lines if line.startswith("USER ")]
    assert users and users[-1].split()[1].split(":")[0] not in ("root", "0"), "最後要是非 root"
    assert any(line.startswith("HEALTHCHECK ") for line in lines)
    assert any(line.startswith('ENTRYPOINT ["') for line in lines), "exec 形式"
    assert any(line.startswith('CMD ["') for line in lines), "exec 形式"
    assert "SYNOX_IN_CONTAINER=1" in text and "SYNOX_HOME=/synox" in text


def test_dockerfile_does_not_bind_all_interfaces_by_itself():
    """映像檔不設 SYNOX_WEB_BIND：`docker run -p …` 忘了寫時網頁只綁容器的 loopback（安全的失敗），改綁由 compose 決定。"""
    env_lines = [line for line in code_lines(read("Dockerfile")) if "SYNOX_WEB_BIND" in line]
    assert env_lines == []


def test_dockerfile_copies_only_what_it_needs():
    sources = []
    for line in code_lines(read("Dockerfile")):
        if line.startswith("COPY ") and "--from" not in line:
            sources += line.split()[1:-1]
    assert "." not in sources and "./" not in sources, "不要 COPY 整個資料夾"
    assert set(sources) <= {"requirements.txt", "pyproject.toml", "vendor/", "src/", "LICENSE", "LICENSE-APACHE",
                            "NOTICE", "LICENSING.md", "docker/healthcheck.py"}


# ── .dockerignore ───────────────────────────────────────────────────

def test_dockerignore_is_an_allowlist_and_blocks_user_data():
    lines = code_lines(read(".dockerignore"))
    assert lines[0] == "*", "白名單：先全部排除"
    for pattern in ("**/data", "**/userdata", "**/var", "**/config.json", "**/.env", "**/*.key", "**/*.enc",
                    "**/.git", "**/.venv", "**/.pytest_cache", "**/packs.lock"):
        assert pattern in lines, pattern
    allowed = {line[1:] for line in lines if line.startswith("!")}
    assert not any(a.startswith(("data", "config.json", ".env", "tests", ".git")) for a in allowed)


def test_env_file_is_ignored_by_git_and_example_has_no_secret_values():
    assert ".env" in read(".gitignore").splitlines()
    for line in code_lines(read(".env.example")):
        name, _, value = line.partition("=")
        assert not re.search(r"TOKEN|KEY|SECRET|PASSWORD", name) or not value.strip(), line


# ── .devcontainer ───────────────────────────────────────────────────

def test_devcontainer_forwards_only_the_web_port_to_localhost():
    cfg = json.loads(read(".devcontainer", "devcontainer.json"))
    assert "3.11" in cfg["image"]
    assert cfg["forwardPorts"] == [8830]
    assert cfg["otherPortsAttributes"]["onAutoForward"] == "ignore"
    assert cfg["customizations"]["vscode"]["settings"]["remote.localPortHost"] == "localhost"
    assert "appPort" not in cfg
    raw = json.dumps(cfg)
    for banned in ("docker.sock", "--privileged", "--network=host", "docker-in-docker", "docker-outside-of-docker",
                   '"-p"', "--publish"):
        assert banned not in raw, banned
