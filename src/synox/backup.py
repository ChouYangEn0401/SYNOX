"""
備份：把 data/ 打包成 zip，再用保管箱的主金鑰加密（Web UI 設定頁的「下載備份」）。

    blob = export_backup(data_dir, vault)        # synox-backup-<日期>.zip 的內容
    inner = read_backup(blob, vault)             # 解回 data/ 的 zip（還原用；v1 還沒有還原按鈕）

外層是一個普通的 zip（任何解壓縮程式都打得開），裡面兩個檔：
  README.txt      這是什麼、怎麼還原
  data.zip.enc    data/ 的 zip，經 Vault.encrypt_bytes（Fernet＋scrypt，金鑰＝保管箱主金鑰）

不放進去的：主金鑰檔本身（.synox.key：DPAPI 包著，換電腦本來就解不開；而且備份不該帶著自己的鑰匙）、
host.lock、暫存檔、網頁登入的 token／session、上傳暫存。
**主金鑰綁這台電腦、這個 Windows 帳號**（DPAPI）：這份備份只能在同一個帳號還原，見 docs/security.md。
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from typing import Iterable

SKIP_FILES = {".synox.key", "host.lock", "web_tokens.json", "web_sessions.json", "last_update_id"}
SKIP_DIRS = {"web_uploads", "job_logs", "claude_workspace"}
MAX_BYTES = 512 * 1024 * 1024

README = """SYNOX 備份（{date}）

data.zip.enc 是 SYNOX 的 data 資料夾（筆記、記帳、提醒、使用者、AI 用量…），
用這台電腦的 SYNOX 保管箱金鑰加密。只有同一台電腦、同一個 Windows 帳號上的 SYNOX 解得開
（vault.mode=file 時，有 data/.synox.key 的人也解得開）。

還原（v1 還沒有按鈕）：
  .venv\\Scripts\\python.exe -c "from synox.backup import restore_cli; restore_cli()" synox-backup.zip 目的資料夾
"""


def _files(data_dir: str) -> Iterable[str]:
    for root, dirs, files in os.walk(data_dir):
        rel_root = os.path.relpath(root, data_dir)
        if rel_root == ".":
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if rel_root == "." and name in SKIP_FILES:
                continue
            if name.endswith(".tmp"):
                continue
            yield os.path.join(root, name)


def data_zip(data_dir: str) -> bytes:
    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in _files(data_dir):
            total += os.path.getsize(path)
            if total > MAX_BYTES:
                raise ValueError("data 資料夾太大（超過 512 MB），請直接複製資料夾備份。")
            z.write(path, os.path.relpath(path, data_dir).replace("\\", "/"))
    return buf.getvalue()


def export_backup(data_dir: str, vault) -> bytes:
    if vault is None:
        raise ValueError("保管箱沒有打開，沒辦法加密備份。")
    sealed = vault.encrypt_bytes(data_zip(data_dir), payload="data.zip")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(date=time.strftime("%Y-%m-%d %H:%M")))
        z.writestr("data.zip.enc", sealed)
    return out.getvalue()


def read_backup(blob: bytes, vault) -> bytes:
    """外層 zip → data/ 的 zip bytes（金鑰不對丟 VaultError）。"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        sealed = z.read("data.zip.enc")
    return vault.decrypt_bytes(sealed, where="data.zip.enc")


def filename(now=None) -> str:
    return time.strftime("synox-backup-%Y%m%d.zip", time.localtime(now))


def restore_cli(argv=None) -> int:  # pragma: no cover - 手動還原用
    import sys

    from synox.config import SynoxConfig
    from synox.vault import open_vault
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("用法：restore_cli <synox-backup.zip> <解到哪個資料夾>")
        return 2
    vault = open_vault(SynoxConfig.load(require_token=False))
    with open(args[0], "rb") as f:
        inner = read_backup(f.read(), vault)
    os.makedirs(args[1], exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(inner)) as z:
        for info in z.infolist():
            target = os.path.realpath(os.path.join(args[1], info.filename))
            if not target.startswith(os.path.realpath(args[1]) + os.sep):
                raise ValueError(f"備份裡有可疑的路徑：{info.filename}")
        z.extractall(args[1])
    print(f"解好了：{args[1]}（確認內容後，關掉 SYNOX、換掉 data 資料夾裡對應的檔案）")
    return 0
