"""手機入口的管理員（ADR 0026；計畫 K7）。同時最多一條入口；只有擁有者、只收人、每次開都要一組新的驗證碼。

`open` 依序（任何一步不過＝RemoteError(code, text)，並記稽核 remote_refused）：
來源是 telegram／web／console（not_human）→ 擁有者（not_owner）→ available()（disabled／container／apps）→ 驗證器已設定（stepup_unset）→
`stepup.verify(…, purpose="remote_open")`（bad_code）→ 通道程式找得到而且雜湊等於核准的（no_binary／binary_changed）→
這個工具宣告了 web.app.remote、而且擁有者打開過「可以從手機用」（not_remote_tool／tool_not_allowed）→ 沒有別條入口（busy）→
服務沒開就開（記 started_here）→ 開閘門的 listener（127.0.0.2:gate_port；port）→ 通道（tunnel_failed；失敗把前面開的都收掉）→
建 Link → 回 {"url": "https://<host>/#k=<key>", "minutes"}。

`close`：先標成關（閘門立刻全回 404）→ 作廢登入與鑰匙 → 通道 stop → 關 listener → started_here 就關服務 → 稽核 → 通知擁有者一則。
一定會關的掛點：工具服務「服務停了」、/web_off（服務會一起停）、app.on_stop、stepup.on_disable、tick（時間、閒置、沒人進門、通道斷了）。
鑰匙、cookie、驗證碼都不進任何檔案、稽核、log。
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
from urllib.parse import urlsplit

from isdtelekit.core import jsonstore

from synox.guard import origin as origin_mod
from synox.guard.limits import Attempts, Rate
from synox.web.remote.gate import RemoteGate, digest
from synox.web.remote.tunnel import URL_RE, TunnelError

TASK_ID = "system.remote"
TASK_NAME = "手機入口"
TICK_S = 15
ENTRY_S = 300
WARN_LEFT_S = 300
REJECT_LIMIT = 300
DATA_FILE = "remote.json"
HUMAN_OPENERS = ("telegram", "web", "console")
TEXT = {
    "not_human": "手機入口只能由你本人在 Telegram 私訊或 SYNOX 網頁開。",
    "not_owner": "只有擁有者能開手機入口。",
    "disabled": "手機入口的總開關關著：到 SYNOX 網頁 → 設定 → 🔐 安全 打開。",
    "container": "容器版還沒開放手機入口。",
    "apps": "工具服務現在不能用：{why}",
    "stepup_unset": "手機入口一定要先設定手機驗證器：到 SYNOX 網頁 → 設定 → 🔐 安全。",
    "bad_code": "驗證碼不對（要一組新的，不能用剛剛用過的）。",
    "no_binary": "找不到通道程式 cloudflared：自己安裝之後，到 SYNOX 網頁 → 設定 → 🔐 安全 核准它。",
    "binary_changed": "通道程式跟核准時不一樣（可能被更新或換掉了），先不跑：到 SYNOX 網頁 → 設定 → 🔐 安全 重新核准。",
    "not_remote_tool": "{title}沒有宣告可以從手機用。",
    "tool_not_allowed": "你還沒打開{title}的「可以從手機用」：到 SYNOX 網頁的工具頁打開。",
    "not_found": "沒有這個工具的畫面。",
    "busy": "已經有一條手機入口開著（{title}）；先 /app_close 它。",
    "port": "手機入口用的埠被別的程式占用了；關掉那個程式再試，或改 config.json 的 web.remote.gate_port。",
    "tunnel_failed": "通道開不起來（{code}）。等一下再試；一直不行就看 doctor 的說明。",
    "opened": "📱 {title}的手機入口開好了（{m} 分鐘後自動關）：\n{url}\n連結只能用一次，5 分鐘內要進去；進門時要再打一組驗證器上的數字。"
              "用完打 /app_close {name}。",
    "entered": "📱 有人從手機進來了（{title}）。不是你的話：/app_close {name}",
    "warn": "📱 {title}的手機入口再 5 分鐘就會自動關。",
    "closed": "📴 手機入口關了（{why}）。資料都在。",
    "knock": "📴 有人在亂敲門，我先把手機入口關了。資料都在。",
}
REASONS = {"owner": "你關的", "time": "時間到了", "idle": "一陣子沒有用", "no_entry": "5 分鐘內沒有人進門",
           "bad_code": "驗證碼錯太多次", "abuse": "被亂敲太多次", "tunnel_down": "通道斷了", "service_stopped": "工具的服務停了",
           "web_off": "網頁介面關了", "shutdown": "SYNOX 結束了", "stepup_disabled": "手機驗證器關掉了"}


class RemoteError(Exception):
    def __init__(self, code: str, text: str):
        super().__init__(code)
        self.code, self.text = code, text


@dataclass
class Link:
    id: str
    name: str
    owner: int
    host: str
    key_digest: str
    entry_deadline: float
    hard_deadline: float
    state: str = "waiting"              # waiting｜entered｜closed
    session_digest: str = ""
    ua_digest: str = ""
    last_activity: float = 0.0
    warned: bool = False
    warned_idle: bool = False
    started_here: bool = False
    rejects: int = 0
    kind: str = "remote"
    listener: object = field(default=None, repr=False)

    @property
    def surface(self) -> str:
        return "remote:" + self.id

    def alive(self) -> bool:
        """工具服務的登入綁在這上面（ADR 0026 對接 d）：入口一關，手機上的登入立刻失效。"""
        return self.state != "closed"


class RemoteManager:
    def __init__(self, app, config, apps, guard, *, tunnel=None, listen=None, clock=time.time, binary_check=None,
                 exists=os.path.exists, environ=None):
        self.app, self.config, self.apps, self.guard = app, config, apps, guard
        self.tunnel_factory = tunnel
        if listen is None:
            from synox.web.apps.listen import open_listener
            listen = open_listener
        self.listen, self.clock = listen, clock
        self.binary_check = binary_check
        self.exists = exists
        self.environ = os.environ if environ is None else environ
        self.lock = threading.RLock()
        self.link: Optional[Link] = None
        self.tunnel = None
        self.gate: Optional[RemoteGate] = None
        self.enter_attempts = Attempts(5, ENTRY_S * 4, 3600, clock=clock)
        self.rate_out = Rate(60, clock=clock)
        self.rate_in = Rate(240, clock=clock)
        self._last_reject_audit = {}
        self.path = os.path.join(str(getattr(config, "data_dir", ".") or "."), DATA_FILE)

    # ── 設定 ─────────────────────────────────────────────────────────

    @property
    def settings(self) -> dict:
        from synox.config import DEFAULT_REMOTE
        return {**DEFAULT_REMOTE, **((getattr(self.config, "web", {}) or {}).get("remote") or {})}

    def data(self) -> dict:
        raw = jsonstore.load_json(self.path, {})
        raw = raw if isinstance(raw, dict) else {}
        return {"binary": raw.get("binary") if isinstance(raw.get("binary"), dict) else None,
                "tools": {k: bool(v) for k, v in (raw.get("tools") or {}).items()}}

    def _save(self, data: dict) -> None:
        jsonstore.save_json(self.path, data)

    def _audit(self, event: str, by: int = 0, origin: str = "", ok: bool = True, code: str = "", **nums) -> None:
        if self.guard is not None and self.guard.audit is not None:
            self.guard.audit.write(event, by=by, origin=origin, target="", ok=ok, code=code, **nums)

    def _owner(self) -> int:
        return int(getattr(self.config, "owner_id", 0) or 0)

    def _title(self, name: str) -> str:
        spec = self.apps.specs().get(name)
        return spec.title if spec is not None else name

    # ── 能不能用 ─────────────────────────────────────────────────────

    def available(self):
        if not self.settings.get("enabled"):
            return False, "disabled", TEXT["disabled"]
        from synox.web.server import CONTAINER_MARKERS
        if str(self.environ.get("SYNOX_IN_CONTAINER", "")).strip() == "1" or any(self.exists(m) for m in CONTAINER_MARKERS):
            return False, "container", TEXT["container"]
        ok, why = self.apps.available()
        if not ok:
            return False, "apps", TEXT["apps"].format(why=why)
        return True, "", ""

    # ── 開 ───────────────────────────────────────────────────────────

    def _refuse(self, code: str, text: str, by: int, o) -> RemoteError:
        self._audit("remote_refused", by=by, origin=getattr(o, "kind", ""), ok=False, code=code)
        return RemoteError(code, text)

    def open(self, name: str, user, code: str, *, origin, minutes=None) -> dict:
        uid = int(getattr(user, "tg_id", user) or 0)
        o = origin
        if getattr(o, "kind", "unknown") not in HUMAN_OPENERS:
            raise self._refuse("not_human", TEXT["not_human"], uid, o)
        if uid != self._owner():
            raise self._refuse("not_owner", TEXT["not_owner"], uid, o)
        ok, why_code, why = self.available()
        if not ok:
            raise self._refuse(why_code, why, uid, o)
        hub = self.guard.stepup if self.guard is not None else None
        if hub is None or not hub.enrolled(uid):
            raise self._refuse("stepup_unset", TEXT["stepup_unset"], uid, o)
        r = hub.verify(uid, code, origin=o, purpose="remote_open")
        if not r.ok:
            raise self._refuse("bad_code", r.text or TEXT["bad_code"], uid, o)
        problem = self._binary_problem()
        if problem:
            raise self._refuse(problem, TEXT[problem], uid, o)
        spec = self.apps.specs().get(name)
        if spec is None:
            raise self._refuse("not_found", TEXT["not_found"], uid, o)
        if not spec.remote:
            raise self._refuse("not_remote_tool", TEXT["not_remote_tool"].format(title=spec.title), uid, o)
        if not self.data()["tools"].get(name):
            raise self._refuse("tool_not_allowed", TEXT["tool_not_allowed"].format(title=spec.title), uid, o)
        top = int(self.settings["max_minutes"])
        try:
            want = int(minutes) if minutes not in (None, "") else int(self.settings["minutes"])
        except (TypeError, ValueError):
            want = int(self.settings["minutes"])
        want = max(5, min(top, want))
        with self.lock:
            if self.link is not None and self.link.state != "closed":
                raise self._refuse("busy", TEXT["busy"].format(title=self._title(self.link.name)), uid, o)
            self.link = Link(id=secrets.token_hex(6), name=name, owner=uid, host="", key_digest="",
                             entry_deadline=0, hard_deadline=0, state="closed")
        started_here = False
        listener = None
        tunnel = None
        try:
            if name not in self.apps.running():
                via = "telegram" if o.kind == "telegram" else "web"
                from synox.web.apps.site import AppsError
                try:
                    self.apps.start(name, by=user, via=via)
                except AppsError as e:
                    raise self._refuse("apps", TEXT["apps"].format(why=e.message), uid, o)
                started_here = True
            site = self.apps.site_of(name)
            gate = RemoteGate(self, None, site, clock=self.clock)
            from synox.guard.http import GuardedHandler
            try:
                listener = self.listen(gate, int(self.settings["gate_port"]), handler=GuardedHandler)
            except OSError:
                raise self._refuse("port", TEXT["port"], uid, o)
            tunnel = self._make_tunnel()
            gate_url = f"http://127.0.0.2:{int(self.settings['gate_port'])}"
            try:
                url = tunnel.start(gate_url)
            except TunnelError as e:
                raise self._refuse("tunnel_failed", TEXT["tunnel_failed"].format(code=e.code), uid, o)
            if not URL_RE.match(str(url or "")):
                raise self._refuse("tunnel_failed", TEXT["tunnel_failed"].format(code="url"), uid, o)
        except RemoteError:
            self._cleanup(tunnel, listener, name if started_here else None)
            with self.lock:
                self.link = None
            raise
        key = secrets.token_urlsafe(32)
        now = self.clock()
        with self.lock:
            link = self.link
            link.host = urlsplit(url).hostname or ""
            link.key_digest = digest(key)
            link.entry_deadline = now + ENTRY_S
            link.hard_deadline = now + want * 60
            link.last_activity = now
            link.started_here = started_here
            link.listener = listener
            link.state = "waiting"
            self.tunnel, self.gate = tunnel, gate
            gate.link = link
            self.enter_attempts.ok(link.id)
        self.apps.remote_until = self._until_text
        self._audit("remote_open", by=uid, origin=o.kind, minutes=want)
        self._reschedule()
        return {"url": f"https://{link.host}/#k={key}", "minutes": want, "name": name, "title": self._title(name)}

    def _make_tunnel(self):
        if self.tunnel_factory is not None:
            return self.tunnel_factory() if callable(self.tunnel_factory) and not hasattr(self.tunnel_factory, "start") \
                else self.tunnel_factory
        from synox.web.remote import tunnel as tunnel_mod
        return tunnel_mod.make(self.config, self._binary_path())

    def _binary_path(self) -> str:
        record = self.data()["binary"] or {}
        return str(record.get("path") or "")

    def _binary_problem(self) -> str:
        if self.binary_check is not None:
            return self.binary_check() or ""
        from synox.web.remote import binary
        path = binary.find(self.config)
        if not path:
            return "no_binary"
        record = self.data()["binary"]
        if not record or not binary.approved(path, record):
            return "binary_changed" if record else "no_binary"
        return ""

    def _cleanup(self, tunnel, listener, started_name) -> None:
        if tunnel is not None:
            try:
                tunnel.stop()
            except Exception:
                logging.warning("[REMOTE] tunnel stop failed")
        if listener is not None:
            try:
                listener.close(5.0)
            except Exception:
                logging.warning("[REMOTE] listener close failed")
        if started_name:
            try:
                self.apps.stop(started_name, via="system", reason="owner")
            except Exception:
                logging.warning("[REMOTE] service stop failed")

    def _until_text(self, name: str) -> str:
        link = self.link
        if link is None or link.state == "closed" or link.name != name:
            return ""
        return datetime.fromtimestamp(link.hard_deadline).isoformat(timespec="seconds")

    def minutes_left(self, name: str) -> int:
        link = self.link
        if link is None or link.state == "closed" or link.name != name:
            return 0
        return max(0, int((link.hard_deadline - self.clock()) // 60) + 1)

    # ── 閘門叫的 ─────────────────────────────────────────────────────

    def rate_ok(self, link: Link, entered: bool) -> bool:
        return (self.rate_in if entered else self.rate_out).allow(link.id)

    def rejected(self, link: Optional[Link], code: str) -> None:
        if link is None or link.state == "closed":
            return
        link.rejects += 1
        now = self.clock()
        if now - self._last_reject_audit.get(code, -1e9) >= 60:
            self._last_reject_audit[code] = now
            self._audit("remote_reject", by=link.owner, origin="remote", ok=False, code=code)
        if link.rejects >= REJECT_LIMIT:
            self.close("abuse", notify_text=TEXT["knock"])

    def verify_entry(self, link: Link, code: str, remote_origin) -> bool:
        hub = self.guard.stepup
        r = hub.verify(link.owner, code, origin=remote_origin, purpose="remote_enter")
        return bool(r.ok)

    def enter_failed(self, link: Link) -> None:
        self._audit("remote_enter_fail", by=link.owner, origin="remote", ok=False, code="enter")
        if self.enter_attempts.fail(link.id) or self.enter_attempts.count(link.id) >= 5:
            self.close("bad_code", notify_text=TEXT["knock"])

    def entered(self, link: Link) -> str:
        ticket = self.apps.issue_ticket(link.name, link.owner, link)
        self._audit("remote_enter", by=link.owner, origin="remote")
        self._notify(TEXT["entered"].format(title=self._title(link.name), name=link.name))
        return ticket

    def used(self, link: Link) -> None:
        self.apps.touch(link.name)

    # ── 關 ───────────────────────────────────────────────────────────

    def close(self, reason: str, *, by: int = 0, notify_text: str = "") -> bool:
        with self.lock:
            link = self.link
            if link is None or link.state == "closed":
                return False
            link.state = "closed"                              # 閘門立刻全回 404；工具站的登入看 alive() 也立刻失效
            link.session_digest = link.key_digest = ""
            tunnel, self.tunnel = self.tunnel, None
            listener = link.listener
        self._cleanup(tunnel, listener, link.name if link.started_here and reason != "service_stopped" else None)
        self.apps.remote_until = None
        self._audit("remote_close", by=by, origin="system", code=reason if reason in REASONS else "other")
        self._notify(notify_text or TEXT["closed"].format(why=REASONS.get(reason, reason)))
        self._reschedule()
        return True

    def on_service_stopped(self, name: str, _reason: str) -> None:
        link = self.link
        if link is not None and link.state != "closed" and link.name == name:
            self.close("service_stopped")

    # ── 時間（runtime 任務 system.remote）────────────────────────────

    def tick(self, ctx=None) -> str:
        link = self.link
        if link is None or link.state == "closed":
            return "沒有開著的手機入口"
        now = self.clock()
        idle_s = int(self.settings["idle_min"]) * 60
        if now >= link.hard_deadline:
            self.close("time")
        elif link.state == "waiting" and now > link.entry_deadline:
            self.close("no_entry")
        elif link.state == "entered" and now - link.last_activity >= idle_s:
            self.close("idle")
        elif self.tunnel is not None and not self.tunnel.alive():
            self.close("tunnel_down")
        elif not link.warned and link.hard_deadline - now <= WARN_LEFT_S:
            link.warned = True
            self._notify(TEXT["warn"].format(title=self._title(link.name)))
        return "手機入口：" + ("開著" if link.state != "closed" else "關了")

    def _reschedule(self) -> None:
        from synox import runtime
        rt = runtime.of(self.app)
        if rt is None:
            return
        try:
            on = self.link is not None and self.link.state != "closed"
            rt.loop.reschedule(TASK_ID, TICK_S if on else None)
        except Exception:
            logging.warning("[REMOTE] reschedule failed")

    def register_task(self) -> None:
        from synox import runtime
        rt = runtime.of(self.app)
        if rt is not None:
            rt.loop.register(TASK_ID, TASK_NAME, fn=self.tick, interval=None)

    def _notify(self, text: str) -> None:
        try:
            self.app.notify(self._owner(), text)
        except Exception:
            logging.warning("[REMOTE] notify failed")

    # ── 主機台的開關（要已解鎖；S14 的 web_api 叫）──────────────────────

    def status(self, user) -> dict:
        ok, code, why = self.available()
        link = self.link
        data = self.data()
        specs = self.apps.specs()
        hub = self.guard.stepup if self.guard is not None else None
        return {"available": ok, "code": code, "why": why, "enabled": bool(self.settings.get("enabled")),
                "stepup": bool(hub is not None and hub.enrolled(self._owner())),
                "binary": dict(data["binary"]) if data["binary"] else None,
                "tools": {n: {"title": s.title, "declared": bool(s.remote), "allowed": bool(data["tools"].get(n))}
                          for n, s in sorted(specs.items())},
                "open": None if link is None or link.state == "closed" else
                {"name": link.name, "title": self._title(link.name), "state": link.state,
                 "minutes_left": self.minutes_left(link.name)}}

    def _need_unlocked(self, user, o) -> None:
        uid = int(getattr(user, "tg_id", user) or 0)
        if uid != self._owner():
            raise RemoteError("not_owner", TEXT["not_owner"])
        if getattr(o, "kind", "") not in HUMAN_OPENERS:
            raise RemoteError("not_human", TEXT["not_human"])
        hub = self.guard.stepup
        if not hub.enrolled(uid):
            raise RemoteError("stepup_unset", TEXT["stepup_unset"])
        if not hub.unlocked(uid, o):
            raise RemoteError("stepup", "這個設定要先解鎖。")

    def set_enabled(self, on: bool, user, origin) -> dict:
        self._need_unlocked(user, origin)
        remote = dict(self.settings)
        remote["enabled"] = bool(on)
        self.config.web["remote"] = remote
        path = getattr(self.apps.ui, "config_path", "") if self.apps is not None else ""
        if path and os.path.exists(path):
            import json
            from synox.wizard import logic
            with open(path, encoding="utf-8-sig") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                cfg.setdefault("web", {}).setdefault("remote", {})["enabled"] = bool(on)
                logic.write_config(path, cfg)
        if not on:
            self.close("owner")
        self._audit("remote_switch", by=int(getattr(user, "tg_id", 0)), origin=origin.kind, on=int(bool(on)))
        return self.status(user)

    def allow_tool(self, name: str, on: bool, user, origin) -> dict:
        self._need_unlocked(user, origin)
        spec = self.apps.specs().get(name)
        if spec is None or not spec.remote:
            raise RemoteError("not_remote_tool", TEXT["not_remote_tool"].format(title=spec.title if spec else name))
        data = self.data()
        tools = dict(data["tools"])
        tools[name] = bool(on)
        self._save({"binary": data["binary"], "tools": tools})
        if not on and self.link is not None and self.link.name == name:
            self.close("owner")
        self._audit("remote_allow", by=int(getattr(user, "tg_id", 0)), origin=origin.kind, on=int(bool(on)))
        return self.status(user)

    def approve_binary(self, user, origin) -> dict:
        self._need_unlocked(user, origin)
        from synox.web.remote import binary
        path = binary.find(self.config)
        if not path:
            raise RemoteError("no_binary", TEXT["no_binary"])
        info = binary.describe(path)
        record = {"path": info["path"], "sha256": info["sha256"], "size": info["size"],
                  "approved_at": datetime.fromtimestamp(self.clock()).isoformat(timespec="seconds")}
        data = self.data()
        self._save({"binary": record, "tools": data["tools"]})
        self._audit("remote_binary", by=int(getattr(user, "tg_id", 0)), origin=origin.kind)
        return {**self.status(user), "binary_info": info}
