"""
GET /api/settings/data：網頁設定「💻 電腦與備份」的「資料版本」卡片（ADR 0043）。只有擁有者；只看（不升級、不改檔）。

    {"core": [{"file", "kind", "action", "before", "after", "current", "steps", "message"}…],
     "packs": [同上＋"pack"], "needs_upgrade": bool, "problems": int}

action：missing（還沒有）｜current（最新）｜planned（要升級，下次啟動自己升）｜too_new（較新版本寫的，不動它）｜failed。
升級不在網頁上按：SYNOX 開著時升不了自己手上的資料，重開 SYNOX 就會升（啟動時、工具載入前）。
"""

from __future__ import annotations

import json


def _json(code: int, data) -> tuple:
    return code, [("Content-Type", "application/json; charset=utf-8")], json.dumps(data, ensure_ascii=False).encode("utf-8")


def status(web) -> dict:
    from synox.datastore import report
    vault = getattr(web, "vault", None)
    return report.to_dict(report.collect(getattr(web, "config_path", "") or None, web.config, vault))


def route(web, user, method: str, path: str, body: bytes):
    denied = web._owner_only(user)
    if denied:
        return denied
    if method != "GET" or path != "/api/settings/data":
        return _json(404 if method == "GET" else 405, {"error": "沒有這個 API。" if method == "GET" else "只收 GET。"})
    return _json(200, status(web))
