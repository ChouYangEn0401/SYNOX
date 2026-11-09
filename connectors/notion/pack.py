"""🗂 Notion：用 Notion 的 internal integration token 打 Notion 官方 REST API（api.notion.com，Notion-Version 2025-09-03）。

指令（群組 /notion，只有擁有者）：
  /notion <關鍵字>                    搜尋頁面（READ）
  /notion_read <頁面>                 讀一頁：標題、欄位、內文（READ）
  /notion_dbs [關鍵字]                列出分享給 SYNOX 的資料庫（READ）
  /notion_rows <資料庫> [筆數]        資料庫最近改過的幾列（READ）
  /notion_new <上層頁面> <標題> [text=內文]           在一頁底下開新頁（WRITE）
  /notion_row <資料庫> <標題> [props=欄位:值; …]       在資料庫加一列（WRITE）
  /notion_append <頁面> <內文>        在一頁最後面加字（WRITE）
  /notion_set <頁面> <欄位:值; …>     改一頁（資料庫的一列）的欄位（DANGER：AI 要做先出核准卡）
  /notion_token [token]               設定 token（不給 AI；只收私訊）
  /notion_status、/notion_logout      看連線狀態、把 token 拿掉（不給 AI）

「頁面」「資料庫」可以給 Notion 網址、32 字的 id，或標題（用搜尋找最像的那一個）。

token 只存在保管箱：pack.store.of(user)（storage=vault → data/notion.json.enc，密文）；不寫 config.json、不寫 log。
[ROUTE] log 那一行會印使用者打的字，所以 install 時在 root logger 掛一個濾網，把長得像 Notion token 的字遮掉。

只用 requests；不開埠、不讀環境變數、不碰 pack 以外的檔案。測試換掉 new_session（假的 HTTP 傳輸，不連網）。
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from isdtelekit.core.registry import DANGER, WRITE, Field

from synox.packs import kit

API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
TIMEOUT = (5, 20)                  # 連線、讀取（秒）
MAX_REPLY = 3500                   # Telegram 一則最多 4096 字，留一點空間
MAX_BLOCKS = 300                   # 讀一頁最多讀幾個區塊
RICH_TEXT_MAX = 2000               # Notion 一段 rich_text 最多 2000 字

TOKEN_RE = re.compile(r"\b(?:ntn|secret)_[A-Za-z0-9]{20,}")
ID_RE = re.compile(r"([0-9a-fA-F]{8})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{12})")
HELP_SHARE = "（Notion 那邊要先把頁面或資料庫分享給你的 integration：頁面右上角 ⋯ → 連接 → 選它）"


def new_session():
    """HTTP 傳輸。測試把這個換成假的（不連網）。"""
    return requests.Session()


class NotionError(Exception):
    """給人看的錯誤（已經是中文）。"""


# ── 遮掉 log 裡的 token ─────────────────────────────────────────────

class _RedactTokens(logging.Filter):
    """log 訊息裡長得像 Notion token 的字換成 ntn_***（[ROUTE] 那一行會印使用者打的字）。"""

    marker = "synox-notion-redact"

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:
            return True
        if TOKEN_RE.search(text):
            record.msg, record.args = TOKEN_RE.sub("ntn_***", text), ()
        return True


def _install_redaction() -> None:
    root = logging.getLogger()
    if not any(getattr(f, "marker", "") == _RedactTokens.marker for f in root.filters):
        root.addFilter(_RedactTokens())


# ── Notion REST ─────────────────────────────────────────────────────

class Notion:
    """一個 token 的 Notion API。每個方法回 Notion 的 JSON；錯誤丟 NotionError（中文）。"""

    def __init__(self, token: str, session=None):
        self.token = token
        self.http = session if session is not None else new_session()

    def call(self, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}", "Notion-Version": NOTION_VERSION,
                   "Content-Type": "application/json"}
        try:
            r = self.http.request(method, API + path, headers=headers, json=body, params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise NotionError(f"連不到 Notion（{type(e).__name__}），等一下再試。")
        try:
            data = r.json()
        except ValueError:
            data = {}
        if 200 <= r.status_code < 300:
            return data if isinstance(data, dict) else {}
        message = str((data or {}).get("message") or "")[:300] if isinstance(data, dict) else ""
        if r.status_code == 401:
            raise NotionError("Notion 不認這個 token（打錯了，或在 Notion 被撤銷了）。用 /notion_token 重新設定。")
        if r.status_code == 403:
            raise NotionError("這個 integration 沒有這個權限（integration 設定頁的「功能」要勾讀取／插入／更新內容）。")
        if r.status_code == 404:
            raise NotionError("找不到。" + HELP_SHARE)
        if r.status_code == 429:
            wait = r.headers.get("Retry-After", "") if hasattr(r, "headers") else ""
            raise NotionError(f"Notion 說太頻繁了，{wait or '幾'} 秒後再試。")
        if r.status_code == 409:
            raise NotionError("Notion 說同時有別的修改，再試一次。")
        if 400 <= r.status_code < 500:
            raise NotionError(f"Notion 不收這個請求：{message or r.status_code}")
        raise NotionError(f"Notion 那邊出錯了（{r.status_code}），等一下再試。")

    def me(self) -> dict:
        return self.call("GET", "/users/me")

    def search(self, query: str, kind: str = "page", n: int = 10) -> List[dict]:
        body = {"query": query, "page_size": max(1, min(n, 100)),
                "filter": {"property": "object", "value": kind},
                "sort": {"timestamp": "last_edited_time", "direction": "descending"}}
        return list(self.call("POST", "/search", body).get("results") or [])

    def page(self, page_id: str) -> dict:
        return self.call("GET", f"/pages/{page_id}")

    def blocks(self, block_id: str, limit: int = MAX_BLOCKS) -> Tuple[List[dict], bool]:
        out: List[dict] = []
        cursor = None
        while len(out) < limit:
            params = {"page_size": min(100, limit - len(out))}
            if cursor:
                params["start_cursor"] = cursor
            data = self.call("GET", f"/blocks/{block_id}/children", params=params)
            out += list(data.get("results") or [])
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                return out, False
        return out, True

    def append(self, block_id: str, children: List[dict]) -> dict:
        return self.call("PATCH", f"/blocks/{block_id}/children", {"children": children})

    def data_source_of(self, some_id: str) -> dict:
        """資料庫 id 或 data source id → data source 物件（有 properties）。
        2025-09-03 起資料庫底下是 data source；一個資料庫有好幾個 data source 時用第一個。"""
        try:
            db = self.call("GET", f"/databases/{some_id}")
        except NotionError:
            db = None
        if db and db.get("data_sources"):
            return self.call("GET", f"/data_sources/{db['data_sources'][0]['id']}")
        return self.call("GET", f"/data_sources/{some_id}")

    def query(self, ds_id: str, n: int = 10) -> List[dict]:
        body = {"page_size": max(1, min(n, 100)),
                "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}]}
        return list(self.call("POST", f"/data_sources/{ds_id}/query", body).get("results") or [])

    def create(self, parent: dict, properties: dict, children: Optional[List[dict]] = None) -> dict:
        body = {"parent": parent, "properties": properties}
        if children:
            body["children"] = children
        return self.call("POST", "/pages", body)

    def update(self, page_id: str, properties: dict) -> dict:
        return self.call("PATCH", f"/pages/{page_id}", {"properties": properties})


# ── 小工具：id、文字、欄位 ───────────────────────────────────────────

def parse_id(text: str) -> Optional[str]:
    """網址或 id → 有 - 的 uuid；找不到回 None。網址裡有好幾段時取最後一段（?v= 之前）。"""
    text = (text or "").strip().split("?")[0]
    found = ID_RE.findall(text)
    if not found:
        return None
    return "-".join(found[-1]).lower()


def plain(rich: Any) -> str:
    if not isinstance(rich, list):
        return ""
    return "".join(str(t.get("plain_text") or (t.get("text") or {}).get("content") or "") for t in rich
                   if isinstance(t, dict))


def rich(text: str) -> List[dict]:
    text = text or ""
    return [{"type": "text", "text": {"content": text[i:i + RICH_TEXT_MAX]}}
            for i in range(0, len(text), RICH_TEXT_MAX)] or [{"type": "text", "text": {"content": ""}}]


def paragraphs(text: str) -> List[dict]:
    """一段文字 → paragraph 區塊（一行一個；空行跳過；最多 100 個，Notion 一次的上限）。"""
    lines = [ln for ln in (text or "").replace("\r", "").split("\n") if ln.strip()]
    return [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich(ln)}} for ln in lines][:100]


def title_of(obj: dict) -> str:
    """page／data source／database 的標題。"""
    if not isinstance(obj, dict):
        return ""
    if isinstance(obj.get("title"), list):
        return plain(obj["title"]) or "（沒有標題）"
    for prop in (obj.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return plain(prop.get("title")) or "（沒有標題）"
    return "（沒有標題）"


def title_prop(props: dict) -> str:
    for name, prop in (props or {}).items():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return name
    return "title"


def show_value(prop: dict) -> str:
    """一個欄位的值 → 給人看的字。"""
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return plain(v)
    if t in ("select", "status"):
        return (v or {}).get("name", "") if isinstance(v, dict) else ""
    if t == "multi_select":
        return "、".join(x.get("name", "") for x in v or [])
    if t == "date":
        if not v:
            return ""
        return v.get("start", "") + (f" → {v['end']}" if v.get("end") else "")
    if t == "checkbox":
        return "☑" if v else "☐"
    if t == "people":
        return "、".join(p.get("name") or "?" for p in v or [])
    if t == "relation":
        return f"{len(v or [])} 個關聯"
    if t == "formula" and isinstance(v, dict):
        return str(v.get(v.get("type")) if v.get(v.get("type")) is not None else "")
    if t == "unique_id" and isinstance(v, dict):
        return f"{v.get('prefix') or ''}{'-' if v.get('prefix') else ''}{v.get('number', '')}"
    if t in ("number", "url", "email", "phone_number", "created_time", "last_edited_time"):
        return "" if v is None else str(v)
    return ""


def show_block(b: dict) -> Optional[str]:
    t = b.get("type")
    v = b.get(t) or {}
    text = plain(v.get("rich_text")) if isinstance(v, dict) else ""
    more = " ▸" if b.get("has_children") and t not in ("child_page", "child_database") else ""
    if t == "paragraph":
        return text + more
    if t in ("heading_1", "heading_2", "heading_3"):
        return "#" * int(t[-1]) + " " + text + more
    if t == "bulleted_list_item":
        return "• " + text + more
    if t == "numbered_list_item":
        return "1. " + text + more
    if t == "to_do":
        return ("☑ " if v.get("checked") else "☐ ") + text + more
    if t in ("quote", "callout"):
        return "> " + text + more
    if t == "toggle":
        return "▸ " + text
    if t == "code":
        return "```\n" + text + "\n```"
    if t == "divider":
        return "———"
    if t == "child_page":
        return "📄 " + (v.get("title") or "")
    if t == "child_database":
        return "🗂 " + (v.get("title") or "")
    if t in ("bookmark", "embed", "link_preview"):
        return "🔗 " + (v.get("url") or "")
    if t in ("image", "file", "pdf", "video", "audio"):
        return f"[{ {'image': '圖片', 'file': '檔案', 'pdf': 'PDF', 'video': '影片', 'audio': '聲音'}[t] }]"
    if t == "table_row":
        return " | ".join(plain(c) for c in v.get("cells") or [])
    return None


def clip(text: str, limit: int = MAX_REPLY) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…（太長了，後面省略；完整的請開網址）"


TRUE = ("true", "yes", "y", "1", "是", "對", "有", "✅", "☑", "v", "x")
FALSE = ("false", "no", "n", "0", "否", "不", "沒有", "☐", "")


def parse_date(text: str) -> str:
    t = text.strip()
    today = datetime.date.today()
    words = {"今天": 0, "今日": 0, "明天": 1, "後天": 2, "昨天": -1}
    if t in words:
        return (today + datetime.timedelta(days=words[t])).isoformat()
    t = t.replace("/", "-")
    for fmt, has_time in (("%Y-%m-%d", False), ("%Y-%m-%d %H:%M", True), ("%Y-%m-%dT%H:%M", True)):
        try:
            d = datetime.datetime.strptime(t, fmt)
        except ValueError:
            continue
        return d.strftime("%Y-%m-%dT%H:%M:00") if has_time else d.date().isoformat()
    raise NotionError(f"日期看不懂：{text}（寫成 2026-11-12、2026-11-12 14:00、今天、明天）")


def prop_value(kind: str, name: str, text: str) -> dict:
    """使用者寫的字 → Notion 的欄位值（照欄位的型別）。"""
    text = text.strip()
    if kind == "title":
        return {"title": rich(text)}
    if kind == "rich_text":
        return {"rich_text": rich(text)}
    if kind == "number":
        if not text:
            return {"number": None}
        try:
            return {"number": float(text.replace(",", ""))}
        except ValueError:
            raise NotionError(f"「{name}」要是數字（現在是 {text}）")
    if kind in ("select", "status"):
        return {kind: {"name": text} if text else None}
    if kind == "multi_select":
        return {"multi_select": [{"name": x.strip()} for x in re.split(r"[,，、]", text) if x.strip()]}
    if kind == "date":
        return {"date": {"start": parse_date(text)} if text else None}
    if kind == "checkbox":
        low = text.lower()
        if low in TRUE:
            return {"checkbox": True}
        if low in FALSE:
            return {"checkbox": False}
        raise NotionError(f"「{name}」是勾選框，寫「是」或「否」")
    if kind in ("url", "email", "phone_number"):
        return {kind: text or None}
    raise NotionError(f"「{name}」這種欄位（{kind}）還不能從這裡改，請在 Notion 裡改。")


def parse_props(text: str) -> List[Tuple[str, str]]:
    """「狀態:進行中; 日期:明天」→ [(狀態, 進行中), (日期, 明天)]。分隔：; ；或換行；名字和值用 : 或 ：。"""
    out = []
    for part in re.split(r"[;；\n]", text or ""):
        if not part.strip():
            continue
        m = re.match(r"^\s*([^:：]+?)\s*[:：]\s*(.*)$", part)
        if not m:
            raise NotionError(f"「{part.strip()}」看不懂：要寫成 欄位:值（好幾個用 ; 隔開）")
        out.append((m.group(1), m.group(2)))
    return out


def build_props(schema: dict, pairs: List[Tuple[str, str]]) -> dict:
    """schema：Notion 的 properties（每個有 type）。名字不分大小寫。"""
    by_lower = {k.lower(): k for k in schema}
    out = {}
    for name, value in pairs:
        real = schema and (name if name in schema else by_lower.get(name.lower()))
        if not real:
            raise NotionError(f"沒有叫「{name}」的欄位。有的欄位：{'、'.join(schema) or '（沒有）'}")
        out[real] = prop_value(schema[real].get("type", ""), real, value)
    return out


def line_of(obj: dict, n: Optional[int] = None) -> str:
    head = f"{n}. " if n is not None else ""
    return f"{head}{title_of(obj)}\n   {obj.get('url') or obj.get('id', '')}"


# ── install ─────────────────────────────────────────────────────────

def install(app, pack):
    g = pack.group
    _install_redaction()

    def stored(user) -> dict:
        data = pack.store.of(user).load({}) or {}
        return data if isinstance(data, dict) else {}

    def client(user) -> Notion:
        token = stored(user).get("token")
        if not token:
            raise NotionError("還沒設定 Notion。先在私訊打 /notion_token，照說明貼上 integration token。")
        return Notion(token)

    def run(api, chat_id, fn):
        """fn() 回要送的字；NotionError 變成一句中文。"""
        try:
            text = fn()
        except NotionError as e:
            text = f"❌ {e}"
        api.send_message(chat_id, clip(text))

    def find(nc: Notion, ref: str, kind: str = "page") -> dict:
        """網址／id／標題 → 物件。kind：page｜data_source。"""
        ref = (ref or "").strip()
        some_id = parse_id(ref)
        if some_id:
            return nc.page(some_id) if kind == "page" else nc.data_source_of(some_id)
        results = nc.search(ref, kind, n=10)
        if not results:
            what = "頁面" if kind == "page" else "資料庫"
            raise NotionError(f"找不到叫「{ref}」的{what}。" + HELP_SHARE)
        exact = [r for r in results if title_of(r).strip().lower() == ref.lower()]
        return exact[0] if exact else results[0]

    # ── 讀 ──

    def search(api, chat_id, user, values):
        def go():
            nc = client(user)
            results = nc.search(values["query"], "page", n=int(values.get("n") or 10))
            if not results:
                return f"🔎 找不到「{values['query']}」。" + HELP_SHARE
            return "\n".join([f"🔎 找到 {len(results)} 頁："] + [line_of(r, i) for i, r in enumerate(results, 1)])
        run(api, chat_id, go)

    def read(api, chat_id, user, values):
        def go():
            nc = client(user)
            page = find(nc, values["page"])
            lines = [f"📄 {title_of(page)}", page.get("url") or page.get("id", "")]
            for name, prop in (page.get("properties") or {}).items():
                if isinstance(prop, dict) and prop.get("type") != "title":
                    shown = show_value(prop)
                    if shown:
                        lines.append(f"・{name}：{shown}")
            blocks, more = nc.blocks(page["id"])
            body = [s for s in (show_block(b) for b in blocks) if s is not None]
            if body:
                lines.append("")
                lines += body
            elif not blocks:
                lines.append("（內文是空的）")
            if more:
                lines.append(f"…（只讀了前 {len(blocks)} 段）")
            return "\n".join(lines)
        run(api, chat_id, go)

    def dbs(api, chat_id, user, values):
        def go():
            results = client(user).search(values.get("query", ""), "data_source", n=20)
            if not results:
                return "🗂 沒有看到資料庫。" + HELP_SHARE
            return "\n".join([f"🗂 {len(results)} 個資料庫："] + [line_of(r, i) for i, r in enumerate(results, 1)])
        run(api, chat_id, go)

    def rows(api, chat_id, user, values):
        def go():
            nc = client(user)
            ref, n = values["database"], values.get("n")
            tail = re.match(r"^(.*\S)\s+(\d{1,3})$", ref)
            if tail and not n:                    # 「/notion_rows 任務 5」：最後一個位置欄位吃掉了筆數
                ref, n = tail.group(1), tail.group(2)
            ds = find(nc, ref, "data_source")
            items = nc.query(ds["id"], n=int(n or 10))
            if not items:
                return f"🗂 {title_of(ds)} 還沒有任何一列。"
            out = [f"🗂 {title_of(ds)}：最近改過的 {len(items)} 列"]
            for i, row in enumerate(items, 1):
                extra = [f"{k}：{show_value(p)}" for k, p in (row.get("properties") or {}).items()
                         if isinstance(p, dict) and p.get("type") != "title" and show_value(p)][:4]
                out.append(line_of(row, i) + (f"\n   {'；'.join(extra)}" if extra else ""))
            return "\n".join(out)
        run(api, chat_id, go)

    # ── 寫 ──

    def new_page(api, chat_id, user, values):
        def go():
            nc = client(user)
            parent = find(nc, values["parent"])
            page = nc.create({"type": "page_id", "page_id": parent["id"]},
                             {"title": {"title": rich(values["title"])}}, paragraphs(values.get("text", "")))
            return f"✅ 在「{title_of(parent)}」底下開了新頁：{values['title']}\n{page.get('url', '')}"
        run(api, chat_id, go)

    def new_row(api, chat_id, user, values):
        def go():
            nc = client(user)
            ds = find(nc, values["database"], "data_source")
            schema = ds.get("properties") or {}
            props = build_props(schema, parse_props(values.get("props", "")))
            props[title_prop(schema)] = {"title": rich(values["title"])}
            page = nc.create({"type": "data_source_id", "data_source_id": ds["id"]}, props,
                             paragraphs(values.get("text", "")))
            return f"✅ 在「{title_of(ds)}」加了一列：{values['title']}\n{page.get('url', '')}"
        run(api, chat_id, go)

    def append(api, chat_id, user, values):
        def go():
            nc = client(user)
            page = find(nc, values["page"])
            blocks = paragraphs(values["text"])
            if not blocks:
                return "❌ 沒有要加的字。"
            nc.append(page["id"], blocks)
            return f"✅ 在「{title_of(page)}」最後面加了 {len(blocks)} 段。\n{page.get('url', '')}"
        run(api, chat_id, go)

    def set_props(api, chat_id, user, values):
        def go():
            nc = client(user)
            page = find(nc, values["page"])
            pairs = parse_props(values["props"])
            if not pairs:
                return "❌ 要寫要改什麼：欄位:值（好幾個用 ; 隔開）"
            props = build_props(page.get("properties") or {}, pairs)
            nc.update(page["id"], props)
            changed = "、".join(f"{k}＝{v}" for k, v in pairs)
            return f"✅ 改好了「{title_of(page)}」：{changed}\n{page.get('url', '')}"
        run(api, chat_id, go)

    # ── token（不給 AI、只收私訊） ──

    def save_token(api, chat_id, user, token: str) -> None:
        token = token.strip()
        if not TOKEN_RE.fullmatch(token):
            api.send_message(chat_id, "❌ 這看起來不是 Notion 的 integration token（應該是 ntn_ 開頭的一長串）。")
            return
        try:
            me = Notion(token).me()
        except NotionError as e:
            api.send_message(chat_id, f"❌ 沒有存：{e}")
            return
        workspace = ((me.get("bot") or {}).get("workspace_name") or "") if isinstance(me, dict) else ""
        pack.store.of(user).save({"token": token, "bot": me.get("name") or "", "workspace": workspace})
        api.send_message(chat_id, f"✅ 接上 Notion 了（integration：{me.get('name') or '?'}"
                                  f"{'，工作區：' + workspace if workspace else ''}）。token 已加密存在這台電腦。\n"
                                  "⚠️ 請把剛剛貼 token 的那則訊息刪掉（長按 → 刪除 → 也替對方刪除）。\n"
                                  "接著在 Notion 把要給 SYNOX 用的頁面／資料庫分享給這個 integration，然後試試 /notion 關鍵字。")

    def token_cmd(api, chat_id, user, args):
        if args:
            save_token(api, chat_id, user, " ".join(args))
            return

        def answer(api_, chat_id_, user_, text):
            app.conversations.end(chat_id_)
            if text.strip().startswith("/"):
                api_.send_message(chat_id_, "好，不設定了。")
                return
            save_token(api_, chat_id_, user_, text)

        app.conversations.supersede(api, chat_id)
        app.conversations.start(chat_id, user.tg_id, "notion_token", answer, idle_seconds=300, label="/notion_token")
        api.send_message(chat_id, "🔑 把 Notion 的 integration token 貼上來（ntn_ 開頭；只收下一則訊息，5 分鐘內）。\n"
                                  "取得方式：notion.so/profile/integrations → 新增 integration → 複製「Internal Integration Secret」。\n"
                                  "打 /cancel 取消。")

    def status(api, chat_id, user, args):
        data = stored(user)
        if not data.get("token"):
            api.send_message(chat_id, "🗂 Notion 還沒設定。私訊打 /notion_token 開始。")
            return
        try:
            me = Notion(data["token"]).me()
            ok = f"✅ 連得上（integration：{me.get('name') or '?'}）"
        except NotionError as e:
            ok = f"❌ {e}"
        api.send_message(chat_id, f"🗂 Notion：{ok}\ntoken 存在保管箱（密文），結尾 …{data['token'][-4:]}")

    def logout(api, chat_id, user, args):
        had = bool(stored(user).get("token"))
        pack.store.of(user).save({})
        api.send_message(chat_id, ("🗂 token 拿掉了。" if had else "🗂 本來就沒有設定 token。")
                         + "要徹底停用，也到 notion.so/profile/integrations 把那個 integration 刪掉。")

    # ── 掛指令 ──

    n_field = Field("n", "筆數", check=kit.positive_int)
    kit.command(g, "search", search, "搜尋頁面", default=True,
                fields=[Field("query", "關鍵字", required=True), n_field], positional=1)
    kit.command(g, "read", read, "讀一頁（標題、欄位、內文）",
                fields=[Field("page", "頁面（網址、id 或標題）", required=True)])
    kit.command(g, "dbs", dbs, "列出分享給 SYNOX 的資料庫", fields=[Field("query", "關鍵字")])
    kit.command(g, "rows", rows, "資料庫最近改過的幾列",
                fields=[Field("database", "資料庫（網址、id 或名字）", required=True), n_field], positional=1)
    kit.command(g, "new", new_page, "在一頁底下開新頁", effect=WRITE, positional=2, fields=[
        Field("parent", "上層頁面（網址、id 或標題）", required=True),
        Field("title", "標題", required=True),
        Field("text", "內文")])
    kit.command(g, "row", new_row, "在資料庫加一列", effect=WRITE, positional=2, fields=[
        Field("database", "資料庫（網址、id 或名字）", required=True),
        Field("title", "標題", required=True),
        Field("props", "其他欄位（欄位:值; 欄位:值）"),
        Field("text", "內文")])
    kit.command(g, "append", append, "在一頁最後面加字", effect=WRITE, fields=[
        Field("page", "頁面（網址、id 或標題）", required=True),
        Field("text", "要加的字", required=True)])
    kit.command(g, "set", set_props, "改一頁的欄位（欄位:值; …）", effect=DANGER, fields=[
        Field("page", "頁面（網址、id 或標題）", required=True),
        Field("props", "欄位:值; 欄位:值", required=True)])
    g.leaf("token", token_cmd, "設定 Notion token（私訊）", usage="[token]", effect=WRITE, ai=False,
           private_only=True, interactive=True)
    g.leaf("status", status, "看 Notion 有沒有接上", ai=False)
    g.leaf("logout", logout, "把 Notion token 拿掉", effect=WRITE, ai=False)
