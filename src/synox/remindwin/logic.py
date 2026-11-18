"""
電腦提醒視窗的邏輯（不碰 tkinter：測試不開視窗就能跑）。

    model = DeskModel(spool_at(data_dir))
    changes = model.poll()            # 每 1 秒：新的卡、要關的卡、待辦
    model.shown(token)                # 卡片真的畫出來了 → from_win/shown-<token>.json（＝desktop 送到了）
    model.act(token, "snooze:15")     # 按了 → from_win/act-<token>-<ms>.json（引擎 5 秒內讀到）

按鈕（desk.BTN_*，卡片上有哪些由引擎決定）→ 引擎的動作（schedule/actions.py）：
    我完成了 done → done　　我知道了 ack → ack（不響了、不算做完）
    稍後再叫我 5／15 分鐘、1 小時、自選（幾分鐘或打時間）→ snooze
    改到別天 明天同一時間、挑日子＋時間 → reschedule（只有一次性的提醒有）

- 視窗顯示的就是 to_win 裡的 show 檔（扣掉剛按過的）：引擎處理掉才刪 show 檔，所以引擎沒在跑、或不接受
  （例如打的時間看不懂）時，那張卡 ACT_HIDE_S 秒後會再跳出來，不會默默消失。
- close 檔（在別處處理掉了）：關掉那張卡、刪掉 close 檔。
- 自己打時間：看得懂就填 until（ISO），看不懂也照樣把原字交給引擎（引擎說了算）。只打數字＝幾分鐘後。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from synox.notify import desk as deskmod

ACT_HIDE_S = 20.0                 # 按過的卡，這麼久之內不再顯示（等引擎處理）
IDLE_EXIT_S = 600.0               # 沒有卡、這麼久之後視窗程式自己結束（要跳時引擎會再開）
PRESET_MIN = {deskmod.BTN_SNOOZE_5: 5, deskmod.BTN_SNOOZE_10: 10, deskmod.BTN_SNOOZE_15: 15,
              deskmod.BTN_SNOOZE_60: 60}
PICK_DAYS = 7                     # 「挑日子」列幾天（明天起）
WEEK = "一二三四五六日"

LABELS = {
    deskmod.BTN_DONE: "我完成了",
    deskmod.BTN_ACK: "我知道了",
    deskmod.BTN_SNOOZE_5: "5 分鐘",
    deskmod.BTN_SNOOZE_10: "10 分鐘",
    deskmod.BTN_SNOOZE_15: "15 分鐘",
    deskmod.BTN_SNOOZE_60: "1 小時",
    deskmod.BTN_SNOOZE_TYPED: "自選…",
    deskmod.BTN_RESCHEDULE_TOMORROW: "明天同一時間",
    deskmod.BTN_RESCHEDULE_PICK: "挑日子…",
}
T = {
    "title": "提醒",
    "brand": "SYNOX",
    "late": "晚了 {n} 分鐘",
    "snoozed": "延後第 {n} 次之後",
    "snooze_head": "稍後再叫我",
    "move_head": "改到別天",
    "todos": "待辦",
    "todo_done": "✓",
    "typed_hint": "幾分鐘（例如 20），或 15:30、+2h、明天 9 點",
    "typed_ok": "確定",
    "typed_empty": "先打一個時間。",
    "pick_hint": "幾點，例如 09:00、下午 3 點",
    "pick_ok": "改過去",
    "pick_bad": "看不懂這個時間：打 09:00 或 下午 3 點。",
    "pick_past": "要挑現在之後的時間。",
    "done": "好，記成做完了。",
    "ack": "好，這次先不叫你了。",
    "snooze_at": "好，{when} 再叫你一次。",
    "snooze_typed": "好，交給 SYNOX 排時間。",
    "moved": "好，改到 {when} 再叫你。",
}

_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
           "九": 9, "十": 10}


def _num(text: str) -> Optional[int]:
    text = text.strip()
    if text.isdigit():
        return int(text)
    if not text or any(c not in _DIGITS for c in text):
        return None
    if text == "十":
        return 10
    if "十" in text:                                   # 十五、二十、二十五
        tens, _, ones = text.partition("十")
        return (_DIGITS[tens] if tens else 1) * 10 + (_DIGITS[ones] if ones else 0)
    return _DIGITS[text] if len(text) == 1 else None


def _clock_part(text: str) -> Optional[Tuple[int, int]]:
    """「15:30」「15.30」「3 點」「3 點半」「3 點 15 分」「下午 3 點」→ (時, 分)。"""
    text = text.strip().replace("：", ":")
    pm = any(w in text for w in ("下午", "晚上", "傍晚"))
    am = any(w in text for w in ("早上", "上午", "凌晨", "早"))
    text = re.sub(r"(下午|晚上|傍晚|早上|上午|凌晨|中午|早)", "", text).strip()
    m = re.fullmatch(r"(\d{1,2})\s*[:.]\s*(\d{2})", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = re.fullmatch(r"([0-9一二兩两三四五六七八九十〇零]{1,3})\s*[點点時时]\s*(半|([0-9一二兩两三四五六七八九十〇零]{1,3})\s*分?)?",
                         text)
        if not m:
            return None
        h = _num(m.group(1))
        if h is None:
            return None
        if m.group(2) == "半":
            mi = 30
        elif m.group(3):
            mi = _num(m.group(3))
            if mi is None:
                return None
        else:
            mi = 0
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    if not (0 <= h < 24 and 0 <= mi < 60):
        return None
    return h, mi


def parse_typed(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """視窗自己看得懂的時間（看不懂回 None，原字照樣交給引擎）：
    15:30／3 點半／下午 3 點（今天，過了就明天）、+2h／+90m／+1h30m、半小時後／10 分鐘後／2 小時後、明天 9 點。"""
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    s = (text or "").strip().lower().replace(" ", "")
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}", s) and 0 < int(s) <= 24 * 60:          # 只打數字＝幾分鐘後（「自選」那一格）
        return now + timedelta(minutes=int(s))
    m = re.fullmatch(r"\+(?:(\d{1,3})h)?(?:(\d{1,4})m(?:in)?)?", s)
    if m and (m.group(1) or m.group(2)):
        return now + timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0))
    if s in ("半小時後", "半小时后", "半個小時後", "半个小时后"):
        return now + timedelta(minutes=30)
    m = re.fullmatch(r"([0-9一二兩两三四五六七八九十]{1,4})(分鐘|分钟|分)後?后?", s)
    if m and _num(m.group(1)) is not None and (s.endswith("後") or s.endswith("后")):
        return now + timedelta(minutes=_num(m.group(1)))
    m = re.fullmatch(r"([0-9一二兩两三四五六七八九十]{1,3})(個|个)?(小時|小时|鐘頭|钟头)(半)?[後后]", s)
    if m and _num(m.group(1)) is not None:
        return now + timedelta(hours=_num(m.group(1)), minutes=30 if m.group(4) else 0)
    day = 0
    for word, add in (("後天", 2), ("后天", 2), ("明天", 1), ("明早", 1), ("今天", 0)):
        if s.startswith(word):
            day, s = add, s[len(word):]
            if word == "明早":
                s = "早上" + s
            break
    hm = _clock_part(s)
    if hm is None:
        return None
    at = (now + timedelta(days=day)).replace(hour=hm[0], minute=hm[1])
    if day == 0 and at <= now:
        at += timedelta(days=1)
    return at


def day_choices(now: Optional[datetime] = None, n: int = PICK_DAYS) -> List[Tuple[date, str]]:
    """「挑日子」的選項：明天起 n 天 → [(那一天, 「明天」「後天」「11/21（五）」)]。"""
    today = (now or datetime.now()).date()
    out = []
    for i in range(1, n + 1):
        d = today + timedelta(days=i)
        label = "明天" if i == 1 else "後天" if i == 2 else f"{d.month}/{d.day}（{WEEK[d.weekday()]}）"
        out.append((d, label))
    return out


def pick_at(day: date, text: str) -> Optional[datetime]:
    """挑的那一天＋打的時間（「09:00」「9 點半」「下午 3 點」）→ 那一刻（本機、沒有時區）；看不懂＝None。"""
    hm = _clock_part((text or "").replace(" ", ""))
    if hm is None:
        return None
    return datetime(day.year, day.month, day.day, hm[0], hm[1])


def same_time_tomorrow(occurrence: str, now: datetime) -> datetime:
    """「明天同一時間」：這一次原本的牆上時間＋1 天（已經過了就再往後）。本機、沒有時區。"""
    try:
        occ = datetime.fromisoformat(occurrence)
        occ = occ.astimezone().replace(tzinfo=None) if occ.tzinfo else occ
    except (TypeError, ValueError):
        occ = now
    at = occ.replace(second=0, microsecond=0) + timedelta(days=1)
    while at <= now:
        at += timedelta(days=1)
    return at


def when_text(at: datetime, now: datetime) -> str:
    """給人看的時間：今天的只寫 HH:MM，別天的寫「明天 09:00」「11 月 21 日（五）09:00」。"""
    if at.date() == now.date():
        return at.strftime("%H:%M")
    from synox.notify.alarms import friendly
    return friendly(at, now)


def stack_positions(n: int, screen_w: int, screen_h: int, w: int, h: int, *, margin: int = 12,
                    bottom: int = 56) -> List[Tuple[int, int]]:
    """n 張卡在右下角往上疊（第 0 張最下面）；疊到頂就往左開一欄。回每張的 (x, y)。"""
    out = []
    per_col = max(1, (screen_h - bottom - margin) // (h + margin))
    for i in range(n):
        col, row = divmod(i, per_col)
        x = screen_w - (col + 1) * (w + margin)
        y = screen_h - bottom - (row + 1) * (h + margin)
        out.append((max(0, x), max(0, y)))
    return out


def stack_heights(heights: List[int], screen_w: int, screen_h: int, w: int, *, margin: int = 12,
                  bottom: int = 56) -> List[Tuple[int, int]]:
    """高度不一樣的卡（每張依內容長高）在右下角往上疊；疊到頂就往左開一欄。回每張的 (x, y)。"""
    out = []
    col, y = 0, screen_h - bottom
    for h in heights:
        if y - h - margin < 0 and y != screen_h - bottom:          # 這一欄放不下：往左開一欄
            col, y = col + 1, screen_h - bottom
        y -= h + margin
        x = screen_w - (col + 1) * (w + margin)
        out.append((max(0, x), max(0, y)))
    return out


def card_lines(card: deskmod.ShowCard) -> Tuple[str, str]:
    """卡片上的兩行：標題（提醒的字）、小字（何時、晚了多久、延後第幾次）。"""
    sub = [card.when] if card.when else []
    if card.late_min > 0:
        sub.append(T["late"].format(n=card.late_min))
    if card.snooze_count > 0:
        sub.append(T["snoozed"].format(n=card.snooze_count))
    return card.text, "・".join(sub)


@dataclass
class Changes:
    new: List[deskmod.ShowCard] = field(default_factory=list)
    updated: List[deskmod.ShowCard] = field(default_factory=list)
    closed: List[Tuple[str, str]] = field(default_factory=list)       # (token, note)
    todos: List[Dict] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.new or self.updated or self.closed)


class DeskModel:

    def __init__(self, spool, *, uid: Optional[int] = None, clock=time.time, demo: bool = False):
        self.spool = spool
        self.uid = uid
        self.clock = clock
        self.demo = demo                                  # 示範模式：按了就自己刪 show 檔（沒有引擎）
        self.cards: Dict[str, deskmod.ShowCard] = {}
        self.acted: Dict[str, float] = {}
        self.todos: List[Dict] = []
        self.last_card_at = clock()

    def poll(self, now: Optional[float] = None) -> Changes:
        now = self.clock() if now is None else now
        out = Changes()
        shows: Dict[str, deskmod.ShowCard] = {}
        closing = set()
        for obj in self.spool.pending_for_win():
            if isinstance(obj, deskmod.CloseCard):
                closing.add(obj.token)
                if obj.token in self.cards:
                    del self.cards[obj.token]
                    out.closed.append((obj.token, obj.note))
                self.acted.pop(obj.token, None)
                self.spool.drop_close(obj.token)
            elif isinstance(obj, deskmod.ShowCard) and (self.uid is None or int(obj.uid) == int(self.uid)):
                shows[obj.token] = obj
        for token in closing:                             # 同一輪有 close：不管 show 檔還在不在，都不再顯示
            shows.pop(token, None)
        for token in [t for t, at in self.acted.items() if now - at >= ACT_HIDE_S]:
            del self.acted[token]
        for token, card in sorted(shows.items(), key=lambda kv: (kv[1].occurrence, kv[1].written_at)):
            if token in self.acted:
                continue
            old = self.cards.get(token)
            if old is None:
                out.new.append(card)
            elif (old.text, old.when, old.late_min, old.snooze_count) != \
                    (card.text, card.when, card.late_min, card.snooze_count):
                out.updated.append(card)
            self.cards[token] = card
        for token in list(self.cards):
            if token not in shows:                        # 引擎刪了 show 檔（在別處處理掉了）
                del self.cards[token]
                out.closed.append((token, ""))
        todos = []
        for lst in self.spool.todos_for_win(self.uid):
            for it in lst.items:
                if "rid" in it:
                    todos.append({"uid": int(lst.uid), "rid": int(it["rid"]), "text": str(it.get("text", ""))})
        out.todos = self.todos = todos[:deskmod.TODO_SHOW]
        if self.cards:
            self.last_card_at = now
        return out

    def ordered(self) -> List[deskmod.ShowCard]:
        return sorted(self.cards.values(), key=lambda c: (c.occurrence, c.written_at))

    def shown(self, token: str, now: Optional[float] = None) -> None:
        self.spool.put_shown(deskmod.ShownAck(token=token, at=self.clock() if now is None else now))

    def act(self, token: str, button: str, typed: str = "", now: Optional[float] = None,
            at: Optional[datetime] = None) -> Tuple[bool, str]:
        """按了卡片上的按鈕。回 (有沒有送出去, 給人看的一句)。打時間但沒打字＝不送。
        at：「挑日子」挑好的那一刻（本機、沒有時區；pick_at 算的），沒有＝看不懂、不送。"""
        card = self.cards.get(token)
        if card is None:
            return False, ""
        ts = self.clock() if now is None else now
        until: Optional[str] = None
        if button == deskmod.BTN_DONE:
            action, message = "done", T["done"]
        elif button == deskmod.BTN_ACK:
            action, message = "ack", T["ack"]
        elif button in (deskmod.BTN_RESCHEDULE_TOMORROW, deskmod.BTN_RESCHEDULE_PICK):
            here = datetime.fromtimestamp(ts).replace(microsecond=0)
            if button == deskmod.BTN_RESCHEDULE_TOMORROW:
                at = same_time_tomorrow(card.occurrence, here)
            elif at is None:
                return False, T["pick_bad"]
            elif at <= here:
                return False, T["pick_past"]
            action, until = "reschedule", at.astimezone().isoformat()
            message = T["moved"].format(when=when_text(at, here))
        elif button in PRESET_MIN:
            at = datetime.fromtimestamp(ts).replace(microsecond=0) + timedelta(minutes=PRESET_MIN[button])
            action, until = "snooze", at.astimezone().isoformat()
            message = T["snooze_at"].format(when=at.strftime("%H:%M"))
        elif button == deskmod.BTN_SNOOZE_TYPED:
            if not (typed or "").strip():
                return False, T["typed_empty"]
            at = parse_typed(typed, datetime.fromtimestamp(ts))
            action = "snooze"
            if at is not None:
                until = at.astimezone().isoformat()
                message = T["snooze_at"].format(when=at.strftime("%m/%d %H:%M") if at.date() != datetime.fromtimestamp(ts).date()
                                                else at.strftime("%H:%M"))
            else:
                message = T["snooze_typed"]
        else:
            return False, ""
        self.spool.put_action(deskmod.DeskAction(token=token, rid=card.rid, occurrence=card.occurrence, action=action,
                                                 at=ts, until=until, typed=(typed or "").strip()))
        self.acted[token] = ts
        del self.cards[token]
        if self.demo:
            self.spool.drop_show(token)
        return True, message

    def todo_done(self, uid: int, rid: int, now: Optional[float] = None) -> None:
        ts = self.clock() if now is None else now
        token = deskmod.make_token(uid, rid, "")
        self.spool.put_action(deskmod.DeskAction(token=token, rid=int(rid), occurrence="", action="done", at=ts))
        self.todos = [t for t in self.todos if not (t["uid"] == int(uid) and t["rid"] == int(rid))]

    def idle(self, now: Optional[float] = None) -> bool:
        """沒有卡已經 IDLE_EXIT_S 秒了：視窗程式可以結束。"""
        now = self.clock() if now is None else now
        return not self.cards and now - self.last_card_at >= IDLE_EXIT_S


def demo_card(uid: int = 0, now: Optional[datetime] = None) -> deskmod.ShowCard:
    """示範用的一張卡（python -m synox remind-window --demo）。"""
    now = now or datetime.now()
    occ = now.replace(microsecond=0).astimezone().isoformat()
    return deskmod.ShowCard(token=deskmod.make_token(uid, 0, occ), uid=uid, rid=0, occurrence=occ,
                            text="這是試跳的提醒：按一個按鈕看看", when=f"今天 {now.strftime('%H:%M')}")


__all__ = ["ACT_HIDE_S", "Changes", "DeskModel", "IDLE_EXIT_S", "LABELS", "PICK_DAYS", "PRESET_MIN", "T", "card_lines",
           "day_choices", "pick_at", "same_time_tomorrow", "stack_heights", "when_text",
           "demo_card", "parse_typed", "stack_positions"]
