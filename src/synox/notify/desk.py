"""
電腦提醒視窗與提醒哨兵的檔案溝通（契約，docs/adr/0029 §3.4）。不開任何網路埠：只有資料夾裡的小檔案與鎖檔。

    data/remind/
      engine.lock          誰在跑提醒引擎（主程式或哨兵）。拿到 OS 的獨占鎖＝我是引擎；內容是 EngineStamp（給人看、給健康檢查）
      yield.request        主程式要哨兵讓位（YieldRequest）。哨兵看到 → 做完這一輪 → 放掉 engine.lock → 刪掉這個檔
      sentinel.lock        哨兵只能有一個（OS 獨占鎖）
      popup.lock           視窗程式只能有一個（OS 獨占鎖）
      desk/to_win/         引擎 → 視窗
        show-<token>.json    要顯示的一張卡（ShowCard）。**引擎寫、引擎刪**（處理掉才刪）；視窗開起來時把現有的全部顯示
        close-<token>.json   要關掉的一張（CloseCard，例如在 Telegram 按了完成）。引擎寫、**視窗處理完刪**
        todos-<uid>.json     待辦清單（TodoList，視窗下半部）。引擎在待辦有變動時整份覆寫；視窗只讀不刪
      desk/from_win/       視窗 → 引擎
        shown-<token>.json   卡片真的出現在螢幕上了（ShownAck）＝desktop 管道的送達確認。視窗寫、**引擎讀完刪**
        act-<token>-<ms>.json 使用者按了（DeskAction）。視窗寫、**引擎讀完刪**

規則：
- 寫檔一律「先寫同資料夾的 .<名字>.tmp，再 os.replace」；讀的人略過 . 開頭與 .tmp 結尾的檔。
- 讀到壞掉的 JSON：記 log（不記內容）、刪掉；不讓一個壞檔卡住整個資料夾。
- token 只有 [0-9A-Za-z_-]（make_token），檔名不含使用者的字。
- 檔案裡的提醒文字是明文、只放在本機 data/ 底下，處理掉就刪（見 ADR 0029 §3.4「隱私」）。
- 視窗每 1 秒看 to_win；引擎每 ≤5 秒看 from_win（POLL_*）。

格式、檔名、純函式是 W0 定的契約；讀寫資料夾（FileSpool）、OS 鎖（FileLock／FileEngineLock）、讓位（request_yield…）、
啟動資料夾（install_autostart）是 W2 的實作，放在本檔後半。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

VERSION = 1
FOLDER = "remind"                         # data/remind
DESK = "desk"
TO_WIN, FROM_WIN = "to_win", "from_win"
ENGINE_LOCK = "engine.lock"
YIELD_REQUEST = "yield.request"
SENTINEL_LOCK = "sentinel.lock"
POPUP_LOCK = "popup.lock"

POLL_WIN_S = 1.0                          # 視窗看 to_win
POLL_ENGINE_S = 5.0                       # 引擎看 from_win（報告的「5 秒內讀到」）
SHOWN_TIMEOUT_S = 60.0                    # 寫了 show 之後這麼久沒有 shown＝desktop 這次 FAILED(no_window)，照 RetryPolicy 重試（重開視窗）
YIELD_WAIT_S = 15.0                       # 主程式送出 yield.request 後最多等這麼久；拿不到鎖就先不跑引擎，下一輪再試
STAMP_STALE_S = 120.0                     # engine.lock 內容的 beat 多久沒更新算「卡住」（健康檢查用；誰是引擎看 OS 鎖，不看這個）

# 視窗上的按鈕（ShowCard.buttons 的值）
BTN_DONE = "done"
BTN_SNOOZE_10 = "snooze:10"
BTN_SNOOZE_60 = "snooze:60"
BTN_SNOOZE_TYPED = "snooze:typed"         # 自己打時間（「15:30」「+2h」「半小時後」「明天 9 點」）
DEFAULT_BUTTONS = (BTN_DONE, BTN_SNOOZE_10, BTN_SNOOZE_60, BTN_SNOOZE_TYPED)

# 誰是引擎
WHO_APP, WHO_SENTINEL = "app", "sentinel"

_TOKEN_OK = re.compile(r"^[0-9A-Za-z_-]{1,96}$")


def make_token(uid: int, rid: int, occurrence: str) -> str:
    """檔名用的代號：<uid>-<rid>-<到點的 YYYYMMDDHHMM>。同一次提醒永遠同一個 token。"""
    stamp = re.sub(r"[^0-9]", "", str(occurrence))[:12]
    return f"{int(uid)}-{int(rid)}-{stamp}"


def token_ok(token: str) -> bool:
    return bool(_TOKEN_OK.match(str(token or "")))


def show_name(token: str) -> str:
    return f"show-{token}.json"


def close_name(token: str) -> str:
    return f"close-{token}.json"


def shown_name(token: str) -> str:
    return f"shown-{token}.json"


def todos_name(uid: int) -> str:
    return f"todos-{int(uid)}.json"


def act_name(token: str, ms: int) -> str:
    return f"act-{token}-{int(ms)}.json"


def is_temp(name: str) -> bool:
    return name.startswith(".") or name.endswith(".tmp")


@dataclass
class ShowCard:
    """引擎 → 視窗：顯示一張提醒卡。待辦（沒有時間的）不寫 show 檔，在 TodoList 裡。"""
    token: str
    uid: int
    rid: int
    occurrence: str                       # ISO
    text: str
    when: str                             # 「今天 00:51」
    late_min: int = 0
    snooze_count: int = 0                 # >0：卡片寫「延後第 N 次之後」
    buttons: List[str] = field(default_factory=lambda: list(DEFAULT_BUTTONS))
    written_at: float = 0.0
    type: str = "show"
    v: int = VERSION


@dataclass
class CloseCard:
    """引擎 → 視窗：關掉這張（在別處處理了、自動收掉）。note 顯示一下再關（例如「✅ 在 Telegram 上做完了」）。"""
    token: str
    reason: str = "done_elsewhere"        # done_elsewhere｜expired｜cancelled
    note: str = ""
    type: str = "close"
    v: int = VERSION


@dataclass
class TodoList:
    """引擎 → 視窗：這個人還沒做的待辦（視窗下半部）。items＝[{"rid": 5, "text": "繳電話費"}]，最多 TODO_SHOW 筆。
    視窗按「完成」寫 DeskAction(action="done", occurrence="")，token 用 make_token(uid, rid, "")。"""
    uid: int
    items: List[Dict[str, Any]] = field(default_factory=list)
    written_at: float = 0.0
    type: str = "todos"
    v: int = VERSION


@dataclass
class ShownAck:
    """視窗 → 引擎：卡片出現在螢幕上了（desktop 的送達確認）。"""
    token: str
    at: float
    type: str = "shown"
    v: int = VERSION


@dataclass
class DeskAction:
    """視窗 → 引擎：使用者按了。until：視窗自己解析得出來就填（ISO）；typed：使用者打的原字。引擎說了算。"""
    token: str
    rid: int
    occurrence: str
    action: str                           # done｜snooze
    at: float
    until: Optional[str] = None
    typed: str = ""
    type: str = "action"
    v: int = VERSION


@dataclass
class EngineStamp:
    """engine.lock 的內容（拿著鎖的那一方每一輪更新 beat）。"""
    who: str                              # app｜sentinel
    pid: int
    since: float
    beat: float
    v: int = VERSION


@dataclass
class YieldRequest:
    pid: int
    at: float
    v: int = VERSION


KINDS = {"show": ShowCard, "close": CloseCard, "todos": TodoList, "shown": ShownAck, "action": DeskAction}
TODO_SHOW = 20


def to_dict(obj) -> Dict[str, Any]:
    return asdict(obj)


def from_dict(data: Dict[str, Any]):
    """依 type 還原成對應的 dataclass；不認得、缺欄位、token 不合規 → ValueError。"""
    cls = KINDS.get(str(data.get("type", "")))
    if cls is None:
        raise ValueError("unknown desk message type")
    names = cls.__dataclass_fields__
    obj = cls(**{k: v for k, v in data.items() if k in names})
    if hasattr(obj, "token") and not token_ok(obj.token):
        raise ValueError("bad token")
    return obj


# ── W2 實作：資料夾與鎖 ───────────────────────────────────────────────

class Spool(Protocol):
    """data/remind/desk 的讀寫（引擎那一邊與視窗那一邊各用一半）。"""

    def put_show(self, card: ShowCard) -> None: ...
    def put_close(self, card: CloseCard) -> None: ...
    def put_todos(self, todos: TodoList) -> None: ...
    def drop_show(self, token: str) -> None: ...
    def take_from_win(self) -> List[Any]:
        """引擎：讀出 from_win 全部（ShownAck／DeskAction），讀完就刪。"""
    def pending_for_win(self) -> List[Any]:
        """視窗：目前 to_win 裡的 show 與 close。"""
    def put_shown(self, ack: ShownAck) -> None: ...
    def put_action(self, act: DeskAction) -> None: ...


class EngineLock(Protocol):
    """data/remind/engine.lock：OS 獨占鎖（Windows msvcrt.locking；其他 fcntl.flock）。程序死掉鎖自動放掉。"""

    def try_acquire(self, who: str) -> bool: ...
    def beat(self) -> None: ...
    def release(self) -> None: ...
    def holder(self) -> Optional[EngineStamp]:
        """讀 stamp（不保證拿著鎖的人還活著；判斷活著要看 try_acquire）。"""


def remind_dir(data_dir: str) -> str:
    return os.path.join(data_dir, FOLDER)


def _write_json(folder: str, name: str, data: Dict[str, Any]) -> str:
    """先寫 .<name>.tmp 再 os.replace（讀的人看不到寫一半的檔）。Windows 上對方剛好在讀時 replace 會失敗：等一下再試。"""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    tmp = os.path.join(folder, f".{name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return path
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)
    return path


def _remove(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        logging.warning("[DESK] cannot remove %s: %s", os.path.basename(path), type(e).__name__)
        return False


class FileSpool:
    """data/remind/desk 的讀寫。引擎那一邊用 put_show／put_close／put_todos／drop_show／take_from_win；
    視窗那一邊用 pending_for_win／todos_for_win／put_shown／put_action／drop_close。"""

    def __init__(self, root: str):
        self.root = root
        self.to_win = os.path.join(root, TO_WIN)
        self.from_win = os.path.join(root, FROM_WIN)

    # ── 共用 ─────────────────────────────────────────────────────────

    def _names(self, folder: str, prefix: str = "") -> List[str]:
        try:
            names = os.listdir(folder)
        except FileNotFoundError:
            return []
        return sorted(n for n in names if not is_temp(n) and n.endswith(".json") and n.startswith(prefix))

    def _read(self, folder: str, name: str):
        """讀一個檔 → dataclass；壞掉的（不是 JSON、type 不認得、token 不合規）記 log（不記內容）、刪掉、回 None。"""
        path = os.path.join(folder, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            return from_dict(data)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as e:
            if isinstance(e, PermissionError):          # 對方正在寫（Windows）：下一輪再讀
                return None
            logging.warning("[DESK] dropping unreadable %s (%s)", name.split("-")[0], type(e).__name__)
            _remove(path)
            return None

    # ── 引擎 → 視窗 ──────────────────────────────────────────────────

    def put_show(self, card: ShowCard) -> None:
        if not card.written_at:
            card.written_at = time.time()
        _write_json(self.to_win, show_name(card.token), to_dict(card))

    def put_close(self, card: CloseCard) -> None:
        _write_json(self.to_win, close_name(card.token), to_dict(card))

    def put_todos(self, todos: TodoList) -> None:
        todos.items = list(todos.items)[:TODO_SHOW]
        if not todos.written_at:
            todos.written_at = time.time()
        _write_json(self.to_win, todos_name(todos.uid), to_dict(todos))

    def drop_show(self, token: str) -> None:
        if token_ok(token):
            _remove(os.path.join(self.to_win, show_name(token)))

    def has_show(self, token: str) -> bool:
        return token_ok(token) and os.path.exists(os.path.join(self.to_win, show_name(token)))

    def take_from_win(self) -> List[Any]:
        out = []
        names = sorted(self._names(self.from_win), key=lambda n: (not n.startswith("shown-"), n))   # 先確認、再處理按了什麼
        for name in names:
            obj = self._read(self.from_win, name)
            if obj is None:
                continue
            if isinstance(obj, (ShownAck, DeskAction)):
                out.append(obj)
            else:
                logging.warning("[DESK] unexpected %s in from_win", type(obj).__name__)
            _remove(os.path.join(self.from_win, name))
        return out

    # ── 視窗那一邊 ───────────────────────────────────────────────────

    def pending_for_win(self) -> List[Any]:
        out = []
        for name in self._names(self.to_win):
            if not (name.startswith("show-") or name.startswith("close-")):
                continue
            obj = self._read(self.to_win, name)
            if isinstance(obj, (ShowCard, CloseCard)):
                out.append(obj)
        return out

    def todos_for_win(self, uid: Optional[int] = None) -> List[TodoList]:
        out = []
        for name in self._names(self.to_win, "todos-"):
            obj = self._read(self.to_win, name)
            if isinstance(obj, TodoList) and (uid is None or int(obj.uid) == int(uid)):
                out.append(obj)
        return out

    def drop_close(self, token: str) -> None:
        if token_ok(token):
            _remove(os.path.join(self.to_win, close_name(token)))

    def put_shown(self, ack: ShownAck) -> None:
        _write_json(self.from_win, shown_name(ack.token), to_dict(ack))

    def put_action(self, act: DeskAction) -> None:
        _write_json(self.from_win, act_name(act.token, int(act.at * 1000) if act.at else now_ms()), to_dict(act))


def spool_at(data_dir: str) -> FileSpool:
    return FileSpool(os.path.join(remind_dir(data_dir), DESK))


# ── OS 獨占鎖（程序死掉，作業系統自動放掉）──────────────────────────────

_LOCK_OFFSET = 1 << 20          # Windows 鎖的是「檔案裡某一段」：鎖遠處的一個位元組，前面的 stamp 別人還讀得到
_STAMP_WIDTH = 256              # stamp 固定寬度覆寫（不 truncate），後面補空白


class FileLock:
    """一個檔一把鎖：同一時間只有一個 handle 拿得到（同一個程序開兩個也一樣）。Windows msvcrt.locking；其他 fcntl.flock。"""

    def __init__(self, path: str):
        self.path = path
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def try_acquire(self) -> bool:
        if self._fd is not None:
            return True
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if sys.platform == "win32":
                import msvcrt
                os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _write_head(self, data: Dict[str, Any]) -> None:
        if self._fd is None:
            return
        raw = json.dumps(data).encode("utf-8")[:_STAMP_WIDTH]
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, raw + b" " * (_STAMP_WIDTH - len(raw)))

    def free(self) -> bool:
        """現在沒有人拿著嗎（試拿一下馬上放；給「視窗程式開著沒」這種判斷用）。"""
        if self.held:
            return False
        probe = FileLock(self.path)
        if probe.try_acquire():
            probe.release()
            return True
        return False


class FileEngineLock(FileLock):
    """data/remind/engine.lock：拿到＝我是提醒引擎；檔頭是 EngineStamp（who、pid、since、beat）。"""

    def __init__(self, path: str, clock=time.time):
        super().__init__(path)
        self.clock = clock
        self.stamp: Optional[EngineStamp] = None

    def try_acquire(self, who: str = WHO_APP) -> bool:            # type: ignore[override]
        if self.held:
            return True
        if not super().try_acquire():
            return False
        now = self.clock()
        self.stamp = EngineStamp(who=who, pid=os.getpid(), since=now, beat=now)
        self._write_stamp()
        return True

    def _write_stamp(self) -> None:
        try:
            self._write_head(asdict(self.stamp))
        except OSError as e:
            logging.warning("[DESK] cannot write engine stamp: %s", type(e).__name__)

    def beat(self) -> None:
        if self.held and self.stamp is not None:
            self.stamp.beat = self.clock()
            self._write_stamp()

    def release(self) -> None:
        self.stamp = None
        super().release()

    def holder(self) -> Optional[EngineStamp]:
        try:
            with open(self.path, "rb") as f:
                raw = f.read(_STAMP_WIDTH).strip(b" \x00\r\n")
            data = json.loads(raw.decode("utf-8")) if raw else None
            if not isinstance(data, dict):
                return None
            return EngineStamp(**{k: v for k, v in data.items() if k in EngineStamp.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return None


def engine_lock_at(data_dir: str) -> FileEngineLock:
    return FileEngineLock(os.path.join(remind_dir(data_dir), ENGINE_LOCK))


def sentinel_lock_at(data_dir: str) -> FileLock:
    return FileLock(os.path.join(remind_dir(data_dir), SENTINEL_LOCK))


def popup_lock_at(data_dir: str) -> FileLock:
    return FileLock(os.path.join(remind_dir(data_dir), POPUP_LOCK))


# ── 讓位：主程式 → 哨兵 ─────────────────────────────────────────────────

def request_yield(data_dir: str, pid: Optional[int] = None, at: Optional[float] = None) -> str:
    req = YieldRequest(pid=int(pid if pid is not None else os.getpid()), at=float(at if at is not None else time.time()))
    return _write_json(remind_dir(data_dir), YIELD_REQUEST, asdict(req))


def yield_requested(data_dir: str) -> Optional[YieldRequest]:
    path = os.path.join(remind_dir(data_dir), YIELD_REQUEST)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return YieldRequest(**{k: v for k, v in data.items() if k in YieldRequest.__dataclass_fields__})
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, AttributeError):
        return YieldRequest(pid=0, at=0.0)          # 壞掉的也算「有人要你讓」：寧可讓


def clear_yield(data_dir: str) -> None:
    _remove(os.path.join(remind_dir(data_dir), YIELD_REQUEST))


# ── 提醒哨兵的開機啟動（只在這個使用者帳號、不用管理員）──────────────────
#
# 跟精靈的「開機自動啟動」同一個地方（wizard.shortcuts.startup_dir()：使用者的「啟動」資料夾），放一個
# SENTINEL_STARTUP_NAME + ".cmd"，內容是用 pythonw 跑 `python -m synox sentinel`（不跳黑窗）。
# 測試一律傳假的 folder（tmp_path），**不准**在開發機真的寫進啟動資料夾或登錄。

SENTINEL_STARTUP_NAME = "SYNOX-remind-sentinel"


def _cmd_quote(arg: str) -> str:
    arg = str(arg)
    if arg and not any(c in arg for c in ' \t"&|<>^()%'):
        return arg
    return '"' + arg.replace('"', '""') + '"'


def autostart_text(command: List[str], cwd: str = "") -> str:
    """啟動檔的內容（CRLF；UTF-8，第一行把主控台切成 UTF-8，中文路徑也能用）。"""
    lines = ["@echo off", "chcp 65001 >nul",
             "rem SYNOX reminder sentinel, created by SYNOX. Delete this file to stop it.",
             'set "PYTHONUTF8=1"', 'set "PYTHONIOENCODING=utf-8"']
    if cwd:
        lines.append(f"cd /d {_cmd_quote(cwd)}")
    lines.append('start "" ' + " ".join(_cmd_quote(c) for c in command))
    return "\r\n".join(lines) + "\r\n"


def autostart_path(folder: str) -> str:
    return os.path.join(folder, SENTINEL_STARTUP_NAME + ".cmd")


def install_autostart(folder: str, command: List[str], cwd: str = "") -> str:
    """在 folder 放啟動檔（回檔案路徑）。已經有了就覆寫成一樣的內容（冪等）。"""
    if not command:
        raise ValueError("command is empty")
    os.makedirs(folder, exist_ok=True)
    path = autostart_path(folder)
    data = autostart_text(command, cwd).encode("utf-8")
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return path
    except OSError:
        pass
    with open(path, "wb") as f:
        f.write(data)
    return path


def remove_autostart(folder: str) -> bool:
    return _remove(autostart_path(folder))


def autostart_installed(folder: str) -> bool:
    return os.path.exists(autostart_path(folder))


def now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


__all__ = ["BTN_DONE", "BTN_SNOOZE_10", "BTN_SNOOZE_60", "BTN_SNOOZE_TYPED", "CloseCard", "DEFAULT_BUTTONS",
           "DeskAction", "ENGINE_LOCK", "EngineLock", "EngineStamp", "FOLDER", "FROM_WIN", "POLL_ENGINE_S",
           "POLL_WIN_S", "POPUP_LOCK", "SENTINEL_LOCK", "SHOWN_TIMEOUT_S", "STAMP_STALE_S", "ShowCard", "ShownAck", "TODO_SHOW", "TodoList",
           "SENTINEL_STARTUP_NAME", "Spool", "TO_WIN", "install_autostart", "remove_autostart", "VERSION", "WHO_APP", "WHO_SENTINEL", "YIELD_REQUEST", "YIELD_WAIT_S", "YieldRequest",
           "act_name", "close_name", "engine_lock_at", "from_dict", "is_temp", "make_token", "show_name",
           "shown_name", "spool_at", "to_dict", "todos_name", "token_ok",
           # W2 的實作（契約之外多的）
           "FileEngineLock", "FileLock", "FileSpool", "autostart_installed", "autostart_path", "autostart_text",
           "clear_yield", "popup_lock_at", "remind_dir", "request_yield", "sentinel_lock_at", "yield_requested"]
