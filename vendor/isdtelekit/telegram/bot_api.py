"""
Telegram Bot HTTP API 的薄封裝：只負責發 HTTP、回傳 dict，不含任何業務邏輯。
它就是 Telegram 這個 channel 的回覆管子（core/channel.py 的 Channel）；get_updates 只給 poller 用。

- 回傳值一律是 Telegram 的 dict（{"ok": bool, "result": …}）；網路錯誤也回 {"ok": False, "error": …}，不丟例外。
- text 是 core/richtext.Html 時用 parse_mode=HTML；Telegram 不收（標籤寫錯）就自動改送純文字。
- 2 秒內送同一句給同一個聊天只送一次（多個 handler 幾乎同時回同一句的保險）；去重快取會清，不會一直長。
- 429 Too Many Requests 的 retry_after 放在回傳值裡（要放慢的人自己看）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from isdtelekit.core.richtext import Html, plain

DEDUPE_SECONDS = 2.0     # 同一句、同一個聊天，這麼短的時間內送兩次 → 第二次不送
DEDUPE_KEEP = 256        # 去重快取超過這麼多筆就清掉過期的
API_ROOT = "https://api.telegram.org"


class BotAPI:

    channel_name = "telegram"

    def __init__(self, token: str, api_root: str = API_ROOT):
        self._token = token
        self._api_root = api_root.rstrip("/")
        self.base_url = f"{self._api_root}/bot{token}"
        self.session = requests.Session()
        self.last_poll_ok = True
        self._recent_sent: Dict[str, float] = {}
        self._recent_lock = threading.Lock()

    # ---------- 基礎 HTTP ----------

    def get(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30) -> Dict[str, Any]:
        try:
            resp = self.session.get(f"{self.base_url}/{method}", params=params, timeout=timeout)
        except requests.RequestException as e:
            logging.error("HTTP GET error [%s]: %s", method, e)
            return {"ok": False, "error": str(e)}
        return self._parse(method, resp)

    def post(self, method: str, data: Dict[str, Any], quiet: bool = False, files=None,
             timeout: float = 30) -> Dict[str, Any]:
        try:
            resp = self.session.post(f"{self.base_url}/{method}", data=data, files=files, timeout=timeout)
        except requests.RequestException as e:
            logging.error("HTTP POST error [%s]: %s", method, e)
            return {"ok": False, "error": str(e)}
        return self._parse(method, resp, quiet=quiet)

    # 預期中、無害的錯誤（不記 ERROR）
    _BENIGN_DESCRIPTIONS = ("message is not modified",)

    def _parse(self, method: str, resp: requests.Response, quiet: bool = False) -> Dict[str, Any]:
        if resp.status_code != 200:
            try:
                body = resp.json()
                description = body.get("description", "")
                retry_after = (body.get("parameters") or {}).get("retry_after")
            except (ValueError, AttributeError):
                description, retry_after = "", None
            if quiet or any(b in description for b in self._BENIGN_DESCRIPTIONS):
                logging.debug("Non-200 [%s] (quiet, ignored): %s %s", method, resp.status_code, description)
            else:
                logging.error("Non-200 [%s]: %s %s", method, resp.status_code, resp.text[:200])
            result = {"ok": False, "status": resp.status_code, "description": description}
            if retry_after:
                result["retry_after"] = int(retry_after)
            return result
        try:
            return resp.json()
        except ValueError:
            logging.error("Invalid JSON [%s]: %s", method, resp.text[:200])
            return {"ok": False, "error": "invalid_json"}

    # ---------- 文字 ----------

    def send_message(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None,
                     quiet: bool = False, link_preview: bool = True) -> Dict[str, Any]:
        """傳送文字訊息。quiet=True：失敗時不記 ERROR（盡力而為的廣播，對方可能封鎖了 bot）。
        link_preview=False：不讓 Telegram 去抓網址預覽（一次性連結被預覽就用掉了）。"""
        if self._is_duplicate(chat_id, text):
            logging.info("Skipping duplicate send_message to %s: %s", chat_id, text)
            return {"ok": False, "error": "duplicate"}
        data: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if isinstance(text, Html):
            data["parse_mode"] = "HTML"
        if not link_preview:
            data["link_preview_options"] = json.dumps({"is_disabled": True})
        if reply_markup is not None:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        res = self._as_plain_if_rejected("sendMessage", data, self.post("sendMessage", data, quiet=quiet), quiet)
        if not res.get("ok") and not quiet:
            logging.error("sendMessage failed: %s", res)
        return res

    def edit_message_text(self, chat_id: int, message_id: int, text: str,
                          reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """改寫已送出的訊息，可同時換掉按鈕。"""
        data: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if isinstance(text, Html):
            data["parse_mode"] = "HTML"
        if reply_markup is not None:
            data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
        res = self._as_plain_if_rejected("editMessageText", data, self.post("editMessageText", data))
        if not res.get("ok") and not any(b in (res.get("description") or "") for b in self._BENIGN_DESCRIPTIONS):
            logging.error("editMessageText failed: %s", res)
        return res

    def _is_duplicate(self, chat_id: int, text: str) -> bool:
        """DEDUPE_SECONDS 內送過一模一樣的一句給同一個聊天 → True；不然記下來回 False。"""
        key = f"{chat_id}:{text}"
        now = time.time()
        with self._recent_lock:
            if len(self._recent_sent) > DEDUPE_KEEP:
                self._recent_sent = {k: t for k, t in self._recent_sent.items() if now - t < DEDUPE_SECONDS}
            last = self._recent_sent.get(key)
            if last is not None and now - last < DEDUPE_SECONDS:
                return True
            self._recent_sent[key] = now
            return False

    def _as_plain_if_rejected(self, method: str, data: Dict[str, Any], res: Dict[str, Any],
                              quiet: bool = False) -> Dict[str, Any]:
        """Telegram 不收這段 HTML（can't parse entities）就改送純文字：格式掉了也不能讓訊息掉了。"""
        if res.get("ok") or "parse_mode" not in data or "parse entities" not in (res.get("description") or ""):
            return res
        logging.warning("[TG] %s：HTML 被拒（%s），改送純文字", method, res.get("description"))
        retry = {k: v for k, v in data.items() if k != "parse_mode"}
        retry["text"] = plain(data["text"])
        return self.post(method, retry, quiet=quiet)

    # ---------- 圖片與檔案 ----------

    def _send_file(self, method: str, field: str, chat_id: int, source: str, caption: str) -> Dict[str, Any]:
        """source 是本機路徑就上傳（multipart），不然當成 URL 或 file_id。"""
        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        if os.path.exists(source):
            with open(source, "rb") as fh:
                res = self.post(method, data, files={field: fh}, timeout=60)
        else:
            data[field] = source
            res = self.post(method, data)
        if not res.get("ok"):
            logging.error("%s failed: %s", method, res)
        return res

    def send_photo(self, chat_id: int, photo: str, caption: str = "") -> Dict[str, Any]:
        return self._send_file("sendPhoto", "photo", chat_id, photo, caption)

    def send_document(self, chat_id: int, document: str, caption: str = "") -> Dict[str, Any]:
        return self._send_file("sendDocument", "document", chat_id, document, caption)

    def send_media_group(self, chat_id: int, photo_paths: List[str], caption: str = "",
                         kind: str = "photo") -> Dict[str, Any]:
        """以「相簿」一次傳送多張本機圖片／檔案（最多 10 張）。kind="document" 原檔不壓縮；caption 掛在第一張。"""
        media_type = "document" if kind == "document" else "photo"
        paths = [p for p in (photo_paths or []) if p and os.path.exists(p)][:10]
        if not paths:
            return {"ok": False, "error": "no_files"}
        opened = [open(p, "rb") for p in paths]
        try:
            media = [{"type": media_type, "media": f"attach://file{i}", **({"caption": caption} if i == 0 and caption else {})}
                     for i in range(len(paths))]
            files = {f"file{i}": fh for i, fh in enumerate(opened)}
            res = self.post("sendMediaGroup", {"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)},
                            files=files, timeout=120)
        finally:
            for fh in opened:
                fh.close()
        if not res.get("ok"):
            logging.error("sendMediaGroup failed: %s", res)
        return res

    def download_file(self, file_id: str, dest_path: str) -> bool:
        """用 file_id 下載使用者傳來的檔案到 dest_path。成功回 True。"""
        res = self.get("getFile", {"file_id": file_id})
        file_path = (res.get("result") or {}).get("file_path") if res.get("ok") else None
        if not file_path:
            logging.error("getFile failed: %s", res)
            return False
        try:
            r = self.session.get(f"{self._api_root}/file/bot{self._token}/{file_path}", timeout=60)
        except requests.RequestException as e:
            logging.error("File download failed: %s", e)
            return False
        if r.status_code != 200:
            logging.error("File download failed: HTTP %s", r.status_code)
            return False
        folder = os.path.dirname(dest_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(r.content)
        return True

    # ---------- 按鈕、訊息管理 ----------

    def remove_buttons(self, chat_id: int, message_id: int) -> Dict[str, Any]:
        """拿掉訊息上的 inline keyboard（文字不動），讓已處理的按鈕不能再按。"""
        return self.post("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id,
                                                    "reply_markup": json.dumps({"inline_keyboard": []})}, quiet=True)

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> Dict[str, Any]:
        """回覆 callback_query（按按鈕後跳出的短暫提示）。一定要回，不然 Telegram 那邊按鈕一直轉。"""
        data: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            data["text"] = text
        res = self.post("answerCallbackQuery", data)
        if not res.get("ok"):
            logging.error("answerCallbackQuery failed: %s", res)
        return res

    def delete_message(self, chat_id: int, message_id: int) -> Dict[str, Any]:
        """刪掉一則訊息。刪不掉（太舊、已經刪了）不算錯。"""
        return self.post("deleteMessage", {"chat_id": chat_id, "message_id": message_id}, quiet=True)

    def pin_message(self, chat_id: int, message_id: int, quiet: bool = True) -> Dict[str, Any]:
        """釘到聊天最上面（私訊裡 bot 可以直接釘）。quiet：不發通知。"""
        return self.post("pinChatMessage", {"chat_id": chat_id, "message_id": message_id,
                                            "disable_notification": "true" if quiet else "false"}, quiet=True)

    def unpin_message(self, chat_id: int, message_id: int) -> Dict[str, Any]:
        return self.post("unpinChatMessage", {"chat_id": chat_id, "message_id": message_id}, quiet=True)

    def typing(self, chat_id: int) -> None:
        """顯示「輸入中…」（幾秒後自動消失）。"""
        self.post("sendChatAction", {"chat_id": chat_id, "action": "typing"}, quiet=True)

    def set_my_commands(self, commands: List[Tuple[str, str]], scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """輸入框旁的指令選單（telegram/menu.py）。commands：[(名稱不含 /, 說明)]。"""
        data: Dict[str, Any] = {"commands": json.dumps([{"command": c, "description": d} for c, d in commands],
                                                       ensure_ascii=False)}
        if scope:
            data["scope"] = json.dumps(scope)
        return self.post("setMyCommands", data)

    def get_me(self) -> Dict[str, Any]:
        """這個 token 是哪一支 bot（啟動時確認 token 對不對）。"""
        return self.get("getMe")

    # ---------- 收訊（只給 poller 用）----------

    def get_updates(self, offset: Optional[int], timeout: int = 25) -> List[Dict[str, Any]]:
        """長輪詢取得新 updates（沒訊息時伺服器等 timeout 秒才回）。失敗回空 list，last_poll_ok 記成 False。"""
        params: Dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        res = self.get("getUpdates", params, timeout=timeout + 10)
        self.last_poll_ok = bool(res.get("ok"))
        if not res.get("ok"):
            logging.warning("getUpdates failed: %s", res)
            return []
        return res.get("result", [])
