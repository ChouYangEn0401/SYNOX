"""scripts/smoke_real.py（真機煙霧測試）的邏輯：假傳輸、假保管箱，不連網、不開埠。

一個 FakeNet 同時扮 Notion、Todoist、Google、iCloud CalDAV、Discord（照網址分）；憑證存進真的 Vault（測試金鑰）。
"""

import importlib.util
import json
import os
import sys
from datetime import datetime
from urllib.parse import urlsplit

import pytest

from synox.config import SynoxConfig
from synox.discord.events import DISCORD
from synox.identity import Identities
from synox.packs.loader import PackStore
from synox.vault import Vault

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "smoke_real.py")

NOTION = "ntn_" + "N0t10nTok3n" * 4
TODOIST = "0123456789abcdef0123456789abcdef01234567"
G_CID = "1234567890-abc.apps.googleusercontent.com"
G_SECRET = "GOCSPX-secret-value-xyz"
G_REFRESH = "1//refresh-token-SECRET"
APPLE_PW = "abcd-efgh-ijkl-mnop"
DISCORD_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4.GhIjKl.discord-token-SECRET-value"
NOW = datetime(2026, 11, 10, 9, 30)

CAL_BASE = "https://caldav.icloud.com/"
PRINCIPAL = "https://caldav.icloud.com/123/principal/"
HOME = "https://p42-caldav.icloud.com/123/calendars/"
REM = HOME + "rem/"


def load_script():
    spec = importlib.util.spec_from_file_location("smoke_real_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


smoke_real = load_script()


class Resp:
    def __init__(self, status=200, body=None, headers=None, raw=None):
        self.status_code = status
        self.headers = headers or {}
        if raw is not None:
            self.content = raw
        else:
            self.content = b"" if body is None else json.dumps(body).encode("utf-8")
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        if not self.content:
            raise ValueError("no json")
        return json.loads(self.content.decode("utf-8"))


def _ms(*rows):
    body = "".join(f"<d:response><d:href>{h}</d:href><d:propstat><d:prop>{p}</d:prop>"
                   "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" for h, p in rows)
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"{body}</d:multistatus>").encode("utf-8")


TODO = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:A\r\nSUMMARY:繳電費\r\nSTATUS:NEEDS-ACTION\r\n"
        "END:VTODO\r\nEND:VCALENDAR\r\n")


class FakeNet:
    """requests.Session 的替身：照主機分給五個假服務。calls 記 (method, url, kw)。"""

    def __init__(self):
        self.calls = []
        self.auth = None
        self.notion_status = 200
        self.notion_pages = True
        self.apple_lists = True
        self.discord_flags = 1 << 19
        self.discord_status = 200
        self.blow_up = None                     # 某個主機丟這個例外
        self.ics = {REM + "A.ics": (TODO, '"e1"')}

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        host = urlsplit(url).hostname or ""
        if self.blow_up and self.blow_up[0] == host:
            raise self.blow_up[1]
        if host == "api.notion.com":
            return self.notion(method, url[len("https://api.notion.com/v1"):], kw)
        if host == "api.todoist.com":
            return self.todoist(method, url[len("https://api.todoist.com/api/v1/"):], kw)
        if host in ("oauth2.googleapis.com", "www.googleapis.com"):
            return self.google(method, url, kw)
        if host.endswith("icloud.com"):
            return self.caldav(method, url, kw)
        if host == "discord.com":
            return self.discord(method, url[len("https://discord.com/api/v10"):], kw)
        return Resp(599, {})

    def writes(self):
        """改東西的請求（不算 Notion 搜尋這種用 POST 的讀取、Google 換 token）。"""
        out = []
        for m, u, _ in self.calls:
            if m in ("PUT", "PATCH", "DELETE"):
                out.append((m, u))
            elif m == "POST" and not (u.endswith("/search") or "oauth2.googleapis.com" in u):
                out.append((m, u))
        return out

    def notion(self, method, path, kw):
        if (kw.get("headers") or {}).get("Authorization") != f"Bearer {NOTION}" or self.notion_status == 401:
            return Resp(401, {"object": "error", "message": "API token is invalid."})
        if path == "/users/me":
            return Resp(200, {"object": "user", "name": "SYNOX", "bot": {"workspace_name": "我的工作區"}})
        if path == "/search":
            kind = kw["json"]["filter"]["value"]
            page = {"object": "page", "id": "p1", "properties": {"t": {"type": "title", "title": [{"plain_text": "首頁"}]}}}
            return Resp(200, {"results": [page] if kind == "page" and self.notion_pages else []})
        if path == "/pages" and method == "POST":
            return Resp(200, {"object": "page", "id": "new-page"})
        if path == "/pages/new-page" and method == "PATCH":
            return Resp(200, {"object": "page", "id": "new-page", "in_trash": True})
        return Resp(404, {"message": "nope"})

    def todoist(self, method, path, kw):
        if (kw.get("headers") or {}).get("Authorization") != f"Bearer {TODOIST}":
            return Resp(401, {"error": "Unauthorized"})
        if path == "projects":
            return Resp(200, {"results": [{"id": "p", "name": "Inbox", "inbox_project": True}], "next_cursor": None})
        if path == "tasks" and method == "GET":
            return Resp(200, {"results": [{"id": "t1", "content": "a"}, {"id": "t2", "content": "b"}], "next_cursor": None})
        if path == "tasks/filter":
            return Resp(200, {"results": [{"id": "t1", "content": "a"}], "next_cursor": None})
        if path == "tasks" and method == "POST":
            return Resp(200, {"id": "t9", "content": kw["json"]["content"]})
        if path == "tasks/t9" and method == "DELETE":
            return Resp(204)
        return Resp(404, {})

    def google(self, method, url, kw):
        if url == "https://oauth2.googleapis.com/token":
            data = kw.get("data") or {}
            if data.get("refresh_token") != G_REFRESH:
                return Resp(400, {"error": "invalid_grant"})
            return Resp(200, {"access_token": "ya29.fresh-access", "expires_in": 3600})
        if (kw.get("headers") or {}).get("Authorization") != "Bearer ya29.fresh-access":
            return Resp(401, {})
        events = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        if url == events and method == "GET":
            return Resp(200, {"items": [{"id": "e1", "summary": "看牙醫", "start": {"date": "2026-11-10"},
                                         "end": {"date": "2026-11-11"}}]})
        if url == events and method == "POST":
            return Resp(200, {"id": "ev-new", "summary": kw["json"]["summary"], "start": kw["json"]["start"]})
        if url == events + "/ev-new" and method == "DELETE":
            return Resp(204)
        return Resp(404, {})

    def caldav(self, method, url, kw):
        if self.auth != ("me@icloud.com", APPLE_PW):
            return Resp(401, raw=b"")
        if method == "PROPFIND" and url == CAL_BASE:
            return Resp(207, raw=_ms(("/", "<d:current-user-principal><d:href>/123/principal/</d:href>"
                                           "</d:current-user-principal>")))
        if method == "PROPFIND" and url == PRINCIPAL:
            return Resp(207, raw=_ms((PRINCIPAL, f"<c:calendar-home-set><d:href>{HOME}</d:href></c:calendar-home-set>")))
        if method == "PROPFIND" and url == HOME:
            rows = [("/123/calendars/home/", "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                     "<d:displayname>行事曆</d:displayname><c:supported-calendar-component-set>"
                     '<c:comp name="VEVENT"/></c:supported-calendar-component-set>')]
            if self.apple_lists:
                rows.append(("/123/calendars/rem/", "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
                             "<d:displayname>提醒事項</d:displayname><c:supported-calendar-component-set>"
                             '<c:comp name="VTODO"/></c:supported-calendar-component-set>'))
            return Resp(207, raw=_ms(*rows))
        if method == "REPORT":
            rows = [(h.replace("https://p42-caldav.icloud.com", ""),
                     f"<d:getetag>{e}</d:getetag><c:calendar-data>{ics}</c:calendar-data>")
                    for h, (ics, e) in self.ics.items() if h.startswith(url)]
            return Resp(207, raw=_ms(*rows))
        if method == "PUT":
            headers = kw.get("headers") or {}
            text = kw["data"].decode("utf-8")
            if headers.get("If-None-Match") == "*":
                self.ics[url] = (text, '"new"')
                return Resp(201, raw=b"")
            if headers.get("If-Match") != self.ics.get(url, ("", ""))[1]:
                return Resp(412, raw=b"")
            self.ics[url] = (text, '"done"')
            return Resp(204, raw=b"")
        if method == "GET" and url in self.ics:
            ics, etag = self.ics[url]
            return Resp(200, raw=ics.encode("utf-8"), headers={"ETag": etag})
        return Resp(404, raw=b"")

    def discord(self, method, path, kw):
        if (kw.get("headers") or {}).get("Authorization") != f"Bot {DISCORD_TOKEN}" or self.discord_status == 401:
            return Resp(401, {"message": "401: Unauthorized", "code": 0})
        if path == "/users/@me":
            return Resp(200, {"id": "4242", "username": "synox-bot", "bot": True})
        if path == "/gateway/bot":
            return Resp(200, {"url": "wss://gateway.discord.gg", "shards": 1,
                              "session_start_limit": {"total": 1000, "remaining": 998}})
        if path == "/applications/@me":
            return Resp(200, {"id": "4242", "flags": self.discord_flags})
        return Resp(404, {})


# ── 準備：設定、保管箱、存好的憑證 ────────────────────────────────────

@pytest.fixture
def env(tmp_path):
    data = tmp_path / "data"
    raw = {"owner_id": 1, "data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "none"},
           "channels": {"discord": {"enabled": True, "bot_token": "vault:discord_bot_token"}}}
    config = SynoxConfig.from_dict(raw, require_token=False, root=str(tmp_path))
    vault = Vault(b"k" * 32, str(data))
    return config, vault


def seed(config, vault, *, notion=True, todoist=True, gcal=True, apple=True, discord=True, paired=True):
    d = config.data_dir
    if notion:
        PackStore("notion", d, vault).save({"token": NOTION, "bot": "SYNOX"})
    if todoist:
        PackStore("todoist", d, vault).save({"token": TODOIST})
    if gcal:
        PackStore("google-calendar", d, vault).save({"client_id": G_CID, "client_secret": G_SECRET,
                                                     "refresh_token": G_REFRESH, "access_token": "ya29.old-SECRET",
                                                     "expires_at": 0, "scope": "https://www.googleapis.com/auth/calendar.events"})
    if apple:
        PackStore("apple-reminders", d, vault).save({"server": "https://caldav.icloud.com", "username": "me@icloud.com",
                                                     "password": APPLE_PW}, key="auth")
    if discord:
        vault.set_secret("discord_bot_token", DISCORD_TOKEN)
    if paired:
        Identities(config.path("identities.json")).bind(DISCORD, "777", 1)


def make(config, vault, net, **kw):
    out = []
    kw.setdefault("interactive", False)
    smoke = smoke_real.Smoke(config, vault, http=net, out=out.append, now=lambda: NOW, **kw)
    return smoke, out


def result(smoke, service, item_start):
    rows = [r for r in smoke.rows if r.service == service and r.item.startswith(item_start)]
    assert rows, f"no row {service}/{item_start}: {[(r.service, r.item) for r in smoke.rows]}"
    return rows[0]


SECRETS = (NOTION, TODOIST, G_CID, G_SECRET, G_REFRESH, APPLE_PW, DISCORD_TOKEN, "ya29.old-SECRET", "ya29.fresh-access")


def assert_no_secret(text):
    for s in SECRETS:
        assert s not in text


# ── 唯讀（預設） ─────────────────────────────────────────────────────

def test_read_only_all_green_and_no_writes(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    smoke, out = make(config, vault, net)
    rc = smoke.run()
    text = "\n".join(out)
    assert rc == 0, text
    assert all(r.result == smoke_real.OK for r in smoke.rows), [(r.item, r.result, r.reason) for r in smoke.rows]
    for service in smoke_real.SERVICES:
        assert any(r.service == service for r in smoke.rows)
    assert net.writes() == []                                      # 一個寫入都沒有
    assert "integration：SYNOX，工作區：我的工作區" in result(smoke, "notion", "token 驗證").reason
    assert result(smoke, "todoist", "列任務").reason == "2 項還沒做完"
    assert result(smoke, "gcal", "今天").reason == "1 個"
    assert "提醒事項" in result(smoke, "apple", "列清單").reason
    assert "synox-bot" in result(smoke, "discord", "bot default：身分").reason
    assert "998/1000" in result(smoke, "discord", "bot default：Gateway").reason
    assert result(smoke, "discord", "擁有者配對").result == smoke_real.OK
    assert "| 服務 | 項目 | 結果 | 原因／下一步 |" in text
    assert "部署測試板" in text and "【真機煙霧測試】2026-11-10 09:30（smoke_real.py，唯讀）" in text
    assert_no_secret(text)


def test_google_refresh_is_not_written_back_to_the_vault(env):
    config, vault = env
    seed(config, vault)
    path = PackStore("google-calendar", config.data_dir, vault).file()
    before = open(path, "rb").read()
    smoke, _ = make(config, vault, FakeNet())
    smoke.run(("gcal",))
    assert open(path, "rb").read() == before                       # 保管箱一個 byte 都沒動
    assert PackStore("google-calendar", config.data_dir, vault).load()["access_token"] == "ya29.old-SECRET"


def test_missing_credentials_are_skipped_with_a_hint(env):
    config, vault = env
    smoke, out = make(config, vault, FakeNet())
    rc = smoke.run(("notion", "todoist", "gcal", "apple"))
    assert rc == 0
    for service in ("notion", "todoist", "gcal", "apple"):
        row = result(smoke, service, "設定")
        assert row.result == smoke_real.SKIP and row.hint
    assert "/notion_token" in result(smoke, "notion", "設定").hint
    assert "Connect-Apple.bat" in result(smoke, "apple", "設定").hint


def test_no_vault_at_all_asks_with_getpass_and_never_prints_it(env):
    config, _vault = env
    net = FakeNet()
    asked = []

    def secret(prompt):
        asked.append(prompt)
        return {"Notion": NOTION, "Todoist": TODOIST}[prompt.split(" ")[0]]
    smoke, out = make(config, None, net, interactive=True, ask_secret=secret)
    rc = smoke.run(("notion", "todoist"))
    assert rc == 0, out
    assert len(asked) == 2 and all("不會顯示" in p for p in asked)
    assert_no_secret("\n".join(out))


def test_open_vault_readonly_does_not_create_a_key(env):
    config, _vault = env
    assert smoke_real.open_vault_readonly(config) is None
    assert not os.path.exists(os.path.join(config.data_dir, ".synox.key"))


# ── 錯誤要變成人話 ───────────────────────────────────────────────────

def test_notion_bad_token_uses_the_connector_message(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    net.notion_status = 401
    smoke, out = make(config, vault, net)
    assert smoke.run(("notion",)) == 1
    row = result(smoke, "notion", "token 驗證")
    assert row.result == smoke_real.FAIL and "Notion 不認這個 token" in row.reason
    assert result(smoke, "notion", "搜尋").result == smoke_real.SKIP
    text = "\n".join(out)
    assert "問題：" in text and "Notion／token 驗證" in text
    assert_no_secret(text)


def test_notion_nothing_shared_is_a_failure_with_the_share_hint(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    net.notion_pages = False
    smoke, _ = make(config, vault, net)
    smoke.run(("notion",))
    row = result(smoke, "notion", "搜尋頁面")
    assert row.result == smoke_real.FAIL and "分享給你的 integration" in row.reason


def test_notion_token_saved_by_connect_is_flagged(env):
    """python -m synox connect notion 把 token 存在 key=auth，但 /notion 讀的是預設那一份：要說出來。"""
    config, vault = env
    PackStore("notion", config.data_dir, vault).save({"token": NOTION}, key="auth")
    smoke, _ = make(config, vault, FakeNet())
    smoke.run(("notion",))
    row = result(smoke, "notion", "token 存的位置")
    assert row.result == smoke_real.FAIL and "/notion_token" in row.hint
    assert result(smoke, "notion", "token 驗證").result == smoke_real.OK


def test_icloud_without_caldav_lists_explains_the_apple_limit(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    net.apple_lists = False
    smoke, out = make(config, vault, net)
    smoke.run(("apple",))
    assert result(smoke, "apple", "登入").result == smoke_real.OK
    row = result(smoke, "apple", "列清單")
    assert row.result == smoke_real.FAIL
    assert "iOS 13" in row.reason and "別家 CalDAV" in row.hint
    assert_no_secret("\n".join(out))


def test_apple_wrong_password(env):
    config, vault = env
    seed(config, vault)
    PackStore("apple-reminders", config.data_dir, vault).save(
        {"server": "https://caldav.icloud.com", "username": "me@icloud.com", "password": "wrong-pass-1234"}, key="auth")
    smoke, out = make(config, vault, FakeNet())
    smoke.run(("apple",))
    row = result(smoke, "apple", "登入")
    assert row.result == smoke_real.FAIL and "App 專用密碼" in row.reason
    assert "wrong-pass-1234" not in "\n".join(out)


def test_discord_intent_off_and_bad_token(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    net.discord_flags = 0
    smoke, _ = make(config, vault, net)
    smoke.run(("discord",))
    row = result(smoke, "discord", "bot default：Message Content")
    assert row.result == smoke_real.FAIL and "4014" in row.reason and "Privileged Gateway Intents" in row.hint
    net = FakeNet()
    net.discord_status = 401
    smoke, out = make(config, vault, net)
    smoke.run(("discord",))
    assert "4004" in result(smoke, "discord", "bot default：身分").reason
    assert_no_secret("\n".join(out))


def test_discord_missing_token_and_unpaired(env):
    config, vault = env
    seed(config, vault, discord=False, paired=False)
    smoke, _ = make(config, vault, FakeNet())
    smoke.run(("discord",))
    row = result(smoke, "discord", "bot default：token")
    assert row.result == smoke_real.FAIL and "python -m synox discord token" in row.hint
    pair = result(smoke, "discord", "擁有者配對")
    assert pair.result == smoke_real.FAIL and "discord pair" in pair.reason


def test_unexpected_errors_do_not_leak_their_message(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    net.blow_up = ("api.todoist.com", RuntimeError(f"boom {TODOIST}"))
    smoke, out = make(config, vault, net)
    smoke.run(("todoist",))
    row = result(smoke, "todoist", "token 驗證")
    assert row.result == smoke_real.FAIL and "RuntimeError" in row.reason
    assert_no_secret("\n".join(out))


def test_redact_hides_every_secret_it_has_seen(env):
    config, vault = env
    smoke, out = make(config, vault, FakeNet())
    smoke.keep_secret("super-secret-value")
    smoke.out("token=super-secret-value!")
    assert out == ["token=***!"]


# ── --write ──────────────────────────────────────────────────────────

def test_write_lists_the_plan_and_does_nothing_without_yes(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    smoke, out = make(config, vault, net, write=True, confirm=lambda _: "no",
                      notion_parent="https://www.notion.so/Home-11111111222233334444555555555555")
    smoke.run()
    text = "\n".join(out)
    assert "要做的寫入" in text and text.count(smoke_real.MARK) >= 4
    assert net.writes() == []
    skipped = [r for r in smoke.rows if r.item.startswith("寫入")]
    assert {r.service for r in skipped} == set(smoke_real.SERVICES)
    assert all(r.result == smoke_real.SKIP for r in skipped)


def test_write_with_yes_creates_and_cleans_up(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    smoke, out = make(config, vault, net, write=True, confirm=lambda _: " YES ",
                      notion_parent="https://www.notion.so/Home-11111111222233334444555555555555")
    assert smoke.run() == 0, "\n".join(out)
    w = net.writes()
    assert ("POST", "https://api.notion.com/v1/pages") in w and ("PATCH", "https://api.notion.com/v1/pages/new-page") in w
    assert ("POST", "https://api.todoist.com/api/v1/tasks") in w
    assert ("DELETE", "https://api.todoist.com/api/v1/tasks/t9") in w
    events = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    assert ("POST", events) in w and ("DELETE", events + "/ev-new") in w
    puts = [u for m, u in w if m == "PUT"]
    assert len(puts) == 2 and puts[0] == puts[1] and puts[0].startswith(REM)
    assert "STATUS:COMPLETED" in net.ics[puts[0]][0] and smoke_real.MARK in net.ics[puts[0]][0]
    assert not any("discord.com" in u for _m, u in w)                # Discord 不寫
    titles = [c[2].get("json", {}) for c in net.calls if c[0] == "POST" and "todoist" in c[1]]
    assert titles and smoke_real.MARK in titles[0]["content"]
    for service in ("notion", "todoist", "gcal", "apple"):
        assert result(smoke, service, "寫入").result == smoke_real.OK
    assert "（smoke_real.py，含寫入）" in "\n".join(out)


def test_write_notion_without_parent_is_skipped(env):
    config, vault = env
    seed(config, vault)
    net = FakeNet()
    smoke, _ = make(config, vault, net, write=True, confirm=lambda _: "yes")
    smoke.run(("notion",))
    assert result(smoke, "notion", "寫入").result == smoke_real.SKIP
    assert net.writes() == []


def test_parse_only():
    assert smoke_real.parse_only("") == smoke_real.SERVICES
    assert smoke_real.parse_only("Notion, discord") == ("notion", "discord")
    with pytest.raises(ValueError):
        smoke_real.parse_only("notion,slack")
