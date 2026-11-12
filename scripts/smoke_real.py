"""
真機煙霧測試：在「可以上網、要真的接服務」的那台電腦上，逐一試 Notion、Todoist、Google 日曆、Apple 提醒事項（CalDAV）、Discord。

    .venv\\Scripts\\python.exe scripts\\smoke_real.py                  只讀（預設；不改任何服務上的東西）
    .venv\\Scripts\\python.exe scripts\\smoke_real.py --only notion,todoist
    .venv\\Scripts\\python.exe scripts\\smoke_real.py --write          另外做一個「建立後馬上刪掉／完成」的小寫入（會先問 yes）

教學：docs/handoff/real-service-testing.md。

規則：
- 直接用各工具自己的程式（pack.py 的 Notion、Client…、synox.discord 的 DiscordChannel），不另寫一套 API 呼叫，
  所以這裡通了＝SYNOX 用起來也通。四個服務的工具 2026-11-12 起在 SYNOX 工具庫（SYNOX_Libs）：先找這台裝好的
  （packs/、packs.dirs），沒裝就找工具庫的原始碼（環境變數 SYNOX_LIBS，沒設就找並排的 ../SYNOX_Libs）。
- 憑證：先讀 SYNOX 的保管箱（使用者先用 /notion_token、/todoist_token、/gcal_setup＋/gcal_code、Connect-Apple.bat、
  python -m synox discord token 設好）；保管箱沒有，就在這裡用 getpass 問（不顯示、不存、不寫檔）。
  憑證絕不印出：輸出前把這次碰到的每個憑證換成 ***；非預期的錯誤只印錯誤種類，不印內容。
- 預設只讀。保管箱也只讀：Google 換到的新 access token 放在記憶體，不寫回保管箱；沒有金鑰檔時不產生新的。
- --write：先跑完唯讀檢查，列出要做的寫入，輸入 yes 才做。每一個寫入都是標題含 "SYNOX-smoke-test" 的新東西，做完立刻刪掉
  （Notion 移到垃圾桶；Apple CalDAV 這版沒有刪除，改成打勾完成）。
- Discord 只查 bot 身分、Gateway 資訊、Message Content intent；不連 Gateway、不上線收訊、不送訊息。
- 測試：tests/test_smoke_real.py（假傳輸、假保管箱，不連網）。
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    import synox  # noqa: F401
except ImportError:                                   # 沒有 pip install -e . 時：直接用原始碼
    sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")]

from isdtelekit.host.config import ConfigError  # noqa: E402

from synox.config import SynoxConfig  # noqa: E402
from synox.packs.loader import PackStore, discover  # noqa: E402
from synox.packs.manifest import ManifestError, read  # noqa: E402

OK, FAIL, SKIP = "✅", "❌", "⏭"
MARK = "SYNOX-smoke-test"
SERVICES = ("notion", "todoist", "gcal", "apple", "discord")
LABEL = {"notion": "Notion", "todoist": "Todoist", "gcal": "Google 日曆", "apple": "Apple 提醒事項", "discord": "Discord"}
PACK = {"notion": "notion", "todoist": "todoist", "gcal": "google-calendar", "apple": "apple-reminders"}
ERROR_CLASS = {"notion": "NotionError", "todoist": "TodoistError", "gcal": "GoogleError", "apple": "CalDavError"}
GUIDE = "docs/handoff/real-service-testing.md"
MESSAGE_CONTENT_FLAGS = (1 << 18) | (1 << 19)        # Discord application flags：GATEWAY_MESSAGE_CONTENT(_LIMITED)


@dataclass
class Row:
    service: str
    item: str
    result: str
    reason: str = ""
    hint: str = ""


@dataclass
class Plan:
    """--write 要做的一件事：說明（給人看、問 yes 之前印）＋ 真的去做的函式（回成功的說明）。"""
    service: str
    item: str
    what: str
    run: Callable[[], str]


def libs_packs_dir() -> str:
    """SYNOX 工具庫的 packs/（環境變數 SYNOX_LIBS，沒設就找並排的 ../SYNOX_Libs）；找不到回 ""。只讀，不改工具庫。"""
    root = os.environ.get("SYNOX_LIBS") or os.path.join(os.path.dirname(ROOT), "SYNOX_Libs")
    packs = os.path.join(root, "packs")
    return packs if os.path.isdir(packs) else ""


class Skip(Exception):
    """這一項不用測（例如沒有設定）：結果 ⏭。"""


class MemoryStore:
    """保管箱那一份的「記憶體複本」：pack 的 Client 要寫（例如 Google 換到新的 access token）只寫在這裡，不動保管箱。"""

    def __init__(self, data: Optional[dict] = None):
        self._data: Dict[Optional[str], object] = {None: dict(data or {})}

    def load(self, default=None, key: Optional[str] = None):
        found = self._data.get(key)
        return found if found is not None else default

    def save(self, data, key: Optional[str] = None) -> None:
        self._data[key] = data

    def update(self, fn, default, key: Optional[str] = None):
        data = self.load(default, key)
        result = fn(data)
        self.save(data, key)
        return result


class Smoke:
    """跑一輪。http：測試放假的傳輸（一個有 request(method, url, **kw) 的物件）；None＝各 connector 自己的 requests。"""

    def __init__(self, config, vault, *, http=None, ask: Callable[[str], str] = input,
                 ask_secret: Callable[[str], str] = getpass.getpass, confirm: Callable[[str], str] = input,
                 out: Callable[[str], None] = print, interactive: bool = True, write: bool = False,
                 user: Optional[int] = None, notion_query: str = "", notion_parent: str = "",
                 now: Callable[[], datetime] = datetime.now):
        self.config = config
        self.vault = vault
        self.http = http
        self.ask = ask
        self.ask_secret = ask_secret
        self.confirm = confirm
        self._out = out
        self.interactive = interactive
        self.write = write
        self.user = user if user is not None else getattr(config, "owner_id", None)
        self.notion_query = notion_query
        self.notion_parent = notion_parent
        self.now = now
        self.rows: List[Row] = []
        self.plans: List[Plan] = []
        self.secrets: set = set()
        self._modules: Dict[str, object] = {}
        self.stamp = now().strftime("%Y%m%d-%H%M%S")

    # ── 輸出（一律先遮憑證） ─────────────────────────────────────────

    def redact(self, text: str) -> str:
        for s in sorted(self.secrets, key=len, reverse=True):
            if s and len(s) >= 4:
                text = text.replace(s, "***")
        return text

    def out(self, text: str = "") -> None:
        self._out(self.redact(text))

    def keep_secret(self, value: Optional[str]) -> Optional[str]:
        if value:
            self.secrets.add(str(value))
        return value

    def add(self, service: str, item: str, result: str, reason: str = "", hint: str = "") -> Row:
        row = Row(service, item, result, self.redact(reason), self.redact(hint))
        self.rows.append(row)
        return row

    # ── 共用 ─────────────────────────────────────────────────────────

    def module(self, service: str):
        """那個工具的 pack.py 原樣載入（不呼叫 install；只用裡面的 Client 與小工具）。
        先找這台裝好的（packs/、packs.dirs），再找工具庫的原始碼（libs_packs_dir）。"""
        if service in self._modules:
            return self._modules[service]
        wanted = PACK[service]
        dirs = tuple(self.config.pack_dirs()) + tuple(d for d in (libs_packs_dir(),) if d)
        for folder in discover(dirs):
            try:
                m = read(folder)
            except ManifestError:
                continue
            if m.name != wanted:
                continue
            path = os.path.join(m.folder, f"{m.python.get('module', 'pack')}.py")
            spec = importlib.util.spec_from_file_location(f"synox_smoke_{wanted.replace('-', '_')}", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod              # dataclass 要在 sys.modules 找得到模組
            spec.loader.exec_module(mod)
            self._modules[service] = (m, mod)
            return m, mod
        raise Skip(f"找不到 {wanted} 這個工具：先從 SYNOX 工具庫裝它，或設環境變數 SYNOX_LIBS=<SYNOX_Libs 資料夾>")

    def store(self, m):
        """這個 pack 在保管箱的那一份（跟 pack 自己讀的同一份）。沒有保管箱（金鑰檔還沒產生）＝空的。"""
        if self.vault is None:
            return MemoryStore()
        server = getattr(self.config, "mode", "personal") == "server"
        store = PackStore(m.name, self.config.data_dir, self.vault if m.storage == "vault" else None, per_user=server)
        if server:
            if not isinstance(self.user, int):
                raise Skip("伺服器版要指定替誰測：--user <Telegram id>")
            return store.of(self.user)
        return store

    def secret_input(self, prompt: str) -> str:
        if not self.interactive:
            return ""
        try:
            return (self.keep_secret((self.ask_secret(prompt + "（輸入時不會顯示；直接 Enter＝略過）：") or "").strip())
                    or "")
        except (EOFError, KeyboardInterrupt):
            return ""

    def plain_input(self, prompt: str, default: str = "") -> str:
        if not self.interactive:
            return ""
        try:
            got = (self.ask(prompt + (f" [{default}]" if default else "") + "：") or "").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        return got or default

    def check(self, service: str, item: str, fn: Callable[[], str], hint: str = "") -> bool:
        """fn() 回成功的說明；connector 自己的錯誤（中文）照印，其他例外只印種類（不印內容，免得帶出憑證）。"""
        try:
            reason = fn()
        except Skip as e:
            self.add(service, item, SKIP, str(e))
            return False
        except Exception as e:                       # noqa: BLE001 — 每一項都要有結果，不能讓一項炸掉整輪
            self.add(service, item, FAIL, self.explain(service, e), hint or f"看 {GUIDE}「常見錯誤」的 {LABEL[service]}")
            return False
        self.add(service, item, OK, reason)
        return True

    def explain(self, service: str, e: Exception) -> str:
        cls = ERROR_CLASS.get(service)
        mod = (self._modules.get(service) or (None, None))[1]
        if cls and mod is not None and isinstance(e, getattr(mod, cls, ())):
            return str(e)
        if isinstance(e, DiscordProblem):
            return str(e)
        return f"程式出錯（{type(e).__name__}）；細節不印（可能含憑證），請回報這一行"

    def missing(self, service: str, hint: str) -> None:
        self.add(service, "設定", SKIP, "保管箱裡沒有、這次也沒輸入", hint)

    # ── Notion ──────────────────────────────────────────────────────

    def notion(self) -> None:
        s = "notion"
        m, mod = self.module(s)
        store = self.store(m)
        token, source = mod.token_of(store)          # 跟 /notion 讀同一套：connect 存的優先，再來 /notion_token 存的
        if token:
            self.add(s, "token 存的位置", OK, f"用的是{mod.SOURCES[source]}")
        token = self.keep_secret(token) or self.secret_input("Notion integration token（ntn_ 開頭）")
        if not token:
            self.missing(s, "先在 Console.bat 打 /notion_token（或 python -m synox connect notion）設定，或這次直接輸入")
            return
        nc = mod.Notion(token, self.http)

        def me():
            info = nc.me()
            ws = (info.get("bot") or {}).get("workspace_name") or ""
            return f"integration：{info.get('name') or '?'}" + (f"，工作區：{ws}" if ws else "")
        if not self.check(s, "token 驗證", me):
            self.add(s, "搜尋", SKIP, "token 沒過，後面不測")
            return

        def pages():
            found = nc.search(self.notion_query, "page", n=5)
            if not found:
                raise mod.NotionError("API 通了，但一頁都看不到：還沒把頁面分享給 integration" + mod.HELP_SHARE)
            return f"看得到 {len(found)} 頁以上（例：{mod.title_of(found[0])}）"
        self.check(s, "搜尋頁面", pages)
        self.check(s, "搜尋資料庫", lambda: f"看得到 {len(nc.search('', 'data_source', n=5))} 個資料庫（0 個也沒關係）")
        if not self.write:
            return
        if not self.notion_parent:
            self.add(s, "寫入", SKIP, "沒有給 --notion-parent（測試頁要開在哪一頁底下）",
                     "加 --notion-parent <一頁的網址>，那一頁要先分享給 integration")
            return
        title = f"{MARK} {self.stamp}"

        def make_and_trash():
            parent_id = mod.parse_id(self.notion_parent)
            if not parent_id:
                raise mod.NotionError("--notion-parent 看不出是哪一頁（貼那一頁的網址）")
            page = nc.create({"type": "page_id", "page_id": parent_id}, {"title": {"title": mod.rich(title)}},
                             mod.paragraphs("SYNOX 煙霧測試建立的頁面，會立刻移到垃圾桶。"))
            pid = page.get("id") or ""
            for body in ({"in_trash": True}, {"archived": True}):
                try:
                    nc.call("PATCH", f"/pages/{pid}", body)
                    return f"建立「{title}」→ 已移到垃圾桶"
                except mod.NotionError:
                    continue
            raise mod.NotionError(f"建立成功，但移到垃圾桶失敗：請到 Notion 手動刪掉「{title}」")
        self.plans.append(Plan(s, "寫入（建立後移到垃圾桶）",
                               f"在 --notion-parent 那一頁底下開一頁「{title}」，再把它移到 Notion 的垃圾桶", make_and_trash))

    # ── Todoist ─────────────────────────────────────────────────────

    def todoist(self) -> None:
        s = "todoist"
        m, mod = self.module(s)
        token = self.keep_secret((self.store(m).load(None) or {}).get("token")) or self.secret_input("Todoist API token")
        if not token:
            self.missing(s, "先在 Console.bat 打 /todoist_token <token>（或這次直接輸入）")
            return
        c = mod.Client(token, self.http)
        if not self.check(s, "token 驗證（列專案）", lambda: f"看得到 {len(c.projects())} 個專案"):
            self.add(s, "列任務", SKIP, "token 沒過，後面不測")
            return
        self.check(s, "列任務", lambda: f"{len(c.tasks())} 項還沒做完")
        self.check(s, "今天到期", lambda: f"{len(c.filter('today'))} 項")
        if not self.write:
            return
        title = f"{MARK} {self.stamp}"

        def add_and_delete():
            made = c.add({"content": title})
            tid = str(made.get("id") or "")
            if not tid:
                raise mod.TodoistError("建立了但 Todoist 沒回編號：請到 Todoist 手動刪掉「" + title + "」")
            c.delete(tid)
            return f"建立「{title}」→ 已刪掉"
        self.plans.append(Plan(s, "寫入（建立後刪掉）", f"在收件匣加一項「{title}」，再把它刪掉", add_and_delete))

    # ── Google 日曆 ─────────────────────────────────────────────────

    def gcal(self) -> None:
        s = "gcal"
        m, mod = self.module(s)
        data = dict(self.store(m).load(None) or {})
        for k in ("client_id", "client_secret", "refresh_token", "access_token"):
            self.keep_secret(data.get(k))
        if not data.get("refresh_token"):
            got = {"client_id": self.secret_input("Google OAuth 用戶端 ID（…apps.googleusercontent.com）")}
            if got["client_id"]:
                got["client_secret"] = self.secret_input("Google OAuth 用戶端密鑰（GOCSPX-…）")
                got["refresh_token"] = self.secret_input("refresh token")
            if not all(got.values()):
                self.missing(s, "先在 Console.bat 打 /gcal_setup <ID> <密鑰>，再 /gcal_code <網址>（或這次直接輸入三樣）")
                return
            data = got
        if self.http is not None:
            mod.transport = self.http
        c = mod.Client(MemoryStore(data))                 # 換到的新 access token 只放記憶體，不寫回保管箱

        def auth():
            c.token(force=True)
            return f"授權有效（{'唯讀' if c.readonly() else '可以看、加、刪'}；日曆：{c.calendar()}）"
        if not self.check(s, "授權（換 access token）", auth):
            self.add(s, "今天／這 7 天", SKIP, "授權沒過，後面不測")
            return
        today = self.now().date()
        self.check(s, "今天的行程", lambda: f"{len(c.list_events(mod.aware(today), mod.aware(today + timedelta(days=1))))} 個")
        self.check(s, "這 7 天的行程",
                   lambda: f"{len(c.list_events(mod.aware(today), mod.aware(today + timedelta(days=7))))} 個")
        if not self.write:
            return
        if c.readonly():
            self.add(s, "寫入", SKIP, "現在是唯讀授權，不能寫", "要測寫入：/gcal_setup（不加 readonly）重新連一次")
            return
        title = f"{MARK} {self.stamp}"
        day = today + timedelta(days=1)

        def add_and_delete():
            body = {"summary": title, "start": {"date": day.isoformat()},
                    "end": {"date": (day + timedelta(days=1)).isoformat()}}
            made = c.call("POST", c.events_path(), body=body) or {}
            eid = str(made.get("id") or "")
            if not eid:
                raise mod.GoogleError(f"建立了但 Google 沒回編號：請到 Google 日曆手動刪掉明天的「{title}」")
            c.call("DELETE", c.events_path(eid))
            return f"建立「{title}」→ 已刪掉"
        self.plans.append(Plan(s, "寫入（建立後刪掉）",
                               f"在主要日曆（{c.calendar()}）明天加一個整天的「{title}」，再把它刪掉", add_and_delete))

    # ── Apple 提醒事項（CalDAV） ────────────────────────────────────

    def apple(self) -> None:
        s = "apple"
        m, mod = self.module(s)
        auth = dict(self.store(m).load(None, key="auth") or {})
        if not auth.get("username") or not auth.get("password"):
            server = self.plain_input("CalDAV 伺服器網址", mod.DEFAULT_SERVER)
            username = self.plain_input("帳號（iCloud 是 Apple ID 的 email）") if server else ""
            password = self.secret_input("App 專用密碼") if username else ""
            if not password:
                self.missing(s, "先雙擊 Connect-Apple.bat（或 python -m synox connect apple-reminders），或這次直接輸入")
                return
            auth = {"server": server, "username": username, "password": password}
        self.keep_secret(auth.get("password"))
        server = auth.get("server") or mod.DEFAULT_SERVER
        holder: Dict[str, object] = {}

        def login():
            c = holder["c"] = mod.Client(server, auth["username"], auth["password"], session=self.http)
            c.home()
            return f"登入成功（{mod.mask(auth['username'])}，{mod._host(server)}）"
        if not self.check(s, "登入", login):
            self.add(s, "列清單", SKIP, "登入沒過，後面不測")
            return
        c = holder["c"]
        lists: List[dict] = []

        def show_lists():
            lists.extend(c.lists())
            if not lists:
                raise mod.CalDavError(mod.NO_LISTS_ICLOUD if c.icloud else
                                      "這個 CalDAV 帳號裡沒有提醒事項（VTODO）清單。先在 iPhone 或伺服器上建一個。")
            return f"{len(lists)} 個清單：{'、'.join(i['name'] for i in lists)}"
        hint = ("iCloud 升級過的提醒事項不開放 CalDAV：改接別家 CalDAV 帳號，見教學「Apple」那一段" if c.icloud
                else f"看 {GUIDE}「常見錯誤」的 Apple 提醒事項")
        if not self.check(s, "列清單（/applerem_status）", show_lists, hint):
            return
        first = lists[0]
        self.check(s, "讀提醒事項",
                   lambda: f"「{first['name']}」有 {sum(1 for t in c.todos(first['url']) if mod.is_open(t))} 項還沒完成")
        if not self.write:
            return
        title = f"{MARK} {self.stamp}"

        def add_and_complete():
            uid = str(uuid.uuid4()).upper()
            href = first["url"] + uid + ".ics"
            c.put(href, mod.build_todo(title, None, uid=uid), new=True)
            ics, etag = c.get(href)
            c.put(href, mod.mark_completed(ics), etag=etag)
            return f"在「{first['name']}」建立「{title}」→ 已打勾完成（留一筆已完成的，可在 iPhone 刪掉）"
        self.plans.append(Plan(s, "寫入（建立後打勾）",
                               f"在清單「{first['name']}」加一個「{title}」，再把它打勾完成"
                               "（CalDAV 這版沒有刪除，會留一筆「已完成」）", add_and_complete))

    # ── Discord ─────────────────────────────────────────────────────

    def discord(self) -> None:
        s = "discord"
        from synox import discord as dc
        from synox.discord.rest import DiscordChannel
        try:
            specs = dc.specs(self.config)
        except ConfigError as e:
            self.add(s, "config.json", FAIL, str(e), "照 docs/handoff/discord-handoff.md 的範例改")
            return
        bots = []
        for spec in specs:
            try:
                token = dc.resolve_token(spec, self.vault) if self.vault is not None else ""
            except Exception as e:                    # noqa: BLE001 — 保管箱沒有這個 token
                self.add(s, f"bot {spec.name}：token", FAIL, str(e) if "保管箱" in str(e) else type(e).__name__,
                         f"python -m synox discord token{'' if spec.legacy else ' --bot ' + spec.name}")
                continue
            if not token:
                self.add(s, f"bot {spec.name}：token", FAIL, "保管箱裡沒有",
                         f"python -m synox discord token{'' if spec.legacy else ' --bot ' + spec.name}")
                continue
            bots.append((spec.name, spec.surface, self.keep_secret(token)))
        if not specs:
            token = self.secret_input("Discord bot token（config.json 還沒開 Discord，這次只驗 token）")
            if not token:
                self.missing(s, "先 python -m synox discord token，並照交接文件改 config.json")
                return
            bots.append(("（這次輸入的）", "dm", token))
        for name, surface, token in bots:
            api = DiscordChannel(token, None, http=self.http)
            self.discord_bot(s, name, surface, api)
        if specs:
            self.check(s, "擁有者配對", lambda: self.paired(dc),
                       "先關掉正在跑的 SYNOX，再 python -m synox discord pair，15 分鐘內私訊 bot 六位數字")
        if self.write:
            self.add(s, "寫入", SKIP, "Discord 不做寫入測試（不上線、不送訊息）",
                     "上線測試照 docs/handoff/discord-handoff.md 的測試清單做")

    def discord_bot(self, s: str, name: str, surface: str, api) -> None:
        head = f"bot {name}"

        def get(path: str) -> dict:
            got = api.request("GET", path)
            if not got.get("ok"):
                err = got.get("error") or "?"
                if err == "HTTP 401":
                    raise DiscordProblem("Discord 不認這個 token（打錯、或在 Developer Portal 按過 Reset Token）；上線會是 4004")
                raise DiscordProblem(f"Discord 回 {err}")
            return got.get("result") or {}

        def me():
            u = get("/users/@me")
            if not u.get("bot"):
                raise DiscordProblem("這個 token 不是 bot 的（要用 Developer Portal → Bot 頁的 token）")
            return f"{u.get('username') or '?'}（id {u.get('id') or '?'}；{'頻道型' if surface == 'channel' else '私訊型'}）"
        if not self.check(s, f"{head}：身分", me):
            return

        def gateway():
            g = get("/gateway/bot")
            limit = g.get("session_start_limit") or {}
            left = f"；今天還能開 {limit.get('remaining')}/{limit.get('total')} 次連線" if limit else ""
            return f"Gateway 可用（建議分片 {g.get('shards', '?')}{left}）"
        self.check(s, f"{head}：Gateway 資訊", gateway)

        def intent():
            flags = int(get("/applications/@me").get("flags") or 0)
            if not flags & MESSAGE_CONTENT_FLAGS:
                raise DiscordProblem("Message Content intent 看起來沒開；上線會被 4014 拒絕")
            return "Message Content intent 已開"
        self.check(s, f"{head}：Message Content intent", intent,
                   "Developer Portal → 你的 App → Bot → Privileged Gateway Intents → 打開 Message Content Intent → Save")

    def paired(self, dc) -> str:
        from synox.discord.events import DISCORD
        from synox.identity import Identities
        identities = Identities(self.config.path("identities.json"), readonly=True)
        owner = getattr(self.config, "owner_id", None)
        if identities.external(DISCORD, owner) is None:
            raise DiscordProblem("擁有者還沒配對 Discord 帳號（私訊 bot 會被當陌生人）；先跑 python -m synox discord pair")
        problem = dc.owner_problem(self.config, identities)
        if problem:
            raise DiscordProblem(problem)
        return "擁有者已配對"

    # ── 一輪 ─────────────────────────────────────────────────────────

    def run(self, only=SERVICES) -> int:
        for service in only:
            try:
                getattr(self, service)()
            except Skip as e:
                self.add(service, "設定", SKIP, str(e))
            except Exception as e:                    # noqa: BLE001
                self.add(service, "（整段）", FAIL, self.explain(service, e), "請回報這一行")
        if self.write and self.plans:
            self.do_writes()
        self.report()
        return 1 if any(r.result == FAIL for r in self.rows) else 0

    def do_writes(self) -> None:
        self.out("")
        self.out("── 要做的寫入（做完立刻刪掉／完成）──")
        for i, p in enumerate(self.plans, 1):
            self.out(f"{i}. {LABEL[p.service]}：{p.what}")
        try:
            answer = (self.confirm("全部照做請輸入 yes（其他＝都不做）：") or "").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "yes":
            for p in self.plans:
                self.add(p.service, p.item, SKIP, "沒有輸入 yes，沒做")
            return
        for p in self.plans:
            self.check(p.service, p.item, p.run)

    def report(self) -> None:
        mode = "含寫入" if self.write else "唯讀"
        when = self.now().strftime("%Y-%m-%d %H:%M")
        self.out("")
        self.out(f"SYNOX 真機煙霧測試（{mode}）　{when}")
        self.out("| 服務 | 項目 | 結果 | 原因／下一步 |")
        self.out("|---|---|---|---|")
        for r in self.rows:
            tail = r.reason + (f" → {r.hint}" if r.hint and r.result != OK else "")
            self.out(f"| {LABEL[r.service]} | {r.item} | {r.result} | {tail.replace('|', '／').replace(chr(10), ' ')} |")
        count = {k: sum(1 for r in self.rows if r.result == k) for k in (OK, FAIL, SKIP)}
        self.out(f"共 {len(self.rows)} 項：{OK} {count[OK]}　{FAIL} {count[FAIL]}　{SKIP} {count[SKIP]}")
        self.out("")
        self.out("──── 下面這段可以整段貼進「部署測試板」────")
        self.out(self.summary())

    def summary(self) -> str:
        lines = [f"【真機煙霧測試】{self.now().strftime('%Y-%m-%d %H:%M')}（smoke_real.py，{'含寫入' if self.write else '唯讀'}）"]
        for service in SERVICES:
            rows = [r for r in self.rows if r.service == service]
            if not rows:
                continue
            mark = FAIL if any(r.result == FAIL for r in rows) else OK if any(r.result == OK for r in rows) else SKIP
            parts = "、".join(f"{r.item}{r.result}" for r in rows)
            lines.append(f"{mark} {LABEL[service]}：{parts}")
        problems = [r for r in self.rows if r.result == FAIL]
        if problems:
            lines.append("問題：")
            lines += [(f"- {LABEL[r.service]}／{r.item}：{r.reason}" + (f"（下一步：{r.hint}）" if r.hint else ""))
                      .replace("\n", " ") for r in problems]
        return self.redact("\n".join(lines))


class DiscordProblem(Exception):
    """Discord 檢查的人話錯誤。"""


def open_vault_readonly(config):
    """金鑰檔已經在才開保管箱；不在＝回 None（不像 open_vault 那樣幫你產生一把新的）。"""
    from synox.vault import open_vault
    from synox.vault.keyring import key_path
    if not os.path.exists(key_path(config.data_dir)):
        return None
    return open_vault(config)


def parse_only(text: str) -> tuple:
    if not text:
        return SERVICES
    wanted = tuple(x.strip().lower() for x in text.split(",") if x.strip())
    bad = [x for x in wanted if x not in SERVICES]
    if bad:
        raise ValueError(f"不認得 {'、'.join(bad)}；可以用：{','.join(SERVICES)}")
    return wanted


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                             # noqa: BLE001
            pass
    p = argparse.ArgumentParser(prog="smoke_real.py", description="SYNOX 真機煙霧測試（預設只讀）")
    p.add_argument("--config", default="", help="config.json 的位置（預設 SYNOX 資料夾的 config.json）")
    p.add_argument("--only", default="", help="只測這幾個，逗號隔開：" + ",".join(SERVICES))
    p.add_argument("--write", action="store_true", help="另外做一個可還原的小寫入（會先列出來、要你輸入 yes）")
    p.add_argument("--no-ask", action="store_true", help="保管箱沒有的就跳過，不在這裡問")
    p.add_argument("--user", type=int, default=None, help="伺服器版：替哪個 Telegram id 測（預設擁有者）")
    p.add_argument("--notion-query", default="", help="Notion 搜尋用的關鍵字（預設空白＝全部）")
    p.add_argument("--notion-parent", default="", help="--write 時 Notion 測試頁開在哪一頁底下（那一頁的網址）")
    args = p.parse_args(argv)
    try:
        only = parse_only(args.only)
    except ValueError as e:
        print(f"❌ {e}")
        return 2
    try:
        config = SynoxConfig.load(args.config or None, require_token=False)
    except ConfigError as e:
        print(f"❌ {e}")
        return 2
    try:
        vault = open_vault_readonly(config)
    except Exception as e:                            # noqa: BLE001 — KeyringError／VaultError：訊息是給人看的
        print(f"❌ 保管箱打不開：{e}")
        return 2
    if vault is None:
        print("（data 裡還沒有保管箱：憑證都會在這裡問）")
    interactive = not args.no_ask and sys.stdin.isatty()
    smoke = Smoke(config, vault, interactive=interactive, write=args.write, user=args.user,
                  notion_query=args.notion_query, notion_parent=args.notion_parent)
    print(f"開始測：{'、'.join(LABEL[x] for x in only)}（{'含寫入，做之前會問你' if args.write else '只讀'}）…")
    return smoke.run(only)


if __name__ == "__main__":
    sys.exit(main())
