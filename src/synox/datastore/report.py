"""
每份資料的版本與要不要升級：`python -m synox data status|upgrade [--dry-run]`、doctor、網頁設定頁共用（ADR 0044）。

    collect(config_path, config, vault, upgrade=False, dry_run=True)
        → {"core": [Outcome…], "packs": [Outcome…]}
        upgrade=False（預設）：只看（doctor、設定頁、data status；不拿鎖、不寫）
        upgrade=True, dry_run=False：真的升（data upgrade；工具的 python 遷移照 packs.lock 對過才執行）
    lines(collected) → 給人看的幾行

工具只看有 data_schema 的、而且 packs.lock 對得上的（沒鎖、被改過的工具本來就不會載入，這裡也不碰它的資料）。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from synox.datastore import core, packdata
from synox.datastore.migrate import Outcome


def _packs(config) -> List:
    from synox.packs import loader
    from synox.packs.manifest import ManifestError, read
    out = []
    for folder in loader.discover(config.pack_dirs()):
        try:
            m = read(folder)
        except ManifestError:
            continue
        if getattr(m, "data_schema", None):
            out.append(m)
    return out


def collect(config_path: Optional[str], config, vault=None, *, upgrade: bool = False,
            dry_run: bool = True) -> Dict[str, List[Outcome]]:
    from synox.packs import lock as pack_lock
    data_dir = config.data_dir
    if upgrade and not dry_run:
        core_out = ([core.upgrade_config(config_path)] if config_path and os.path.exists(config_path) else [])
        core_out += core.upgrade_data_dir(data_dir)
    else:
        core_out = core.status(config_path if config_path and os.path.exists(config_path) else None, data_dir)
    packs_out: List[Outcome] = []
    for m in _packs(config):
        state, _changes = pack_lock.verify(data_dir, m.name, m.folder)
        if state != pack_lock.LOCKED:
            packs_out.append(Outcome(m.name, f"{m.title} 的資料", "failed",
                                     message="這個工具沒有經過安裝頁或檔案被改過，不會載入，也不碰它的資料"))
            continue
        use_vault = vault if getattr(m, "storage", "plain") == "vault" else None
        if getattr(m, "storage", "plain") == "vault" and vault is None:
            packs_out.append(Outcome(m.name, f"{m.title} 的資料", "failed",
                                     message="保管箱沒有打開，看不到這個工具的資料（python -m synox doctor 看原因）"))
            continue
        locked = dict((pack_lock.entry(data_dir, m.name) or {}).get("files") or {})
        packs_out.append(packdata.ensure(m, config, use_vault, dry_run=not (upgrade and not dry_run), locked=locked))
    return {"core": core_out, "packs": packs_out}


def lines(collected: Dict[str, List[Outcome]]) -> List[str]:
    out = []
    for r in collected.get("core", []):
        out.append("  " + r.line())
    for r in collected.get("packs", []):
        out.append("  " + r.line())
    return out


def problems(collected: Dict[str, List[Outcome]]) -> int:
    """要人處理的：失敗、太新（要升級的不算：下次啟動會自己升）。"""
    return sum(1 for group in collected.values() for r in group if not r.ok)


def to_dict(collected: Dict[str, List[Outcome]]) -> dict:
    return {"core": [r.to_dict() for r in collected.get("core", [])],
            "packs": [{**r.to_dict(), "pack": r.path} for r in collected.get("packs", [])],
            "needs_upgrade": any(r.needs_upgrade for g in collected.values() for r in g),
            "problems": problems(collected)}
