"""
config.json 的 `runtime` 這一塊：預設值與檢查（docs/adr/0001）。只用標準函式庫，config.py 直接 import。

    "runtime": {
      "heartbeat": {"enabled": true, "interval_min": 45, "quiet_hours": "23:00-08:00",
                    "daily_max_notify": 4, "daily_max_calls": 40},
      "mother": {"enabled": true, "memory_turns": 20, "read_chat": true, "soul_append": true, "soul_review": false},
      "activator": {"enabled": true, "max_depth": 5, "max_chain_actions": 20, "max_fanout": 10,
                    "budget_window_min": 10, "budget_max_actions": 60, "rules": [ … ]}
    }

activator（連動，docs/adr/0004）的 rules 每一條（只收資料，不收程式；程式定義的規則見 runtime/activator.py）：
    {"id": "diary-image-ask", "on": "pack.diary", "state": "ok", "from": "failed", "tag": "diary-image",
     "run_task": "system.schedule" 或 "notify": "一句話",  "timing": "now" 或 "heartbeat",
     "cooldown_s": 0, "max_per_hour": 30, "enabled": true, "name": "給人看的名字"}

soul_review（docs/adr/0005）：true＝常駐助理想記進 soul.md 的每一行都先等你在主控面板按；false＝沒有疑慮的直接加。
"""

from __future__ import annotations

import copy
import re
from typing import Optional, Tuple

MIN_INTERVAL_MIN = 15
MAX_INTERVAL_MIN = 1440

DEFAULT_RUNTIME = {
    "heartbeat": {"enabled": True, "interval_min": 45, "quiet_hours": "23:00-08:00",
                  "daily_max_notify": 4, "daily_max_calls": 40},
    "mother": {"enabled": True, "memory_turns": 20, "read_chat": True, "soul_append": True, "soul_review": False},
    "activator": {"enabled": True, "max_depth": 5, "max_chain_actions": 20, "max_fanout": 10,
                  "budget_window_min": 10, "budget_max_actions": 60, "rules": []},
}

# 連動規則（activator）的欄位與範圍；runtime/activator.py 也用這些（程式定義的規則一樣要過）
RULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
RULE_STATES = ("ok", "running", "failed", "idle")
TIMINGS = ("now", "heartbeat")
RULE_KEYS = {"id", "name", "on", "state", "from", "tag", "run_task", "notify", "timing", "cooldown_s",
             "max_per_hour", "enabled"}
RESERVED_PREFIXES = ("system.", "pack.")     # config.json 的規則不能用（留給系統與 pack）
MAX_RULES = 100
NOTIFY_MAX = 200
COOLDOWN_MAX = 86400
PER_HOUR_MAX = 600
DEFAULT_PER_HOUR = 30

_HHMM = r"([01]\d|2[0-3]):([0-5]\d)"
QUIET_RE = re.compile(rf"^{_HHMM}-{_HHMM}$")


class RuntimeConfigError(ValueError):
    """config.json 的 runtime 寫錯；訊息是給人看的一句話（config.py 轉成 ConfigError）。"""


def defaults() -> dict:
    return copy.deepcopy(DEFAULT_RUNTIME)


def interval_problem(value) -> str:
    """心跳間隔（分鐘）合不合法：""＝合法。bool、小數、字串都不收（網頁與 config.json 共用這一句）。"""
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_INTERVAL_MIN <= value <= MAX_INTERVAL_MIN:
        return f"間隔要是 {MIN_INTERVAL_MIN}～{MAX_INTERVAL_MIN} 的整數（分鐘）。"
    return ""


def parse_quiet(text: str) -> Optional[Tuple[int, int]]:
    """"23:00-08:00" → (1380, 480)（一天裡的第幾分鐘）；空字串 → None（沒有安靜時段）。格式錯丟 RuntimeConfigError。"""
    text = (text or "").strip()
    if not text:
        return None
    m = QUIET_RE.match(text)
    if not m:
        raise RuntimeConfigError("runtime.heartbeat.quiet_hours 要寫成 \"HH:MM-HH:MM\"（例如 \"23:00-08:00\"），或空字串＝不設。")
    start, end = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
    return start, end


def in_quiet(quiet: Optional[Tuple[int, int]], minute_of_day: int) -> bool:
    """跨午夜也算（23:00-08:00）；開始＝結束＝沒有安靜時段。"""
    if quiet is None:
        return False
    start, end = quiet
    if start == end:
        return False
    if start < end:
        return start <= minute_of_day < end
    return minute_of_day >= start or minute_of_day < end


def _bool(section: dict, key: str, where: str) -> bool:
    value = section[key]
    if not isinstance(value, bool):
        raise RuntimeConfigError(f"runtime.{where}.{key} 要是 true 或 false。")
    return value


def _int(section: dict, key: str, where: str, low: int, high: int) -> int:
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise RuntimeConfigError(f"runtime.{where}.{key} 要是 {low}～{high} 的整數。")
    return value


def parse(raw) -> dict:
    """config.json 的 runtime（可以沒寫）→ 補好預設、檢查過的 dict。錯丟 RuntimeConfigError。"""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise RuntimeConfigError("config.json 的 runtime 要是一個 {…} 物件。")
    out = defaults()
    for name in ("heartbeat", "mother", "activator"):
        section = raw.get(name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise RuntimeConfigError(f"config.json 的 runtime.{name} 要是一個 {{…}} 物件。")
        out[name].update(section)
    hb, mother = out["heartbeat"], out["mother"]
    _bool(hb, "enabled", "heartbeat")
    problem = interval_problem(hb["interval_min"])
    if problem:
        raise RuntimeConfigError("runtime.heartbeat.interval_min：" + problem)
    if not isinstance(hb["quiet_hours"], str):
        raise RuntimeConfigError("runtime.heartbeat.quiet_hours 要是字串（\"23:00-08:00\" 或 \"\"）。")
    hb["quiet_hours"] = hb["quiet_hours"].strip()
    parse_quiet(hb["quiet_hours"])
    _int(hb, "daily_max_notify", "heartbeat", 0, 48)
    _int(hb, "daily_max_calls", "heartbeat", 0, 200)
    for key in ("enabled", "read_chat", "soul_append", "soul_review"):
        _bool(mother, key, "mother")
    _int(mother, "memory_turns", "mother", 0, 100)
    act = out["activator"]
    _bool(act, "enabled", "activator")
    _int(act, "max_depth", "activator", 1, 10)
    _int(act, "max_chain_actions", "activator", 1, 100)
    _int(act, "max_fanout", "activator", 1, 50)
    _int(act, "budget_window_min", "activator", 1, 1440)
    _int(act, "budget_max_actions", "activator", 1, 1000)
    act["rules"] = parse_rules(act.get("rules"))
    return out


def _states(value, where: str, key: str) -> list:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not items or not all(isinstance(v, str) and v in RULE_STATES for v in items):
        raise RuntimeConfigError(f"{where}.{key} 要是 {'／'.join(RULE_STATES)} 其中一個，或這些字的清單。")
    return list(dict.fromkeys(items))


def parse_rule(raw, where: str = "runtime.activator.rules[]", *, reserved: bool = True) -> dict:
    """一條資料形式的連動規則 → 補好預設、檢查過的 dict（錯丟 RuntimeConfigError，訊息是給人看的一句話）。
    reserved=True（config.json）：id 不能用 system.／pack. 開頭。"""
    if not isinstance(raw, dict):
        raise RuntimeConfigError(f"{where} 要是一個 {{…}} 物件。")
    extra = sorted(set(raw) - RULE_KEYS)
    if extra:
        raise RuntimeConfigError(f"{where} 有不認得的欄位：{'、'.join(extra)}（只收 {'、'.join(sorted(RULE_KEYS))}）。")
    rid = raw.get("id")
    if not isinstance(rid, str) or not RULE_ID_RE.match(rid):
        raise RuntimeConfigError(f"{where}.id 要是小寫英數字與 . _ -（128 字內）。")
    where = f"{where}（{rid}）"
    if reserved and rid.startswith(RESERVED_PREFIXES):
        raise RuntimeConfigError(f"{where}.id 不能用 system. 或 pack. 開頭（留給系統與工具自己的規則）。")
    on = raw.get("on")
    if not isinstance(on, str) or not TASK_ID_RE.match(on):
        raise RuntimeConfigError(f"{where}.on 要是任務 id（例如 pack.weather、system.schedule）。")
    tag = raw.get("tag")
    if tag is not None and (not isinstance(tag, str) or not TAG_RE.match(tag)):
        raise RuntimeConfigError(f"{where}.tag 要是小寫英數字與 . _ -（32 字內），或不寫＝什麼標籤都算。")
    actions = [k for k in ("run_task", "notify") if raw.get(k) not in (None, "")]
    if len(actions) != 1:
        raise RuntimeConfigError(f"{where} 要剛好有一個動作：run_task（跑一個任務）或 notify（通知你一句話）。")
    run_task = raw.get("run_task") or ""
    if run_task and (not isinstance(run_task, str) or not TASK_ID_RE.match(run_task)):
        raise RuntimeConfigError(f"{where}.run_task 要是任務 id。")
    notify = raw.get("notify") or ""
    if notify and (not isinstance(notify, str) or len(notify) > NOTIFY_MAX or not notify.strip()):
        raise RuntimeConfigError(f"{where}.notify 要是 {NOTIFY_MAX} 字內的一句話。")
    timing = raw.get("timing", "now")
    if timing not in TIMINGS:
        raise RuntimeConfigError(f"{where}.timing 要是 now（馬上）或 heartbeat（留給下一次心跳）。")
    name = raw.get("name", "")
    if not isinstance(name, str) or len(name) > 60:
        raise RuntimeConfigError(f"{where}.name 要是 60 字內的字串。")
    rule = {"id": rid, "name": name.strip() or rid, "on": on,
            "state": _states(raw.get("state", "ok"), where, "state"),
            "from": _states(raw["from"], where, "from") if raw.get("from") is not None else [],
            "tag": tag, "run_task": run_task, "notify": notify.strip(), "timing": timing,
            "cooldown_s": raw.get("cooldown_s", 0), "max_per_hour": raw.get("max_per_hour", DEFAULT_PER_HOUR),
            "enabled": raw.get("enabled", True)}
    _int(rule, "cooldown_s", f"activator.rules（{rid}）", 0, COOLDOWN_MAX)
    _int(rule, "max_per_hour", f"activator.rules（{rid}）", 1, PER_HOUR_MAX)
    _bool(rule, "enabled", f"activator.rules（{rid}）")
    return rule


def parse_rules(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuntimeConfigError("runtime.activator.rules 要是一個 […] 清單。")
    if len(raw) > MAX_RULES:
        raise RuntimeConfigError(f"runtime.activator.rules 最多 {MAX_RULES} 條。")
    rules, seen = [], set()
    for i, item in enumerate(raw):
        rule = parse_rule(item, f"runtime.activator.rules[{i}]")
        if rule["id"] in seen:
            raise RuntimeConfigError(f"runtime.activator.rules 有兩條 id 都是 {rule['id']}。")
        seen.add(rule["id"])
        rules.append(rule)
    cycle = find_cycle([(r["id"], r["on"], r["tag"], [(r["run_task"], "")] if r["run_task"] else []) for r in rules])
    if cycle:
        raise RuntimeConfigError("runtime.activator.rules 會繞回自己（無限連動）：" + " → ".join(cycle)
                                 + "。拿掉其中一條，或把動作改成 notify。")
    return rules


def find_cycle(rules) -> list:
    """rules：[(規則 id, 聽哪個任務, 聽哪個標籤（None＝都聽）, [(做完會讓哪個任務有新狀態, 標籤)])]。
    標籤：""＝沒有標籤（跑任務做完就是這樣）、None＝不知道（當作什麼標籤都可能）。
    有循環＝回規則 id 的路徑（頭尾同一條），沒有＝[]。規則 A 會讓任務 T 有新狀態、規則 B 聽 T（標籤對得上）→ A 接到 B。
    不看 state（ok／failed 都可能）：寧可多擋，不要漏。"""
    listeners = {}
    for rid, on, tag, _emits in rules:
        listeners.setdefault(on, []).append((rid, tag))
    edges = {rid: sorted({b for task, etag in emits for b, btag in listeners.get(task, [])
                          if btag is None or etag is None or btag == etag})
             for rid, _on, _tag, emits in rules}
    color, stack = {}, []

    def visit(node):
        color[node] = 1
        stack.append(node)
        for nxt in edges.get(node, []):
            if color.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if color.get(nxt) is None:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = 2
        return []

    for rid in sorted(edges):
        if color.get(rid) is None:
            found = visit(rid)
            if found:
                return found
    return []
