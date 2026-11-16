"""
送達介面（契約，docs/adr/0028 §3.3）：疊在通知中心（hub.py）上的「送達確認＋重試＋佇列」。

    from synox.notify import delivery
    ticket = delivery.deliver(app, delivery.Message(key="rem:3:2026-11-16T00:51:00+08:00", uid=123,
                                                    text="⏰ 提醒：倒垃圾", kind="alarm", level="alarm",
                                                    actions=[{"id": "ok"}, {"id": "snooze"}],
                                                    ref=delivery.ReminderRef(rid=3, occurrence="2026-11-16T00:51:00+08:00")))
    delivery.resolve(app, 123, ticket.key, note="✅ 在電腦上做完了", via="desktop")

分工：
- **W2 實作**這裡的 Outbox、各管道的 ChannelAdapter、deliver／resolve／planned_channels，並把它接進 Hub。
- **W1 只呼叫** deliver／resolve／planned_channels／status，並實作 ReminderActions（使用者按了完成／延後時，
  送達層回頭叫它）。W1 不寫任何送出的程式；W2 不 import synox.schedule 的引擎。
- Hub.notify 的簽名與行為不變（其他種類的通知照舊一次送完、不重試）；只有走 deliver() 的才有確認與重試。

本檔是契約（型別、常數、RetryPolicy 的數字）＋四個函式的入口；本體在 outbox.py、channels.py、deskapp.py（W2）。
多的兩個入口：is_engine(app)（提醒哨兵在跑時主程式先不跑引擎）、publish_todos(app, uid, items)（視窗下半部的待辦）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

# 管道 id：沿用 hub 的三個，加上電腦提醒視窗
WEB, TELEGRAM, DISCORD, DESKTOP = "web", "telegram", "discord", "desktop"
CHAT = "chat"                       # 沒有 Telegram／Discord 時交給 app.home 的退路（終端機、測試）
CHANNELS = (WEB, TELEGRAM, DISCORD, DESKTOP)
DESKTOP_LABEL = "這台電腦的視窗"

# 一個管道對一則訊息的狀態
QUEUED = "queued"          # 進了佇列還沒試，或送出去了等對方回「看到了」（desktop 等視窗的 shown）
SENT = "sent"              # 管道回報成功（＝送達確認）
FAILED = "failed"          # 這次失敗，等下一次重試
GAVE_UP = "gave_up"        # 重試到 RetryPolicy.max_age_s 還是失敗，或永久性錯誤
SKIPPED = "skipped"        # 沒接上／使用者關掉這一類／這台不是 Windows（不算失敗）
RETRACTED = "retracted"    # 已經在別處處理掉：這邊的按鈕拿掉、訊息改成「✅ 在…做完了」、視窗關掉
STATES = (QUEUED, SENT, FAILED, GAVE_UP, SKIPPED, RETRACTED)

# 錯誤分類（只記種類，不記內容，跟 hub._log_fail 一樣）
ERRORS = ("network", "rate_limited", "blocked", "bad_token", "duplicate_text", "no_window", "timeout", "unknown")
PERMANENT_ERRORS = ("blocked", "bad_token")    # 不重試：直接 GAVE_UP，健康檢查說哪一條壞了


@dataclass
class ReminderRef:
    """這則訊息是哪一個提醒的哪一次（送達層只認這兩個值，不讀提醒的資料）。"""
    rid: int
    occurrence: str                 # 那一次原本的到點時間（ISO）


@dataclass
class Message:
    """要確定送到的一則。key 是冪等鍵：同一個 key 再 deliver 一次＝回原本那張 ticket，不重送。"""
    key: str
    uid: int
    text: str
    kind: str = "alarm"
    level: str = "alarm"
    actions: List[Dict[str, Any]] = field(default_factory=list)   # 同 hub.notify 的 actions（ok／snooze／done…）
    data: Dict[str, Any] = field(default_factory=dict)
    ref: Optional[ReminderRef] = None
    channels: Optional[List[str]] = None       # None＝planned_channels(uid, kind) 全部
    desktop: Optional[Dict[str, Any]] = None   # 給視窗的額外欄位（when、late_min、snooze_count），見 desk.ShowCard


@dataclass
class DeliveryRecord:
    """一個管道對一則訊息的紀錄。也原樣存進提醒的 deliveries[管道]（reminder.Reminder.deliveries）。"""
    channel: str
    state: str = QUEUED
    tries: int = 0
    first_try: Optional[float] = None          # epoch 秒
    last_try: Optional[float] = None
    next_try: Optional[float] = None           # None＝不再試（SENT／GAVE_UP／SKIPPED／RETRACTED）
    ok_at: Optional[float] = None
    error: str = ""                            # ERRORS 之一
    ref: Dict[str, Any] = field(default_factory=dict)   # 管道自己的把手：{"chat_id", "message_id"}、{"token"}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeliveryRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DeliveryResult:
    """ChannelAdapter.send 的回傳。state 只會是 SENT／QUEUED（等確認）／FAILED／SKIPPED。"""
    channel: str
    state: str
    error: str = ""
    ref: Dict[str, Any] = field(default_factory=dict)
    retry_after: Optional[float] = None        # 管道說「幾秒後再來」（Telegram 429）時填；蓋過 RetryPolicy

    @property
    def permanent(self) -> bool:
        return self.state == FAILED and self.error in PERMANENT_ERRORS


@dataclass
class DeliveryTicket:
    """deliver() 的回傳：佇列裡那一則的現況。"""
    key: str
    uid: int
    records: Dict[str, DeliveryRecord] = field(default_factory=dict)

    @property
    def notified(self) -> bool:
        """任一管道 SENT＝「有通知到」（其他管道繼續試）。"""
        return any(r.state == SENT for r in self.records.values())

    @property
    def settled(self) -> bool:
        """沒有任何管道還要再試。"""
        return all(r.next_try is None for r in self.records.values())


@dataclass
class RetryPolicy:
    """失敗後幾秒再試：30 秒、1 分、2 分、5 分、10 分，之後每 15 分；第一次試之後滿 6 小時就放棄。"""
    delays: tuple = (30, 60, 120, 300, 600, 900)
    max_age_s: float = 6 * 3600

    def next_try(self, record: DeliveryRecord, now: float, retry_after: Optional[float] = None) -> Optional[float]:
        """record 剛失敗（tries 已經 +1）之後，下一次幾點試；None＝放棄。"""
        first = record.first_try if record.first_try is not None else now
        if now - first >= self.max_age_s:
            return None
        if retry_after is not None:
            wait = max(1.0, float(retry_after))
        else:
            wait = float(self.delays[min(max(record.tries, 1), len(self.delays)) - 1])
        at = now + wait
        return at if at - first <= self.max_age_s else first + self.max_age_s


DEFAULT_POLICY = RetryPolicy()


@runtime_checkable
class ChannelAdapter(Protocol):
    """一個管道（W2 實作：web、telegram、discord、desktop；包住 hub 現在送的那幾行）。"""
    name: str

    def available(self, uid: int) -> bool:
        """這個人現在接得到嗎（hub.active 的那一格；desktop＝Windows 個人版且視窗功能開著）。"""

    def send(self, msg: Message) -> DeliveryResult:
        """送一次。不可以丟例外（包起來變 FAILED＋error）；不可以 sleep 等重試（重試是 Outbox 的事）。"""

    def retract(self, record: DeliveryRecord, note: str) -> bool:
        """在別處處理掉了：拿掉按鈕、改字成 note、關視窗。失敗回 False（不重試，最多留一顆沒用的按鈕）。"""


@runtime_checkable
class ReminderActions(Protocol):
    """W1 實作、登記在 app.extras[ACTIONS_EXTRA]；送達層（按鈕、網頁、電腦視窗）回頭叫它。"""

    def act(self, uid: int, rid: int, occurrence: str, action: str, *, until: Optional[str] = None,
            typed: str = "", via: str = "") -> "ActionOutcome":
        """action：done（完成）｜ack（知道了）｜snooze（延後到 until，或解析 typed）。via：哪個管道按的。
        要冪等：同一次已經處理過就回 ok=False、reason="gone"。"""

    def on_delivery(self, uid: int, rid: int, occurrence: str, record: DeliveryRecord) -> None:
        """某個管道的紀錄變了（SENT、GAVE_UP…）：W1 寫進提醒的 deliveries。不可以丟例外。"""


@dataclass
class ActionOutcome:
    ok: bool
    reason: str = ""                # gone｜bad_time｜…（白話由 text 給）
    text: str = ""                  # 回給按的人的一句：「好，15:30 再叫你一次。」
    note: str = ""                  # 其他管道要改成的字：「✅ 在電腦上做完了」（空＝不用改）


ACTIONS_EXTRA = "synox_reminder_actions"
OUTBOX_EXTRA = "synox_notify_outbox"
OUTBOX_FOLDER = "outbox"            # data/notifications/outbox/<uid>.json(.enc)（跟通知清單同一套加密）
PUMP_TASK_ID = "system.notify.outbox"
PUMP_INTERVAL = 15                  # 秒：佇列多久看一次該重試的


class Outbox(Protocol):
    """每人一份的送達佇列（W2 實作；存檔、重啟後照樣重試）。"""

    def submit(self, msg: Message) -> DeliveryTicket: ...

    def pump(self, now: Optional[float] = None) -> List[DeliveryTicket]:
        """試所有 next_try ≤ now 的；回有變動的那些。由 runtime 任務 PUMP_TASK_ID 每 PUMP_INTERVAL 秒叫。"""

    def confirm(self, uid: int, key: str, channel: str, ref: Optional[Dict[str, Any]] = None) -> None:
        """非同步的確認（desktop 的 shown）：QUEUED → SENT。"""

    def resolve(self, uid: int, key: str, *, note: str = "", via: str = "") -> None:
        """這一則處理掉了：停止所有重試，除了 via 以外的管道 retract(note)。"""

    def status(self, uid: int, key: str) -> Optional[DeliveryTicket]: ...


# ── W1 呼叫的四個函式（W2 實作本體）──────────────────────────────────

#
# 本體在 notify/outbox.py（佇列）、notify/channels.py（四個管道）、notify/deskapp.py（接上主程式）。
# `app` 只要有 extras：extras[OUTBOX_EXTRA] 是佇列（哨兵自己放一個），沒有的話用通知中心現場裝一個。

def _outbox(app):
    from synox.notify import deskapp
    outbox = deskapp.ensure(app)
    if outbox is None:
        raise RuntimeError("notify hub is not installed")
    return outbox


def deliver(app, msg: Message) -> DeliveryTicket:
    """送一則要確認的通知：馬上試一次，失敗的照 RetryPolicy 留在佇列。冪等（同 key 不重送）。"""
    return _outbox(app).submit(msg)


def resolve(app, uid: int, key: str, *, note: str = "", via: str = "") -> None:
    _outbox(app).resolve(int(uid), key, note=note, via=via)


def status(app, uid: int, key: str) -> Optional[DeliveryTicket]:
    return _outbox(app).status(int(uid), key)


def planned_channels(app, uid: int, kind: str = "alarm") -> List[str]:
    """現在這一類會送到哪些管道（id，CHANNELS 的順序）：給排程回執的 channels。
    跟 hub.where 同一套判斷，多一個 desktop。"""
    from synox import notify
    from synox.notify import channels, deskapp
    hub = notify.of(app)
    if hub is None:
        return []
    deskapp.ensure(app)
    desk = app.extras.get(deskapp.DESK_EXTRA)
    return channels.planned(hub, int(uid), kind, desk.available if desk is not None else (lambda _uid: False))


def is_engine(app) -> bool:
    """這支程式現在是不是提醒引擎（engine.lock 在我手上）。提醒哨兵在跑、還沒讓位時是 False：
    W1 的到點檢查要先看這個，False 就這一輪不跑（哨兵在送，不會重複）。還沒 start（測試）一律 True。"""
    from synox.notify import deskapp
    gate = getattr(app, "extras", {}).get(deskapp.GATE_EXTRA)
    return True if gate is None else bool(gate.mine)


def publish_todos(app, uid: int, items: List[Dict[str, Any]]) -> None:
    """待辦（沒有時間的）有變動時整份交給電腦視窗的下半部：items＝[{"rid": 5, "text": "繳電話費"}]（最多 20 筆）。
    不是 Windows 個人版、不是擁有者就什麼都不做。W1 在待辦新增／完成／刪除後叫。"""
    from synox.notify import deskapp
    if deskapp.ensure(app) is None:
        return
    desk = app.extras.get(deskapp.DESK_EXTRA)
    if desk is not None:
        desk.put_todos(int(uid), items)


def message_key(rid: int, occurrence: str, owner: int) -> str:
    """提醒那一次的冪等鍵（W1 用這個當 Message.key；hub 的 dedupe key 也用它）。"""
    return f"rem:{int(owner)}:{int(rid)}:{occurrence}"


__all__ = ["ACTIONS_EXTRA", "ActionOutcome", "CHANNELS", "CHAT", "ChannelAdapter", "DEFAULT_POLICY", "DESKTOP",
           "DESKTOP_LABEL", "DISCORD", "DeliveryRecord", "DeliveryResult", "DeliveryTicket", "ERRORS", "FAILED",
           "GAVE_UP", "Message", "OUTBOX_EXTRA", "OUTBOX_FOLDER", "Outbox", "PERMANENT_ERRORS", "PUMP_INTERVAL",
           "PUMP_TASK_ID", "QUEUED", "RETRACTED", "ReminderActions", "ReminderRef", "RetryPolicy", "SENT", "SKIPPED",
           "STATES", "TELEGRAM", "WEB", "deliver", "is_engine", "message_key", "planned_channels", "publish_todos",
           "resolve", "status"]
