"""
電腦提醒視窗與提醒哨兵的檔案溝通（契約，docs/adr/0028 §3.4）。不開任何網路埠：只有資料夾裡的小檔案與鎖檔。

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
- 檔案裡的提醒文字是明文、只放在本機 data/ 底下，處理掉就刪（見 ADR 0028 §3.4「隱私」）。
- 視窗每 1 秒看 to_win；引擎每 ≤5 秒看 from_win（POLL_*）。

本檔只有格式、檔名、純函式；讀寫資料夾與鎖的類別是 W2 的事（函式本體 NotImplementedError）。
"""

from __future__ import annotations

import re
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


def spool_at(data_dir: str) -> Spool:
    raise NotImplementedError("W2: desk.spool_at")


def engine_lock_at(data_dir: str) -> EngineLock:
    raise NotImplementedError("W2: desk.engine_lock_at")


# ── 提醒哨兵的開機啟動（W2 實作；只在這個使用者帳號、不用管理員）──────────
#
# 跟精靈的「開機自動啟動」同一個地方（wizard.shortcuts.startup_dir()：使用者的「啟動」資料夾），放一個
# SENTINEL_STARTUP_NAME + ".cmd"，內容是用 pythonw 跑 `python -m synox sentinel`（不跳黑窗）。
# 測試一律傳假的 folder（tmp_path），**不准**在開發機真的寫進啟動資料夾或登錄。

SENTINEL_STARTUP_NAME = "SYNOX-remind-sentinel"


def install_autostart(folder: str, command: List[str]) -> str:
    """在 folder 放啟動檔（回檔案路徑）。已經有了就覆寫成一樣的內容（冪等）。"""
    raise NotImplementedError("W2: desk.install_autostart")


def remove_autostart(folder: str) -> bool:
    raise NotImplementedError("W2: desk.remove_autostart")


def now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


__all__ = ["BTN_DONE", "BTN_SNOOZE_10", "BTN_SNOOZE_60", "BTN_SNOOZE_TYPED", "CloseCard", "DEFAULT_BUTTONS",
           "DeskAction", "ENGINE_LOCK", "EngineLock", "EngineStamp", "FOLDER", "FROM_WIN", "POLL_ENGINE_S",
           "POLL_WIN_S", "POPUP_LOCK", "SENTINEL_LOCK", "SHOWN_TIMEOUT_S", "STAMP_STALE_S", "ShowCard", "ShownAck", "TODO_SHOW", "TodoList",
           "SENTINEL_STARTUP_NAME", "Spool", "TO_WIN", "install_autostart", "remove_autostart", "VERSION", "WHO_APP", "WHO_SENTINEL", "YIELD_REQUEST", "YIELD_WAIT_S", "YieldRequest",
           "act_name", "close_name", "engine_lock_at", "from_dict", "is_temp", "make_token", "show_name",
           "shown_name", "spool_at", "to_dict", "todos_name", "token_ok"]
