"""
桌面捷徑「SYNOX」與開機自動啟動（使用者在精靈裡勾的才做，invariant 5）。

- 桌面捷徑：PowerShell 的 WScript.Shell 建 .lnk，目標是 Start.bat。
- 開機自動啟動：啟動資料夾（shell:startup）放一個 SYNOX.cmd（ASCII＋CRLF：cmd.exe 用主控台字碼頁讀 .bat/.cmd）。
  SYNOX 資料夾的路徑有中文時 .cmd 寫不成 ASCII，改放一個 .lnk（WScript.Shell 吃 Unicode）。
刪掉那個檔案就不會自動啟動了。
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

STARTUP_NAME = "SYNOX"


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def shortcut_script(lnk_path: str, target: str, workdir: str, description: str = "SYNOX",
                    window_style: int = 7) -> str:
    """建 .lnk 的 PowerShell 片段。window_style 7＝最小化。"""
    return "\n".join([
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(lnk_path) + ")",
        "$s.TargetPath = " + _ps_quote(target),
        "$s.WorkingDirectory = " + _ps_quote(workdir),
        "$s.Description = " + _ps_quote(description),
        f"$s.WindowStyle = {int(window_style)}",
        "$s.Save()",
    ])


def desktop_dir() -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup")


def startup_cmd_text(root: str) -> str:
    """啟動資料夾那支 .cmd 的內容（CRLF）。路徑不是 ASCII 時丟 ValueError（改用 .lnk）。"""
    start = os.path.join(root, "Start.bat")
    text = ("@echo off\r\n"
            "rem SYNOX autostart, created by the SYNOX setup wizard. Delete this file to stop it.\r\n"
            f'cd /d "{root}"\r\n'
            f'call "{start}"\r\n')
    text.encode("ascii")                       # 有中文路徑就在這裡丟 UnicodeEncodeError（ValueError 的子類）
    return text


def run_powershell(script: str) -> Optional[str]:
    """跑一段 PowerShell；成功回 None，失敗回錯誤訊息。"""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, timeout=60,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return None if out.returncode == 0 else (out.stderr or out.stdout or "PowerShell failed").strip()[-300:]


def create_desktop_shortcut(root: str) -> Optional[str]:
    lnk = os.path.join(desktop_dir(), "SYNOX.lnk")
    return run_powershell(shortcut_script(lnk, os.path.join(root, "Start.bat"), root, "開啟 SYNOX"))


def enable_autostart(root: str, folder: Optional[str] = None) -> str:
    """回建立的檔案路徑。"""
    folder = folder or startup_dir()
    os.makedirs(folder, exist_ok=True)
    try:
        text = startup_cmd_text(root)
    except ValueError:
        lnk = os.path.join(folder, STARTUP_NAME + ".lnk")
        err = run_powershell(shortcut_script(lnk, os.path.join(root, "Start.bat"), root, "SYNOX 開機自動啟動"))
        if err:
            raise OSError(err)
        return lnk
    path = os.path.join(folder, STARTUP_NAME + ".cmd")
    with open(path, "wb") as f:
        f.write(text.encode("ascii"))
    return path


def disable_autostart(folder: Optional[str] = None) -> None:
    folder = folder or startup_dir()
    for ext in (".cmd", ".lnk"):
        try:
            os.remove(os.path.join(folder, STARTUP_NAME + ext))
        except OSError:
            pass
