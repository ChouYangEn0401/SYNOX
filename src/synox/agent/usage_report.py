"""AI 用量與花費的報表：把 data/llm_usage.json 依「每小時／每天／每週／每月」分組，給設定頁的小儀表板用。

資料來源是 UsageBook（agent/loop.py）：`days`（永遠留）與 `hours`（只留最近 HOURS_KEEP 天）。純函式、不碰檔案、時間由呼叫端給，好測。

花費怎麼來：
- 紀錄裡有 `usd` 就用它（Claude Code 回報的 total_cost_usd，或按 llm.price_in／price_out 算的）。
- 舊紀錄沒有（個人版以前不記花費）：用 token 數照現在的單價估，這一格標 est＝True，畫面上說「約」。
- Claude Code 走的是你自己的訂閱，這裡的美元是「照 API 價換算的約數」，不是額外扣的錢。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List

PERIODS = {            # 名稱 → (顯示幾格, 一格多久)
    "hour": 24,
    "day": 14,
    "week": 12,
    "month": 12,
}
HOURS_KEEP = 14        # 每小時的紀錄只留幾天（再久的看「每天」）


def hour_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H")


def _week_start(d: datetime) -> datetime:
    d = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())            # 星期一


def _add_months(d: datetime, n: int) -> datetime:
    total = d.year * 12 + (d.month - 1) + n
    return d.replace(year=total // 12, month=total % 12 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _slots(period: str, now: datetime) -> List[dict]:
    """由舊到新的格子：[{key, label, start}]。key 是 bucket 的字首（hour／day）或週一／月初的日期。"""
    n = PERIODS[period]
    out = []
    if period == "hour":
        top = now.replace(minute=0, second=0, microsecond=0)
        for i in range(n - 1, -1, -1):
            t = top - timedelta(hours=i)
            out.append({"key": hour_key(t), "label": t.strftime("%H:00"), "start": t.isoformat(timespec="minutes")})
    elif period == "day":
        top = now.replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(n - 1, -1, -1):
            t = top - timedelta(days=i)
            out.append({"key": t.strftime("%Y-%m-%d"), "label": t.strftime("%m-%d"), "start": t.strftime("%Y-%m-%d")})
    elif period == "week":
        top = _week_start(now)
        for i in range(n - 1, -1, -1):
            t = top - timedelta(weeks=i)
            out.append({"key": t.strftime("%Y-%m-%d"), "label": t.strftime("%m-%d") + "起", "start": t.strftime("%Y-%m-%d")})
    else:
        top = _add_months(now, 0)
        for i in range(n - 1, -1, -1):
            t = _add_months(top, -i)
            out.append({"key": t.strftime("%Y-%m"), "label": t.strftime("%Y-%m"), "start": t.strftime("%Y-%m-%d")})
    return out


def _slot_of(period: str, day_or_hour: str) -> str:
    """bucket 的名字（days：YYYY-MM-DD；hours：YYYY-MM-DD HH）→ 它落在哪一格的 key。"""
    if period == "hour" or period == "day":
        return day_or_hour
    d = datetime.strptime(day_or_hour[:10], "%Y-%m-%d")
    if period == "week":
        return _week_start(d).strftime("%Y-%m-%d")
    return d.strftime("%Y-%m")


def _empty() -> dict:
    return {"calls": 0, "input": 0, "output": 0, "usd": 0.0, "est": False}


def series(data: dict, period: str, now: datetime, estimate: Callable[[int, int], float]) -> Dict[str, object]:
    """data＝llm_usage.json 的內容。回 {"period", "points": [...由舊到新...], "total": {...}, "estimated": bool}。"""
    if period not in PERIODS:
        raise ValueError(f"period 要是 {', '.join(PERIODS)}")
    data = data if isinstance(data, dict) else {}
    slots = _slots(period, now)
    cells = {s["key"]: dict(_empty(), **{"key": s["key"], "label": s["label"], "start": s["start"]}) for s in slots}
    source = data.get("hours" if period == "hour" else "days") or {}
    for name, bucket in source.items():
        if not isinstance(bucket, dict) or not isinstance(name, str):
            continue
        try:
            key = _slot_of(period, name)
        except ValueError:
            continue
        cell = cells.get(key)
        if cell is None:
            continue
        calls, tin, tout = int(bucket.get("calls", 0) or 0), int(bucket.get("input", 0) or 0), int(bucket.get("output", 0) or 0)
        cell["calls"] += calls
        cell["input"] += tin
        cell["output"] += tout
        if "usd" in bucket:
            cell["usd"] += float(bucket["usd"] or 0.0)
        elif calls:
            cell["usd"] += estimate(tin, tout)             # 舊紀錄沒記花費：照 token 估
            cell["est"] = True
    points = [cells[s["key"]] for s in slots]
    for p in points:
        p["usd"] = round(p["usd"], 4)
    total = {"calls": sum(p["calls"] for p in points), "input": sum(p["input"] for p in points),
             "output": sum(p["output"] for p in points), "usd": round(sum(p["usd"] for p in points), 4)}
    return {"period": period, "points": points, "total": total, "estimated": any(p["est"] for p in points)}
