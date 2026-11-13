r"""
桌面捷徑「SYNOX」與開機自動啟動（使用者在精靈裡勾的才做，invariant 5）。

- 桌面捷徑：PowerShell 的 WScript.Shell 建 .lnk，目標是 Open-SYNOX.bat（沒在跑就先開 SYNOX，再發一個擁有者的
  一次性登入連結打開網頁介面：沒接 Telegram 的人也進得去）。
- 開機自動啟動：啟動資料夾（shell:startup）放一個 SYNOX.cmd（ASCII＋CRLF：cmd.exe 用主控台字碼頁讀 .bat/.cmd），
  跑 `Start.bat --no-browser`（開機登入時不要跳出瀏覽器）。
  SYNOX 資料夾的路徑有中文時 .cmd 寫不成 ASCII，改放一個 .lnk（WScript.Shell 吃 Unicode）。
刪掉那個檔案就不會自動啟動了。
- .synoxpack 點兩下就安裝（使用者在精靈完成頁勾的才做）：HKCU\Software\Classes 底下登記副檔名與 ProgID，
  打開＝`<SYNOX>\Install-Pack.bat "%1"`（跑安全檢查、開網頁設定頁給人按確認）。只寫目前使用者，不要管理員權限。
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

STARTUP_NAME = "SYNOX"
AUTOSTART_ARGS = "--no-browser"          # Start.bat：只跑網頁時也不自動打開瀏覽器（開機登入時不要跳出來）
OPEN_BAT = "Open-SYNOX.bat"
PACK_EXT = ".synoxpack"
PACK_PROGID = "SYNOX.Pack"


PACK_ICON = ("src", "synox", "assets", "synoxpack.ico")   # scripts/make_pack_icon.py 畫的（下載箭頭＋托盤）
CLASSES = "Software\\Classes"


def pack_icon_path(root: str) -> str:
    return os.path.join(root, *PACK_ICON)


def synoxpack_keys(root: str, classes: str = CLASSES):
    """登記 .synoxpack 要寫的 HKCU 機碼：[(子機碼, 值名稱（"" ＝預設值）, 字串), …]。測試只驗這份清單。
    DefaultIcon 沒寫的話檔案總管畫一張空白頁（看起來像壞掉的檔）；OpenWithProgids 讓「開啟檔案」清單也有 SYNOX。
    classes 給測試換成拋棄式的子機碼（不碰真的 .synoxpack 關聯）。"""
    bat = os.path.join(root, "Install-Pack.bat")
    return [
        (f"{classes}\\{PACK_EXT}", "", PACK_PROGID),
        (f"{classes}\\{PACK_EXT}", "Content Type", "application/zip"),
        (f"{classes}\\{PACK_EXT}\\OpenWithProgids", PACK_PROGID, ""),
        (f"{classes}\\{PACK_PROGID}", "", "SYNOX 功能包"),
        (f"{classes}\\{PACK_PROGID}\\DefaultIcon", "", f"{pack_icon_path(root)},0"),
        (f"{classes}\\{PACK_PROGID}\\shell", "", "open"),
        (f"{classes}\\{PACK_PROGID}\\shell\\open", "", "用 SYNOX 安裝"),
        (f"{classes}\\{PACK_PROGID}\\shell\\open\\command", "", f'"{bat}" "%1"'),
    ]


def _winreg_reader(subkey: str, name: str) -> Optional[str]:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def _winreg_writer(subkey: str, name: str, value: str) -> None:
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _winreg_delete_tree(subkey: str) -> bool:
    """刪 HKCU\\subkey 整棵（winreg 沒有 DeleteTree：由下往上刪）。不存在回 False。"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as key:
            children = []
            while True:
                try:
                    children.append(winreg.EnumKey(key, len(children)))
                except OSError:
                    break
    except OSError:
        return False
    for child in children:
        _winreg_delete_tree(subkey + "\\" + child)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
    return True


def synoxpack_status(root: str, reader=None, classes: str = CLASSES):
    """[(子機碼, 名稱, 要的值, 現在的值或 None), …]：Setup／`synox filetype status` 用來說「改了什麼」。"""
    reader = reader or _winreg_reader
    return [(k, n, v, reader(k, n)) for k, n, v in synoxpack_keys(root, classes)]


def register_synoxpack(root: str, writer=None, reader=None, classes: str = CLASSES):
    """寫 HKCU（不要管理員權限）；重跑是安全的（一樣的值不再寫）。回 [(子機碼, 名稱, 值, 有沒有改), …]。
    writer(子機碼, 名稱, 值)／reader(子機碼, 名稱) 給測試換掉；只給 writer 時每一筆都寫（舊的呼叫方式）。"""
    if writer is None:
        writer = _winreg_writer
        reader = reader or _winreg_reader
    done = []
    for subkey, name, value in synoxpack_keys(root, classes):
        changed = reader is None or reader(subkey, name) != value
        if changed:
            writer(subkey, name, value)
        done.append((subkey, name, value, changed))
    if any(c for *_rest, c in done):
        _notify_shell()
    return done


def unregister_synoxpack(reader=None, deleter=None, classes: str = CLASSES):
    """拿掉 SYNOX 寫的關聯（Uninstall.bat、精靈沒勾）。.synoxpack 的預設值不是 SYNOX.Pack（別的程式接手了）就
    不動它。回刪掉的子機碼清單。"""
    reader = reader or _winreg_reader
    deleter = deleter or _winreg_delete_tree
    removed = []
    ext, progid = f"{classes}\\{PACK_EXT}", f"{classes}\\{PACK_PROGID}"
    if reader(ext, "") == PACK_PROGID and deleter(ext):
        removed.append(ext)
    if deleter(progid):
        removed.append(progid)
    if removed:
        _notify_shell()
    return removed


def _notify_shell() -> None:
    """告訴檔案總管關聯改了（SHChangeNotify），不然圖示、開啟方式要登出才更新。失敗不要緊。"""
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def icon_path(root: str) -> str:
    """SYNOX 的圖示（src/synox/assets/synox.ico）；找不到回 ""（捷徑就用預設圖示）。"""
    path = os.path.join(root, "src", "synox", "assets", "synox.ico")
    return path if os.path.exists(path) else ""


def shortcut_script(lnk_path: str, target: str, workdir: str, description: str = "SYNOX",
                    window_style: int = 7, icon: str = "", arguments: str = "") -> str:
    """建 .lnk 的 PowerShell 片段。window_style 7＝最小化。"""
    return "\n".join([
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(lnk_path) + ")",
        "$s.TargetPath = " + _ps_quote(target),
        *(["$s.Arguments = " + _ps_quote(arguments)] if arguments else []),
        "$s.WorkingDirectory = " + _ps_quote(workdir),
        "$s.Description = " + _ps_quote(description),
        f"$s.WindowStyle = {int(window_style)}",
        *(["$s.IconLocation = " + _ps_quote(icon)] if icon else []),
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
            f'call "{start}" {AUTOSTART_ARGS}\r\n')
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
    return run_powershell(shortcut_script(lnk, os.path.join(root, OPEN_BAT), root, "開啟 SYNOX",
                                                icon=icon_path(root)))


def enable_autostart(root: str, folder: Optional[str] = None) -> str:
    """回建立的檔案路徑。"""
    folder = folder or startup_dir()
    os.makedirs(folder, exist_ok=True)
    try:
        text = startup_cmd_text(root)
    except ValueError:
        lnk = os.path.join(folder, STARTUP_NAME + ".lnk")
        err = run_powershell(shortcut_script(lnk, os.path.join(root, "Start.bat"), root, "SYNOX 開機自動啟動",
                                                icon=icon_path(root), arguments=AUTOSTART_ARGS))
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
