"""🍎 apple-reminders（CalDAV VTODO）：全部用假的 HTTP 傳輸（FakeICloud），不連網。"""

import io
import os
import sys
import zipfile
from datetime import date, datetime

import pytest

from synox import connect
from synox.packs import admin, scan
from synox.packs.loader import PACK_DIRS
from synox.packs.manifest import read

FOLDER = os.path.join(PACK_DIRS[1], "apple-reminders-caldav")
MODULE = "synox_pack_apple_reminders"
BASE = "https://caldav.icloud.com/"
PRINCIPAL = "https://caldav.icloud.com/123/principal/"
HOME = "https://p42-caldav.icloud.com:443/123/calendars/"
REM = HOME + "rem/"
WORK = HOME + "work/"


def _ms(*responses):
    body = "".join(f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{prop}</d:prop>"
                   f"<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" for href, prop in responses)
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"{body}</d:multistatus>").encode("utf-8")


def _todo(uid, summary, extra=""):
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Apple Inc.//iOS 12//EN\r\nBEGIN:VTODO\r\n"
            f"UID:{uid}\r\nSUMMARY:{summary}\r\n{extra}X-APPLE-SORT-ORDER:1\r\n"
            "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT5M\r\nSTATUS:KEEP\r\nEND:VALARM\r\n"
            "END:VTODO\r\nEND:VCALENDAR\r\n")


class Resp:
    def __init__(self, status, content=b"", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}


class FakeICloud:
    """像 iCloud 的 CalDAV：caldav.icloud.com 給 principal，帳號分流到 p42-caldav.icloud.com。"""

    def __init__(self, lists=True):
        self.auth = None
        self.calls = []
        self.lists = lists
        self.items = {
            REM + "A.ics": (_todo("A", "繳電費", "DUE;VALUE=DATE:20261108\r\nSTATUS:NEEDS-ACTION\r\n"), '"e1"'),
            REM + "B.ics": (_todo("B", "買牛奶\\, 雞蛋"), '"e2"'),
            REM + "C.ics": (_todo("C", "已經做完", "STATUS:COMPLETED\r\nCOMPLETED:20261101T000000Z\r\n"), '"e3"'),
            WORK + "D.ics": (_todo("D", "週報", "DUE:20261110T090000\r\nRRULE:FREQ=WEEKLY\r\n"), '"e4"'),
        }
        self.password = "abcd-efgh-ijkl-mnop"

    def request(self, method, url, data=None, headers=None, timeout=None, allow_redirects=True):
        self.calls.append((method, url, headers or {}, data, allow_redirects, timeout))
        assert allow_redirects is False and timeout
        if self.auth != ("me@icloud.com", self.password):
            return Resp(401)
        if method == "PROPFIND" and url == BASE:
            return Resp(207, _ms(("/", "<d:current-user-principal><d:href>/123/principal/</d:href></d:current-user-principal>")))
        if method == "PROPFIND" and url == PRINCIPAL:
            return Resp(207, _ms((PRINCIPAL, f"<c:calendar-home-set><d:href>{HOME}</d:href></c:calendar-home-set>")))
        if method == "PROPFIND" and url == HOME:
            rows = [("/123/calendars/", "<d:resourcetype><d:collection/></d:resourcetype>"),
                    ("/123/calendars/home/", "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                     "<d:displayname>行事曆</d:displayname>"
                     '<c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>')]
            if self.lists:
                for href, name in (("/123/calendars/rem/", "提醒事項"), ("/123/calendars/work/", "工作")):
                    rows.append((href, "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                                       f"<d:displayname>{name}</d:displayname>"
                                       '<c:supported-calendar-component-set><c:comp name="VTODO"/>'
                                       "</c:supported-calendar-component-set>"))
            return Resp(207, _ms(*rows))
        if method == "REPORT":
            rows = [(href.replace("https://p42-caldav.icloud.com:443", ""),
                     f"<d:getetag>{etag}</d:getetag><c:calendar-data>{ics.replace('&', '&amp;')}</c:calendar-data>")
                    for href, (ics, etag) in self.items.items() if href.startswith(url)]
            return Resp(207, _ms(*rows))
        if method == "GET" and url in self.items:
            ics, etag = self.items[url]
            return Resp(200, ics.encode("utf-8"), {"ETag": etag})
        if method == "PUT":
            text = data.decode("utf-8")
            if (headers or {}).get("If-None-Match") == "*":
                if url in self.items:
                    return Resp(412)
                self.items[url] = (text, '"new"')
                return Resp(201)
            if url not in self.items or headers.get("If-Match") != self.items[url][1]:
                return Resp(412)
            self.items[url] = (text, '"changed"')
            return Resp(204)
        return Resp(404)


@pytest.fixture
def icloud(make_bot, owner):
    """擁有者的帳號存進保管箱（走 connect.run，跟 Connect-Apple.bat 同一條路），HTTP 換成 FakeICloud。"""
    def factory(lists=True, password="abcd-efgh-ijkl-mnop"):
        bot = make_bot()
        answers = iter(["", "me@icloud.com"])
        out = []
        rc = connect.run("apple-reminders", bot.app.config, bot.app.extras["vault"], ask=lambda _: next(answers),
                         ask_secret=lambda _: password, out=out.append)
        assert rc == 0, out
        fake = FakeICloud(lists=lists)
        mod = sys.modules[MODULE]
        mod.make_session = lambda: fake
        mod.now = lambda: datetime(2026, 11, 9, 10, 0)
        return bot, fake
    return factory


# ── 五關 ─────────────────────────────────────────────────────────────────

def test_gate1_and_gate2_pass_with_only_network():
    m = read(FOLDER, strict=True)
    assert m.kind == "python" and m.capabilities == ["network"] and m.storage == "vault" and m.auth == "caldav"
    report = scan.scan(m)
    assert report.problems(m) == []
    assert report.required_capabilities == ["network"]


def test_gate2_refuses_it_without_network_declared(tmp_path):
    import json
    import shutil
    dst = tmp_path / "p"
    shutil.copytree(FOLDER, dst, ignore=shutil.ignore_patterns("__pycache__"))
    raw = json.loads((dst / "pack.json").read_text(encoding="utf-8"))
    raw["capabilities"] = []
    (dst / "pack.json").write_text(json.dumps(raw), encoding="utf-8")
    m = read(str(dst), strict=True)
    assert any("network" in p for p in scan.scan(m).problems(m))


def test_install_pipeline_stage_and_lock(make_bot, owner, tmp_path):
    """當成別人給的 .synoxpack 裝：zip 檢查、第 1、2 關、第 3 關 packs.lock，裝完載得起來。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in os.listdir(FOLDER):
            path = os.path.join(FOLDER, name)
            if os.path.isfile(path):
                z.write(path, name)
    bot = make_bot(pack_dirs=())
    data = bot.app.config.data_dir
    token, summary = admin.stage(buf.getvalue(), data)
    assert summary["scan"]["ok"], summary
    packs_dir = tmp_path / "userpacks"
    assert admin.install_staged(token, data, str(packs_dir), approved_by=owner) == "apple-reminders"
    report = admin.reload(bot.app, bot.app.config, bot.app.extras["vault"], (str(packs_dir),))
    item = {i.name: i for i in report.items}["apple-reminders"]
    assert item.status == "loaded" and item.lock == "locked"


def test_ai_tools_exclude_account_commands(make_bot):
    bot = make_bot()
    reg = bot.app.registry
    assert reg.node("applerem.list").command == "/applerem"
    assert all(reg.node(f"applerem.{n}").ai for n in ("list", "lists", "add", "done"))
    assert not reg.node("applerem.status").ai and not reg.node("applerem.logout").ai
    assert "password" not in {f.name for n in ("list", "lists", "add", "done") for f in reg.node(f"applerem.{n}").fields}


# ── 帳號：保管箱、密文、不經聊天 ───────────────────────────────────────────

def test_connect_stores_ciphertext_and_status(icloud, owner):
    bot, fake = icloud()
    path = bot.app.extras["vault"].path("apple-reminders.auth")
    raw = open(path, "rb").read()
    assert b"abcd-efgh" not in raw and b"me@icloud.com" not in raw
    bot.say(owner, "/applerem_status")
    text = bot.last(owner)
    assert "m***@icloud.com" in text and "提醒事項、工作" in text and "abcd" not in text
    # 每一次請求都帶帳密、只打 icloud.com 的主機
    assert {c[1].split("/")[2].split(":")[0] for c in fake.calls} <= {"caldav.icloud.com", "p42-caldav.icloud.com"}


def test_not_connected_says_how(make_bot, owner):
    bot = make_bot()
    bot.say(owner, "/applerem")
    assert "還沒設定帳號" in bot.last(owner) and "Connect-Apple.bat" in bot.last(owner)


def test_wrong_password(icloud, owner):
    bot, fake = icloud(password="wrong")
    bot.say(owner, "/applerem")
    assert "App 專用密碼" in bot.last(owner)


def test_upgraded_icloud_reminders_explained(icloud, owner):
    bot, _fake = icloud(lists=False)
    bot.say(owner, "/applerem_status")
    assert "登入成功" in bot.last(owner) and "iOS 13" in bot.last(owner)
    bot.say(owner, "/applerem_add 繳電費")
    assert "Apple 的限制" in bot.last(owner)


def test_logout_clears(icloud, owner):
    bot, _ = icloud()
    bot.say(owner, "/applerem_logout")
    assert "撤銷" in bot.last(owner)
    bot.say(owner, "/applerem")
    assert "還沒設定帳號" in bot.last(owner)


# ── 讀、加、完成 ───────────────────────────────────────────────────────────

def test_list_open_sorted(icloud, owner):
    bot, _ = icloud()
    bot.say(owner, "/applerem")
    text = bot.last(owner)
    assert "（3 項）" in text and "已經做完" not in text
    lines = text.splitlines()
    assert lines[1].startswith("☐ 1. 繳電費") and "⚠️逾期" in lines[1] and "［提醒事項］" in lines[1]
    assert lines[2].startswith("☐ 2. 週報") and "明天 11/10（二） 09:00" in lines[2]
    assert lines[3].startswith("☐ 3. 買牛奶, 雞蛋")
    bot.say(owner, "/applerem 工作")
    assert "（1 項）" in bot.last(owner) and "週報" in bot.last(owner)
    bot.say(owner, "/applerem 沒有這個")
    assert "有：提醒事項、工作" in bot.last(owner)


def test_add_escapes_and_alarm(icloud, owner):
    bot, fake = icloud()
    bot.say(owner, "/applerem_add 開會; 帶筆電,充電器 due=明天 15:00 list=工作")
    assert "加到「工作」了" in bot.last(owner)
    put = [c for c in fake.calls if c[0] == "PUT"][0]
    assert put[1].startswith(WORK) and put[1].endswith(".ics") and put[2]["If-None-Match"] == "*"
    ics = put[3].decode("utf-8")
    assert "SUMMARY:開會\\; 帶筆電\\,充電器\r\n" in ics and "DUE:20261110T150000" in ics
    assert "TRIGGER;RELATED=END:PT0S" in ics and ics.endswith("END:VCALENDAR\r\n")
    mod = sys.modules[MODULE]
    assert mod.parse_todos(ics)[0]["summary"] == "開會; 帶筆電,充電器"


def test_add_cannot_inject_properties(icloud, owner):
    """換行進不了 iCalendar：不會多出 STATUS:COMPLETED 之類的欄位。"""
    bot, fake = icloud()
    mod = sys.modules[MODULE]
    ics = mod.build_todo("x\r\nSTATUS:COMPLETED\nEND:VTODO", None, uid="U")
    todos = mod.parse_todos(ics)
    assert len(todos) == 1 and todos[0]["status"] == "NEEDS-ACTION"
    assert "\r\nSTATUS:COMPLETED" not in ics


def test_add_bad_due(icloud, owner):
    bot, fake = icloud()
    bot.say(owner, "/applerem_add 繳電費 due=下下禮拜")
    assert "看不懂到期" in bot.last(owner)
    assert not [c for c in fake.calls if c[0] == "PUT"]


def test_done_marks_completed_with_etag(icloud, owner):
    bot, fake = icloud()
    bot.say(owner, "/applerem")
    bot.say(owner, "/applerem_done 3")
    assert bot.last(owner) == "☑ 完成：買牛奶, 雞蛋"
    put = [c for c in fake.calls if c[0] == "PUT"][0]
    assert put[2]["If-Match"] == '"e2"'
    ics = fake.items[REM + "B.ics"][0]
    assert "STATUS:COMPLETED" in ics and "PERCENT-COMPLETE:100" in ics and "X-APPLE-SORT-ORDER:1" in ics
    assert "STATUS:KEEP" in ics                                    # VALARM 裡的屬性沒被動到
    bot.say(owner, "/applerem")
    assert "買牛奶" not in bot.last(owner)


def test_done_refuses_recurring_and_bad_number(icloud, owner):
    bot, fake = icloud()
    bot.say(owner, "/applerem_done 1")
    assert "先 /applerem 列出來" in bot.last(owner)
    bot.say(owner, "/applerem")
    bot.say(owner, "/applerem_done 2")
    assert "重複的提醒事項" in bot.last(owner)
    assert not [c for c in fake.calls if c[0] == "PUT"]


def test_done_conflict(icloud, owner):
    bot, fake = icloud()
    bot.say(owner, "/applerem")
    real = fake.request

    def changed(method, url, **kw):
        if method == "PUT":
            fake.items[url] = (fake.items[url][0], '"other"')
        return real(method, url, **kw)

    fake.request = changed
    bot.say(owner, "/applerem_done 3")
    assert "別的裝置上改過" in bot.last(owner)


# ── 安全：主機、XML、大小 ───────────────────────────────────────────────────

def test_credentials_never_leave_the_configured_host(icloud, owner):
    bot, fake = icloud()
    real = fake.request

    def evil(method, url, **kw):
        if method == "PROPFIND" and url == PRINCIPAL:
            fake.calls.append((method, url, {}, None, False, 1))
            return Resp(207, _ms((PRINCIPAL, "<c:calendar-home-set><d:href>https://evil.example/steal/</d:href>"
                                             "</c:calendar-home-set>")))
        return real(method, url, **kw)

    fake.request = evil
    bot.say(owner, "/applerem")
    assert "evil.example" in bot.last(owner) and "沒有連" in bot.last(owner)
    assert not any("evil.example" in c[1] for c in fake.calls)


def test_plain_http_server_refused(make_bot):
    make_bot()
    mod = sys.modules[MODULE]
    with pytest.raises(mod.CalDavError):
        mod.Client("http://caldav.icloud.com", "a", "b", session=FakeICloud())


def test_non_icloud_server_same_host_only(make_bot):
    make_bot()
    mod = sys.modules[MODULE]
    c = mod.Client("https://dav.example.org/dav/", "a", "b", session=FakeICloud())
    assert c.allowed("https://dav.example.org/x/") and not c.allowed("https://other.example.org/x/")
    assert not c.allowed("http://dav.example.org/x/") and not c.icloud
    ic = mod.Client(BASE, "a", "b", session=FakeICloud())
    assert ic.allowed(HOME) and not ic.allowed("https://icloud.com.evil.example/")


def test_xml_entities_refused(make_bot):
    make_bot()
    mod = sys.modules[MODULE]
    with pytest.raises(mod.CalDavError):
        mod.Client.xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')


def test_oversized_response_refused(make_bot):
    make_bot()
    mod = sys.modules[MODULE]
    fake = FakeICloud()
    fake.request = lambda *a, **k: Resp(207, b"x" * (mod.MAX_BYTES + 1))
    c = mod.Client(BASE, "me@icloud.com", "p", session=fake)
    with pytest.raises(mod.CalDavError) as e:
        c.home()
    assert "太大" in str(e.value)


# ── iCalendar 小工具 ──────────────────────────────────────────────────────

def test_fold_unfold_round_trip_multibyte(make_bot):
    make_bot()
    mod = sys.modules[MODULE]
    line = "SUMMARY:" + "提醒事項" * 30
    folded = mod.fold(line)
    assert all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n"))
    assert mod.unfold(folded) == [line]


def test_parse_dt_and_due(make_bot):
    make_bot()
    mod = sys.modules[MODULE]
    assert mod.parse_dt("20261110", {"VALUE": "DATE"}) == date(2026, 11, 10)
    assert mod.parse_dt("20261110T090000", {}) == datetime(2026, 11, 10, 9, 0)
    assert isinstance(mod.parse_dt("20261110T010000Z", {}), datetime)
    assert mod.parse_dt("garbage", {}) is None
    today = date(2026, 11, 9)
    assert mod.parse_due("明天 15:00", today) == datetime(2026, 11, 10, 15, 0)
    assert mod.parse_due("1/5", today) == date(2027, 1, 5)
    assert mod.parse_due("2026-11-20", today) == date(2026, 11, 20)
    assert mod.parse_due("", today) is None
    with pytest.raises(mod.CalDavError):
        mod.parse_due("2026-02-30", today)


def test_connect_cli_requires_vault_pack_and_fields(make_bot):
    bot = make_bot()
    out = []
    assert connect.run("notes", bot.app.config, bot.app.extras["vault"], out=out.append) == 2
    assert "auth.fields" in out[-1]
    assert connect.run("nope", bot.app.config, bot.app.extras["vault"], out=out.append) == 2
    assert connect.run("apple-reminders", bot.app.config, bot.app.extras["vault"], ask=lambda _: "",
                       ask_secret=lambda _: "", out=out.append) == 1        # 沒填密碼：不存
    assert not os.path.exists(bot.app.extras["vault"].path("apple-reminders.auth"))
