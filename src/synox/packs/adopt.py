"""
「送去安裝頁檢查」：把手放進 packs/、沒有 packs.lock 那一筆的工具送進正常的安裝流程（ADR 0028 §4，S9）。

沒有經過安裝頁的工具 SYNOX 不載入（loader：狀態 unapproved）。擁有者在設定頁按「送去安裝頁檢查」→
  stage_unlocked(name, packs_dir, data_dir)：把 packs/<name>/ 原地壓成 zip 的位元組（只讀檔案，不執行任何東西；
      捷徑／符號連結／junction 一律拒）→ admin.stage（跟上傳 .synoxpack 同一條路：zip 檢查、簽章、第 1、2 關）
      → 同一份報告；暫存的 staged.json 多記 adopt（哪個資料夾），摘要多一個 "adopt": name。
  install(token, ...)：按了確認 → 再確認 packs/<name> **仍然**沒有鎖、pack.json 的名字還是同一個 →
      把它搬到 packs/_removed/<name>-<版本>-<時間>（upgrade.archive，reason="adopt"，不刪）→ admin.install_staged
      照一般安裝把暫存那一份搬進來、寫鎖。中途失敗：搬走的那一份搬回原位，再把錯誤往外丟。
工具的資料在 data/（data/<name>.json、data/packs/<name>/、data/users/…），不在 pack 資料夾，送去安裝不會動到。

packs.dirs 指過去的資料夾不能送（那不是 SYNOX 管的資料夾、搬不了）：開發者跑 `python -m synox packs lock --approve <name>`。
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import zipfile
from typing import Dict, Optional, Tuple

from isdtelekit.core import jsonstore

from synox.packs import admin, upgrade
from synox.packs import lock as pack_lock
from synox.packs.admin import PackAdminError
from synox.packs.manifest import NAME_RE, ManifestError, read

ADOPT_KEY = "adopt"                  # staged.json 與摘要：送去安裝的是哪一個工具（名字）
ADOPT_FOLDER_KEY = "adopt_folder"    # staged.json：packs/ 底下的資料夾名（通常跟名字一樣）


def _is_link(path: str) -> bool:
    """符號連結或 Windows 的 junction／其他 reparse point。"""
    try:
        st = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _find(name: str, packs_dir: str) -> str:
    """packs/ 底下 pack.json 的 name 是 name 的那個資料夾（先看 packs/<name>）。找不到丟 PackAdminError。"""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise PackAdminError("工具的名字不對，重新整理設定頁再按一次")
    candidates = [name] + sorted(e for e in (os.listdir(packs_dir) if os.path.isdir(packs_dir) else [])
                                 if e != name and e != admin.REMOVED and not e.startswith("."))
    for entry in candidates:
        folder = os.path.join(packs_dir, entry)
        if not os.path.isfile(os.path.join(folder, "pack.json")):
            continue
        try:
            if read(folder).name == name:
                return folder
        except ManifestError:
            if entry == name:
                return folder            # 名字對、pack.json 壞了：照樣送去檢查，第 1 關會說哪裡不對
    raise PackAdminError(f"packs 資料夾裡找不到 {name}（可能已經被移走了）。重新整理設定頁再看一次；"
                         "如果它是 config.json packs.dirs 指過去的，在電腦上跑 "
                         f"python -m synox packs lock --approve {name}")


def _zip_folder(folder: str) -> bytes:
    """pack 資料夾 → zip 的位元組：只拿一般檔案、pack.json 在最上層、路徑用 / 接；跳過 __pycache__；
    碰到捷徑（符號連結、junction）就拒：連結可能指到 pack 外面（例如你的文件），不能偷偷把那裡的東西一起裝。"""
    if _is_link(folder):
        raise PackAdminError(f"{os.path.basename(folder)} 本身是捷徑（連結），不能送去安裝。"
                             "請把真正的工具資料夾（或它的 .synoxpack 檔）拿去安裝頁上傳")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for base, dirnames, filenames in os.walk(folder, followlinks=False):
            rel_base = os.path.relpath(base, folder)
            keep = []
            for d in sorted(dirnames):
                if d == "__pycache__":
                    continue
                if _is_link(os.path.join(base, d)):
                    raise PackAdminError(_link_error(rel_base, d))
                keep.append(d)
            dirnames[:] = keep
            for fname in sorted(filenames):
                path = os.path.join(base, fname)
                if _is_link(path):
                    raise PackAdminError(_link_error(rel_base, fname))
                if not stat.S_ISREG(os.lstat(path).st_mode):
                    raise PackAdminError(f"工具資料夾裡有不是一般檔案的東西：{_rel(rel_base, fname)}。把它拿掉再按一次")
                info = zipfile.ZipInfo(_rel(rel_base, fname))
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = os.lstat(path).st_mode & 0o777 if os.name != "nt" else 0o644    # Windows 沒有執行位元
                info.external_attr = (stat.S_IFREG | mode) << 16
                with open(path, "rb") as f:
                    z.writestr(info, f.read())
    return buf.getvalue()


def _rel(rel_base: str, name: str) -> str:
    return name if rel_base in ("", ".") else rel_base.replace(os.sep, "/") + "/" + name


def _link_error(rel_base: str, name: str) -> str:
    return (f"工具資料夾裡有捷徑（符號連結或 junction）：{_rel(rel_base, name)}。捷徑可能指到工具外面的檔案，"
            "SYNOX 不會把它送去安裝。請把捷徑換成真正的檔案，或向作者要 .synoxpack 檔從安裝頁上傳")


def stage_unlocked(name: str, packs_dir: str, data_dir: str) -> Tuple[str, Dict]:
    """沒有鎖的 packs/<name> → 壓成 zip → admin.stage（zip 檢查、簽章、第 1、2 關）→ (token, 摘要)。
    摘要多一個 "adopt": name（網頁照一般安裝報告畫，確認時改叫 install）。
    PackAdminError／GateRefused 照原樣往外丟（GateRefused 帶報告、沒有確認鈕）。"""
    folder = _find(name, packs_dir)
    if pack_lock.entry(data_dir, name) is not None:
        raise PackAdminError(f"{name} 已經經過安裝頁、有鎖了，不用再送。重新整理設定頁看看它的狀態")
    blob = _zip_folder(folder)
    token, summary = admin.stage(blob, data_dir)
    try:
        meta = admin.staged_meta(token, data_dir)
        staged_name = meta.get("name")
        if staged_name != name:
            raise PackAdminError(f"pack.json 裡的名字（{staged_name}）跟要送的工具（{name}）不一樣，不送。"
                                 "重新整理設定頁再看一次")
        meta[ADOPT_KEY] = name
        meta[ADOPT_FOLDER_KEY] = os.path.basename(folder)
        if isinstance(meta.get("summary"), dict):
            meta["summary"][ADOPT_KEY] = name
        jsonstore.save_json(os.path.join(admin.staging_root(data_dir), token, admin.STAGED_META), meta)
    except Exception:
        admin.discard_staged(token, data_dir)
        raise
    summary = dict(summary)
    summary[ADOPT_KEY] = name
    return token, summary


def adopted_name(token: str, data_dir: str) -> Optional[str]:
    """這次暫存是不是「送去安裝頁檢查」來的：是＝工具名字，不是＝None（讀不到丟 PackAdminError）。"""
    found = admin.staged_meta(token, data_dir).get(ADOPT_KEY)
    return found if isinstance(found, str) and found else None


def install(token: str, data_dir: str, packs_dir: str, approved_by=None, via: str = "web",
            trust: Optional[str] = None, trust_publisher: Optional[str] = None,
            runtime: Optional[str] = None, accept_warnings=None) -> str:
    """按了確認：packs/<name> 仍然沒有鎖 → 搬到 packs/_removed/（不刪）→ admin.install_staged 裝暫存那一份、寫鎖。
    任何一步失敗：搬走的那一份搬回原位、錯誤照原樣往外丟（PackAdminError／GateRefused）。回工具名字。"""
    meta = admin.staged_meta(token, data_dir)
    name = meta.get(ADOPT_KEY)
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise PackAdminError("這一份不是「送去安裝頁檢查」來的，請用一般的「確認安裝」")
    if meta.get("name") != name:
        raise PackAdminError("暫存的工具名字對不上，不裝。重新整理設定頁再按一次「送去安裝頁檢查」")
    folder_name = meta.get(ADOPT_FOLDER_KEY) or name
    if (not isinstance(folder_name, str) or folder_name in (".", "..", admin.REMOVED)
            or os.path.basename(folder_name) != folder_name or "/" in folder_name or "\\" in folder_name):
        raise PackAdminError("暫存的資料夾名字不對，不裝。重新整理設定頁再按一次「送去安裝頁檢查」")
    folder = os.path.join(packs_dir, folder_name)
    if pack_lock.entry(data_dir, name) is not None:
        raise PackAdminError(f"{name} 在你看報告的時候已經裝好、有鎖了，這一份不裝。重新整理設定頁看看它的狀態")
    if not os.path.isfile(os.path.join(folder, "pack.json")):
        raise PackAdminError(f"packs 資料夾裡的 {name} 不見了（可能被移走了）。重新整理設定頁再看一次")
    try:
        current = read(folder)
    except ManifestError:
        current = None
    if current is not None and current.name != name:
        raise PackAdminError(f"packs/{folder_name} 的 pack.json 名字變了（現在是 {current.name}），不裝。"
                             "重新整理設定頁再按一次「送去安裝頁檢查」")
    if folder_name != name and os.path.exists(os.path.join(packs_dir, name)):
        raise PackAdminError(f"packs 資料夾裡已經有另一個 {name} 資料夾，不裝。先把多的那個移走再按一次")
    version = current.version if current is not None else ""
    backup = upgrade.archive(folder, name, version, packs_dir, data_dir, reason="adopt")
    try:
        return admin.install_staged(token, data_dir, packs_dir, approved_by=approved_by, via=via, trust=trust,
                                    trust_publisher=trust_publisher, runtime=runtime,
                                    accept_warnings=accept_warnings)
    except BaseException:
        _put_back(backup, folder, os.path.join(packs_dir, name), data_dir, name)
        raise


def _put_back(backup: str, folder: str, target: str, data_dir: str, name: str) -> None:
    """install_staged 失敗：搬走的那一份放回 packs/<資料夾>。暫存那一份如果已經搬進來但沒寫鎖，先拿掉（它跟暫存是同一份）。"""
    if os.path.exists(target) and pack_lock.entry(data_dir, name) is None:
        shutil.rmtree(target, ignore_errors=True)
    if not os.path.exists(folder):
        shutil.move(backup, folder)
        try:
            os.remove(backup + upgrade.SIDECAR)
        except OSError:
            pass
