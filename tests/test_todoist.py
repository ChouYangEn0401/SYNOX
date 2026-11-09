# -*- coding: utf-8 -*-
"""Todoist connector（connectors/todoist）：全部用假的 HTTP session（一個記憶體裡的小 Todoist），不打真的 Todoist、不開埠。"""

import json
import logging
import os
import sys
from datetime import datetime
from urllib.parse import urlsplit

import pytest
import requests

from isdtelekit.users.roles import BasicRoles

from synox.packs import scan
from synox.packs.manifest import read
from synox.packs.loader import discover

TOKEN = "0123456789abcdef0123456789abcdef01234567"
OTHER_TOKEN = "fedcba9876543210fedcba9876543210fedcba98"
TODAY = datetime(2026, 11, 9, 10, 0)            # 星期一
API = "https://api.todoist.com/api/v1/"


class Resp:
    def __init__(self, status, data=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = b"" if data is None else json.dumps(data).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class FakeTodoist:
    """requests.Session 的替身：request(method, url, params=, json=, headers=, timeout=) → 記憶體裡的 Todoist。"""

    def __init__(self, tokens=(TOKEN,)):
        self.tokens = set(tokens)
        self.calls = []
        self.fail = None                      # 下一次回這個（Resp 或 Exception）
        self.page_size = 200
        self.projects = [{"id": "p_inbox", "name": "Inbox", "inbox_project": True},
                         {"id": "p_home", "name": "家事"}]
        self.labels = [{"id": "l1", "name": "電話"}]
        self.tasks = {}
        self._n = 0

    def seed(self, content, **kw):
        self._n += 1
        tid = f"t{self._n:04d}X"
        self.tasks[tid] = {"id": tid, "content": content, "project_id": kw.pop("project_id", "p_inbox"),
                           "labels": kw.pop("labels", []), "priority": kw.pop("priority", 1),
                           "due": kw.pop("due", None), "checked": False, **kw}
        return tid

    def _page(self, rows, params):
        start = int((params or {}).get("cursor") or 0)
        end = start + min(int((params or {}).get("limit") or 50), self.page_size)
        return Resp(200, {"results": rows[start:end], "next_cursor": str(end) if end < len(rows) else None})

    def request(self, method, url, params=None, json=None, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({"method": method, "url": url, "params": dict(params or {}), "json": json,
                           "auth": (headers or {}).get("Authorization"), "timeout": timeout})
        assert url.startswith(API), url
        assert timeout, "every request must have a timeout"
        if self.fail is not None:
            fail, self.fail = self.fail, None
            if isinstance(fail, Exception):
                raise fail
            return fail
        if (headers or {}).get("Authorization", "").replace("Bearer ", "") not in self.tokens:
            return Resp(401, {"error": "Unauthorized"})
        path = urlsplit(url).path[len("/api/v1/"):]
        parts = path.split("/")
        active = [t for t in self.tasks.values() if not t["checked"]]
        if method == "GET" and path == "projects":
            return self._page(self.projects, params)
        if method == "GET" and path == "labels":
            return self._page(self.labels, params)
        if method == "GET" and path == "tasks":
            rows = active
            if params.get("project_id"):
                rows = [t for t in rows if t["project_id"] == params["project_id"]]
            if params.get("label"):
                rows = [t for t in rows if params["label"] in t["labels"]]
            return self._page(rows, params)
        if method == "GET" and path == "tasks/filter":
            iso = TODAY.date().isoformat()
            day = lambda t: (t.get("due") or {}).get("date", "")[:10]
            if params["query"] == "today":
                rows = [t for t in active if day(t) == iso]
            elif params["query"] == "overdue":
                rows = [t for t in active if day(t) and day(t) < iso]
            else:
                return Resp(400, {"error": "bad filter"})
            return self._page(rows, params)
        if method == "POST" and path == "tasks":
            tid = self.seed(json["content"], project_id=json.get("project_id", "p_inbox"),
                            labels=json.get("labels", []), priority=json.get("priority", 1))
            self.tasks[tid]["due"] = self._due(json)
            return Resp(200, self.tasks[tid])
        if len(parts) >= 2 and parts[0] == "tasks":
            t = self.tasks.get(parts[1])
            if t is None:
                return Resp(404, {"error": "Task not found"})
            if method == "GET" and len(parts) == 2:
                return Resp(200, t)
            if method == "POST" and len(parts) == 2:
                if any(k.startswith("due_") for k in json):
                    t["due"] = self._due(json)
                return Resp(200, t)
            if method == "POST" and parts[2:] == ["close"]:
                if (t.get("due") or {}).get("is_recurring"):
                    t["due"] = {**t["due"], "date": "2026-11-16"}
                else:
                    t["checked"] = True
                return Resp(204)
            if method == "DELETE" and len(parts) == 2:
                del self.tasks[parts[1]]
                return Resp(204)
        return Resp(404, {"error": "no such endpoint"})

    @staticmethod
    def _due(body):
        if body.get("due_datetime"):
            return {"date": body["due_datetime"], "string": body["due_datetime"], "is_recurring": False}
        if body.get("due_date"):
            return {"date": body["due_date"], "string": body["due_date"], "is_recurring": False}
        s = body.get("due_string")
        if s == "no date":
            return None
        if s:
            return {"date": "2026-11-16", "string": s, "is_recurring": s.startswith("every")}
        return None

    def last(self, method=None):
        calls = [c for c in self.calls if method is None or c["method"] == method]
        return calls[-1] if calls else None


@pytest.fixture
def todoist(make_bot):
    """(bot, fake, module)：裝好 connectors/todoist、HTTP 換成 FakeTodoist、今天固定 2026-11-09（一）。"""
    def factory(script=None, *, connect=True, **kw):
        bot = make_bot(script, **kw)
        mod = sys.modules["synox_pack_todoist"]
        fake = FakeTodoist()
        mod.HTTP = fake
        mod.now = lambda: TODAY
        if connect:
            bot.say(100, f"/todoist_token {TOKEN}")
            assert "接上 Todoist 了" in bot.last(100)
            fake.calls.clear()
        return bot, fake, mod
    return factory


# ── 安全五關、設定 ──────────────────────────────────────────────────────

def test_manifest_and_static_scan_pass():
    folder = next(f for f in discover() if os.path.basename(f) == "todoist")
    m = read(folder, strict=True)                                  # 第 1 關（安裝時的嚴格版）
    assert m.kind == "python" and m.capabilities == ["network"] and m.storage == "vault"
    report = scan.scan(m)                                          # 第 2 關
    assert report.problems(m) == []
    assert report.required_capabilities == ["network"]


def test_not_connected_says_how(todoist, owner):
    bot, fake, _ = todoist(connect=False)
    bot.say(owner, "/todoist_list")
    assert "還沒接上 Todoist" in bot.last(owner) and "/todoist_token" in bot.last(owner)
    bot.say(owner, "/todoist 繳電費")
    assert "還沒接上" in bot.last(owner)
    assert fake.calls == []


def test_token_is_checked_encrypted_and_not_logged(todoist, owner, caplog):
    bot, fake, _ = todoist(connect=False)
    bot.say(owner, "/todoist_token 太短")
    assert "不是 Todoist 的 API token" in bot.last(owner) and fake.calls == []
    bot.say(owner, f"/todoist_token {OTHER_TOKEN}")               # Todoist 說 401 → 不存
    assert "沒存" in bot.last(owner)
    vault = bot.app.extras["vault"]
    assert not vault.exists("todoist")
    with caplog.at_level(logging.INFO):
        bot.say(owner, f"/todoist_token {TOKEN}")
    assert "接上 Todoist 了（看得到 2 個專案）" in bot.last(owner)
    assert fake.last()["auth"] == f"Bearer {TOKEN}"
    raw = open(vault.path("todoist"), "rb").read()
    assert TOKEN.encode() not in raw                               # 密文
    assert vault.load_json("todoist")["token"] == TOKEN
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "/todoist_token" in logged and TOKEN not in logged      # [ROUTE] 那一行遮掉了
    bot.say(owner, "/todoist_token")
    assert "已經接上了" in bot.last(owner) and TOKEN not in bot.last(owner)
    bot.say(owner, "/todoist_logout")
    assert "拔掉了" in bot.last(owner)
    assert not (vault.load_json("todoist") or {}).get("token")
    bot.say(owner, "/todoist_list")
    assert "還沒接上" in bot.last(owner)


def test_token_command_is_not_an_ai_tool(todoist, owner):
    bot, _, _ = todoist(["好"])
    bot.talk(owner, "Todoist 今天有什麼")
    _messages, tools = bot.app.extras["synox_agent"].adapter.calls[0]
    names = {t.name for t in tools}
    assert {"todoist__add", "todoist__list", "todoist__done", "todoist__due", "todoist__rm"} <= names
    assert "todoist__token" not in names and "todoist__logout" not in names


def test_stranger_cannot_see_it(todoist, owner):
    from conftest import OTHER_ID
    bot, fake, _ = todoist()
    bot.say(OTHER_ID, "/todoist_list")
    assert "Todoist" not in bot.last(OTHER_ID)                     # owner-only：跟不存在一樣
    assert fake.calls == []


# ── 加 ─────────────────────────────────────────────────────────────────

def test_add_same_syntax_as_todo_pack(todoist, owner):
    bot, fake, _ = todoist()
    bot.say(owner, "/todoist !! 繳電費 明天 #家事 @電話")
    body = fake.last("POST")["json"]
    assert body == {"content": "繳電費", "due_date": "2026-11-10", "priority": 4, "project_id": "p_home",
                    "labels": ["電話"]}
    reply = bot.last(owner)
    assert reply.startswith("✅ 加到 Todoist 了：☐ [1] ‼️ 繳電費 · 明天 11/10（二）")
    assert "#家事" in reply and "@電話" in reply


def test_add_unknown_hash_becomes_label_and_time(todoist, owner):
    bot, fake, _ = todoist()
    bot.say(owner, "/todoist ! 打給房東 下午3點 #租屋")
    body = fake.last("POST")["json"]
    assert body["labels"] == ["租屋"] and "project_id" not in body
    assert body["due_datetime"] == "2026-11-09T15:00:00" and body["priority"] == 3
    assert "今天 11/09（一） 15:00" in bot.last(owner)


def test_add_fields_like_ai_and_due_string_passthrough(todoist, owner):
    bot, fake, _ = todoist()
    bot.say(owner, "/todoist 倒垃圾 due=every monday priority=1")
    body = fake.last("POST")["json"]
    assert body == {"content": "倒垃圾", "due_string": "every monday", "priority": 3}
    assert "🔁" in bot.last(owner)
    bot.say(owner, "/todoist 沒有期限的事")
    assert fake.last("POST")["json"] == {"content": "沒有期限的事"}
    bot.say(owner, "/todoist 2026-02-30 交稿")
    assert "不是真的日期" in bot.last(owner)


def test_add_via_ai(todoist, owner):
    bot, fake, _ = todoist([{"tool": "todoist__add", "args": {"text": "買燈泡 #家事", "due": "週五"}}, "加好了"])
    bot.talk(owner, "Todoist 幫我加一個週五買燈泡，放家事")
    assert bot.last(owner) == "加好了"
    assert fake.last("POST")["json"] == {"content": "買燈泡", "due_date": "2026-11-13", "project_id": "p_home"}


# ── 看 ─────────────────────────────────────────────────────────────────

def test_list_filters_and_stable_numbers(todoist, owner):
    bot, fake, _ = todoist()
    fake.seed("逾期的帳單", due={"date": "2026-11-01"})
    fake.seed("今天開會", due={"date": "2026-11-09T14:00:00"}, priority=4)
    fake.seed("家裡的事", project_id="p_home", labels=["電話"])
    bot.say(owner, "/todoist_list")
    text = bot.last(owner)
    assert text.splitlines()[0] == "✅ 還沒做完（3 項）"
    lines = text.splitlines()[1:]
    assert lines[0].startswith("☐ [1] 逾期的帳單 · ⚠️逾期")
    assert lines[1] == "☐ [2] ‼️ 今天開會 · 今天 11/09（一） 14:00"
    assert lines[2] == "☐ [3] 家裡的事 #家事 @電話"
    fake.seed("新的", due={"date": "2026-11-09"})
    bot.say(owner, "/todoist_list today")
    assert fake.last("GET")["params"]["query"] == "today"
    today = bot.last(owner)
    assert "[2] ‼️ 今天開會" in today and "[4] 新的" in today and "逾期的帳單" not in today   # 編號不變
    bot.say(owner, "/todoist_list overdue")
    assert "[1] 逾期的帳單" in bot.last(owner) and "今天開會" not in bot.last(owner)
    bot.say(owner, "/todoist_list #家事")
    assert fake.last("GET")["params"]["project_id"] == "p_home" and "[3] 家裡的事" in bot.last(owner)
    bot.say(owner, "/todoist_list @電話")
    assert fake.last("GET")["params"]["label"] == "電話" and "[3] 家裡的事" in bot.last(owner)
    bot.say(owner, "/todoist_list @沒有這個")
    assert "沒有。🎉" in bot.last(owner)
    bot.say(owner, "/todoist_list 亂寫")
    assert "只能是" in bot.last(owner)


def test_list_follows_pagination(todoist, owner):
    bot, fake, mod = todoist()
    fake.page_size = 2
    for i in range(5):
        fake.seed(f"事{i}")
    bot.say(owner, "/todoist_list")
    assert bot.last(owner).splitlines()[0] == "✅ 還沒做完（5 項）"
    cursors = [c["params"].get("cursor") for c in fake.calls if c["url"].endswith("/tasks")]
    assert cursors == [None, "2", "4"]


def test_projects_and_labels(todoist, owner):
    bot, _, _ = todoist()
    bot.say(owner, "/todoist_projects")
    assert "Inbox（收件匣）" in bot.last(owner) and "• 家事" in bot.last(owner)
    bot.say(owner, "/todoist_labels")
    assert "@電話" in bot.last(owner)


# ── 完成、改期、刪 ──────────────────────────────────────────────────────

def test_done_by_number(todoist, owner):
    bot, fake, _ = todoist()
    tid = fake.seed("繳電費")
    bot.say(owner, "/todoist_list")
    bot.say(owner, "/todoist_done 1")
    assert bot.last(owner) == "☑ 完成：繳電費"
    assert fake.last("POST")["url"].endswith(f"/tasks/{tid}/close")
    assert fake.tasks[tid]["checked"]
    bot.say(owner, "/todoist_done 1")                               # 完成了就收回編號
    assert "沒有 [1] 這一項" in bot.last(owner)
    bot.say(owner, f"/todoist_done {tid}")                          # 也收 Todoist 原本的 id
    assert "早就完成了" in bot.last(owner)


def test_done_recurring_moves_to_next(todoist, owner):
    bot, fake, _ = todoist()
    fake.seed("倒垃圾", due={"date": "2026-11-09", "is_recurring": True})
    bot.say(owner, "/todoist_list")
    bot.say(owner, "/todoist_done 1")
    assert "完成這一次" in bot.last(owner) and "11/16" in bot.last(owner)
    bot.say(owner, "/todoist_list")
    assert "[1] 倒垃圾" in bot.last(owner)                          # 重複的：編號留著


def test_reschedule(todoist, owner):
    bot, fake, _ = todoist()
    tid = fake.seed("報告", due={"date": "2026-11-10"})
    bot.say(owner, "/todoist_list")
    bot.say(owner, "/todoist_due 1 下週一 10:00")
    assert fake.last("POST")["json"] == {"due_datetime": "2026-11-16T10:00:00"}
    assert bot.last(owner).startswith("📅 改期了：☐ [1] 報告 · 11/16（一） 10:00")
    bot.say(owner, "/todoist_due 1 無")
    assert fake.last("POST")["json"] == {"due_string": "no date"}
    assert fake.tasks[tid]["due"] is None and "拿掉到期" in bot.last(owner)
    bot.say(owner, "/todoist_due 1")
    assert "用法" in bot.last(owner)


def test_rm_typed_and_ai_needs_card(todoist, owner):
    bot, fake, _ = todoist([{"tool": "todoist__rm", "args": {"n": "1"}}])
    tid = fake.seed("不要的")
    bot.say(owner, "/todoist_list")
    fake.calls.clear()
    bot.talk(owner, "把 Todoist 第一個刪掉")
    assert "AI 想執行：/todoist_rm" in bot.last(owner)
    assert fake.last("DELETE") is None and tid in fake.tasks       # 還沒按，什麼都沒刪
    go = [b for b in bot.buttons(owner) if b.startswith("agent_ok:go:")][0]
    bot.press(owner, go)
    assert "從 Todoist 刪掉了：不要的" in bot.last(owner)
    assert tid not in fake.tasks


def test_ids_cannot_escape_the_api_path(todoist, owner):
    bot, fake, _ = todoist()
    for bad in ("../../projects", "a/b", "x?y=1"):
        bot.say(owner, f"/todoist_done {bad}")
        assert "編號" in bot.last(owner)
    assert fake.calls == []


# ── 出錯的時候 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("fail,needle", [
    (Resp(429, {"error": "Too many"}, {"Retry-After": "30"}), "30 秒後再試"),
    (Resp(500, {"error": "boom"}), "Todoist 那邊出錯了（500）"),
    (Resp(401, {"error": "Unauthorized"}), "/todoist_token 重新設定"),
    (Resp(400, {"error": "Invalid argument value"}), "Invalid argument value"),
    (Resp(200, None), "沒有專案"),
    (requests.Timeout(), "逾時"),
    (requests.ConnectionError(), "連不上 Todoist"),
])
def test_errors_become_one_sentence(todoist, owner, fail, needle):
    bot, fake, _ = todoist()
    fake.projects = []
    bot.say(owner, "/todoist_projects")                            # 先把 projects 那次叫完
    fake.fail = fail
    bot.say(owner, "/todoist_projects")
    assert needle in bot.last(owner)


def test_missing_task(todoist, owner):
    bot, fake, _ = todoist()
    bot.say(owner, "/todoist_done nosuchid123")
    assert "找不到這一項" in bot.last(owner)


# ── 伺服器版：每個人自己的 token ─────────────────────────────────────────

def test_server_mode_tokens_are_per_user(todoist, owner):
    bot, fake, mod = todoist(raw={"mode": "server"})
    fake.tokens.add(OTHER_TOKEN)
    vault = bot.app.extras["vault"]
    assert vault.for_user(owner).load_json("todoist")["token"] == TOKEN
    assert not os.path.exists(vault.path("todoist"))               # 不是共用的那一份
    # owner-only pack：成員看不到；這裡直接確認 store.of() 分開（換成 member 時每人一份）
    pack = next(p for p in bot.app.extras["synox_packs"] if p.name == "todoist")
    assert pack.store.of(77).load(None) is None
