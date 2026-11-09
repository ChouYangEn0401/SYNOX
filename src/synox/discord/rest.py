"""
DiscordChannel：SDK 的 Channel 介面，用 Discord REST API（v10，requests）回覆。不開埠，只往外打 HTTPS。

    api = DiscordChannel(token, identities, http=requests.Session())
    api.send_message(uid, "嗨", reply_markup=buttons([("好", "ok:1")]))

- chat_id 是**內部使用者 id**（私訊）：先看收訊時記下的私訊頻道，沒有就用 identities 找回 Discord user id，
  POST /users/@me/channels 開私訊。找不到（例如那是個只有 Telegram 的人）→ {"ok": False}，不丟例外。
- 文字一律 plain()（Discord 不吃 Telegram 的 HTML）；超過 2000 字切成幾則，按鈕放在最後一則。
- inline_keyboard → Discord 按鈕元件（custom_id = callback_data；有 url 的變連結按鈕）；最多 5 列 × 5 顆。
- answer_callback_query：有字＝只給按的人看的小訊息（ephemeral），沒字＝默默確認（type 6）。
- 429 照 retry_after 等一次（最多 5 秒）再試；其他錯誤回 {"ok": False, "error": …}。token 不進 log。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from isdtelekit.core.richtext import plain

from synox.discord.events import DISCORD

API_ROOT = "https://discord.com/api/v10"
TEXT_MAX = 2000
LABEL_MAX = 80
CUSTOM_ID_MAX = 100
EPHEMERAL = 64


def components(reply_markup: Optional[Dict[str, Any]]) -> List[dict]:
    rows = (reply_markup or {}).get("inline_keyboard") or []
    out = []
    for row in rows[:5]:
        items = []
        for b in row[:5]:
            label = str(b.get("text") or "·")[:LABEL_MAX]
            if b.get("url"):
                items.append({"type": 2, "style": 5, "label": label, "url": str(b["url"])})
            elif b.get("callback_data"):
                items.append({"type": 2, "style": 2, "label": label,
                              "custom_id": str(b["callback_data"])[:CUSTOM_ID_MAX]})
        if items:
            out.append({"type": 1, "components": items})
    return out


def chunks(text: str, size: int = TEXT_MAX) -> List[str]:
    text = text or "·"
    out = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        cut = cut if cut > size // 2 else size
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    out.append(text or "·")
    return out


class DiscordChannel:

    channel_name = DISCORD

    def __init__(self, token: str, identities, http=None, api_root: str = API_ROOT, sleep=time.sleep):
        if http is None:
            import requests
            http = requests.Session()
        self._token = token
        self.identities = identities
        self.http = http
        self.api_root = api_root.rstrip("/")
        self._sleep = sleep
        self._dm: Dict[int, str] = {}
        self._answered: set = set()
        self._lock = threading.Lock()

    def take_answered(self, callback_query_id) -> bool:
        """這個按鈕回應過了沒（看完就忘掉）。DiscordEntry 用來決定要不要自動確認。"""
        with self._lock:
            if str(callback_query_id) in self._answered:
                self._answered.discard(str(callback_query_id))
                return True
            return False

    # ── HTTP ────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bot {self._token}", "User-Agent": "DiscordBot (https://github.com/synox, 0.1)"}

    def request(self, method: str, path: str, *, json_body=None, data=None, files=None) -> Dict[str, Any]:
        url = self.api_root + path
        for attempt in (0, 1):
            try:
                kw = {"headers": self._headers(), "timeout": 15}
                if files is not None:
                    kw.update(data=data, files=files)
                elif json_body is not None:
                    kw["json"] = json_body
                resp = self.http.request(method, url, **kw)
            except Exception as e:                  # 網路錯誤：不丟例外（跟 BotAPI 一樣）
                logging.warning("[DISCORD] %s %s failed: %s", method, path, type(e).__name__)
                return {"ok": False, "error": type(e).__name__}
            status = getattr(resp, "status_code", 200)
            try:
                body = resp.json() if status != 204 else {}
            except ValueError:
                body = {}
            if status == 429 and attempt == 0:
                self._sleep(min(float((body or {}).get("retry_after") or 1.0), 5.0))
                continue
            if status >= 400:
                logging.warning("[DISCORD] %s %s → %s %s", method, path, status, (body or {}).get("message", ""))
                return {"ok": False, "error": f"HTTP {status}", "result": body}
            return {"ok": True, "result": body}
        return {"ok": False, "error": "rate limited"}

    # ── 私訊頻道 ─────────────────────────────────────────────────────

    def remember_dm(self, uid: int, channel_id: str) -> None:
        if channel_id:
            with self._lock:
                self._dm[int(uid)] = str(channel_id)

    def dm_channel(self, chat_id) -> Optional[str]:
        try:
            uid = int(chat_id)
        except (TypeError, ValueError):
            return None
        with self._lock:
            if uid in self._dm:
                return self._dm[uid]
        external = self.identities.external(DISCORD, uid)
        if not external:
            return None
        out = self.request("POST", "/users/@me/channels", json_body={"recipient_id": external})
        cid = (out.get("result") or {}).get("id") if out.get("ok") else None
        if cid:
            self.remember_dm(uid, cid)
        return cid

    def can_reach(self, chat_id) -> bool:
        try:
            uid = int(chat_id)
        except (TypeError, ValueError):
            return False
        with self._lock:
            if uid in self._dm:
                return True
        return self.identities.external(DISCORD, uid) is not None

    # ── Channel ──────────────────────────────────────────────────────

    def send_message(self, chat_id, text, reply_markup=None, quiet=False, link_preview=True, **kw):
        cid = self.dm_channel(chat_id)
        if not cid:
            return {"ok": False, "error": "no discord dm for this user"}
        parts = chunks(plain(text))
        out: Dict[str, Any] = {"ok": False}
        for i, part in enumerate(parts):
            body: Dict[str, Any] = {"content": part, "allowed_mentions": {"parse": []}}
            if i == len(parts) - 1 and reply_markup:
                body["components"] = components(reply_markup)
            if quiet:
                body["flags"] = 4096                  # SUPPRESS_NOTIFICATIONS
            if not link_preview:
                body["flags"] = body.get("flags", 0) | 4   # SUPPRESS_EMBEDS
            out = self.request("POST", f"/channels/{cid}/messages", json_body=body)
            if not out.get("ok"):
                return out
        return {"ok": True, "result": {"message_id": int((out.get("result") or {}).get("id") or 0)}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kw):
        cid = self.dm_channel(chat_id)
        if not cid:
            return {"ok": False}
        body = {"content": chunks(plain(text))[0], "components": components(reply_markup)}
        return self.request("PATCH", f"/channels/{cid}/messages/{int(message_id)}", json_body=body)

    def remove_buttons(self, chat_id, message_id, **kw):
        cid = self.dm_channel(chat_id)
        if not cid:
            return {"ok": False}
        return self.request("PATCH", f"/channels/{cid}/messages/{int(message_id)}", json_body={"components": []})

    def delete_message(self, chat_id, message_id):
        cid = self.dm_channel(chat_id)
        if not cid:
            return {"ok": False}
        return self.request("DELETE", f"/channels/{cid}/messages/{int(message_id)}")

    def answer_callback_query(self, callback_query_id, text: Optional[str] = None, **kw):
        iid, _, token = str(callback_query_id or "").partition(":")
        if not iid or not token:
            return {"ok": False}
        with self._lock:
            self._answered.add(str(callback_query_id))
        if text:
            body = {"type": 4, "data": {"content": plain(text)[:TEXT_MAX], "flags": EPHEMERAL}}
        else:
            body = {"type": 6}                        # DEFERRED_UPDATE_MESSAGE：確認收到，不改訊息
        return self.request("POST", f"/interactions/{iid}/{token}/callback", json_body=body)

    def _upload(self, chat_id, paths: List[str], caption: str):
        cid = self.dm_channel(chat_id)
        if not cid:
            return {"ok": False}
        real = [p for p in paths if isinstance(p, str) and os.path.isfile(p)][:10]
        if not real:                                  # 不是本機檔案（例如網址）：當文字送
            return self.send_message(chat_id, "\n".join([plain(caption or "")] + [str(p) for p in paths]).strip())
        handles = []
        try:
            files = {}
            for i, p in enumerate(real):
                fh = open(p, "rb")
                handles.append(fh)
                files[f"files[{i}]"] = (os.path.basename(p), fh)
            payload = {"content": plain(caption or "")[:TEXT_MAX], "allowed_mentions": {"parse": []}}
            out = self.request("POST", f"/channels/{cid}/messages", data={"payload_json": json.dumps(payload)},
                               files=files)
        finally:
            for fh in handles:
                fh.close()
        if out.get("ok"):
            return {"ok": True, "result": {"message_id": int((out.get("result") or {}).get("id") or 0)}}
        return out

    def send_photo(self, chat_id, photo, caption=""):
        return self._upload(chat_id, [photo], caption)

    def send_document(self, chat_id, document, caption=""):
        return self._upload(chat_id, [document], caption)

    def send_media_group(self, chat_id, photo_paths, caption="", kind="photo"):
        return self._upload(chat_id, list(photo_paths or []), caption)

    def download_file(self, file_id, dest_path):
        return False                                  # 最小版不收附件

    def typing(self, chat_id):
        cid = self.dm_channel(chat_id)
        if cid:
            self.request("POST", f"/channels/{cid}/typing")

    def pin_message(self, chat_id, message_id, **kw):
        cid = self.dm_channel(chat_id)
        return self.request("PUT", f"/channels/{cid}/pins/{int(message_id)}") if cid else {"ok": False}

    def unpin_message(self, chat_id, message_id=None, **kw):
        cid = self.dm_channel(chat_id)
        if not cid or message_id is None:
            return {"ok": True}
        return self.request("DELETE", f"/channels/{cid}/pins/{int(message_id)}")
