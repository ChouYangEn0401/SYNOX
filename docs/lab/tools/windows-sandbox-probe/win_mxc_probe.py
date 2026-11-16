#!/usr/bin/env python3
"""
SYNOX research probe -- Microsoft eXecution Containers (MXC) ProcessContainer, driven through wxc-exec.exe.

STATUS: written and first run on 2026-11-16 (Windows 11 Home 25H2, build 26200.9974, normal user, Python 3.11,
wxc-exec 1.1.0 from the @microsoft/mxc-sdk 1.1.0 npm tarball). Same test items as win_appcontainer_probe.py
(F1-F5, N1-N6, P1/P2) plus a long-running stdio round-trip (S1) and a loopback-proxy check (X1/X2).

Where wxc-exec.exe comes from: it ships inside the official npm package @microsoft/mxc-sdk (bin\\x64, MIT,
Authenticode-signed by Microsoft). No npm needed: download the tarball from registry.npmjs.org, check its sha512
against the registry's "integrity" field, unpack it with tar, and pass --wxc <path>\\package\\bin\\x64\\wxc-exec.exe.
See the README in this folder for the exact commands.

NOTE ON TELEMETRY: MXC's docs say four "Required" telemetry events (ExecutionStart/End, Error, ProcessExited) are
collected on supported Windows builds regardless of any setting. Running this probe therefore sends those events.

What it touches (nothing else):
  - creates  %TEMP%\\synox-research-mxc-<random>\\{ro,rw,outside}   (deleted at the end)
  - starts wxc-exec.exe several times; each run creates and destroys a transient container
  - opens one listening socket on 127.0.0.1 (random port)
  - only with --net: at most 1 HTTPS request attempt to https://example.com under "egress deny" (expected blocked)
It needs NO administrator rights and installs nothing. It never reads your documents (F5 records success only).

Usage:
    python win_mxc_probe.py --wxc PATH\\wxc-exec.exe [--node PATH\\node.exe] [--ports 11434,8830] [--net]
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time


def arg(name: str):
    if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv):
        return sys.argv[sys.argv.index(name) + 1]
    return None


def redact(text: str) -> str:
    user = os.environ.get("USERNAME", "")
    if not user:
        return text
    return re.sub(r"(?i)(\\+)" + re.escape(user) + r"(?=\\|\"|'|$)", lambda m: m.group(1) + "<user>", text)


def main() -> int:
    if os.name != "nt":
        print("This probe only runs on Windows.")
        return 2
    wxc = arg("--wxc") or shutil.which("wxc-exec")
    if not wxc or not os.path.isfile(wxc):
        print("wxc-exec.exe not found: pass --wxc PATH (see the README for where to get it)")
        return 2
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    cmd_exe = os.path.join(system32, "cmd.exe")
    curl_exe = os.path.join(system32, "curl.exe")
    root = os.path.join(tempfile.gettempdir(), "synox-research-mxc-" + secrets.token_hex(4))
    ro, rw, outside = (os.path.join(root, n) for n in ("ro", "rw", "outside"))
    py_home = sys.base_prefix
    node = arg("--node") or shutil.which("node")
    results = []
    hits = {"count": 0}
    stop = threading.Event()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.5)
    port = listener.getsockname()[1]

    def accept_loop():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except OSError:
                continue
            hits["count"] += 1
            try:
                conn.settimeout(2)
                try:
                    conn.recv(4096)
                except OSError:
                    pass
                conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
            finally:
                conn.close()

    threading.Thread(target=accept_loop, daemon=True).start()

    def request(command: str, *, readonly=(), readwrite=(), denied=(), egress="deny", loopback=None,
                proxy=None, ui=False, timeout_ms=30000) -> dict:
        req = {"version": "1.0.0", "containment": "processcontainer",
               "process": {"commandLine": command, "cwd": rw, "timeout": timeout_ms},
               "filesystem": {"readonlyPaths": list(readonly), "readwritePaths": [rw, *readwrite],
                              "deniedPaths": list(denied)},
               "network": {"egress": {"default": egress}}}
        if loopback:
            req["network"]["ingress"] = {"hostLoopback": loopback}
        if proxy:
            # "Identityless loopback proxy" (MXC networking.md): networkProxy + ingress.default=allow +
            # hostLoopback=allow and no allowedProxyPeer. wxc-exec 1.1.0 rejects the request otherwise (measured).
            # MXC then sets HTTP(S)_PROXY inside and narrows loopback to exactly this endpoint.
            req["runtimeConfig"] = {"networkProxy": proxy}
            req["network"]["ingress"] = {"default": "allow", "hostLoopback": "allow"}
        if ui:
            # Measured: node.exe and Python's _ssl die in DLL init (0xC0000142) unless Win32k/UI is allowed.
            # Allow UI but keep clipboard and input injection off.
            req["ui"] = {"disable": False, "clipboard": "none", "injection": False}
        return req

    def run(req: dict, timeout: float = 90.0):
        """Run one transient container; returns (exit_code or None, stdout, stderr, seconds)."""
        cfg = base64.b64encode(json.dumps(req).encode("utf-8")).decode("ascii")
        t0 = time.time()
        try:
            p = subprocess.run([wxc, "--config-base64", cfg], capture_output=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return None, "", "timed out", time.time() - t0
        out = p.stdout.decode("mbcs", "replace")
        err = p.stderr.decode("mbcs", "replace")
        return p.returncode, out, err, time.time() - t0

    def record(key, what, expect, code, note=""):
        if code is None:
            verdict = "ERROR"
        elif expect == "allow":
            verdict = "PASS" if code == 0 else "FAIL"
        elif expect == "deny":
            verdict = "PASS" if code != 0 else "FAIL"
        else:
            verdict = "INFO"
        note = " ".join(note.split())[:400]
        results.append({"test": key, "what": what, "expect": expect, "exit_code": code, "note": note,
                        "verdict": verdict})
        print(f"{key:4s} {verdict:5s} expect={expect:5s} exit={code} {what} {note}".rstrip())

    def shell(test: str) -> str:
        return f'"{cmd_exe}" /d /s /c "{test}"'

    def tail(out, err, secs):
        bits = [f"{secs:.1f}s"]
        if out.strip():
            bits.append("out=" + out.strip()[:160])
        if err.strip():
            bits.append("err=" + err.strip()[:300])
        return " ".join(bits)

    packages = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages")
    before_pkgs = set(os.listdir(packages)) if os.path.isdir(packages) else set()
    try:
        for d in (ro, rw, outside):
            os.makedirs(d)
        for d, text in ((ro, "ro-canary"), (rw, "rw-canary"), (outside, "outside-canary")):
            with open(os.path.join(d, "canary.txt"), "w", encoding="ascii") as f:
                f.write(text + "\n")
        probe = subprocess.run([wxc, "--probe"], capture_output=True, text=True, timeout=30)
        try:
            tier = json.loads(probe.stdout).get("tier")
        except ValueError:
            tier = None
        record("M0", "wxc-exec --probe: native ProcessContainer available", "allow", probe.returncode,
               f"tier={tier}")
        print(f"scratch: {root}\nloopback listener: 127.0.0.1:{port}\n")

        code, out, err, secs = run(request(shell(f'type "{os.path.join(ro, "canary.txt")}"'), readonly=[ro]))
        record("F1", "read a file in a readonlyPaths folder", "allow", code, tail(out, err, secs))
        target = os.path.join(rw, "written.txt")
        code, out, err, secs = run(request(shell(f'echo written> "{target}"')))
        made = os.path.isfile(target)
        record("F2", "write a file in a readwritePaths folder", "allow", code if made or code is None else 1,
               f"file exists={made} " + tail(out, err, secs))
        target = os.path.join(ro, "written.txt")
        code, out, err, secs = run(request(shell(f'echo x> "{target}"'), readonly=[ro]))
        leaked = os.path.isfile(target)
        record("F2b", "write a file in a readonlyPaths folder", "deny",
               None if code is None else (0 if leaked else (code or 1)), f"file exists={leaked} " + tail(out, err, secs))
        code, out, err, secs = run(request(shell(f'type "{os.path.join(outside, "canary.txt")}"')))
        record("F3", "read a file in a folder NOT in the policy", "deny",
               1 if code == 0 and "outside-canary" not in out else code, tail(out, err, secs))
        target = os.path.join(outside, "written.txt")
        code, out, err, secs = run(request(shell(f'echo x> "{target}"')))
        leaked = os.path.isfile(target)
        record("F4", "write a file in a folder NOT in the policy", "deny",
               None if code is None else (0 if leaked else (code or 1)), f"file exists={leaked} " + tail(out, err, secs))
        profile = os.environ.get("USERPROFILE", "")
        code, out, err, secs = run(request(shell(f'dir /b "{profile}" > NUL')))
        record("F5", "list the user profile folder (output discarded)", "deny", code, tail("", err, secs))
        code, out, err, secs = run(request(shell(f'type "{os.path.join(ro, "canary.txt")}"'), readonly=[ro],
                                           denied=[ro]))
        record("F6", "deniedPaths wins over readonlyPaths for the same folder", "deny",
               1 if code == 0 and "ro-canary" not in out else code, tail(out, err, secs))

        os.environ["SYNOX_PROBE_MARKER"] = "1"
        code, out, err, secs = run(request(shell("set")))
        del os.environ["SYNOX_PROBE_MARKER"]
        names = sorted({line.split("=", 1)[0] for line in out.splitlines() if "=" in line})
        temp_line = next((line for line in out.splitlines() if line.upper().startswith("TEMP=")), "")
        record("E1", "default environment inside (names only + TEMP)", "info", code,
               f"marker_seen={'SYNOX_PROBE_MARKER' in names} vars={len(names)} {temp_line} names={','.join(names)}")

        def curl(url: str, **kw):          # --noproxy: always a DIRECT connection, even if HTTP(S)_PROXY is set
            return run(request(f'"{curl_exe}" --noproxy "*" -s -m 6 -o NUL -w "%{{http_code}}" {url}', **kw))

        before = hits["count"]
        code, out, err, secs = curl(f"http://127.0.0.1:{port}/")
        time.sleep(0.3)
        record("N2", "egress deny: connect to host loopback", "deny", code,
               f"listener hits={hits['count'] - before} " + tail(out, err, secs))
        before = hits["count"]
        code, out, err, secs = curl(f"http://127.0.0.1:{port}/", egress="allow")
        time.sleep(0.3)
        record("N4", "egress allow (no hostLoopback): connect to host loopback", "deny", code,
               f"listener hits={hits['count'] - before} " + tail(out, err, secs))
        before = hits["count"]
        code, out, err, secs = curl(f"http://127.0.0.1:{port}/", loopback="allow")
        time.sleep(0.3)
        record("N4b", "ingress.hostLoopback=allow: connect to host loopback", "allow", code,
               f"listener hits={hits['count'] - before} " + tail(out, err, secs))
        for p in [x.strip() for x in (arg("--ports") or "").split(",") if x.strip().isdigit()]:
            try:
                socket.create_connection(("127.0.0.1", int(p)), timeout=1).close()
            except OSError:
                print(f"N6   SKIP  nothing listens on 127.0.0.1:{p}")
                continue
            code, out, err, secs = curl(f"http://127.0.0.1:{p}/", egress="allow")
            record("N6", f"egress allow: GET / to existing host service 127.0.0.1:{p}", "deny", code, tail(out, err, secs))
            code, out, err, secs = curl(f"http://127.0.0.1:{p}/", proxy=f"http://127.0.0.1:{port}")
            record("X2", f"proxy mode (identityless), egress deny: DIRECT GET / to 127.0.0.1:{p}",
                   "deny", code, tail(out, err, secs))
            code, out, err, secs = curl(f"http://127.0.0.1:{p}/", loopback="allow")
            record("N6b", f"hostLoopback=allow: GET / to existing host service 127.0.0.1:{p}", "info", code,
                   tail(out, err, secs))
        # X1: the loopback-proxy path the domain allow-list would use: proxy = our listener, egress deny.
        before = hits["count"]
        code, out, err, secs = curl(f"http://127.0.0.1:{port}/", proxy=f"http://127.0.0.1:{port}")
        time.sleep(0.3)
        record("X1", "proxy mode (identityless), egress deny: DIRECT connect to the proxy endpoint", "allow", code,
               f"listener hits={hits['count'] - before} " + tail(out, err, secs))
        other = socket.socket()
        other.bind(("127.0.0.1", 0))
        other.listen(1)
        code, out, err, secs = curl(f"http://127.0.0.1:{other.getsockname()[1]}/", proxy=f"http://127.0.0.1:{port}")
        other.close()
        record("X3", "proxy mode (identityless): DIRECT connect to another host loopback port", "deny", code,
               tail(out, err, secs))
        before = hits["count"]
        code, out, err, secs = run(request(shell(f'set HTTPS_PROXY & "{curl_exe}" -s -m 6 -o NUL -w "%{{http_code}}" '
                                                 'http://example.invalid/'), proxy=f"http://127.0.0.1:{port}"))
        time.sleep(0.3)
        record("X4", "proxy mode: plain curl to a host NAME goes through HTTP(S)_PROXY set by MXC", "allow", code,
               f"listener hits={hits['count'] - before} " + tail(out, err, secs))
        if "--net" in sys.argv:
            code, out, err, secs = curl("https://example.com/")
            record("N1", "egress deny: HTTPS to example.com", "deny", code, tail(out, err, secs))
        else:
            print("N1/N3 SKIP (internet tests need --net; N3 'allow' was not run on purpose)")

        py_plain = f'"{sys.executable}" -I -c "print(1+1)"'
        py_ssl = f'"{sys.executable}" -I -c "import ssl, json; print(1+1)"'
        code, out, err, secs = run(request(py_plain))
        record("P1", "per-user Python, its folder NOT in the policy", "info", code, tail(out, err, secs))
        code, out, err, secs = run(request(py_plain, readonly=[py_home]))
        record("P1c", "per-user Python, install folder in readonlyPaths (no ssl import)", "allow", code,
               tail(out, err, secs))
        code, out, err, secs = run(request(py_ssl, readonly=[py_home]))
        record("P1d", "same, but 'import ssl' (UI/Win32k disabled = default)", "info", code, tail(out, err, secs))
        code, out, err, secs = run(request(py_ssl, readonly=[py_home], ui=True))
        record("P1e", "same 'import ssl' with ui.disable=false (clipboard none, injection off)", "allow", code,
               tail(out, err, secs))
        if node:
            node_cmd = f'"{node}" -e "console.log(1+1)"'
            code, out, err, secs = run(request(node_cmd))
            record("P2", "node.exe, its folder NOT in the policy", "info", code, tail(out, err, secs))
            code, out, err, secs = run(request(node_cmd, readonly=[os.path.dirname(node)]))
            record("P2c", "node.exe, its folder in readonlyPaths (UI disabled = default)", "info", code,
                   tail(out, err, secs))
            code, out, err, secs = run(request(node_cmd, readonly=[os.path.dirname(node)], ui=True))
            record("P2e", "node.exe, folder in readonlyPaths, ui.disable=false", "allow", code, tail(out, err, secs))
        else:
            print("P2   SKIP  node not found (use --node PATH)")

        # S1: long-running stdio round-trip. A Python echo loop inside the container; we write three lines with
        # pauses and expect each reply before sending the next, then close stdin and expect a clean exit.
        echo = os.path.join(rw, "echo_loop.py")
        with open(echo, "w", encoding="ascii") as f:
            f.write("import sys\nfor line in sys.stdin:\n    sys.stdout.write('echo:' + line)\n    sys.stdout.flush()\n")
        req = request(f'"{sys.executable}" -I -u "{echo}"', readonly=[py_home], timeout_ms=120000)
        cfg = base64.b64encode(json.dumps(req).encode("utf-8")).decode("ascii")
        t0 = time.time()
        proc = subprocess.Popen([wxc, "--config-base64", cfg], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        replies, timings, note = [], [], ""
        got = []

        def reader():
            for raw in proc.stdout:
                got.append((time.time(), raw.decode("utf-8", "replace").rstrip()))

        threading.Thread(target=reader, daemon=True).start()
        try:
            for i in range(3):
                sent = time.time()
                proc.stdin.write(f"ping{i}\n".encode())
                proc.stdin.flush()
                deadline = sent + 15
                while time.time() < deadline and len(got) <= i:
                    time.sleep(0.02)
                if len(got) > i:
                    replies.append(got[i][1])
                    timings.append(round(got[i][0] - sent, 3))
                else:
                    note = f"no reply to ping{i} within 15s"
                    break
                time.sleep(2)
            proc.stdin.close()
            code = proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            proc.kill()
            code = None
            note = f"{type(exc).__name__}: {exc}"
        err = proc.stderr.read().decode("mbcs", "replace") if proc.stderr else ""
        ok = replies == ["echo:ping0", "echo:ping1", "echo:ping2"]
        record("S1", "long-running stdio: 3 line round-trips over ~6s, then EOF", "allow",
               None if code is None else (code if ok else (code or 1)),
               f"replies={replies} reply_secs={timings} total={time.time() - t0:.1f}s {note} "
               + (f"err={err.strip()[:200]}" if err.strip() else ""))
    finally:
        stop.set()
        listener.close()
        shutil.rmtree(root, ignore_errors=True)
        after_pkgs = set(os.listdir(packages)) if os.path.isdir(packages) else set()
        print(f"\ncleanup: scratch removed={not os.path.exists(root)}; new %LOCALAPPDATA%\\Packages entries left "
              f"behind by MXC: {sorted(after_pkgs - before_pkgs) or 'none'}")

    wv = sys.getwindowsversion()
    report = os.path.join(os.path.dirname(os.path.abspath(__file__)), "win_mxc_probe_result.json")
    with open(report, "w", encoding="utf-8") as f:
        f.write(redact(json.dumps({"windows": {"major": wv.major, "minor": wv.minor, "build": wv.build},
                                   "python": sys.version, "wxc_exec": redact(wxc), "argv": sys.argv[1:],
                                   "leftover_packages": sorted(after_pkgs - before_pkgs), "results": results},
                                  indent=1, ensure_ascii=False)))
    print(f"result file: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
