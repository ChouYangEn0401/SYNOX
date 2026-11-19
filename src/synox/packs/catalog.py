"""
官方工具庫（SYNOX_Libs）的線上清單：網頁設定頁「功能與安裝」→「工具庫（官方）」用。

- **只在使用者按按鈕時連網**（「載入工具清單」「安裝」），沒有背景抓取；目的地寫死在這裡（OFFICIAL_INDEX_URL、DOWNLOAD_PREFIX），
  不從網址列參數、送來的資料或外面的頁面決定（ADR 0022 R8、決定 25）。
- 清單＝SYNOX_Libs 發佈頁的 `index.json`（scripts/build.py 產生：name、title、summary、version、stage、access、capabilities、
  file、sha256、size）。格式不對的條目直接不列（檔名一定要是 `<name>-<version>.synoxpack`、sha256 要是 64 個十六進位字）。
- 轉址只跟到 GitHub 自己的主機（REDIRECT_HOSTS，https、預設埠、沒有帳密）；github.com 上也只限這個工具庫的發佈路徑。
  實測（2026-11-13）：`github.com/…/releases/download/<tag>/<檔>` 302 到 `objects.githubusercontent.com` 或
  `release-assets.githubusercontent.com`；`releases/latest/download/…` 先 302 到該版的 `releases/download/<tag>/…`。
- 下載的檔：大小上限＝admin.MAX_UPLOAD（5 MB），大小與 sha256 都要跟清單一樣，不一樣＝不裝。
  通過的位元組交給 `admin.stage`（跟上傳同一條路：第 1、2 關 → 報告 → 人按確認 → 第 3 關）；這裡不碰 packs/。
- 還沒有簽章（ADR 0022 決定 26 未實作）：信任的是「HTTPS ＋ GitHub 這個 repo 的發佈頁」。

測試一律換 opener（`opener(url, timeout, limit) -> (status, Location, body)`），不連網。
給人看的字集中在 TEXT（白話；主流程不出現雜湊、index.json 這類詞）。

SYNOX 衣櫃（外觀包）：跟工具在同一份清單裡，條目寫 `"kind": "theme"`（`category`「衣櫃／外觀」、`collection` "wardrobe"）。
- 「功能與安裝」的工具清單（cards）**不列**外觀包；「設定 → 🎨 外觀 → 衣櫃」（wardrobe_cards）只列外觀包。
- 安裝走同一條路（/api/packs/library/install：下載 → 大小、sha256 對清單 → admin.stage → 報告 → 人按確認）。
- 卡片的小預覽：清單有 `swatches`（最多 6 個 #hex 顏色）就畫色條，沒有就用 `series`（一個字母）當字母方塊。
  清單裡不會有圖片網址（也不收）：預覽一律是 SYNOX 自己畫的。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from synox.packs.admin import MAX_UPLOAD
from synox.packs.manifest import STAGES, stage_label, stage_text
from synox.wizard.tools import MAX_INDEX_BYTES

REPO_PATH = "/ChouYangEn0401/SYNOX_Libs/releases/"
# 工具庫目前唯一的發佈 v0.2.0 標成「預先發行」，latest/download 會 404，所以先釘在這一版；
# 之後有正式發佈（不是 pre-release）就改回 releases/latest/download/index.json。
OFFICIAL_INDEX_URL = "https://github.com/ChouYangEn0401/SYNOX_Libs/releases/download/v0.2.0/index.json"
DOWNLOAD_PREFIX = "https://github.com" + REPO_PATH + "download/"
RELEASES_PAGE = "https://github.com/ChouYangEn0401/SYNOX_Libs/releases"
OVERVIEW_URL = "https://claude.ai/artifact/M8zGBGy9kRtGTjNS24wBVL"          # 工具庫介紹（線上）
WARDROBE_URL = "https://claude.ai/artifact/USzGNERZ2477E7XzPaPCsR"          # SYNOX 衣櫃的公開頁（完整預覽；只給人點的連結）
ASSET_HOSTS = ("objects.githubusercontent.com", "release-assets.githubusercontent.com")
REDIRECT_HOSTS = ("github.com",) + ASSET_HOSTS

MAX_INDEX = MAX_INDEX_BYTES                 # 2 MB（跟本機工具庫的目錄同一個上限）
MAX_PACK = MAX_UPLOAD                       # 5 MB（admin.stage 也擋這個）
MAX_REDIRECTS = 5
TIMEOUT = 20                                # 每次連線／讀取
TOTAL_TIMEOUT = 60                          # 一個檔從頭到尾

Opener = Callable[[str, float, int], Tuple[int, Optional[str], bytes]]

TEXT = {
    "offline": "連不到工具庫，可能是現在沒有網路。先看看網路，再按一次。也可以按下面的「⬇ 下載」，或到下載頁自己下載。",
    "not_found": "工具庫裡找不到這個檔案，可能還沒放上去。可以到下載頁看看，或按「⬇ 下載」。",
    "bad_status": "工具庫現在怪怪的。等一下再按一次，或到下載頁自己下載。",
    "moved": "下載被帶到不認識的地方，為了安全我停下來了。請到下載頁自己下載。",
    "too_big": f"檔案太大（最多 {MAX_PACK // (1024 * 1024)} MB），沒有下載。",
    "broken": "工具庫的清單我看不懂，所以先不顯示。可以到下載頁自己下載。",
    "mismatch": "下載的檔案跟清單上寫的不一樣，可能沒下載完整，或被人換過。為了安全沒有裝。"
                "請再按一次。還是一樣的話，到下載頁自己下載。",
    "not_listed": "下載的檔案裡面不是清單上寫的那個工具，為了安全沒有裝。",
    "unknown": "工具庫裡沒有這個工具。清單可能更新了，按「重新看一次」。",
    "simulated": "只用假資料測過",
    "simulated_hint": "還沒有真的連上去長時間用過，只用假資料測過",
    "offline_ok": "不用上網",
    "offline_ok_hint": "這個工具不會上網，資料存在這台電腦",
    "owner": "👤 單人用",
    "owner_hint": "只有安裝 SYNOX 的那個人能用；伺服器版的其他人看不到",
    "member": "👥 伺服器版也能用",
    "member_hint": "伺服器版裡每個人都能用，各自一份資料、互相看不到",
    "wardrobe_empty": "衣櫃裡還沒有東西。可以先到衣櫃網頁看看。",
}
WARDROBE_TITLE = "SYNOX 衣櫃"

# 每個官方工具的線上說明頁（工具庫的網站）
HELP_PAGES = {
    "notes": "https://claude.ai/artifact/NpYbd3FtMAkXmASXc1pJzh",
    "todo": "https://claude.ai/artifact/JuKURoMhZY58fWyR4j3961",
    "money": "https://claude.ai/artifact/6kA9jSkwVFPPBthsCjmz6d",
    "calendar": "https://claude.ai/artifact/Fm6dXH5oiua8zPY3U5RYQ5",
    "bullet": "https://claude.ai/artifact/BTdPArDtbddRk4ijNqExZ3",
    "notion": "https://claude.ai/artifact/B36np3VigMinvyFuyz74dJ",
    "todoist": "https://claude.ai/artifact/D3zgGcZ9h1LRrDLu2QD5Mw",
    "google-calendar": "https://claude.ai/artifact/NyhRhPrRL1n9NMMbMEv3mx",
    "apple-reminders": "https://claude.ai/artifact/Jm4tdCTZdaQ1mc1waTatYp",
    "diary": "https://claude.ai/artifact/HRobvC114kdVY9CtkocFMt",
    "google-sheets": "https://claude.ai/artifact/H74Xn3PdwzCsseG9dEkq1r",
}

# 清單裡沒有的時候用的：(emoji, 中文名, 一句話, 例子)；跟工具庫網站的卡片同一份文字
TOOLS: Dict[str, Tuple[str, str, str, str]] = {
    "notes": ("📒", "隨手記", "記一筆、找、刪", "/note 買牛奶"),
    "todo": ("✅", "待辦", "重要度、專案、到期日、打勾完成", "/todo !! 繳電費 明天"),
    "money": ("💰", "記帳", "支出、收入、轉帳、預算", "/money 120 午餐"),
    "calendar": ("📅", "行事曆", "存在這台電腦的行程，可匯出 .ics", "/cal 明天 14:00 看牙醫"),
    "bullet": ("•", "子彈筆記", "快速記錄、今天、月誌、搬到今天", "/bj • 買牛奶"),
    "notion": ("🗂", "Notion", "搜尋、讀頁面、加一列、改欄位", "/notion 會議"),
    "todoist": ("✅", "Todoist", "看、加、完成、改期 Todoist 的待辦", "/todoist !! 繳電費 明天"),
    "google-calendar": ("📅", "Google 日曆", "看今天／這週、加行程、刪行程", "/gcal 明天 14:00 看牙醫"),
    "apple-reminders": ("🍎", "Apple 提醒事項", "CalDAV 提醒事項（升級過的 iCloud 讀不到）", "/applerem_add 買牛奶"),
}
SIMULATED_ONLY = frozenset({"notion", "todoist", "google-calendar", "apple-reminders"})   # 接外面服務、只用模擬測過

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
VERSION_RE = re.compile(r"^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
SERIES_RE = re.compile(r"^[A-Za-z0-9]$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")


class CatalogError(Exception):
    """給人看的錯誤。offline＝連不上（網頁回 502，附發佈頁連結）；其他＝拒絕（400）。"""

    def __init__(self, message: str, offline: bool = False):
        super().__init__(message)
        self.offline = offline


@dataclass
class Tool:
    name: str
    title: str
    summary: str
    version: str
    stage: str
    access: str
    file: str
    sha256: str
    tag: str
    size: Optional[int] = None
    capabilities: Optional[List[str]] = None
    line: str = ""
    kind: str = ""                          # "theme"＝外觀包（衣櫃）；其他＝工具
    series: str = ""                        # 衣櫃：系列字母（卡片的字母方塊）
    swatches: List[str] = field(default_factory=list)   # 衣櫃：小預覽的顏色（#hex，最多 6 個）
    # 清單上的標記警告（工具庫照 pack.json 的 warnings 抄過來，ADR 0041；同一套檢查）。真正擋人的是安裝報告的那一份
    warnings: List[dict] = field(default_factory=list)

    @property
    def is_theme(self) -> bool:
        return self.kind == "theme"

    @property
    def download_url(self) -> str:
        return f"{DOWNLOAD_PREFIX}{self.tag}/{self.file}"

    @property
    def help_url(self) -> str:
        return HELP_PAGES.get(self.name, OVERVIEW_URL)


@dataclass
class Library:
    version: str
    tag: str
    tools: List[Tool] = field(default_factory=list)
    collections: Dict[str, dict] = field(default_factory=dict)   # 只拿來參考（衣櫃的標題、一句話）

    @property
    def themes(self) -> List[Tool]:
        return [t for t in self.tools if t.is_theme]


# ── 連網（只有這裡）──────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不自己跟轉址：每一跳都回到 get() 檢查主機。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def default_opener(url: str, timeout: float, limit: int) -> Tuple[int, Optional[str], bytes]:
    """真的連網：(狀態碼, Location, 內容)。內容最多讀 limit+1 個位元組（多讀一個才知道超過）。"""
    request = urllib.request.Request(url, headers={"User-Agent": "SYNOX", "Accept": "application/octet-stream"})
    try:
        response = _OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as e:                  # 3xx（沒跟）、4xx、5xx
        try:
            return e.code, e.headers.get("Location") if e.headers else None, b""
        finally:
            e.close()
    with response:
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > limit:
            return response.status, None, b"\0" * (limit + 1)
        deadline = time.monotonic() + TOTAL_TIMEOUT
        chunks, size = [], 0
        while size <= limit:
            if time.monotonic() > deadline:
                raise TimeoutError("download took too long")
            chunk = response.read(min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return response.status, None, b"".join(chunks)


def _allowed(url: str, first: bool) -> bool:
    """https、預設埠、沒有帳密；github.com 只限這個工具庫的發佈路徑；第一跳一定是 github.com。"""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return False
    host = (parts.hostname or "").lower()
    if host == "github.com":
        return parts.path.startswith(REPO_PATH) and ".." not in parts.path
    return not first and host in ASSET_HOSTS


def get(url: str, limit: int, opener: Optional[Opener] = None) -> bytes:
    """抓一個工具庫的檔（跟 GitHub 自己的轉址）→ 內容；任何不對丟 CatalogError。"""
    opener = opener or default_opener
    if not _allowed(url, first=True):
        raise CatalogError(TEXT["moved"])
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            status, location, body = opener(current, TIMEOUT, limit)
        except CatalogError:
            raise
        except (urllib.error.URLError, OSError, HTTPException, ValueError):
            raise CatalogError(TEXT["offline"], offline=True)
        if status in (301, 302, 303, 307, 308):
            target = urljoin(current, location or "")
            if not location or not _allowed(target, first=False):
                raise CatalogError(TEXT["moved"])
            current = target
            continue
        if status == 404:
            raise CatalogError(TEXT["not_found"], offline=True)
        if status != 200:
            raise CatalogError(TEXT["bad_status"], offline=True)
        if len(body) > limit:
            raise CatalogError(TEXT["too_big"])
        return body
    raise CatalogError(TEXT["moved"])


# ── 清單 ─────────────────────────────────────────────────────────────

def _text(value, limit: int) -> str:
    return _CONTROL_RE.sub("", value).strip()[:limit] if isinstance(value, str) else ""


def _tool(item, tag: str) -> Optional[Tool]:
    """一筆清單 → Tool；不安全或對不起來的回 None（不列）。"""
    if not isinstance(item, dict):
        return None
    name, version, file = item.get("name"), item.get("version"), item.get("file")
    sha, size = item.get("sha256"), item.get("size")
    if not (isinstance(name, str) and NAME_RE.match(name) and isinstance(version, str) and VERSION_RE.match(version)):
        return None
    if file != f"{name}-{version}.synoxpack" or not (isinstance(sha, str) and SHA_RE.match(sha)):
        return None
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_PACK):
        return None
    caps = item.get("capabilities")
    stage = item.get("stage") if item.get("stage") in STAGES else "alpha"
    theme = item.get("kind") == "theme"
    swatches = item.get("swatches") if theme and isinstance(item.get("swatches"), list) else []
    series = item.get("series") if theme and isinstance(item.get("series"), str) else ""
    from synox.packs import packwarn
    warned, _bad = packwarn.parse(item.get("warnings"), present="warnings" in item)
    return Tool(kind="theme" if theme else "", warnings=warned,
                series=series.upper() if SERIES_RE.match(series) else "",
                swatches=[c.lower() for c in swatches if isinstance(c, str) and HEX_RE.match(c)][:6],
                name=name, title=_text(item.get("title"), 60), summary=_text(item.get("summary"), 300),
                version=version, stage=stage, access=item.get("access") if item.get("access") in
                ("owner", "member", "everyone") else "owner", file=file, sha256=sha.lower(), tag=tag, size=size,
                capabilities=[c for c in caps if isinstance(c, str)] if isinstance(caps, list) else None,
                line=_text(item.get("line"), 80))


def parse_index(blob: bytes) -> Library:
    try:
        raw = json.loads(blob.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise CatalogError(TEXT["broken"])
    if not isinstance(raw, dict) or not isinstance(raw.get("packs"), list):
        raise CatalogError(TEXT["broken"])
    version = raw.get("library_version")
    if not (isinstance(version, str) and VERSION_RE.match(version)):
        raise CatalogError(TEXT["broken"])
    tag = "v" + version
    tools, seen = [], set()
    for item in raw["packs"]:
        tool = _tool(item, tag)
        if tool is not None and tool.name not in seen:
            seen.add(tool.name)
            tools.append(tool)
    collections = {}
    if isinstance(raw.get("collections"), dict):
        for key, info in raw["collections"].items():
            if isinstance(key, str) and NAME_RE.match(key) and isinstance(info, dict):
                collections[key] = {"title": _text(info.get("title"), 40), "summary": _text(info.get("summary"), 200)}
    return Library(version=version, tag=tag, tools=tools, collections=collections)


def fetch_library(opener: Optional[Opener] = None) -> Library:
    """按「載入工具清單」：抓官方清單（寫死的網址）。"""
    return parse_index(get(OFFICIAL_INDEX_URL, MAX_INDEX, opener))


def download(tool: Tool, opener: Optional[Opener] = None) -> bytes:
    """按「安裝」：從發佈頁抓那一個檔，大小、sha256 都要跟清單一樣。"""
    if not tool.download_url.startswith(DOWNLOAD_PREFIX):
        raise CatalogError(TEXT["moved"])
    blob = get(tool.download_url, MAX_PACK, opener)
    if tool.size is not None and len(blob) != tool.size:
        raise CatalogError(TEXT["mismatch"])
    if hashlib.sha256(blob).hexdigest() != tool.sha256:
        raise CatalogError(TEXT["mismatch"])
    return blob


# ── 給網頁的卡片 ─────────────────────────────────────────────────────

def _split_title(title: str) -> Tuple[str, str]:
    """「📒 隨手記」→ ("📒", "隨手記")；開頭不是符號就沒有 emoji。"""
    first, _, rest = title.partition(" ")
    if rest.strip() and first and not any(ch.isalnum() for ch in first):
        return first, rest.strip()
    return "", title


def _newer(catalog_version: str, installed: str) -> bool:
    from synox.packs.upgrade import UPGRADE, compare_versions
    return bool(installed) and compare_versions(installed, catalog_version)[0] == UPGRADE


def card(tool: Tool, installed: str = "") -> dict:
    """網頁的一張工具卡（字都是純文字，網頁用 textContent 放）。"""
    emoji, title = _split_title(tool.title)
    static = TOOLS.get(tool.name)
    emoji = emoji or (static[0] if static else "🧩")
    title = title or (static[1] if static else tool.name)
    line = tool.line or (static[2] if static else tool.summary)
    # 作者標的警告（ADR 0041）排最前面、紅色；hint 是建議怎麼做
    badges = [{"text": f"⚠️ {w['text']}", "tone": "bad", "hint": w.get("advice") or ""} for w in tool.warnings]
    badges.append({"text": stage_label(tool.stage), "tone": "warn", "hint": stage_text(tool.stage)})
    if tool.name in SIMULATED_ONLY:
        badges.append({"text": TEXT["simulated"], "tone": "", "hint": TEXT["simulated_hint"]})
    elif tool.capabilities is not None and "network" not in tool.capabilities:
        badges.append({"text": TEXT["offline_ok"], "tone": "ok", "hint": TEXT["offline_ok_hint"]})
    who = "owner" if tool.access == "owner" else "member"
    badges.append({"text": TEXT[who], "tone": "", "hint": TEXT[who + "_hint"]})
    online = tool.capabilities is not None and "network" in tool.capabilities
    return {"name": tool.name, "emoji": emoji, "title": title, "line": line, "summary": tool.summary,
            "example": static[3] if static else "", "version": tool.version, "badges": badges,
            "group": "online" if online or tool.name in SIMULATED_ONLY else "local",
            "help_url": tool.help_url, "download_url": tool.download_url,
            "installed": installed or "", "newer": _newer(tool.version, installed),
            "warnings": [dict(w) for w in tool.warnings]}


def cards(lib: Library, installed: Dict[str, str]) -> List[dict]:
    """整份清單的工具卡片（外觀包不列：它們在「外觀 → 衣櫃」）：官方工具照工具庫網站的順序（TOOLS），其他的照名字排在後面。"""
    order = list(TOOLS)
    tools = sorted((t for t in lib.tools if not t.is_theme),
                   key=lambda t: (order.index(t.name) if t.name in order else len(order), t.name))
    return [card(t, installed.get(t.name, "")) for t in tools]


def wardrobe_card(tool: Tool, installed: str = "") -> dict:
    """衣櫃的一張卡（外觀包）：標題、一句話、小預覽（色條或字母方塊）、已安裝／有新版。字一樣都是純文字。"""
    _emoji, title = _split_title(tool.title)
    letter = tool.series or (title[:1].upper() if title[:1].isalnum() else "") or tool.name[:1].upper()
    return {"name": tool.name, "title": title or tool.name, "line": tool.line or tool.summary, "summary": tool.summary,
            "version": tool.version, "letter": letter, "swatches": list(tool.swatches),
            "badge": {"text": stage_label(tool.stage), "hint": stage_text(tool.stage)},
            "installed": installed or "", "newer": _newer(tool.version, installed)}


def wardrobe_cards(lib: Library, installed: Dict[str, str]) -> List[dict]:
    """衣櫃（只有外觀包）：照系列字母、再照名字排。"""
    themes = sorted(lib.themes, key=lambda t: (t.series or "~", t.name))
    return [wardrobe_card(t, installed.get(t.name, "")) for t in themes]


def wardrobe_info(lib: Library) -> dict:
    """衣櫃的標題與一句話（清單的 collections.wardrobe；沒有就用內建的字）。"""
    info = lib.collections.get("wardrobe") or {}
    return {"title": info.get("title") or WARDROBE_TITLE, "summary": info.get("summary") or ""}


# ── 有新版的工具（「全部更新」、`synox tools check／update`、每週檢查）───────────────

def updates(lib: Library, installed: Dict[str, str]) -> List[dict]:
    """裝著、而且清單上的版本比較新的：工具和外觀包（kind=theme）都算。照名字排。
    每一筆：name、title、kind（"theme"＝外觀包，"tool"＝工具）、installed（裝著的）、version（清單上的）。"""
    out = []
    for tool in lib.tools:
        have = installed.get(tool.name, "")
        if _newer(tool.version, have):
            _emoji, title = _split_title(tool.title)
            static = TOOLS.get(tool.name)
            out.append({"name": tool.name, "title": title or (static[1] if static else tool.name),
                        "kind": "theme" if tool.is_theme else "tool", "installed": have, "version": tool.version})
    return sorted(out, key=lambda u: u["name"])


def stage_tool(tool: Tool, data_dir: str, opener: Optional[Opener] = None) -> Tuple[str, dict]:
    """下載一個工具（大小、sha256 對清單）→ admin.stage（安全管線第 1、2 關，跟上傳同一條路）→ (token, 摘要)。
    壓縮檔裡的名字／版本／種類跟清單不一樣＝丟掉暫存、丟 CatalogError。**不裝**：裝要人看過報告再核准。
    admin.GateRefused（檢查沒過，摘要裡有報告）、admin.PackAdminError 照原樣往外丟。"""
    from synox.packs.admin import PackAdminError, discard_staged, stage
    blob = download(tool, opener=opener)
    token, summary = stage(blob, data_dir)
    if summary.get("name") != tool.name or summary.get("version") != tool.version or \
            (summary.get("kind") == "theme") != tool.is_theme:
        try:
            discard_staged(token, data_dir)
        except PackAdminError:
            pass
        raise CatalogError(TEXT["not_listed"])
    return token, summary
