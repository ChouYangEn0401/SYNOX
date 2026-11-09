"""
pack 裝卸（Web UI 設定頁用）：上傳 .synoxpack → 檢查 → 給人看摘要 → 按確認才裝；移除＝搬到 packs/_removed/；重新載入。

.synoxpack＝一個 pack 資料夾壓成的 zip（pack.json 在最上層，或在唯一的那個資料夾裡）。

檢查（架構 v1 §4 的第 1 關「宣告檢查」；第 2 關靜態掃描、第 3 關完整性鎖定還沒做）：
- zip 本身：不能有絕對路徑、`..`、磁碟代號、符號連結；最多 MAX_FILES 個檔、解開最多 MAX_UNZIPPED。
- 解到 data/web_uploads/<隨機>/ 之後跑 manifest.read()（pack.json 格式、skill 檔、pack.py、web.panel…）。
- 名字跟已經裝的 pack 一樣 → 不裝（先移除舊的）。
python pack 的程式會在 SYNOX 裡面、用你的 Windows 帳號權限執行——摘要會明講。
"""

from __future__ import annotations

import io
import logging
import os
import re
import secrets
import shutil
import stat
import time
import zipfile
from typing import Dict, List, Tuple

from synox.packs import loader
from synox.packs.manifest import ManifestError, read

MAX_UPLOAD = 5 * 1024 * 1024
MAX_UNZIPPED = 20 * 1024 * 1024
MAX_FILES = 300
REMOVED = "_removed"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class PackAdminError(ValueError):
    """給人看的錯誤。"""


def _safe_parts(name: str) -> List[str]:
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise PackAdminError(f"zip 裡有絕對路徑：{name}")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PackAdminError(f"zip 裡有往上跳的路徑：{name}")
    return parts


def _members(z: zipfile.ZipFile) -> List[Tuple[zipfile.ZipInfo, List[str]]]:
    infos = z.infolist()
    if len(infos) > MAX_FILES:
        raise PackAdminError(f"檔案太多（{len(infos)} 個，最多 {MAX_FILES}）")
    total = 0
    out = []
    for info in infos:
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise PackAdminError(f"zip 裡有捷徑（符號連結）：{info.filename}")
        parts = _safe_parts(info.filename)
        if not parts:
            continue
        total += info.file_size
        if total > MAX_UNZIPPED:
            raise PackAdminError("解開太大（超過 20 MB）")
        out.append((info, parts))
    return out


def _strip_root(members) -> List[Tuple[zipfile.ZipInfo, List[str]]]:
    files = [(i, p) for i, p in members if not i.is_dir()]
    if any(p == ["pack.json"] for _i, p in files):
        return files
    tops = {p[0] for _i, p in files}
    if len(tops) == 1 and all(len(p) > 1 for _i, p in files):
        stripped = [(i, p[1:]) for i, p in files]
        if any(p == ["pack.json"] for _i, p in stripped):
            return stripped
    raise PackAdminError("zip 裡找不到 pack.json（要在最上層，或在唯一的那個資料夾裡）")


def staging_root(data_dir: str) -> str:
    return os.path.join(data_dir, "web_uploads")


def stage(blob: bytes, data_dir: str) -> Tuple[str, Dict]:
    """上傳的 zip → 解到暫存資料夾、檢查 → (token, 摘要)。不合丟 PackAdminError。"""
    if not blob:
        raise PackAdminError("沒有收到檔案")
    if len(blob) > MAX_UPLOAD:
        raise PackAdminError("檔案太大（最多 5 MB）")
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise PackAdminError("不是 zip 檔（.synoxpack 要是 pack 資料夾壓成的 zip）")
    with z:
        files = _strip_root(_members(z))
        token = secrets.token_urlsafe(16)
        folder = os.path.join(staging_root(data_dir), token, "pack")
        os.makedirs(folder)
        try:
            for info, parts in files:
                target = os.path.join(folder, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            m = read(folder)
        except ManifestError as e:
            shutil.rmtree(os.path.dirname(folder), ignore_errors=True)
            raise PackAdminError(f"pack.json 不合：{e}")
        except Exception:
            shutil.rmtree(os.path.dirname(folder), ignore_errors=True)
            raise
    summary = {"token": token, "name": m.name, "title": m.title, "summary": m.summary, "version": m.version,
               "kind": m.kind, "access": m.access, "storage": m.storage,
               "files": sorted("/".join(p) for _i, p in files)[:100],
               "panel": bool(m.web.get("panel")), "api": list(m.web.get("api", [])),
               "warnings": warnings_for(m)}
    return token, summary


def warnings_for(m) -> List[str]:
    out = []
    if m.kind == "python":
        out.append("這是 python pack：它的程式會在 SYNOX 裡面、用你的 Windows 帳號權限執行。只裝你信得過的人給的。")
    if m.kind == "cli":
        out.append("這是 cli pack：會在這台電腦上執行它指定的程式。")
    if m.access == "everyone":
        out.append("access 是 everyone：伺服器版裡任何傳訊息給 bot 的人都用得到。")
    out.append("安全管線只做了第 1 關（宣告檢查）；靜態掃描與完整性鎖定還沒做。")
    return out


def install_staged(token: str, data_dir: str, packs_dir: str) -> str:
    if not TOKEN_RE.match(token or ""):
        raise PackAdminError("找不到這次上傳（重新上傳一次）")
    folder = os.path.join(staging_root(data_dir), token, "pack")
    if not os.path.isdir(folder):
        raise PackAdminError("找不到這次上傳（重新上傳一次）")
    try:
        m = read(folder)
    except ManifestError as e:
        raise PackAdminError(f"pack.json 不合：{e}")
    target = os.path.join(packs_dir, m.name)
    if os.path.exists(target):
        raise PackAdminError(f"已經有叫 {m.name} 的 pack 了；要換新版先移除舊的。")
    os.makedirs(packs_dir, exist_ok=True)
    shutil.move(folder, target)
    shutil.rmtree(os.path.join(staging_root(data_dir), token), ignore_errors=True)
    return m.name


def remove(name: str, packs_dir: str, now=None) -> str:
    """packs/<name> → packs/_removed/<name>-<時間>（不刪，搬走）。回搬到哪。"""
    if not name or not re.match(r"^[a-z][a-z0-9_-]{0,31}$", name):
        raise PackAdminError("pack 名字不對")
    folder = os.path.join(packs_dir, name)
    if not os.path.isfile(os.path.join(folder, "pack.json")):
        raise PackAdminError(f"packs/ 裡沒有 {name}（出廠的 connector 設計稿不能從這裡移除）")
    dest_root = os.path.join(packs_dir, REMOVED)
    os.makedirs(dest_root, exist_ok=True)
    dest = os.path.join(dest_root, f"{name}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}")
    shutil.move(folder, dest)
    return dest


def reload(app, config, vault, dirs) -> loader.LoadReport:
    """在跑著的 app 上重新載入全部 pack：拿掉現在每個 pack 的群組，再跑一次 loader。
    限制：pack 自己 bind_callback 的按鈕前綴拿不掉（registry 沒有解除綁定），那種 pack 重新載入會失敗、記在報告裡。"""
    packs = app.extras.setdefault("synox_packs", [])
    for pack in list(packs):
        loader._drop_group(app.registry, pack.manifest.group)
    packs.clear()
    report = loader.load_all(app, config, vault, dirs=dirs)
    logging.info("[PACKS] reloaded: %s", ", ".join(f"{i.name}={i.status}" for i in report.items))
    return report
