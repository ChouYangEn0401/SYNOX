"""時間用語解析（synox/schedule/timeparse.py）：兩種讀法差很多時要問；過了的時間回「是要明天嗎？」。"""

from datetime import date, datetime

import pytest

from synox.schedule import timeparse as tp

NIGHT = datetime(2026, 11, 16, 0, 40)
NOON = datetime(2026, 11, 16, 13, 0)


def at(text, now=NOON, **kw):
    w = tp.parse(text, now, **kw)
    assert w.kind == tp.AT, (text, w)
    return w.at


def test_dot_time_picks_the_near_one_or_asks():
    assert at("12.51", NIGHT) == datetime(2026, 11, 16, 0, 51)          # 00:40 說 12.51 → 今天 00:51
    w = tp.parse("12.51", NOON)                                        # 13:00 說 12.51 → 要問
    assert w.kind == tp.ASK and w.options == [datetime(2026, 11, 17, 0, 51), datetime(2026, 11, 17, 12, 51)]
    assert "明天 00:51" in w.question and "明天 12:51" in w.question
    assert at("1.30") == datetime(2026, 11, 16, 13, 30)
    assert at("三點") == datetime(2026, 11, 16, 15, 0)
    assert at("3點半") == datetime(2026, 11, 16, 15, 30)


def test_colon_time_is_24h_and_past_asks_tomorrow():
    assert at("15:30") == datetime(2026, 11, 16, 15, 30)
    w = tp.parse("08:00", NOON)
    assert w.kind == tp.PAST and w.at == datetime(2026, 11, 17, 8, 0)
    assert tp.past_question(w.at, NOON) == "08:00 已經過了，是要明天 08:00 嗎？"
    assert tp.parse("25:00", NOON).kind == tp.NONE
    assert at("13:00") == NOON                                         # 同一分鐘不算過了


@pytest.mark.parametrize("text,expected", [
    ("半小時後", datetime(2026, 11, 16, 13, 30)),
    ("半個小時後", datetime(2026, 11, 16, 13, 30)),
    ("10分鐘後", datetime(2026, 11, 16, 13, 10)),
    ("10 分鐘之後", datetime(2026, 11, 16, 13, 10)),
    ("1個半小時後", datetime(2026, 11, 16, 14, 30)),
    ("兩小時後", datetime(2026, 11, 16, 15, 0)),
    ("1.5小時後", datetime(2026, 11, 16, 14, 30)),
    ("+2h", datetime(2026, 11, 16, 15, 0)),
    ("+30m", datetime(2026, 11, 16, 13, 30)),
    ("+90", datetime(2026, 11, 16, 14, 30)),
    ("３天後", datetime(2026, 11, 19, 13, 0)),
])
def test_relative(text, expected):
    w = tp.parse(text, NOON)
    assert w.kind == tp.AT and w.at == expected and w.relative


@pytest.mark.parametrize("text,expected", [
    ("明早", datetime(2026, 11, 17, 8, 0)),
    ("明天 9 點", datetime(2026, 11, 17, 9, 0)),
    ("明天9點", datetime(2026, 11, 17, 9, 0)),
    ("明天3點", datetime(2026, 11, 17, 15, 0)),
    ("明天早上7點", datetime(2026, 11, 17, 7, 0)),
    ("明晚", datetime(2026, 11, 17, 20, 0)),
    ("今晚", datetime(2026, 11, 16, 20, 0)),
    ("下午3點半", datetime(2026, 11, 16, 15, 30)),
    ("晚上十點", datetime(2026, 11, 16, 22, 0)),
    ("後天 15:00", datetime(2026, 11, 18, 15, 0)),
    ("今天3點", datetime(2026, 11, 16, 15, 0)),
])
def test_days_and_periods(text, expected):
    assert at(text) == expected


def test_vague_and_unclear_ask():
    w = tp.parse("等等", NOON)
    assert w.kind == tp.ASK and len(w.options) == 3 and "多久" in w.question
    assert tp.parse("待會", NOON).kind == tp.ASK
    assert tp.parse("明天", NOON).kind == tp.ASK
    w = tp.parse("明天6點", NOON)
    assert w.kind == tp.ASK and w.options == [datetime(2026, 11, 17, 6, 0), datetime(2026, 11, 17, 18, 0)]
    assert tp.parse("9.15", NOON).kind == tp.ASK                       # 21:15 還要 8 小時多：要問
    assert tp.parse("吃飯", NOON).kind == tp.NONE
    assert tp.parse("", NOON).kind == tp.NONE
    assert tp.parse("今早8點", NOON).kind == tp.PAST


def test_with_a_given_day():
    assert at("08:00", day=date(2026, 11, 17)) == datetime(2026, 11, 17, 8, 0)
    assert at("12.51", day=date(2026, 11, 17)) == datetime(2026, 11, 17, 12, 51)
    w = tp.parse("00:00", NOON, day=date(2026, 11, 16))
    assert w.kind == tp.PAST and w.at == datetime(2026, 11, 17, 0, 0)
    assert tp.parse("半小時後", NOON, day=date(2026, 11, 17)).kind == tp.NONE
    assert tp.parse("08:00", NOON, day=date(2026, 11, 1)).kind == tp.PAST


def test_aware_now_is_local():
    aware = NOON.astimezone()
    assert at("15:30", aware) == datetime(2026, 11, 16, 15, 30)
