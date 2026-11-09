"""📅 Google 日曆 connector：直接打 Google Calendar API v3（REST），只用 requests＋標準函式庫。

指令跟 SYNOXPacks 的本機 calendar pack 對齊（葉節點名字、欄位一樣，只是群組 gcal 換成 cal 就能互換）：
    /gcal <時間 標題>、/gcal_today、/gcal_week、/gcal_list [n]、/gcal_rm <編號>
連接（只給人打，ai=False，AI 永遠碰不到憑證）：
    /gcal_setup <client_id> <client_secret> [readonly]   → 回一個 Google 登入連結
    /gcal_code <整串網址或授權碼>                       → 換到 refresh token，存進保管箱
    /gcal_token <refresh_token>                           → 另一條路：直接貼 refresh token
    /gcal_status、/gcal_logout

OAuth（見 README）：
- Google 的 device flow 不收 Calendar 的 scope；OOB（urn:ietf:wg:oauth:2.0:oob）已停用。
  所以用「桌面應用程式」client＋loopback 轉址網址＋PKCE，但 **SYNOX 不開任何埠**：Google 把瀏覽器轉到
  http://127.0.0.1:47231/?code=…，那裡沒有人在聽，瀏覽器顯示「無法連上」；使用者把網址列整串貼回來。
  就算這台電腦上剛好有別的程式在聽那個埠，拿到 code 也沒用（沒有 PKCE 的 code_verifier 換不到 token）。
- state 隨機 32 bytes、15 分鐘內有效、只能用一次；網址裡的 state 不符就不換。
- client_id／client_secret／refresh_token／access_token 都經 pack.store.of(user)（storage=vault → 密文
  data/google-calendar.json.enc）；不寫 config.json、不寫 log、不出現在任何回覆或 AI 的工具結果。

日期解析（parse_when、day_label…）是 SYNOXPacks `packs/_shared/zhdate.py` 的原樣複製（pack 不能互相 import），
跟本機 calendar pack 同一套寫法。改的話改正本、再照抄過來。

測試換掉 `transport`（要有 request(method, url, **kw)）、`now()`、`local_tz()`；不連真的 Google。
"""

import base64
import hashlib
import secrets
import time
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

from isdtelekit.core.registry import DANGER, WRITE, Field

from synox.packs import kit

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
REDIRECT_URI = "http://127.0.0.1:47231/"         # 沒有人在聽（SYNOX 不開埠）；使用者把轉過去的網址貼回來
SCOPES = {"full": "https://www.googleapis.com/auth/calendar.events",
          "readonly": "https://www.googleapis.com/auth/calendar.events.readonly"}
PENDING_SECONDS = 15 * 60
TIMEOUT = 20
MAX_LIST = 50
MAX_TITLE = 200

transport = None                                 # 測試換成假的；None＝requests


def now() -> datetime:
    """現在時間（測試換掉這一個）。"""
    return datetime.now()


def local_tz():
    """行程的時區。None＝這台電腦的當地時間（含日光節約）；測試換成固定的 timezone。"""
    return None


def _http():
    return transport if transport is not None else requests


class GoogleError(Exception):
    """要回給使用者的一句話（不含任何憑證）。"""


class NotConnected(GoogleError):
    pass


# >>> zhdate（正本 packs/_shared/zhdate.py；不要直接改這段，改正本再跑 scripts/sync_shared.py）
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


DEFAULT_MINUTES = 60
_TIME_RANGE = _re.compile(r"^(\d{1,2}):(\d{2})(?:\s*[-~～]\s*(\d{1,2}):(\d{2}))?$")
_CLIENT_ID = _re.compile(r"^[A-Za-z0-9._-]{10,200}\.apps\.googleusercontent\.com$")
_TOKENISH = _re.compile(r"^[A-Za-z0-9._~/+=-]{8,2048}$")
NOT_CONNECTED = ("還沒連上 Google 日曆。設定步驟見 connectors/google-calendar/README.md：\n"
                 "1. /gcal_setup <client_id> <client_secret>\n2. 照回覆打開連結、按允許\n3. /gcal_code <瀏覽器網址列整串網址>")


def check_time(value: str):
    """Field(check=…)：HH:MM 或 HH:MM-HH:MM（跟 calendar pack 一樣）。"""
    m = _TIME_RANGE.match(value.strip())
    if not m:
        return "要是 HH:MM 或 HH:MM-HH:MM（例如 14:00-15:30）"
    nums = [int(x) for x in m.groups() if x is not None]
    if any(h > 23 for h in nums[0::2]) or any(mm > 59 for mm in nums[1::2]):
        return "不是真的時間"
    if len(nums) == 4 and (nums[2], nums[3]) <= (nums[0], nums[1]):
        return "結束要比開始晚"
    return None


def plus_minutes(hhmm: str, minutes: int) -> str:
    h, m = int(hhmm[:2]), int(hhmm[3:])
    total = max(0, min(h * 60 + m + minutes, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


def _clean(text, limit: int = MAX_TITLE) -> str:
    """Google 來的字：拿掉控制字元、換行變空白、太長截掉（標題可能是別人邀請你時寫的，當資料不當指令）。"""
    text = "".join(" " if ch in "\r\n\t" else ch for ch in str(text or "") if ch >= " " or ch in "\r\n\t")
    text = _re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


# ── 時間 ↔ RFC 3339 ─────────────────────────────────────────────────────

def aware(day: date, hhmm: str = "00:00") -> datetime:
    naive = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
    tz = local_tz()
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


def to_local(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    tz = local_tz()
    return dt.astimezone(tz) if tz is not None else dt.astimezone()


def to_row(item: dict) -> dict:
    """Google 的 event → 跟 calendar pack 一樣的那幾個欄位（day、start、end、all_day、title、location）。"""
    start, end = item.get("start") or {}, item.get("end") or {}
    row = {"id": str(item.get("id", "")), "title": _clean(item.get("summary")) or "（沒有標題）",
           "location": _clean(item.get("location"), 80)}
    if start.get("dateTime"):
        s = to_local(start["dateTime"])
        row.update(day=s.date().isoformat(), start=s.strftime("%H:%M"), all_day=False, end="")
        if end.get("dateTime"):
            e = to_local(end["dateTime"])
            row["end"] = e.strftime("%H:%M") if e.date() == s.date() else f"{e.month}/{e.day} {e.strftime('%H:%M')}"
    else:
        row.update(day=str(start.get("date") or "")[:10], start="", end="", all_day=True)
    return row


def line(row: dict, today: date, n=None, with_day: bool = True) -> str:
    """'[3] 明天 11/10（二） 14:00–15:00 看牙醫 @診所'（跟 calendar pack 同一種樣子）。"""
    parts = [f"[{n}]"] if n is not None else []
    if with_day:
        try:
            parts.append(day_label(date.fromisoformat(row["day"]), today))
        except ValueError:
            parts.append(row["day"])
    parts.append("整天" if row.get("all_day") else row["start"] + (f"–{row['end']}" if row.get("end") else ""))
    parts.append(row["title"])
    if row.get("location"):
        parts.append(f"@{row['location']}")
    return " ".join(parts)


# ── OAuth ───────────────────────────────────────────────────────────────

def pkce_pair():
    verifier = secrets.token_urlsafe(64)                              # 86 字（規定 43–128）
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def auth_url(client_id: str, scope: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT_URI, "response_type": "code", "scope": scope,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


def parse_pasted(text: str):
    """使用者貼的東西 → (code, state, error)。整串網址、只有 ?code=… 的那一段、或只有授權碼都收。"""
    text = (text or "").strip().strip("<>\"'")
    if "code=" in text or "error=" in text:
        query = urlparse(text).query if "://" in text else text.split("?", 1)[-1]
        q = parse_qs(query)
        return (q.get("code") or [""])[0], (q.get("state") or [""])[0], (q.get("error") or [""])[0]
    return text, "", ""


def _post_token(data: dict) -> dict:
    try:
        r = _http().request("POST", TOKEN_URL, data=data, timeout=TIMEOUT)
    except requests.RequestException:
        raise GoogleError("連不上 Google（網路有問題？等一下再試）。")
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200:
        err = str(body.get("error") or r.status_code)
        if err == "invalid_grant":
            raise NotConnected("Google 不再接受這個授權（被收回、過期，或 app 還在「測試」狀態時 7 天就失效）。"
                               "請重新 /gcal_setup 連一次。")
        if err == "invalid_client":
            raise GoogleError("Google 說 client_id／client_secret 不對。請檢查後重新 /gcal_setup。")
        raise GoogleError(f"Google 拒絕了（{_clean(err, 60)}）。")
    if not isinstance(body, dict) or not body.get("access_token"):
        raise GoogleError("Google 的回應看不懂（沒有 access_token）。")
    return body


class Client:
    """一個人的 Google 日曆連線。憑證只在 store（保管箱）裡。"""

    def __init__(self, store):
        self.store = store

    def data(self) -> dict:
        return self.store.load(None) or {}

    def connected(self) -> bool:
        return bool(self.data().get("refresh_token"))

    def readonly(self) -> bool:
        return self.data().get("scope") == SCOPES["readonly"]

    def calendar(self) -> str:
        return self.data().get("calendar") or "primary"

    def _save_token(self, body: dict) -> str:
        def put(d):
            d["access_token"] = body["access_token"]
            d["expires_at"] = time.time() + int(body.get("expires_in") or 3600)
            if body.get("refresh_token"):
                d["refresh_token"] = body["refresh_token"]
        self.store.update(put, {})
        return body["access_token"]

    def forget_tokens(self) -> None:
        def drop(d):
            for k in ("refresh_token", "access_token", "expires_at"):
                d.pop(k, None)
        self.store.update(drop, {})

    def token(self, force: bool = False) -> str:
        d = self.data()
        if not d.get("refresh_token"):
            raise NotConnected(NOT_CONNECTED)
        if not force and d.get("access_token") and float(d.get("expires_at") or 0) > time.time() + 60:
            return d["access_token"]
        try:
            body = _post_token({"client_id": d.get("client_id", ""), "client_secret": d.get("client_secret", ""),
                                "refresh_token": d["refresh_token"], "grant_type": "refresh_token"})
        except NotConnected:
            self.forget_tokens()
            raise
        return self._save_token(body)

    def call(self, method: str, path: str, params=None, body=None):
        for attempt in (0, 1):
            headers = {"Authorization": "Bearer " + self.token(force=attempt == 1), "Accept": "application/json"}
            try:
                r = _http().request(method, API + path, params=params, json=body, headers=headers, timeout=TIMEOUT)
            except requests.RequestException:
                raise GoogleError("連不上 Google（網路有問題？等一下再試）。")
            if r.status_code == 401 and attempt == 0:
                continue                                      # access token 剛好過期：換一個再試一次
            break
        if r.status_code in (200, 201):
            try:
                return r.json()
            except ValueError:
                raise GoogleError("Google 的回應看不懂。")
        if r.status_code == 204:
            return {}
        if r.status_code == 401:
            raise NotConnected("Google 的授權失效了，請重新 /gcal_setup。")
        if r.status_code == 403:
            raise GoogleError("Google 說沒有權限（唯讀模式？或這個日曆不是你的）。")
        if r.status_code in (404, 410):
            raise GoogleError("Google 那邊找不到（可能已經被刪掉了）。")
        if r.status_code == 429 or r.status_code >= 500:
            raise GoogleError("Google 現在忙不過來，等一下再試。")
        raise GoogleError(f"Google 回了錯誤（HTTP {r.status_code}）。")

    def events_path(self, event_id: str = "") -> str:
        p = f"/calendars/{quote(self.calendar(), safe='')}/events"
        return p + (f"/{quote(event_id, safe='')}" if event_id else "")

    def list_events(self, start: datetime, end=None, limit: int = MAX_LIST) -> list:
        params = {"timeMin": start.isoformat(), "singleEvents": "true", "orderBy": "startTime",
                  "maxResults": str(max(1, min(limit, 250)))}
        if end is not None:
            params["timeMax"] = end.isoformat()
        items = (self.call("GET", self.events_path(), params=params) or {}).get("items") or []
        return [to_row(i) for i in items if isinstance(i, dict) and i.get("status") != "cancelled"][:limit]


def install(app, pack):
    g = pack.group

    def client(user) -> Client:
        return Client(pack.store.of(user))

    def guarded(fn):
        """連線、Google 的錯誤 → 一句話給使用者（也是 AI 拿到的工具結果）；不會帶出任何憑證。"""
        def run(api, chat_id, user, values):
            try:
                fn(api, chat_id, user, values)
            except GoogleError as e:
                api.send_message(chat_id, f"❌ {e}")
        return run

    def remember(user, rows) -> None:
        """這次列出來的編號 → Google 的 event id（/gcal_rm 用）。"""
        keep = [{"n": i, "id": r["id"], "day": r["day"]} for i, r in enumerate(rows[:MAX_LIST], 1)]
        pack.store.of(user).update(lambda d: d.__setitem__("last_list", keep), {})

    def show(api, chat_id, user, header, rows, today, empty_text, with_day=True):
        remember(user, rows)
        if not rows:
            api.send_message(chat_id, f"{header}\n{empty_text}")
            return
        api.send_message(chat_id, "\n".join([header] + [line(r, today, i, with_day) for i, r in enumerate(rows, 1)]))

    # ── 行程（跟 calendar pack 一樣的指令） ──

    def add(api, chat_id, user, values):
        c = client(user)
        if not c.connected():
            raise NotConnected(NOT_CONNECTED)
        if c.readonly():
            raise GoogleError("現在是唯讀模式，不能加行程（要加就 /gcal_setup … full 重新連一次）。")
        today = now().date()
        text = values["text"].strip()
        if values.get("date"):
            day = date.fromisoformat(values["date"])
            start = end = None
            if values.get("time"):
                m = _TIME_RANGE.match(values["time"].strip())
                start = f"{int(m.group(1)):02d}:{m.group(2)}"
                end = f"{int(m.group(3)):02d}:{m.group(4)}" if m.group(3) else None
            title = text
        else:
            w = parse_when(text, today)
            if w.error:
                raise GoogleError(f"{w.error}。")
            if w.day is None and w.start is None:
                raise GoogleError("看不出是哪一天。例：/gcal 明天 14:00 看牙醫、/gcal 11/20 整天 員工旅遊")
            day, start, end, title = w.day or today, w.start, w.end, w.rest
        title = title.replace("整天", "").strip() if start is None else title
        if not title:
            raise GoogleError("要有標題。例：/gcal 明天 14:00 看牙醫")
        if start and not end:
            end = plus_minutes(start, DEFAULT_MINUTES)
        body = {"summary": title[:MAX_TITLE]}
        if values.get("location", "").strip():
            body["location"] = values["location"].strip()
        if values.get("note", "").strip():
            body["description"] = values["note"].strip()
        if start:
            body["start"] = {"dateTime": aware(day, start).isoformat()}
            body["end"] = {"dateTime": aware(day, end).isoformat()}
        else:
            body["start"] = {"date": day.isoformat()}
            body["end"] = {"date": (day + timedelta(days=1)).isoformat()}
        made = c.call("POST", c.events_path(), body=body) or {}
        row = to_row(made) if made.get("start") else {"day": day.isoformat(), "start": start or "", "end": end or "",
                                                      "all_day": start is None, "title": title,
                                                      "location": body.get("location", "")}
        lines = ["📅 加到 Google 日曆了：" + line(row, today)]
        if day < today:
            lines.append("（這一天已經過了，當作紀錄。）")
        elif start:
            lines.append(f"要提醒的話：/remind_add {plus_minutes(start, -30)} {title} date={day.isoformat()}")
        api.send_message(chat_id, "\n".join(lines))

    def today_(api, chat_id, user, values):
        today = now().date()
        rows = client(user).list_events(aware(today), aware(today + timedelta(days=1)))
        show(api, chat_id, user, f"📅 Google 日曆 {day_label(today, today)}", rows, today, "今天沒有行程。",
             with_day=False)

    def week(api, chat_id, user, values):
        today = now().date()
        last = today + timedelta(days=6)
        rows = client(user).list_events(aware(today), aware(today + timedelta(days=7)))
        show(api, chat_id, user, f"📅 Google 日曆 這 7 天（{today.month}/{today.day}–{last.month}/{last.day}）",
             rows, today, "這 7 天沒有行程。")

    def list_(api, chat_id, user, values):
        today = now().date()
        n = min(int(values.get("n") or 10), MAX_LIST)
        rows = client(user).list_events(aware(today), None, limit=n)
        show(api, chat_id, user, f"📅 Google 日曆 接下來 {len(rows)} 個行程", rows, today,
             "接下來沒有行程。用 /gcal 明天 14:00 看牙醫 加一個。")

    def rm(api, chat_id, user, values):
        c = client(user)
        if not c.connected():
            raise NotConnected(NOT_CONNECTED)
        if c.readonly():
            raise GoogleError("現在是唯讀模式，不能刪行程。")
        n = int(values["n"])
        hit = next((x for x in c.data().get("last_list") or [] if x.get("n") == n), None)
        if hit is None:
            raise GoogleError(f"沒有 [{n}] 這個編號。先用 /gcal_list（或 /gcal_today、/gcal_week）看編號。")
        gone = to_row(c.call("GET", c.events_path(hit["id"])) or {})   # 先讀回來：回覆說清楚刪的是哪一個
        c.call("DELETE", c.events_path(hit["id"]))

        def drop(d):
            d["last_list"] = [x for x in d.get("last_list") or [] if x.get("n") != n]
        pack.store.of(user).update(drop, {})
        api.send_message(chat_id, "🗑 從 Google 日曆刪掉了：" + line(gone, now().date()))

    # ── 連接（只給人；ai=False） ──

    def setup(api, chat_id, user, values):
        store = pack.store.of(user)
        old = store.load(None) or {}
        given = values.get("client_id", "").strip()
        mode = (values.get("mode") or "").strip().lower()
        if given.lower() in ("full", "readonly") and not values.get("client_secret"):
            given, mode = "", given.lower()                 # /gcal_setup readonly：沿用存著的 client
        mode = mode or "full"
        if mode not in SCOPES:
            raise GoogleError("最後一個只能是 full 或 readonly。")
        cid = given or old.get("client_id", "")
        secret = values.get("client_secret", "").strip() or old.get("client_secret", "")
        if not cid or not secret:
            raise GoogleError("用法：/gcal_setup <client_id> <client_secret> [readonly]（怎麼拿這兩個見 README）")
        if not _CLIENT_ID.match(cid):
            raise GoogleError("client_id 看起來不對（應該是 ….apps.googleusercontent.com 結尾）。")
        if not _TOKENISH.match(secret):
            raise GoogleError("client_secret 看起來不對（不能有空白）。")
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(32)

        def put(d):
            d.update(client_id=cid, client_secret=secret)
            d["pending"] = {"state": state, "verifier": verifier, "scope": SCOPES[mode], "at": time.time()}
        store.update(put, {})
        api.send_message(chat_id, "\n".join([
            "🔑 連 Google 日曆（" + ("唯讀" if mode == "readonly" else "可以看、加、刪行程") + "）：",
            "1. 打開這個連結，登入 Google、按「允許」（看到「Google 尚未驗證這個應用程式」→ 進階 → 前往）：",
            auth_url(cid, SCOPES[mode], state, challenge),
            "2. 最後瀏覽器會顯示「無法連上這個網站」——這是正常的（SYNOX 沒有開任何網路埠）。",
            "3. 把瀏覽器網址列那一整串（http://127.0.0.1:47231/?…code=…）複製，傳：/gcal_code <貼上>",
            "連結 15 分鐘內有效。"]), link_preview=False)

    def code(api, chat_id, user, values):
        store = pack.store.of(user)
        d = store.load(None) or {}
        pending = d.get("pending") or {}
        if not pending or time.time() - float(pending.get("at") or 0) > PENDING_SECONDS:
            raise GoogleError("沒有等待中的登入（或已經超過 15 分鐘）。請先 /gcal_setup。")
        got, state, error = parse_pasted(values["pasted"])
        if error:
            raise GoogleError("Google 說沒有允許（" + _clean(error, 40) + "）。要連的話重新 /gcal_setup。")
        if state and not secrets.compare_digest(state, pending.get("state", "")):
            raise GoogleError("這個網址不是剛剛那次登入的（state 對不上）。請用最新一次 /gcal_setup 給的連結。")
        if not got or not _TOKENISH.match(got):
            raise GoogleError("看不到授權碼。請貼瀏覽器網址列那一整串（裡面有 code=…）。")
        body = _post_token({"code": got, "client_id": d.get("client_id", ""), "client_secret": d.get("client_secret", ""),
                            "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code",
                            "code_verifier": pending.get("verifier", "")})
        if not body.get("refresh_token"):
            raise GoogleError("Google 沒有給 refresh token。請到 https://myaccount.google.com/permissions 移除這個 app，"
                              "再 /gcal_setup 一次。")

        def put(x):
            x.pop("pending", None)
            x["refresh_token"] = body["refresh_token"]
            x["access_token"] = body["access_token"]
            x["expires_at"] = time.time() + int(body.get("expires_in") or 3600)
            x["scope"] = pending.get("scope") or SCOPES["full"]
        store.update(put, {})
        api.send_message(chat_id, "✅ 連上 Google 日曆了（授權存在加密的保管箱）。試試 /gcal_today。\n"
                                  "建議把剛剛貼網址的那則訊息刪掉。")

    def token(api, chat_id, user, values):
        store = pack.store.of(user)
        d = store.load(None) or {}
        refresh = values["refresh_token"].strip()
        if not d.get("client_id") or not d.get("client_secret"):
            raise GoogleError("先 /gcal_setup <client_id> <client_secret>（refresh token 要跟同一組 client 搭配）。")
        if not _TOKENISH.match(refresh):
            raise GoogleError("refresh token 看起來不對（不能有空白）。")
        body = _post_token({"client_id": d["client_id"], "client_secret": d["client_secret"],
                            "refresh_token": refresh, "grant_type": "refresh_token"})
        granted = str(body.get("scope") or "").split()
        scope = SCOPES["readonly"] if SCOPES["readonly"] in granted and SCOPES["full"] not in granted else SCOPES["full"]

        def put(x):
            x.pop("pending", None)
            x.update(refresh_token=refresh, access_token=body["access_token"], scope=scope,
                     expires_at=time.time() + int(body.get("expires_in") or 3600))
        store.update(put, {})
        api.send_message(chat_id, "✅ refresh token 可以用，存進保管箱了。試試 /gcal_today。建議把剛剛那則訊息刪掉。")

    def status(api, chat_id, user, values):
        c = client(user)
        d = c.data()
        if not d.get("refresh_token"):
            extra = "（已經填過 client，等你 /gcal_code）" if d.get("pending") else ""
            api.send_message(chat_id, "🔌 Google 日曆：還沒連上" + extra + "。\n" + NOT_CONNECTED)
            return
        api.send_message(chat_id, "🔌 Google 日曆：已連上（" + ("唯讀" if c.readonly() else "可以看、加、刪") + "）\n"
                                  f"日曆：{c.calendar()}　client：{d.get('client_id', '')[:8]}…")

    def logout(api, chat_id, user, values):
        store = pack.store.of(user)
        d = store.load(None) or {}
        refresh = d.get("refresh_token")
        revoked = False
        if refresh:
            try:
                r = _http().request("POST", REVOKE_URL, data={"token": refresh}, timeout=TIMEOUT)
                revoked = r.status_code == 200
            except requests.RequestException:
                revoked = False
        store.save({k: v for k, v in d.items() if k in ("client_id", "client_secret")})
        api.send_message(chat_id, "👋 已經把 Google 日曆的授權從這台電腦刪掉了。" +
                         ("Google 那邊也收回了。" if revoked else
                          "（Google 那邊沒收回成功：可以到 https://myaccount.google.com/permissions 手動移除）" if refresh else ""))

    def mode_check(value: str):
        return None if value.lower() in ("full", "readonly") else "只能是 full 或 readonly"

    kit.command(g, "add", guarded(add), "加一個行程到 Google 日曆（明天 14:00 看牙醫）", default=True, effect=WRITE,
                positional=1, usage="<時間 標題>（例：明天 14:00 看牙醫） [location=…] [note=…]",
                fields=[Field("text", "時間和標題（AI 給了 date 就只放標題）", required=True),
                        Field("date", "日期 YYYY-MM-DD（AI 用；人直接寫在句子裡）", check=check_ymd),
                        Field("time", "時間 HH:MM 或 HH:MM-HH:MM（沒有＝整天）", check=check_time),
                        Field("location", "地點"),
                        Field("note", "備註")])
    kit.command(g, "today", guarded(today_), "Google 日曆今天的行程")
    kit.command(g, "week", guarded(week), "Google 日曆這 7 天的行程")
    kit.command(g, "list", guarded(list_), "Google 日曆接下來的行程（預設 10 個）",
                fields=[Field("n", "幾個", check=kit.positive_int)])
    kit.command(g, "rm", guarded(rm), "從 Google 日曆刪掉一個行程（編號看 /gcal_list）", effect=DANGER,
                fields=[Field("n", "編號（最近一次列出來的 [n]）", required=True, check=kit.positive_int)])
    kit.command(g, "status", guarded(status), "Google 日曆連上了沒")
    kit.command(g, "setup", guarded(setup), "連 Google 日曆：填 client_id、client_secret，拿登入連結", effect=WRITE,
                ai=False, usage="<client_id> <client_secret> [readonly]",
                fields=[Field("client_id", "OAuth client ID"), Field("client_secret", "OAuth client secret"),
                        Field("mode", "full（預設）或 readonly", check=mode_check)])
    kit.command(g, "code", guarded(code), "貼回 Google 登入後瀏覽器網址列的整串網址", effect=WRITE, ai=False,
                fields=[Field("pasted", "整串網址或授權碼", required=True)])
    kit.command(g, "token", guarded(token), "（進階）直接貼 refresh token", effect=WRITE, ai=False,
                fields=[Field("refresh_token", "refresh token", required=True)])
    kit.command(g, "logout", guarded(logout), "中斷 Google 日曆（刪掉授權、請 Google 收回）", effect=WRITE, ai=False)
