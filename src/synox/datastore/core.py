"""
SYNOX 核心自己的持久化資料：登記了哪些檔、各自目前的版本、0→1 的升級步驟（ADR 0044）。

    upgrade_config(config.json 的路徑)        啟動時第一件事（讀設定之前）
    upgrade_data_dir(data/)                   讀完設定、開工具之前
    status(config.json 的路徑, data/)          doctor、設定頁、`python -m synox data status`（只看不改）

已經接上的（其他還沒接上的見 docs/data-migrations.md 的盤點表與 ADR 0044 的採用計畫）：

    config.json            頂層 "schema_version"（新加；0→1 只補版本號）
    data/packs.lock        頂層 "version"（早就有，沿用；0→1 補上 packs 物件）
    data/pack_data.json    頂層 "schema_version"（新檔：工具資料的版本登記表，packdata.py）

**改這些檔的格式＝在這裡加一個遷移步驟（current+1、@X.step(舊版)）＋測試**（AGENTS.md）。
寫這些檔的程式一律先過 X.upgrade_data(data)：寫出去的永遠是目前的格式與版本號；檔案比較新就拒絕寫。
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from synox.datastore.migrate import JSON, Chain, JsonCodec, Outcome, inspect_file, upgrade_file

CONFIG = Chain("config.json", current=1, title="設定檔 config.json")
LOCK = Chain("packs.lock", current=1, version_key="version", title="工具核准紀錄 packs.lock")
PACK_DATA = Chain("pack_data.json", current=1, title="工具資料版本登記表 pack_data.json")


@CONFIG.step(0)
def _config_0_to_1(cfg: dict) -> dict:
    """1 版＝0 版加上 schema_version；內容不變。"""
    return cfg


@LOCK.step(0)
def _lock_0_to_1(data: dict) -> dict:
    """很早期的 packs.lock 沒有 version；packs 不是物件的當作空的（跟 lock.load 一樣）。"""
    if not isinstance(data.get("packs"), dict):
        data["packs"] = {}
    return data


@PACK_DATA.step(0)
def _pack_data_0_to_1(data: dict) -> dict:
    if not isinstance(data.get("packs"), dict):
        data["packs"] = {}
    return data


# 每個檔用原本寫它的程式的縮排（config.json：wizard.write_config；packs.lock：SDK 的 jsonstore）
CONFIG_CODEC = JsonCodec(indent=2)
DATA_FILES = (("packs.lock", LOCK, JSON), ("pack_data.json", PACK_DATA, JSON))


def upgrade_config(path: str, *, dry_run: bool = False) -> Outcome:
    return upgrade_file(path, CONFIG, CONFIG_CODEC, dry_run=dry_run)


def upgrade_data_dir(data_dir: str, *, dry_run: bool = False) -> List[Outcome]:
    return [upgrade_file(os.path.join(data_dir, name), chain, codec, dry_run=dry_run)
            for name, chain, codec in DATA_FILES]


def status(config_path: Optional[str], data_dir: str) -> List[Outcome]:
    """每一份登記的核心資料：版本、要不要升級（不拿鎖、不寫）。"""
    out = [inspect_file(config_path, CONFIG, CONFIG_CODEC)] if config_path else []
    return out + [inspect_file(os.path.join(data_dir, name), chain, codec) for name, chain, codec in DATA_FILES]


def upgrade_on_start(config_path: str, data_dir_of=None, *, log=logging) -> List[Outcome]:
    """啟動用：config.json 先升（讀設定之前），data_dir_of() 讀完設定拿 data/ 再升其他的。
    回全部結果；呼叫的人看 failed() 決定要不要停。太新的（較新版本寫的）只記 log、照樣開（那份檔不會被寫）。"""
    results = [upgrade_config(config_path)]
    if data_dir_of is not None:
        data_dir = data_dir_of()
        if data_dir:
            results += upgrade_data_dir(data_dir)
    for r in results:
        if r.action == "upgraded":
            log.info("[DATA] %s upgraded %s -> %s (backup %s)", r.kind, r.before, r.after, r.backup)
        elif not r.ok:
            log.warning("[DATA] %s: %s", r.kind, r.message)
    return results


def failed(results: List[Outcome]) -> List[Outcome]:
    """要擋住啟動的：步驟失敗、缺步驟、看不懂（太新的不算：只是不寫它）。"""
    return [r for r in results if r.action == "failed"]
