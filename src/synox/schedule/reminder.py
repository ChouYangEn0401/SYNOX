"""
一筆提醒／待辦的資料格式（契約，docs/adr/0028 §3.1；docs/notifications.md「契約」）。

存在原本的排程清單裡（data/schedule.json(.enc)，伺服器版每人一份），kind 仍是 "remind"；/schedule_* 的
kind="command" 不在這份契約內、格式不變。

    {"v": 2, "id": 3, "kind": "remind", "owner": 123, "text": "倒垃圾", "created": 1763225400,
     "repeat": "once", "due": "2026-11-16T00:51:00+08:00", "status": "pending",
     "occurrence": null, "snooze_until": null, "snooze_count": 0, "deliveries": {},
     "history": [], "source": "command", "done_at": null, "done_via": "",
     "time": "00:51", "date": "2026-11-16", "last_run": "", "command": ""}

- **due**：絕對的到點時間（ISO 8601，帶時區位移）。沒有 due（None）的就是**待辦**（repeat="none"）。
- **repeat**："once"（一次）｜"daily"（每天同一個牆上時間）｜"none"（待辦，沒有時間）。
- **status**：見 STATUSES。每天型的一次結束後回到 "pending"、due 往後推一天，結果記進 history。
- **occurrence**：正在響的那一次原本的到點時間（ISO）；送達紀錄與按鈕都以 (id, occurrence) 認這一次。
- **deliveries**：這一次每個管道的送達紀錄（管道 id → DeliveryRecord 的 dict，見 synox.notify.delivery）。
- **time／date／last_run／command**：舊欄位，**照樣寫**（由 due 推出來），讓舊的讀法（/remind_list、網頁鬧鐘清單、
  測試）不用一起改。due 才是準的；兩者不一致時以 due 為準。

本檔只放格式與純函式（不碰檔案、不碰時鐘以外的東西）：W1（提醒引擎）照它讀寫，W2（送達層）只透過
(id, occurrence) 認提醒，不 import 這裡以外的 schedule 模組。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Protocol

VERSION = 2
KIND = "remind"

# 重複方式
ONCE, DAILY, NONE = "once", "daily", "none"
REPEATS = (ONCE, DAILY, NONE)

# 狀態
PENDING = "pending"        # 排著（有 due＝還沒到點；待辦＝還沒做）
RINGING = "ringing"        # 到點了、送出去了（或正在送／重試），等人按
SNOOZED = "snoozed"        # 延後中：snooze_until 到了再響
DONE = "done"              # 完成／知道了
MISSED = "missed"          # 錯過：晚太久，只送了「你錯過了」（或併進彙整那一則）
CANCELLED = "cancelled"    # 使用者刪掉
EXPIRED = "expired"        # 響了 EXPIRE_AFTER 沒人理，自動收掉（標「沒人回」）
STATUSES = (PENDING, RINGING, SNOOZED, DONE, MISSED, CANCELLED, EXPIRED)
OPEN = (PENDING, RINGING, SNOOZED)          # 還算「在清單上」的
CLOSED = (DONE, MISSED, CANCELLED, EXPIRED)

# 來源（誰建的；給 log 與健康檢查，不影響行為）
SOURCES = ("command", "ai", "web", "snooze", "legacy", "test")

# 時間界線（W1 照這些數字實作；改數字要改 ADR 0028）
RING_LATE_MAX_MIN = 60          # 晚 60 分鐘內：照常響（帶按鈕），寫「晚了 N 分鐘」——沿用現在的 LATE_MAX_MIN
MISSED_NOTICE_MAX_H = 6         # 晚 60 分鐘～6 小時：一則一則「你錯過了」；超過 6 小時：併成一則彙整
EXPIRE_AFTER_H = 24             # 響了 24 小時沒人按：自動收掉
HISTORY_KEEP = 10               # 每天型保留最近幾次的結果

ISO_SPEC = "seconds"


def local_tz():
    return datetime.now().astimezone().tzinfo


def aware(dt: datetime) -> datetime:
    """沒有時區的 datetime 當作本機時間（測試與舊程式傳的都是這種）。"""
    return dt if dt.tzinfo is not None else dt.astimezone()


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else aware(dt).replace(microsecond=0).isoformat(timespec=ISO_SPEC)


def from_iso(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    return aware(datetime.fromisoformat(str(text)))


@dataclass
class Reminder:
    """一筆提醒或待辦。to_dict()／from_dict() 是存檔的格式（來回轉換不失真）。"""

    id: int
    owner: int
    text: str
    created: int                                   # epoch 秒
    repeat: str = ONCE
    due: Optional[str] = None                      # ISO（帶時區）；None＝待辦
    status: str = PENDING
    occurrence: Optional[str] = None               # 正在響的那一次（ISO）
    snooze_until: Optional[str] = None
    snooze_count: int = 0
    deliveries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "command"
    done_at: Optional[str] = None
    done_via: str = ""                             # "telegram"｜"discord"｜"web"｜"desktop"｜"command"｜"auto"
    last_run: str = ""                             # 舊欄位（每天型：最後一次處理的日期 YYYY-MM-DD）
    kind: str = KIND
    v: int = VERSION

    # ── 推出來的 ─────────────────────────────────────────────────────

    @property
    def is_todo(self) -> bool:
        return self.due is None

    @property
    def due_at(self) -> Optional[datetime]:
        return from_iso(self.due)

    def compat(self) -> Dict[str, str]:
        """舊欄位 time／date（由 due 推）：每天型 date=""；待辦 time=""。"""
        at = self.due_at
        if at is None:
            return {"time": "", "date": ""}
        local = at.astimezone(local_tz())
        return {"time": local.strftime("%H:%M"), "date": "" if self.repeat == DAILY else local.strftime("%Y-%m-%d")}

    # ── 存檔格式 ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out.update(self.compat())
        out["command"] = ""
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Reminder":
        """v2 的 dict → Reminder（不認得的鍵忽略；舊格式請先 upgrade_item）。"""
        if not is_v2(data):
            raise ValueError("not a v2 reminder; call upgrade_item() first")
        names = {f.name for f in fields(cls)}
        rem = cls(**{k: v for k, v in data.items() if k in names})
        problem = check(rem)
        if problem:
            raise ValueError(problem)
        return rem


def check(rem: Reminder) -> str:
    """格式檢查：回 "" ＝沒問題，否則一句白話（不含使用者的內容）。"""
    if rem.repeat not in REPEATS:
        return f"repeat 不認得：{rem.repeat!r}"
    if rem.status not in STATUSES:
        return f"status 不認得：{rem.status!r}"
    if (rem.due is None) != (rem.repeat == NONE):
        return "待辦（repeat=none）不能有 due；有 due 的一定要是 once／daily"
    for name in ("due", "occurrence", "snooze_until", "done_at"):
        value = getattr(rem, name)
        if value is not None:
            try:
                from_iso(value)
            except ValueError:
                return f"{name} 不是 ISO 時間"
    if rem.status == SNOOZED and not rem.snooze_until:
        return "snoozed 一定要有 snooze_until"
    return ""


def is_v2(data: Dict[str, Any]) -> bool:
    return isinstance(data, dict) and data.get("v") == VERSION and data.get("kind") == KIND


def _legacy_due(old: Dict[str, Any]) -> Optional[datetime]:
    """舊的 time＋date → 絕對時間。
    一次性：那一天那一刻。每天：created 之後、last_run 那天之後的第一個那一刻（不看現在幾點——
    「錯過的舊的那幾次不算」由引擎的補送規則處理，見 ADR 0028 §3.1）。"""
    try:
        h, m = (int(x) for x in str(old.get("time", "")).split(":"))
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    if old.get("date"):
        try:
            day = datetime.strptime(str(old["date"]), "%Y-%m-%d")
        except ValueError:
            return None
        return aware(day.replace(hour=h, minute=m))
    created = datetime.fromtimestamp(float(old.get("created") or 0))
    anchor = created
    if old.get("last_run"):
        try:
            after_run = datetime.strptime(str(old["last_run"]), "%Y-%m-%d") + timedelta(days=1)
            anchor = max(anchor, after_run)
        except ValueError:
            pass
    at = anchor.replace(hour=h, minute=m, second=0, microsecond=0)
    if at < anchor:
        at += timedelta(days=1)
    return aware(at)


def upgrade_item(old: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """舊格式（v1：{"id","kind":"remind","time","date","text","owner","last_run","created",...}）→ v2 dict。
    已經是 v2 的原樣回（同一個物件）；kind 不是 remind 的（/schedule_* 的 command）原樣回；
    時間壞掉讀不懂的回 None（引擎記 log、留著原樣不動，不刪使用者的資料）。可以重複呼叫，結果一樣。"""
    if not isinstance(old, dict) or old.get("kind") != KIND or is_v2(old):
        return old
    due = _legacy_due(old)
    if due is None:
        return None
    rem = Reminder(id=int(old.get("id") or 0), owner=int(old.get("owner") or 0), text=str(old.get("text", "")),
                   created=int(float(old.get("created") or 0)), repeat=ONCE if old.get("date") else DAILY,
                   due=to_iso(due), status=PENDING, source="legacy", last_run=str(old.get("last_run") or ""))
    return rem.to_dict()


def new_reminder(id: int, owner: int, text: str, *, due: Optional[datetime], repeat: str = ONCE,
                 created: Optional[int] = None, source: str = "command") -> Reminder:
    """建一筆新的（due=None＝待辦）。W1 的 /remind_add、AI、網頁都走這裡建。"""
    if due is None:
        repeat = NONE
    rem = Reminder(id=id, owner=owner, text=text, created=int(created if created is not None else datetime.now().timestamp()),
                   repeat=repeat, due=to_iso(due), source=source)
    problem = check(rem)
    if problem:
        raise ValueError(problem)
    return rem


class Engine(Protocol):
    """提醒引擎（W1 實作）。主程式的 runtime 任務 system.schedule 與提醒哨兵（W2）都只叫 tick。"""

    def tick(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """處理所有「到點時間 ≤ now、這一次還沒處理」的（冪等：多叫幾次結果一樣），回處理了哪些（測試用）。"""


def headless_engine(data_dir: str, vault, deliver: Callable[[Any], Any], *, per_user: bool = False) -> Engine:
    """不需要整個 App 的引擎（給提醒哨兵）：讀同一份 data/schedule.json(.enc)，到點時呼叫 deliver(Message)
    （哨兵傳自己的 Outbox.submit）。W1 實作；哨兵（W2）只呼叫它。"""
    raise NotImplementedError("W1: reminder.headless_engine")


__all__ = ["CLOSED", "Engine", "headless_engine", "CANCELLED", "DAILY", "DONE", "EXPIRED", "EXPIRE_AFTER_H", "HISTORY_KEEP", "KIND", "MISSED",
           "MISSED_NOTICE_MAX_H", "NONE", "ONCE", "OPEN", "PENDING", "REPEATS", "RING_LATE_MAX_MIN", "RINGING",
           "Reminder", "SNOOZED", "SOURCES", "STATUSES", "VERSION", "aware", "check", "from_iso", "is_v2",
           "new_reminder", "to_iso", "upgrade_item"]
