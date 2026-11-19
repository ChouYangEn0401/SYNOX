"""
資料版本的基本功（ADR 0044、docs/data-migrations.md）：版本號放哪裡、怎麼讀、原子寫入、檔案鎖、升級前的備份。

版本號放哪裡（每種檔案各自計，整數，從 1 開始；**沒有版本＝0（legacy）**）：

    JSON（頂層是物件）   頂層的版本鍵：新檔一律 "schema_version"；早就有自己版本鍵的舊檔沿用舊鍵
                         （packs.lock 的 "version"），不改名——改名本身就會讓舊的讀取程式壞掉
    SQLite              PRAGMA user_version
    其他（YAML、純文字、資料夾）  旁檔 <檔名>.schema（JSON：{"schema_version": N}）；或由登記表記（工具的資料夾，packdata.py）

這支檔案不知道任何一種資料的內容；遷移步驟與「從幾版跑到幾版」在 migrate.py。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from typing import Any, List, Optional

LEGACY = 0                       # 沒有版本欄位的舊檔
DEFAULT_KEY = "schema_version"
SIDECAR_SUFFIX = ".schema"
LOCK_SUFFIX = ".migrate.lock"
BACKUP_DIR = "_migration_backups"  # 放在資料檔旁邊：data/_migration_backups/、data/users/<id>/_migration_backups/
KEEP_BACKUPS = 3                   # 每個檔留最近幾份升級前備份（ADR 0044 §安全措施；待擁有者確認）
LOCK_WAIT_S = 30.0                 # 等別的程序升級完最多幾秒
LOCK_STALE_S = 600.0               # 鎖檔超過這麼久、而且寫鎖的程序已經不在＝留下來的殘骸，可以清
_REPLACE_RETRIES = 5


class DataError(Exception):
    """資料版本的問題。訊息是給人看的（白話、不含內部詞）。"""


class TooNewError(DataError):
    """檔案是比這支程式新的版本寫的：不讀成舊格式、不寫、不動檔案。"""


class GapError(DataError):
    """從檔案的版本到目前版本，中間少了遷移步驟：拒絕，不跳過。"""


class StepError(DataError):
    """某一個遷移步驟失敗（已還原，原資料沒動）。"""


class BusyError(DataError):
    """另一個程序正在升級同一份資料，等太久。"""


def too_new_text(what: str, found: int, supported: int) -> str:
    return (f"{what} 是較新版本寫的（資料版本 {found}，這一版只認得到 {supported}）。"
            "為了不弄壞它，這次不讀寫、不動這份資料。請升級 SYNOX 或這個工具，或從備份還原。")


# ── 版本號 ─────────────────────────────────────────────────────────────

def check_version(value: Any, where: str = "資料") -> int:
    """版本值要是 ≥ 0 的整數（布林、字串、小數都不算）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataError(f"{where} 的版本號看不懂（{value!r}）：要是 0 以上的整數。")
    return value


def json_version(data: Any, key: str = DEFAULT_KEY, where: str = "資料") -> int:
    """JSON 物件的版本；沒有這個鍵＝0。頂層不是物件丟 DataError（放不了版本號）。"""
    if not isinstance(data, dict):
        raise DataError(f"{where} 最外層不是 {{…}} 物件，放不了版本號。")
    if key not in data:
        return LEGACY
    return check_version(data[key], where)


def sidecar_path(path: str) -> str:
    return path + SIDECAR_SUFFIX


def sidecar_version(path: str) -> int:
    """旁檔 <path>.schema 的版本；沒有旁檔＝0。"""
    side = sidecar_path(path)
    if not os.path.exists(side):
        return LEGACY
    try:
        with open(side, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise DataError(f"{os.path.basename(side)} 讀不了（{e}）。")
    return json_version(data, DEFAULT_KEY, os.path.basename(side))


def write_sidecar(path: str, version: int) -> None:
    atomic_write_bytes(sidecar_path(path), json.dumps({DEFAULT_KEY: check_version(version)}).encode("utf-8") + b"\n")


def sqlite_version(conn) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


# ── 原子寫入 ───────────────────────────────────────────────────────────

def atomic_write_bytes(path: str, blob: bytes) -> None:
    """寫到同一個資料夾的暫存檔、flush＋fsync，再 os.replace 蓋過去：任何時候中斷，原檔不是舊的就是新的，
    不會只寫一半。失敗時暫存檔清掉。"""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:           # Windows：別的程式剛好開著這個檔（防毒、備份），稍等再試
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ── 檔案鎖（跨程序） ───────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259                              # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class FileLock:
    """<path>.migrate.lock：用 O_CREAT|O_EXCL 建檔當鎖（Windows／Linux 都是原子的）。同一時間只有一個程序升級同一份資料；
    另一個等（最多 wait 秒），拿到鎖後呼叫的人要**重讀版本**——通常已經被前一個升好了，什麼都不用做。
    鎖檔放超過 LOCK_STALE_S 而且寫鎖的程序已經不在＝殘骸，清掉再拿。"""

    def __init__(self, path: str, wait: float = LOCK_WAIT_S, poll: float = 0.05):
        self.path = path + LOCK_SUFFIX
        self.wait = wait
        self.poll = poll
        self._fd: Optional[int] = None

    def _stale(self) -> bool:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                info = json.load(f)
            pid, at = int(info.get("pid", 0)), float(info.get("at", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            try:
                at = os.path.getmtime(self.path)
            except OSError:
                return False
            pid = 0
        return time.time() - at > LOCK_STALE_S and not _pid_alive(pid)

    def acquire(self) -> None:
        deadline = time.monotonic() + max(0.0, self.wait)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._stale():
                    try:
                        os.remove(self.path)
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise BusyError(f"另一個程序正在升級 {os.path.basename(self.path[:-len(LOCK_SUFFIX)])}，"
                                    "等太久了，這次先不動它（稍後再開一次 SYNOX，或跑 python -m synox data status 看看）。")
                time.sleep(self.poll)
                continue
            os.write(fd, json.dumps({"pid": os.getpid(), "at": time.time()}).encode("ascii"))
            self._fd = fd
            return

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
                try:
                    os.remove(self.path)
                except OSError:
                    pass

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# ── 升級前備份 ─────────────────────────────────────────────────────────

_STAMP_RE = re.compile(r"\.v(\d+)\.(\d{8}-\d{6})(?:-(\d+))?\.bak$")


def backup_root(path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(path)), BACKUP_DIR)


def _stamp(now: Optional[float]) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(now))


def backups_of(path: str) -> List[str]:
    """這個檔（或資料夾）的升級前備份，新的在前。"""
    root = backup_root(path)
    base = os.path.basename(os.path.abspath(path))
    if not os.path.isdir(root):
        return []
    found = []
    for name in os.listdir(root):
        if not name.startswith(base + ".v"):
            continue
        m = _STAMP_RE.search(name)
        if m and name[:m.start()] == base:
            found.append((m.group(2), int(m.group(3) or 1), os.path.join(root, name)))
    found.sort(reverse=True)
    return [p for _s, _n, p in found]


def make_backup(path: str, version: int, *, keep: int = KEEP_BACKUPS, now: Optional[float] = None) -> str:
    """升級前把原檔（或整個資料夾）照原樣複製一份：<資料夾>/_migration_backups/<檔名>.v<升級前版本>.<時間>.bak。
    一次升級（不管跨幾版）只備份一份「升級前」的；超過 keep 份的舊備份刪掉。回備份的路徑。"""
    root = backup_root(path)
    os.makedirs(root, exist_ok=True)
    base = f"{os.path.basename(os.path.abspath(path))}.v{int(version)}.{_stamp(now)}"
    dest, n = os.path.join(root, base + ".bak"), 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(root, f"{base}-{n}.bak")
    if os.path.isdir(path):
        shutil.copytree(path, dest)
    else:
        tmp = dest + ".partial"
        shutil.copy2(path, tmp)
        os.replace(tmp, dest)
    prune_backups(path, keep)
    return dest


def prune_backups(path: str, keep: int = KEEP_BACKUPS) -> List[str]:
    """只留最新的 keep 份；回刪掉的。keep ≤ 0＝不刪。"""
    if keep <= 0:
        return []
    removed = []
    for old in backups_of(path)[keep:]:
        try:
            if os.path.isdir(old):
                shutil.rmtree(old)
            else:
                os.remove(old)
            removed.append(old)
        except OSError:
            pass
    return removed


def restore_backup(backup: str, path: str) -> None:
    """備份放回原位（檔案：原子取代；資料夾：整個換掉）。"""
    if os.path.isdir(backup):
        aside = path + ".failed-migration"
        if os.path.exists(aside):
            shutil.rmtree(aside, ignore_errors=True)
        if os.path.exists(path):
            os.replace(path, aside)
        shutil.copytree(backup, path)
        shutil.rmtree(aside, ignore_errors=True)
        return
    with open(backup, "rb") as f:
        atomic_write_bytes(path, f.read())
