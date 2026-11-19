"""
SYNOX 本體的「有沒有新版」（docs/adr/0023 §1、決定 U2、U3）。

- **只在使用者按了才連網**（`synox update --check`、網頁設定「💻 電腦與備份」→「檢查更新」），或使用者自己打開「每週看一次」
  （config.json `"updates": {"check": "weekly"}`，**預設 manual＝不查**）。查到了只顯示、通知一次，不下載、不安裝。
- 問哪裡（寫死），每次檢查問兩件事（決定 U3，2026-11-19 修訂）：
  (a) 最新**正式版**：`GET https://api.github.com/repos/ChouYangEn0401/SYNOX/releases/latest`（再擋一次：prerelease／draft／
      版本號有尾巴＝不算，當作「還沒有正式版」）；
  (b) 最新**測試版**：`GET …/releases?per_page=20`，草稿不算，只看預覽版（版本號有尾巴或標了 prerelease），**用 SemVer 挑最大的**
      （不看 GitHub 的時間順序）。
  兩行都給人看（卡片、`synox update --check`）；「有新版」的提示、橫幅、每週通知、Update.bat 照**更新通道**：
  config.json `"updates": {"channel": "stable" | "preview"}`，**預設 stable＝只看正式版**；preview＝正式版與測試版取 SemVer 較大的。
  命令列 `--include-prerelease`＝這一次當作 preview。
- 送出去的只有那兩個 GET（User-Agent `synox-update-check`，不帶版本、不帶任何識別）；GitHub 看得到 IP。
  代理伺服器：urllib 預設就照 HTTPS_PROXY 等環境變數（Windows 也讀系統的 Proxy 設定）。逾時 15 秒。
- 轉址只跟 GitHub 自己的主機（api.github.com；附檔才到 github.com 的 SYNOX releases 路徑與 GitHub 的下載主機）。
- 安全更新：發佈頁的標題或說明有「🔒 安全更新」或「強烈建議更新」（docs/versioning.md、決定 U9）→ security=True。
- 失敗一律安靜：回 status="error" 和一句人話，記 log，不丟例外、不重試。
- 預覽版（beta／alpha）：卡片一定顯示「最新測試版」那一行（只看）；要被提醒、讓 Update.bat 也裝測試版，要自己選 preview 通道
  （卡片「也提醒我有測試版」、`synox update --channel preview`），或這一次加 `--include-prerelease`（只看，不存結果）。
- **只給測試用**：環境變數 `SYNOX_UPDATE_API`（docs/release-playbook.md「先測更新」）把「問哪裡」換成這台電腦上的檔案
  （路徑或 file:// 網址）或 http://127.0.0.1／localhost。只從環境變數讀（config.json、網頁都改不到它），而且只收本機的
  目的地（指到別台主機一律拒絕），用的時候每一次輸出、每個通知最上面都印「⚠️⚠️ 測試模式」。測試模式下發佈的附檔也只能是
  本機的檔案，預覽版也算數（測試包的版本像 0.2.1-test.1）。

測試一律換 opener（`opener(url, timeout, limit, sink=None) -> (status, Location, body)`），不連網。
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from http.client import HTTPException
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from synox import __version__
from synox.packs.upgrade import semver_key

OWNER_REPO = "ChouYangEn0401/SYNOX"
API_URL = f"https://api.github.com/repos/{OWNER_REPO}/releases/latest"
API_LIST_URL = f"https://api.github.com/repos/{OWNER_REPO}/releases?per_page=20"   # 最新測試版（預覽版）
CHANNELS = ("stable", "preview")
TEST_API_ENV = "SYNOX_UPDATE_API"        # 只給測試：只從環境變數讀、只收本機的檔案／127.0.0.1（見上面）
LOOPBACK = ("127.0.0.1", "localhost", "::1")
RELEASES_PAGE = f"https://github.com/{OWNER_REPO}/releases"
DOWNLOAD_PATH = f"/{OWNER_REPO}/releases/download/"
ASSET_HOSTS = ("objects.githubusercontent.com", "release-assets.githubusercontent.com")
USER_AGENT = "synox-update-check"
TIMEOUT = 15
TOTAL_TIMEOUT = 600                      # 一個檔從頭到尾（ZIP 可能幾十 MB）
MAX_API = 1024 * 1024                    # releases/latest 的回應（說明很長也不會到 1 MB）
MAX_REDIRECTS = 5
WEEK = 7 * 24 * 3600
STATE_FILE = "update_check.json"         # data/ 裡：上次查的時間、結果、通知過哪一版
SECURITY_MARKERS = ("🔒 安全更新", "強烈建議更新")
CHECK_MODES = ("manual", "weekly")
STABLE_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ANY_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")

Opener = Callable[..., Tuple[int, Optional[str], bytes]]

TEXT = {
    "offline": "連不到 GitHub（可能沒有網路，或公司網路擋住了）。等一下再試，或直接打開發佈頁看。",
    "not_found": "GitHub 上還沒有 SYNOX 的正式版。可以打開發佈頁看看。",
    "bad_status": "GitHub 現在回應不正常（也可能是查太多次被暫時擋住），等一下再試，或直接打開發佈頁看。",
    "moved": "GitHub 把查詢轉到不認得的地方，為了安全沒有跟過去。可以直接打開發佈頁看。",
    "broken": "GitHub 回的內容看不懂，先不顯示。可以直接打開發佈頁看。",
    "too_big": "GitHub 回的內容太大，沒有讀。可以直接打開發佈頁看。",
    "current": "你是最新版 ✅",
    "ahead": "你裝的版本比最新的正式版還新（測試版或開發中的版本），不用更新。",
    "ahead_preview": "你裝的版本比 GitHub 上最新的正式版和測試版都新（開發中的版本），不用更新。",
    "none": "GitHub 上還沒有可以更新的正式版（下面是正式版與測試版的現況）。",
    "none_preview": "GitHub 上還沒有 SYNOX 的正式版，也沒有測試版。",
    "newer": "有新版：{installed} → {latest}",
    "stable_line": "最新正式版：{v}（{state}）",
    "stable_none": "最新正式版：還沒有正式版",
    "preview_line": "最新測試版：{v}（{state}）",
    "preview_none": "最新測試版：沒有測試版",
    "unknown_line": "{label}：無法判斷（{why}）",
    "state_newer": "比你裝的新",
    "state_current": "跟你裝的一樣",
    "state_ahead": "比你裝的舊",
    "order_note": "（測試版的號碼比同號的正式版小：0.2.2-alpha.1 < 0.2.2-beta.1 < 0.2.2。）",
    "preview_hint": "有比你裝的新的測試版，但你只收正式版的提醒。想被提醒、讓 Update.bat 也能裝測試版："
                    "在設定卡片打開「也提醒我有測試版」（或 synox update --channel preview）。測試版可能還有問題。",
    "security": "🔒 強烈建議更新：這版修了安全問題。",
    "tools": "有 {n} 個工具可以更新（設定 → 🧩 功能與安裝 → 工具庫，按「看有哪些工具」→「全部更新」；"
             "或打 synox tools update --all。一樣先給你看檢查的結果，你同意了才換）。",
    "test_mode": "⚠️⚠️ 測試模式：SYNOX_UPDATE_API={src}（只給測試用：查新版、下載都改到這台電腦上的檔案，不是 GitHub）。"
                 "不是你自己設的，請關掉這個視窗、刪掉這個環境變數。",
    "test_bad": "SYNOX_UPDATE_API 只能指到這台電腦上的檔案或 http://127.0.0.1（只給測試用），這個值不收：{src}",
    "prerelease": "（{v} 是測試版（預覽版）：你選了也提醒測試版，或這次加了 --include-prerelease。測試版可能還有問題。）",
    "how_git": "你的 SYNOX 是用 git 裝的：關掉 SYNOX（Stop.bat）→ 在 SYNOX 資料夾打 `git pull` → 點兩下 Setup.bat。",
    "how_zip": "要更新：點兩下 SYNOX 資料夾裡的 Update.bat（會先給你看這版改了什麼，你按確認才換；你的設定、資料、工具都不動）。",
    "how_exe": "你的 SYNOX 是用安裝程式裝的：到發佈頁下載新的 SYNOX-Setup-<版本>.exe，裝在原本的位置。",
    "how_docker": "你用的是 Docker：`git pull` → `docker compose build` → `docker compose up -d`。",
}


class UpdateError(Exception):
    """給人看的錯誤（offline＝連不上，不是我們拒絕的）。"""

    def __init__(self, message: str, offline: bool = False):
        super().__init__(message)
        self.offline = offline


class NotFound(UpdateError):
    """GitHub 上沒有這種版本（還沒有正式版／沒有測試版）：不是錯，只是「沒有」。"""

    def __init__(self, message: str = ""):
        super().__init__(message or TEXT["not_found"], offline=True)


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0
    digest: str = ""                       # GitHub 給的 "sha256:<hex>"（有的話）


@dataclass
class Release:
    version: str
    tag: str
    title: str
    date: str
    body: str
    url: str
    assets: List[Asset] = field(default_factory=list)
    prerelease: bool = False

    def asset(self, name: str) -> Optional[Asset]:
        return next((a for a in self.assets if a.name == name), None)


@dataclass
class CheckResult:
    status: str                            # newer | current | ahead | none（通道上還沒有任何版本）| error
    installed: str
    latest: str = ""
    date: str = ""
    title: str = ""
    summary: str = ""
    notes_url: str = RELEASES_PAGE
    security: bool = False
    signed: bool = False                   # 這一版有附簽章（release.json.sig），而且這個 SYNOX 有公鑰可以驗
    message: str = ""
    kind: str = "zip"                      # zip | git | exe | docker（怎麼裝的，決定「怎麼更新」那一句）
    tools_newer: Optional[int] = None      # 工具庫裡有新版的工具有幾個（None＝沒查）
    checked_at: float = 0.0
    prerelease: bool = False               # 「有新版」指的是預覽版（preview 通道、--include-prerelease、測試模式）
    test_source: str = ""                  # 測試模式（SYNOX_UPDATE_API）用的來源；空＝GitHub
    channel: str = "stable"                # 這次照哪個通道判斷「有新版」：stable（只看正式版）｜preview（也看測試版）
    # 卡片的兩行（不管通道都有）：{"version", "date", "url", "state": newer|current|ahead|none|unknown, "why"}
    stable: dict = field(default_factory=dict)
    preview: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = asdict(self)
        out["lines"] = self.lines()
        return out

    def channel_lines(self) -> List[str]:
        """「最新正式版：…」「最新測試版：…」兩行＋號碼順序的說明（沒查過＝空）。"""
        if not self.stable and not self.preview:
            return []
        out = [_channel_line(self.stable, "stable"), _channel_line(self.preview, "preview"), TEXT["order_note"]]
        if self.channel == "stable" and self.preview.get("state") == "newer" and self.status != "newer" \
                and not self.test_source:
            out.append(TEXT["preview_hint"])
        return out

    def lines(self) -> List[str]:
        """給人看的幾行（終端機、通知、網頁都用這份）：第一行是結論，接著兩行正式版／測試版的現況。"""
        out: List[str] = []
        if self.test_source:
            out.append(TEXT["test_mode"].format(src=self.test_source))
        if self.status == "error":
            out.append("❌ " + (self.message or TEXT["offline"]))
            out.append(f"發佈頁：{RELEASES_PAGE}")
        elif self.status == "none":
            out.append(TEXT["none_preview" if self.channel == "preview" else "none"])
        elif self.status == "newer":
            when = f"（{self.date}）" if self.date else ""
            out.append(TEXT["newer"].format(installed=self.installed, latest=self.latest) + when)
            if self.prerelease and not self.test_source:
                out.append(TEXT["prerelease"].format(v=self.latest))
            if self.security:
                out.append(TEXT["security"])
            if self.summary:
                out.append("這版改了什麼：" + self.summary)
            out.append(f"完整說明：{self.notes_url}")
            out.append(how_line(self.kind))
        elif self.status == "ahead":
            if self.channel == "preview":
                out.append(f"你是 {self.installed}，GitHub 上最新的是 {self.latest}。" + TEXT["ahead_preview"])
            else:
                out.append(f"你是 {self.installed}，最新的正式版是 {self.latest}。" + TEXT["ahead"])
        else:
            out.append(f"{TEXT['current']}（{self.installed}）")
        out += self.channel_lines()
        if self.tools_newer:
            out.append(TEXT["tools"].format(n=self.tools_newer))
        return out


def _channel_line(info: dict, which: str) -> str:
    label = "最新正式版" if which == "stable" else "最新測試版"
    state = info.get("state") if isinstance(info, dict) else None
    if state == "none":
        return TEXT[which + "_none"]
    if state in ("newer", "current", "ahead") and info.get("version"):
        return TEXT[which + "_line"].format(v=info["version"], state=TEXT["state_" + state])
    return TEXT["unknown_line"].format(label=label, why=(info or {}).get("why") or "沒有查到")


def how_line(kind: str) -> str:
    return TEXT.get("how_" + kind, TEXT["how_zip"])


# ── 版本 ─────────────────────────────────────────────────────────────

def compare(installed: str, latest: str) -> str:
    """newer（latest 比較新）｜current（一樣）｜ahead（裝的比較新）｜invalid。照 semver（正式版 > 同號的 beta > alpha）。"""
    a, b = semver_key(installed), semver_key(latest)
    if a is None or b is None:
        return "invalid"
    return "newer" if b > a else "current" if b == a else "ahead"


def install_kind(root: str) -> str:
    """怎麼裝的：git（有 .git）｜exe（安裝程式留下 installer-choices.json）｜docker｜zip（其他）。"""
    if os.path.exists(os.path.join(root, ".git")):
        return "git"
    if os.environ.get("SYNOX_IN_DOCKER") == "1" or os.path.exists("/.dockerenv"):
        return "docker"
    try:
        with open(os.path.join(root, "installer-choices.json"), "r", encoding="utf-8-sig") as f:
            if (json.load(f) or {}).get("source") == "exe-installer":
                return "exe"
    except (OSError, ValueError, AttributeError):
        pass
    return "zip"


# ── 連網（只有這裡）──────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())     # 照預設帶 ProxyHandler（環境變數／Windows 的 Proxy 設定）


def default_opener(url: str, timeout: float, limit: int, sink=None) -> Tuple[int, Optional[str], bytes]:
    """真的連網：(狀態碼, Location, 內容)。sink（檔案）有給就邊讀邊寫進去、回傳 b""；最多讀 limit+1 個位元組。"""
    return _open(_OPENER, url, timeout, limit, sink)


def _open(opener, url: str, timeout: float, limit: int, sink=None) -> Tuple[int, Optional[str], bytes]:
    api = urlsplit(url).hostname == "api.github.com"
    headers = {"User-Agent": USER_AGENT,
               "Accept": "application/vnd.github+json" if api else "application/octet-stream"}
    if api:
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as e:
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
            chunk = response.read(min(1 << 16, limit + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if sink is not None:
                sink.write(chunk)
            else:
                chunks.append(chunk)
        if sink is not None:
            return response.status, None, (b"\0" * (limit + 1) if size > limit else b"")
        return response.status, None, b"".join(chunks)


def allowed(url: str, first: bool) -> bool:
    """https、預設埠、沒有帳密；api.github.com 只限這個 repo 的 releases；github.com 只限 SYNOX 的下載路徑；
    下載主機（ASSET_HOSTS）只能是轉址過去的。"""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return False
    host = (parts.hostname or "").lower()
    if ".." in parts.path:
        return False
    if host == "api.github.com":
        return parts.path.startswith(f"/repos/{OWNER_REPO}/releases")
    if host == "github.com":
        return parts.path.startswith(DOWNLOAD_PATH)
    return not first and host in ASSET_HOSTS


# ── 只給測試：SYNOX_UPDATE_API（只從環境變數讀、只收本機）──────────────────

def test_api() -> str:
    """測試模式的來源（環境變數 SYNOX_UPDATE_API）；空＝正常（GitHub）。config.json 裡寫什麼都不算。"""
    return os.environ.get(TEST_API_ENV, "").strip()


def is_local(url: str) -> bool:
    """file://（這台的檔）或 http://127.0.0.1|localhost|[::1]。"""
    try:
        parts = urlsplit(url)
        _port = parts.port                      # 埠寫壞了丟 ValueError
    except ValueError:
        return False
    if parts.username or parts.password:
        return False
    if parts.scheme == "file":
        return parts.netloc in ("", "localhost")
    return parts.scheme == "http" and (parts.hostname or "").lower() in LOOPBACK


def local_url(value: str) -> str:
    """測試來源 → 網址：絕對路徑（→ file://）、file:// 網址、http://127.0.0.1|localhost|[::1]。其他（別台主機）回 ""。"""
    if not value:
        return ""
    if os.path.isabs(value):
        return pathlib.Path(value).resolve().as_uri()
    return value if is_local(value) else ""


_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())   # 127.0.0.1 不走代理


def local_opener(url: str, timeout: float, limit: int, sink=None) -> Tuple[int, Optional[str], bytes]:
    """測試模式的 opener：file:// 讀這台的檔；http://127.0.0.1 照一般的讀法（不走代理）。"""
    parts = urlsplit(url)
    if parts.scheme != "file":
        return _open(_LOCAL_OPENER, url, timeout, limit, sink)
    path = urllib.request.url2pathname(parts.path)
    if not os.path.isfile(path):
        return 404, None, b""
    if os.path.getsize(path) > limit:
        return 200, None, b"\0" * (limit + 1)
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    if sink is not None:
        sink.write(data)
        return 200, None, b""
    return 200, None, data


def get(url: str, limit: int, opener: Optional[Opener] = None, sink=None) -> bytes:
    """抓一個網址（只跟 GitHub 自己的轉址）；任何不對丟 UpdateError。sink：寫進檔案（大檔）。
    測試模式（SYNOX_UPDATE_API）：只收這台電腦上的檔案／127.0.0.1，不跟轉址。"""
    testing = bool(test_api())
    opener = opener or (local_opener if testing else default_opener)
    ok = (lambda u, first: first and is_local(u)) if testing else allowed
    if not ok(url, True):
        raise UpdateError(TEXT["moved"])
    current = url
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            status, location, body = opener(current, TIMEOUT, limit, sink) if sink is not None else \
                opener(current, TIMEOUT, limit)
        except UpdateError:
            raise
        except (urllib.error.URLError, OSError, HTTPException, ValueError):
            raise UpdateError(TEXT["offline"], offline=True)
        if status in (301, 302, 303, 307, 308):
            target = urljoin(current, location or "")
            if not location or not ok(target, False):
                raise UpdateError(TEXT["moved"])
            current = target
            continue
        if status == 404:
            raise NotFound()
        if status != 200:
            raise UpdateError(TEXT["bad_status"], offline=True)
        if len(body) > limit:
            raise UpdateError(TEXT["too_big"])
        return body
    raise UpdateError(TEXT["moved"])


# ── 讀 GitHub 的回應 ──────────────────────────────────────────────────

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")


def _clean(text, limit: int) -> str:
    return _CONTROL_RE.sub("", text).strip()[:limit] if isinstance(text, str) else ""


def parse_release(blob: bytes, allow_prerelease: bool = False) -> Release:
    """releases/latest 的 JSON → Release。預覽版、草稿、版本號不是 X.Y.Z 的一律不算（UpdateError）。
    allow_prerelease（只有 --include-prerelease、測試模式）：預覽版也算；也收 releases 的清單（JSON 陣列），挑版本最大的
    （草稿、看不懂的跳過）。"""
    try:
        raw = json.loads(blob.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise UpdateError(TEXT["broken"])
    if isinstance(raw, list):
        best = None
        for item in raw[:100]:
            try:
                rel = _release(item, allow_prerelease)
            except UpdateError:
                continue
            if best is None or semver_key(rel.version) > semver_key(best.version):
                best = rel
        if best is None:
            raise NotFound()
        return best
    return _release(raw, allow_prerelease)


def _release(raw, allow_prerelease: bool) -> Release:
    if not isinstance(raw, dict):
        raise UpdateError(TEXT["broken"])
    tag = raw.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v") or not ANY_RE.match(tag[1:]):
        raise UpdateError(TEXT["broken"])
    if not allow_prerelease and not STABLE_RE.match(tag[1:]):
        raise NotFound()                     # latest 指到版本號有尾巴的（被標成 Latest 的 alpha）：不算正式版
    if raw.get("draft") or (raw.get("prerelease") and not allow_prerelease):
        raise NotFound()
    assets = []
    for item in raw.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name, url = item.get("name"), item.get("browser_download_url")
        if not (isinstance(name, str) and isinstance(url, str) and re.match(r"^[\w.+-]{1,120}$", name)):
            continue
        size = item.get("size") if isinstance(item.get("size"), int) and not isinstance(item.get("size"), bool) else 0
        digest = item.get("digest") if isinstance(item.get("digest"), str) else ""
        assets.append(Asset(name=name, url=url, size=max(0, size), digest=digest.lower()))
    date = _clean(raw.get("published_at"), 40)[:10]
    url = raw.get("html_url") if isinstance(raw.get("html_url"), str) and \
        raw["html_url"].startswith(f"https://github.com/{OWNER_REPO}/releases/") else f"{RELEASES_PAGE}/tag/{tag}"
    return Release(version=tag[1:], tag=tag, title=_clean(raw.get("name"), 120), date=date,
                   body=_clean(raw.get("body"), 20000), url=url, assets=assets,
                   prerelease=bool(raw.get("prerelease")) or "-" in tag)


def is_security(release: Release) -> bool:
    return any(m in release.title or m in release.body for m in SECURITY_MARKERS)


def summarize(body: str, limit: int = 300) -> str:
    """發佈說明「這版改了什麼」那一段的前幾條（沒有那一段就用前幾條清單），去掉 markdown 與 HTML 註解。"""
    text = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)
    lines = text.splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if re.match(r"^#{1,6}\s*這版改了什麼", ln.strip())), 0)
    items: List[str] = []
    for ln in lines[start:]:
        s = ln.strip()
        if start and s.startswith("#"):
            break
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            item = re.sub(r"[*_`]", "", m.group(1))
            item = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", item).strip()
            if item:
                items.append(item)
        if len(items) >= 3:
            break
    out = "；".join(items)
    return out if len(out) <= limit else out[:limit - 1] + "…"


def is_preview(rel: Release) -> bool:
    """預覽版＝版本號有尾巴（-alpha.N、-beta.N…）或 GitHub 標了 pre-release。"""
    return rel.prerelease or "-" in rel.version


def _best(raw_list, want_preview: bool) -> Release:
    """releases 清單（JSON 陣列）裡 SemVer 最大的正式版／預覽版；草稿、看不懂的跳過；一個都沒有＝NotFound。
    **不看 GitHub 的時間順序**。"""
    if not isinstance(raw_list, list):
        raise UpdateError(TEXT["broken"])
    best = None
    for item in raw_list[:100]:
        try:
            rel = _release(item, True)
        except UpdateError:
            continue
        if is_preview(rel) != want_preview:
            continue
        if best is None or semver_key(rel.version) > semver_key(best.version):
            best = rel
    if best is None:
        raise NotFound()
    return best


def _load(blob: bytes):
    try:
        return json.loads(blob.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise UpdateError(TEXT["broken"])


def _test_url() -> str:
    src = test_api()
    url = local_url(src)
    if not url:
        raise UpdateError(TEXT["test_bad"].format(src=src))
    logging.warning("[UPDATE] TEST MODE: %s=%s (not GitHub)", TEST_API_ENV, src)
    return url


def fetch_stable(opener: Optional[Opener] = None) -> Release:
    """最新的正式版（releases/latest）。沒有＝NotFound；連不上、看不懂＝UpdateError。"""
    return _release(_load(get(API_URL, MAX_API, opener)), False)     # latest 一定是一個物件；清單＝看不懂


def fetch_preview(opener: Optional[Opener] = None) -> Release:
    """最新的測試版（releases 清單裡 SemVer 最大的預覽版）。沒有＝NotFound。"""
    return _best(_load(get(API_LIST_URL, MAX_API, opener)), want_preview=True)


Found = Tuple[Optional[Release], Optional[UpdateError]]     # (找到的版本, 沒找到的原因)；NotFound＝沒有這種版本


def _try(fn, *args) -> Found:
    try:
        return fn(*args), None
    except UpdateError as e:
        return None, e


def fetch_channels(opener: Optional[Opener] = None) -> Tuple[Found, Found]:
    """(最新正式版, 最新測試版)，各自是 (Release 或 None, 錯誤或 None)。兩個 GET；一個失敗不影響另一個。
    測試模式（SYNOX_UPDATE_API）：只讀那個本機的檔（一個發佈或一份清單），從裡面分出正式版與測試版。"""
    if test_api():
        try:
            raw = _load(get(_test_url(), MAX_API, opener))
        except UpdateError as e:
            return (None, e), (None, e)
        items = raw if isinstance(raw, list) else [raw]
        return _try(_best, items, False), _try(_best, items, True)
    return _try(fetch_stable, opener), _try(fetch_preview, opener)


def pick(stable: Found, preview: Found, include_prerelease: bool) -> Release:
    """照通道挑「要不要更新」比的那一版：stable＝最新正式版；preview＝正式版與測試版取 SemVer 較大的。
    都沒有：有錯（連不上、看不懂）丟那個錯；只是沒有這種版本丟 NotFound。"""
    sources = [stable] + ([preview] if include_prerelease else [])
    found = [rel for rel, _err in sources if rel is not None]
    if found:
        return max(found, key=lambda r: semver_key(r.version))
    errors = [err for _rel, err in sources if err is not None and not isinstance(err, NotFound)]
    if errors:
        raise errors[0]
    raise NotFound()


def fetch_latest(opener: Optional[Opener] = None, include_prerelease: bool = False) -> Release:
    """這次要比的那一版（prepare 用）：預設最新的正式版（只問 releases/latest）；include_prerelease＝正式版與測試版取
    SemVer 較大的（兩個都問）。測試模式（SYNOX_UPDATE_API）：讀那個本機的檔案（預覽版也算）。"""
    if test_api():
        stable, preview = fetch_channels(opener)
        return pick(stable, preview, True)
    if not include_prerelease:
        return fetch_stable(opener)
    stable, preview = fetch_channels(opener)
    return pick(stable, preview, True)


def _why(err: Optional[UpdateError]) -> str:
    """錯誤的第一句（卡片「無法判斷（…）」用）。"""
    text = str(err or "") or TEXT["broken"]
    return text.split("。")[0].split("（")[0].strip() or text


def _info(found: Found, installed: str) -> dict:
    rel, err = found
    if rel is None:
        if isinstance(err, NotFound):
            return {"state": "none"}
        return {"state": "unknown", "why": _why(err)}
    state = compare(installed, rel.version)
    if state == "invalid":
        return {"state": "unknown", "version": rel.version, "why": "比不出新舊"}
    return {"state": state, "version": rel.version, "date": rel.date, "url": rel.url}


def check(installed: str = __version__, *, root: str = "", opener: Optional[Opener] = None,
          tools: Optional[Callable[[], Optional[int]]] = None, keys=None, clock=time.time,
          include_prerelease: bool = False) -> CheckResult:
    """問 GitHub 最新的正式版與最新的測試版，跟裝著的比。從不丟例外：連不上、看不懂＝那一行「無法判斷」，
    要比的那一版拿不到＝status error＋一句人話（記 log）。
    include_prerelease（preview 通道、命令列 --include-prerelease）：「有新版」也算測試版；否則只看正式版。
    tools：另外算「有幾個工具可以更新」（失敗回 None，不影響本體的結果）。"""
    from synox.update import signing
    kind = install_kind(root) if root else "zip"
    result = CheckResult(status="error", installed=installed, kind=kind, checked_at=clock(), test_source=test_api(),
                         channel="preview" if include_prerelease else "stable")
    if result.test_source:
        keys = list(signing.RELEASE_PUBLIC_KEYS if keys is None else keys) + signing.test_keys()
        include_prerelease = True                     # 測試包的版本像 0.2.1-test.1
        result.channel = "preview"
    stable, preview = fetch_channels(opener)
    result.stable, result.preview = _info(stable, installed), _info(preview, installed)
    try:
        rel = pick(stable, preview, include_prerelease)
    except NotFound:
        result.status = "none"
    except UpdateError as e:
        logging.info("[UPDATE] check failed: %s", e)
        result.message = str(e)
    else:
        state = compare(installed, rel.version)
        if state == "invalid":
            result.message = f"比不出新舊（裝著的是 {installed!r}）。可以直接打開發佈頁看。"
        else:
            result.status = state
            result.latest, result.date, result.title = rel.version, rel.date, rel.title
            result.summary, result.notes_url, result.security = summarize(rel.body), rel.url, is_security(rel)
            result.prerelease = is_preview(rel)
            result.signed = bool(rel.asset(signing.SIG_ASSET) and rel.asset(signing.MANIFEST_ASSET)
                                 and signing.public_keys(keys))
    if tools is not None:
        try:
            result.tools_newer = tools()
        except Exception:                                   # 工具庫查不到不影響本體的結果
            logging.info("[UPDATE] tool library check failed", exc_info=True)
            result.tools_newer = None
    return result


def tools_updates(installed: Dict[str, str], opener=None) -> List[dict]:
    """工具庫（官方清單，跟「載入工具清單」同一份）裡比裝著的新的工具與外觀包（catalog.updates）。會連網。"""
    from synox.packs import catalog
    return catalog.updates(catalog.fetch_library(opener=opener), installed)


def tools_newer_count(installed: Dict[str, str], opener=None) -> int:
    """有新版的工具有幾個（外觀包也算）。"""
    return len(tools_updates(installed, opener=opener))


def installed_pack_versions(packs_dir: str) -> Dict[str, str]:
    """packs/ 底下每個裝著的工具 → 版本（讀 pack.json；_ 開頭的資料夾不算）。"""
    out: Dict[str, str] = {}
    if not os.path.isdir(packs_dir):
        return out
    for name in os.listdir(packs_dir):
        path = os.path.join(packs_dir, name, "pack.json")
        if name.startswith("_") or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            out[str(raw.get("name") or name)] = str(raw.get("version") or "")
        except (OSError, ValueError, AttributeError):
            continue
    return out


# ── 每週檢查（選用，預設關）與狀態檔 ─────────────────────────────────

def check_mode(raw_config: Optional[dict]) -> str:
    """config.json 的 updates.check：manual（預設，不自己查）｜weekly。寫錯＝manual。"""
    updates = (raw_config or {}).get("updates") if isinstance(raw_config, dict) else None
    mode = updates.get("check") if isinstance(updates, dict) else None
    return mode if mode in CHECK_MODES else "manual"


def weekly_enabled(raw_config: Optional[dict]) -> bool:
    return check_mode(raw_config) == "weekly"


def set_mode(cfg: dict, weekly: bool) -> dict:
    out = dict(cfg)
    updates = dict(out.get("updates") or {}) if isinstance(out.get("updates"), dict) else {}
    updates["check"] = "weekly" if weekly else "manual"
    out["updates"] = updates
    return out


def channel(raw_config: Optional[dict]) -> str:
    """config.json 的 updates.channel：stable（預設，「有新版」只看正式版）｜preview（也看測試版）。
    缺鍵、寫錯＝stable（舊的 config.json 不用改、不用遷移：ADR 0044 的「新增選填鍵」）。"""
    updates = (raw_config or {}).get("updates") if isinstance(raw_config, dict) else None
    value = updates.get("channel") if isinstance(updates, dict) else None
    return value if value in CHANNELS else "stable"


def wants_preview(raw_config: Optional[dict]) -> bool:
    return channel(raw_config) == "preview"


def set_channel(cfg: dict, preview: bool) -> dict:
    out = dict(cfg)
    updates = dict(out.get("updates") or {}) if isinstance(out.get("updates"), dict) else {}
    updates["channel"] = "preview" if preview else "stable"
    out["updates"] = updates
    return out


def load_state(data_dir: str) -> dict:
    try:
        with open(os.path.join(data_dir, STATE_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(data_dir: str, state: dict) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, STATE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def remember(data_dir: str, result: CheckResult) -> dict:
    """存這次的結果（網頁的卡片與橫幅讀它）。"""
    state = load_state(data_dir)
    state["last_check"] = result.checked_at
    state["result"] = result.to_dict()
    save_state(data_dir, state)
    return state


def due(state: dict, now: float) -> bool:
    last = state.get("last_check")
    return not isinstance(last, (int, float)) or now - float(last) >= WEEK


def notice_text(result: CheckResult) -> str:
    head = "🔒 SYNOX 有安全更新" if result.security else "🆕 SYNOX 有新版"
    lines = replace(result, tools_newer=None, test_source="").lines()      # 工具另外一則通知
    test = [TEXT["test_mode"].format(src=result.test_source)] if result.test_source else []
    return "\n".join(test + [f"{head}：{result.installed} → {result.latest}"] + lines[1:])


def tools_notice_text(ups: List[dict]) -> str:
    """每週檢查：工具（含外觀包）有新版的那一則通知。"""
    names = "、".join(("外觀 " if u.get("kind") == "theme" else "") + f"{u['name']} {u['installed']} → {u['version']}"
                     for u in ups[:8]) + ("…" if len(ups) > 8 else "")
    return (f"🧩 有 {len(ups)} 個工具可以更新：{names}\n"
            "要更新：網頁「設定 → 🧩 功能與安裝」按「看有哪些工具」→「全部更新」，或在 SYNOX 資料夾打 "
            "python -m synox tools update --all。一樣先給你看檢查報告，你核准了才換（舊版會留著，可以退回）。")


def tools_key(ups: List[dict]) -> str:
    """「這一組版本」：同一組只通知一次。"""
    return ",".join(sorted(f"{u['name']}@{u['version']}" for u in ups))


def weekly_tick(data_dir: str, raw_config: Optional[dict], notify: Callable[[str], None], *,
                installed: str = __version__, root: str = "", opener: Optional[Opener] = None,
                clock=time.time, tools: Optional[Callable[[], Optional[List[dict]]]] = None) -> str:
    """runtime 每幾小時叫一次：沒打開每週檢查＝什麼都不做（不連網）；打開了、距離上次 ≥ 7 天才查。
    查到新版：同一個版本只通知擁有者一次（Telegram／Discord＋網頁的橫幅）。回一句給任務狀態看的字。
    tools（有給才查）：工具與外觀包有新版的清單（tools_updates）；同一組版本只通知一次。只看，從不自己裝。"""
    if not weekly_enabled(raw_config):
        return "沒有打開每週檢查"
    state = load_state(data_dir)
    now = clock()
    if not due(state, now):
        return "這週查過了"
    result = check(installed, root=root, opener=opener, clock=clock, include_prerelease=wants_preview(raw_config))
    ups = None
    if tools is not None:
        try:
            ups = tools()
        except Exception:                                   # 工具庫查不到不影響本體
            logging.info("[UPDATE] weekly tool check failed", exc_info=True)
        if ups is not None:
            result.tools_newer = len(ups)
    state = remember(data_dir, result)
    if result.status != "newer":
        said = "沒有新版" if result.status != "error" else "這次沒查成（下週再試）"
    elif state.get("notified") == result.latest:
        said = f"有新版 {result.latest}（已經通知過）"
    else:
        try:
            notify(notice_text(result))
        except Exception:
            logging.exception("[UPDATE] notify failed")
        state["notified"] = result.latest
        save_state(data_dir, state)
        said = f"有新版 {result.latest}（通知了擁有者）"
    if ups:
        key = tools_key(ups)
        if state.get("tools_notified") == key:
            said += f"；{len(ups)} 個工具有新版（已經通知過）"
        else:
            try:
                notify(tools_notice_text(ups))
            except Exception:
                logging.exception("[UPDATE] notify failed")
            state["tools_notified"] = key
            save_state(data_dir, state)
            said += f"；{len(ups)} 個工具有新版（通知了擁有者）"
    return said
