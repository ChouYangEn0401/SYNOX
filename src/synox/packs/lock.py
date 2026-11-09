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
- 雜湊涵蓋 pack 資料夾裡的**每一個檔**（P7：含 __pycache__、node_modules、執行檔；`"hash_scope": "all"`）。
  P7 以前寫的鎖沒有 hash_scope：照當時的算法（跳過 __pycache__）對檔，不會因為升級 SYNOX 就全部變成被改過。
  SYNOX 開 cli／mcp 子程序時一律 PYTHONDONTWRITEBYTECODE=1，自己不會在 pack 資料夾裡產生 __pycache__。
  pack 資料夾**外**的程式（cli.argv 的 npx、git、絕對路徑、{python} -m 外部模組）不進雜湊：鎖裡的 t2.external
  記解析後的路徑，報告標「未鎖定執行環境」。
- T2（P7，packs/tier.py）：`"tier": "T0|T1|T2"`；T2 另外有 `"t2": {"opaque", "external", "packages", "runs"}`、
  `"trusted_publisher"`（安裝者明確輸入的 pack.json publisher）、`"trusted_at"`。
- trust（PERM-2）：`"trust": "core"｜"third-party"`，擁有者在安裝報告上選（預設 third-party），跟著每一筆鎖；
  也記當時的 `surfaces`／`data`。**舊的鎖沒有 trust**＝當作 third-party（`trust_of`）；沒有鎖＝None（出廠、手放的，由呼叫的人決定）。
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
CORE, THIRD_PARTY = "core", "third-party"
TRUSTS = (CORE, THIRD_PARTY)
DEFAULT_TRUST = THIRD_PARTY


def check_trust(trust) -> str:
    """None／"" → 預設 third-party；core｜third-party 原樣；其他丟 ValueError。"""
    if trust in (None, ""):
        return DEFAULT_TRUST
    if trust not in TRUSTS:
        raise ValueError(f"trust 只能是 {'、'.join(TRUSTS)}（現在是 {trust!r}）")
    return trust


def trust_of(data_dir: str, name: str) -> "Optional[str]":
    """packs.lock 記的 trust；舊的鎖沒寫＝third-party；沒有鎖＝None。"""
    found = entry(data_dir, name)
    if found is None:
        return None
    value = found.get("trust")
    return value if value in TRUSTS else DEFAULT_TRUST


def lock_path(data_dir: str) -> str:
    return os.path.join(data_dir, LOCK_FILE)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


HASH_SCOPE_ALL = "all"


def hash_files(folder: str, include_cache: bool = True) -> Dict[str, str]:
    """pack 資料夾 → {相對路徑: sha256}：**每一個檔**（含 __pycache__、node_modules、執行檔；P7）。
    include_cache=False 是舊的算法（跳過 __pycache__），只給 P7 以前寫的鎖對檔用（hashes_for）。"""
    return {rel: sha256_file(os.path.join(folder, *rel.split("/")))
            for rel in pack_files(folder, include_cache=include_cache)}


def hashes_for(record: Optional[dict], folder: str) -> Dict[str, str]:
    """照這一筆鎖當時的算法重算：hash_scope=all（P7 之後）＝每個檔；舊的鎖＝跳過 __pycache__。"""
    scope_all = isinstance(record, dict) and record.get("hash_scope") == HASH_SCOPE_ALL
    return hash_files(folder, include_cache=scope_all)


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
            folder: Optional[str] = None, now: Optional[float] = None, trust: Optional[str] = None,
            tier_fields: Optional[dict] = None) -> dict:
    """寫（或換掉）這個 pack 的鎖。hashes 沒給就現算 folder（預設 manifest.folder）；一律是每個檔（hash_scope=all）。
    trust：core｜third-party（沒給＝third-party；不認得丟 ValueError）。
    tier_fields：tier.lock_fields 的結果（tier、t2、trusted_publisher、trusted_at）；沒給＝照檔案現算 tier（不寫確認）。"""
    trust = check_trust(trust)
    hashes = dict(hashes) if hashes is not None else hash_files(folder or manifest.folder)
    if tier_fields is None:
        from synox.packs import tier as pack_tier
        tier_fields = pack_tier.lock_fields(pack_tier.assess(manifest, report), None)
    record = {"name": manifest.name, "version": manifest.version, "kind": manifest.kind,
              "publisher": getattr(manifest, "publisher", ""), "files": hashes, "hash_scope": HASH_SCOPE_ALL,
              "scan": report.summary(manifest) if report is not None else {},
              "trust": trust, "surfaces": list(getattr(manifest, "surfaces", ["dm"])),
              "data": getattr(manifest, "data", "none"),
              "approved_by": approved_by, "via": via,
              "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), **tier_fields}
    with _LOCK:
        data = load(data_dir)
        data["packs"][manifest.name] = record
        jsonstore.save_json(lock_path(data_dir), data)
    return record


def restore(data_dir: str, name: str, record: dict) -> None:
    """`packs rollback`：把搬走時留下的那一筆鎖原樣放回（呼叫的人先確認過檔案對得上）。"""
    with _LOCK:
        data = load(data_dir)
        data["packs"][name] = dict(record)
        jsonstore.save_json(lock_path(data_dir), data)


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
        actual = hashes_for(found, folder)
    except OSError as e:
        return TAMPERED, [f"讀不了：{e}"]
    changes = diff(found.get("files") or {}, actual)
    return (TAMPERED, changes) if changes else (LOCKED, [])


def check_integrity(manifest, hashes: Dict[str, str]) -> List[str]:
    """pack.json 的 integrity.sha256（作者打包時算的）跟實際的檔案比。沒寫 integrity 回 []。"""
    declared = getattr(manifest, "integrity", {}) or {}
    if not declared:
        return []
    # __pycache__ 不是作者打包的東西（synox-sdk zip 不放、安裝不解出來）：不跟 integrity 比；packs.lock 照樣鎖它
    actual = {k: v for k, v in hashes.items() if k != "pack.json" and "__pycache__" not in k.split("/")[:-1]}
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
