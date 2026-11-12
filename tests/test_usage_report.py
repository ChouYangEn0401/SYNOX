"""AI 用量與花費報表：分組（每小時／天／週／月）、舊紀錄的估算、每小時紀錄只留最近幾天、API 只給擁有者、個人版也記花費。"""
import json
from datetime import datetime

import pytest

from synox.agent import usage_report as ur
from synox.agent.budget import usd_of
from tests.test_web import Client, ui_of

NOW = datetime(2026, 11, 12, 15, 40)                  # 星期四
PRICE = lambda tin, tout: (tin * 3.0 + tout * 15.0) / 1_000_000


def test_day_series_has_fixed_slots_oldest_first():
    data = {"days": {"2026-11-12": {"calls": 2, "input": 1000, "output": 100, "usd": 0.5},
                     "2026-11-10": {"calls": 1, "input": 10, "output": 1, "usd": 0.25}}}
    r = ur.series(data, "day", NOW, PRICE)
    assert [p["key"] for p in r["points"]][-3:] == ["2026-11-10", "2026-11-11", "2026-11-12"] and len(r["points"]) == 14
    assert r["points"][-1]["usd"] == 0.5 and r["points"][-2]["calls"] == 0 and r["points"][-3]["usd"] == 0.25
    assert r["total"]["usd"] == 0.75 and r["total"]["calls"] == 3 and r["estimated"] is False


def test_week_and_month_group_days_and_weeks_start_on_monday():
    data = {"days": {"2026-11-09": {"calls": 1, "usd": 1.0},      # 星期一
                     "2026-11-08": {"calls": 1, "usd": 2.0},      # 星期日（上一週）
                     "2026-10-31": {"calls": 1, "usd": 4.0}}}
    wk = ur.series(data, "week", NOW, PRICE)
    by = {p["key"]: p["usd"] for p in wk["points"]}
    assert by["2026-11-09"] == 1.0 and by["2026-11-02"] == 2.0 and len(wk["points"]) == 12
    mo = ur.series(data, "month", NOW, PRICE)
    by = {p["key"]: p["usd"] for p in mo["points"]}
    assert by["2026-11"] == 3.0 and by["2026-10"] == 4.0 and mo["points"][-1]["key"] == "2026-11" and len(mo["points"]) == 12


def test_hour_series_uses_hour_buckets():
    data = {"hours": {"2026-11-12 15": {"calls": 1, "usd": 0.1}, "2026-11-12 14": {"calls": 2, "usd": 0.2},
                      "2026-11-10 01": {"calls": 9, "usd": 9.0}}}          # 超出 24 小時：不算
    r = ur.series(data, "hour", NOW, PRICE)
    assert len(r["points"]) == 24 and r["points"][-1]["key"] == "2026-11-12 15" and r["points"][-1]["label"] == "15:00"
    assert r["total"]["calls"] == 3 and r["total"]["usd"] == pytest.approx(0.3)


def test_old_buckets_without_usd_are_estimated_and_marked():
    data = {"days": {"2026-11-12": {"calls": 1, "input": 1_000_000, "output": 0}}}
    r = ur.series(data, "day", NOW, PRICE)
    assert r["points"][-1]["usd"] == 3.0 and r["points"][-1]["est"] is True and r["estimated"] is True


def test_series_survives_garbage_and_rejects_unknown_period():
    r = ur.series({"days": {"not-a-date": {"calls": 1}, "2026-11-12": "oops"}, "hours": []}, "day", NOW, PRICE)
    assert r["total"]["calls"] == 0
    assert ur.series(None, "month", NOW, PRICE)["total"]["usd"] == 0
    with pytest.raises(ValueError):
        ur.series({}, "year", NOW, PRICE)


def test_reported_usd_wins_over_token_price(make_bot):
    cfg = make_bot().app.config
    assert usd_of(cfg, {"input": 1_000_000, "output": 0}) == 3.0
    assert usd_of(cfg, {"input": 1_000_000, "output": 0, "usd": 0.07}) == 0.07


def test_usage_book_keeps_hours_only_for_recent_days(tmp_path, monkeypatch):
    from synox.agent import loop as loop_mod
    book = loop_mod.UsageBook(str(tmp_path / "u.json"))
    old = {"hours": {"2026-01-01 00": {"calls": 1}}, "days": {"2026-01-01": {"calls": 1}}, "total": {"calls": 1}}
    (tmp_path / "u.json").write_text(json.dumps(old), encoding="utf-8")
    book.record({"input": 1, "output": 1}, usd=0.5)
    data = json.loads((tmp_path / "u.json").read_text(encoding="utf-8"))
    assert "2026-01-01 00" not in data["hours"] and "2026-01-01" in data["days"]      # 小時的修掉，天的留著
    assert len(data["hours"]) == 1 and next(iter(data["hours"].values()))["usd"] == 0.5


def test_personal_mode_records_cost_and_api_reports_it(make_bot, owner):
    bot = make_bot(script=["好"])
    c = Client(ui_of(bot))
    c.login(owner)
    loop = bot.app.extras["synox_agent"]
    user = bot.app.users.get(owner) if hasattr(bot.app.users, "get") else None
    loop._record(user, {"input": 1_000_000, "output": 0, "usd": 0.25})                       # 個人版：以前花費是 0
    status, data = c.get("/api/usage?period=day")
    assert status == 200 and data["period"] == "day" and data["total"]["usd"] == 0.25 and data["total"]["calls"] == 1
    assert data["subscription"] is False and data["points"][-1]["usd"] == 0.25
    for period in ("hour", "week", "month"):
        assert c.get(f"/api/usage?period={period}")[0] == 200
    assert c.get("/api/usage?period=year")[0] == 400


def test_usage_api_is_owner_only(make_bot, owner):
    from tests.test_web import GUEST_ID
    bot = make_bot()
    m = Client(ui_of(bot))
    m.login(GUEST_ID)
    assert m.get("/api/usage?period=day")[0] == 403
