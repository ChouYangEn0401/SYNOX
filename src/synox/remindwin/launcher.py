"""
開電腦提醒視窗、哨兵啟動檔要跑的指令。用 pythonw（沒有黑色主控台視窗）；找不到 pythonw 就用目前的 python。

測試不叫 popup_launcher 回的函式（只有 app 真的 start、或哨兵在跑時才會叫）；要測就傳假的 popen。
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, List, Optional, Tuple


def windowless_python() -> str:
    folder = os.path.dirname(sys.executable)
    for name in ("pythonw.exe", "pythonw"):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    return sys.executable


def popup_command(data_dir: str) -> List[str]:
    return [windowless_python(), "-m", "synox.remindwin", "--data", os.path.abspath(data_dir)]


def popup_launcher(data_dir: str, popen: Optional[Callable] = None) -> Callable[[], None]:
    """回一個「開視窗程式」的函式（DeskService.launch 先看 popup.lock，沒開才叫它）。"""
    def launch() -> None:
        run = popen or subprocess.Popen
        flags = 0
        if sys.platform == "win32":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        run(popup_command(data_dir), cwd=os.path.abspath(data_dir), close_fds=True, creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return launch


def sentinel_command(config_path: str = "") -> Tuple[List[str], str]:
    """哨兵的指令與工作資料夾：pythonw -m synox --config <config.json> sentinel。"""
    if not config_path:
        from synox.config import CONFIG_PATH
        config_path = CONFIG_PATH
    config_path = os.path.abspath(config_path)
    return [windowless_python(), "-m", "synox", "--config", config_path, "sentinel"], os.path.dirname(config_path)


__all__ = ["popup_command", "popup_launcher", "sentinel_command", "windowless_python"]
