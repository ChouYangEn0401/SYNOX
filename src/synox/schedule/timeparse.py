"""
時間用語解析（docs/adr/0028 §1.1）：把人說的「等等」「12.51」「半小時後」「明早」「明天 9 點」「+2h」「15:30」
換成絕對時間，**兩種讀法差很多時不猜、回「要問」**；已經過了的時間回「過了」並附「是要明天嗎？」的建議。

    from synox.schedule import timeparse
    w = timeparse.parse("12.51", now=datetime(2026, 11, 16, 0, 40))
    w.kind == timeparse.AT and w.at == datetime(2026, 11, 16, 0, 51)

規則（全部是純函式、不碰檔案；now 沒給＝現在，沒有時區的 datetime 一律當本機時間，回傳的也是沒有時區的本機時間）：

- **HH:MM（冒號、兩位數分鐘）**＝24 小時制，照字面（指令 /remind_add 的格式、AI 也被要求寫 24 小時制）。
- **「12.51」「8 點」「3 點半」這種沒說上午下午的**：可能是兩個時刻（00:51／12:51）。最近的那一個在 6 小時內就用它；
  不然回「要問」，列出兩個選項（例：13:00 說「12.51」→ 要問明天 00:51 還是 12:51）。
- **有說上午／下午／晚上／凌晨／中午**：照說的。
- **有說哪一天（今天、明天、後天、明早、今晚）**：那一天；沒說上午下午時，7–11 點當早上、12 點當中午、1–5 點當下午、
  6 點要問。只說「明天」沒說幾點＝要問；「明早」＝明天 08:00、「今晚／明晚」＝20:00（回傳的 note 會講）。
- **相對**：「半小時後」「10 分鐘後」「1 個半小時後」「兩小時後」「3 天後」「+2h」「+30m」「+90」（分鐘）。
- **「等等」「待會」「晚點」**：沒有數字，回「要問」並給 10 分鐘、30 分鐘、1 小時三個選項。
- 只有時刻、而且今天已經過了 → PAST，at＝明天同一時刻（給「是要明天嗎？」用）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

AT, ASK, PAST, NONE = "at", "ask", "past", "none"

PICK_NEAREST_WITHIN = timedelta(hours=6)       # 兩種讀法裡最近的那個在這之內就用它，不然要問
DEFAULT_MORNING = (8, 0)
DEFAULT_EVENING = (20, 0)
VAGUE_OPTIONS_MIN = (10, 30, 60)

FULL = str.maketrans("０１２３４５６７８９：．＋", "0123456789:.+")
CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
             "八": 8, "九": 9}
NUM = r"(?:\d{1,3}|[零〇一二兩两三四五六七八九十]{1,4})"

VAGUE = ("等等", "等一下", "等下", "待會", "待會兒", "待会", "晚點", "晚一點", "一會兒", "一下子", "稍後", "等會", "等會兒")

# 哪一天：（幾天後, 時段, 只說這個字時的預設時刻）
DAY_WORDS: List[Tuple[str, int, str, Optional[Tuple[int, int]]]] = [
    ("明天早上", 1, "am", DEFAULT_MORNING), ("明天上午", 1, "am", DEFAULT_MORNING), ("明天中午", 1, "noon", (12, 0)),
    ("明天下午", 1, "pm", None), ("明天晚上", 1, "pm", DEFAULT_EVENING), ("明天凌晨", 1, "night", None),
    ("今天早上", 0, "am", None), ("今天上午", 0, "am", None), ("今天中午", 0, "noon", (12, 0)),
    ("今天下午", 0, "pm", None), ("今天晚上", 0, "pm", DEFAULT_EVENING),
    ("後天早上", 2, "am", DEFAULT_MORNING), ("後天下午", 2, "pm", None), ("後天晚上", 2, "pm", DEFAULT_EVENING),
    ("明早", 1, "am", DEFAULT_MORNING), ("明晚", 1, "pm", DEFAULT_EVENING), ("今早", 0, "am", None),
    ("今晚", 0, "pm", DEFAULT_EVENING), ("明天", 1, "", None), ("明日", 1, "", None), ("後天", 2, "", None),
    ("今天", 0, "", None), ("今日", 0, "", None),
]
PERIOD_WORDS: List[Tuple[str, str]] = [
    ("凌晨", "night"), ("清晨", "am"), ("早上", "am"), ("上午", "am"), ("中午", "noon"), ("下午", "pm"),
    ("午後", "pm"), ("傍晚", "pm"), ("晚上", "pm"), ("夜裡", "pm"), ("早", "am"), ("晚", "pm"),
]


@dataclass
class When:
    """解析結果。kind：AT（at 就是答案）｜ASK（question＋options）｜PAST（at＝建議的明天同一時刻）｜NONE（看不懂）。"""
    kind: str
    at: Optional[datetime] = None
    question: str = ""
    options: List[datetime] = field(default_factory=list)
    relative: bool = False          # 「半小時後」這種（不是幾點幾分）
    day_given: bool = False         # 有說哪一天
    clock: Optional[Tuple[int, int]] = None   # 解析出的牆上時刻（相對時間沒有）
    note: str = ""                  # 替你假設了什麼（「明早＝明天 08:00」）

    @property
    def ok(self) -> bool:
        return self.kind == AT


def _cn_int(text: str) -> Optional[int]:
    if text.isdigit():
        return int(text)
    if not text or any(c not in CN_DIGITS and c != "十" for c in text):
        return None
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = CN_DIGITS.get(head, None) if head else 1
        ones = CN_DIGITS.get(tail, None) if tail else 0
        if tens is None or ones is None or "十" in tail:
            return None
        return tens * 10 + ones
    if len(text) == 1:
        return CN_DIGITS[text]
    return None


def _norm(text: str) -> str:
    t = str(text or "").translate(FULL).strip().lower()
    t = re.sub(r"\s+", "", t)
    for a, b in (("鐘頭", "小時"), ("分鐘", "分"), ("以後", "後"), ("之後", "後"), ("后", "後")):
        t = t.replace(a, b)
    return t


def hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _say(dt: datetime, now: datetime) -> str:
    days = (dt.date() - now.date()).days
    head = {0: "今天", 1: "明天", 2: "後天"}.get(days, f"{dt.month}/{dt.day}")
    return f"{head} {hm(dt)}"


# ── 相對時間 ─────────────────────────────────────────────────────────

def _relative(t: str) -> Optional[timedelta]:
    m = re.fullmatch(r"\+(\d{1,4})(m|min|mins|分|h|hr|hrs|小時|d|天)?", t)
    if m:
        n, unit = int(m.group(1)), (m.group(2) or "m")
        return _delta(n, unit)
    if t in ("半小時後", "半個小時後"):
        return timedelta(minutes=30)
    m = re.fullmatch(r"(" + NUM + r"(?:\.\d)?)個?(半)?(小時|分|天|秒)(半)?後", t)
    if not m:
        return None
    raw = m.group(1)
    if "." in raw:
        try:
            n_f = float(raw)
        except ValueError:
            return None
    else:
        n = _cn_int(raw)
        if n is None:
            return None
        n_f = float(n)
    half = bool(m.group(2) or m.group(4))
    unit = m.group(3)
    if unit == "小時":
        return timedelta(minutes=round((n_f + (0.5 if half else 0)) * 60))
    if unit == "分":
        return timedelta(minutes=n_f + (0.5 if half else 0))
    if unit == "天":
        return timedelta(days=n_f + (0.5 if half else 0))
    return None                        # 「30 秒後」：太短，提醒做不到那麼準，當看不懂


def _delta(n: int, unit: str) -> timedelta:
    if unit in ("h", "hr", "hrs", "小時"):
        return timedelta(hours=n)
    if unit in ("d", "天"):
        return timedelta(days=n)
    return timedelta(minutes=n)


# ── 時刻 ─────────────────────────────────────────────────────────────

def _clock(t: str) -> Optional[Tuple[int, int, bool]]:
    """「15:30」「12.51」「3點」「3點半」「3點15分」「十點」→ (時, 分, 是不是 24 小時制照字面)。看不懂＝None。"""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        return (h, mi, True) if h < 24 and mi < 60 else None
    m = re.fullmatch(r"(\d{1,2})\.(\d{2})", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h >= 24 or mi >= 60:
            return None
        return h, mi, (h == 0 or h >= 13)
    m = re.fullmatch(r"(" + NUM + r")[點点時时](半|整|(" + NUM + r")分?)?", t)
    if m:
        h = _cn_int(m.group(1))
        if h is None or h >= 24:
            return None
        rest = m.group(2) or ""
        if rest == "半":
            mi = 30
        elif rest in ("", "整"):
            mi = 0
        else:
            mi = _cn_int(m.group(3) or "")
            if mi is None or mi >= 60:
                return None
        return h, mi, (h == 0 or h >= 13)
    return None


def _apply_period(h: int, period: str) -> Optional[int]:
    if period == "am":
        return 0 if h == 12 else (h if h < 12 else None)
    if period == "night":
        return 0 if h == 12 else (h if h < 12 else None)
    if period == "noon":
        return h if h in (11, 12) else (h + 12 if 1 <= h <= 2 else None)
    if period == "pm":
        return h + 12 if 1 <= h < 12 else (h if h >= 12 else None)
    return h


def _split_day(t: str) -> Tuple[Optional[int], str, Optional[Tuple[int, int]], str]:
    for word, days, period, default in DAY_WORDS:
        if t.startswith(word):
            return days, period, default, t[len(word):]
    return None, "", None, t


def _split_period(t: str) -> Tuple[str, str]:
    for word, period in PERIOD_WORDS:
        if t.startswith(word) and len(t) > len(word):
            return period, t[len(word):]
    return "", t


def _day_hour(h: int) -> Optional[int]:
    """指定了哪一天、沒說上午下午：7–11 早上、12 中午、1–5 下午、6 要問（None）。"""
    if 7 <= h <= 12:
        return h
    if 1 <= h <= 5:
        return h + 12
    return None


def parse(text: str, now: Optional[datetime] = None, *, day: Optional[date] = None) -> When:
    """day：另外指定了哪一天（/remind_add 的 date=）——text 裡沒說哪一天時就用它（要是今天或之後）。"""
    now = now or datetime.now()
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    t = _norm(text)
    if not t:
        return When(NONE)
    minute = now.replace(second=0, microsecond=0)
    if day is not None and _split_day(t)[0] is None:
        offset = (day - now.date()).days
        if offset < 0:
            return When(PAST, day_given=True)
        if t in VAGUE or _relative(t) is not None:
            return When(NONE, relative=True)          # 指定了日期，時間就要是幾點幾分
        period, rest = _split_period(t)
        return _resolve(rest, now, minute, offset, period, None)
    if t in VAGUE:
        opts = [minute + timedelta(minutes=m) for m in VAGUE_OPTIONS_MIN]
        return When(ASK, question="要多久之後？例如「10 分鐘後」「半小時後」「1 小時後」。", options=opts, relative=True)
    rel = _relative(t)
    if rel is not None:
        if rel <= timedelta(0):
            return When(NONE)
        return When(AT, at=(now + rel).replace(microsecond=0), relative=True)
    days, period, default, rest = _split_day(t)
    if not period:
        period, rest = _split_period(rest)
    return _resolve(rest, now, minute, days, period, default)


def _resolve(rest: str, now: datetime, minute: datetime, days: Optional[int], period: str,
             default: Optional[Tuple[int, int]]) -> When:
    day_given = days is not None
    if rest == "" and day_given:
        if default is None:
            word = _word(days)
            return When(ASK, question=f"{word}幾點？例如「{word} 9 點」「{word} 15:30」。", day_given=True)
        base = minute.replace(hour=default[0], minute=default[1]) + timedelta(days=days)
        note = f"沒說幾點，先當 {hm(base)}"
        if days == 0 and base < minute:
            return When(PAST, at=base + timedelta(days=1), day_given=True, clock=default, note=note)
        return When(AT, at=base, day_given=True, clock=default, note=note)
    c = _clock(rest)
    if c is None:
        return When(NONE)
    h, mi, literal = c
    if period:
        h2 = _apply_period(h, period)
        if h2 is None:
            return When(NONE)
        readings = [h2]
    elif literal:
        readings = [h]
    elif day_given and days > 0:
        h2 = _day_hour(h)
        if h2 is None:
            base = minute + timedelta(days=days)
            opts = [base.replace(hour=x % 24, minute=mi) for x in (h % 12, h % 12 + 12)]
            return When(ASK, question=f"{_word(days)} {h} 點是早上還是晚上？", options=opts, day_given=True)
        readings = [h2]
    else:
        readings = sorted({h % 12, h % 12 + 12})

    if day_given:
        base = minute + timedelta(days=days)
        cands = [base.replace(hour=x, minute=mi) for x in readings]
        if days == 0:
            future = [x for x in cands if x >= minute]
            if not future:
                last = max(cands)
                return When(PAST, at=last + timedelta(days=1), day_given=True, clock=(last.hour, mi))
            cands = future
        if len(cands) == 1:
            return When(AT, at=cands[0], day_given=True, clock=(cands[0].hour, mi))
        if days == 0 and cands[0] - minute <= PICK_NEAREST_WITHIN:     # 今天、兩種讀法都還沒到：近的那個夠近就用
            return When(AT, at=cands[0], day_given=True, clock=(cands[0].hour, mi))
        return When(ASK, question=_which(cands, now), options=cands, day_given=True)

    # 沒說哪一天
    if len(readings) == 1:
        at = minute.replace(hour=readings[0], minute=mi)
        if at < minute:
            return When(PAST, at=at + timedelta(days=1), clock=(at.hour, mi))
        return When(AT, at=at, clock=(at.hour, mi))
    nxt = []
    for x in readings:
        at = minute.replace(hour=x, minute=mi)
        if at < minute:
            at += timedelta(days=1)
        nxt.append(at)
    nxt.sort()
    if nxt[0] - minute <= PICK_NEAREST_WITHIN:
        return When(AT, at=nxt[0], clock=(nxt[0].hour, mi))
    return When(ASK, question=_which(nxt, now), options=nxt)


def _word(days: int) -> str:
    return {0: "今天", 1: "明天", 2: "後天"}.get(days, "那天")


def _which(options: List[datetime], now: datetime) -> str:
    return "是哪一個：" + "，還是".join(_say(o, now) for o in options) + "？"


def past_question(at: datetime, now: datetime) -> str:
    """PAST 的那一句：「00:51 已經過了，是要明天 00:51 嗎？」（at＝建議的時刻）。"""
    return f"{hm(at)} 已經過了，是要{_say(at, now)} 嗎？"


__all__ = ["ASK", "AT", "NONE", "PAST", "PICK_NEAREST_WITHIN", "When", "hm", "parse", "past_question"]
