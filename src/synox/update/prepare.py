"""
Update.bat 的前半段（docs/adr/0023 §2、決定 U4、U5）：下載新版、驗證、解到暫存資料夾。**不動任何現在的檔案**。

`setup/update.ps1` 先叫 `python -m synox update --prepare`（就是這裡），過了才停 SYNOX、換檔。驗證放在 Python
是因為 Windows PowerShell 5.1 沒有 Ed25519；用的是**現在裝著、已經信任的**這份程式碼來驗新下載的檔。

順序（每一步不過就停，下載的檔刪掉，說一句人話）：
1. 怎麼裝的：git → 請 `git pull`；安裝程式 → 下載新的 Setup.exe；Docker → compose。只有 ZIP 裝法會自動換檔。
2. GitHub releases/latest（只有正式版）→ 比版本：不是比較新就不做（不降級；退回走 `Update.bat -Rollback`）。
3. `SHA256SUMS.txt`（必須有）→ ZIP 的 sha256；GitHub 附檔資訊有 digest 的話也要一樣。
4. 簽章：有 `release.json`＋`release.json.sig`、而且這個 SYNOX 有公鑰 → 一定要驗得過，release.json 的版本與 ZIP 的 sha256
   也要跟上面一樣（不過＝拒絕，`--allow-unsigned` 也救不了）。沒有簽章或沒有公鑰 → **不自動換檔**，除非使用者明確
   `--allow-unsigned`（`Update.bat -AllowUnsigned`），並照實說只信任 HTTPS＋GitHub。
5. 下載 ZIP 到 `data/update/<版本>/`（大小上限 MAX_ZIP），大小、sha256 都要對。
6. 解到 `data/update/<版本>/stage/`：只收 `SYNOX/` 底下的檔；拒絕絕對路徑、`..`、磁碟代號、連結；
   `config.json`、`data/`、`packs/`… （KEEP）就算在 ZIP 裡也不解；解完 `src/synox/__init__.py` 的版本要等於這一版。
7. 寫 `data/update/ready.json`（update.ps1 讀）：版本、暫存資料夾、要不要重裝套件（requirements／pyproject 的相依變了）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import zipfile
from typing import Optional

from synox import __version__
from synox.update import signing
from synox.update.check import (TEXT, Opener, UpdateError, compare, fetch_latest, get, how_line, install_kind)

MAX_ZIP = 400 * 1024 * 1024
MAX_SMALL = 1024 * 1024
MAX_UNPACKED = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 30000
READY = "ready.json"
# 換檔時「不是程式」的東西：留在原地，永遠不搬、不蓋（setup/update.ps1 的 $Keep 要一樣；tests/test_update.py 檢查）
KEEP = ("config.json", "data", "packs", ".venv", "runtime", "_previous", "lang.txt", "installer-choices.json", ".git")

PREP_TEXT = {
    "no_zip": "這一版的發佈頁沒有附 SYNOX-{v}.zip，沒辦法自動更新。請到發佈頁照「怎麼更新」手動做。",
    "no_sums": "這一版的發佈頁沒有附 SHA256SUMS.txt（檢查檔案有沒有被換過用的），為了安全不自動更新。",
    "not_in_sums": "SHA256SUMS.txt 裡沒有 SYNOX-{v}.zip 這一行，為了安全不自動更新。",
    "digest": "GitHub 記錄的檔案指紋跟 SHA256SUMS.txt 不一樣，為了安全沒有下載。",
    "bad_sig": "❌ 這一版的簽章對不上：檔案可能被動過。沒有更新，請不要手動裝這一版，並到 GitHub 回報（SECURITY.md）。",
    "bad_manifest": "❌ release.json 跟其他檔案對不起來（{why}）。沒有更新，請到 GitHub 回報（SECURITY.md）。",
    "unsigned": "⚠️ 這一版沒有簽章（或這個 SYNOX 還沒有可以驗簽章的公鑰），所以不自動換檔。\n"
                "  沒有簽章時，能確認的只有「檔案跟 GitHub 上這個 repo 的發佈頁一樣」（HTTPS＋SHA256SUMS.txt）；\n"
                "  如果有人盜用了維護者的 GitHub 帳號，這擋不住。\n"
                "  你接受這一點、還是要更新：重新執行 `Update.bat -AllowUnsigned`；或照發佈頁的「怎麼更新」手動做。",
    "unsigned_ok": "⚠️ 這一版沒有簽章：你用了 -AllowUnsigned，只確認檔案跟 GitHub 發佈頁上的一樣（HTTPS＋SHA256SUMS.txt）。",
    "signed_ok": "✅ 簽章驗過了（維護者簽的 release.json）。",
    "too_old": "這一版要從 {min_from} 以後才能直接更新（中間有資料要轉換）。請先更新到 {min_from}，再更新到 {v}。",
    "mismatch": "下載的檔案跟發佈頁寫的不一樣（可能沒下載完整，或被換過），已經刪掉、沒有更新。再試一次；一直這樣請到 GitHub 回報。",
    "bad_zip": "下載的 ZIP 裡面不對（{why}），已經刪掉、沒有更新。請到 GitHub 回報。",
    "current": "你已經是最新版（{v}），不用更新。",
    "ahead": "你裝的 {installed} 比最新的正式版 {v} 還新，不會「更新」成舊版。要回到上一版請用 Update.bat -Rollback。",
}


class AlreadyCurrent(UpdateError):
    pass


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def deps_fingerprint(folder: str) -> str:
    """會影響 .venv 的東西：requirements.txt、requirements.lock、pyproject.toml 的相依與 Python 版本那幾行。
    版本號那一行每版都變，不算。兩邊一樣＝不用重裝套件。"""
    h = hashlib.sha256()
    for name in ("requirements.txt", "requirements.lock"):
        try:
            with open(os.path.join(folder, name), "rb") as f:
                h.update(name.encode() + b"\0" + f.read().replace(b"\r\n", b"\n") + b"\0")
        except OSError:
            h.update(name.encode() + b"\0-\0")
    try:
        with open(os.path.join(folder, "pyproject.toml"), "r", encoding="utf-8") as f:
            for line in f:
                if re.match(r"^\s*(dependencies|requires-python|llm|dev)\s*=", line):
                    h.update(line.strip().encode("utf-8") + b"\n")
    except OSError:
        h.update(b"pyproject-")
    return h.hexdigest()


def _safe_member(name: str) -> Optional[str]:
    """ZIP 裡的路徑 → SYNOX/ 底下的相對路徑（用 /）；不安全或不在 SYNOX/ 底下回 None。"""
    if not name or "\\" in name or name.startswith("/") or ":" in name or "\0" in name:
        return None
    parts = name.split("/")
    if parts[0] != "SYNOX" or any(p in ("..", ".") for p in parts):
        return None
    rel = "/".join(p for p in parts[1:] if p)
    return rel or None


def extract_release(zip_path: str, stage: str, version: str) -> str:
    """解到 stage/SYNOX；回傳那個資料夾。不對丟 UpdateError（stage 會清掉）。"""
    target = os.path.join(stage, "SYNOX")
    if os.path.exists(stage):
        shutil.rmtree(stage)
    os.makedirs(target)
    try:
        with zipfile.ZipFile(zip_path) as z:
            infos = z.infolist()
            if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED:
                raise UpdateError(PREP_TEXT["bad_zip"].format(why="太大"))
            for info in infos:
                rel = _safe_member(info.filename)
                if rel is None:
                    if info.filename.rstrip("/") == "SYNOX":
                        continue
                    raise UpdateError(PREP_TEXT["bad_zip"].format(why=f"不安全的路徑 {info.filename!r}"))
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise UpdateError(PREP_TEXT["bad_zip"].format(why=f"有連結 {info.filename!r}"))
                if rel.split("/")[0] in KEEP:
                    logging.warning("[UPDATE] release zip carries %s: skipped (user data is never replaced)", rel)
                    continue
                dest = os.path.join(target, *rel.split("/"))
                if info.is_dir():
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
    except zipfile.BadZipFile:
        shutil.rmtree(stage, ignore_errors=True)
        raise UpdateError(PREP_TEXT["bad_zip"].format(why="不是 ZIP"))
    except UpdateError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    init = os.path.join(target, "src", "synox", "__init__.py")
    try:
        with open(init, "r", encoding="utf-8") as f:
            m = re.search(r'^__version__\s*=\s*"([^"]*)"', f.read(), re.M)
    except OSError:
        m = None
    if m is None or m.group(1) != version or not os.path.isfile(os.path.join(target, "Setup.bat")):
        shutil.rmtree(stage, ignore_errors=True)
        raise UpdateError(PREP_TEXT["bad_zip"].format(why=f"裡面不是 SYNOX {version}"))
    return target


def prepare(root: str, *, installed: str = __version__, allow_unsigned: bool = False,
            opener: Optional[Opener] = None, keys=None, say=print) -> dict:
    """下載＋驗證＋解開；成功回 ready（也寫進 data/update/ready.json）。不對丟 UpdateError（AlreadyCurrent＝不用更新）。"""
    kind = install_kind(root)
    if kind != "zip":
        raise UpdateError(how_line(kind))
    rel = fetch_latest(opener)
    state = compare(installed, rel.version)
    if state == "current":
        raise AlreadyCurrent(PREP_TEXT["current"].format(v=rel.version))
    if state != "newer":
        raise AlreadyCurrent(PREP_TEXT["ahead"].format(installed=installed, v=rel.version))
    zip_name = f"SYNOX-{rel.version}.zip"
    zasset, sums_asset = rel.asset(zip_name), rel.asset(signing.SUMS_ASSET)
    if zasset is None:
        raise UpdateError(PREP_TEXT["no_zip"].format(v=rel.version))
    if sums_asset is None:
        raise UpdateError(PREP_TEXT["no_sums"])
    sums = signing.parse_sums(get(sums_asset.url, MAX_SMALL, opener).decode("utf-8", "replace"))
    expected = sums.get(zip_name)
    if not expected:
        raise UpdateError(PREP_TEXT["not_in_sums"].format(v=rel.version))
    if zasset.digest.startswith("sha256:") and zasset.digest[7:] != expected:
        raise UpdateError(PREP_TEXT["digest"])
    signed = False
    manifest = {}
    man_a, sig_a = rel.asset(signing.MANIFEST_ASSET), rel.asset(signing.SIG_ASSET)
    if man_a is not None and sig_a is not None and signing.public_keys(keys):
        blob = get(man_a.url, MAX_SMALL, opener)
        sig = get(sig_a.url, MAX_SMALL, opener)
        if not signing.verify(blob, sig, keys):
            raise UpdateError(PREP_TEXT["bad_sig"])
        try:
            manifest = signing.parse_manifest(blob)
        except signing.SignatureError as e:
            raise UpdateError(PREP_TEXT["bad_manifest"].format(why=e))
        if manifest["version"] != rel.version:
            raise UpdateError(PREP_TEXT["bad_manifest"].format(why=f"版本 {manifest['version']} ≠ {rel.version}"))
        info = manifest["assets"].get(zip_name) or {}
        if str(info.get("sha256", "")).lower() != expected:
            raise UpdateError(PREP_TEXT["bad_manifest"].format(why="ZIP 的指紋不一樣"))
        if isinstance(info.get("size"), int) and zasset.size and info["size"] != zasset.size:
            raise UpdateError(PREP_TEXT["bad_manifest"].format(why="ZIP 的大小不一樣"))
        min_from = manifest.get("min_from")
        if isinstance(min_from, str) and compare(installed, min_from) == "newer":
            raise UpdateError(PREP_TEXT["too_old"].format(min_from=min_from, v=rel.version))
        signed = True
        say(PREP_TEXT["signed_ok"])
    elif not allow_unsigned:
        raise UpdateError(PREP_TEXT["unsigned"])
    else:
        say(PREP_TEXT["unsigned_ok"])

    base = os.path.join(root, "data", "update")
    work = os.path.join(base, rel.version)
    if os.path.exists(work):
        shutil.rmtree(work)
    os.makedirs(work)
    zip_path = os.path.join(work, zip_name)
    say(f"下載 {zip_name} …")
    try:
        with open(zip_path, "wb") as f:
            get(zasset.url, MAX_ZIP, opener, sink=f)
        if (zasset.size and os.path.getsize(zip_path) != zasset.size) or _sha256(zip_path) != expected:
            raise UpdateError(PREP_TEXT["mismatch"])
        say("檔案驗過了，解開到暫存資料夾 …")
        target = extract_release(zip_path, os.path.join(work, "stage"), rel.version)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    ready = {"version": rel.version, "from": installed, "stage": os.path.abspath(target),
             "zip": os.path.abspath(zip_path), "sha256": expected, "signed": signed,
             "rebuild_venv": bool(manifest.get("rebuild_venv")) or deps_fingerprint(root) != deps_fingerprint(target),
             "notes_url": rel.url, "keep": list(KEEP)}
    with open(os.path.join(base, READY), "w", encoding="utf-8") as f:
        json.dump(ready, f, ensure_ascii=False, indent=2)
    return ready


__all__ = ["KEEP", "AlreadyCurrent", "PREP_TEXT", "TEXT", "deps_fingerprint", "extract_release", "prepare"]
