"""SYNOX 自己更新（docs/adr/0023）：

- check.py   有沒有新版（按了才查；或使用者自己打開的每週檢查）、版本比較、通知一次
- prepare.py Update.bat 的前半段：下載、驗 SHA256／簽章、解到暫存資料夾（不動現在的檔案）
- signing.py release.json 的 Ed25519 簽章與公鑰
- web_api.py 網頁設定「💻 電腦與備份」的「檢查更新」卡片
換檔、退回在 setup/update.ps1（Update.bat）。
"""

from __future__ import annotations

import logging
import os

from synox.update.check import CheckResult, UpdateError, weekly_tick   # 不匯入 check()：synox.update.check 是模組

TASK_ID = "system.update_check"
TICK_INTERVAL = 6 * 3600          # 每 6 小時看一次「到了沒」；真的連網只在打開每週檢查、而且離上次 ≥ 7 天


def install(app, config, config_path: str = "") -> None:
    """登記 runtime 任務 system.update_check（用現有的排程迴圈，不另開執行緒）。沒打開每週檢查時任務照跑但不連網。
    沒有 runtime（舊的組法、測試）就不登記：只剩按了才查。"""
    rt = app.extras.get("synox_runtime")
    if rt is None:
        return
    path = config_path or os.path.join(getattr(config, "root", "."), "config.json")
    data_dir = getattr(config, "data_dir", os.path.join(getattr(config, "root", "."), "data"))
    root = getattr(config, "root", ".")

    def tick(_ctx=None) -> str:
        from synox.wizard import logic
        raw = logic.read_existing(path)              # 每次讀檔：網頁上改了開關不用重開 SYNOX
        try:
            return weekly_tick(data_dir, raw, app.notify_owner, root=root)
        except Exception:                            # 安靜失敗：記 log，下次再說
            logging.exception("[UPDATE] weekly check failed")
            return "這次沒查成"

    rt.loop.register(TASK_ID, "檢查 SYNOX 有沒有新版（每週，要自己打開）", fn=tick, interval=TICK_INTERVAL,
                     timeout=120.0, first_delay=300)


__all__ = ["CheckResult", "TASK_ID", "UpdateError", "install", "weekly_tick"]
