#!/usr/bin/env python3
"""
SYNOX research probe (stage 3, part B) -- Windows AppContainer feasibility test.

STATUS: written on Linux, NEVER RUN ON WINDOWS. Only a syntax check was done. Treat every result as
"first real measurement"; if the script itself fails, that is a script bug, not a finding.

What it answers (each one is marked "to be measured" in B-sandbox-npm.md):
  F1-F5  Can an unpackaged AppContainer process read/write ONLY a folder we grant by ACL?
  N1-N4  Is the network really off without the internetClient capability? Is loopback blocked?
         Does internetClient turn the internet back on (all-or-nothing, no domain filter)?
  P1-P2  Can python.exe / node.exe even START inside an AppContainer from where they are installed?

What it touches (nothing else):
  - creates  %TEMP%\\synox-research-<random>\\{inside,outside}   (deleted at the end)
  - creates an AppContainer profile named "synox.research.probe"  (deleted at the end; Windows keeps it under
    %LOCALAPPDATA%\\Packages\\synox.research.probe and a per-user registry mapping)
  - opens one listening socket on 127.0.0.1 (random port) for the loopback test
  - makes at most 2 HTTPS requests to https://example.com from the sandboxed curl.exe
  - runs icacls on the "inside" scratch folder only
It needs NO administrator rights, installs nothing, and never reads your documents: the "list my profile"
test only records whether the listing was allowed (output goes to NUL).

Usage (normal, non-admin PowerShell or cmd):
    python win_appcontainer_probe.py            # run everything, print a table, write result JSON next to the script
    python win_appcontainer_probe.py --no-net   # skip the two requests to example.com
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

PROFILE = "synox.research.probe"
E_ALREADY_EXISTS = 0x800700B7
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_NO_WINDOW = 0x08000000
WAIT_TIMEOUT = 0x00000102
SE_GROUP_ENABLED = 0x00000004
CAP_INTERNET_CLIENT = "S-1-15-3-1"          # WinCapabilityInternetClientSid


def main() -> int:
    if os.name != "nt":
        print("This probe only runs on Windows (it calls userenv/advapi32/kernel32).")
        return 2
    import ctypes
    import ctypes.wintypes as wt

    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PSID = ctypes.c_void_p

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", PSID), ("Attributes", wt.DWORD)]

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [("AppContainerSid", PSID), ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
                    ("CapabilityCount", wt.DWORD), ("Reserved", wt.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                    ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                    ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                    ("hStdError", wt.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD),
                    ("dwThreadId", wt.DWORD)]

    userenv.CreateAppContainerProfile.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR,
                                                  ctypes.POINTER(SID_AND_ATTRIBUTES), wt.DWORD, ctypes.POINTER(PSID)]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [wt.LPCWSTR, ctypes.POINTER(PSID)]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [wt.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    advapi32.ConvertSidToStringSidW.argtypes = [PSID, ctypes.POINTER(wt.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wt.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(PSID)]
    advapi32.ConvertStringSidToSidW.restype = wt.BOOL
    advapi32.FreeSid.argtypes = [PSID]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wt.DWORD, wt.DWORD,
                                                           ctypes.POINTER(ctypes.c_size_t)]
    kernel32.InitializeProcThreadAttributeList.restype = wt.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                                   ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.UpdateProcThreadAttribute.restype = wt.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                                        ctypes.c_void_p, wt.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW),
                                        ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.CreateProcessW.restype = wt.BOOL
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.WaitForSingleObject.restype = wt.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]

    def hr(value: int) -> int:
        return value & 0xFFFFFFFF

    def profile_sid() -> "ctypes.c_void_p":
        sid = PSID()
        rc = hr(userenv.CreateAppContainerProfile(PROFILE, "SYNOX research probe",
                                                  "Temporary profile created by win_appcontainer_probe.py",
                                                  None, 0, ctypes.byref(sid)))
        if rc == E_ALREADY_EXISTS:
            rc = hr(userenv.DeriveAppContainerSidFromAppContainerName(PROFILE, ctypes.byref(sid)))
        if rc != 0:
            raise OSError(f"CreateAppContainerProfile/Derive failed: HRESULT 0x{rc:08X}")
        return sid

    def sid_text(sid) -> str:
        buf = wt.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(buf)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return buf.value
        finally:
            kernel32.LocalFree(buf)

    def run_boxed(sid, capability_sids, command: str, cwd: str, timeout: float = 30.0):
        """Start `command` inside the AppContainer. Returns (exit_code or None, note)."""
        caps = (SID_AND_ATTRIBUTES * max(1, len(capability_sids)))()
        for i, cap in enumerate(capability_sids):
            caps[i].Sid, caps[i].Attributes = cap, SE_GROUP_ENABLED
        sc = SECURITY_CAPABILITIES()
        sc.AppContainerSid = sid
        sc.Capabilities = caps if capability_sids else None
        sc.CapabilityCount = len(capability_sids)
        size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attrs = ctypes.create_string_buffer(size.value)
        if not kernel32.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)):
            return None, f"InitializeProcThreadAttributeList failed: {ctypes.get_last_error()}"
        try:
            if not kernel32.UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                                                      ctypes.byref(sc), ctypes.sizeof(sc), None, None):
                return None, f"UpdateProcThreadAttribute failed: {ctypes.get_last_error()}"
            si = STARTUPINFOEXW()
            si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            si.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
            pi = PROCESS_INFORMATION()
            line = ctypes.create_unicode_buffer(command)
            ok = kernel32.CreateProcessW(None, line, None, None, False,
                                         EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW, None, cwd,
                                         ctypes.byref(si), ctypes.byref(pi))
            if not ok:
                err = ctypes.get_last_error()
                return None, f"CreateProcessW failed: WinError {err} ({ctypes.FormatError(err).strip()})"
            try:
                if kernel32.WaitForSingleObject(pi.hProcess, int(timeout * 1000)) == WAIT_TIMEOUT:
                    kernel32.TerminateProcess(pi.hProcess, 1)
                    return None, "timed out (killed)"
                code = wt.DWORD()
                kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
                return int(code.value), ""
            finally:
                kernel32.CloseHandle(pi.hThread)
                kernel32.CloseHandle(pi.hProcess)
        finally:
            kernel32.DeleteProcThreadAttributeList(attrs)

    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    cmd_exe = os.path.join(system32, "cmd.exe")
    curl_exe = os.path.join(system32, "curl.exe")
    root = os.path.join(tempfile.gettempdir(), "synox-research-" + secrets.token_hex(4))
    inside, outside = os.path.join(root, "inside"), os.path.join(root, "outside")
    results = []
    hits = {"count": 0}
    stop = threading.Event()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
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
                conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
            finally:
                conn.close()

    threading.Thread(target=accept_loop, daemon=True).start()
    sid = None
    cap_inet = PSID()
    try:
        os.makedirs(inside)
        os.makedirs(outside)
        sid = profile_sid()
        sid_str = sid_text(sid)
        if not advapi32.ConvertStringSidToSidW(CAP_INTERNET_CLIENT, ctypes.byref(cap_inet)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Grant the AppContainer SID modify rights on "inside" only (inherits to children). "outside" gets nothing.
        acl = subprocess.run(["icacls", inside, "/grant", f"*{sid_str}:(OI)(CI)(M)"], capture_output=True, text=True)
        with open(os.path.join(inside, "canary.txt"), "w", encoding="ascii") as f:
            f.write("inside-canary\n")
        with open(os.path.join(outside, "canary.txt"), "w", encoding="ascii") as f:
            f.write("outside-canary\n")
        print(f"scratch: {root}\nAppContainer SID: {sid_str}\nicacls rc={acl.returncode}\nloopback listener: 127.0.0.1:{port}\n")

        def shell(test: str) -> str:              # cmd /s strips the outer quotes; everything else is literal
            return f'"{cmd_exe}" /d /s /c "{test}"'

        def record(key, what, expect, code, note, extra=""):
            if code is None:
                verdict = "ERROR"
            elif expect == "allow":
                verdict = "PASS" if code == 0 else "FAIL"
            elif expect == "deny":
                verdict = "PASS" if code != 0 else "FAIL"
            else:
                verdict = "INFO"
            results.append({"test": key, "what": what, "expect": expect, "exit_code": code, "note": note or extra,
                            "verdict": verdict})
            print(f"{key:4s} {verdict:5s} expect={expect:5s} exit={code} {what} {note or extra}")

        none, inet = [], [cap_inet]
        profile_dir = os.environ.get("USERPROFILE", "")
        out = os.path.join(inside, "out.txt")

        code, note = run_boxed(sid, none, shell(f'type "{os.path.join(inside, "canary.txt")}" > "{out}" 2>&1'), inside)
        record("F1", "read a file in the granted folder", "allow", code, note)
        code, note = run_boxed(sid, none, shell(f'echo written> "{os.path.join(inside, "written.txt")}"'), inside)
        made = os.path.isfile(os.path.join(inside, "written.txt"))
        record("F2", "write a file in the granted folder", "allow", code if made or code is None else 1, note,
               f"file exists={made}")
        code, note = run_boxed(sid, none, shell(f'type "{os.path.join(outside, "canary.txt")}" > "{out}" 2>&1'), inside)
        record("F3", "read a file in a folder NOT granted", "deny", code, note)
        code, note = run_boxed(sid, none, shell(f'echo x> "{os.path.join(outside, "written.txt")}"'), inside)
        leaked = os.path.isfile(os.path.join(outside, "written.txt"))
        record("F4", "write a file in a folder NOT granted", "deny",
               None if code is None else (0 if leaked else (code or 1)), note, f"file exists={leaked}")
        if profile_dir:
            code, note = run_boxed(sid, none, shell(f'dir "{profile_dir}" > NUL 2>&1'), inside)
            record("F5", "list the user profile folder (result only, output discarded)", "deny", code, note)
        code, note = run_boxed(sid, none, shell(f'set LOCALAPPDATA > "{out}" 2>&1 & set TEMP >> "{out}" 2>&1'), inside)
        seen = ""
        try:
            with open(out, "r", encoding="mbcs", errors="replace") as f:
                seen = " | ".join(line.strip() for line in f if line.strip())[:300]
        except OSError:
            pass
        record("E1", "environment the child sees (LOCALAPPDATA/TEMP)", "info", code, note, seen)

        if os.path.isfile(curl_exe):
            before = hits["count"]
            code, note = run_boxed(sid, none, f'"{curl_exe}" -s -m 5 -o NUL http://127.0.0.1:{port}/', inside)
            time.sleep(0.3)
            record("N2", "no capability: connect to host loopback", "deny", code, note,
                   f"listener hits={hits['count'] - before}")
            before = hits["count"]
            code, note = run_boxed(sid, inet, f'"{curl_exe}" -s -m 5 -o NUL http://127.0.0.1:{port}/', inside)
            time.sleep(0.3)
            record("N4", "internetClient: connect to host loopback (expected blocked; to be measured)", "deny", code,
                   note, f"listener hits={hits['count'] - before}")
            if "--no-net" not in sys.argv:
                code, note = run_boxed(sid, none, f'"{curl_exe}" -s -m 8 -o NUL https://example.com/', inside)
                record("N1", "no capability: HTTPS to example.com", "deny", code, note)
                code, note = run_boxed(sid, inet, f'"{curl_exe}" -s -m 15 -o NUL https://example.com/', inside)
                record("N3", "internetClient: HTTPS to example.com", "allow", code, note)
        else:
            print("curl.exe not found in System32: network tests skipped")

        py_out = os.path.join(inside, "py.txt")
        code, note = run_boxed(sid, none, shell(f'"{sys.executable}" -I -c "print(1+1)" > "{py_out}" 2>&1'), inside)
        record("P1", f"start this Python inside the AppContainer ({sys.executable})", "info", code, note)
        node = shutil.which("node")
        if node:
            code, note = run_boxed(sid, none, shell(f'"{node}" -e "console.log(1+1)" > "{py_out}" 2>&1'), inside)
            record("P2", f"start node inside the AppContainer ({node})", "info", code, note)
        else:
            print("P2   SKIP  node not on PATH")
    finally:
        stop.set()
        listener.close()
        if sid:
            advapi32.FreeSid(sid)
        if cap_inet:
            kernel32.LocalFree(cap_inet)
        rc = hr(userenv.DeleteAppContainerProfile(PROFILE))
        shutil.rmtree(root, ignore_errors=True)
        print(f"\ncleanup: DeleteAppContainerProfile HRESULT 0x{rc:08X}; scratch removed={not os.path.exists(root)}")

    report = os.path.join(os.path.dirname(os.path.abspath(__file__)), "win_appcontainer_probe_result.json")
    with open(report, "w", encoding="utf-8") as f:
        json.dump({"windows": sys.getwindowsversion()._asdict() if hasattr(sys, "getwindowsversion") else {},
                   "python": sys.version, "results": results}, f, indent=1, default=str)
    print(f"result file: {report}")
    print("P1/P2 exit 0 = the interpreter starts from its install folder; non-zero or ERROR = its folder is not "
          "readable by the AppContainer (SYNOX would have to add ACLs or use a copy).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
