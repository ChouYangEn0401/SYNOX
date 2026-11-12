"""Clean-room check: does a fresh copy of SYNOX work without anything this computer happens to have?

    <python> scripts\\clean_room_check.py [--tools <SYNOX_Libs>\\dist | --libs <SYNOX_Libs>] [--keep] [--no-tests]

Steps (docs/adr/0002; the owner's real test on a blank machine is docs/handoff/clean-machine-test.md):
1. copy what ships (git-tracked files, same list as make_zip.py: no .git, .venv, data, config.json) into a new
   temp folder; optionally add tools/ (a built library, or build one from a SYNOX_Libs checkout into the copy);
2. scan the copy's text files for local paths (C:\\Users\\<name>, /home/<name>) and sibling-folder guesses
   (dirname(ROOT) + another project); a documented fallback carries "clean-room: sibling-fallback" on its line;
3. run the copy with a scrubbed environment: every SYNOX_* variable removed, PYTHONPATH = the copy only,
   PATH = Windows system folders only (no py, git, claude), USERPROFILE/HOME/APPDATA/LOCALAPPDATA = empty temp
   folders, current folder = another temp folder (not the copy):
   import check -> doctor --offline -> init --dry-run -> init --non-interactive (picks one tool when there is a
   library) -> tools list -> doctor --offline -> a pytest subset inside the copy;
4. every output is searched for the original checkout's path (a hidden dependency would show up there).

Limits -- this is NOT a blank computer: it reuses THIS interpreter (the existing .venv python; no new venv, no pip,
no network), so missing packages, the Python install itself, Setup.bat / bootstrap.ps1, winget, DPAPI under a new
Windows account, the window wizard and the exe installer are not exercised here.
Nothing is downloaded, no port is opened, no AI / Telegram is called; the temp folders are deleted unless --keep.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_zip  # noqa: E402

ROOT = make_zip.ROOT
DEFAULT_TESTS = ("tests/test_clean_room.py", "tests/test_root_dir.py", "tests/test_empty_host.py",
                 "tests/test_clean_room_check.py", "tests/test_wizard.py", "tests/test_lock_deps.py",
                 "tests/test_release_layout.py")
TEXT_EXT = (".py", ".ps1", ".psd1", ".bat", ".cmd", ".md", ".json", ".toml", ".txt", ".iss", ".cfg", ".ini", ".html",
            ".js", ".css")
SIBLING = re.compile(r"dirname\(\s*(?:ROOT|LIBS_ROOT|os\.path\.dirname\(ROOT\))\s*\)|\.\.[\\/]+(?:SYNOX|ISDTeleKitSDK)\b")
SIBLING_OK = "clean-room: sibling-fallback"
STEP_TIMEOUT = 300


class Report:
    def __init__(self, out=print):
        self.out = out
        self.failed = []
        self.notes = []

    def step(self, name: str, ok: bool, detail: str = "") -> bool:
        self.out(("  OK   " if ok else "  FAIL ") + name + (f"  -- {detail}" if detail else ""))
        if not ok:
            self.failed.append(name)
        return ok


def copy_release(dest: str, tools: str = "") -> int:
    files = make_zip.release_files(tools)
    for src, rel in files:
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
    return len(files)


def scan_files(pairs) -> list:
    """[(path, rel)] -> [(rel, line no, kind)] for local paths and sibling-folder guesses in text files."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import prepublish_check as pc
    hits = []
    for path, rel in pairs:
        if not rel.lower().endswith(TEXT_EXT) or rel.startswith("tools/"):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, kind in pc.scan_text(text):
            if "路徑" in kind:
                hits.append((rel, line_no, kind))
        if rel.endswith(".py"):
            for i, line in enumerate(text.splitlines(), 1):
                if SIBLING.search(line) and SIBLING_OK not in line:
                    hits.append((rel, i, f"sibling folder guess (mark a documented fallback with '{SIBLING_OK}')"))
    return hits


def scan_copy(copy: str) -> list:
    """Every text file under the copy (tools/ is the shipped library, not scanned)."""
    pairs = []
    for folder, _dirs, files in os.walk(copy):
        for name in files:
            path = os.path.join(folder, name)
            pairs.append((path, os.path.relpath(path, copy).replace(os.sep, "/")))
    return scan_files(pairs)


def scrubbed_env(copy: str, home: str) -> dict:
    """A user who has never seen SYNOX: no SYNOX_* variables, nothing on PATH but Windows itself, empty profile."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("SYNOX_", "PYTHON", "VIRTUAL_ENV",
                                                                              "CLAUDE", "ANTHROPIC", "OPENAI",
                                                                              "GEMINI", "TELEGRAM", "DISCORD"))}
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        env["PATH"] = os.pathsep.join([os.path.join(system_root, "System32"), system_root,
                                       os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0")])
        for key, sub in (("USERPROFILE", ""), ("APPDATA", "AppData/Roaming"), ("LOCALAPPDATA", "AppData/Local")):
            path = os.path.join(home, *[p for p in sub.split("/") if p])
            os.makedirs(path, exist_ok=True)
            env[key] = path
        env["HOMEDRIVE"], env["HOMEPATH"] = os.path.splitdrive(home)
    else:
        env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = home
    env["PYTHONPATH"] = os.pathsep.join([os.path.join(copy, "src"), os.path.join(copy, "vendor")])
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run(python: str, args: list, env: dict, cwd: str, timeout: int = STEP_TIMEOUT) -> tuple:
    started = time.monotonic()
    try:
        done = subprocess.run([python] + args, env=env, cwd=cwd, capture_output=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {timeout}s)"
    text = (done.stdout + done.stderr).decode("utf-8", errors="replace")
    return done.returncode, text + f"\n(elapsed {time.monotonic() - started:.1f}s)"


def leaked(text: str, originals, interpreter: str = "") -> list:
    """Which original paths show up in a step's output. The reused interpreter's own folder (its venv may live
    inside the original checkout) is taken out first: that one is a known limit, not a hidden dependency."""
    low = text.lower()
    if interpreter:
        venv = os.path.dirname(os.path.dirname(os.path.abspath(interpreter)))
        for form in {venv, venv.replace("\\", "/")}:
            low = low.replace(form.lower(), "<interpreter>")
    return [o for o in originals if o and o.lower() in low]


def first_tool(tools_dir: str) -> str:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from synox.wizard import tools as library
    lib = library.read(tools_dir)
    names = [e.name for e in lib.entries]
    starter = [n for n in (lib.bundles.get("starter") or {}).get("packs") or [] if n in names]
    return (starter or names or [""])[0]       # 建議組合 starter 的第一個（沒有就目錄的第一個）


def main(argv=None, out=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--tools", default="", help="a built tool library to ship as tools/ (SYNOX_Libs dist/)")
    group.add_argument("--libs", default="", help="a SYNOX_Libs checkout: build its tools into the copy's tools/")
    parser.add_argument("--keep", action="store_true", help="keep the temp folders and print where they are")
    parser.add_argument("--no-tests", action="store_true", help="skip the pytest subset")
    parser.add_argument("--tests", nargs="*", default=None, help=f"pytest targets (default: {' '.join(DEFAULT_TESTS)})")
    args = parser.parse_args(argv)
    python = sys.executable
    report = Report(out)
    base = tempfile.mkdtemp(prefix="synox-clean-room-")
    copy, elsewhere, home = (os.path.join(base, n) for n in ("SYNOX", "somewhere-else", "blank-user"))
    for d in (elsewhere, home):
        os.makedirs(d)
    originals = sorted({os.path.abspath(ROOT), os.path.realpath(ROOT)}
                       | ({os.path.abspath(args.libs)} if args.libs else set()))
    out(f"clean-room check: copy -> {copy}")
    out(f"  interpreter (reused, nothing installed): {python}")
    try:
        try:
            n = copy_release(copy, args.tools)
        except ValueError as e:
            report.step("copy what ships", False, str(e))
            return 1
        report.step("copy what ships", True, f"{n} files" + (" + tools/" if args.tools else ""))
        env = scrubbed_env(copy, home)
        if args.libs:
            libs_env = dict(env, SYNOX_HOME=copy)
            rc, text = run(python, [os.path.join(args.libs, "scripts", "build.py"), "--out",
                                    os.path.join(copy, "tools")], libs_env, elsewhere)
            report.step("build tools from SYNOX_Libs into the copy (SYNOX_HOME = the copy)", rc == 0,
                        "" if rc == 0 else " | ".join([x for x in text.strip().splitlines()
                                                       if not x.startswith("(elapsed")][-3:])[:400])
        hits = scan_copy(copy)
        report.step("no local paths / sibling-folder guesses in what ships", not hits,
                    "; ".join(f"{r}:{n} {k}" for r, n, k in hits[:8]) + (" ..." if len(hits) > 8 else ""))

        rc, text = run(python, ["-c", "import synox, isdtelekit, synox.config as c; "
                                      "print(synox.__file__); print(isdtelekit.__file__); print(c.ROOT); "
                                      "print(c.ROOT_SOURCE)"], env, elsewhere)
        lines = text.splitlines()
        inside = rc == 0 and len(lines) >= 4 and all(os.path.normcase(x).startswith(os.path.normcase(copy))
                                                    for x in lines[:3]) and lines[3] == "source"
        report.step("imports come from the copy; SYNOX folder = the copy", inside,
                    "" if inside else text.strip()[-300:])
        if not inside:
            return 1
        outputs = [text]
        tools_dir = os.path.join(copy, "tools")
        has_tools = os.path.isfile(os.path.join(tools_dir, "index.json"))
        steps = [("doctor --offline before setup (no config.json)", ["-m", "synox", "doctor", "--offline"], (0, 1)),
                 ("init --dry-run writes nothing",
                  ["-m", "synox", "init", "--non-interactive", "--dry-run", "--llm", "none"], (0,))]
        tool = first_tool(tools_dir) if has_tools else ""
        init_args = ["-m", "synox", "init", "--non-interactive", "--llm", "none"] + (["--tools", tool] if tool else [])
        steps.append(("init --non-interactive" + (f" (installs {tool} from tools/)" if tool else ""), init_args, (0,)))
        if has_tools:
            steps.append(("tools list (finds tools/ with no setting)", ["-m", "synox", "tools", "list"], (0,)))
        steps.append(("doctor --offline after setup", ["-m", "synox", "doctor", "--offline"], (0, 1)))
        config_path = os.path.join(copy, "config.json")
        for name, cmd, ok_codes in steps:
            if "--dry-run" in cmd and os.path.exists(config_path):
                os.remove(config_path)
            rc, text = run(python, cmd, env, elsewhere)
            outputs.append(text)
            ok = rc in ok_codes and "Traceback" not in text
            if ok and "--dry-run" in cmd:
                ok = not os.path.exists(config_path)
            if ok and cmd[2:3] == ["init"] and "--dry-run" not in cmd:
                ok = os.path.isfile(config_path) and (not tool or f"✅ {tool}" in text)
            if ok and cmd[2:3] == ["doctor"]:
                ok = f"資料夾：{copy}" in text
            report.step(name, ok, f"exit {rc}" + ("" if ok else ": " + text.strip()[-400:].replace("\n", " | ")))
        if not args.no_tests:
            targets = args.tests if args.tests else list(DEFAULT_TESTS)
            rc, text = run(python, ["-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp",
                                    os.path.join(base, "pytest"), *targets], env, copy, timeout=900)
            outputs.append(text)
            tail = [x for x in text.strip().splitlines() if x.strip()][-2:]
            report.step(f"pytest subset inside the copy ({len(targets)} files)", rc == 0, " | ".join(tail)[-300:])
        found = sorted({o for t in outputs for o in leaked(t, originals, python)})
        report.step("no output mentions the original checkout", not found, ", ".join(found))
    finally:
        if args.keep:
            out(f"  kept: {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)
    out("result: " + ("OK (this is a partial simulation; see the limits in the script header)" if not report.failed
                      else f"{len(report.failed)} step(s) failed: {', '.join(report.failed)}"))
    return 0 if not report.failed else 1


if __name__ == "__main__":
    sys.exit(main())
