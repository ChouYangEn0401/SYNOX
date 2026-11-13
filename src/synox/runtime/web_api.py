"""
/api/runtime/...（合約 docs/runtime-api.md）。web/server.py 的 WebUI.api 把這個前綴整個轉過來；
登入、CSRF、Origin 已經在 WebUI.route 檢查過，這裡只做「只給擁有者」與各 API。

route(ui, user, method, path, body) -> Resp（(status, headers, body)，跟 server.py 一樣的形狀）
"""

from __future__ import annotations

import json
import logging
import re

from synox import runtime as runtime_mod
from synox.runtime.ledger import LedgerError
from synox.runtime.loop import iso
from synox.runtime.soul import SoulError

TASK_LOG_RE = re.compile(r"^/api/runtime/tasks/([a-z0-9][a-z0-9._-]{0,63})/log$")
RULE_RESET_RE = re.compile(r"^/api/runtime/activator/rules/([a-z0-9][a-z0-9._-]{0,127})/reset$")
PENDING_DISMISS_RE = re.compile(r"^/api/runtime/activator/pending/([0-9a-f]{8})/dismiss$")


def _json(status, data):
    from synox.web.server import _json as web_json
    return web_json(status, data)


def _err(status, message):
    return _json(status, {"error": message})


def _body(body: bytes):
    """(dict, 錯誤 Resp 或 None)。"""
    try:
        data = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (ValueError, UnicodeDecodeError):
        return None, _err(400, "送來的不是 JSON。")
    if not isinstance(data, dict):
        return None, _err(400, "送來的 JSON 要是物件。")
    return data, None


def route(ui, user, method: str, path: str, body: bytes):
    if not ui.is_owner(user):
        return _err(403, "只有擁有者能做這件事。")
    rt = runtime_mod.of(ui.app)
    if rt is None:
        return _err(503, "常駐助理沒有啟用（runtime 沒有裝上）。")
    if method == "GET":
        if path == "/api/runtime/status":
            return _json(200, rt.status())
        if path == "/api/runtime/soul":
            return soul_get(rt)
        if path == "/api/runtime/soul/notes":
            return ledger_call(rt, lambda ledger: ledger.view())
        if path == "/api/runtime/soul/export":
            return ledger_call(rt, lambda ledger: ledger.export())
        m = TASK_LOG_RE.match(path)
        if m:
            task = rt.loop.task(m.group(1))
            if task is None:
                return _err(404, "沒有這個任務。")
            return _json(200, {"lines": list(task.log)})
        return _err(404, "沒有這個 API。")
    if method == "PUT":
        if path == "/api/runtime/soul":
            data, bad = _body(body)
            return bad or soul_put(rt, data)
        return _err(405, "這個 API 不收 PUT。") if path.startswith("/api/runtime/") else _err(404, "沒有這個 API。")
    if method != "POST":
        return _err(405, "只收 GET、POST、PUT。")
    data, bad = _body(body)
    if bad:
        return bad
    if path == "/api/runtime/heartbeat":
        return heartbeat_post(ui, rt, data)
    if path == "/api/runtime/keep-awake":
        return keep_awake_post(ui, rt, data)
    if path == "/api/runtime/heartbeat/run-now":
        from synox.runtime.heartbeat import TASK_ID
        if rt.loop.run_now(TASK_ID, manual=True):
            return _json(200, {"ok": True, "message": "開始巡了，做完會更新「上一次的結果」。"})
        return _json(200, {"ok": False, "message": "正在巡，等它做完再按。"})
    if path == "/api/runtime/mother/reset-memory":
        rt.mother.reset_memory()
        return _json(200, {"ok": True})
    if path in SOUL_POSTS:
        return SOUL_POSTS[path](rt, data)
    if path.startswith("/api/runtime/activator/"):
        return activator_post(rt, path)
    return _err(404, "沒有這個 API。")


def activator_post(rt, path: str):
    """連動（docs/adr/0004）：重設一條暫停的規則、恢復全部、現在處理待處理、丟掉一件待處理。"""
    act = rt.activator
    if act is None:
        return _err(503, "連動沒有裝上。")
    m = RULE_RESET_RE.match(path)
    if m:
        if not act.reset_rule(m.group(1)):
            return _err(404, "沒有這條連動規則。")
        return _json(200, {"ok": True, "message": "重設了，這條規則會再照常動作。"})
    if path == "/api/runtime/activator/resume":
        was = act.resume()
        return _json(200, {"ok": True, "message": "恢復了，連動會再照常動作。" if was else "本來就沒有全部暫停。"})
    if path == "/api/runtime/activator/pending/run":
        n = act.drain()
        return _json(200, {"ok": True, "count": n,
                           "message": f"開始處理 {n} 件。" if n else "沒有可以處理的（暫停中的規則留著，重設後再處理）。"})
    m = PENDING_DISMISS_RE.match(path)
    if m:
        if not act.dismiss(m.group(1)):
            return _err(404, "沒有這件待處理（可能已經處理掉了）。")
        return _json(200, {"ok": True})
    return _err(404, "沒有這個 API。")


def heartbeat_post(ui, rt, data: dict):
    enabled = data.get("enabled")
    interval = data.get("interval_min")
    if enabled is not None and not isinstance(enabled, bool):
        return _err(400, "enabled 要是 true 或 false。")
    if interval is not None:
        from synox.runtime import settings as rs
        problem = rs.interval_problem(interval)
        if problem:
            return _err(400, problem)
    view = rt.heartbeat.update(enabled=enabled, interval_min=interval)
    _write_config(ui, rt)
    return _json(200, view)


def keep_awake_post(ui, rt, data: dict):
    """保持清醒（docs/adr/0006）：開關、閒置幾分鐘請 Windows 關螢幕。預設關。
    打開＝覆蓋 Windows 電源選項的「睡眠」設定（電腦不再自動睡眠）；螢幕仍可照電源計畫或閒置 N 分鐘後關。
    回的 view 帶 notice（這段提醒）、tagline、modern_standby／modern_standby_note，介面照著顯示。"""
    ka = rt.keep_awake
    if ka is None:
        return _err(503, "保持清醒沒有裝上。")
    enabled = data.get("enabled")
    minutes = data.get("screen_off_after_min")
    if enabled is not None and not isinstance(enabled, bool):
        return _err(400, "enabled 要是 true 或 false。")
    try:
        view = ka.update(enabled=enabled, screen_off_after_min=minutes)
    except ValueError as e:
        return _err(400, str(e))
    _write_config(ui, rt, section="keep_awake")
    return _json(200, view)


def _write_config(ui, rt, section: str = "heartbeat") -> None:
    """改過的心跳設定寫回 config.json（跟設定頁存 AI 來源同一套 read_existing／write_config）。"""
    from synox.wizard import logic
    path = rt.config_path or getattr(ui, "config_path", "")
    if not path:
        return
    try:
        cfg = logic.read_existing(path)
        runtime = cfg.get("runtime") if isinstance(cfg.get("runtime"), dict) else {}
        if section == "keep_awake":
            values = {"enabled": rt.keep_awake.enabled, "screen_off_after_min": rt.keep_awake.screen_off_after_min}
        else:
            values = {"enabled": rt.heartbeat.enabled, "interval_min": rt.heartbeat.interval_min}
        block = runtime.get(section) if isinstance(runtime.get(section), dict) else {}
        block.update(values)
        runtime[section] = block
        cfg["runtime"] = runtime
        logic.write_config(path, cfg)
        conf = getattr(ui.config, "runtime", None)
        if isinstance(conf, dict):
            conf.setdefault(section, {}).update(values)
    except Exception:
        logging.exception("[RUNTIME] cannot write %s settings to config.json", section)


def soul_get(rt):
    try:
        return _json(200, {"text": rt.soul.text(), "updated_at": iso(rt.soul.updated_at())})
    except SoulError as e:
        return _err(503, str(e))


def soul_put(rt, data: dict):
    text = data.get("text")
    if not isinstance(text, str):
        return _err(400, "text 要是字串。")
    if not rt.soul.available:
        return _err(503, "保管箱沒有打開，soul.md 讀寫不了（python -m synox doctor 看原因）。")
    try:
        saved = rt.soul.write(text, by="owner")
    except SoulError as e:
        return _err(400, str(e))
    return _json(200, {"ok": True, "text": saved["text"], "updated_at": iso(saved["updated_at"])})


# ── soul 帳本（docs/adr/0005）：助理筆記的來歷、提議、收起來的、整理、遺忘、匯出 ──────────

def ledger_call(rt, fn):
    """叫 soul 帳本做一件事，回它給的 dict。保管箱沒開＝503；其他說得出口的錯＝400。內容不寫 log。"""
    ledger = getattr(rt, "ledger", None)
    if ledger is None or not ledger.available:
        return _err(503, "保管箱沒有打開，助理筆記讀寫不了（python -m synox doctor 看原因）。")
    try:
        return _json(200, fn(ledger))
    except LedgerError as e:
        return _err(400, str(e))
    except SoulError as e:
        return _err(503, str(e))


def _text_field(data: dict, key: str):
    """(字串, 錯誤 Resp 或 None)：body 裡那個欄位要是非空字串。"""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        return "", _err(400, f"{key} 要是字串。")
    return value.strip(), None


def proposal_post(rt, data: dict):
    pid, bad = _text_field(data, "id")
    if bad:
        return bad
    action = data.get("action")
    if action not in ("approve", "replace", "reject"):
        return _err(400, "action 要是 approve、replace 或 reject。")
    if action == "reject":
        return ledger_call(rt, lambda ledger: ledger.reject(pid))
    return ledger_call(rt, lambda ledger: ledger.approve(pid, replace=action == "replace"))


def note_post(rt, data: dict):
    item, bad = _text_field(data, "id")
    if bad:
        return bad
    action = data.get("action")
    if action not in ("retire", "confirm", "restore"):
        return _err(400, "action 要是 retire、confirm 或 restore。")
    return ledger_call(rt, lambda ledger: getattr(ledger, action)(item))


def forget_post(rt, data: dict):
    text, bad = _text_field(data, "text")
    if bad:
        return bad
    confirm = data.get("confirm", False)
    if not isinstance(confirm, bool):
        return _err(400, "confirm 要是 true 或 false。")
    return ledger_call(rt, lambda ledger: ledger.forget(text, confirm=confirm))


def tidy_post(rt, data: dict):
    def run(ledger):
        result = ledger.tidy()
        return {"ok": True, "message": result["summary"], "notes": ledger.view()}
    return ledger_call(rt, run)


SOUL_POSTS = {"/api/runtime/soul/proposal": proposal_post, "/api/runtime/soul/note": note_post,
              "/api/runtime/soul/forget": forget_post, "/api/runtime/soul/tidy": tidy_post}
