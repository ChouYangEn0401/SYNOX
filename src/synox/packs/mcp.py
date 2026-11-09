"""
kind=mcp、mcp.transport=stdio（SDK P4a）：SYNOX 開一個子程序跑 MCP 伺服器，用 stdio 講 JSON-RPC 2.0（一行一個訊息）。

    pack.json  "kind": "mcp", "capabilities": ["subprocess"],
               "mcp": {"transport": "stdio", "argv": ["{python}", "./server.py"], "env": {…}, "cwd": ".",
                       "timeout": 60, "start_timeout": 20,
                       "tools_allow": ["search"], "effects": {"search": "READ"}}

**協定子集**（只用標準函式庫）：initialize → notifications/initialized → tools/list（可分頁）→ tools/call；ping 兩邊都回。
伺服器問 SYNOX 別的（roots、sampling…）一律回 -32601。stdout 只能是 JSON-RPC：印了一行不是 JSON 的東西＝壞了，
這個程序收掉，正在等的呼叫回一句人話；逾時、程序中途結束也一樣。下一次呼叫重新啟動。都不會卡住 bot
（人打字的跑在 app.tasks；經 AI 的本來就在 AI 那一輪的執行緒上）。

**程序模型**：McpPool。每個 (pack, 使用者) 一個長駐子程序（Scope＝PerUserScope，預設、最安全：SYNOX_USER_DATA_DIR、
secret 都是那個人的）；第一次呼叫才啟動；閒置 IDLE_SECONDS（10 分鐘）回收；崩潰了下次呼叫重啟；bot 關閉（app.on_stop）
全部收掉。Windows 上每個子程序放進自己的 Job Object（KILL_ON_JOB_CLOSE，照 isdtelekit.jobs.runner：先 suspended 開、
放進 Job 再放行），SYNOX 掛了子程序也跟著結束；其他平台開新的 session、收的時候整組 killpg。
啟動的 argv／env 照 kind=cli：樣板代換（loader.placeholders）、SYNOX_* 環境（loader.context_env）、auth.fields 的 secret
（只走環境變數）、clean_env 拿掉像密鑰的變數（requires.env／auth.fields[].env 例外），最後過 synox/sandbox.py 的
box.wrap(grants)。env 的指紋（含 secret）變了 → 下一次呼叫換一個新程序（使用者改了「連接」的值就生效）。
SharedScope（全部人共用一個程序）只有介面、還沒做：伺服器版要共用還是一人一個，擁有者還沒決定。

**工具 → 指令**：tools_allow 的每一個工具在載入時就掛成群組底下的葉節點（沒列的工具不存在，伺服器列了也一樣）；
指令名＝工具名轉成合法指令（小寫英數字、_）。說明、欄位來自 tools/list（第一次啟動時讀，存 data/mcp/<pack>.tools.json，
之後載入先用存的）：inputSchema 的 string→text、integer→int、number→number、boolean→bool、enum→choice；
巢狀 object／array 暫不給（doctor 列出來；是必填的話這個工具不給 AI、人打也不能跑）。
**effect 一律來自 pack.json 的 mcp.effects**（工具自述的 annotations 不算），沒寫的當 DANGER。
呼叫仍走 policy.decide、第 4 關（validate.check_call）、DANGER 核准卡、結果包 nonce 分隔符（agent/loop.py）。
工具回 structuredContent.needs_confirm → 核准卡（packs/confirm.py 的一次性憑證）→ 按 ✅ 用同一組參數、
params._meta["synox/confirm_token"]＝工具給的 token 重叫一次（AI 碰不到 _meta）。

**連法（Backend）**：上面這些（工具→指令、欄位、effect、policy、第 4 關、核准卡、needs_confirm、結果遮掉 secret）
是 install() 的共用部分，不管怎麼連。連法只管「這個人怎麼連」與「開一條還沒 initialize 的連線」：
StdioBackend（這支檔案，子程序）、HttpBackend（packs/mcp_http.py，遠端 MCP、Streamable HTTP，P4b）。
池、閒置回收、handshake、tools/list 快取兩種共用。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple

PROTOCOL_VERSION = "2025-06-18"
CONFIRM_META = "synox/confirm_token"
DEFAULT_TIMEOUT = 60.0
DEFAULT_START_TIMEOUT = 20.0
IDLE_SECONDS = 600.0
REAP_EVERY = 30.0
MAX_LINE = 4 * 1024 * 1024
MAX_TEXT = 3500
SUMMARY_MAX = 200
ASK_MAX = 60
MAX_FIELDS = 20
MAX_PAGES = 10
CACHE_DIR = "mcp"

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_COMMAND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class McpError(Exception):
    """給人看的一句話。fatal=True：這個程序／連線不能再用了（逾時、壞 JSON、結束了、寫不進去）→ 收掉，下次呼叫重啟。
    retry=True（只有 http 的連線過期）：收掉之後馬上重新連一次再試。"""

    def __init__(self, message: str, *, fatal: bool = False, retry: bool = False):
        super().__init__(message)
        self.message = str(message)
        self.fatal = fatal or retry
        self.retry = retry


def _snip(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ── 子程序 ─────────────────────────────────────────────────────────────

class Proc:
    """一個 MCP 伺服器子程序：stdin／stdout 是 PIPE（bytes），stderr 寫進 log 檔。"""

    def __init__(self, popen: subprocess.Popen, job=None, log_path: str = ""):
        self.popen = popen
        self.job = job
        self.log_path = log_path

    @property
    def pid(self) -> int:
        return self.popen.pid

    @property
    def stdin(self):
        return self.popen.stdin

    @property
    def stdout(self):
        return self.popen.stdout

    def poll(self) -> Optional[int]:
        return self.popen.poll()

    def stderr_tail(self, n: int = 400) -> str:
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - n))
                return f.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""

    def kill(self, grace: float = 0.0) -> None:
        """grace 秒內先讓它自己結束（關 stdin＝MCP 的正常收尾），還在就整組收掉。"""
        p = self.popen
        if grace and p.poll() is None:
            try:
                p.stdin.close()
            except Exception:
                pass
            try:
                p.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
        if self.job is not None:
            self.job.terminate()
        elif p.poll() is None and os.name != "nt":
            try:
                os.killpg(p.pid, 9)  # type: ignore[attr-defined]
            except OSError:
                pass
        if p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logging.error("[MCP] pid %s did not exit after kill", p.pid)
        if self.job is not None:
            self.job.close()
            self.job = None
        for stream in (p.stdin, p.stdout):
            try:
                stream.close()
            except Exception:
                pass


def spawn(argv: List[str], *, env: Dict[str, str], cwd: str, log_path: str) -> Proc:
    """開子程序（不經 shell、不開視窗）。Windows：suspended 開 → 放進 KILL_ON_JOB_CLOSE 的 Job Object → 放行
    （isdtelekit.jobs.runner 的做法：SYNOX 結束，Job 的 handle 一關，整棵程序樹跟著結束）。叫不起來丟 OSError。"""
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a list, never a shell string")
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    kwargs: Dict[str, Any] = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd, env=env, shell=False)
    with open(log_path, "wb") as err:
        kwargs["stderr"] = err
        if sys.platform == "win32":
            from isdtelekit.jobs.runner import _CREATE_SUSPENDED, _WinJob
            job = _WinJob(kill_on_close=True)
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | _CREATE_SUSPENDED
            try:
                popen = subprocess.Popen([str(a) for a in argv], **kwargs)
            except BaseException:
                job.close()
                raise
            job.adopt(popen)
            return Proc(popen, job, log_path)
        kwargs["start_new_session"] = True
        return Proc(subprocess.Popen([str(a) for a in argv], **kwargs), None, log_path)


# ── JSON-RPC session ──────────────────────────────────────────────────

class _Waiter:
    __slots__ = ("event", "result", "error", "dead")

    def __init__(self):
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[dict] = None
        self.dead: Optional[str] = None


class Session:
    """一個子程序上的 MCP 連線。request() 可以從好幾條執行緒同時叫（id 對回應）。"""

    def __init__(self, proc, *, name: str = "mcp", clock: Callable[[], float] = time.monotonic):
        self.proc = proc
        self.name = name
        self.clock = clock
        self.last_used = clock()
        self.fingerprint = ""
        self.tools: Dict[str, dict] = {}
        self.server_info: dict = {}
        self.dead: Optional[str] = None
        self.busy = 0
        self._ids = itertools.count(1)
        self._pending: Dict[int, _Waiter] = {}
        self._lock = threading.Lock()
        self._write = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name=f"mcp-{name}")
        self._reader.start()

    # 收

    def _read_loop(self) -> None:
        stream = self.proc.stdout
        try:
            while True:
                line = stream.readline(MAX_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_LINE:
                    self._fail("工具伺服器回了一行太長的訊息（超過 4 MB），收掉了")
                    return
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except ValueError:
                    self._fail(f"工具伺服器回了看不懂的東西（不是 JSON：{_snip(text)}）")
                    return
                if not isinstance(msg, dict):
                    self._fail("工具伺服器回了不是 JSON-RPC 物件的東西")
                    return
                self._dispatch(msg)
        except Exception as e:                    # 讀的時候管線斷了
            if self.dead is None:
                self._fail(f"讀工具伺服器的回應失敗：{type(e).__name__}")
            return
        if self.dead is None:
            code = None
            try:
                code = self.proc.popen.wait(timeout=2) if hasattr(self.proc, "popen") else self.proc.poll()
            except Exception:
                pass
            tail = self.proc.stderr_tail() if hasattr(self.proc, "stderr_tail") else ""
            if tail:
                logging.warning("[MCP] %s exited (%s); stderr tail: %s", self.name, code, tail[-300:])
            self._fail(f"工具伺服器中途結束了（結束碼 {code if code is not None else '不明'}）")

    def _dispatch(self, msg: dict) -> None:
        if "method" in msg:                       # 伺服器 → SYNOX
            if "id" in msg:
                if msg.get("method") == "ping":
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}}, quiet=True)
                else:
                    self._send({"jsonrpc": "2.0", "id": msg["id"],
                                "error": {"code": -32601, "message": f"Method not found: {msg.get('method')}"}},
                               quiet=True)
            return                                # 通知（logging、list_changed…）不處理
        with self._lock:
            waiter = self._pending.pop(msg.get("id"), None) if isinstance(msg.get("id"), int) else None
        if waiter is None:
            return
        if isinstance(msg.get("error"), dict):
            waiter.error = msg["error"]
        else:
            waiter.result = msg.get("result")
        waiter.event.set()

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self.dead is not None:
                return
            self.dead = reason
            waiting, self._pending = list(self._pending.values()), {}
        for w in waiting:
            w.dead = reason
            w.event.set()
        try:
            self.proc.kill()
        except Exception:
            logging.exception("[MCP] kill %s failed", self.name)

    # 送

    def _send(self, msg: dict, quiet: bool = False) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._write:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            reason = "工具伺服器已經關了（寫不進去）"
            self._fail(reason)
            if not quiet:
                raise McpError(self.dead or reason, fatal=True)

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def request(self, method: str, params: Optional[dict] = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
        """回 result（一定是 dict）。伺服器回 error（不收掉）／逾時、壞 JSON、結束了（收掉）都丟 McpError。"""
        if self.dead is not None:
            raise McpError(self.dead, fatal=True)
        rid = next(self._ids)
        waiter = _Waiter()
        with self._lock:
            self._pending[rid] = waiter
            self.busy += 1
        try:
            msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                msg["params"] = params
            self._send(msg)
            if not waiter.event.wait(timeout):
                with self._lock:
                    self._pending.pop(rid, None)
                self._fail(f"超過 {timeout:g} 秒沒有回應（{method}），已經停掉")
                raise McpError(f"超過 {timeout:g} 秒沒有回應，已經停掉", fatal=True)
        finally:
            with self._lock:
                self.busy -= 1
            self.last_used = self.clock()
        if waiter.dead is not None:
            raise McpError(waiter.dead, fatal=True)
        if waiter.error is not None:
            err = waiter.error
            raise McpError(f"工具伺服器回了錯誤：{_snip(err.get('message') or '沒有說明', 200)}"
                           f"（代碼 {err.get('code')}）")
        if not isinstance(waiter.result, dict):
            raise McpError("工具伺服器回的結果不是物件")
        return waiter.result

    def close(self, grace: float = 1.0) -> None:
        with self._lock:
            already = self.dead is not None
            if not already:
                self.dead = "已經關閉"
            waiting, self._pending = list(self._pending.values()), {}
        for w in waiting:
            w.dead = "已經關閉"
            w.event.set()
        try:
            if already:                            # 已經壞掉的（_fail 收過了）：確認收乾淨
                self.proc.kill()
            else:                                  # 正常收尾：先關 stdin 給它 grace 秒自己結束
                self.proc.kill(grace)
        except Exception:
            logging.exception("[MCP] close %s failed", self.name)

    @property
    def alive(self) -> bool:
        return self.dead is None


def handshake(session: Session, timeout: float) -> Dict[str, dict]:
    """initialize → notifications/initialized → tools/list（跟著 nextCursor 最多 MAX_PAGES 頁）。回 {工具名: spec}。"""
    from synox import __version__
    init = session.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                          "clientInfo": {"name": "synox", "version": __version__}}, timeout)
    info = init.get("serverInfo")
    session.server_info = info if isinstance(info, dict) else {}
    session.notify("notifications/initialized")
    tools: Dict[str, dict] = {}
    cursor = None
    for _ in range(MAX_PAGES):
        page = session.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
        for t in page.get("tools") or []:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                tools[t["name"]] = t
        cursor = page.get("nextCursor")
        if not isinstance(cursor, str) or not cursor:
            break
    session.tools = tools
    return tools


# ── 程序範圍（策略） ──────────────────────────────────────────────────

class Scope:
    """誰跟誰共用一個 MCP 伺服器程序。key(pack, user)：同一個 key＝同一個程序；identity(user)：代換與 SYNOX_* 用誰。"""
    name = ""

    def key(self, pack: str, user) -> Hashable:          # pragma: no cover - 介面
        raise NotImplementedError

    def identity(self, user):                            # pragma: no cover - 介面
        raise NotImplementedError


class PerUserScope(Scope):
    """預設：每個 (pack, 使用者) 一個程序。SYNOX_USER_DATA_DIR、secret 都是那個人的；別人的程序看不到。"""
    name = "per-user"

    def key(self, pack: str, user) -> Hashable:
        return (pack, getattr(user, "tg_id", None))

    def identity(self, user):
        return user


SHARED_TODO = ("mcp 的 shared 程序範圍還沒做（只有介面）：全部人共用一個程序時，SYNOX_USER_DATA_DIR、secret 要改成"
               "每次呼叫帶（MCP 沒有標準欄位），伺服器版要先決定一人一個還是共用。")


class SharedScope(Scope):
    """（預留）每個 pack 一個程序、全部人共用。還沒做。"""
    name = "shared"

    def key(self, pack: str, user) -> Hashable:
        raise NotImplementedError(SHARED_TODO)

    def identity(self, user):
        raise NotImplementedError(SHARED_TODO)


SCOPES = {"per-user": PerUserScope, "shared": SharedScope}


# ── 程序池 ─────────────────────────────────────────────────────────────

class McpPool:
    """app.extras["synox_mcp_pool"]。clock 可以換（測試用假時鐘＋直接呼叫 reap()）；spawner 可以換（測試記 argv／env）。"""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, idle: float = IDLE_SECONDS,
                 scope: Optional[Scope] = None, spawner: Callable[..., Any] = spawn, reap_every: float = REAP_EVERY,
                 background: bool = True):
        self.clock = clock
        self.idle = float(idle)
        self.scope = scope or PerUserScope()
        self.spawner = spawner
        self.reap_every = reap_every
        self.background = background
        self._sessions: Dict[Hashable, Session] = {}
        self._key_locks: Dict[Hashable, threading.Lock] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reaper: Optional[threading.Thread] = None
        self.started = 0                          # 開過幾個程序（測試、doctor）

    def _key_lock(self, key) -> threading.Lock:
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def session(self, key: Hashable, start: Callable[[], Session], fingerprint: str = "") -> Session:
        """這個 key 的程序；沒有、死了、或 env 指紋變了就（重新）開一個。start() 失敗丟 McpError。"""
        with self._key_lock(key):
            with self._lock:
                found = self._sessions.get(key)
            if found is not None and (not found.alive or found.fingerprint != fingerprint):
                self.drop(key, found)
                found = None
            if found is None:
                found = start()
                found.fingerprint = fingerprint
                with self._lock:
                    self._sessions[key] = found
                    self.started += 1
                self._ensure_reaper()
            found.last_used = self.clock()
            return found

    def drop(self, key: Hashable, session: Optional[Session] = None) -> None:
        with self._lock:
            current = self._sessions.get(key)
            if current is None or (session is not None and current is not session):
                current = session
            else:
                self._sessions.pop(key, None)
        if current is not None:
            current.close()

    def get(self, key: Hashable) -> Optional[Session]:
        with self._lock:
            return self._sessions.get(key)

    def keys(self) -> List[Hashable]:
        with self._lock:
            return list(self._sessions)

    def reap(self) -> int:
        """收掉閒置超過 idle 秒（而且沒有呼叫在跑）或已經死掉的程序。回收了幾個。"""
        now = self.clock()
        with self._lock:
            victims = [(k, s) for k, s in self._sessions.items()
                       if not s.alive or (s.busy == 0 and now - s.last_used >= self.idle)]
            for k, _s in victims:
                self._sessions.pop(k, None)
        for _k, s in victims:
            s.close()
        if victims:
            logging.info("[MCP] reaped %d idle session(s)", len(victims))
        return len(victims)

    def close_all(self) -> None:
        self._stop.set()
        with self._lock:
            sessions, self._sessions = list(self._sessions.values()), {}
        for s in sessions:
            s.close()

    def _ensure_reaper(self) -> None:
        if not self.background:
            return
        with self._lock:
            if self._reaper is not None and self._reaper.is_alive():
                return
            self._stop.clear()
            self._reaper = threading.Thread(target=self._reap_loop, daemon=True, name="mcp-reaper")
            self._reaper.start()

    def _reap_loop(self) -> None:
        while not self._stop.wait(self.reap_every):
            try:
                self.reap()
            except Exception:
                logging.exception("[MCP] reap failed")


def pool_of(app) -> McpPool:
    found = app.extras.get("synox_mcp_pool")
    if found is None:
        found = app.extras["synox_mcp_pool"] = McpPool()
        app.on_stop.append(lambda a: found.close_all())          # bot 關閉，全部的 MCP 程序跟著收
    return found


# ── 工具 → 指令、inputSchema → fields ──────────────────────────────────

def to_identifier(name: str, prefix: str = "t", max_len: int = 32) -> str:
    """"getWeather"、"search-docs"、"2fa" → get_weather、search_docs、t_2fa（小寫英數字、_，英文字母開頭）。"""
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", str(name or ""))
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    if not s or not s[0].isalpha():
        s = f"{prefix}_{s}" if s else prefix
    return s[:max_len].rstrip("_") or prefix


def unique_identifiers(names: List[str], prefix: str = "t", max_len: int = 32) -> Dict[str, str]:
    out: Dict[str, str] = {}
    used = set()
    for name in names:
        base = to_identifier(name, prefix, max_len)
        candidate, n = base, 2
        while candidate in used:
            tail = f"_{n}"
            candidate = base[:max_len - len(tail)].rstrip("_") + tail
            n += 1
        used.add(candidate)
        out[name] = candidate
    return out


@dataclass
class FieldSpec:
    name: str                   # SYNOX 的欄位名（kit.parse_args、AI 看到的）
    prop: str                   # inputSchema 的原名（tools/call 的 arguments 用）
    kind: str                   # text｜int｜number｜bool｜choice
    required: bool = False
    ask: str = ""
    choices: Tuple[str, ...] = ()
    enum: Tuple[Any, ...] = ()  # choice 的原值（可能是數字）
    default: str = ""


@dataclass
class ToolShape:
    tool: str                   # MCP 的工具名
    command: str                # SYNOX 的指令名
    summary: str = ""
    fields: List[FieldSpec] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    callable: bool = True       # 有不支援的必填欄位＝False
    known: bool = False         # 讀過 tools/list 了
    missing: bool = False       # 讀過了，伺服器卻沒有這個工具


def clean_text(text: Any, limit: int) -> str:
    """工具自述的說明：拿掉控制字元、只留第一段、截短（是第三方的字，進 /help 與 AI 的工具說明）。"""
    text = _CONTROL.sub(" ", str(text or "")).strip()
    text = text.split("\n\n")[0].replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _json_type(p: dict) -> str:
    t = p.get("type")
    if isinstance(t, list):
        rest = [x for x in t if x != "null"]
        t = rest[0] if len(rest) == 1 else None
    return t if isinstance(t, str) else ""


_KINDS = {"string": "text", "integer": "int", "number": "number", "boolean": "bool"}


def shape_of(tool: str, command: str, spec: Optional[dict]) -> ToolShape:
    """tools/list 的一項（或 None＝還不知道）→ ToolShape。"""
    shape = ToolShape(tool, command)
    if spec is None:
        shape.summary = f"MCP 工具 {tool}（第一次用時會啟動工具伺服器、讀參數說明）"
        return shape
    shape.known = True
    shape.summary = clean_text(spec.get("description") or spec.get("title") or "", SUMMARY_MAX) or f"MCP 工具 {tool}"
    schema = spec.get("inputSchema")
    if schema is None:
        return shape
    if not isinstance(schema, dict) or (schema.get("type") not in (None, "object")):
        shape.notes.append(f"{tool}：inputSchema 不是物件，不給參數")
        return shape
    props = schema.get("properties") or {}
    required = set(schema.get("required") or []) if isinstance(schema.get("required"), list) else set()
    if not isinstance(props, dict):
        props = {}
    names = unique_identifiers([str(k) for k in props], prefix="f")
    for prop, p in props.items():
        prop = str(prop)
        is_required = prop in required
        if not isinstance(p, dict):
            p = {}
        kind, choices, enum = _KINDS.get(_json_type(p), ""), (), ()
        values = p.get("enum")
        if isinstance(values, list) and values and len(values) <= 50 and \
                all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in values):
            kind, enum = "choice", tuple(values)
            choices = tuple(str(v) for v in values)
        if not kind:
            what = _json_type(p) or "沒寫型別"
            shape.notes.append(f"{tool}.{prop}：{what} 欄位這一版不支援（巢狀物件／陣列要等 schema 模式），不給 AI"
                               + ("；它是必填的，所以整個工具不能用" if is_required else ""))
            if is_required:
                shape.callable = False
            continue
        if len(shape.fields) >= MAX_FIELDS:
            shape.notes.append(f"{tool}.{prop}：欄位超過 {MAX_FIELDS} 個，後面的不給")
            if is_required:
                shape.callable = False
            continue
        default = p.get("default")
        default = ("true" if default else "false") if isinstance(default, bool) else \
            (str(default) if isinstance(default, (str, int, float)) else "")
        ask = clean_text(p.get("description") or p.get("title") or prop, ASK_MAX) or prop
        shape.fields.append(FieldSpec(names[prop], prop, kind, is_required, ask, choices, enum, default))
    return shape


def to_arguments(shape: ToolShape, values: Dict[str, str]) -> Dict[str, Any]:
    """檢查、整理過的欄位值（字串）→ tools/call 的 arguments（JSON 型別、原本的屬性名）。"""
    out: Dict[str, Any] = {}
    for f in shape.fields:
        raw = values.get(f.name)
        if raw is None or not str(raw).strip():
            continue
        v = str(raw).strip()
        if f.kind == "int":
            out[f.prop] = int(v)
        elif f.kind == "number":
            num = float(v)
            out[f.prop] = int(num) if num.is_integer() and re.fullmatch(r"[+-]?\d+", v) else num
        elif f.kind == "bool":
            out[f.prop] = v.lower() == "true"
        elif f.kind == "choice":
            out[f.prop] = next((e for e in f.enum if str(e).lower() == v.lower()), v)
        else:
            out[f.prop] = str(raw)
    return out


def needs_confirm_of(result: dict) -> Optional[dict]:
    """tools/call 的 result 是「要確認」（structuredContent.needs_confirm）→ P3 的信封；不是回 None。"""
    sc = result.get("structuredContent")
    if result.get("isError") is True or not isinstance(sc, dict) or sc.get("needs_confirm") is not True:
        return None
    return {"needs_confirm": True, "summary": sc.get("summary") if isinstance(sc.get("summary"), str) else "",
            "confirm_token": sc.get("confirm_token") if isinstance(sc.get("confirm_token"), str) else ""}


def render_result(result: dict) -> Tuple[bool, str]:
    """tools/call 的 result → (成功?, 給人看的字)。text 內容照原樣接起來；其他種類（image、resource…）只說有幾個。"""
    from synox.packs import render
    texts, others = [], []
    for c in result.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
            texts.append(c["text"])
        elif isinstance(c, dict):
            others.append(str(c.get("type") or "?"))
    text = "\n".join(t for t in texts if t.strip()).strip()
    if not text and isinstance(result.get("structuredContent"), dict):
        text = render.render(result["structuredContent"])
    if others:
        text = (text + "\n" if text else "") + f"（另有 {len(others)} 個 {'、'.join(sorted(set(others)))} 內容，SYNOX 不顯示）"
    text = _CONTROL.sub("", text)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT - 1] + "…"
    return result.get("isError") is not True, text


# ── 工具清單的快取（data/mcp/<pack>.tools.json） ─────────────────────────

def cache_path(data_dir: str, name: str) -> str:
    return os.path.join(data_dir, CACHE_DIR, f"{name}.tools.json")


def load_cache(data_dir: str, m) -> Optional[Dict[str, dict]]:
    """上次讀到的 tools/list（只有 tools_allow 裡的）；pack 版本換了就不用。"""
    try:
        with open(cache_path(data_dir, m.name), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != m.version or not isinstance(data.get("tools"), dict):
        return None
    return {k: v for k, v in data["tools"].items() if isinstance(v, dict)}


def save_cache(data_dir: str, m, tools: Dict[str, dict]) -> None:
    from isdtelekit.core import jsonstore
    allow = set((m.mcp or {}).get("tools_allow") or [])
    keep = {k: {"name": k, "description": v.get("description", ""), "inputSchema": v.get("inputSchema")}
            for k, v in tools.items() if k in allow}
    try:
        os.makedirs(os.path.join(data_dir, CACHE_DIR), exist_ok=True)
        jsonstore.save_json(cache_path(data_dir, m.name), {"version": m.version, "tools": keep,
                                                          "listed": sorted(tools)})
    except OSError:
        logging.exception("[MCP] cannot save tool cache for %s", m.name)


def effect_name(m, tool: str) -> str:
    """READ｜WRITE｜DANGER：一律來自 pack.json 的 mcp.effects（工具自述的不算）；沒寫＝DANGER。"""
    from synox.packs.manifest import norm_effect
    return norm_effect(((m.mcp or {}).get("effects") or {}).get(tool)) or "DANGER"


def doctor_notes(m, data_dir: str) -> List[str]:
    """doctor 要印的：pack 外的程式（未鎖定執行環境）、不支援的欄位、伺服器沒列的工具、還沒連過。"""
    from synox.packs.scan import external_programs
    out = [f"⚠️ 未鎖定執行環境：argv 用了 pack 外的程式 {p}（packs.lock 不記它的雜湊）" for p in external_programs(m)]
    if getattr(m, "mcp_http", False):
        from urllib.parse import urlsplit
        out.append(f"ℹ️ 遠端 MCP：只連 {urlsplit(m.mcp.get('url', '')).netloc}（https，不跟著轉址）")
    cached = load_cache(data_dir, m)
    allow = list((m.mcp or {}).get("tools_allow") or [])
    if cached is None:
        out.append("ℹ️ 還沒連過（第一次呼叫才啟動、讀工具清單）")
        return out
    names = unique_identifiers(allow)
    for tool in allow:
        if tool not in cached:
            try:
                with open(cache_path(data_dir, m.name), "r", encoding="utf-8") as f:
                    listed = set(json.load(f).get("listed") or [])
            except (OSError, ValueError):
                listed = set()
            if tool not in listed:
                out.append(f"⚠️ tools_allow 的 {tool}：伺服器上次的 tools/list 沒有這個工具")
            continue
        for note in shape_of(tool, names[tool], cached[tool]).notes:
            out.append(f"⚠️ {note}")
    return out


def redact(text: str, secrets: List[str]) -> str:
    """把這個人存的 secret（8 字以上）從要給人／AI 看的字裡遮掉（伺服器回聲了 token 也不外流）。"""
    for s in sorted({s.strip() for s in secrets if isinstance(s, str) and len(s.strip()) >= 8}, key=len, reverse=True):
        text = text.replace(s, "***")
    return text


# ── 連法（transport）：stdio 的子程序；http 在 packs/mcp_http.py ────────────

class Backend:
    """install() 的共用部分（工具→指令、欄位、policy、第 4 關、核准卡、needs_confirm）不管連法；連法只負責：
    plan(user) → (ctx, 指紋)：這個人要怎麼連（stdio＝代換與環境；http＝token）；指紋變了換一條新連線。
    open(user, ctx) → 還沒 initialize 的 session（有 request／notify／close／alive／busy／last_used）。
    not_connected(user) → 還不能連的原因（""＝可以）。commands(group) → 這種連法自己的指令（http 的 OAuth 登入）。"""
    start_failed = "工具伺服器啟動失敗"
    again = "（下一次呼叫會重新啟動工具伺服器）"

    def plan(self, user) -> Tuple[Any, str]:              # pragma: no cover - 介面
        raise NotImplementedError

    def open(self, user, ctx):                            # pragma: no cover - 介面
        raise NotImplementedError

    def not_connected(self, user) -> str:
        return ""

    def commands(self, group, taken: List[str]) -> None:
        return None


class StdioBackend(Backend):
    """transport=stdio（P4a）：每個 (pack, 使用者) 一個長駐子程序，照 kind=cli 的代換、環境、沙盒。"""

    def __init__(self, app, pack, config, pool: "McpPool"):
        from synox.packs import confirm as tool_confirm
        from synox.packs.manifest import secret_env_names
        self.app, self.pack, self.config, self.pool = app, pack, config, pool
        self.m = pack.manifest
        self.keep_env = list(secret_env_names(self.m)) + list(tool_confirm.ENV_NAMES)
        self.server = getattr(config, "mode", "personal") == "server"

    def plan(self, user):
        """這個人的 ((placeholders, 要加的 env), 指紋)。"""
        from synox.packs import confirm as tool_confirm
        from synox.packs import envs, loader
        m, config, pack = self.m, self.config, self.pack
        who = self.pool.scope.identity(user)
        ph = loader.placeholders(m, config, who)
        env = envs.node_env(m, config.data_dir)
        env.update({k: loader.substitute(v, ph) for k, v in (m.mcp.get("env") or {}).items()})
        env.update(loader.context_env(m, config, ph, pack.secret_fields))
        env.update(tool_confirm.env_for(None))      # MCP 模式的「已確認」只看 _meta，環境變數一律明寫 0
        if pack.secret_fields and pack.secrets is not None:
            env.update(pack.secrets.env_for(m.name, pack.secret_fields, who))
        digest = hashlib.sha256(json.dumps([sorted(env.items()), sorted(ph.items())], ensure_ascii=False)
                                .encode("utf-8")).hexdigest()
        return (ph, env), digest

    def open(self, user, ctx) -> Session:
        from isdtelekit.jobs.cli import clean_env

        from synox import sandbox
        from synox.packs import loader
        m, config = self.m, self.config
        ph, env = ctx
        if self.server:
            os.makedirs(ph["user_data_dir"], exist_ok=True)
        argv = []
        for part in m.mcp["argv"]:
            part = str(part)
            if part.startswith(("./", ".\\")):
                part = os.path.join(m.folder, part[2:])
            argv.append(loader.substitute(part, ph))
        cwd = os.path.normpath(os.path.join(m.folder, loader.substitute(m.mcp.get("cwd") or ".", ph)))
        box = sandbox.sandbox_for(config)                         # PERM-7：照宣告算範圍，交給後端包一層
        g = sandbox.grants_for(m, config, ph, pass_env=self.keep_env)
        if box.name != "none":
            for folder in g.write:
                os.makedirs(folder, exist_ok=True)
        argv2, env2 = box.wrap(argv, env, cwd, g)
        log_path = os.path.join(ph["user_data_dir"], "logs", f"mcp-{m.name}.log")
        try:
            proc = self.pool.spawner(argv2, env=clean_env(env2, keep=self.keep_env), cwd=cwd, log_path=log_path)
        except (OSError, ValueError) as e:
            raise McpError(f"工具伺服器叫不起來：{e}", fatal=True)
        return Session(proc, name=f"{m.name}-{ph.get('tg_id') or 'x'}", clock=self.pool.clock)

    def not_connected(self, user) -> str:
        return missing_secrets(self.pack, user)


def missing_secrets(pack, user) -> str:
    """auth.fields（「連接」表單）還沒填齊的話，一句給人看的話；填齊了或不用填回 ""。"""
    m = pack.manifest
    if not pack.secret_fields:
        return ""
    if pack.secrets is None or not pack.secrets.available:
        return f"🔌 {m.title} 要先連接，但保管箱沒有打開（python -m synox doctor 看原因）。"
    missing = pack.secrets.missing(m.name, pack.secret_fields, user)
    if not missing:
        return ""
    return (f"🔌 {m.title} 還沒連接：缺 {'、'.join(missing)}。"
            f"到網頁介面的工具頁，按這個 pack 的「連接」填（/web 拿登入連結；為了安全，不在聊天裡收）。")


# ── 裝進 app（loader._install_mcp 叫） ─────────────────────────────────

def install(app, pack) -> None:
    from isdtelekit.core.registry import DANGER, READ, WRITE, Field

    from synox.agent import validate as gate4
    from synox.packs import confirm as tool_confirm
    from synox.packs import kit

    m = pack.manifest
    config = pack.config if pack.config is not None else app.config
    pool = pool_of(app)
    grants_book = tool_confirm.grants_of(app)
    allow: List[str] = list(m.mcp.get("tools_allow") or [])
    commands = unique_identifiers(allow)
    effects = {"READ": READ, "WRITE": WRITE, "DANGER": DANGER}
    call_timeout = float(m.mcp.get("timeout") or DEFAULT_TIMEOUT)
    start_timeout = float(m.mcp.get("start_timeout") or DEFAULT_START_TIMEOUT)
    if m.mcp_http:
        from synox.packs import mcp_http
        backend: Backend = mcp_http.HttpBackend(app, pack, config, pool)
    else:
        backend = StdioBackend(app, pack, config, pool)
    meta = app.extras.setdefault("synox_tool_meta", {})
    cached = load_cache(config.data_dir, m) or {}
    shapes: Dict[str, ToolShape] = {t: shape_of(t, commands[t], cached.get(t)) for t in allow}
    nodes: Dict[str, Any] = {}
    pack.mcp_shapes = shapes                     # 測試、doctor 看得到

    def say(api, chat_id, text):
        try:
            api.send_message(chat_id, text)
        except Exception:
            logging.exception("[MCP] reply to %s failed", chat_id)

    def apply(tool: str) -> None:
        shape, node = shapes[tool], nodes.get(tool)
        if node is None:
            return
        fields = tuple(Field(f.name, f.ask, required=f.required, default=f.default, choices=f.choices,
                             check=gate4.typed_check(f.kind, f.choices)) for f in shape.fields)
        node.summary = node.title = shape.summary
        node.fields = fields
        if fields:
            node.usage = kit.usage_of(fields, sum(1 for f in fields if f.required))
        else:                                    # 還沒讀過 tools/list：給 AI 一個 args 字串（第一次呼叫後換成真的欄位）
            node.usage = "" if shape.known else "[參數，照位置或 key=value]"
        node.ai = shape.callable and not shape.missing
        meta[node.path] = {"argv": False, "positional": [], "kinds": {f.name: f.kind for f in shape.fields},
                           "confirm": False}

    def learned(listed: Dict[str, dict]) -> None:
        """一個新程序讀到 tools/list：更新每個葉節點的說明與欄位，存快取。"""
        for tool in allow:
            spec = listed.get(tool)
            shape = shape_of(tool, commands[tool], spec)
            if spec is None:
                shape.known, shape.missing = True, True
                shape.summary = f"MCP 工具 {tool}（伺服器沒有提供這個工具）"
            shapes[tool] = shape
            apply(tool)
        save_cache(config.data_dir, m, listed)

    def start(user, ctx) -> Any:
        session = backend.open(user, ctx)
        try:
            listed = handshake(session, start_timeout)
        except McpError as e:
            session.close(grace=0)
            raise McpError(f"{backend.start_failed}：{e.message}", fatal=True)
        learned(listed)
        return session

    def session_for(user) -> Tuple[Hashable, Any]:
        key = pool.scope.key(m.name, user)
        ctx, digest = backend.plan(user)
        return key, pool.session(key, lambda: start(user, ctx), digest)

    def hidden(user) -> List[str]:
        """這個人存的 secret 值（給人／AI 看的字裡要遮掉）。"""
        store = pack.secrets
        if store is None or not getattr(store, "available", False):
            return []
        try:
            return store.secret_values(user)
        except Exception:
            return []

    not_connected = backend.not_connected

    def dispatch(api, chat_id, work: Callable[[], None], cmd: str) -> None:
        if getattr(api, "via_ai", False) is True:     # 經 AI：同步做完，結果交回 AI（loop 包 nonce 分隔符）
            work()
            return
        typing = getattr(api, "typing", None)
        if callable(typing):
            typing(chat_id)
        app.tasks.run(work, name=f"mcp-{m.name}-{cmd}")

    def make(tool: str):
        cmd = commands[tool]

        def ask_confirm(api, chat_id, user, raw_values, values, envelope, again: bool) -> None:
            if again:                                  # 確認過的重叫又要確認：不再出卡
                say(api, chat_id, tool_confirm.AGAIN.format(name=cmd))
                return
            desk = app.extras.get("synox_approval_desk")
            node = nodes.get(tool)
            if desk is None or node is None:
                say(api, chat_id, tool_confirm.NO_DESK.format(name=cmd))
                return
            gid = grants_book.issue(m.name, cmd, values, getattr(user, "tg_id", None),
                                    tool_confirm.tool_token(envelope), app.timing.confirm_ttl)
            shown = [f"{k}={str(v)[:60]}" for k, v in raw_values.items() if str(v).strip()]

            def rerun(api2, chat2, clicker, grant):
                dispatch(api2, chat2, lambda: call(api2, chat2, clicker, raw_values, grant), cmd)

            try:
                desk.request(api, chat_id, user, node, shown, tool_confirm.summary_of(envelope), grant=gid,
                             rerun=rerun, header="⚠️ 要你確認才會做")
            except Exception:
                grants_book.discard(gid)
                raise
            mark = getattr(type(api), "mark_carded", None)
            if callable(mark):
                mark(api)

        def call(api, chat_id, user, raw_values: Dict[str, str], grant: str = "") -> None:
            """grant：只有核准卡按 ✅ 的重叫會給（指令、AI 都造不出來）。"""
            blocked = not_connected(user)
            if blocked:
                if grant:
                    grants_book.discard(grant)
                say(api, chat_id, blocked)
                return
            shape = shapes[tool]
            if shape.missing:
                say(api, chat_id, f"❌ {cmd}：MCP 伺服器沒有提供 {tool} 這個工具（pack.json 有允許，但伺服器的清單裡沒有）。")
                return
            if not shape.callable:
                say(api, chat_id, f"❌ {cmd}：這個工具有這一版還不支援的必填參數（巢狀物件／陣列），不能用。")
                return
            kinds = {f.name: (f.kind, f.choices) for f in shape.fields}
            values = {k: gate4.normalize(kinds.get(k, ("text", ()))[0], v, kinds.get(k, ("text", ()))[1])
                      for k, v in raw_values.items()}
            token: Optional[str] = None
            if grant:
                token = grants_book.redeem(grant, m.name, cmd, values, getattr(user, "tg_id", None))
                if token is None:
                    say(api, chat_id, tool_confirm.EXPIRED)
                    return
            try:
                arguments = to_arguments(shape, values)
            except ValueError as e:
                say(api, chat_id, f"❌ {cmd}：參數不對（{e}）")
                return
            params: Dict[str, Any] = {"name": tool, "arguments": arguments}
            if token is not None:
                params["_meta"] = {CONFIRM_META: token}
            result = None
            for attempt in (1, 2):                     # http 的連線過期（404＋Mcp-Session-Id）：重新 initialize 再試一次
                key = None
                try:
                    key, session = session_for(user)
                    result = session.request("tools/call", params, call_timeout)
                    break
                except McpError as e:
                    if e.fatal and key is not None:
                        pool.drop(key)
                    if e.retry and attempt == 1:
                        continue
                    again = backend.again if e.fatal else ""
                    say(api, chat_id, redact(f"❌ {m.title}／{cmd}：{e.message}{again}", hidden(user)))
                    return
            envelope = needs_confirm_of(result)
            if envelope is not None:
                ask_confirm(api, chat_id, user, raw_values, values, envelope, again=token is not None)
                return
            ok, text = render_result(result)
            text = redact(text, hidden(user))
            say(api, chat_id, text if ok and text else (f"❌ {cmd}：{text or '工具回報失敗'}" if not ok else "（做完了，沒有輸出）"))

        def typed(api, chat_id, user, args: List[str]) -> None:
            shape = shapes[tool]
            if not shape.known:                        # 還不知道參數：先啟動一次讀 tools/list（失敗的不會留在池裡）
                blocked = not_connected(user)
                if blocked:
                    say(api, chat_id, blocked)
                    return
                try:
                    session_for(user)
                except McpError as e:
                    say(api, chat_id, redact(f"❌ {m.title}／{cmd}：{e.message}{backend.again}", hidden(user)))
                    return
            node = nodes[tool]
            fields = tuple(node.fields)
            n_pos = sum(1 for f in fields if f.required)
            values, missing, errors = kit.parse_args(fields, args, n_pos)
            if errors:
                say(api, chat_id, "❌ " + "；".join(errors))
                return
            if missing:
                say(api, chat_id, f"用法：{node.command} {node.usage}\n（少了：{'、'.join(f.ask for f in missing)}）")
                return
            call(api, chat_id, user, values)

        def leaf(api, chat_id, user, args):
            dispatch(api, chat_id, lambda: typed(api, chat_id, user, list(args)), cmd)

        return leaf

    for tool in allow:
        node = pack.group.leaf(commands[tool], make(tool), shapes[tool].summary,
                               effect=effects.get(effect_name(m, tool), DANGER))
        nodes[tool] = node
        apply(tool)
    backend.commands(pack.group, list(commands.values()))


__all__ = ["Backend", "CONFIRM_META", "FieldSpec", "McpError", "McpPool", "PerUserScope", "Proc", "SCOPES", "Scope",
           "Session", "StdioBackend", "missing_secrets", "redact",
           "SharedScope", "ToolShape", "doctor_notes", "effect_name", "handshake", "install", "load_cache",
           "needs_confirm_of", "pool_of", "render_result", "shape_of", "spawn", "to_arguments", "to_identifier",
           "unique_identifiers"]
