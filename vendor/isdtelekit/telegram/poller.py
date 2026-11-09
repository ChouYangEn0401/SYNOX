"""
Telegram channel 的收訊迴圈：持續呼叫 getUpdates（長輪詢），每個 update 經 TelegramEntry 轉成 Inbound 交給 Dispatcher。
跑在 host/supervisor.py 的受監看執行緒上：stop() 之後，這一輪長輪詢回來就結束。

- 收訊進度（處理到哪一則）存在 offset_path：重啟之後從這裡接著收，已經處理過的不會再送一次（不然會重跑舊指令）。
  先存再處理、暫存檔＋os.replace：處理到一半當掉不會重跑同一則，寫到一半被砍掉也不會變成空檔。
- getUpdates 本身就是長輪詢，成功之後馬上問下一輪；失敗（網路斷、409 Conflict…）才退避：
  poll_interval_seconds 起跳、每次加倍、最多 30 秒。409 通常是同一個 token 有兩支程式在收（host/lock.py 擋這件事）。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from isdtelekit.telegram.bot_api import BotAPI
from isdtelekit.telegram.updates import TelegramEntry

OFFSET_PATH = "data/last_update_id"
MAX_BACKOFF = 30.0


class Poller:

    def __init__(self, api: BotAPI, entry: TelegramEntry, offset_path: str = OFFSET_PATH,
                 poll_interval_seconds: float = 3.0):
        self.api = api
        self.entry = entry
        self.poll_interval_seconds = poll_interval_seconds
        self._stop = threading.Event()
        self._offset_path = offset_path
        self.update_offset: Optional[int] = self._load_offset()

    def _load_offset(self) -> Optional[int]:
        """沒有檔案、或內容不是數字 → None（從 Telegram 還留著的最舊那則開始）。"""
        try:
            with open(self._offset_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            return int(text) if text else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logging.warning("Ignoring unreadable update offset %s (%s)", self._offset_path, exc)
            return None

    def _save_offset(self) -> None:
        try:
            folder = os.path.dirname(self._offset_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = f"{self._offset_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(str(self.update_offset))
            os.replace(tmp, self._offset_path)
        except OSError as exc:
            logging.warning("Could not save update offset to %s: %s", self._offset_path, exc)

    def poll_once(self) -> None:
        """執行一次 getUpdates 並處理所有新 update。"""
        for update in self.api.get_updates(self.update_offset):
            self.update_offset = update["update_id"] + 1
            self._save_offset()
            try:
                self.entry.dispatch(self.api, update)
            except Exception:
                logging.exception("Unhandled error while dispatching update %s", update.get("update_id"))

    def run_forever(self) -> None:
        """主迴圈：持續輪詢，直到 stop()。"""
        backoff = max(1.0, float(self.poll_interval_seconds))
        delay = backoff
        logging.info("Polling started (no wait after a successful long poll; backoff from %ss on errors)", backoff)
        while not self._stop.is_set():
            self.poll_once()
            if getattr(self.api, "last_poll_ok", True):
                delay = backoff
                continue
            self._stop.wait(delay)
            delay = min(delay * 2, MAX_BACKOFF)
        logging.info("Polling stopped.")

    def stop(self) -> None:
        self._stop.set()
