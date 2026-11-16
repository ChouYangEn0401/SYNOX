#!/usr/bin/env python3
"""
SYNOX research probe -- Windows "write-restricted token + Job Object" (no AppContainer) feasibility test.

STATUS: written and first run on 2026-11-16 (Windows 11 Home 25H2, build 26200, normal user, Python 3.11).

Question: research topic 4 says a write-restricted token narrows WRITES only (reads and network are not blocked) and
that Schannel HTTPS (System32\\curl.exe) breaks under it [AN2]. This measures that on a real machine.

What it touches (nothing else):
  - creates  %TEMP%\\synox-research-rt-<random>\\{inside,outside}   (deleted at the end)
  - grants a made-up SID (S-1-9-1-<random>) modify rights on "inside" only (PowerShell Set-Acl)
  - opens one listening socket on 127.0.0.1 (random port)
  - at most 1 HTTPS request to https://example.com from the restricted curl.exe (skip with --no-net)
It needs NO administrator rights and installs nothing. The "read my profile" test only records success/failure.

Usage:  python win_restricted_token_probe.py [--no-net] [--no-everyone] [--restrict-also SID,SID]
"""
from __future__ import annotations

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

WRITE_RESTRICTED = 0x8
DISABLE_MAX_PRIVILEGE = 0x1
TOKEN_ALL_ACCESS = 0xF01FF
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
WAIT_TIMEOUT = 0x00000102
TokenUser = 1
TokenGroups = 2
TokenDefaultDacl = 6
SE_GROUP_LOGON_ID = 0xC0000000
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


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
    import ctypes
    import ctypes.wintypes as wt

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PSID = ctypes.c_void_p

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", PSID), ("Attributes", wt.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
                    ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
                    ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
                    ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
                    ("hStdError", wt.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD),
                    ("dwThreadId", wt.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                                                      "OtherOperationCount", "ReadTransferCount",
                                                      "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                             ctypes.POINTER(wt.DWORD)]
    advapi32.CreateRestrictedToken.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                               ctypes.c_void_p, wt.DWORD, ctypes.POINTER(SID_AND_ATTRIBUTES),
                                               ctypes.POINTER(wt.HANDLE)]
    advapi32.ConvertStringSidToSidW.argtypes = [wt.LPCWSTR, ctypes.POINTER(PSID)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wt.LPCWSTR, wt.DWORD,
                                                                              ctypes.POINTER(ctypes.c_void_p),
                                                                              ctypes.c_void_p]
    advapi32.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.BOOL),
                                                   ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.BOOL)]
    advapi32.SetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    advapi32.ConvertSidToStringSidW.argtypes = [PSID, ctypes.POINTER(wt.LPWSTR)]
    advapi32.CreateProcessAsUserW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                              wt.BOOL, wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                                              ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    kernel32.CreateJobObjectW.restype = wt.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    kernel32.ResumeThread.argtypes = [wt.HANDLE]
    kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel32.WaitForSingleObject.restype = wt.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    def sid_text(sid) -> str:
        buf = wt.LPWSTR()
        advapi32.ConvertSidToStringSidW(sid, ctypes.byref(buf))
        try:
            return buf.value
        finally:
            kernel32.LocalFree(buf)

    # The logon SID of this session goes into the restricting list so the child can still write to its own
    # window station / desktop objects; files in the user's folders are ACL'd to the user SID, not the logon SID.
    own = wt.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ALL_ACCESS, ctypes.byref(own)):
        raise ctypes.WinError(ctypes.get_last_error())
    need = wt.DWORD()
    advapi32.GetTokenInformation(own, TokenGroups, None, 0, ctypes.byref(need))
    groups_buf = ctypes.create_string_buffer(need.value)
    if not advapi32.GetTokenInformation(own, TokenGroups, groups_buf, need, ctypes.byref(need)):
        raise ctypes.WinError(ctypes.get_last_error())
    count = ctypes.cast(groups_buf, ctypes.POINTER(wt.DWORD))[0]
    offset = ctypes.sizeof(ctypes.c_void_p)          # DWORD GroupCount + padding on x64
    entries = ctypes.cast(ctypes.addressof(groups_buf) + offset, ctypes.POINTER(SID_AND_ATTRIBUTES))
    logon_sid = next((entries[i].Sid for i in range(count)
                      if entries[i].Attributes & SE_GROUP_LOGON_ID == SE_GROUP_LOGON_ID), None)

    # Measured 2026-11-16: CreateRestrictedToken rejects capability SIDs (S-1-15-3-...) as restricting SIDs with
    # ERROR_INVALID_PARAMETER (87); a made-up SID under the resource-manager authority (S-1-9-...) is accepted.
    cap_str = "S-1-9-1-" + "-".join(str(secrets.randbits(31)) for _ in range(4))
    cap_sid = PSID()
    if not advapi32.ConvertStringSidToSidW(cap_str, ctypes.byref(cap_sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    # Also Everyone (S-1-1-0). Measured: with only <made-up SID> + logon SID (+ RESTRICTED S-1-5-12) python.exe and
    # curl.exe die in DLL init (0xC0000142) while cmd.exe runs; adding Everyone fixes it. Trade-off: anything whose
    # ACL lets Everyone write becomes writable again. --no-everyone reproduces the failure; --restrict-also adds SIDs.
    restricting = [cap_str] + ([] if "--no-everyone" in sys.argv else ["S-1-1-0"]) +         [x for x in (arg("--restrict-also") or "").split(",") if x]
    restrict = (SID_AND_ATTRIBUTES * (len(restricting) + 1))()
    keep = []
    for i, text in enumerate(restricting):
        psid = PSID()
        if not advapi32.ConvertStringSidToSidW(text, ctypes.byref(psid)):
            raise ctypes.WinError(ctypes.get_last_error())
        keep.append(psid)
        restrict[i].Sid = psid
    n = len(restricting)
    if logon_sid:
        restrict[n].Sid = logon_sid
        n += 1
    token = wt.HANDLE()
    if not advapi32.CreateRestrictedToken(own, DISABLE_MAX_PRIVILEGE | WRITE_RESTRICTED, 0, None, 0, None, n,
                                          restrict, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    # Without this the child dies in DLL init (0xC0000142, measured): the default DACL for the child's own process,
    # thread and section objects does not name a restricting SID, so the write-restricted check on them fails.
    user_buf = ctypes.create_string_buffer(256)
    if not advapi32.GetTokenInformation(own, TokenUser, user_buf, 256, ctypes.byref(need)):
        raise ctypes.WinError(ctypes.get_last_error())
    user_sid = sid_text(ctypes.cast(user_buf, ctypes.POINTER(SID_AND_ATTRIBUTES))[0].Sid)
    logon_part = f"(A;;GA;;;{sid_text(logon_sid)})" if logon_sid else ""
    sd = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"D:(A;;GA;;;SY)(A;;GA;;;{user_sid})(A;;GA;;;{cap_str}){logon_part}", 1, ctypes.byref(sd), None):
        raise ctypes.WinError(ctypes.get_last_error())
    present, defaulted, dacl = wt.BOOL(), wt.BOOL(), ctypes.c_void_p()
    advapi32.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
    default_dacl = ctypes.c_void_p(dacl.value)
    if not advapi32.SetTokenInformation(token, TokenDefaultDacl, ctypes.byref(default_dacl),
                                        ctypes.sizeof(default_dacl)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel32.LocalFree(sd)

    def run_restricted(command: str, cwd: str, max_procs: int = 0, timeout: float = 30.0):
        job = kernel32.CreateJobObjectW(None, None)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if max_procs:
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = max_procs
        kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                         ctypes.sizeof(info))
        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(si)
        pi = PROCESS_INFORMATION()
        line = ctypes.create_unicode_buffer(command)
        try:
            if not advapi32.CreateProcessAsUserW(token, None, line, None, None, False,
                                                 CREATE_SUSPENDED | CREATE_NO_WINDOW, None, cwd,
                                                 ctypes.byref(si), ctypes.byref(pi)):
                err = ctypes.get_last_error()
                return None, f"CreateProcessAsUserW failed: WinError {err} ({ctypes.FormatError(err).strip()})"
            try:
                if not kernel32.AssignProcessToJobObject(job, pi.hProcess):
                    kernel32.TerminateProcess(pi.hProcess, 1)
                    return None, f"AssignProcessToJobObject failed: {ctypes.get_last_error()}"
                kernel32.ResumeThread(pi.hThread)
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
            kernel32.CloseHandle(job)            # KILL_ON_JOB_CLOSE: anything left in the job dies here

    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    cmd_exe = os.path.join(system32, "cmd.exe")
    curl_exe = os.path.join(system32, "curl.exe")
    root = os.path.join(tempfile.gettempdir(), "synox-research-rt-" + secrets.token_hex(4))
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

    def shell(test: str) -> str:
        return f'"{cmd_exe}" /d /s /c "{test}"'

    def record(key, what, expect, code, note="", extra=""):
        if code is None:
            verdict = "ERROR"
        elif expect == "allow":
            verdict = "PASS" if code == 0 else "FAIL"
        elif expect == "deny":
            verdict = "PASS" if code != 0 else "FAIL"
        else:
            verdict = "INFO"
        results.append({"test": key, "what": what, "expect": expect, "exit_code": code,
                        "note": " ".join(x for x in (note, extra) if x), "verdict": verdict})
        print(f"{key:4s} {verdict:5s} expect={expect:5s} exit={code} {what} {note} {extra}".rstrip())

    try:
        os.makedirs(inside)
        os.makedirs(outside)
        # icacls refuses a SID that does not resolve to a name (rc 1332, measured), so use .NET via PowerShell.
        ps = (f"$a = Get-Acl -LiteralPath '{inside}'; "
              f"$s = New-Object System.Security.Principal.SecurityIdentifier '{cap_str}'; "
              "$r = New-Object System.Security.AccessControl.FileSystemAccessRule($s, 'Modify', "
              "'ContainerInherit,ObjectInherit', 'None', 'Allow'); $a.AddAccessRule($r); "
              f"Set-Acl -LiteralPath '{inside}' -AclObject $a")
        acl = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True)
        for folder, text in ((inside, "inside-canary\n"), (outside, "outside-canary\n")):
            with open(os.path.join(folder, "canary.txt"), "w", encoding="ascii") as f:
                f.write(text)
        print(f"scratch: {root}\nrestricting SIDs: {', '.join(restricting)}, logon SID {'found' if logon_sid else 'NOT found'}"
              f"\nicacls rc={acl.returncode}\nloopback listener: 127.0.0.1:{port}\n")
        out = os.path.join(inside, "out.txt")

        code, note = run_restricted(shell(f'echo written> "{os.path.join(inside, "w.txt")}"'), inside)
        made = os.path.isfile(os.path.join(inside, "w.txt"))
        record("R1", "write a file in the granted folder", "allow", code if made or code is None else 1, note,
               f"file exists={made}")
        code, note = run_restricted(shell(f'echo x> "{os.path.join(outside, "w.txt")}"'), inside)
        leaked = os.path.isfile(os.path.join(outside, "w.txt"))
        record("R2", "write a file in a folder NOT granted", "deny",
               None if code is None else (0 if leaked else (code or 1)), note, f"file exists={leaked}")
        code, note = run_restricted(shell(f'type "{os.path.join(outside, "canary.txt")}" > "{out}" 2>&1'), inside)
        record("R3", "read a file in a folder NOT granted (expected ALLOWED: reads are not restricted)", "allow",
               code, note)
        profile_dir = os.environ.get("USERPROFILE", "")
        # Output goes to a granted file, not NUL: the NUL device's DACL names Everyone, which is not a restricting
        # SID, so "> NUL" itself fails under a write-restricted token (measured).
        code, note = run_restricted(shell(f'dir "{profile_dir}" > "{out}" 2>&1'), inside)
        record("R4", "list the user profile folder (expected ALLOWED; output discarded)", "allow", code, note)
        try:
            os.remove(out)
        except OSError:
            pass
        temp_probe = os.path.join(tempfile.gettempdir(), f"synox-rt-{secrets.token_hex(3)}.txt")
        code, note = run_restricted(shell(f'echo x> "{temp_probe}"'), inside)
        leaked = os.path.isfile(temp_probe)
        if leaked:
            os.remove(temp_probe)
        record("R5", "write into the user's %TEMP% root (not granted)", "deny",
               None if code is None else (0 if leaked else (code or 1)), note, f"file existed={leaked}")
        # Loopback with this Python (it can be READ under a write-restricted token); curl.exe is tried separately.
        connect = "import socket,sys; socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=5).close()"
        before = hits["count"]
        code, note = run_restricted(f'"{sys.executable}" -I -c "{connect}" {port}', inside)
        time.sleep(0.3)
        record("R6", "python: connect to host loopback (expected ALLOWED: network is not restricted)", "allow", code,
               note, f"listener hits={hits['count'] - before}")
        for p in ("11434", "8830"):
            try:
                socket.create_connection(("127.0.0.1", int(p)), timeout=1).close()
            except OSError:
                continue
            code, note = run_restricted(f'"{sys.executable}" -I -c "{connect}" {p}', inside)
            record("R7", f"python: TCP connect to existing host service 127.0.0.1:{p} (expected ALLOWED)", "allow",
                   code, note)
        if os.path.isfile(curl_exe):
            before = hits["count"]
            code, note = run_restricted(f'"{curl_exe}" -s -m 5 -o "{out}" http://127.0.0.1:{port}/', inside)
            time.sleep(0.3)
            record("R8", "System32 curl.exe plain HTTP to loopback (does curl.exe even start?)", "info", code, note,
                   f"listener hits={hits['count'] - before}")
            if "--no-net" not in sys.argv:
                code, note = run_restricted(f'"{curl_exe}" -s -m 15 -o "{out}" https://example.com/', inside)
                record("R9", "System32 curl.exe HTTPS (Schannel) under the restricted token", "info", code, note)
        code, note = run_restricted(shell(f'"{cmd_exe}" /d /c exit 0'), inside, max_procs=1)
        record("J1", "Job ActiveProcessLimit=1: a child process must fail to start", "deny", code, note)
        code, note = run_restricted(shell(f'"{cmd_exe}" /d /c exit 0'), inside, max_procs=0)
        record("J2", "same command without the process limit (control)", "allow", code, note)
    finally:
        stop.set()
        listener.close()
        kernel32.CloseHandle(token)
        kernel32.CloseHandle(own)
        kernel32.LocalFree(cap_sid)
        shutil.rmtree(root, ignore_errors=True)
        print(f"\ncleanup: scratch removed={not os.path.exists(root)}")

    wv = sys.getwindowsversion()
    report = os.path.join(os.path.dirname(os.path.abspath(__file__)), "win_restricted_token_probe_result.json")
    with open(report, "w", encoding="utf-8") as f:
        f.write(redact(json.dumps({"windows": {"major": wv.major, "minor": wv.minor, "build": wv.build},
                                   "python": sys.version, "argv": sys.argv[1:], "results": results},
                                  indent=1, ensure_ascii=False)))
    print(f"result file: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
