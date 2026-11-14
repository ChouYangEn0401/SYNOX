"""
/api/settings/update…：網頁設定「💻 電腦與備份」的「SYNOX 更新」卡片＋網頁頂端的「有新版」橫幅。全部只有擁有者。

    GET  /api/settings/update           現況（不連網）：版本、每週檢查開關、上次的結果、怎麼裝的、能不能按「更新」
    POST /api/settings/update/check     現在查一次（連 GitHub；順便算有幾個工具可以更新）
    POST /api/settings/update/weekly    {"enabled": true|false}：每週檢查開關（寫 config.json 的 updates.check）
    POST /api/settings/update/dismiss   橫幅按「知道了」：這個版本不再顯示橫幅
    POST /api/settings/update/launch    只在 Windows、ZIP 裝法：打開 Update.bat（它自己先給人看說明、再問一次）

「更新」按鈕不在網頁裡換檔：SYNOX 正在跑時換不了自己（ADR 0023 決定 U4），所以只是打開 Update.bat 的視窗。
POST 會經過門禁的手機驗證器（guard/stepup.py：/api/settings/ 底下預設就算敏感；check、dismiss 不改東西，列在例外）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
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
    notice = None
    if last and last.get("status") == "newer" and last.get("latest") and state.get("dismissed") != last.get("latest") \
            and upd.compare(__version__, last["latest"]) == "newer":
        notice = {"latest": last["latest"], "security": bool(last.get("security")), "notes_url": last.get("notes_url")}
    return {"installed": __version__, "weekly": upd.weekly_enabled(logic.read_existing(web.config_path)),
            "kind": kind, "how": upd.how_line(kind), "releases": upd.RELEASES_PAGE, "last": last, "notice": notice,
            "can_launch": os.name == "nt" and kind == "zip" and os.path.isfile(os.path.join(root, "Update.bat"))}


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
        result = upd.check(__version__, root=_root(web), opener=getattr(web, "update_opener", None),
                           tools=_tools_counter(web))
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
    if path == "/api/settings/update/dismiss":
        state = upd.load_state(_data_dir(web))
        last = state.get("result") if isinstance(state.get("result"), dict) else {}
        if last.get("latest"):
            state["dismissed"] = last["latest"]
            upd.save_state(_data_dir(web), state)
        return _json(200, status(web))
    if path == "/api/settings/update/launch":
        return launch(web, user)
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
