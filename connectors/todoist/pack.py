"""✅ Todoist：/todoist <內容> [到期]、/todoist_list [all|today|overdue|#專案|@標籤]、/todoist_done <編號>、
/todoist_due <編號> <到期>、/todoist_rm <編號>、/todoist_projects、/todoist_labels；設定：/todoist_token <token>、/todoist_logout。

跟 SYNOXPacks 的本機待辦 `todo` pack 同一套寫法（可以互換）：`/todoist !! 繳電費 明天 #家事` → 很重要、到期明天、
放進「家事」專案（沒有這個專案就當標籤）；`@標籤` 一定是標籤。到期用跟行事曆同一套中文日期（明天、下週一、11/20、下午3點…），
看不懂的寫法（例如 every monday）原樣交給 Todoist 自己解析。

連線：Todoist API v1（https://api.todoist.com/api/v1，REST v2 已退役），個人 API token，只用 requests、只連 api.todoist.com，
不開埠、不存明文：token 在 pack.store.of(user)（保管箱，密文 data/todoist.json.enc；伺服器版每人一份）。
存的東西：{"token": "...", "ids": {"<Todoist 任務 id>": 編號}, "next_n": 1}——編號是 SYNOX 這邊給的短號（[3]），
第一次看到某個任務時配一個，之後不變；完成、刪除就收回。指令也收 Todoist 原本的任務 id。

測試換掉 HTTP（假的 requests.Session）與 now()，不打真的 Todoist。
"""

import re
import time
from datetime import date, datetime

import requests

from isdtelekit.core.registry import DANGER, WRITE, Field

from synox.packs import kit

API = "https://api.todoist.com/api/v1"
TIMEOUT = 15                    # 秒；AI 的工具呼叫會等它
PAGE_LIMIT = 200                # Todoist v1 一頁最多 200
MAX_PAGES = 10                  # 最多讀 2000 個任務
SHOW = 30                       # 清單最多顯示幾行
MAX_IDS = 3000                  # 編號對照表最多記幾個（多了丟最舊的）
HTTP = None                     # None＝requests.Session()；測試放假的 session
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-.]{20,200}$")
NO_DATE_WORDS = ("無", "沒有", "不要", "清掉", "取消", "none", "no date")
SETUP_HINT = ("還沒接上 Todoist。到 Todoist 網頁版：右上頭像 → 設定 → 整合 → 開發者，複製「API token」，"
              "然後在這裡打 /todoist_token 貼上那串字。")


def now() -> datetime:
    """現在時間（測試換掉這一個）。"""
    return datetime.now()


# >>> zhdate（正本在 SYNOXPacks repo 的 packs/_shared/zhdate.py；這裡是原樣複製（pack 不互相 import）。
#     不要直接改這段：改正本，再整段複製過來，讓 todo、calendar、todoist 三個看得懂的日期一樣）
import re as _re
from dataclasses import dataclass as _dataclass
from datetime import date as _date, timedelta as _timedelta

WEEK_NAMES = "一二三四五六日"
_CN = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5,
       "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"(?:\d{1,2}|[零〇一二兩两三四五六七八九十]{1,3})"
_WD = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
       "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}
_PERIOD = r"(早上|上午|中午|下午|晚上|傍晚|凌晨|半夜|早|晚)?"
_DATE_PATTERNS = (
    ("ymd", _re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")),
    ("md", _re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")),
    ("md_cn", _re.compile(r"(" + _NUM + r")月(" + _NUM + r")[日號号]?")),
    ("rel", _re.compile(r"(大後天|大后天|後天|后天|明天|明日|明晚|明早|今天|今日|今晚|今早)")),
    ("week", _re.compile(r"(下下|下|這|这|本)?(?:個|个)?(?:週|周|星期|禮拜|礼拜)([一二三四五六日天1-7])")),
    ("after", _re.compile(r"(" + _NUM + r")\s*(天|週|周|個禮拜|个礼拜)[後后]")),
    ("day", _re.compile(r"(?<![\d月/])(\d{1,2})[號号]")),
)
_TIME_HM = _re.compile(_PERIOD + r"\s*(\d{1,2}):(\d{2})(?!\d)")
_TIME_CN = _re.compile(_PERIOD + r"\s*(" + _NUM + r")\s*[點点](?![點点])\s*(半|(" + _NUM + r")\s*分?)?")
_TIME_AMPM = _re.compile(r"(?<![\dA-Za-z:])(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?(?![a-z])", _re.IGNORECASE)
_NOON = _re.compile(r"中午")
_RANGE_SEP = _re.compile(r"^\s*(?:-|~|～|－|–|到|至)\s*")
_EVENING_WORDS = ("今晚", "明晚")


def cn_int(s: str) -> int:
    """'14'→14、'三'→3、'十二'→12、'二十三'→23。看不懂丟 ValueError。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        if (a and a not in _CN) or (b and b not in _CN):
            raise ValueError(s)
        return (_CN[a] if a else 1) * 10 + (_CN[b] if b else 0)
    if len(s) == 1 and s in _CN:
        return _CN[s]
    raise ValueError(s)


@_dataclass
class When:
    """parse_when 的結果。day：日期（沒看到＝None）；start／end：'HH:MM'（沒看到＝None）；
    rest：拿掉日期、時間之後剩下的字；error：看到了但不是真的日期／時間。"""
    day: object = None
    start: object = None
    end: object = None
    rest: str = ""
    error: str = ""

    @property
    def all_day(self) -> bool:
        return self.start is None


def _safe_date(y: int, m: int, d: int):
    try:
        return _date(y, m, d)
    except ValueError:
        return None


def _roll_year(today, m: int, d: int):
    """月／日沒寫年：今年的那一天已經過了就算明年的。"""
    found = _safe_date(today.year, m, d)
    if found is None:
        return None
    if found < today:
        found = _safe_date(today.year + 1, m, d)
    return found


def _date_from(kind: str, m, today):
    """一個日期 match → date；不是真的日期回 None。"""
    g = m.groups()
    if kind == "ymd":
        return _safe_date(int(g[0]), int(g[1]), int(g[2]))
    if kind in ("md", "md_cn"):
        try:
            return _roll_year(today, cn_int(g[0]), cn_int(g[1]))
        except ValueError:
            return None
    if kind == "rel":
        word = g[0]
        offset = 3 if word.startswith("大") else 2 if word[0] in "後后" else 1 if word[0] == "明" else 0
        return today + _timedelta(days=offset)
    if kind == "week":
        prefix, wd = g[0] or "", _WD[g[1]]
        monday = today - _timedelta(days=today.weekday())
        if prefix == "下下":
            return monday + _timedelta(days=14 + wd)
        if prefix == "下":
            return monday + _timedelta(days=7 + wd)
        if prefix:                                   # 這週、本週
            return monday + _timedelta(days=wd)
        return today + _timedelta(days=(wd - today.weekday()) % 7)   # 沒寫：最近的那一天（今天也算）
    if kind == "after":
        try:
            n = cn_int(g[0])
        except ValueError:
            return None
        return today + _timedelta(days=n if g[1] == "天" else 7 * n)
    if kind == "day":
        d = int(g[0])
        found = _safe_date(today.year, today.month, d)
        if found is not None and found >= today:
            return found
        y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        return _safe_date(y, mo, d)
    return None


def _standalone(text: str, m) -> bool:
    """前後是空白或句子頭尾（『今天的事 今天』裡後面那個才是日期）。"""
    return (m.start() == 0 or text[m.start() - 1].isspace()) and (m.end() == len(text) or text[m.end()].isspace())


def _first_date(text: str, today):
    """日期寫法 → (kind, match)：前後有空白的優先，其次最前面的；同一個位置取最長的。"""
    best = None
    for kind, pattern in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            key = (0 if _standalone(text, m) else 1, m.start(), -(m.end() - m.start()))
            if best is None or key < best[0]:
                best = (key, kind, m)
    return (best[1], best[2]) if best else (None, None)


def _apply_period(period: str, hour: int, evening: bool) -> int:
    if period in ("下午", "晚上", "傍晚", "晚") or (evening and not period):
        return hour + 12 if hour < 12 else hour
    if period == "中午":
        return hour + 12 if hour < 3 else hour
    if period in ("凌晨", "半夜") and hour == 12:
        return 0
    return hour


def _match_time(text: str, evening: bool, pos_only: bool = False):
    """第一個時間寫法 → (start, end, (開始, 結束) 位置) 或 None。pos_only：只認從開頭開始的（區間的後半）。"""
    found = []
    for pattern, kind in ((_TIME_HM, "hm"), (_TIME_CN, "cn"), (_TIME_AMPM, "ampm")):
        m = pattern.match(text) if pos_only else pattern.search(text)
        if m:
            found.append((m.start(), kind, m))
    if not found:
        return None
    found.sort(key=lambda t: (t[0], -(t[2].end() - t[2].start())))     # 同一個位置取最長的（2:30pm 不是 2:30）
    _pos, kind, m = found[0]
    try:
        if kind == "hm":
            period, hour, minute = m.group(1) or "", int(m.group(2)), int(m.group(3))
            hour = _apply_period(period, hour, evening)
        elif kind == "cn":
            period, hour = m.group(1) or "", cn_int(m.group(2))
            half, mins = m.group(3), m.group(4)
            minute = 30 if half == "半" else (cn_int(mins) if mins else 0)
            hour = _apply_period(period, hour, evening)
        else:
            hour, minute = int(m.group(1)), int(m.group(2) or 0)
            if hour > 12:
                return "bad", None, (m.start(), m.end())
            hour = (hour % 12) + (12 if m.group(3).lower() == "p" else 0)
    except ValueError:
        return "bad", None, (m.start(), m.end())
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return "bad", None, (m.start(), m.end())
    return f"{hour:02d}:{minute:02d}", m.group(1) if kind != "ampm" else "", (m.start(), m.end())


def _cut(text: str, start: int, end: int) -> str:
    return text[:start] + " " + text[end:]


def _tidy(text: str) -> str:
    text = _re.sub(r"\s+", " ", text).strip(" ，,、：:")
    if text.startswith("的"):                     # 「明天的會議」拿掉明天 → 「的會議」
        text = text[1:]
    return text.strip(" ，,、：:")


def parse_when(text: str, today) -> When:
    """在一句話裡找一個日期、一個時間（或時間區間），拿掉之後剩下的當標題。

    日期：2026-11-12、2026/11/12、11/12、11月12日、今天、明天、後天、大後天、今晚、明早、
         週五／星期五／禮拜五（最近的那一天，今天也算）、這週五、下週一、下下週三、3天後、2週後、15號。
    時間：14:00、14:00-15:30、下午2點、下午兩點半、晚上8點15分、9am、2:30pm、中午（12:00）。
    沒寫年的日期已經過了就算明年；『15號』過了就算下個月。"""
    w = When(rest=text or "")
    rest = w.rest
    kind, m = _first_date(rest, today)
    evening = False
    if m is not None:
        day = _date_from(kind, m, today)
        if day is None:
            w.error = f"「{m.group(0)}」不是真的日期"
            return w
        w.day = day
        evening = m.group(0) in _EVENING_WORDS
        rest = _cut(rest, m.start(), m.end())
    hit = _match_time(rest, evening)
    if hit is not None:
        start, period, (a, b) = hit
        if start == "bad":
            w.error = f"「{rest[a:b].strip()}」不是真的時間"
            return w
        w.start = start
        tail = rest[b:]
        sep = _RANGE_SEP.match(tail)
        if sep:
            second = _match_time(tail[sep.end():], evening or period in ("下午", "晚上", "傍晚", "晚"), pos_only=True)
            if second is not None and second[0] != "bad":
                end = second[0]
                if end <= start and int(end[:2]) < 12:            # 「下午2點到4點」：後半沒寫下午
                    end = f"{int(end[:2]) + 12:02d}{end[2:]}"
                if end > start:
                    w.end = end
                    b = b + sep.end() + second[2][1]
        rest = _cut(rest, a, b)
    elif _NOON.search(rest):
        noon = _NOON.search(rest)
        w.start = "12:00"
        rest = _cut(rest, noon.start(), noon.end())
    w.rest = _tidy(rest)
    return w


def check_ymd(value: str):
    """Field(check=…)：YYYY-MM-DD。回錯誤訊息或 None。"""
    m = _re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value or "")
    if not m or _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))) is None:
        return "要是 YYYY-MM-DD（例如 2026-11-12）"
    return None


def day_label(day, today) -> str:
    """'今天 11/09（一）'、'明天 11/10（二）'、'11/14（六）'；不同年加年份。"""
    names = {0: "今天", 1: "明天", 2: "後天", -1: "昨天"}
    diff = (day - today).days
    base = f"{day.month:02d}/{day.day:02d}（{WEEK_NAMES[day.weekday()]}）"
    if day.year != today.year:
        base = f"{day.year}/" + base
    return f"{names[diff]} {base}" if diff in names else base
# <<< zhdate


# ── Todoist API v1 ─────────────────────────────────────────────────────

class TodoistError(Exception):
    """給人看的錯誤（中文）。auth=True：token 不對或被撤銷；missing=True：找不到那個東西。"""

    def __init__(self, message: str, *, auth: bool = False, missing: bool = False):
        super().__init__(message)
        self.auth = auth
        self.missing = missing


class Client:
    """Todoist API v1 的一小部分。只連 API（https://api.todoist.com/api/v1）；token 只放在 Authorization header。"""

    def __init__(self, token: str, session=None):
        self.token = token
        self.session = session if session is not None else (HTTP if HTTP is not None else requests.Session())

    def call(self, method: str, path: str, *, params=None, body=None):
        try:
            r = self.session.request(method, f"{API}/{path}", params=params, json=body, timeout=TIMEOUT,
                                     headers={"Authorization": f"Bearer {self.token}"}, allow_redirects=False)
        except requests.Timeout:
            raise TodoistError("Todoist 沒有回應（逾時），等一下再試。")
        except requests.RequestException:
            raise TodoistError("連不上 Todoist（網路斷了？），等一下再試。")
        status = r.status_code
        if status == 204:
            return None
        if 200 <= status < 300:
            if not (r.content or b"").strip():
                return None
            try:
                return r.json()
            except ValueError:
                raise TodoistError("Todoist 回了看不懂的東西。")
        if status in (401, 403):
            raise TodoistError("Todoist 不收這個 token（打錯了、或被撤銷了）。用 /todoist_token 重新設定。", auth=True)
        if status == 404:
            raise TodoistError("Todoist 找不到這一項（可能已經完成或刪掉了）。", missing=True)
        if status == 429:
            wait = str(r.headers.get("Retry-After") or "").strip()
            raise TodoistError(f"Todoist 說太頻繁了，{wait + ' 秒後' if wait.isdigit() else '等一下'}再試。")
        if 400 <= status < 500:
            raise TodoistError(f"Todoist 不接受這個要求（{status}）：{_error_text(r)}")
        raise TodoistError(f"Todoist 那邊出錯了（{status}），等一下再試。")

    def pages(self, path: str, params=None) -> list:
        """v1 的分頁：{"results": [...], "next_cursor": "…"|null}，照 cursor 一頁一頁讀（最多 MAX_PAGES 頁）。"""
        out, cursor = [], None
        for _ in range(MAX_PAGES):
            query = dict(params or {}, limit=PAGE_LIMIT)
            if cursor:
                query["cursor"] = cursor
            data = self.call("GET", path, params=query) or {}
            if isinstance(data, list):                  # 保險：舊格式直接回清單
                return out + data
            out += list(data.get("results") or [])
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return out

    def tasks(self, **params) -> list:
        return self.pages("tasks", {k: v for k, v in params.items() if v})

    def filter(self, query: str) -> list:
        return self.pages("tasks/filter", {"query": query})

    def task(self, task_id: str) -> dict:
        return self.call("GET", f"tasks/{_safe_id(task_id)}") or {}

    def add(self, body: dict) -> dict:
        return self.call("POST", "tasks", body=body) or {}

    def update(self, task_id: str, body: dict) -> dict:
        return self.call("POST", f"tasks/{_safe_id(task_id)}", body=body) or {}

    def close(self, task_id: str) -> None:
        self.call("POST", f"tasks/{_safe_id(task_id)}/close")

    def delete(self, task_id: str) -> None:
        self.call("DELETE", f"tasks/{_safe_id(task_id)}")

    def projects(self) -> list:
        return self.pages("projects")

    def labels(self) -> list:
        return self.pages("labels")


def _error_text(r) -> str:
    try:
        data = r.json()
        text = data.get("error") if isinstance(data, dict) else ""
    except ValueError:
        text = ""
    text = str(text or getattr(r, "text", "") or "").strip().replace("\n", " ")
    return text[:200] or "沒有說原因"


def _safe_id(task_id: str) -> str:
    """任務 id 會放進網址：只收英數字、-、_（擋 ../ 之類）。"""
    task_id = str(task_id or "").strip()
    if not TASK_ID_RE.match(task_id):
        raise TodoistError(f"「{task_id[:40]}」不是 Todoist 的任務編號。", missing=True)
    return task_id


# ── 寫法（跟 todo pack 對齊） ───────────────────────────────────────────

_BANG = _re.compile(r"(?:^|(?<=\s))([!！]{1,3})(?=\s|$)|^([!！]{1,3})(?=\S)")
_TAG = _re.compile(r"(?:^|(?<=\s))([#＃@＠])([^\s#＃@＠!！]{1,60})")
PRIORITY_MARK = {4: "‼️", 3: "❗"}
TO_TODOIST = {0: 1, 1: 3, 2: 4}                 # SYNOX 的 0／1／2（普通／重要／很重要）→ Todoist 的 1／3／4（4＝p1 最緊急）
FILTERS = ("all", "today", "overdue")


def check_filter(value: str):
    v = value.strip().lower()
    if v in FILTERS or (v[:1] in ("#", "＃", "@", "＠") and len(v) > 1):
        return None
    return "只能是 all、today、overdue、#專案 或 @標籤"


def check_priority(value: str):
    return None if value.strip() in ("0", "1", "2", "!", "!!") else "要是 0、1、2（或 !、!!）"


def check_ref(value: str):
    v = value.strip().lstrip("[").rstrip("]")
    return None if TASK_ID_RE.match(v) else "要是清單上的編號（例如 3）"


def split_todo(text: str, today):
    """'!! 繳電費 明天 #家事 @電話' → (標題, 重要度 0–2, [#名字], [@名字], When)。"""
    priority = 0
    for m in _BANG.finditer(text):
        priority = max(priority, min(2, len(m.group(1) or m.group(2))))
    text = _BANG.sub(" ", text)
    hashes, ats = [], []
    for mark, name in _TAG.findall(text):
        (ats if mark in "@＠" else hashes).append(name)
    text = _TAG.sub(" ", text)
    w = parse_when(text, today)
    return w.rest, priority, list(dict.fromkeys(hashes)), list(dict.fromkeys(ats)), w


def due_fields(w, today) -> dict:
    """parse_when 的結果 → Todoist 的 due_date／due_datetime（沒有時區＝跟著使用者的 Todoist 時區走）。"""
    day = w.day or (today if w.start else None)
    if day is None:
        return {}
    if w.start:
        return {"due_datetime": f"{day.isoformat()}T{w.start}:00"}
    return {"due_date": day.isoformat()}


def due_from_text(value: str, today):
    """使用者寫的到期 → (Todoist 欄位, 錯誤)。看得懂的中文日期自己換；看不懂的原樣給 Todoist（due_string）。"""
    value = (value or "").strip()
    if value.lower() in NO_DATE_WORDS:
        return {"due_string": "no date"}, ""
    w = parse_when(value, today)
    if w.error:
        return {}, w.error
    if w.day is None and w.start is None:
        return {"due_string": value}, ""
    return due_fields(w, today), ""


def task_due(t: dict):
    """Todoist 任務的 due → (date|None, 'HH:MM'|'', 重複嗎)。v1 的 due.date 有時間時是 2026-11-12T15:00:00。"""
    due = t.get("due") or {}
    raw = str(due.get("datetime") or due.get("date") or "")
    try:
        day = date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        day = None
    hhmm = raw[11:16] if len(raw) >= 16 and raw[10] in "T " else ""
    return day, hhmm, bool(due.get("is_recurring"))


def sort_key(t: dict, n: int):
    day, hhmm, _ = task_due(t)
    return (day.isoformat() if day else "9999-99-99", hhmm or "99:99", -int(t.get("priority") or 1), n)


def due_label(t: dict, today) -> str:
    day, hhmm, recurring = task_due(t)
    if day is None:
        return ""
    label = day_label(day, today) + (f" {hhmm}" if hhmm else "") + (" 🔁" if recurring else "")
    if day < today and not t.get("checked"):
        return f"⚠️逾期 {label}"
    return label


def line(t: dict, n, today, projects=None) -> str:
    parts = [f"{'☑' if t.get('checked') else '☐'} [{n}]"]
    mark = PRIORITY_MARK.get(int(t.get("priority") or 1))
    if mark:
        parts.append(mark)
    parts.append(str(t.get("content") or "（沒有標題）"))
    due = due_label(t, today)
    if due:
        parts.append("· " + due)
    project = (projects or {}).get(t.get("project_id"))
    if project and not project.get("inbox_project"):
        parts.append(f"#{project.get('name')}")
    parts += [f"@{x}" for x in t.get("labels") or []]
    return " ".join(parts)


def _same(a: str, b: str) -> bool:
    return str(a or "").strip().casefold() == str(b or "").strip().casefold()


# ── 指令 ───────────────────────────────────────────────────────────────

def install(app, pack):
    g = pack.group
    cmd = g.node.command                            # /todoist
    kit.redact_in_logs(f"{cmd}_token")          # token 不准出現在 [ROUTE] 那一行 log

    def store(user):
        return pack.store.of(user)

    def data(user) -> dict:
        return store(user).load(None) or {}

    def client(api, chat_id, user):
        token = data(user).get("token")
        if not token:
            api.send_message(chat_id, f"🔌 {SETUP_HINT}")
            return None
        return Client(token)

    def number(user, tasks) -> dict:
        """每個任務的短號（第一次看到就配一個，之後不變）。回 {task_id: n}。"""
        ids = [str(t.get("id")) for t in tasks if t.get("id")]

        def assign(d):
            table = d.setdefault("ids", {})
            for tid in ids:
                if tid not in table:
                    table[tid] = int(d.get("next_n") or 1)
                    d["next_n"] = table[tid] + 1
            if len(table) > MAX_IDS:
                keep = set(ids)
                for tid, _n in sorted(table.items(), key=lambda kv: kv[1]):
                    if len(table) <= MAX_IDS:
                        break
                    if tid not in keep:
                        del table[tid]
            return {tid: table[tid] for tid in ids}

        return store(user).update(assign, {})

    def forget(user, task_id: str) -> None:
        store(user).update(lambda d: d.setdefault("ids", {}).pop(task_id, None), {})

    def resolve(user, ref: str) -> str:
        """[3]／3 → Todoist 的任務 id（照編號對照表）；不是短號就當 Todoist 原本的 id。"""
        ref = ref.strip().lstrip("[").rstrip("]")
        if ref.isdigit():
            for tid, n in (data(user).get("ids") or {}).items():
                if n == int(ref):
                    return tid
            if len(ref) < 8:                         # 短號但對照表沒有：說清楚，不要拿去當 Todoist 的 id 亂打
                raise TodoistError(f"沒有 [{ref}] 這一項（先 {cmd}_list 看編號）。", missing=True)
        return _safe_id(ref)

    def projects_by_id(c) -> dict:
        return {p.get("id"): p for p in c.projects()}

    def run(api, chat_id, user, work):
        """work(c) 回要送的字；Todoist 的錯誤一律變成一句中文。"""
        c = client(api, chat_id, user)
        if c is None:
            return
        try:
            text = work(c)
        except TodoistError as e:
            text = f"❌ {e}"
        if text:
            api.send_message(chat_id, text)

    # ── /todoist <內容>：加一項 ─────────────────────────────────────────
    def add(api, chat_id, user, values):
        today = now().date()
        title, priority, hashes, ats, w = split_todo(values["text"].strip(), today)
        due = due_fields(w, today) if not w.error else {}
        if w.error:
            api.send_message(chat_id, f"❌ {w.error}。")
            return
        if values.get("due"):
            due, problem = due_from_text(values["due"], today)
            if problem:
                api.send_message(chat_id, f"❌ {problem}。")
                return
        if values.get("priority"):
            p = values["priority"].strip()
            priority = len(p) if p.startswith("!") else int(p)
        if not title:
            api.send_message(chat_id, f"❌ 要寫做什麼。例：{cmd} 繳電費 明天")
            return

        def work(c):
            body = {"content": title, **due}
            if priority:
                body["priority"] = TO_TODOIST[priority]
            labels = list(ats)
            projects = projects_by_id(c) if hashes else {}
            for name in hashes:
                found = next((p for p in projects.values() if _same(p.get("name"), name)), None)
                if found is not None and "project_id" not in body:
                    body["project_id"] = found.get("id")
                else:
                    labels.append(name)
            if labels:
                body["labels"] = list(dict.fromkeys(labels))
            t = c.add(body)
            n = number(user, [t]).get(str(t.get("id")), "?")
            return f"✅ 加到 Todoist 了：{line(t, n, today, projects)}"

        run(api, chat_id, user, work)

    # ── /todoist_list ──────────────────────────────────────────────────
    def list_(api, chat_id, user, values):
        today = now().date()
        which = (values.get("filter") or "").strip()
        key = which.lower()

        def work(c):
            projects = projects_by_id(c)
            if key == "today":
                title, rows = "今天到期", c.filter("today")
            elif key == "overdue":
                title, rows = "逾期的待辦", c.filter("overdue")
            elif which[:1] in ("#", "＃"):
                name = which[1:]
                project = next((p for p in projects.values() if _same(p.get("name"), name)), None)
                if project is not None:
                    title, rows = f"#{project.get('name')} 還沒做完", c.tasks(project_id=project.get("id"))
                else:
                    title, rows = f"@{name} 還沒做完", c.tasks(label=name)
            elif which[:1] in ("@", "＠"):
                title, rows = f"@{which[1:]} 還沒做完", c.tasks(label=which[1:])
            else:
                title = "全部待辦（Todoist 只列還沒做完的）" if key == "all" else "還沒做完"
                rows = c.tasks()
            if not rows:
                return f"✅ {title}：沒有。🎉" if which else f"✅ {title}：沒有待辦。用 {cmd} 繳電費 明天 加一項。"
            nums = number(user, rows)
            rows = sorted(rows, key=lambda t: sort_key(t, nums.get(str(t.get("id")), 0)))
            out = [f"✅ {title}（{len(rows)} 項）"]
            out += [line(t, nums.get(str(t.get("id")), "?"), today, projects) for t in rows[:SHOW]]
            if len(rows) > SHOW:
                out.append(f"…還有 {len(rows) - SHOW} 項（用 today、overdue、#專案 縮小範圍）")
            return "\n".join(out)

        run(api, chat_id, user, work)

    # ── /todoist_done <編號> ────────────────────────────────────────────
    def done(api, chat_id, user, values):
        def work(c):
            tid = resolve(user, values["n"])
            t = c.task(tid)
            if t.get("checked"):
                return f"[{values['n']}] 早就完成了：{t.get('content')}"
            c.close(tid)
            if task_due(t)[2]:
                after = c.task(tid)
                return f"☑ 完成這一次：{t.get('content')}（🔁 重複的待辦，下一次：{due_label(after, now().date()) or '—'}）"
            forget(user, tid)
            return f"☑ 完成：{t.get('content')}"

        run(api, chat_id, user, work)

    # ── /todoist_due <編號> <到期>：改期 ────────────────────────────────
    def reschedule(api, chat_id, user, values):
        today = now().date()
        due, problem = due_from_text(values["due"], today)
        if problem:
            api.send_message(chat_id, f"❌ {problem}。")
            return

        def work(c):
            tid = resolve(user, values["n"])
            t = c.update(tid, due)
            n = number(user, [t]).get(str(t.get("id")), values["n"])
            verb = "拿掉到期" if due.get("due_string") == "no date" else "改期"
            return f"📅 {verb}了：{line(t, n, today)}"

        run(api, chat_id, user, work)

    # ── /todoist_rm <編號> ──────────────────────────────────────────────
    def rm(api, chat_id, user, values):
        def work(c):
            tid = resolve(user, values["n"])
            t = c.task(tid)
            c.delete(tid)
            forget(user, tid)
            return f"🗑 從 Todoist 刪掉了：{t.get('content')}"

        run(api, chat_id, user, work)

    # ── 專案、標籤 ─────────────────────────────────────────────────────
    def projects_(api, chat_id, user, values):
        def work(c):
            rows = c.projects()
            if not rows:
                return "📁 Todoist 沒有專案。"
            names = [f"• {p.get('name')}" + ("（收件匣）" if p.get("inbox_project") else "") for p in rows]
            return "\n".join([f"📁 Todoist 的專案（{len(rows)} 個）；加待辦時寫 #專案名"] + names[:50])

        run(api, chat_id, user, work)

    def labels_(api, chat_id, user, values):
        def work(c):
            rows = c.labels()
            if not rows:
                return "🏷 Todoist 沒有標籤。加待辦時寫 @標籤 就會用那個標籤。"
            return "\n".join([f"🏷 Todoist 的標籤（{len(rows)} 個）；加待辦時寫 @標籤"] +
                             [f"• @{x.get('name')}" for x in rows[:50]])

        run(api, chat_id, user, work)

    # ── 設定：token ────────────────────────────────────────────────────
    def token(api, chat_id, user, values):
        value = (values.get("token") or "").strip()
        if not value:
            saved = data(user).get("token")
            api.send_message(chat_id, ("🔌 Todoist 已經接上了（token 存在保管箱，密文）。換 token："
                                       f"{cmd}_token <新的>；拔掉：{cmd}_logout") if saved else f"🔌 {SETUP_HINT}")
            return
        if not TOKEN_RE.match(value):
            api.send_message(chat_id, "❌ 這看起來不是 Todoist 的 API token（應該是一串 40 個英數字）。")
            return
        try:
            count = len(Client(value).projects())
        except TodoistError as e:
            api.send_message(chat_id, f"❌ 沒存：{e}")
            return
        store(user).update(lambda d: d.update(token=value), {})
        api.send_message(chat_id, f"✅ 接上 Todoist 了（看得到 {count} 個專案）。token 加密存在這台電腦的保管箱。\n"
                                  f"建議把你剛剛貼 token 的那則訊息刪掉。試試 {cmd}_list")

    def logout(api, chat_id, user, values):
        had = bool(data(user).get("token"))
        store(user).save({})
        api.send_message(chat_id, "🔌 拔掉了：這台電腦不再存你的 Todoist token（Todoist 那邊的待辦不受影響）。"
                         "要讓那個 token 完全失效，到 Todoist 設定 → 整合 → 開發者 按「重新產生」。" if had
                         else "本來就沒有接上 Todoist。")

    ref = Field("n", "編號（清單上 [3] 的 3）", required=True, check=check_ref)
    kit.command(g, "add", add, "加一項到 Todoist（!! 重要、#專案、@標籤、明天到期）", default=True, effect=WRITE,
                positional=1, usage="<內容>（例：!! 繳電費 明天 #家事） [due=…] [priority=0|1|2]",
                fields=[Field("text", "要做的事（可以帶 !、!!、#專案、@標籤、到期）", required=True),
                        Field("due", "到期（明天、11/20、2026-11-20 15:00、every monday…）"),
                        Field("priority", "重要度 0／1／2", check=check_priority)])
    kit.command(g, "list", list_, "看 Todoist 的待辦（today 今天、overdue 逾期、#專案、@標籤）",
                fields=[Field("filter", "all／today／overdue／#專案／@標籤（不寫＝全部還沒做完的）", check=check_filter)])
    kit.command(g, "done", done, "在 Todoist 打勾完成一項（編號看清單）", effect=WRITE, fields=[ref])
    kit.command(g, "due", reschedule, "改期（例：/todoist_due 3 下週一；寫「無」拿掉到期）", effect=WRITE,
                fields=[ref, Field("due", "新的到期（明天、11/20、下午3點、every monday；「無」＝拿掉）", required=True)])
    kit.command(g, "rm", rm, "從 Todoist 刪掉一項（刪了救不回來）", effect=DANGER, fields=[ref])
    kit.command(g, "projects", projects_, "看 Todoist 的專案")
    kit.command(g, "labels", labels_, "看 Todoist 的標籤")
    kit.command(g, "token", token, "設定 Todoist 的 API token（只給人打，不給 AI）", effect=WRITE, ai=False,
                usage="<API token>（Todoist 設定 → 整合 → 開發者）",
                fields=[Field("token", "Todoist 的 API token")])
    kit.command(g, "logout", logout, "拔掉 Todoist（刪掉這台電腦存的 token）", effect=WRITE, ai=False)
