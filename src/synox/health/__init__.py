"""
工具健康（docs/tool-health.md）：失敗信封 v1、隔離清單、冷卻與重新檢查。

    reg = health.install(app, config, vault)     app.build 在 runtime.install 之後叫；登記 runtime 任務 system.health
    health.of(app)                               HealthRegistry（沒裝＝None，一律當成正常）

loader（cli）、packs/mcp.py、agent/loop.py 只經下面這幾個函式碰它，**每一個都 fail open**（健康管理器自己出錯、存檔壞掉、
設定關掉 → 所有工具當成正常、記 log；不能因為它壞了讓工具都不能用）：

    observe_failure(app, api, tool=, pack=, failure=, user=, …)   記一次失敗；api 是 AI 的 CaptureApi 就把 Failure 交給它
    observe_success(app, api, tool, user)                       記一次成功（手動成功＝重新檢查通過）
    hidden(app, tool, user) → Entry｜None                        這個工具現在不給 AI（broken／needs_action／quarantined）
    unavailable_line(node, entry)                                AI 硬叫時回的那一行、系統提示的那一行（SYNOX 自己的字）
    manual_warning(app, tool, user)                             人自己打指令時前面多的一行警告

- 權限判斷不變：能不能用一個工具只由 `policy.decide` 決定；這裡只管「現在好不好」。
- 重新檢查只用 pack.json `health.check` 宣告的唯讀指令，走既有的工具執行路徑（`ProbeApi`：via_ai、同步、有逾時），
  **過程不叫 AI**；沒有宣告的工具冷卻結束後放回清單試用一次（每天最多 daily_trials 次）。
- 這一版**不做任何自動修復**：補救建議只寫出來給人看。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

from synox.health import failure as failures
from synox.health import settings as health_settings
from synox.health.failure import Failure
from synox.health.state import (BROKEN, HEALTHY, HIDDEN, NEEDS_ACTION, QUARANTINED, STATE_LABELS, Entry, Rules,
                                key_of)
from synox.health import state as machine

HEALTH_KEY = "synox_health"
TASK_ID = "system.health"
TASK_TIMEOUT = 300.0


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _uid(user) -> Optional[int]:
    uid = user if isinstance(user, int) and not isinstance(user, bool) else getattr(user, "tg_id", None)
    return uid if isinstance(uid, int) and not isinstance(uid, bool) else None


class HealthRegistry:
    """記錄失敗、查狀態、過濾工具清單、重新檢查。執行緒安全；clock 可以換（測試用假時鐘）。"""

    def __init__(self, settings: Optional[dict] = None, store=None, clock: Callable[[], float] = time.time):
        self.settings = settings if settings is not None else health_settings.defaults()
        self.rules = Rules.from_settings(self.settings)
        self.enabled = bool(self.settings.get("enabled", True))
        self.store = store
        self.clock = clock
        self._lock = threading.RLock()
        self.entries: Dict[str, Entry] = store.load() if (store is not None and self.enabled) else {}

    # ── 記錄 ─────────────────────────────────────────────────────────

    def _save(self) -> None:
        if self.store is not None:
            self.store.save(list(self.entries.values()))

    def record_failure(self, tool: str, f: Failure, *, pack: str = "", user=None, tool_version: str = "",
                       untrusted: bool = False) -> Optional[Entry]:
        """記一次失敗。scope=input 不記；scope=user 只記在那個人身上。回那一筆（沒記＝None）。"""
        if not self.enabled or f.scope == "input":
            return None
        uid = _uid(user) if f.scope == "user" else None
        if f.scope == "user" and uid is None:
            return None
        now = self.clock()
        with self._lock:
            key = key_of(tool, uid)
            entry = self.entries.get(key)
            if entry is None:
                entry = self.entries[key] = Entry(tool=tool, pack=pack, user=uid)
            before = entry.state
            fp = machine.fingerprint(pack, tool, f, tool_version)
            after = machine.record_failure(entry, f, fp, self.rules, now, untrusted=untrusted)
            self._save()
        logging.warning("[HEALTH] %s failed: code=%s scope=%s state=%s%s diag=%s", key, f.code, f.scope, after,
                        "" if before == after else f" (was {before})", f.diag)
        return entry

    def record_success(self, tool: str, user=None) -> None:
        if not self.enabled:
            return
        uid = _uid(user)
        keys = [key_of(tool)] + ([key_of(tool, uid)] if uid is not None else [])
        with self._lock:
            changed = False
            for key in keys:
                entry = self.entries.get(key)
                if entry is None:
                    continue
                before = entry.state
                changed = machine.record_success(entry, self.clock()) or changed
                if before != entry.state:
                    logging.info("[HEALTH] %s recovered (was %s)", key, before)
            if changed:
                self._save()

    # ── 查 ───────────────────────────────────────────────────────────

    def hidden(self, tool: str, user=None) -> Optional[Entry]:
        """不給 AI 的那一筆（整個工具的優先，再看這個人自己的）；可以用＝None。"""
        if not self.enabled or not self.entries:
            return None
        uid = _uid(user)
        with self._lock:
            for key in (key_of(tool),) + ((key_of(tool, uid),) if uid is not None else ()):
                entry = self.entries.get(key)
                if entry is not None and entry.hidden:
                    return entry
        return None

    def any_hidden(self) -> bool:
        return self.enabled and any(e.hidden for e in list(self.entries.values()))

    def entry(self, key: str) -> Optional[Entry]:
        return self.entries.get(key)

    def problems(self, tool: Optional[str] = None) -> List[Entry]:
        """不正常的（含試用中的）。tool 有給＝只看那個工具（整個的與每個人的）。"""
        out = [e for e in list(self.entries.values()) if e.state != HEALTHY]
        if tool is not None:
            out = [e for e in out if e.tool == tool]
        return sorted(out, key=lambda e: (e.tool, e.user or 0))

    def due(self) -> List[Entry]:
        """冷卻到了、要重新檢查的（broken、不在試用中）。needs_action／quarantined 不自動檢查。"""
        if not self.enabled:
            return []
        now = self.clock()
        return [e for e in list(self.entries.values())
                if e.state == BROKEN and not e.trial and e.next_check is not None and e.next_check <= now]

    # ── 重新檢查、解除 ────────────────────────────────────────────────

    def check_result(self, entry: Entry, ok: bool) -> None:
        with self._lock:
            if ok:
                machine.record_success(entry, self.clock())
            else:
                machine.check_failed(entry, self.rules, self.clock())
            self._save()
        logging.info("[HEALTH] %s self-check %s → %s", entry.key, "passed" if ok else "failed", entry.state)

    def start_trial(self, entry: Entry) -> bool:
        with self._lock:
            started = machine.start_trial(entry, self.rules, self.clock())
            self._save()
        return started

    def release(self, key: str) -> bool:
        """擁有者解除（任何不正常的狀態，含隔離）。沒有這筆＝False。"""
        with self._lock:
            entry = self.entries.get(key)
            if entry is None:
                return False
            machine.release(entry, self.clock())
            self._save()
        logging.info("[HEALTH] %s released by the owner", key)
        return True

    # ── 顯示 ─────────────────────────────────────────────────────────

    def view(self, entry: Entry, *, owner: bool = False) -> dict:
        info = failures.CODES.get(entry.code)
        out = {"key": entry.key, "tool": entry.tool, "pack": entry.pack, "state": entry.state,
               "label": STATE_LABELS.get(entry.state, entry.state), "code": entry.code,
               "code_label": info.label if info else "", "reason": entry.reason, "count": entry.count,
               "since": _iso(entry.since), "next_check": _iso(entry.next_check), "trial": entry.trial,
               "personal": entry.user is not None}
        if owner:
            out["diag"] = dict(entry.diag)
        return out


# ── 給 AI 看的字（SYNOX 自己產生，不採用工具的文字）──────────────────────

def reason_label(entry: Entry) -> str:
    info = failures.CODES.get(entry.code)
    label = info.label if info else "連續失敗"
    if entry.state == BROKEN:
        return f"{label}，暫停中，稍後會自動重新檢查"
    if entry.state == NEEDS_ACTION:
        return f"{label}，要使用者或擁有者處理"
    return f"{label}，反覆失敗被隔離，要擁有者解除"


def unavailable_line(node, entry: Entry) -> str:
    """系統提示最後那一行，也是 AI 硬叫時回的那一行。"""
    return f"暫時不能用的功能：{getattr(node, 'command', '') or entry.tool}（{reason_label(entry)}）"


# ── fail open 的入口（loader、mcp、agent 用）──────────────────────────────

def of(app) -> Optional[HealthRegistry]:
    try:
        return (getattr(app, "extras", None) or {}).get(HEALTH_KEY)
    except Exception:
        return None


def _probing(api) -> bool:
    return getattr(type(api), "health_probe", False) is True if api is not None else False


def observe_failure(app, api, *, tool: str, pack: str = "", failure: Failure, user=None, tool_version: str = "",
                    untrusted: bool = False) -> None:
    """工具失敗了：交給 AI 的 CaptureApi（它會改回「FAIL …」那一行）；不是重新檢查的話記進隔離清單。"""
    try:
        note = getattr(type(api), "note_failure", None) if api is not None else None
        if callable(note):
            note(api, failure)
        if _probing(api):
            return
        reg = of(app)
        if reg is not None:
            reg.record_failure(tool, failure, pack=pack, user=user, tool_version=tool_version,
                               untrusted=untrusted or not failure.declared)
    except Exception:
        logging.exception("[HEALTH] observe_failure for %s failed (ignored: fail open)", tool)


def observe_success(app, api, tool: str, user=None) -> None:
    try:
        if _probing(api):
            api.note_success()
            return
        reg = of(app)
        if reg is not None:
            reg.record_success(tool, user)
    except Exception:
        logging.exception("[HEALTH] observe_success for %s failed (ignored: fail open)", tool)


def hidden(app, tool: str, user=None) -> Optional[Entry]:
    try:
        reg = of(app)
        return reg.hidden(tool, user) if reg is not None else None
    except Exception:
        logging.exception("[HEALTH] lookup for %s failed (ignored: fail open)", tool)
        return None


def any_hidden(app) -> bool:
    try:
        reg = of(app)
        return reg is not None and reg.any_hidden()
    except Exception:
        logging.exception("[HEALTH] any_hidden failed (ignored: fail open)")
        return False


def prompt_lines(app) -> int:
    reg = of(app)
    try:
        return int(reg.settings.get("prompt_lines", 5)) if reg is not None else 0
    except Exception:
        return 0


def manual_warning(app, tool: str, user=None) -> str:
    """人自己打的指令：這一版照常執行，只在前面多一行警告（"" ＝正常）。"""
    entry = hidden(app, tool, user)
    if entry is None:
        return ""
    return f"⚠️ 這個工具目前{STATE_LABELS.get(entry.state, entry.state)}（{reason_label(entry)}）；照你的指令先試一次。"


# ── 重新檢查（runtime 任務 system.health）────────────────────────────────

class ProbeApi:
    """重新檢查用的 Channel：via_ai（cli 同步跑、有逾時）、什麼都不送出去、記下失敗。不經 AI。"""
    via_ai = True
    health_probe = True

    def __init__(self):
        self.failure: Optional[Failure] = None
        self.succeeded = False              # cli／mcp 真的跑完而且成功（沒連接、檔案被改過這類「沒跑」不算過）
        self.carded = False
        self.lines: List[str] = []

    def note_failure(self, f: Failure) -> None:
        self.failure = f

    def note_success(self) -> None:
        self.succeeded = True

    def mark_carded(self) -> None:
        self.carded = True

    def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.lines.append(str(text)[:300])
        return {"ok": True, "result": {"message_id": 0}}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **kw: {"ok": True, "result": {"message_id": 0}}


def _pack_of(app, entry: Entry):
    return next((p for p in app.extras.get("synox_packs", []) if p.name == entry.pack), None)


def check_node(app, entry: Entry):
    """這個工具的 pack 在 pack.json `health.check` 宣告的自我檢查指令節點；沒宣告、找不到、不是唯讀＝None。"""
    from isdtelekit.core.registry import READ
    pack = _pack_of(app, entry)
    if pack is None:
        return None
    m = pack.manifest
    name = (getattr(m, "health", None) or {}).get("check")
    if not name:
        return None
    if m.kind == "mcp":
        from synox.packs import mcp as pack_mcp
        name = pack_mcp.unique_identifiers(list(m.mcp.get("tools_allow") or [])).get(name, name)
    node = app.registry.node(f"{m.group}.{name}")
    if node is None or node.is_group or node.effect != READ:
        return None
    return node


def probe(app, node, user, *, needs_success: bool = True) -> bool:
    """跑一次自我檢查（既有的執行路徑，經 ProbeApi）。丟例外、回失敗信封、要確認＝沒過。
    needs_success（kind=cli／mcp）：還要真的跑完、回了成功（沒連接、檔案被改過、參數不對這類「沒跑」不算過）；
    kind=python 沒有信封，沒丟例外就算過。"""
    api = ProbeApi()
    try:
        node.fn(api, getattr(user, "tg_id", 0), user, [])
    except Exception as e:
        logging.warning("[HEALTH] self-check %s raised %s", node.path, type(e).__name__)
        return False
    return api.failure is None and not api.carded and (api.succeeded or not needs_success)


def _user_for(app, entry: Entry):
    uid = entry.user if entry.user is not None else getattr(app.config, "owner_id", None)
    users = getattr(app, "users", None)
    if users is None or uid is None:
        return None
    return users.get(int(uid)) or users.get_or_create(int(uid))


def recheck(app, entry: Entry, *, manual: bool = False) -> str:
    """重新檢查一筆：有自我檢查就跑它（過了放回、沒過下一段冷卻）；沒有就放回清單試用一次。回一句結果（給任務日誌）。
    manual＝擁有者在網頁按的（needs_action 只有這樣才檢查）。quarantined 不檢查（要先解除）。
    來源一律是 system（ADR 0025 §2）：自我檢查是 SYNOX 自己叫的，不是人打的。"""
    from synox.guard.origin import Origin, using
    with using(Origin("system", 0, surface="health")):
        return _recheck(app, entry, manual=manual)


def _recheck(app, entry: Entry, *, manual: bool = False) -> str:
    reg = of(app)
    if reg is None or entry.state == QUARANTINED:
        return ""
    if entry.state == NEEDS_ACTION and not manual:
        return f"{entry.key}：要人處理，等擁有者按「重新檢查」"
    node = check_node(app, entry)
    if node is None:
        if entry.state not in (BROKEN, NEEDS_ACTION):
            return ""
        started = reg.start_trial(entry)
        return f"{entry.key}：放回清單試用一次" if started else f"{entry.key}：今天的試用次數用完了"
    user = _user_for(app, entry)
    pack = _pack_of(app, entry)
    ok = probe(app, node, user, needs_success=getattr(getattr(pack, "manifest", None), "kind", "cli") != "python")
    reg.check_result(entry, ok)
    return f"{entry.key}：自我檢查{'過了' if ok else '沒過'}"


def tick(app) -> str:
    """runtime 任務：冷卻到了的逐一重新檢查。過程不叫 AI。"""
    reg = of(app)
    if reg is None or not reg.enabled:
        return "關閉"
    done = [recheck(app, e) for e in reg.due()]
    return "；".join(d for d in done if d) or "沒有要檢查的"


def install(app, config, vault=None, *, clock: Optional[Callable[[], float]] = None) -> HealthRegistry:
    """建 HealthRegistry（存檔在保管箱）、登記 runtime 任務。出錯一律當作沒有健康管理（fail open）。"""
    from synox.health.store import HealthStore
    settings = getattr(config, "health", None) or health_settings.defaults()
    try:
        store = HealthStore(vault, getattr(config, "data_dir", "")) if vault is not None else None
        reg = HealthRegistry(settings, store, clock=clock or time.time)
    except Exception:
        logging.exception("[HEALTH] cannot start; every tool counts as healthy")
        reg = HealthRegistry(dict(settings, enabled=False))
    app.extras[HEALTH_KEY] = reg
    if reg.enabled:
        try:
            from synox import runtime
            rt = runtime.of(app)
            if rt is not None:
                rt.loop.register(TASK_ID, "🩺 工具健康", fn=lambda ctx: tick(app),
                                 interval=float(settings.get("check_interval_s", 60)), timeout=TASK_TIMEOUT)
        except Exception:
            logging.exception("[HEALTH] cannot register %s", TASK_ID)
    return reg


__all__ = ["BROKEN", "Failure", "HEALTHY", "HIDDEN", "HealthRegistry", "NEEDS_ACTION", "ProbeApi", "QUARANTINED",
           "TASK_ID", "any_hidden", "check_node", "failures", "hidden", "install", "manual_warning", "observe_failure",
           "observe_success", "of", "probe", "prompt_lines", "reason_label", "recheck", "tick", "unavailable_line"]
