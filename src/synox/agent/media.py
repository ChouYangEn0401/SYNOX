"""
私訊傳來的圖 → 位元組（只在記憶體，docs/adr/0021）。

現在只有 Telegram 有收圖的入口：SDK 把沒有文字的照片／檔案編成 `__MEDIA__:photo:<file_id>:`、
`__MEDIA__:document:<file_id>:<檔名>`（vendor/isdtelekit/telegram/updates.py）。這裡認得這兩種裡「是圖片」的
（photo，或副檔名是圖的 document），用同一個 BotAPI 的 getFile 抓回位元組：

- **不寫檔**：SDK 的 download_file 會寫到磁碟，所以不用它；直接 getFile＋串流讀，讀超過上限就停（不把整個大檔讀進來）。
- 下載網址含 bot token：例外只記類別名稱，網址不進 log。
- 抓不到就回一句原因（呼叫的人告訴使用者），**不把 file_id 當文字餵 AI**。
- Discord 私訊（附件只有檔名）、網頁（沒有上傳圖的入口）目前不收圖。
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from isdtelekit.core.channel import TELEGRAM

MEDIA_PREFIX = "__MEDIA__:"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
CHUNK = 64 * 1024
FETCH_FAILED = "圖片沒有抓到（Telegram 沒有給檔案），所以沒有送給 AI；可以再傳一次。"


def telegram_image(inbound, text: str) -> Optional[str]:
    """這則 Telegram 訊息是一張圖＝回它的 file_id；不是（文字、非圖片的檔案、別的通道）＝None。"""
    if getattr(inbound, "channel", "") != TELEGRAM or not (text or "").startswith(MEDIA_PREFIX):
        return None
    from isdtelekit.telegram.updates import parse_media
    found = parse_media(text)
    if not found:
        return None
    kind, file_id, name = found
    if not file_id:
        return None
    if kind == "photo" or (kind == "document" and (name or "").lower().endswith(IMAGE_EXTS)):
        return file_id
    return None


def fetch_telegram(api, file_id: str, max_bytes: int) -> Tuple[Optional[bytes], str]:
    """(位元組, "") 或 (None, 原因)。超過 max_bytes 不下載完（Telegram 有給 file_size 就先擋）。"""
    get = getattr(api, "get", None)
    session = getattr(api, "session", None)
    root = getattr(api, "_api_root", None)
    token = getattr(api, "_token", None)
    if not (callable(get) and session is not None and root and token):
        return None, "這個通道抓不到圖片，所以沒有送給 AI。"
    try:
        res = get("getFile", {"file_id": file_id}) or {}
        info = (res.get("result") or {}) if res.get("ok") else {}
        path = info.get("file_path")
        if not path:
            return None, FETCH_FAILED
        size = int(info.get("file_size") or 0)
        if size > max_bytes:
            return None, too_big(size, max_bytes)
        resp = session.get(f"{root}/file/bot{token}/{path}", timeout=60, stream=True)
        try:
            if int(getattr(resp, "status_code", 0) or 0) != 200:
                return None, FETCH_FAILED
            data = bytearray()
            chunks = resp.iter_content(CHUNK) if hasattr(resp, "iter_content") else [resp.content]
            for chunk in chunks:
                data += chunk or b""
                if len(data) > max_bytes:
                    return None, too_big(len(data), max_bytes)
            return bytes(data), ""
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()
    except Exception as e:                        # 網址含 token：只記類別
        logging.warning("[VISION] telegram image download failed: %s", type(e).__name__)
        return None, FETCH_FAILED


def too_big(size: int, limit: int) -> str:
    return f"圖片太大（超過 {limit / 1048576:.0f} MB），沒有送給 AI。"


def telegram_loader(api, file_ids: List[str], limits: dict):
    """給 AgentLoop.run_turn(images=…) 的延遲載入：真的要看圖（route 不是 none）才下載。回 (ImagePart 清單, 問題清單)。"""
    def load():
        from synox.llm import vision
        blobs: List[bytes] = []
        problems: List[str] = []
        for file_id in file_ids[:limits["max_images"]]:
            data, problem = fetch_telegram(api, file_id, limits["max_bytes"])
            if data is None:
                problems.append(problem)
            else:
                blobs.append(data)
        parts, more = vision.prepare_all(blobs, limits)
        return parts, problems + more
    load.count = len(file_ids)
    return load
