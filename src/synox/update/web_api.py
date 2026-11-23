"""
/api/settings/update…：網頁設定「💻 電腦與備份」的「SYNOX 更新」卡片＋網頁頂端的「有新版」橫幅。全部只有擁有者。

    GET  /api/settings/update           現況（不連網）：版本、每週檢查開關、上次的結果、怎麼裝的、能不能按「更新」
    POST /api/settings/update/check     現在查一次（連 GitHub；順便算有幾個工具可以更新）
    POST /api/settings/update/weekly    {"enabled": true|false}：每週檢查開關（寫 config.json 的 updates.check）
    POST /api/settings/update/channel   {"preview": true|false}：「也提醒我有測試版」（寫 config.json 的 updates.channel；
                                        預設 stable）。卡片不管這個開關，都顯示「最新正式版」「最新測試版」兩行
    POST /api/settings/update/dismiss   橫幅按「知道了」：這個版本不再顯示橫幅
    POST /api/settings/update/launch    只在 Windows、ZIP 裝法：打開 Update.bat（它自己先給人看說明、再問一次）
    POST /api/settings/update/start     {"version": "X"}：網頁一鍵更新（docs/adr/0047）。背景跑 prepare（下載、SHA256、**一定要有
                                        簽章而且驗過**、解開；查到的一定要正好是 X）→ 打開 `Update.bat -Apply -FromWeb`（停 SYNOX、
                                        換檔、套件有變才重裝、確認版本、出事自動退回、開回來）。進度看 GET 的 job
    POST /api/settings/update/rollback  {"confirm": true}：回到上一版（`Update.bat -Rollback -FromWeb`；_previous 裡要有舊版）
    POST /api/settings/update/deps      再試一次「補裝套件」（update/deps.py，跟啟動時同一個；背景跑，看 GET 的 deps_job）

換檔不在 SYNOX 自己的程序裡做：SYNOX 正在跑時換不了自己（ADR 0023 決定 U4），所以一律交給 update.ps1（Update.bat）。
POST 會經過門禁的手機驗證器（guard/stepup.py：/api/settings/ 底下預設就算敏感；check、dismiss 不改東西，列在例外）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from typing import Optional

from synox import __version__
from synox.update import check as upd

LAUNCH_TEXT = {
    "not_windows": "這台不是 Windows：請照下面的步驟手動更新。",
    "not_zip": "這種裝法不能從網頁更新：",
    "missing": "找不到 Update.bat（可能是舊版的 SYNOX）：請照發佈頁的「怎麼更新」手動做。",
    "launched": "已經打開「SYNOX 更新」的視窗（Update.bat）：照視窗裡說的做（它會先給你看這版改了什麼，再問一次）。"
                "更新時 SYNOX 會暫時關掉，網頁會斷線；好了之後重新整理這一頁。",
    "failed": "打不開 Update.bat：{e}。可以到 SYNOX 資料夾自己點兩下 Update.bat。",
}

WEB_TEXT = {
    "no_script": "找不到 Update.bat 或 setup\\update.ps1（可能是舊版的 SYNOX）：請照發佈頁的「怎麼更新」手動做。",
    "busy": "已經在更新了，等它做完。",
    "deps_busy": "已經在補裝套件了，等它做完。",
    "no_version": "要說更新到哪一版（先按「檢查更新」）。",
    "not_seen": "這一版不是上次「檢查更新」看到的新版：請先重新按「檢查更新」。",
    "unsigned": "這一版沒有簽章，網頁不會自動換（不能確定檔案是維護者發的）。要換：按「打開更新視窗…」，在視窗裡自己決定"
                "（Update.bat -AllowUnsigned），或照發佈頁手動做。",
    "preview_off": "這一版是測試版，但你只收正式版（「也提醒我有測試版」沒打開）。要裝測試版先打開那一格、再檢查一次。",
    "confirm": "要先確認。",
    "no_previous": "沒有可以退回的舊版（_previous 是空的：還沒用 Update.bat／網頁更新過）。",
    "preparing": "下載並檢查 {v}（這時候 SYNOX 照常可以用）…",
    "verified": "檔案和簽章都驗過了。",
    "launching": "SYNOX 會暫時關掉、換成 {v}、再自己開起來；這一頁好了會自己重新整理。",
    "launched": "已經交給「SYNOX 更新」視窗：換檔中…",
    "rollback_launched": "已經交給「SYNOX 更新」視窗：退回 {v} 中…",
    "launch_failed": "打不開更新視窗（{e}）：可以到 SYNOX 資料夾自己點兩下 Update.bat。",
    "error": "更新沒有開始：{e}",
    "crashed": "準備更新時出錯（{e}），什麼都沒有換。",
}

JOB_KEY = "_synox_update_job"
DEPS_KEY = "_synox_deps_job"
_LOCK = threading.Lock()


def _json(code: int, data) -> tuple:
    return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps(data, ensure_ascii=False).encode("utf-8")


def _err(code: int, message: str) -> tuple:
    return _json(code, {"error": message})


def _root(web) -> str:
    return os.path.abspath(getattr(web.config, "root", "."))


def _data_dir(web) -> str:
    return getattr(web.config, "data_dir", os.path.join(_root(web), "data"))


def status(web) -> dict:
    from synox.wizard import logic
    root = _root(web)
    kind = upd.install_kind(root)
    state = upd.load_state(_data_dir(web))
    last = state.get("result") if isinstance(state.get("result"), dict) else None
    raw = logic.read_existing(web.config_path)
    preview = upd.wants_preview(raw)
    notice = None
    if last and last.get("status") == "newer" and last.get("latest") and state.get("dismissed") != last.get("latest") \
            and upd.compare(__version__, last["latest"]) == "newer" and (preview or "-" not in last["latest"]):
        # 改回只收正式版之後，上次查到的測試版不再出橫幅
        notice = {"latest": last["latest"], "security": bool(last.get("security")), "notes_url": last.get("notes_url")}
    can = can_update(root, kind)
    from synox.update import deps
    return {"installed": __version__, "weekly": upd.weekly_enabled(raw), "channel": upd.channel(raw),
            "kind": kind, "how": upd.how_line(kind), "releases": upd.RELEASES_PAGE, "last": last, "notice": notice,
            "can_launch": os.name == "nt" and kind == "zip" and os.path.isfile(os.path.join(root, "Update.bat")),
            # 網頁一鍵更新（ADR 0047）：Windows＋ZIP 裝法＋有 Update.bat 與 update.ps1
            "can_update": can, "previous": previous_versions(root) if can else [],
            "job": _public(getattr(web, JOB_KEY, None)), "boot": getattr(web, "boot_id", ""),
            "last_update": last_update(_data_dir(web)), "deps": deps.last_result(_data_dir(web)),
            "deps_job": _public(getattr(web, DEPS_KEY, None))}


def can_update(root: str, kind: Optional[str] = None) -> bool:
    kind = kind or upd.install_kind(root)
    return os.name == "nt" and kind == "zip" and os.path.isfile(os.path.join(root, "Update.bat")) \
        and os.path.isfile(os.path.join(root, "setup", "update.ps1"))


def previous_versions(root: str) -> list:
    """_previous\\ 裡可以退回的舊版（資料夾名，最新的在前；. 開頭的是退回時的暫存，不算）。跟 update.ps1 的
    Get-PreviousFolders 同一個規則（那邊照建立時間，這裡照修改時間，搬進來的資料夾兩個一樣）。"""
    folder = os.path.join(root, "_previous")
    try:
        names = [n for n in os.listdir(folder) if not n.startswith(".") and os.path.isdir(os.path.join(folder, n))]
    except OSError:
        return []
    return sorted(names, key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True)


def last_update(data_dir: str) -> Optional[dict]:
    """update.ps1 寫的 data/update_last.json（上一次換版本或退回的結果）：{action, from, to, ok, rolled_back, at}。"""
    try:
        with open(os.path.join(data_dir, "update_last.json"), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    keep = ("action", "from", "to", "ok", "rolled_back", "signed", "at")
    return {k: data[k] for k in keep if k in data and isinstance(data[k], (str, bool, int, float))}


def _public(job: Optional[dict]) -> Optional[dict]:
    if not isinstance(job, dict):
        return None
    with _LOCK:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in job.items() if not k.startswith("_")}


def _tools_counter(web):
    def count() -> Optional[int]:
        return upd.tools_newer_count(web._installed_versions(), opener=getattr(web, "catalog_opener", None))
    return count


def route(web, user, method: str, path: str, body: bytes):
    denied = web._owner_only(user)
    if denied:
        return denied
    if method == "GET":
        if path == "/api/settings/update":
            return _json(200, status(web))
        return _err(404, "沒有這個 API。")
    if method != "POST":
        return _err(405, "只收 GET、POST。")
    try:
        data = json.loads(body.decode("utf-8") or "{}") if body else {}
    except (ValueError, UnicodeDecodeError):
        return _err(400, "送來的不是 JSON。")
    if not isinstance(data, dict):
        return _err(400, "送來的 JSON 要是物件。")
    if path == "/api/settings/update/check":
        from synox.wizard import logic
        result = upd.check(__version__, root=_root(web), opener=getattr(web, "update_opener", None),
                           tools=_tools_counter(web),
                           include_prerelease=upd.wants_preview(logic.read_existing(web.config_path)))
        try:
            upd.remember(_data_dir(web), result)
        except OSError:
            logging.warning("[UPDATE] cannot save the check result", exc_info=True)
        logging.info("[WEB] %s checked for updates: %s %s", user.tg_id, result.status, result.latest)
        return _json(200, {**status(web), "result": result.to_dict()})
    if path == "/api/settings/update/weekly":
        from synox.wizard import logic
        cfg = logic.read_existing(web.config_path)
        if not cfg:
            return _err(400, "讀不到 config.json，沒有存（重跑 Setup.bat）。")
        logic.write_config(web.config_path, upd.set_mode(cfg, bool(data.get("enabled"))))
        logging.info("[WEB] %s set the weekly update check %s", user.tg_id, "on" if data.get("enabled") else "off")
        return _json(200, status(web))
    if path == "/api/settings/update/channel":
        from synox.wizard import logic
        cfg = logic.read_existing(web.config_path)
        if not cfg:
            return _err(400, "讀不到 config.json（先跑一次 Setup.bat）")
        on = data.get("preview") is True
        logic.write_config(web.config_path, upd.set_channel(cfg, on))
        logging.info("[WEB] %s set the update channel to %s", user.tg_id, "preview" if on else "stable")
        return _json(200, status(web))
    if path == "/api/settings/update/dismiss":
        state = upd.load_state(_data_dir(web))
        last = state.get("result") if isinstance(state.get("result"), dict) else {}
        if last.get("latest"):
            state["dismissed"] = last["latest"]
            upd.save_state(_data_dir(web), state)
        return _json(200, status(web))
    if path == "/api/settings/update/launch":
        return launch(web, user)
    if path == "/api/settings/update/start":
        return start(web, user, data)
    if path == "/api/settings/update/rollback":
        return rollback(web, user, data)
    if path == "/api/settings/update/deps":
        return deps_retry(web, user)
    return _err(404, "沒有這個 API。")


def launch(web, user, popen=subprocess.Popen):
    root = _root(web)
    kind = upd.install_kind(root)
    if os.name != "nt":
        return _err(400, LAUNCH_TEXT["not_windows"])
    if kind != "zip":
        return _err(400, LAUNCH_TEXT["not_zip"] + upd.how_line(kind))
    bat = os.path.join(root, "Update.bat")
    if not os.path.isfile(bat):
        return _err(400, LAUNCH_TEXT["missing"])
    try:
        # start＝另開一個視窗、跟 SYNOX 脫鉤（update.ps1 停 SYNOX 時用 taskkill /T，不能是 SYNOX 的子行程）
        popen(["cmd", "/c", "start", "SYNOX Update", bat], cwd=root,
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        return _err(500, LAUNCH_TEXT["failed"].format(e=e))
    logging.info("[WEB] %s opened Update.bat", user.tg_id)
    return _json(200, {"ok": True, "message": LAUNCH_TEXT["launched"]})


# ── 網頁一鍵更新、退回、補裝套件（docs/adr/0047）──────────────────────────

def _spawn(web, fn) -> None:
    """背景跑（測試換成馬上跑：web.update_spawn）。"""
    custom = getattr(web, "update_spawn", None)
    if custom is not None:
        custom(fn)
        return
    threading.Thread(target=fn, name="synox-update", daemon=True).start()


def _audit(web, event: str, user, target: str, ok: bool, code: str = "") -> None:
    try:
        from synox import guard
        g = guard.of(web.app)
        if g is not None and g.audit is not None:
            g.audit.write(event, by=user.tg_id, origin="web", target=target, ok=ok, code=code)
    except Exception:
        logging.debug("[UPDATE] audit failed", exc_info=True)


def _open_updater(web, root: str, args: list) -> Optional[str]:
    """打開 `Update.bat <args>`（cmd /c start：另開一個看得見的視窗、跟 SYNOX 脫鉤；update.ps1 停 SYNOX 時用 taskkill /T，
    不能是 SYNOX 的子行程）。成功回 None，失敗回原因。"""
    popen = getattr(web, "update_popen", None) or subprocess.Popen
    try:
        popen(["cmd", "/c", "start", "SYNOX Update", os.path.join(root, "Update.bat")] + list(args), cwd=root,
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        return str(e)
    return None


def _precheck(root: str) -> Optional[tuple]:
    kind = upd.install_kind(root)
    if os.name != "nt":
        return _err(400, LAUNCH_TEXT["not_windows"])
    if kind != "zip":
        return _err(400, LAUNCH_TEXT["not_zip"] + upd.how_line(kind))
    if not can_update(root, kind):
        return _err(400, WEB_TEXT["no_script"])
    return None


LAUNCHED_HOLD = 15 * 60                  # 秒：交給 Update.bat 之後這段時間不再開第二個（它會停掉這支 SYNOX）


def _busy(job: Optional[dict], states=("preparing", "launching")) -> bool:
    if not isinstance(job, dict):
        return False
    if job.get("state") == "launched" and "launched" not in states:
        return time.time() - float(job.get("started") or 0) < LAUNCHED_HOLD
    return job.get("state") in states


def _say(job: dict, text) -> None:
    with _LOCK:
        job["lines"].append(str(text))
        del job["lines"][:-40]


def _set(job: dict, **kw) -> None:
    with _LOCK:
        job.update(kw)


def start(web, user, data: dict):
    """「更新到 X」：只收上次檢查看到、比較新、**有簽章**的那一版；背景 prepare → 打開 Update.bat -Apply -FromWeb。"""
    from synox.wizard import logic
    root = _root(web)
    bad = _precheck(root)
    if bad:
        return bad
    version = data.get("version") if isinstance(data.get("version"), str) else ""
    if not version:
        return _err(400, WEB_TEXT["no_version"])
    last = upd.load_state(_data_dir(web)).get("result")
    if not (isinstance(last, dict) and last.get("status") == "newer" and last.get("latest") == version
            and upd.compare(__version__, version) == "newer"):
        return _err(400, WEB_TEXT["not_seen"])
    if not last.get("signed"):
        return _err(400, WEB_TEXT["unsigned"])
    preview = upd.wants_preview(logic.read_existing(web.config_path))
    if (last.get("prerelease") or "-" in version) and not preview and not upd.test_api():
        return _err(400, WEB_TEXT["preview_off"])
    with _LOCK:
        if _busy(getattr(web, JOB_KEY, None)):
            return _err(409, WEB_TEXT["busy"])
        job = {"action": "update", "state": "preparing", "version": version, "from": __version__,
               "lines": [WEB_TEXT["preparing"].format(v=version)], "message": "", "started": time.time()}
        setattr(web, JOB_KEY, job)
    logging.info("[WEB] %s started the web update to %s", user.tg_id, version)
    _spawn(web, lambda: _run_update(web, user, job, root, version, preview))
    return _json(200, status(web))


def _run_update(web, user, job: dict, root: str, version: str, preview: bool) -> None:
    from synox.update import prepare as prep
    try:
        ready = prep.prepare(root, allow_unsigned=False, opener=getattr(web, "update_opener", None),
                             keys=getattr(web, "update_keys", None), say=lambda t: _say(job, t),
                             include_prerelease=preview, expect=version)
    except prep.AlreadyCurrent as e:
        _set(job, state="current", message=str(e))
        return
    except upd.UpdateError as e:
        _set(job, state="failed", message=str(e))
        _audit(web, "update", user, version, False, "prepare")
        return
    except Exception as e:                                   # 什麼都沒換；記下來
        logging.exception("[UPDATE] web update failed while preparing")
        _set(job, state="failed", message=WEB_TEXT["crashed"].format(e=type(e).__name__))
        return
    if not ready.get("signed") or ready.get("version") != version:      # prepare 已經擋過；再看一次（不收沒簽章的）
        _discard(root, ready)
        _set(job, state="failed", message=WEB_TEXT["unsigned"])
        return
    _say(job, WEB_TEXT["verified"])
    _set(job, state="launching", message=WEB_TEXT["launching"].format(v=version))
    why = _open_updater(web, root, ["-Apply", "-FromWeb"])
    if why:
        _discard(root, ready)
        _set(job, state="failed", message=WEB_TEXT["launch_failed"].format(e=why))
        _audit(web, "update", user, version, False, "launch")
        return
    _set(job, state="launched", message=WEB_TEXT["launched"], rebuild_venv=bool(ready.get("rebuild_venv")))
    _audit(web, "update", user, version, True)
    logging.info("[WEB] %s: Update.bat -Apply opened for %s", user.tg_id, version)


def _discard(root: str, ready: dict) -> None:
    """準備好、但沒交出去的那一份（ready.json 與 data/update/<版本>/）丟掉；只動 data/update 底下。"""
    import shutil
    base = os.path.abspath(os.path.join(root, "data", "update"))
    try:
        os.remove(os.path.join(base, "ready.json"))
    except OSError:
        pass
    work = os.path.abspath(os.path.join(base, str(ready.get("version") or "")))
    if work != base and os.path.dirname(work) == base:
        shutil.rmtree(work, ignore_errors=True)


def rollback(web, user, data: dict):
    """「回到上一版」：_previous 裡最新的那一份（Update.bat -Rollback -FromWeb，既有的 Restore-Previous）。"""
    root = _root(web)
    bad = _precheck(root)
    if bad:
        return bad
    if data.get("confirm") is not True:
        return _err(400, WEB_TEXT["confirm"])
    prev = previous_versions(root)
    if not prev:
        return _err(400, WEB_TEXT["no_previous"])
    with _LOCK:
        if _busy(getattr(web, JOB_KEY, None)):
            return _err(409, WEB_TEXT["busy"])
        job = {"action": "rollback", "state": "launching", "version": prev[0], "from": __version__, "lines": [],
               "message": "", "started": time.time()}
        setattr(web, JOB_KEY, job)
    why = _open_updater(web, root, ["-Rollback", "-FromWeb"])
    if why:
        _set(job, state="failed", message=WEB_TEXT["launch_failed"].format(e=why))
        _audit(web, "update_rollback", user, prev[0], False, "launch")
        return _err(500, job["message"])
    _set(job, state="launched", message=WEB_TEXT["rollback_launched"].format(v=prev[0]))
    _audit(web, "update_rollback", user, prev[0], True)
    logging.info("[WEB] %s asked to roll back to %s", user.tg_id, prev[0])
    return _json(200, status(web))


def deps_retry(web, user):
    """卡片的「再試一次」：背景跑啟動時同一個套件補裝（不管上次失敗多久以前）。"""
    from synox.update import deps
    root, data_dir = _root(web), _data_dir(web)
    with _LOCK:
        if _busy(getattr(web, DEPS_KEY, None), ("running",)):
            return _err(409, WEB_TEXT["deps_busy"])
        job = {"state": "running", "lines": [], "started": time.time()}
        setattr(web, DEPS_KEY, job)

    def run():
        sync = getattr(web, "deps_sync", None) or deps.sync
        try:
            result = sync(root, data_dir, say=lambda t: _say(job, t), force=True)
        except Exception as e:                               # deps.sync 自己不丟；保險
            logging.exception("[DEPS] retry failed")
            result = {"ok": False, "fixed": [], "lines": [f"⚠️ {type(e).__name__}"]}
        _set(job, state="done", ok=bool(result.get("ok")), fixed=len(result.get("fixed") or []),
             lines=list(result.get("lines") or job["lines"]))
    logging.info("[WEB] %s asked to reinstall SYNOX's packages", user.tg_id)
    _spawn(web, run)
    return _json(200, status(web))
