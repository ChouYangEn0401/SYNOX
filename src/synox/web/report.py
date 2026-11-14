"""
「遇到問題？」（網頁 設定 → 🙋 遇到問題？；畫面在 static/app.html 的 #set-help、動作在 static/report.js）。

鼓勵遇到問題的人到 GitHub 開一張問題單。SYNOX 只幫忙**整理一份安全的摘要**給人看、讓人自己改；
**SYNOX 自己不連網、不送出任何東西**：開 GitHub 是使用者自己按的連結（摘要放在網址參數裡，太長就複製到剪貼簿）。

    POST /api/report                (CSRF＋Origin，跟其他 API 一樣) → {"full", "summary", "issue": {...}}

- 擁有者：SYNOX／Python／作業系統版本、個人版或伺服器版、AI 的 kind、哪些聊天通道有設定、裝了哪些工具（名字＋版本）、
  最近的錯誤或警告（記憶體裡最後幾行，見 RecentLog）。
- 其他人（伺服器版的成員、訪客）：只有 SYNOX 版本和「伺服器版」。這台的設定、工具、錯誤紀錄都不給。
- 遮罩（scrub）：保管箱裡存的每個值、看起來像 token 的樣式（packs/kit.TOKEN_PATTERNS，跟 log 遮罩同一份）、
  網址裡的 /bot<token>、帳密、查詢字串、email、7 位數以上的數字（Telegram／Discord 的 id）、
  SYNOX 資料夾 → <SYNOX 資料夾>、使用者資料夾（C:\\Users\\<名字>、/home/<名字>）→ %USERPROFILE%。
- 對話內容：會帶人打的字或 AI 參數的 log 行（[ROUTE]／[AGENT]…）整行不收；INFO 以下不收；
  例外只記型別與檔名:行號，不記例外的訊息。
"""

from __future__ import annotations

import logging
import os
import platform
import re
import threading
import time
from collections import deque
from typing import Deque, Iterable, List, Optional

from synox import __version__
from synox.packs.kit import TOKEN_LOG_PREFIXES, mask_tokens

REPO = "https://github.com/ChouYangEn0401/SYNOX"
ISSUE_NEW = REPO + "/issues/new"
ISSUES = REPO + "/issues"
SECURITY = REPO + "/security/policy"                    # SECURITY.md（安全問題私下寄信，不開公開 issue）
SIGNUP = "https://github.com/signup"
GUIDE = "https://claude.ai/artifact/96iWvykYyUfAC5pkYUrC6F"   # 一步一步的圖文教學（也在 .github/ISSUE_TEMPLATE/config.yml）
ISSUE_TEMPLATE = "problem.yml"                          # .github/ISSUE_TEMPLATE/problem.yml
SUMMARY_FIELD = "summary"                               # 那張表單裡「SYNOX 幫你準備的回報內容」的 id（網址參數預填）
MAX_URL = 6000                                          # 整個網址的上限（GitHub 大約 8 KB 就拒絕；留餘裕）

LOG_KEEP = 60                                           # 記憶體裡留幾筆（不寫檔）
LOG_SHOW = 15                                           # 摘要裡最多幾行
LINE_MAX = 240                                          # 每行最多幾個字
SKIP_PREFIXES = tuple(TOKEN_LOG_PREFIXES) + ("[ROOM-AI]", "[MOTHER]", "[SOUL]")   # 這幾種會帶對話內容：整行不收

MODE_TEXT = {"personal": "個人版", "server": "伺服器版"}


# ── 最近的錯誤（記憶體裡的環形緩衝；SYNOX 的 log 只印在視窗裡，沒有 log 檔）──────────────

class RecentLog(logging.Handler):
    """root logger 上的一個 handler：只留 WARNING 以上、最後 LOG_KEEP 筆（時間、等級、第一行訊息、例外的型別與位置）。
    收的時候先做一次不需要 app 的遮罩（token 樣式、路徑），產生摘要時再遮一次（加上保管箱裡的值）。"""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: Deque[tuple] = deque(maxlen=LOG_KEEP)
        self._guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return
        message = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
        if not message or message.startswith(SKIP_PREFIXES):
            return
        where = ""
        if record.exc_info and record.exc_info[0] is not None:
            tb = record.exc_info[2]
            while tb is not None and tb.tb_next is not None:
                tb = tb.tb_next
            spot = f"，{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}" if tb is not None else ""
            where = f"（{record.exc_info[0].__name__}{spot}）"
        line = scrub(message[:LINE_MAX * 2])[:LINE_MAX] + where
        with self._guard:
            self.records.append((record.created, record.levelname, line))

    def clear(self) -> None:
        with self._guard:
            self.records.clear()

    def snapshot(self) -> List[tuple]:
        with self._guard:
            return list(self.records)


_RECENT = RecentLog()


def recent_log() -> RecentLog:
    return _RECENT


def install_log_buffer() -> None:
    """把 RecentLog 掛到 root logger（WebUI 建立時叫；重複叫沒關係）。"""
    root = logging.getLogger()
    if _RECENT not in root.handlers:
        root.addHandler(_RECENT)


def recent_lines(secrets: Iterable[str] = ()) -> List[str]:
    """摘要用的最後 LOG_SHOW 行（連續重複的合成一行「（重複 N 次）」），每行再遮一次。"""
    folded: List[list] = []
    for created, level, line in _RECENT.snapshot():
        if folded and folded[-1][2] == line and folded[-1][1] == level:
            folded[-1][0] = created
            folded[-1][3] += 1
        else:
            folded.append([created, level, line, 1])
    out = []
    for created, level, line, n in folded[-LOG_SHOW:]:
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(created))
        out.append(f"{stamp} {level} {scrub(line, secrets=secrets)}" + (f"（重複 {n} 次）" if n > 1 else ""))
    return out


# ── 遮罩 ─────────────────────────────────────────────────────────────

_URL_BOT = re.compile(r"(/bot)[^/\s]+", re.I)                                   # api.telegram.org/bot<token>/…
_URL_AUTH = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", re.I)     # scheme://帳號:密碼@
_URL_QUERY = re.compile(r"(\bhttps?://[^\s?#\"']+)\?[^\s\"']*", re.I)            # 查詢字串常帶 token
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LONG_NUMBER = re.compile(r"(?<![\w.])\d{7,}(?![\w.])")                          # Telegram／Discord 的 id
_USER_DIRS = [
    re.compile(r"\b[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+[^\\/\s\"':;,]+", re.I),   # Windows
    re.compile(r"(?<![\w.])/(?:home|Users)/[^/\s\"':;,]+"),                                         # Linux／macOS
    re.compile(r"(?<![\w.])/root(?=/|\b)"),
]


def _path_pattern(path: str) -> Optional["re.Pattern"]:
    parts = [p for p in re.split(r"[\\/]+", path or "") if p]
    if len(parts) < 2 and not (len(parts) == 1 and len(parts[0]) > 3):
        return None                                   # 「C:」或「/」這種太短的不換（會換掉太多）
    lead = r"[\\/]+" if re.match(r"^[\\/]", path) else ""
    return re.compile(lead + r"[\\/]+".join(re.escape(p) for p in parts) + r"(?![^\\/\s\"':;,])", re.I)


def scrub(text: str, *, secrets: Iterable[str] = (), root: Optional[str] = None,
          home: Optional[str] = None) -> str:
    """要給人貼到公開網站的字：拿掉密鑰、token、帳密、id、email、有使用者名稱的路徑。
    root／home 沒給＝這台的 SYNOX 資料夾、使用者資料夾（""＝不換）。"""
    text = str(text or "")
    for s in sorted({s.strip() for s in secrets if isinstance(s, str) and len(s.strip()) >= 6}, key=len, reverse=True):
        text = text.replace(s, "***")
    text = mask_tokens(text)
    text = _URL_BOT.sub(r"\1***", text)
    text = _URL_AUTH.sub(r"\1***@", text)
    text = _URL_QUERY.sub(r"\1?***", text)
    if root is None:
        from synox.config import ROOT as root
    if home is None:
        home = os.path.expanduser("~")
    for path, label in ((root, "<SYNOX 資料夾>"), (home, "%USERPROFILE%")):
        pattern = _path_pattern(path)
        if pattern is not None:
            text = pattern.sub(lambda _m, label=label: label, text)
    for pattern in _USER_DIRS:
        text = pattern.sub("%USERPROFILE%", text)
    text = _EMAIL.sub("<email>", text)
    return _LONG_NUMBER.sub("<數字>", text)


# ── 摘要 ─────────────────────────────────────────────────────────────

def _os_line() -> str:
    system, release, version = platform.system(), platform.release(), platform.version()
    if system == "Windows":
        return f"Windows {release}（{version}）"
    return f"{system} {release}".strip() or "不知道"


def secret_values(app, config) -> List[str]:
    """要遮掉的值：保管箱、pack 的帳密、config 裡 env: 指到的（agent/room.stored_secrets，跟頻道 AI 的遮罩同一份）
    ＋config 裡名字像密鑰的欄位（token、key、secret、password）。讀不到的就略過。"""
    out: List[str] = []
    try:
        from synox.agent.room import stored_secrets
        out += stored_secrets(app)
    except Exception:
        logging.warning("[REPORT] could not read stored secrets for masking")

    def walk(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str) and any(s in key.lower() for s in ("token", "key", "secret", "password")):
            out.append(value)
    walk(getattr(config, "raw", None) or {})
    token = getattr(config, "bot_token", "")
    if isinstance(token, str) and token:
        out.append(token)
    return out


def summary(app, config, *, full: bool, packs=(), log_lines: Optional[List[str]] = None,
            secrets: Iterable[str] = ()) -> str:
    """給人看、可以自己改、再貼到 GitHub 的那一段字。full=False（不是擁有者）＝只有版本。"""
    mode = getattr(config, "mode", "personal")
    if not full:
        return "\n".join([
            "【SYNOX 回報摘要】（成員版：只有版本。這台 SYNOX 的設定、工具和錯誤紀錄只有擁有者看得到）",
            f"SYNOX 版本：{__version__}",
            f"用法：{MODE_TEXT.get(mode, mode)}（我不是擁有者）",
        ])
    llm = dict(getattr(config, "llm", None) or {})
    kind = str(llm.get("kind") or "none")
    from synox.llm.local import DEFAULT_URLS
    server = llm.get("server") if kind == "local" and llm.get("server") in DEFAULT_URLS else ""
    channels = (["Telegram"] if getattr(config, "has_token", False) else []) + \
        (["Discord"] if getattr(config, "discord_enabled", False) else []) + ["網頁"]
    tools = []
    for item in packs:
        mark = "" if item.status in ("loaded", "connector") else f"（{item.status}）"
        tools.append(f"{item.name} {item.version or '?'}{mark}".strip())
    lines = [
        "【SYNOX 回報摘要】（SYNOX 自動整理：token、金鑰、對話內容、有使用者名稱的路徑都拿掉了）",
        f"SYNOX 版本：{__version__}",
        f"作業系統：{_os_line()}",
        f"Python：{platform.python_version()}",
        f"用法：{MODE_TEXT.get(mode, mode)}",
        f"AI：{kind}" + (f"（{server}）" if server else ""),
        f"聊天通道：{'、'.join(channels)}",
        f"裝了的工具（{len(tools)} 個）：" + ("、".join(tools) if tools else "沒有"),
        f"最近的錯誤或警告（最多 {LOG_SHOW} 行）：",
    ]
    errors = log_lines if log_lines is not None else recent_lines(secrets)
    lines += ["  " + ln for ln in errors] or ["  （這次開 SYNOX 之後沒有）"]
    return scrub("\n".join(lines), secrets=secrets)


def issue_info() -> dict:
    return {"url": ISSUE_NEW, "template": ISSUE_TEMPLATE, "field": SUMMARY_FIELD, "max_url": MAX_URL}
