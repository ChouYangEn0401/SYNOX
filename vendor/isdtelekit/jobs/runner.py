"""
JobRunner — bot 啟動的每一個外部程式都經過這裡（從 ClawBot 的 core/jobs.py 搬過來，邏輯沒改）。

- 指令一律是 argv 陣列（.bat / cmd 字串就明寫 ["cmd", "/c", ...]），不經 shell 字串。
- 不開視窗；stdout/stderr 併進一個 log 檔，stdin 接 DEVNULL（.bat 結尾的 pause 讀到 EOF 就過）。
- Windows 上每個 job 放進自己的 Job Object：逾時或取消（packs/jobs_admin.py 的 /sys_job_cancel）時整棵樹
  （含 .bat 底下的孫程序）一起收掉。
  survive_bot=False（預設）時再加 KILL_ON_JOB_CLOSE：bot 結束，子程序跟著結束，不留孤兒。
  要跑很久、不該因為重啟 bot 就被砍的（例如每天一次的批次），用 survive_bot=True。
- 每個 job 有 id 和具名狀態：running → succeeded / failed / timed_out / cancelled。
- 有 deadline 的 job（要能加時、要活過 bot 重啟的長時間服務）由一條監看執行緒輪詢：
  到期前 warn_before 秒呼叫一次 on_warn，到期就整棵樹收掉（狀態 timed_out）；extend() 把 deadline 往後推。
- adopt()：bot 重啟後，用「pid＋建立時間」把上一個 bot 留下的 survive_bot 程式接回來。pid 會被別的程式
  重用，所以建立時間對不上就當作已經結束；接回之後握著它的 handle，pid 就不可能再被重用。收掉接回的程式
  只能用 taskkill /PID <pid> /T /F（原本的 Job Object handle 跟著舊的 bot 一起沒了，具名 Job Object
  的做法實測不可行，不要再試）。
"""

from __future__ import annotations

import itertools
import locale
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence

LOG_ROOT = "data/job_logs"
LOG_KEEP_DAYS = 30
_HISTORY = 50

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
TIMED_OUT = "timed_out"
CANCELLED = "cancelled"
STATE_LABELS = {RUNNING: "執行中", SUCCEEDED: "成功", FAILED: "失敗",
                TIMED_OUT: "逾時被終止", CANCELLED: "已取消"}


def child_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """輸出導到檔案時，Windows 的 Python 會改用 cp950 寫 stdout，中文會亂碼或直接 UnicodeEncodeError。
    PYTHONIOENCODING 只影響 stdin/stdout/stderr，不會改子程式讀寫資料檔的編碼。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def read_log(path: str) -> str:
    """同一批子程序的編碼不一定一致：有 chcp 65001 的 .bat 與 python 子程序寫 UTF-8（cmd 還會多一個
    BOM），沒有 chcp 的 cmd 輸出是系統 OEM 編碼（這台是 cp950）。先試 UTF-8 再退回地區編碼；
    反過來試會把 UTF-8 當 Big5 讀成亂碼而且不報錯。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    for enc in ("utf-8-sig", locale.getpreferredencoding(False)):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_") or "job"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimit),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _ntdll = ctypes.WinDLL("ntdll")
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long

    _KILL_ON_JOB_CLOSE = 0x2000
    _EXTENDED_LIMIT_INFORMATION = 9
    _CREATE_SUSPENDED = 0x00000004
    # survive_bot 的程式要能脫離 bot 自己所在的 job（例如從某些終端機啟動時，終端機把 bot 放進一個
    # 「關掉就全殺」的 job）。那個 job 不允許脫離時 CreateProcess 會回 ERROR_ACCESS_DENIED，就退回不帶。
    _CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    _QUERY = 0x1000          # PROCESS_QUERY_LIMITED_INFORMATION
    _SYNCHRONIZE = 0x00100000
    _STILL_ACTIVE = 259
    _INFINITE = 0xFFFFFFFF

    def _created_of(handle) -> Optional[int]:
        """行程的建立時間（FILETIME，100ns 為單位的整數）——跟 pid 一起才認得出「同一支程式」。"""
        times = [ctypes.c_ulonglong() for _ in range(4)]
        if not _kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        return int(times[0].value)

    def _still_active(handle) -> bool:
        code = wintypes.DWORD()
        return bool(_kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == _STILL_ACTIVE

    def process_created(pid: int) -> Optional[int]:
        """這個 pid 現在那支程式的建立時間；程式不在了（或打不開）回 None。"""
        handle = _kernel32.OpenProcess(_QUERY, False, int(pid))
        if not handle:
            return None
        try:
            return _created_of(handle) if _still_active(handle) else None
        finally:
            _kernel32.CloseHandle(handle)

    def kill_tree(pid: int) -> bool:
        """taskkill /PID <pid> /T /F：連子孫一起收掉。接回來的程式只能用這個（沒有 Job Object handle）。"""
        try:
            done = subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError:
            return False
        return done.returncode == 0
else:
    def process_created(pid: int) -> Optional[int]:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return None
        return 0

    def kill_tree(pid: int) -> bool:
        try:
            os.killpg(int(pid), 9)  # type: ignore[attr-defined]
            return True
        except OSError:
            return False


if sys.platform == "win32":

    class _WinJob:
        def __init__(self, kill_on_close: bool) -> None:
            self.handle = _kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            if kill_on_close:
                info = _ExtendedLimit()
                info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
                if not _kernel32.SetInformationJobObject(self.handle, _EXTENDED_LIMIT_INFORMATION,
                                                         ctypes.byref(info), ctypes.sizeof(info)):
                    err = ctypes.get_last_error()
                    _kernel32.CloseHandle(self.handle)
                    raise OSError(err, "SetInformationJobObject failed")

        def adopt(self, process: subprocess.Popen) -> None:
            """Process was started suspended: put it in the job, then let it run, so it cannot
            spawn a grandchild outside the job first."""
            handle = int(process._handle)  # type: ignore[attr-defined]
            if not _kernel32.AssignProcessToJobObject(self.handle, handle) or _ntdll.NtResumeProcess(handle) != 0:
                err = ctypes.get_last_error()
                process.kill()
                self.close()
                raise OSError(err or 1, "could not start the child inside a job object")

        def terminate(self) -> None:
            if self.handle:
                _kernel32.TerminateJobObject(self.handle, 1)

        def close(self) -> None:
            handle, self.handle = self.handle, None
            if handle:
                _kernel32.CloseHandle(handle)


@dataclass
class Job:
    id: str
    name: str
    argv: List[str]
    cwd: str
    log_path: str
    timeout: Optional[float]
    started_at: datetime
    state: str = RUNNING
    returncode: Optional[int] = None
    finished_at: Optional[datetime] = None
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    pid: Optional[int] = None
    created: Optional[int] = None          # 行程建立時間（FILETIME）；跟 pid 一起才能在重啟後認回它
    deadline: Optional[datetime] = None    # 有值就由監看執行緒管：到期收掉，extend() 可以往後推
    warn_before: float = 0.0               # 到期前幾秒呼叫 on_warn（0＝不提醒）
    warned: bool = False
    adopted: bool = False                  # 上一個 bot 開的、這個 bot 用 adopt() 接回來的

    @property
    def output(self) -> str:
        return read_log(self.log_path)

    @property
    def remaining(self) -> Optional[timedelta]:
        if self.deadline is None:
            return None
        return max(self.deadline - datetime.now(), timedelta(0))

    def tail(self, lines: int = 15) -> str:
        return "\n".join(self.output.strip().splitlines()[-lines:])

    def summary(self) -> str:
        took = (self.finished_at or datetime.now()) - self.started_at
        mins = int(took.total_seconds() // 60)
        rc = f"，代碼 {self.returncode}" if self.returncode not in (None, 0) else ""
        mark = "（接回）" if self.adopted else ""
        return f"#{self.id} {self.name}{mark}：{STATE_LABELS[self.state]}{rc}（{mins} 分鐘）"


class JobRunner:

    def __init__(self, log_root: str = LOG_ROOT, poll_seconds: float = 10.0,
                 clock: Callable[[], datetime] = datetime.now):
        self._log_root = log_root
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}
        self._handles: Dict[str, tuple] = {}   # id -> (Popen, win job | None)；adopt() 的是 (None, None)
        self._cancelled: set = set()
        self._expired: set = set()             # 到 deadline 被收掉的（狀態記成 timed_out）
        self._warn_callbacks: Dict[str, Callable[[Job], None]] = {}
        self._poll = poll_seconds
        self._now = clock
        self._monitor: Optional[threading.Thread] = None
        self._listeners: List[Callable[[Job], None]] = []   # 任何工作結束都通知（例如「等這個工作做完」）
        self._prune_logs()

    def add_listener(self, listener: Callable[[Job], None]) -> None:
        """listener(job) 會在每一個工作結束時被呼叫（在 on_done 之後）。"""
        self._listeners.append(listener)

    def start(self, name: str, argv: Sequence[str], *, cwd: Optional[str] = None,
              timeout: Optional[float] = None, env: Optional[Dict[str, str]] = None,
              survive_bot: bool = False, log_path: Optional[str] = None, console: bool = False,
              on_done: Optional[Callable[[Job], None]] = None, input_text: Optional[str] = None,
              deadline: Optional[datetime] = None, warn_before: float = 0.0,
              on_warn: Optional[Callable[[Job], None]] = None) -> Job:
        """Start argv in the background. Raises OSError if it cannot start.

        deadline：到這個時間就整棵樹收掉（可以用 extend() 往後推，timeout 不行）；warn_before 秒前先呼叫
        on_warn(job) 一次。survive_bot=True：bot 結束時不跟著結束，而且會試著脫離 bot 自己所在的 job。

        console=True（只有 Windows）：開一個自己的主控台視窗、輸出留在視窗裡不進 log。給一定要有
        真的終端機才肯跑的互動程式用（ClawBot 實測：有些程式的第一次確認提示，用 input_text 餵不進去）。
        Job Object、逾時、取消照舊。

        input_text：background 模式下餵進子程序的 stdin（不是真的終端機，但管線輸入收得到）；
        給那種不需要真人互動、只是「跑之前先問一句 y/n」的提示用，或是用 stdin 收一包 JSON 的程式。
        console=True 時 stdin 接的是那個視窗自己的鍵盤，這個參數不會生效。"""
        if isinstance(argv, (str, bytes)):
            raise TypeError("argv must be a list, never a shell string")
        argv = [str(a) for a in argv]
        job_id = str(next(self._ids))
        now = datetime.now()
        if log_path is None:
            day_dir = os.path.join(self._log_root, now.strftime("%Y-%m-%d"))
            log_path = os.path.join(day_dir, f"{now:%H%M%S}_{job_id}_{safe_name(name)}.log")
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        job = Job(job_id, name, argv, cwd or os.getcwd(), log_path, timeout, now,
                  deadline=deadline, warn_before=warn_before)

        console = console and sys.platform == "win32"
        with open(log_path, "wb") as log:
            stdin = subprocess.PIPE if (input_text is not None and not console) else subprocess.DEVNULL
            kwargs = dict(cwd=cwd, env=env or child_env(), stdin=stdin,
                          stdout=log, stderr=subprocess.STDOUT, shell=False)
            if console:
                log.write("（這個工作開在自己的主控台視窗，輸出不在這個 log 裡）\n".encode("utf-8"))
                kwargs.update(stdin=None, stdout=None, stderr=None)
            win_job = None
            if sys.platform == "win32":
                window = subprocess.CREATE_NEW_CONSOLE if console else subprocess.CREATE_NO_WINDOW
                flags = window | _CREATE_SUSPENDED
                win_job = _WinJob(kill_on_close=not survive_bot)
                try:
                    try:
                        kwargs["creationflags"] = flags | (_CREATE_BREAKAWAY_FROM_JOB if survive_bot else 0)
                        process = subprocess.Popen(argv, **kwargs)
                    except PermissionError:
                        if not survive_bot:
                            raise
                        # bot 所在的 job 不准脫離：照樣開，只是 bot 那個 job 被關時它可能會被帶走
                        logging.warning("[JOBS] %s: cannot break away from the bot's job; starting inside it", name)
                        kwargs["creationflags"] = flags
                        process = subprocess.Popen(argv, **kwargs)
                except BaseException:
                    win_job.close()
                    raise
                win_job.adopt(process)
                job.created = _created_of(int(process._handle))  # type: ignore[attr-defined]
            else:
                kwargs["start_new_session"] = True
                process = subprocess.Popen(argv, **kwargs)
            if stdin == subprocess.PIPE:
                try:
                    process.stdin.write(input_text.encode("utf-8"))
                    process.stdin.close()
                except OSError:
                    pass

        job.pid = process.pid
        with self._lock:
            self._jobs[job_id] = job
            self._handles[job_id] = (process, win_job)
            self._trim_history()
        logging.info("[JOBS] #%s %s started: %s", job_id, name, argv)
        threading.Thread(target=self._watch, args=(job, on_done), daemon=True,
                         name=f"Job-{job_id}").start()
        if deadline is not None:
            self._track(job, on_warn)
        return job

    def adopt(self, name: str, pid: int, created: Optional[int], log_path: str, *,
              started_at: datetime, argv: Sequence[str] = (), cwd: str = "",
              deadline: Optional[datetime] = None, warn_before: float = 0.0, warned: bool = False,
              on_warn: Optional[Callable[[Job], None]] = None,
              on_done: Optional[Callable[[Job], None]] = None) -> Optional[Job]:
        """把上一個 bot 留下來、還在跑的程式接回來。pid＋建立時間都對得上才算同一支程式（pid 會被
        別的程式重用）；對不上或已經結束就回 None。接回之後握著 handle，結束時一樣呼叫 on_done。"""
        handle = None
        if sys.platform == "win32":
            handle = _kernel32.OpenProcess(_SYNCHRONIZE | _QUERY, False, int(pid))
            if not handle:
                return None
            if not _still_active(handle) or (created is not None and _created_of(handle) != int(created)):
                _kernel32.CloseHandle(handle)
                return None
        elif process_created(pid) is None:
            return None
        job_id = str(next(self._ids))
        job = Job(job_id, name, [str(a) for a in argv], cwd, log_path, None, started_at,
                  pid=int(pid), created=created, deadline=deadline, warn_before=warn_before,
                  warned=warned, adopted=True)
        with self._lock:
            self._jobs[job_id] = job
            self._handles[job_id] = (None, None)
            self._trim_history()
        logging.info("[JOBS] #%s %s adopted: pid %s", job_id, name, pid)
        threading.Thread(target=self._watch_adopted, args=(job, handle, on_done), daemon=True,
                         name=f"Job-{job_id}").start()
        if deadline is not None:
            self._track(job, on_warn)
        return job

    def extend(self, job_id: str, seconds: float) -> Optional[datetime]:
        """deadline 往後推（累加在現在的 deadline 上，不是從現在重算）。回傳新的 deadline。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state != RUNNING or job.deadline is None:
                return None
            job.deadline = job.deadline + timedelta(seconds=seconds)
            job.warned = False
            return job.deadline

    def run(self, name: str, argv: Sequence[str], **kwargs) -> Job:
        """start() and wait for it. Only call this from a thread that is allowed to block."""
        job = self.start(name, argv, **kwargs)
        job.done.wait()
        return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._handles:
                return False
            self._cancelled.add(job_id)
            process, win_job = self._handles[job_id]
            job = self._jobs[job_id]
        self._stop(job, process, win_job)
        return True

    def _stop(self, job: Job, process, win_job) -> None:
        if process is not None:
            self._kill(process, win_job)
        if job.pid and process_created(job.pid) is not None:
            kill_tree(job.pid)   # 接回來的（沒有 Job Object handle），或 Job Object 漏掉的子孫

    # ── deadlines（監看執行緒） ─────────────────────────────────────────

    def _track(self, job: Job, on_warn: Optional[Callable[[Job], None]]) -> None:
        with self._lock:
            if on_warn is not None:
                self._warn_callbacks[job.id] = on_warn
            if self._monitor is None or not self._monitor.is_alive():
                self._monitor = threading.Thread(target=self._monitor_loop, daemon=True, name="JobDeadlines")
                self._monitor.start()

    def _monitor_loop(self) -> None:
        while True:
            time.sleep(self._poll)
            try:
                self.check_deadlines()
            except Exception:
                logging.exception("[JOBS] deadline check failed")

    def check_deadlines(self) -> None:
        """到期前提醒一次、到期收掉。監看執行緒每 poll_seconds 秒呼叫一次（測試可以直接呼叫）。"""
        now = self._now()
        with self._lock:
            due = [j for j in self._jobs.values() if j.state == RUNNING and j.deadline is not None]
        for job in due:
            if now >= job.deadline:
                with self._lock:
                    if job.id not in self._handles:
                        continue
                    self._expired.add(job.id)
                    process, win_job = self._handles[job.id]
                logging.info("[JOBS] #%s %s reached its deadline", job.id, job.name)
                self._stop(job, process, win_job)
            elif job.warn_before and not job.warned and now >= job.deadline - timedelta(seconds=job.warn_before):
                job.warned = True
                callback = self._warn_callbacks.get(job.id)
                if callback:
                    try:
                        callback(job)
                    except Exception:
                        logging.exception("[JOBS] on_warn for #%s failed", job.id)

    def list(self) -> List[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(jobs, key=lambda j: (j.state != RUNNING, -j.started_at.timestamp()))

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def _watch(self, job: Job, on_done: Optional[Callable[[Job], None]]) -> None:
        process, win_job = self._handles[job.id]
        state = None
        try:
            rc = process.wait(timeout=job.timeout)
        except subprocess.TimeoutExpired:
            self._kill(process, win_job)
            rc, state = process.returncode, TIMED_OUT
        if win_job:
            win_job.close()
        self._finish(job, rc, state, on_done)

    def _watch_adopted(self, job: Job, handle, on_done: Optional[Callable[[Job], None]]) -> None:
        rc = None
        if handle is not None:
            _kernel32.WaitForSingleObject(handle, _INFINITE)
            code = wintypes.DWORD()
            if _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                rc = int(code.value)
            _kernel32.CloseHandle(handle)
        else:
            while process_created(job.pid) is not None:
                time.sleep(1)
        self._finish(job, rc, None, on_done)

    def _finish(self, job: Job, rc: Optional[int], state: Optional[str],
                on_done: Optional[Callable[[Job], None]]) -> None:
        with self._lock:
            self._handles.pop(job.id, None)
            self._warn_callbacks.pop(job.id, None)
            cancelled = job.id in self._cancelled
            expired = job.id in self._expired
            self._cancelled.discard(job.id)
            self._expired.discard(job.id)
        job.returncode = rc
        job.finished_at = datetime.now()
        if state is None:
            state = (TIMED_OUT if expired else CANCELLED if cancelled
                     else SUCCEEDED if rc == 0 else FAILED)
        job.state = state
        logging.info("[JOBS] %s", job.summary())
        job.done.set()
        if on_done:
            try:
                on_done(job)
            except Exception:
                logging.exception("[JOBS] on_done for #%s failed", job.id)
        for listener in list(self._listeners):
            try:
                listener(job)
            except Exception:
                logging.exception("[JOBS] listener for #%s failed", job.id)

    @staticmethod
    def _kill(process: subprocess.Popen, win_job) -> None:
        if win_job:
            win_job.terminate()
        elif process.poll() is None:
            try:
                os.killpg(process.pid, 9)  # type: ignore[attr-defined]
            except OSError:
                pass
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logging.error("[JOBS] pid %s did not exit after kill", process.pid)

    def _trim_history(self) -> None:
        finished = [j for j in self._jobs.values() if j.state != RUNNING]
        for j in sorted(finished, key=lambda j: j.started_at)[:max(0, len(self._jobs) - _HISTORY)]:
            del self._jobs[j.id]

    def _prune_logs(self) -> None:
        cutoff = (datetime.now() - timedelta(days=LOG_KEEP_DAYS)).strftime("%Y-%m-%d")
        try:
            for entry in os.listdir(self._log_root):
                if len(entry) == 10 and entry < cutoff:
                    shutil.rmtree(os.path.join(self._log_root, entry), ignore_errors=True)
        except FileNotFoundError:
            pass
