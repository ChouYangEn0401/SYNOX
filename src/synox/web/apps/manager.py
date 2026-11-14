"""工具服務的管理員（計畫 WP2、C1、C7、C10–C12；ADR 0024 第三版）。

- 開（`start`）只收兩種來路：`via="web"`（主機台按鈕）與 `via="telegram"`（擁有者自己打的 /app_open）。其他（system、app、
  ai、排程、任何內部呼叫）一律 `forbidden`——AI 與排程不能開服務（擁有者決定；/app_open 本身也是 interactive）。
- 一個工具配一個埠，配過就永遠是它的（`data/apps.json`）；埠被別的程式占住 → error，不自動換埠。
- 一把 RLock：開、關、決定要關誰、發票、兌票、讀寫埠表都在鎖裡；通知、稽核在鎖外。`touch` 不拿這把鎖。
- 關是同步的：`Listener.close()` 回來了才算關；超過 5 秒 → error（stuck），那個埠到 SYNOX 重開之前不再用。
- 閒置照每個工具自己的設定（C10）；runtime 任務 `system.tool_apps` 只有在有服務開著時才排。
- `on_stopped(fn)`：每一種停法（手動、閒置、重新載入、/web_off、關 SYNOX）都叫一次 fn(name, reason)（手機入口跟著關，對接 f）。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional

from isdtelekit.core import jsonstore

from synox.web.apps import spec as spec_mod
from synox.web.apps.audit import FILE as AUDIT_FILE, Audit, safe_trace
from synox.web.apps.listen import open_listener
from synox.web.apps.sessions import HandoffTickets
from synox.web.apps.site import AppSite, AppsError

TASK_ID = "system.tool_apps"
TASK_NAME = "工具服務"
TICK_S = 60
SUGGEST_MIN = 30
APPS_FILE = "apps.json"
STATE_FILE = "apps_state.json"
VIAS_THAT_OPEN = ("web", "telegram")
MODES = ("auto", "suggest", "keep", "blocked")
CONTAINER_ENV = "SYNOX_IN_CONTAINER"
TEXT = {
    "what": "記帳這類工具平常只在 SYNOX 裡面聽你的指令。開啟服務＝SYNOX 在這台電腦上多開一個網址，讓你用瀏覽器看這個工具的完整畫面。"
            "這個網址只有這台電腦打得開。",
    "why_close": "服務開著，就像家裡多開了一扇門：沒有你的登入進不來，但門在那裡。不用的時候關上，門就不存在了。"
                 "關掉不會刪任何資料，Telegram 照樣可以用。",
    "restart": "SYNOX 每次重開，所有服務都是關的；要用再開。",
    "in_use": "你在這個畫面上做事（看資料、按按鈕、存東西），或這個分頁在你眼前、而且你有動滑鼠、打字、捲動、點或滑。"
              "分頁開著但切到別的地方去了，不算。",
    "forbidden": "工具服務只能由擁有者在 SYNOX 網頁按「開啟」或在 Telegram 打 /app_open 開。",
    "unavailable_web": "網頁介面關著（web.enabled=false），工具服務不能用。",
    "unavailable_apps": "工具服務關著（config.json 的 web.apps.enabled=false）。",
    "unavailable_off": "網頁介面被 /web_off 關掉了，重開 SYNOX 才能再用。",
    "unavailable_container": "容器版還沒開放工具服務。",
    "owner": "只有擁有者能開關工具服務。",
    "not_found": "沒有這個工具的畫面。",
    "blocked": "你把{title}設成不開放了；要開先到 SYNOX 網頁的工具頁改設定。",
    "busy": "{title}的服務正在開或正在關，等一下再試。",
    "max_running": "已經開了 {n} 個服務（最多 {max} 個）：{names}。先關一個再開。",
    "port_full": "工具服務的埠用完了；把 config.json 的 web.apps.port_count 調大。",
    "port_busy": "{port} 被別的程式用了。關掉那個程式再試；還是不行就重開 SYNOX。",
    "port_stuck": "{port} 上次沒有關乾淨，重開 SYNOX 之後才能再用。",
    "not_on": "這個工具的服務沒有開。",
    "idle_closed": "🧩 {title}的服務 {n} 分鐘沒有用，我先關掉了。資料都在；要用再 /app_open {name}。",
    "idle_suggest": "🧩 {title}的服務 {n} 分鐘沒有用了。要關：/app_close {name}。不理我的話再 {m} 分鐘我會自己關。",
    "idle_suggest_keep": "🧩 {title}的服務 {n} 分鐘沒有用了。要關：/app_close {name}。它會一直開著，直到你關掉或重開 SYNOX。"
                         "想改成自動關，到 SYNOX 網頁的工具頁設定。",
    "policy_bad": "閒置設定不對：{why}",
    "keep_understood": "選「一直開著」要先看過說明（understood: true）。",
    "close_min": "close_min 要是 5–1440 的整數",
    "mode": "mode 只能是 auto、suggest、keep、blocked",
    "error_port": "埠被別的程式占用了。",
    "error_stuck": "上次沒有關乾淨。",
    "error_tampered": "畫面的檔跟安裝時不一樣。",
}


@dataclass
class AppState:
    name: str
    status: str = "off"           # off｜starting｜on｜stopping｜error
    port: int = 0
    since: float = 0.0
    last_used: float = 0.0
    suggested: bool = False
    reason: str = ""
    site: object = None
    listener: object = None


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t).isoformat(timespec="seconds") if t else ""


class AppManager:
    def __init__(self, app, config, ui, *, listen=open_listener, clock=time.time, exists=os.path.exists, environ=None):
        self.app, self.config, self.ui = app, config, ui
        self.listen, self.clock, self.exists = listen, clock, exists
        self.environ = os.environ if environ is None else environ
        self.lock = threading.RLock()
        data_dir = str(getattr(config, "data_dir", ".") or ".")
        self.apps_path = os.path.join(data_dir, APPS_FILE)
        self.state_path = os.path.join(data_dir, STATE_FILE)
        self.audit = Audit(os.path.join(data_dir, AUDIT_FILE), clock=clock)
        self.tickets = HandoffTickets(clock)
        self._states: Dict[str, AppState] = {}
        self._stuck_ports: set = set()
        self._on_stopped: List[Callable[[str, str], None]] = []
        self.remote_until: Optional[Callable[[str], str]] = None       # 手機入口（ADR 0026）掛上：幾點自動關

    # ── 設定與狀態檔 ─────────────────────────────────────────────────

    @property
    def settings(self) -> dict:
        from synox.config import DEFAULT_APPS
        web = getattr(self.config, "web", {}) or {}
        return {**DEFAULT_APPS, **(web.get("apps") or {})}

    def _data(self) -> dict:
        raw = jsonstore.load_json(self.apps_path, {})
        raw = raw if isinstance(raw, dict) else {}
        return {"ports": dict(raw.get("ports") or {}), "explained": bool(raw.get("explained")),
                "policy": dict(raw.get("policy") or {})}

    def _save_data(self, data: dict) -> None:
        jsonstore.save_json(self.apps_path, data)

    def _write_state(self) -> None:
        running = [{"name": s.name, "port": s.port, "since": _iso(s.since)} for s in self._states.values()
                   if s.status == "on"]
        try:
            jsonstore.save_json(self.state_path, {"pid": os.getpid(), "at": _iso(self.clock()), "running": running})
        except OSError as e:
            logging.warning("[APPS] cannot write state: %s", safe_trace(e))

    def clear_state_file(self) -> None:
        with self.lock:
            self._write_state()

    def on_stopped(self, fn: Callable[[str, str], None]) -> None:
        self._on_stopped.append(fn)

    def console_url(self) -> str:
        port = int((getattr(self.config, "web", {}) or {}).get("port") or 8830)
        return f"http://127.0.0.1:{port}/#tools"

    # ── 可不可以用 ──────────────────────────────────────────────────

    def available(self):
        web = getattr(self.config, "web", {}) or {}
        if not web.get("enabled", True):
            return False, TEXT["unavailable_web"]
        if not self.settings.get("enabled", True):
            return False, TEXT["unavailable_apps"]
        if getattr(self.ui, "disabled", False):
            return False, TEXT["unavailable_off"]
        from synox.web.server import CONTAINER_MARKERS
        if str(self.environ.get(CONTAINER_ENV, "")).strip() == "1" or any(self.exists(m) for m in CONTAINER_MARKERS):
            return False, TEXT["unavailable_container"]
        return True, ""

    def specs(self):
        return spec_mod.specs_of(self.app)[0]

    def problems(self):
        return spec_mod.specs_of(self.app)[1]

    def _state(self, name: str) -> AppState:
        st = self._states.get(name)
        if st is None:
            st = self._states[name] = AppState(name)
        return st

    def _is_owner(self, by) -> bool:
        if by is None or by == 0:
            return False
        user = by if hasattr(by, "tg_id") else self.app.users.get_or_create(int(by))
        return self.app.registry.is_owner(user)

    @staticmethod
    def _by_id(by) -> int:
        return int(getattr(by, "tg_id", by) or 0)

    # ── 閒置設定（C10）────────────────────────────────────────────────

    def policy_of(self, name: str) -> dict:
        saved = self._data()["policy"].get(name)
        if isinstance(saved, dict) and saved.get("mode") in MODES:
            mode = saved["mode"]
            close = int(saved.get("close_min") or 0) if mode == "auto" else 0
            suggest = SUGGEST_MIN if (mode == "suggest" or (mode == "auto" and close > SUGGEST_MIN)) else 0
            return {"mode": mode, "suggest_min": suggest, "close_min": close, "default": False,
                    "text": policy_text(mode, suggest, close)}
        s = self.settings
        suggest, close = int(s.get("idle_suggest_min", 30)), int(s.get("idle_close_min", 120))
        mode = "auto" if close else ("suggest" if suggest else "keep")
        if mode == "suggest":
            suggest = suggest or SUGGEST_MIN
        return {"mode": mode, "suggest_min": suggest if mode != "keep" else 0, "close_min": close, "default": True,
                "text": policy_text(mode, suggest, close)}

    def set_policy(self, name: str, data, by) -> dict:
        if not self._is_owner(by):
            raise AppsError("forbidden", TEXT["owner"], 403)
        if name not in self.specs() and name not in self.problems():
            raise AppsError("not_found", TEXT["not_found"], 404)
        if not isinstance(data, dict) or data.get("mode") not in MODES:
            raise AppsError("invalid", TEXT["policy_bad"].format(why=TEXT["mode"]), 400)
        mode = data["mode"]
        entry = {"mode": mode}
        if mode == "auto":
            close = data.get("close_min")
            if isinstance(close, bool) or not isinstance(close, int) or not 5 <= close <= 1440:
                raise AppsError("invalid", TEXT["policy_bad"].format(why=TEXT["close_min"]), 400)
            entry["close_min"] = close
        if mode == "keep" and data.get("understood") is not True:
            raise AppsError("invalid", TEXT["keep_understood"], 400)
        with self.lock:
            stored = self._data()
            stored["policy"][name] = entry
            self._save_data(stored)
            on = self._state(name).status == "on"
        self.audit.write("policy", name, by=self._by_id(by), via="web", mode=mode, close_min=entry.get("close_min", 0))
        if mode == "blocked" and on:
            self.stop(name, by=self._by_id(by), via="web", reason="blocked")
        else:
            self.touch(name)
        return self.view(name)

    # ── 開 ───────────────────────────────────────────────────────────

    def _assign_port(self, name: str, stored: dict) -> int:
        ports = stored["ports"]
        if name in ports:
            return int(ports[name])
        s = self.settings
        used = {int(p) for p in ports.values()}
        for port in range(int(s["port_first"]), int(s["port_first"]) + int(s["port_count"])):
            if port not in used:
                ports[name] = port
                self._save_data(stored)
                return port
        raise AppsError("port", TEXT["port_full"], 503)

    def start(self, name: str, by, via: str) -> dict:
        if via not in VIAS_THAT_OPEN:
            raise AppsError("forbidden", TEXT["forbidden"], 403)
        ok, why = self.available()
        if not ok:
            raise AppsError("unavailable", why, 409)
        if not self._is_owner(by):
            raise AppsError("forbidden", TEXT["owner"], 403)
        specs, problems = spec_mod.specs_of(self.app)
        if name in problems:
            raise AppsError("unavailable", problems[name], 409)
        spec = specs.get(name)
        if spec is None:
            raise AppsError("not_found", TEXT["not_found"], 404)
        if self.policy_of(name)["mode"] == "blocked":
            raise AppsError("blocked", TEXT["blocked"].format(title=spec.title), 409)
        with self.lock:
            st = self._state(name)
            if st.status in ("starting", "stopping"):
                raise AppsError("busy", TEXT["busy"].format(title=spec.title), 409)
            if st.status == "on":
                return self.view(name)
            running = [s for s in self._states.values() if s.status in ("on", "starting")]
            limit = int(self.settings["max_running"])
            if len(running) >= limit:
                names = "、".join(self._title(s.name) for s in running)
                raise AppsError("max_running", TEXT["max_running"].format(n=len(running), max=limit, names=names), 409)
            stored = self._data()
            port = self._assign_port(name, stored)
            if port in self._stuck_ports:
                raise AppsError("port", TEXT["port_stuck"].format(port=port), 503)
            st.status, st.reason, st.port = "starting", "", port
        try:
            site = AppSite(self, spec, port, clock=self.clock, console_url=self.console_url())
        except AppsError as e:
            with self.lock:
                st.status, st.reason = "error", "tampered"
            self.audit.write("error", name, by=self._by_id(by), via=via, ok=False, code="tampered", reason="tampered",
                             port=port)
            raise e
        try:
            listener = self.listen(site, port)
        except OSError as e:
            logging.error("[APPS] %s cannot listen on %s: %s", name, port, safe_trace(e))
            with self.lock:
                st.status, st.reason = "error", "port"
            self.audit.write("error", name, by=self._by_id(by), via=via, ok=False, code="port", reason="port", port=port)
            raise AppsError("port", TEXT["port_busy"].format(port=port), 503)
        with self.lock:
            now = self.clock()
            st.status, st.site, st.listener, st.since, st.last_used, st.suggested = "on", site, listener, now, now, False
            self._write_state()
        self.audit.write("start", name, by=self._by_id(by), via=via, port=port)
        self._reschedule()
        return self.view(name)

    # ── 關 ───────────────────────────────────────────────────────────

    def stop(self, name: str, by=0, via: str = "system", reason: str = "owner") -> bool:
        with self.lock:
            st = self._states.get(name)
            if st is None or st.status != "on":
                if st is not None and st.status in ("starting", "stopping"):
                    raise AppsError("busy", TEXT["busy"].format(title=self._title(name)), 409)
                return False
            st.status = "stopping"
            if st.site is not None:
                st.site.sessions.drop_all()
            self.tickets.clear(name)
            listener = st.listener
        closed = True
        try:
            closed = bool(listener.close(5.0)) if listener is not None else True
        except Exception as e:
            logging.error("[APPS] %s close failed: %s", name, safe_trace(e))
            closed = False
        with self.lock:
            st.site, st.listener = None, None
            if closed:
                st.status, st.reason = "off", ""
            else:
                st.status, st.reason = "error", "stuck"
                self._stuck_ports.add(st.port)
            self._write_state()
        event = "auto_stop" if reason == "idle" else "stop"
        self.audit.write(event, name, by=self._by_id(by), via=via, reason=reason if closed else "stuck", port=st.port,
                         ok=closed)
        for fn in list(self._on_stopped):
            try:
                fn(name, reason)
            except Exception as e:
                logging.error("[APPS] on_stopped listener failed: %s", safe_trace(e))
        self._reschedule()
        return True

    def stop_all(self, by=0, via: str = "system", reason: str = "owner") -> List[str]:
        with self.lock:
            names = [n for n, s in self._states.items() if s.status == "on"]
        stopped = []
        for name in names:
            try:
                if self.stop(name, by=by, via=via, reason=reason):
                    stopped.append(name)
            except AppsError:
                continue
        return stopped

    def keep(self, name: str, by=0, via: str = "web") -> dict:
        self.touch(name)
        self.audit.write("keep", name, by=self._by_id(by), via=via)
        return self.view(name)

    def touch(self, name: str) -> None:
        """有在用（C11）：更新 last_used、清掉「這一段閒置已經提醒過」。不拿大鎖。"""
        st = self._states.get(name)
        if st is not None:
            st.last_used = self.clock()
            st.suggested = False

    def running(self) -> List[str]:
        return [n for n, s in self._states.items() if s.status == "on"]

    def port_of(self, name: str) -> int:
        st = self._states.get(name)
        return st.port if st is not None and st.status == "on" else 0

    def site_of(self, name: str):
        st = self._states.get(name)
        return st.site if st is not None and st.status == "on" else None

    # ── 交接票（C7、C12）──────────────────────────────────────────────

    def issue_ticket(self, name: str, tg_id: int, parent) -> str:
        with self.lock:
            st = self._states.get(name)
            if st is None or st.status != "on":
                raise AppsError("not_found", TEXT["not_on"], 404)
            return self.tickets.issue(name, st.port, tg_id, parent)

    def redeem_ticket(self, name: str, port: int, ticket):
        with self.lock:
            st = self._states.get(name)
            if st is None or st.status != "on" or st.port != int(port):
                return None
            return self.tickets.redeem(name, port, ticket)

    # ── 閒置（tick）───────────────────────────────────────────────────

    def tick(self, ctx=None) -> str:
        now = self.clock()
        to_stop, to_suggest, gone = [], [], []
        specs, problems = spec_mod.specs_of(self.app)
        with self.lock:
            for name, st in self._states.items():
                if st.status != "on":
                    continue
                if name not in specs or name in problems or self._quarantined(specs.get(name)):
                    gone.append(name)
                    continue
                policy = self.policy_of(name)
                idle = (now - st.last_used) / 60.0
                if policy["mode"] == "auto" and policy["close_min"] and idle >= policy["close_min"]:
                    to_stop.append((name, int(idle)))
                elif policy["mode"] in ("auto", "suggest") and policy["suggest_min"] and idle >= policy["suggest_min"] \
                        and not st.suggested:
                    st.suggested = True
                    to_suggest.append((name, int(idle), policy))
        for name in gone:
            self.stop(name, via="system", reason="reload")
        for name, idle in to_stop:
            if self.stop(name, via="system", reason="idle"):
                self._notify(TEXT["idle_closed"].format(title=self._title(name), n=idle, name=name))
        for name, idle, policy in to_suggest:
            self.audit.write("suggest", name, via="system", mode=policy["mode"], close_min=policy["close_min"])
            if policy["mode"] == "suggest":
                text = TEXT["idle_suggest_keep"].format(title=self._title(name), n=idle, name=name)
            else:
                text = TEXT["idle_suggest"].format(title=self._title(name), n=idle, name=name,
                                                   m=max(1, policy["close_min"] - idle))
            self._notify(text)
        on = [s for s in self._states.values() if s.status == "on"]
        if not on:
            return "沒有開著的工具服務"
        return "開著：" + "、".join(f"{self._title(s.name)}（閒置 {int((now - s.last_used) // 60)} 分）" for s in on)

    def _quarantined(self, spec) -> bool:
        if spec is None:
            return True
        from synox import health
        return any(health.hidden(self.app, f"{spec.group}.{n}") is not None for n in spec.actions)

    def _notify(self, text: str) -> None:
        try:
            self.app.notify_owner(text)
        except Exception as e:
            logging.error("[APPS] notify failed: %s", safe_trace(e))

    def _title(self, name: str) -> str:
        spec = self.specs().get(name)
        return spec.title if spec is not None else name

    def _reschedule(self) -> None:
        from synox import runtime
        rt = runtime.of(self.app)
        if rt is None:
            return
        try:
            rt.loop.reschedule(TASK_ID, TICK_S if self.running() else None)
        except Exception as e:
            logging.warning("[APPS] reschedule failed: %s", safe_trace(e))

    def register_task(self) -> None:
        from synox import runtime
        rt = runtime.of(self.app)
        if rt is None:
            return
        rt.loop.register(TASK_ID, TASK_NAME, fn=self.tick, interval=TICK_S if self.running() else None)

    # ── 給畫面的清單（C7）─────────────────────────────────────────────

    def view(self, name: str, user=None) -> dict:
        specs, problems = spec_mod.specs_of(self.app)
        spec = specs.get(name)
        st = self._states.get(name) or AppState(name)
        now = self.clock()
        policy = self.policy_of(name)
        idle = int((now - st.last_used) // 60) if st.status == "on" else 0
        close_in = None
        if st.status == "on" and policy["mode"] == "auto" and policy["close_min"]:
            close_in = max(0, policy["close_min"] - idle)
        effects = dict(spec.actions) if spec else {}
        return {"name": name, "title": spec.title if spec else name, "app_title": spec.app_title if spec else name,
                "state": st.status if st.status in ("on", "error") else "off",
                "open": f"/apps/{name}/open" if st.status == "on" else "",
                "port": st.port or self._data()["ports"].get(name, 0),
                "since": _iso(st.since) if st.status == "on" else "",
                "last_used": _iso(st.last_used) if st.status == "on" else "", "idle_min": idle,
                "suggest_close": bool(st.status == "on" and st.suggested),
                "auto_close_in_min": close_in,
                "error": {"port": TEXT["error_port"], "stuck": TEXT["error_stuck"],
                          "tampered": TEXT["error_tampered"]}.get(st.reason, "") if st.status == "error" else "",
                "policy": policy,
                "actions": {"write": sum(1 for e in effects.values() if e == "write"),
                            "danger": sum(1 for e in effects.values() if e == "danger")},
                "exports": list(spec.exports) if spec else [], "remote": bool(spec.remote) if spec else False,
                "problem": problems.get(name, "")}

    def views(self, user) -> dict:
        ok, why = self.available()
        specs, problems = spec_mod.specs_of(self.app)
        registry = self.app.registry
        owner = registry.is_owner(user)
        names = sorted(set(specs) | set(problems))
        visible = []
        for name in names:
            pack = next((p for p in self.app.extras.get("synox_packs", []) if p.name == name), None)
            group = registry.node(pack.manifest.group) if pack is not None else None
            if group is not None and registry.visible(user, group):
                visible.append(self.view(name))
        return {"available": ok, "reason": why, "can_manage": owner,
                "running": len(self.running()), "max_running": int(self.settings["max_running"]),
                "explain": {"what": TEXT["what"], "why_close": TEXT["why_close"], "restart": TEXT["restart"],
                            "in_use": TEXT["in_use"]},
                "explained": self._data()["explained"], "apps": visible}

    def mark_explained(self) -> None:
        with self.lock:
            data = self._data()
            if not data["explained"]:
                data["explained"] = True
                self._save_data(data)

    def resolve(self, text: str) -> Optional[str]:
        """C9：pack 名、群組名、標題（去掉 emoji 與空白）、app.title，不分大小寫。"""
        want = _plain(text)
        if not want:
            return None
        specs, problems = spec_mod.specs_of(self.app)
        for pack in self.app.extras.get("synox_packs", []):
            name = pack.name
            if name not in specs and name not in problems:
                continue
            m = pack.manifest
            app_title = ((m.web or {}).get("app") or {}).get("title") or ""
            if want in {_plain(name), _plain(m.group), _plain(m.title), _plain(app_title)} - {""}:
                return name
        return None


def _plain(text) -> str:
    import unicodedata
    out = []
    for ch in str(text or ""):
        if ch.isspace() or unicodedata.category(ch) in ("So", "Sk", "Cf", "Mn", "Cs") or ord(ch) >= 0x1F000:
            continue
        out.append(ch.lower())
    return "".join(out)


def policy_text(mode: str, suggest: int, close: int) -> str:
    if mode == "keep":
        return "一直開著"
    if mode == "blocked":
        return "不開放這個工具的畫面"
    if mode == "suggest":
        return "只提醒，不自動關"
    if close and suggest and close > suggest:
        return f"{close} 分鐘沒用就關，{suggest} 分鐘先提醒"
    if close:
        return f"{close} 分鐘沒用就關"
    return "只提醒，不自動關"
