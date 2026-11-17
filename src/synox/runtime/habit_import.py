"""
匯入程式：別的助理的排程規則檔（先前的聊天機器人的 schedule_rules.json 格式）→ soul.md「習慣與規則」的幾行（核心統一規劃 11.4、8.5）。

    python -m synox import-legacy schedule-rules --from=<一個 JSON 檔>            乾跑：只印會寫哪幾行，什麼都不改
    python -m synox import-legacy schedule-rules --from=<一個 JSON 檔> --apply    真的寫（SoulStore.set_habit，by=import）

- 可以重跑：同一個鍵再匯一次＝取代那一行（habits.insert 的規則），不會越寫越多。
- 輸入可以是完整的預設檔，也可以是只寫了幾項的覆寫檔；`_` 開頭的說明欄位不看。
- 對不到 SOUL 鍵的（例如最上層的 enabled）、值是 null（原格式的「拿掉這一項」）的，列在「略過」，不寫。
- 每一列自己帶型別、預設與範圍（跟規劃 11.4 的宣告一致）：跟預設一樣的值不寫（略過清單寫「跟預設一樣」），
  型別或範圍不合的不寫（寫原因）；--apply 時 SoulStore 也照這份宣告再檢查一次。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from synox.runtime import habits

# (原檔裡的路徑, SOUL 的鍵, 人話（{v} 換成值）, 宣告：type、default、min／max)。預設值照規劃 11.4，通用、保守；不放任何人的值。
_P = Tuple[Tuple[str, ...], str, str, Dict[str, Any]]
SCHEDULE_RULES: Tuple[_P, ...] = (
    (("class", "title_regex"), "schedule.class.title_regex", "標題對到這個樣式的行程算課。",
     {"type": "regex", "default": "課|上課|class|lecture"}),
    (("class", "exclude_prefixes"), "schedule.class.exclude_prefixes", "這些字開頭的行程不算課。",
     {"type": "list", "default": []}),
    (("class", "after_minutes"), "schedule.class.after_minutes", "上完課 {v} 分鐘內不排別的。",
     {"type": "int", "default": 30, "min": 0, "max": 240, "looser": "smaller"}),
    (("meals",), "schedule.meals", "吃飯時間要留空。",
     {"type": "json", "default": [{"name": "午餐", "from": "11:00", "to": "14:00", "minutes": 30}]}),
    (("busy", "max_hours"), "schedule.busy.max_hours", "連續排超過 {v} 小時要休息。",
     {"type": "number", "default": 4, "min": 0, "max": 24, "looser": "larger"}),
    (("busy", "break_minutes"), "schedule.busy.break_minutes", "中間空不到 {v} 分鐘不算休息。",
     {"type": "int", "default": 30, "min": 0, "max": 240}),
    (("busy", "day_latest"), "schedule.busy.day_latest", "每天最晚排到 {v}。",
     {"type": "time", "default": "23:30", "looser": "larger"}),
    (("series", "enabled"), "schedule.series.enabled", "{v}檢查同一系列有沒有照順序排。",
     {"type": "bool", "default": True}),
    (("delete_series", "enabled"), "schedule.delete_series.enabled", "刪掉系列的某一段、之後就沒有了的時候{v}提醒。",
     {"type": "bool", "default": True}),
    (("naming",), "schedule.naming", "標題的寫法規則。", {"type": "json", "default": []}),
    (("plan", "per_day"), "schedule.plan.per_day", "一天最多排 {v} 部。",
     {"type": "int", "default": 1, "min": 1, "max": 24, "looser": "larger"}),
    (("plan", "split"), "schedule.plan.split", "一部{v}切段。", {"type": "bool", "default": False}),
    (("plan", "overdue"), "schedule.plan.overdue", "過期的{v}排進去。", {"type": "bool", "default": True}),
    (("plan", "horizon_days"), "schedule.plan.horizon_days", "最遠排到 {v} 天後。",
     {"type": "int", "default": 120, "min": 1, "max": 366}),
    (("plan", "step_minutes"), "schedule.plan.step_minutes", "時間以 {v} 分鐘為一格。",
     {"type": "int", "default": 15, "min": 1, "max": 240}),
    (("plan", "margin_minutes"), "schedule.plan.margin_minutes", "前後留 {v} 分鐘。",
     {"type": "int", "default": 15, "min": 0, "max": 240}),
    (("plan", "windows"), "schedule.plan.windows", "平日與週末可以排的時段。",
     {"type": "json", "default": {"weekday": ["20:00", "23:00"], "weekend": ["09:00", "23:00"]}}),
)
KINDS = {"schedule-rules": SCHEDULE_RULES}


def _get(data: dict, path: Tuple[str, ...]):
    node: Any = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _paths(data: Any, prefix: Tuple[str, ...] = ()) -> List[Tuple[str, ...]]:
    """原檔裡每一個「葉」的路徑（`_` 開頭的說明不算）。"""
    if not isinstance(data, dict):
        return [prefix] if prefix else []
    out: List[Tuple[str, ...]] = []
    for k, v in data.items():
        if str(k).startswith("_"):
            continue
        out += _paths(v, prefix + (str(k),)) if isinstance(v, dict) else [prefix + (str(k),)]
    return out


def declarations(kind: str = "schedule-rules") -> Dict[str, "habits.Pref"]:
    """匯入表自己帶的宣告（鍵 → Pref）：convert 檢查型別與範圍、--apply 時交給 SoulStore 再檢查一次。"""
    raw = [dict(spec, key=key) for _path, key, _text, spec in KINDS[kind]]
    prefs, bad = habits.parse_decls(raw, pack="import", title="匯入")
    if bad:                                          # 表寫錯是程式的錯，不是使用者的
        raise ValueError("；".join(bad))
    return {p.key: p for p in prefs}


def convert(data: dict, kind: str = "schedule-rules") -> Tuple[List[str], List[str]]:
    """原檔的 dict → (要寫的行, 略過的說明)。純函式。跟預設一樣、型別或範圍不合、null 的不寫。"""
    decls = declarations(kind)
    lines: List[str] = []
    skipped: List[str] = []
    used = set()
    for path, key, text, _spec in KINDS[kind]:
        found, value = _get(data, path)
        if not found:
            continue
        used.add(path)
        name = ".".join(path)
        if value is None:
            skipped.append(f"{name}＝null（原格式的「拿掉這一項」；不寫，工具用自己的預設）")
            continue
        pref = decls[key]
        value, problem = habits.coerce(pref, value)
        if problem:
            skipped.append(f"{name}：型別或範圍不合（{problem}），不寫")
            continue
        if value == pref.default:
            skipped.append(f"{name}：跟預設一樣（{habits.format_value(value)}），不寫")
            continue
        shown = ("要" if value else "不要") if isinstance(value, bool) else (value if isinstance(value, str) else habits.format_value(value))
        line = habits.make_line(text.replace("{v}", shown), [(key, value)])
        try:
            habits.check_line(line, decls)
        except habits.HabitError as e:
            skipped.append(f"{name}：寫不進去（{e}）")
            continue
        lines.append(line)
    for path in _paths(data):
        if path in used or any(path[:len(p)] == p for p in used):
            continue
        name = ".".join(path)
        why = "整個檢查的總開關，SOUL 沒有對應的鍵（要關就把各項關掉）" if path == ("enabled",) else "SOUL 沒有對應的鍵"
        skipped.append(f"{name}：{why}")
    return lines, skipped


def read_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("檔案的最外層要是 JSON 物件")
    return data


def run(path: str, *, apply: bool = False, soul=None, kind: str = "schedule-rules", out=print) -> int:
    """印出每一行；apply＝寫進 soul（SoulStore）。回 exit code（0＝好、2＝讀不了或寫不了）。"""
    try:
        data = read_file(path)
    except (OSError, ValueError) as e:
        out(f"❌ 讀不了 {path}：{e}")
        return 2
    lines, skipped = convert(data, kind)
    head = "會寫進" if not apply else "寫進"
    out(f"{'乾跑（沒有改任何東西；加 --apply 才寫）' if not apply else '匯入'}："
        f"{head} soul.md「{habits.HEADING[3:]}」的 {len(lines)} 行：")
    for line in lines:
        out(line)
    if skipped:
        out(f"略過 {len(skipped)} 項：")
        for item in skipped:
            out(f"  · {item}")
    if not apply:
        return 0
    if soul is None:
        out("❌ 保管箱沒有打開，寫不了。")
        return 2
    from synox.runtime.soul import SoulError
    if soul.declarations is None:                  # 命令列沒有載入工具：用匯入表自己的宣告檢查型別與範圍
        decls = declarations(kind)
        soul.declarations = lambda: decls
    bad = 0
    for line in lines:
        try:
            done = soul.set_habit(line, by="import")
        except SoulError as e:
            out(f"❌ 沒寫進去：{line}——{e}")
            bad += 1
            continue
        if done["replaced"]:
            out(f"  （取代：{'；'.join(done['replaced'])}）")
    out(f"✅ 寫好了 {len(lines) - bad} 行。" + (f"{bad} 行沒寫進去。" if bad else ""))
    return 2 if bad else 0
