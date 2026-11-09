"""
安全管線第 3 關：完整性鎖定（架構 v1 §4；跟 ClawBot 14e「審查釘住 commit」同一個想法）。

`data/packs.lock`（JSON，SYNOX 的資料夾 data/ 裡）：

    {"version": 1, "packs": {
       "hello": {"name": "hello", "version": "0.1.0",
                 "files": {"pack.json": "<sha256>", "pack.py": "<sha256>", …},
                 "scan": {"files": 3, "findings": 0, "required": [], "declared": []},
                 "approved_by": 123456789, "via": "web", "approved_at": "2026-11-10T21:00:00"}}}

- 誰寫：Web UI 設定頁按「確認安裝」（stage → 第 1 關 → 第 2 關 → 給人看報告 → 確認 → 第 3 關 → 裝）、
  `python -m synox install <檔> --yes`、工程師的 `python -m synox packs lock --approve <name>`。
- 載入時（loader.load_all）：有鎖的 pack 每個檔重算 sha256；**不符＝不載入**（報告裡是 tampered），
  用 app.home 通知擁有者一次（同樣的竄改只通知一次，記在 data/packs_tamper_notified.json）；doctor 也列出來。
- 沒有鎖的 pack（出廠的、工程師直接放進 packs/ 的）照舊載入，報告與 doctor 標「未鎖定」——
  要鎖就 `python -m synox packs lock --approve <name>`。
- `__pycache__` 不算（loader 自己從原始碼編譯，不讀那裡的 .pyc）。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

from isdtelekit.core import jsonstore

from synox.packs.scan import pack_files

LOCK_FILE = "packs.lock"
NOTIFIED_FILE = "packs_tamper_notified.json"
_LOCK = threading.Lock()

LOCKED, UNLOCKED, TAMPERED = "locked", "unlocked", "tampered"


def lock_path(data_dir: str) -> str:
    return os.path.join(data_dir, LOCK_FILE)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_files(folder: str) -> Dict[str, str]:
    """pack 資料夾 → {相對路徑: sha256}（跳過 __pycache__）。"""
    return {rel: sha256_file(os.path.join(folder, *rel.split("/"))) for rel in pack_files(folder)}


def load(data_dir: str) -> dict:
    data = jsonstore.load_json(lock_path(data_dir), {}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    if not isinstance(data.get("packs"), dict):
        data["packs"] = {}
    return data


def entry(data_dir: str, name: str) -> Optional[dict]:
    found = load(data_dir)["packs"].get(name)
    return found if isinstance(found, dict) else None


def approve(data_dir: str, manifest, report, approved_by, *, via: str, hashes: Optional[Dict[str, str]] = None,
            folder: Optional[str] = None, now: Optional[float] = None) -> dict:
    """寫（或換掉）這個 pack 的鎖。hashes 沒給就現算 folder（預設 manifest.folder）。"""
    hashes = dict(hashes) if hashes is not None else hash_files(folder or manifest.folder)
    record = {"name": manifest.name, "version": manifest.version, "kind": manifest.kind,
              "publisher": getattr(manifest, "publisher", ""), "files": hashes,
              "scan": report.summary(manifest) if report is not None else {},
              "approved_by": approved_by, "via": via,
              "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))}
    with _LOCK:
        data = load(data_dir)
        data["packs"][manifest.name] = record
        jsonstore.save_json(lock_path(data_dir), data)
    return record


def remove(data_dir: str, name: str) -> bool:
    with _LOCK:
        data = load(data_dir)
        if data["packs"].pop(name, None) is None:
            return False
        jsonstore.save_json(lock_path(data_dir), data)
        return True


def diff(expected: Dict[str, str], actual: Dict[str, str]) -> List[str]:
    """兩份 {檔: sha256} 差在哪：['改了 pack.py', '多了 x.py', '少了 SKILL.md']。"""
    out = [f"改了 {f}" for f in sorted(expected) if f in actual and actual[f] != expected[f]]
    out += [f"多了 {f}" for f in sorted(actual) if f not in expected]
    out += [f"少了 {f}" for f in sorted(expected) if f not in actual]
    return out


def verify(data_dir: str, name: str, folder: str) -> Tuple[str, List[str]]:
    """(locked｜unlocked｜tampered, 差異清單)。"""
    found = entry(data_dir, name)
    if found is None:
        return UNLOCKED, []
    try:
        actual = hash_files(folder)
    except OSError as e:
        return TAMPERED, [f"讀不了：{e}"]
    changes = diff(found.get("files") or {}, actual)
    return (TAMPERED, changes) if changes else (LOCKED, [])


def check_integrity(manifest, hashes: Dict[str, str]) -> List[str]:
    """pack.json 的 integrity.sha256（作者打包時算的）跟實際的檔案比。沒寫 integrity 回 []。"""
    declared = getattr(manifest, "integrity", {}) or {}
    if not declared:
        return []
    actual = {k: v for k, v in hashes.items() if k != "pack.json"}
    problems = [f"integrity：{c}" for c in diff(declared, actual)]
    return problems


def fingerprint(changes: List[str], actual: Optional[Dict[str, str]] = None) -> str:
    blob = json.dumps({"changes": changes, "files": actual or {}}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def first_notice(data_dir: str, name: str, fp: str) -> bool:
    """同一個 pack、同一種竄改只回一次 True（之後回 False）。"""
    path = os.path.join(data_dir, NOTIFIED_FILE)
    with _LOCK:
        seen = jsonstore.load_json(path, {}) or {}
        if not isinstance(seen, dict):
            seen = {}
        if seen.get(name) == fp:
            return False
        seen[name] = fp
        jsonstore.save_json(path, seen)
        return True
