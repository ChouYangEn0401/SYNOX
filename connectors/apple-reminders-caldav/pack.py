"""🍎 Apple 提醒事項（CalDAV VTODO）：/applerem、/applerem_lists、/applerem_add、/applerem_done、/applerem_status、/applerem_logout。

只用 requests＋標準函式庫：WebDAV 的 PROPFIND／REPORT／GET／PUT，自己組最小的 iCalendar（VTODO）、自己解析。

帳號（伺服器網址、帳號、App 專用密碼）**不經聊天**：在電腦上跑 `python -m synox connect apple-reminders`
（或雙擊 Connect-Apple.bat），密碼用 getpass 輸入、存進保管箱 `pack.store.of(user)` 的 key="auth"（密文）。
聊天裡打密碼會留在 Telegram 紀錄與 [ROUTE] log，所以這裡沒有「在聊天裡登入」的指令。

研究結論（README.md）：iCloud 的「升級過的提醒事項」（iOS 13 起）Apple 已經不經 CalDAV 提供；
這個 pack 對 iCloud 只在「還沒升級的舊清單」上有用。真正可用的路是：iPhone「設定 → 提醒事項 → 帳號 → 加入 CalDAV 帳號」
接一個標準 CalDAV 伺服器（Fastmail、Nextcloud、Synology…），SYNOX 連同一個伺服器——iPhone 的提醒事項 App 會顯示那些清單。

安全：
- 只連 https；之後打的每個網址（伺服器回的 href）都要跟設定的主機同一個（iCloud 允許 *.icloud.com），帳密不會被帶到別的主機。
- 不跟隨重新導向（allow_redirects=False），回應最多 5 MB，XML 裡有 DOCTYPE／ENTITY 一律拒絕。
- 使用者的字寫進 iCalendar 前一律跳脫（換行、逗號、分號、反斜線），不能插入別的欄位。
- 重複（RRULE）的提醒事項不在這裡打勾（CalDAV 打勾會把整串結束），請在 iPhone 上做。

資料（保管箱，密文）：key="auth"＝{server, username, password}；key="last"＝上次 /applerem 列出來的編號 → 網址。
"""

import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

import requests

from isdtelekit.core.registry import WRITE, Field

from synox.packs import kit

DEFAULT_SERVER = "https://caldav.icloud.com"
TIMEOUT = 20
MAX_BYTES = 5 * 1024 * 1024
MAX_SHOWN = 30
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}
PRODID = "-//SYNOX//apple-reminders 0.1//ZH"


def make_session():
    """HTTP 的 session（測試換掉這一個：假的傳輸，不連網）。"""
    return requests.Session()


def now() -> datetime:
    """現在的本地時間（測試換掉這一個）。"""
    return datetime.now()


class CalDavError(Exception):
    """給人看的錯誤訊息。"""


# ── iCalendar：最小的解析與產生 ─────────────────────────────────────────

def unfold(text: str) -> list:
    """RFC 5545 §3.1：CRLF 後面接空白或 tab 是上一行的延續。"""
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        elif raw:
            out.append(raw)
    return out


def fold(line: str) -> str:
    """一行最多 75 個 octet（UTF-8），不切斷多位元組字；續行開頭一個空白。"""
    parts, cur, size, limit = [], "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            parts.append(cur)
            cur, size, limit = "", 0, 74
        cur += ch
        size += n
    parts.append(cur)
    return "\r\n ".join(parts)


def split_prop(line: str):
    """'DUE;VALUE=DATE:20261110' → ('DUE', {'VALUE': 'DATE'}, '20261110')。冒號在引號裡的參數值不算。"""
    in_quote, cut = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            cut = i
            break
    if cut < 0:
        return line.upper(), {}, ""
    head, value = line[:cut], line[cut + 1:]
    pieces = head.split(";")
    params = {}
    for p in pieces[1:]:
        k, _, v = p.partition("=")
        params[k.strip().upper()] = v.strip().strip('"')
    return pieces[0].strip().upper(), params, value


def escape_text(value: str) -> str:
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return value.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def unescape_text(value: str) -> str:
    out, i = [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_dt(value: str, params: dict):
    """DATE → date；DATE-TIME（UTC 的 Z、TZID、浮動）→ 本地的 naive datetime。看不懂回 None。"""
    value = value.strip()
    try:
        if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value[:8], "%Y%m%d").date()
        if value.endswith("Z"):
            return datetime.strptime(value[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
        tzid = params.get("TZID")
        if tzid:
            try:
                from zoneinfo import ZoneInfo
                return dt.replace(tzinfo=ZoneInfo(tzid)).astimezone().replace(tzinfo=None)
            except Exception:                       # 沒有那個時區資料：當成本地時間
                return dt
        return dt
    except ValueError:
        return None


def parse_todos(text: str) -> list:
    """一份 VCALENDAR → 裡面的 VTODO（只看第一層的屬性；VALARM 裡的不算）。"""
    todos, cur, depth = [], None, 0
    for line in unfold(text):
        name, params, value = split_prop(line)
        if name == "BEGIN":
            if value.upper() == "VTODO" and cur is None:
                cur, depth = {"rrule": False}, 0
            elif cur is not None:
                depth += 1
            continue
        if name == "END":
            if cur is not None and value.upper() == "VTODO" and depth == 0:
                todos.append(cur)
                cur = None
            elif cur is not None:
                depth -= 1
            continue
        if cur is None or depth:
            continue
        if name == "UID":
            cur["uid"] = value.strip()
        elif name == "SUMMARY":
            cur["summary"] = unescape_text(value)
        elif name == "STATUS":
            cur["status"] = value.strip().upper()
        elif name == "COMPLETED":
            cur["completed"] = True
        elif name == "DUE":
            cur["due"] = parse_dt(value, params)
        elif name == "PRIORITY":
            cur["priority"] = int(value) if value.strip().isdigit() else 0
        elif name == "RRULE":
            cur["rrule"] = True
    return todos


def is_open(todo: dict) -> bool:
    return not todo.get("completed") and todo.get("status") not in ("COMPLETED", "CANCELLED")


def utc_stamp(when=None) -> str:
    when = when or datetime.now(timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_todo(summary: str, due=None, uid: str = "", stamp: str = "") -> str:
    """一個新的 VTODO。due：date（整天）／datetime（浮動的本地時間，到時提醒）／None。"""
    stamp = stamp or utc_stamp()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "BEGIN:VTODO",
             f"UID:{uid}", f"DTSTAMP:{stamp}", f"CREATED:{stamp}", f"LAST-MODIFIED:{stamp}",
             f"SUMMARY:{escape_text(summary)}", "STATUS:NEEDS-ACTION"]
    if isinstance(due, datetime):
        lines.append(f"DUE:{due.strftime('%Y%m%dT%H%M%S')}")
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{escape_text(summary)}",
                  "TRIGGER;RELATED=END:PT0S", "END:VALARM"]
    elif isinstance(due, date):
        lines.append(f"DUE;VALUE=DATE:{due.strftime('%Y%m%d')}")
    lines += ["END:VTODO", "END:VCALENDAR"]
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


def mark_completed(text: str, stamp: str = "") -> str:
    """把第一個 VTODO 改成完成：拿掉舊的 STATUS／COMPLETED／PERCENT-COMPLETE／DTSTAMP／LAST-MODIFIED，加新的。
    其他屬性（含 Apple 自己的 X- 欄位、VALARM）原樣留著。"""
    stamp = stamp or utc_stamp()
    drop = {"STATUS", "COMPLETED", "PERCENT-COMPLETE", "DTSTAMP", "LAST-MODIFIED"}
    out, in_todo, depth, done = [], False, 0, False
    for line in unfold(text):
        name, _params, value = split_prop(line)
        if name == "BEGIN" and value.upper() == "VTODO" and not done and not in_todo:
            in_todo, depth = True, 0
        elif in_todo and name == "BEGIN":
            depth += 1
        elif in_todo and name == "END" and value.upper() == "VTODO" and depth == 0:
            out += ["STATUS:COMPLETED", f"COMPLETED:{stamp}", "PERCENT-COMPLETE:100", f"DTSTAMP:{stamp}",
                    f"LAST-MODIFIED:{stamp}"]
            in_todo, done = False, True
        elif in_todo and name == "END":
            depth -= 1
        elif in_todo and depth == 0 and name in drop:
            continue
        out.append(line)
    if not done:
        raise CalDavError("這一筆裡找不到 VTODO。")
    return "\r\n".join(fold(x) for x in out) + "\r\n"


# ── 到期：YYYY-MM-DD [HH:MM]、今天／明天／後天 [HH:MM]、HH:MM ───────────────

_REL = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "後天": 2, "后天": 2}


def parse_due(text: str, today: date):
    """回 date、datetime 或 None（沒寫）；看不懂丟 CalDavError。"""
    text = (text or "").strip()
    if not text:
        return None
    m = re.fullmatch(r"(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})/(\d{1,2})|(今天|今日|明天|明日|後天|后天))?"
                     r"\s*(?:(\d{1,2}):(\d{2}))?", text)
    if not m or not any(m.groups()):
        raise CalDavError(f"看不懂到期「{text}」。例：2026-11-20、11/20、明天、明天 15:00")
    g = m.groups()
    try:
        if g[0]:
            day = date(int(g[0]), int(g[1]), int(g[2]))
        elif g[3]:
            day = date(today.year, int(g[3]), int(g[4]))
            if day < today:
                day = date(today.year + 1, int(g[3]), int(g[4]))
        elif g[5]:
            day = today + timedelta(days=_REL[g[5]])
        else:
            day = today
        if g[6]:
            return datetime(day.year, day.month, day.day, int(g[6]), int(g[7]))
    except ValueError:
        raise CalDavError(f"「{text}」不是真的日期／時間。")
    return day


def check_due(value: str):
    try:
        parse_due(value, date.today())
    except CalDavError as e:
        return "：" + str(e)
    return None


# ── CalDAV ────────────────────────────────────────────────────────────

def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def check_server(url: str):
    """設定的伺服器網址：一定要 https、要有主機名。回錯誤訊息或 None。"""
    parts = urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname:
        return "伺服器網址要是 https://…（例如 https://caldav.icloud.com）"
    return None


class Client:
    """最小的 CalDAV 用戶端。session：requests.Session 介面（request(method, url, …) → response）。"""

    def __init__(self, server: str, username: str, password: str, session=None):
        problem = check_server(server)
        if problem:
            raise CalDavError(problem)
        self.server = server.rstrip("/") + "/"
        self.base_host = _host(server)
        self.session = session if session is not None else make_session()
        self.session.auth = (username, password)
        self.icloud = self.base_host == "icloud.com" or self.base_host.endswith(".icloud.com")

    def allowed(self, url: str) -> bool:
        """帳密只送去設定的那台主機（iCloud：*.icloud.com；分流主機 pNN-caldav.icloud.com 也算）。"""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            return False
        if self.icloud:
            return host == "icloud.com" or host.endswith(".icloud.com")
        return host == self.base_host

    def request(self, method: str, url: str, body: str = "", headers=None, ok=(200, 207)):
        if not self.allowed(url):
            raise CalDavError(f"伺服器要我連到別的地方（{_host(url) or url}），為了帳密安全沒有連。")
        hdrs = {"User-Agent": "SYNOX-apple-reminders/0.1"}
        if body:
            hdrs["Content-Type"] = "application/xml; charset=utf-8" if body.lstrip().startswith("<") \
                else "text/calendar; charset=utf-8"
        hdrs.update(headers or {})
        try:
            resp = self.session.request(method, url, data=body.encode("utf-8") if body else None, headers=hdrs,
                                        timeout=TIMEOUT, allow_redirects=False)
        except requests.RequestException as e:
            raise CalDavError(f"連不上伺服器（{type(e).__name__}）。網路斷了，或伺服器網址不對？")
        content = resp.content or b""
        if len(content) > MAX_BYTES:
            raise CalDavError("伺服器回的資料太大了（超過 5 MB），沒有讀。")
        if resp.status_code == 401:
            raise CalDavError("帳號或密碼不對。iCloud 要用「App 專用密碼」（appleid.apple.com → 登入與安全性），"
                              "不是 Apple ID 本身的密碼。重新設定：在電腦上跑 Connect-Apple.bat。")
        if resp.status_code == 412:
            raise CalDavError("這一筆剛剛在別的裝置上改過了。先 /applerem 重新列一次再試。")
        if resp.status_code not in ok:
            raise CalDavError(f"伺服器回 HTTP {resp.status_code}（{method}）。")
        return resp, content

    @staticmethod
    def xml(content: bytes):
        head = content[:4096].upper()
        if b"<!DOCTYPE" in head or b"<!ENTITY" in content.upper():
            raise CalDavError("伺服器回的 XML 有 DOCTYPE／ENTITY，為了安全沒有讀。")
        try:
            return ET.fromstring(content)
        except ET.ParseError:
            raise CalDavError("伺服器回的不是看得懂的 XML。")

    def propfind(self, url: str, props: str, depth: str = "0"):
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                f"<d:prop>{props}</d:prop></d:propfind>")
        resp, content = self.request("PROPFIND", url, body, {"Depth": depth})
        return self.responses(url, self.xml(content))

    @staticmethod
    def responses(url: str, root):
        """multistatus → [(絕對網址, prop 元素)]（只取 200 的 propstat）。"""
        out = []
        for r in root.findall("d:response", NS):
            href = (r.findtext("d:href", default="", namespaces=NS) or "").strip()
            if not href:
                continue
            for ps in r.findall("d:propstat", NS):
                status = ps.findtext("d:status", default="", namespaces=NS) or ""
                prop = ps.find("d:prop", NS)
                if prop is not None and " 200 " in f" {status} ":
                    out.append((urljoin(url, href), prop))
        return out

    def _href_prop(self, url: str, outer: str, tag: str) -> str:
        for _href, prop in self.propfind(url, f"<{tag}/>"):
            el = prop.find(outer, NS)
            if el is not None:
                h = (el.findtext("d:href", default="", namespaces=NS) or "").strip()
                if h:
                    return urljoin(url, h)
        return ""

    def home(self) -> str:
        principal = self._href_prop(self.server, "d:current-user-principal", "d:current-user-principal")
        if not principal:
            raise CalDavError("伺服器沒有告訴我你的帳號在哪（current-user-principal）。伺服器網址對嗎？")
        home = self._href_prop(principal, "c:calendar-home-set", "c:calendar-home-set")
        if not home:
            raise CalDavError("伺服器沒有告訴我你的行事曆在哪（calendar-home-set）。")
        return home if home.endswith("/") else home + "/"

    def lists(self) -> list:
        """有 VTODO 的集合（＝提醒事項清單）：[{"url", "name"}]。"""
        home = self.home()
        props = "<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>"
        out = []
        for href, prop in self.propfind(home, props, depth="1"):
            rt = prop.find("d:resourcetype", NS)
            if rt is None or rt.find("c:calendar", NS) is None:
                continue
            comps = prop.find("c:supported-calendar-component-set", NS)
            if comps is None:
                continue                               # 沒說支援什麼：不猜（多半是只有 VEVENT 的行事曆）
            if "VTODO" not in {(c.get("name") or "").upper() for c in comps.findall("c:comp", NS)}:
                continue
            name = (prop.findtext("d:displayname", default="", namespaces=NS) or "").strip()
            out.append({"url": href if href.endswith("/") else href + "/", "name": name or "（沒有名字）"})
        return out

    def todos(self, list_url: str) -> list:
        """一個清單的全部 VTODO：[{href, etag, uid, summary, due, status, completed, rrule}]。
        完成的也會回來（伺服器的 filter 支援不一，自己過濾）。"""
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
                '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VTODO"/></c:comp-filter></c:filter>'
                "</c:calendar-query>")
        resp, content = self.request("REPORT", list_url, body, {"Depth": "1"})
        out = []
        for href, prop in self.responses(list_url, self.xml(content)):
            data = prop.findtext("c:calendar-data", default="", namespaces=NS) or ""
            etag = (prop.findtext("d:getetag", default="", namespaces=NS) or "").strip()
            for t in parse_todos(data)[:1]:
                out.append({**t, "href": href, "etag": etag})
        return out

    def get(self, href: str):
        resp, content = self.request("GET", href, ok=(200,))
        return content.decode("utf-8", "replace"), (resp.headers.get("ETag") or "").strip()

    def put(self, href: str, ics: str, etag: str = "", new: bool = False) -> None:
        headers = {"If-None-Match": "*"} if new else ({"If-Match": etag} if etag else {})
        self.request("PUT", href, ics, headers, ok=(200, 201, 204))


# ── 顯示 ───────────────────────────────────────────────────────────────

WEEK = "一二三四五六日"


def due_label(due, today: date) -> str:
    if due is None:
        return ""
    day = due.date() if isinstance(due, datetime) else due
    names = {0: "今天", 1: "明天", -1: "昨天"}
    label = f"{day.month}/{day.day}（{WEEK[day.weekday()]}）"
    if day.year != today.year:
        label = f"{day.year}/" + label
    diff = (day - today).days
    if diff in names:
        label = f"{names[diff]} {label}"
    if isinstance(due, datetime):
        label += due.strftime(" %H:%M")
    return ("⚠️逾期 " if day < today else "") + label


def sort_key(t: dict):
    due = t.get("due")
    if due is None:
        return (1, "", t.get("summary") or "")
    key = due.strftime("%Y%m%d%H%M") if isinstance(due, datetime) else due.strftime("%Y%m%d") + "9999"
    return (0, key, t.get("summary") or "")


# ── 指令 ───────────────────────────────────────────────────────────────

SETUP_HINT = ("在這台電腦上雙擊 Connect-Apple.bat（或 python -m synox connect apple-reminders），"
              "貼上帳號與 App 專用密碼——密碼不要打在聊天裡。")
NO_LISTS_ICLOUD = ("iCloud 帳號裡找不到能用 CalDAV 讀的提醒事項清單。\n"
                   "原因：iOS 13 起「升級過」的提醒事項 Apple 改存在別的地方，第三方程式（CalDAV）讀不到——這是 Apple 的限制，不是設定錯。\n"
                   "可行的做法：iPhone「設定 → 提醒事項 → 帳號 → 加入帳號 → 其他 → CalDAV」接一個 CalDAV 伺服器"
                   "（Fastmail、Nextcloud…），在那個帳號建清單，再把 SYNOX 也連到同一個伺服器。詳見 README。")


def install(app, pack):
    g = pack.group

    def account(user):
        auth = pack.store.of(user).load(None, key="auth") or {}
        if not auth.get("username") or not auth.get("password"):
            return None
        return auth

    def client(user) -> Client:
        auth = account(user)
        if auth is None:
            raise CalDavError("還沒設定帳號。" + SETUP_HINT)
        return Client(auth.get("server") or DEFAULT_SERVER, auth["username"], auth["password"])

    def no_lists(c: Client) -> str:
        return NO_LISTS_ICLOUD if c.icloud else "這個 CalDAV 帳號裡沒有提醒事項（VTODO）清單。先在 iPhone 或伺服器上建一個。"

    def guarded(fn):
        def run(api, chat_id, user, values):
            try:
                fn(api, chat_id, user, values)
            except CalDavError as e:
                api.send_message(chat_id, f"🍎 {e}")
        return run

    def pick_list(c: Client, wanted: str):
        lists = c.lists()
        if not lists:
            raise CalDavError(no_lists(c))
        if not wanted:
            return lists[0], lists
        for item in lists:
            if item["name"].lower() == wanted.strip().lower():
                return item, lists
        raise CalDavError(f"沒有叫「{wanted}」的清單。有：{'、'.join(i['name'] for i in lists)}")

    def show(api, chat_id, user, values):
        c = client(user)
        target, lists = pick_list(c, values.get("list", ""))
        chosen = [target] if values.get("list") else lists
        today = now().date()
        rows = []
        for item in chosen:
            for t in c.todos(item["url"]):
                if is_open(t):
                    rows.append({**t, "list": item["name"]})
        rows.sort(key=sort_key)
        shown = rows[:MAX_SHOWN]
        pack.store.of(user).save({"at": int(time.time()), "items": [
            {"href": t["href"], "summary": t.get("summary") or "", "list": t["list"]} for t in shown]}, key="last")
        if not rows:
            api.send_message(chat_id, "🍎 沒有還沒完成的提醒事項。🎉")
            return
        multi = len(chosen) > 1
        lines = [f"🍎 還沒完成的提醒事項（{len(rows)} 項）"]
        for i, t in enumerate(shown, 1):
            parts = [f"☐ {i}. {t.get('summary') or '（沒有標題）'}"]
            label = due_label(t.get("due"), today)
            if label:
                parts.append("· " + label)
            if multi:
                parts.append(f"［{t['list']}］")
            lines.append(" ".join(parts))
        if len(rows) > MAX_SHOWN:
            lines.append(f"…還有 {len(rows) - MAX_SHOWN} 項（只列前 {MAX_SHOWN} 項）")
        lines.append("完成一項：/applerem_done <編號>")
        api.send_message(chat_id, "\n".join(lines))

    def show_lists(api, chat_id, user, values):
        c = client(user)
        lists = c.lists()
        if not lists:
            api.send_message(chat_id, "🍎 " + no_lists(c))
            return
        api.send_message(chat_id, "🍎 提醒事項清單：\n" + "\n".join(f"• {i['name']}" for i in lists)
                         + "\n（/applerem_add 沒指定 list= 時加到第一個）")

    def add(api, chat_id, user, values):
        text = values["text"].strip()
        if not text:
            api.send_message(chat_id, "❌ 要寫提醒什麼。例：/applerem_add 繳電費 due=明天")
            return
        due = parse_due(values.get("due", ""), now().date())
        c = client(user)
        target, _lists = pick_list(c, values.get("list", ""))
        uid = str(uuid.uuid4()).upper()
        c.put(target["url"] + uid + ".ics", build_todo(text[:500], due, uid=uid), new=True)
        label = due_label(due, now().date())
        api.send_message(chat_id, f"🍎 加到「{target['name']}」了：{text[:500]}" + (f" · {label}" if label else ""))

    def done(api, chat_id, user, values):
        n = int(values["n"])
        last = (pack.store.of(user).load(None, key="last") or {}).get("items") or []
        if not 1 <= n <= len(last):
            api.send_message(chat_id, f"❌ 沒有第 {n} 項。先 /applerem 列出來，再用那裡的編號。")
            return
        item = last[n - 1]
        c = client(user)
        ics, etag = c.get(item["href"])
        todos = parse_todos(ics)
        if not todos:
            raise CalDavError("那一筆已經不是提醒事項了（被刪掉或搬走？）。先 /applerem 重新列一次。")
        if not is_open(todos[0]):
            api.send_message(chat_id, f"🍎 「{todos[0].get('summary') or item['summary']}」早就完成了。")
            return
        if todos[0].get("rrule"):
            api.send_message(chat_id, "🍎 這是重複的提醒事項：經 CalDAV 打勾會把整串結束，請在 iPhone 上完成這一次。")
            return
        c.put(item["href"], mark_completed(ics), etag=etag)
        api.send_message(chat_id, f"☑ 完成：{todos[0].get('summary') or item['summary']}")

    def status(api, chat_id, user, values):
        auth = account(user)
        if auth is None:
            api.send_message(chat_id, "🍎 還沒設定帳號。\n" + SETUP_HINT + "\n說明與限制見 connectors/apple-reminders-caldav/README.md。")
            return
        server = auth.get("server") or DEFAULT_SERVER
        head = f"🍎 帳號：{mask(auth['username'])}（{_host(server)}）"
        try:
            c = Client(server, auth["username"], auth["password"])
            lists = c.lists()
        except CalDavError as e:
            api.send_message(chat_id, f"{head}\n❌ {e}")
            return
        if not lists:
            api.send_message(chat_id, f"{head}\n✅ 登入成功，但：{no_lists(c)}")
            return
        api.send_message(chat_id, f"{head}\n✅ 連得上，{len(lists)} 個清單：{'、'.join(i['name'] for i in lists)}")

    def logout(api, chat_id, user, values):
        store = pack.store.of(user)
        had = account(user) is not None
        store.save({}, key="auth")
        store.save({}, key="last")
        api.send_message(chat_id, "🍎 已經把這台電腦上存的帳號清掉了。" + (
            "\n記得也到 appleid.apple.com 撤銷那組 App 專用密碼。" if had else ""))

    list_field = Field("list", "清單名稱（不寫＝全部／第一個）")
    kit.command(g, "list", guarded(show), "列出還沒完成的提醒事項", default=True, positional=1,
                fields=[list_field])
    kit.command(g, "lists", guarded(show_lists), "看有哪些提醒事項清單")
    kit.command(g, "add", guarded(add), "加一個提醒事項", effect=WRITE, positional=1,
                usage="<內容> [due=明天 15:00] [list=清單名稱]",
                fields=[Field("text", "要提醒的事", required=True),
                        Field("due", "到期（2026-11-20、11/20、明天、明天 15:00）", check=check_due),
                        list_field])
    kit.command(g, "done", guarded(done), "完成一項（編號看 /applerem）", effect=WRITE,
                fields=[Field("n", "編號", required=True, check=kit.positive_int)])
    kit.command(g, "status", guarded(status), "看帳號設定、測試連線", ai=False)
    kit.command(g, "logout", guarded(logout), "清掉這台電腦上存的帳號", effect=WRITE, ai=False)


def mask(name: str) -> str:
    """a***@icloud.com：只露第一個字與網域。"""
    user, at, domain = (name or "").partition("@")
    return (user[:1] + "***" + (at + domain if at else "")) if user else "***"
