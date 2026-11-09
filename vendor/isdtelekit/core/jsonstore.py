"""
JSON 檔案持久化的共用規矩（SDK 裡所有 data/*.json 都走這裡）。

- 寫入一律「暫存檔 + os.replace」，程序在寫到一半被砍掉時，舊檔仍然完整。
- 讀到壞掉的 JSON 不會默默當成空的：原檔改名成 `<name>.corrupt-<時間>` 留證據，
  寫一筆 ERROR log，再回傳 default 讓程式繼續跑。
- 多條執行緒會讀改寫同一份檔的地方，呼叫端自己加鎖（這裡只保證「一次寫入」是原子的）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

_REPLACE_RETRIES = 5


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        aside = f"{path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
        os.replace(path, aside)
        logging.error("Corrupt JSON %s was moved to %s (%s); starting from default.", path, aside, exc)
        return default


def save_json(path: str, data: Any) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Windows refuses to replace a file another process has open for a moment
    # (an editor, a backup tool); a short retry covers that without masking real errors.
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                os.remove(tmp)
                raise
            time.sleep(0.05 * (attempt + 1))
