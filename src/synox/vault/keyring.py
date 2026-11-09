"""
保管箱的主金鑰（32 bytes 隨機）放哪裡：data/.synox.key。

- Windows（vault.mode = "dpapi"，預設）：用 DPAPI（CryptProtectData）包起來再存。只有**同一台電腦、同一個
  Windows 帳號**解得開——硬碟被拷走、雲端備份被看，拿到的都只是包過的金鑰和密文。
- 其他平台，或 vault.mode = "file"：金鑰明文存在檔案裡（記一筆 WARNING）。這時「拿到 data/ 資料夾＝拿到資料」。

檔案格式：一行 "SYNOXKEY1 dpapi <base64>" 或 "SYNOXKEY1 file <base64>"。
**金鑰檔不見 = 加密的資料再也解不開**，所以 load_or_create 只在「金鑰檔不存在而且 data/ 裡也還沒有任何
*.json.enc」時才產生新的；否則丟 KeyringError，不會默默換一把新金鑰。
"""

from __future__ import annotations

import base64
import ctypes
import glob
import logging
import os
import sys

KEY_FILE = ".synox.key"
MAGIC = "SYNOXKEY1"


class KeyringError(Exception):
    pass


# ── DPAPI（Windows）──────────────────────────────────────────────────

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


CRYPTPROTECT_UI_FORBIDDEN = 0x01


def dpapi_available() -> bool:
    return sys.platform == "win32"


def _blob_in(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _blob_out(blob: _Blob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def dpapi_protect(data: bytes, description: str = "SYNOX vault key") -> bytes:
    if not dpapi_available():
        raise KeyringError("DPAPI 只有 Windows 有。")
    blob_in, _keep = _blob_in(data)
    blob_out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob_in), ctypes.c_wchar_p(description), None, None,
                                                None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise KeyringError(f"CryptProtectData 失敗（錯誤碼 {ctypes.GetLastError()}）。")
    return _blob_out(blob_out)


def dpapi_unprotect(data: bytes) -> bytes:
    if not dpapi_available():
        raise KeyringError("DPAPI 只有 Windows 有。")
    blob_in, _keep = _blob_in(data)
    blob_out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None,
                                                  CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise KeyringError("金鑰檔解不開：它是在別台電腦或別的 Windows 帳號上建立的（DPAPI 綁帳號）。")
    return _blob_out(blob_out)


# ── 金鑰檔 ───────────────────────────────────────────────────────────

def key_path(data_dir: str) -> str:
    return os.path.join(data_dir, KEY_FILE)


def read_key(path: str) -> bytes:
    with open(path, "r", encoding="ascii") as f:
        parts = f.read().strip().split()
    if len(parts) != 3 or parts[0] != MAGIC or parts[1] not in ("dpapi", "file"):
        raise KeyringError(f"{path} 的格式不對。")
    raw = base64.b64decode(parts[2])
    return dpapi_unprotect(raw) if parts[1] == "dpapi" else raw


def write_key(path: str, key: bytes, mode: str) -> str:
    """回實際用的方式（要 dpapi 但不是 Windows → file）。"""
    if mode == "dpapi" and not dpapi_available():
        logging.warning("[VAULT] 這個平台沒有 DPAPI：金鑰改存成明文檔 %s（拿到 data/ 就能解開資料）。", path)
        mode = "file"
    if mode == "file":
        logging.warning("[VAULT] 金鑰以明文存在 %s；請保護好 data/ 資料夾。", path)
    payload = dpapi_protect(key) if mode == "dpapi" else key
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii", newline="\n") as f:
        f.write(f"{MAGIC} {mode} {base64.b64encode(payload).decode('ascii')}\n")
    os.replace(tmp, path)
    return mode


def key_mode(path: str) -> str:
    try:
        with open(path, "r", encoding="ascii") as f:
            return f.read().split()[1]
    except (OSError, IndexError):
        return ""


def load_or_create(data_dir: str, mode: str = "dpapi") -> bytes:
    path = key_path(data_dir)
    if os.path.exists(path):
        return read_key(path)
    existing = glob.glob(os.path.join(data_dir, "*.json.enc"))
    if existing:
        raise KeyringError(f"找不到金鑰檔 {path}，但 data/ 裡已經有 {len(existing)} 個加密檔；"
                           "不會產生新金鑰（那些檔就再也解不開了）。把原本的 .synox.key 放回來。")
    key = os.urandom(32)
    write_key(path, key, mode)
    return key
