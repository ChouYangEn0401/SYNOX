"""
SYNOX 本體的「有沒有新版」（docs/adr/0023 §1、決定 U2、U3）。

- **只在使用者按了才連網**（`synox update --check`、網頁設定「💻 電腦與備份」→「檢查更新」），或使用者自己打開「每週看一次」
  （config.json `"updates": {"check": "weekly"}`，**預設 manual＝不查**）。查到了只顯示、通知一次，不下載、不安裝。
- 問哪裡（寫死）：GitHub 的 `GET https://api.github.com/repos/ChouYangEn0401/SYNOX/releases/latest`。GitHub 的 latest
  **只會是正式版**（不含 pre-release、草稿），所以一般人永遠看不到 beta（決定 U3）；這裡再擋一次（prerelease／draft／版本號有尾巴＝不算）。
- 送出去的只有那一個 GET（User-Agent `synox-update-check`，不帶版本、不帶任何識別）；GitHub 看得到 IP。
  代理伺服器：urllib 預設就照 HTTPS_PROXY 等環境變數（Windows 也讀系統的 Proxy 設定）。逾時 15 秒。
- 轉址只跟 GitHub 自己的主機（api.github.com；附檔才到 github.com 的 SYNOX releases 路徑與 GitHub 的下載主機）。
- 安全更新：發佈頁的標題或說明有「🔒 安全更新」或「強烈建議更新」（docs/versioning.md、決定 U9）→ security=True。
- 失敗一律安靜：回 status="error" 和一句人話，記 log，不丟例外、不重試。

測試一律換 opener（`opener(url, timeout, limit, sink=None) -> (status, Location, body)`），不連網。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from http.client import HTTPException
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from synox import __version__
from synox.packs.upgrade import semver_key

OWNER_REPO = "ChouYangEn0401/SYNOX"
API_URL = f"https://api.github.com/repos/{OWNER_REPO}/releases/latest"
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
    "newer": "有新版：{installed} → {latest}",
    "security": "🔒 強烈建議更新：這版修了安全問題。",
    "tools": "有 {n} 個工具可以更新（設定 → 🧩 功能與安裝 → 工具庫，按「載入工具清單」）。",
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

    def asset(self, name: str) -> Optional[Asset]:
        return next((a for a in self.assets if a.name == name), None)


@dataclass
class CheckResult:
    status: str                            # newer | current | ahead | error
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

    def to_dict(self) -> dict:
        out = asdict(self)
        out["lines"] = self.lines()
        return out

    def lines(self) -> List[str]:
        """給人看的幾行（終端機、通知、網頁都用這份）。"""
        out: List[str] = []
        if self.status == "error":
            out.append("❌ " + (self.message or TEXT["offline"]))
            out.append(f"發佈頁：{RELEASES_PAGE}")
        elif self.status == "newer":
            when = f"（{self.date}）" if self.date else ""
            out.append(TEXT["newer"].format(installed=self.installed, latest=self.latest) + when)
            if self.security:
                out.append(TEXT["security"])
            if self.summary:
                out.append("這版改了什麼：" + self.summary)
            out.append(f"完整說明：{self.notes_url}")
            out.append(how_line(self.kind))
        elif self.status == "ahead":
            out.append(f"你是 {self.installed}，最新的正式版是 {self.latest}。" + TEXT["ahead"])
        else:
            out.append(f"{TEXT['current']}（{self.installed}）")
        if self.tools_newer:
            out.append(TEXT["tools"].format(n=self.tools_newer))
        return out


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
    api = urlsplit(url).hostname == "api.github.com"
    headers = {"User-Agent": USER_AGENT,
               "Accept": "application/vnd.github+json" if api else "application/octet-stream"}
    if api:
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = _OPENER.open(request, timeout=timeout)
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


def get(url: str, limit: int, opener: Optional[Opener] = None, sink=None) -> bytes:
    """抓一個網址（只跟 GitHub 自己的轉址）；任何不對丟 UpdateError。sink：寫進檔案（大檔）。"""
    opener = opener or default_opener
    if not allowed(url, first=True):
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
            if not location or not allowed(target, first=False):
                raise UpdateError(TEXT["moved"])
            current = target
            continue
        if status == 404:
            raise UpdateError(TEXT["not_found"], offline=True)
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


def parse_release(blob: bytes) -> Release:
    """releases/latest 的 JSON → Release。預覽版、草稿、版本號不是 X.Y.Z 的一律不算（UpdateError）。"""
    try:
        raw = json.loads(blob.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise UpdateError(TEXT["broken"])
    if not isinstance(raw, dict):
        raise UpdateError(TEXT["broken"])
    tag = raw.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v") or not STABLE_RE.match(tag[1:]):
        raise UpdateError(TEXT["broken"])
    if raw.get("prerelease") or raw.get("draft"):
        raise UpdateError(TEXT["not_found"])
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
                   body=_clean(raw.get("body"), 20000), url=url, assets=assets)


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


def fetch_latest(opener: Optional[Opener] = None) -> Release:
    return parse_release(get(API_URL, MAX_API, opener))


def check(installed: str = __version__, *, root: str = "", opener: Optional[Opener] = None,
          tools: Optional[Callable[[], Optional[int]]] = None, keys=None, clock=time.time) -> CheckResult:
    """問 GitHub 最新的正式版，跟裝著的比。從不丟例外：連不上、看不懂＝status error＋一句人話（記 log）。
    tools：另外算「有幾個工具可以更新」（失敗回 None，不影響本體的結果）。"""
    from synox.update import signing
    kind = install_kind(root) if root else "zip"
    result = CheckResult(status="error", installed=installed, kind=kind, checked_at=clock())
    try:
        rel = fetch_latest(opener)
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
            result.signed = bool(rel.asset(signing.SIG_ASSET) and rel.asset(signing.MANIFEST_ASSET)
                                 and signing.public_keys(keys))
    if tools is not None:
        try:
            result.tools_newer = tools()
        except Exception:                                   # 工具庫查不到不影響本體的結果
            logging.info("[UPDATE] tool library check failed", exc_info=True)
            result.tools_newer = None
    return result


def tools_newer_count(installed: Dict[str, str], opener=None) -> int:
    """工具庫（官方清單，跟「載入工具清單」同一份）裡比裝著的新的工具有幾個。"""
    from synox.packs import catalog
    lib = catalog.fetch_library(opener=opener)
    return sum(1 for c in catalog.cards(lib, installed) if c.get("newer"))


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
    return f"{head}：{result.installed} → {result.latest}\n" + "\n".join(result.lines()[1:])


def weekly_tick(data_dir: str, raw_config: Optional[dict], notify: Callable[[str], None], *,
                installed: str = __version__, root: str = "", opener: Optional[Opener] = None,
                clock=time.time) -> str:
    """runtime 每幾小時叫一次：沒打開每週檢查＝什麼都不做（不連網）；打開了、距離上次 ≥ 7 天才查。
    查到新版：同一個版本只通知擁有者一次（Telegram／Discord＋網頁的橫幅）。回一句給任務狀態看的字。"""
    if not weekly_enabled(raw_config):
        return "沒有打開每週檢查"
    state = load_state(data_dir)
    now = clock()
    if not due(state, now):
        return "這週查過了"
    result = check(installed, root=root, opener=opener, clock=clock)
    state = remember(data_dir, result)
    if result.status != "newer":
        return "沒有新版" if result.status != "error" else "這次沒查成（下週再試）"
    if state.get("notified") == result.latest:
        return f"有新版 {result.latest}（已經通知過）"
    try:
        notify(notice_text(result))
    except Exception:
        logging.exception("[UPDATE] notify failed")
    state["notified"] = result.latest
    save_state(data_dir, state)
    return f"有新版 {result.latest}（通知了擁有者）"
