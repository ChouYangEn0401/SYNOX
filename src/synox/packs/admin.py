"""
pack 裝卸：上傳 .synoxpack → 安全管線第 1–3 關 → 按確認才裝；移除＝搬到 packs/_removed/；重新載入。
Web UI 設定頁、`python -m synox install <檔>`、`python -m synox packs lock` 都用這裡。

.synoxpack＝一個 pack 資料夾壓成的 zip（pack.json 在最上層，或在唯一的那個資料夾裡）。

    stage(blob, data_dir)            zip 檢查 → 解到 data/web_uploads/<token>/pack/ → 第 1 關（宣告，嚴格版）
                                     → 第 2 關（靜態掃描＋integrity 對檔）→ (token, 摘要＋掃描報告)；過不了丟 GateRefused
    （給人看報告＋「要建環境」那一段（runtime.python／node = auto，packs/envs.py）、按確認）
    install_staged(token, …)         再跑一次 1、2 關、確認檔案跟看報告時一樣 → 搬進 packs/ → 第 3 關：寫 packs.lock（誰、何時、
                                     trust、runtime：用容器／不用，S2；報告的「🧱 執行環境」＝runtime_report）
    list_staged(data_dir)            還沒按確認的暫存（網頁的待核准清單）；順便清掉過期（STAGED_MAX_AGE）與半套的
    discard_staged(token, …)         「不要裝」：刪掉那一份暫存
    build_env(name, …, jobs, on_done)  裝好之後才建環境（JobRunner、最多 10 分鐘）；失敗＝pack 已裝、doctor 標環境沒建好

zip 本身：不能有絕對路徑、`..`、磁碟代號、符號連結；檔名不能是 Windows 保留名（CON、NUL、COM1…）、
不能有冒號（NTFS 資料流）或 Windows 不收的字元、結尾不能是空白或句點（_safe_parts，審查 B #E）；
不能有雙向文字控制字元（U+202A–U+202E、U+2066–U+2069）或零寬字元（U+200B–U+200D、U+FEFF）；
一段最多 MAX_PART 字、整條最多 MAX_REL_PATH 字；解壓縮時的 OSError 一律變成 PackAdminError（審查 C #C6，不再是網頁 500）；
最多 MAX_FILES 個檔、解開最多 MAX_UNZIPPED。
名字跟已經裝的 pack 一樣＝升級：比對、版本檢查、舊的搬到 _removed、退回都在 upgrade.py（install_staged 只裝新的）；
升級完環境要建／重建（upgrade.env_change）也走這裡的 build_env。
python pack 的程式會在 SYNOX 裡面、用你的 Windows 帳號權限執行——摘要會明講。
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import shutil
import stat
import time
import zipfile
from typing import Dict, List, Optional, Tuple

from synox.packs import envs, loader
from synox.packs import lock as pack_lock
from synox.packs import tier as pack_tier
from synox.packs.manifest import (DEFAULT_STAGE, Manifest, ManifestError, read, stage_label, stage_text,
                                  synox_problem)
from synox.packs.scan import ScanReport, scan

MAX_UPLOAD = 5 * 1024 * 1024
ZIP_MAGIC = b"PK\x03\x04"                 # 本機檔頭：.synoxpack 的第一個位元組就要是它（stage 檢查）
UPLOAD_TYPES = ("", "application/zip", "application/x-zip-compressed", "application/octet-stream")
MAX_UNZIPPED = 20 * 1024 * 1024
MAX_FILES = 300
REMOVED = "_removed"
STAGED_META = "staged.json"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class PackAdminError(ValueError):
    """給人看的錯誤。"""


class GateRefused(PackAdminError):
    """第 1、2 關沒過：拒裝。summary 裡有掃描報告（給網頁、終端機顯示）。"""

    def __init__(self, message: str, summary: Optional[dict] = None):
        super().__init__(message)
        self.summary = summary or {}


# Windows 的保留裝置名（不分大小寫、加副檔名也算：nul.txt、COM1.py）；COM¹ 這種上標數字 Windows 也當成裝置
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | \
    {f"{p}{n}" for p in ("COM", "LPT") for n in list("0123456789") + ["¹", "²", "³"]}
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
# 審查 C #C6：雙向文字控制字元（‮yp.a 在報告上會顯示成 a.py）與零寬字元（看不出來的兩個不同檔名）
_INVISIBLE_CHARS = re.compile("[​-‍‪-‮⁦-⁩﻿]")
# 審查 C #C6：太長的路徑在 Windows 解壓縮時會丟原生錯誤（網頁變成 500）；pack 不需要這麼深的路徑
MAX_PART = 100                    # 一段（資料夾名或檔名）最多幾個字
MAX_REL_PATH = 160                # pack 裡的相對路徑最多幾個字（暫存／安裝的資料夾還要再加上前面那一段）
MAX_FULL_PATH = 255               # 解壓縮的完整路徑（Windows 傳統上限 260，留一點餘裕）


def _safe_parts(name: str) -> List[str]:
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise PackAdminError(f"zip 裡有絕對路徑：{name}")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PackAdminError(f"zip 裡有往上跳的路徑：{name}")
    shown = name if len(name) <= 80 else name[:77] + "…"
    if _INVISIBLE_CHARS.search(name):
        raise PackAdminError(f"zip 裡的檔名有看不見的字元（雙向文字控制或零寬字元，報告上會顯示成別的名字）：{shown!r}")
    if len("/".join(parts)) > MAX_REL_PATH or any(len(p) > MAX_PART for p in parts):
        raise PackAdminError(f"zip 裡的路徑太長（一段最多 {MAX_PART} 字、整條最多 {MAX_REL_PATH} 字）：{shown}")
    for p in parts:                                     # 審查 B #E：防禦深度（Windows 解壓縮的怪名字）
        if ":" in p:
            raise PackAdminError(f"zip 裡的檔名有冒號（NTFS 資料流，例如 x.py::$DATA）：{name}")
        if _BAD_CHARS.search(p):
            raise PackAdminError(f"zip 裡的檔名有 Windows 不收的字元（< > \" | ? * 或控制字元）：{name}")
        if p != p.rstrip(" ."):
            raise PackAdminError(f"zip 裡的檔名結尾是空白或句點（Windows 會默默拿掉，變成另一個檔）：{name}")
        if p.split(".")[0].rstrip(" ").upper() in WINDOWS_RESERVED:
            raise PackAdminError(f"zip 裡的檔名是 Windows 的保留裝置名（CON、NUL、COM1…）：{name}")
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


# ── 第 1、2 關 ─────────────────────────────────────────────────────────

def run_gates(folder: str, exec_bits=()) -> Tuple[Manifest, ScanReport, Dict[str, str], List[str]]:
    """一個 pack 資料夾跑第 1 關（嚴格的宣告檢查）與第 2 關（靜態掃描＋integrity 對檔）。
    回 (manifest, 掃描報告, 每個檔的 sha256, 拒裝理由)。pack.json 本身不合丟 PackAdminError。
    exec_bits：zip 裡帶執行位元的檔（stage 記在 staged.json；掃不到內容的判斷要用）。"""
    try:
        m = read(folder, strict=True)
    except ManifestError as e:
        raise PackAdminError(f"pack.json 不合（第 1 關）：{e}")
    report = scan(m, exec_bits)
    hashes = pack_lock.hash_files(folder)
    problems = report.problems(m) + pack_lock.check_integrity(m, hashes)
    problems += envs.npm_source_problems(m)        # 審查 C #C8：npm 套件只准從 registry.npmjs.org 來
    too_old = synox_problem(m)                     # requires.synox：版本不合就不裝
    if too_old:
        problems.append(too_old)
    return m, report, hashes, problems


def summary_of(m: Manifest, report: ScanReport, hashes: Dict[str, str], problems: List[str],
               token: str = "") -> dict:
    return {"token": token, "name": m.name, "title": m.title, "summary": m.summary, "version": m.version,
            "kind": m.kind, "access": m.access, "storage": m.storage, "publisher": m.publisher,
            "stage": m.stage, "stage_label": m.stage_label, "stage_declared": m.stage_declared,
            "files": sorted(hashes)[:100], "panel": bool(m.web.get("panel")), "api": list(m.web.get("api", [])),
            "capabilities": list(m.capabilities), "integrity": bool(m.integrity),
            "scan": {**report.to_dict(m), "problems": problems, "ok": not problems},
            "warnings": warnings_for(m, report), "env": env_plan(m).to_dict(), "mcp": mcp_report(m), **scope_of(m),
            "tier": tier_of(m, report), "runtime": runtime_report(m), **theme_report(m, problems)}


def theme_report(m: Manifest, problems: List[str]) -> dict:
    """kind=theme：報告多一段 theme（顏色給畫面畫色票、換了哪些位置；第 1、2 關沒過就不給 markup）。"""
    if m.kind != "theme":
        return {}
    from synox.theme import pack as theme_pack
    if problems:
        return {"theme": {"tokens": m.theme.get("tokens") or {}, "slots": sorted(m.theme.get("slots") or {}),
                          "markup": {}, "fonts": [], "css": bool(m.theme.get("css"))}}
    return {"theme": theme_pack.report(m, m.theme)}


# ── 執行環境：用容器／不用（S2） ─────────────────────────────────────────

RUNTIME_TEXT = {"container": "用容器（建議）：在 podman／docker 的容器裡跑，只看得到自己的 pack 與資料夾",
                "host": "不用容器：直接在這台跑（伺服器版有 bwrap／systemd 就用它們）"}


def runtime_report(m: Manifest) -> dict:
    """安裝報告的「🧱 執行環境」：這台找得到哪些容器引擎（只用 which，不執行）、pack 有沒有提供容器、可以選什麼。"""
    from synox import sandbox
    from synox.packs import container as pack_container
    info = pack_container.summary(m)
    engines = {e: bool(sandbox._engine_which(e)) for e in sandbox.ENGINES}
    offered = bool(info)
    choices = [{"value": v, "text": RUNTIME_TEXT[v]} for v in (("container", "host") if offered else ("host",))]
    return {"offered": offered, "container": info, "engines": engines, "choices": choices,
            "default": "container" if offered else "host",
            "applies": m.kind == "cli" or m.mcp_stdio}


def offers_container(m: Manifest) -> bool:
    return bool((m.runtime or {}).get("container"))


def check_runtime(m: Manifest, runtime: Optional[str]) -> str:
    """擁有者選的 runtime（None＝照預設：有提供容器＝container）→ container｜host；不合丟 PackAdminError。"""
    if runtime in (None, ""):
        return "container" if (m.runtime or {}).get("container") else "host"
    if runtime not in pack_lock.RUNTIME_MODES:
        raise PackAdminError(f"runtime 只能是 {'、'.join(pack_lock.RUNTIME_MODES)}（現在是 {runtime!r}）")
    if runtime == "container" and not (m.runtime or {}).get("container"):
        raise PackAdminError(f"{m.name} 的 pack.json 沒有提供容器（runtime.container），只能選 host（不用容器）")
    return runtime


def format_runtime(summary: dict) -> List[str]:
    """終端機的「🧱 執行環境」那一段。"""
    rt = summary.get("runtime") or {}
    if not rt or not rt.get("applies"):
        return []
    engines = "、".join(f"{e} {'✅' if ok else '—'}" for e, ok in (rt.get("engines") or {}).items())
    lines = [f"🧱 執行環境：這台的容器引擎 {engines}（只看 PATH，沒有執行）"]
    info = rt.get("container") or {}
    if not rt.get("offered"):
        lines.append("  這個 pack 沒有提供容器（runtime.container）：只能直接在這台跑"
                     "（伺服器版的第三方／T2 pack 要 bwrap／systemd 才給成員）")
        return lines
    res = info.get("resources") or {}
    limits = "、".join(f"{k}={v}" for k, v in res.items()) or "照 policy.sandbox"
    lines.append(f"  這個 pack 提供容器：{info.get('run_image')}，network: {str(info.get('network')).lower()}，"
                 f"上限 {limits}" + (f"（Dockerfile {info.get('dockerfile')}）" if info.get("dockerfile") else ""))
    lines.append("  映像的內容 SYNOX 不看（跟 pip／npm 套件一樣）；執行時不會自己拉映像（--pull=never），要事先照 digest 拉好")
    lines.append("  要怎麼跑：預設「用容器」（終端機 --runtime container｜host；網頁在報告上選）")
    if not any((rt.get("engines") or {}).values()):
        lines.append("  ⚠️ 這台找不到 podman／docker：選了容器也會先退回直接跑（doctor 會說），裝好引擎後自動改用容器")
    return lines


EFFECT_TEXT = {"READ": "只讀", "WRITE": "會寫入", "DANGER": "危險（每次都要你按核准）"}


def mcp_report(m: Manifest) -> dict:
    """kind=mcp 的那一段：連法、連到哪、允許的每一個工具與它的 effect（安裝者逐一確認；沒寫 effect 的第 1 關就拒了）。
    http（遠端 MCP）是 T0：這台不跑它的程式，能信的只有這份宣告。不是 mcp 回 {}。"""
    if m.kind != "mcp":
        return {}
    from urllib.parse import urlsplit
    mcp = m.mcp or {}
    transport = mcp.get("transport") or ""
    auth = (m.auth_info or {}).get("type", "none")
    tools = [{"name": t, "effect": (mcp.get("effects") or {}).get(t) or "DANGER",
              "effect_text": EFFECT_TEXT.get((mcp.get("effects") or {}).get(t) or "DANGER", "")}
             for t in mcp.get("tools_allow") or []]
    return {"transport": transport or "（只登記）", "host": urlsplit(mcp.get("url") or "").netloc if mcp.get("url") else "",
            "trust_level": "T0（只有宣告）" if transport == "http" else "", "auth": auth, "tools": tools}


def format_mcp(summary: dict) -> List[str]:
    mcp = summary.get("mcp") or {}
    if not mcp:
        return []
    where = f"，連到 {mcp['host']}" if mcp.get("host") else ""
    level = f"，信任 {mcp['trust_level']}" if mcp.get("trust_level") else ""
    lines = [f"🔌 MCP：{mcp.get('transport')}{where}{level}；只允許下面這 {len(mcp.get('tools') or [])} 個工具（請逐一確認）："]
    lines += [f"  · {t['name']}：{t['effect']}（{t['effect_text']}）" for t in mcp.get("tools") or []]
    return lines


def tier_of(m: Manifest, report: ScanReport) -> dict:
    """安裝報告的信任層級那一段（packs/tier.py）：T2 有 warning_lines（紅字）與 needs_publisher。"""
    info = pack_tier.assess(m, report)
    return {**info, "warning_lines": pack_tier.warning_lines(info)}


# ── 權限宣告與信任（PERM-2） ───────────────────────────────────────────

SURFACE_TEXT = {"dm": "只能私訊", "channel": "私訊＋頻道（群組）"}
DATA_TEXT = {"none": "不存資料", "user": "每個人自己一份", "shared": "大家共用一份"}
TRUST_TEXT = {pack_lock.CORE: "核心（core）：信得過，跟出廠的一樣",
              pack_lock.THIRD_PARTY: "第三方（third-party）：別人寫的，伺服器版限制比較多"}


def scope_of(m: Manifest) -> dict:
    """安裝報告的「在哪裡用、資料屬於誰、信任」那一段（trust 由擁有者在報告上選，預設 third-party）。"""
    if m.kind == "theme":                      # 外觀包：不在聊天裡用、沒有資料、沒有程式可信任（報告不給選）
        return {}
    surfaces = list(m.surfaces)
    return {"surfaces": surfaces, "surfaces_text": SURFACE_TEXT["channel" if "channel" in surfaces else "dm"],
            "data": m.data, "data_text": DATA_TEXT.get(m.data, m.data), "data_declared": m.data_declared,
            "trust_choices": [{"value": t, "text": TRUST_TEXT[t]} for t in pack_lock.TRUSTS],
            "trust_default": pack_lock.DEFAULT_TRUST}


def _trust(trust) -> str:
    try:
        return pack_lock.check_trust(trust)
    except ValueError as e:
        raise PackAdminError(str(e))


def format_scope(summary: dict) -> List[str]:
    """終端機的那一段（format_summary 用）。"""
    if "data" not in summary:
        return []
    data = summary.get("data_text") or summary.get("data")
    note = "" if summary.get("data_declared") else "（沒寫，照預設推的）"
    return [f"🧭 在哪裡用：{summary.get('surfaces_text')}　資料：{data}{note}",
            f"🔑 信任：預設 {summary.get('trust_default')}（終端機加 --trust core 改成核心；"
            f"網頁在報告上選）"]


def env_plan(m: Manifest, data_dir: Optional[str] = None) -> "envs.EnvPlan":
    """第 2 關之後、確認之前的報告：要建什麼環境（runtime.python／node = auto）。只看、不跑。"""
    return envs.builder(data_dir).plan(m)


def build_env(name: str, data_dir: str, packs_dir: str, jobs, on_done) -> bool:
    """裝好之後（或 packs env rebuild）：照 pack.json 建 data/envs/<name>/。經 jobs（JobRunner）在背景跑，
    結束呼叫 on_done(BuildResult)。不用建回 False（on_done 不會被叫）。失敗不影響 pack 已經裝好：
    loader／doctor 會標「環境沒建好」。"""
    folder = os.path.join(packs_dir, name)
    try:
        m = read(folder)
    except ManifestError as e:
        raise PackAdminError(f"pack.json 不合：{e}")
    if not envs.needs_env(m):
        return False

    def done(result):
        if result.ok:
            logging.info("[PACKS] env for %s built", name)
        else:
            logging.warning("[PACKS] env for %s failed: %s", name, result.detail)
        on_done(result)

    envs.builder(data_dir).build(m, jobs, done)
    return True


def stage(blob: bytes, data_dir: str) -> Tuple[str, Dict]:
    """上傳的 zip → 解到暫存資料夾、跑第 1、2 關 → (token, 摘要)。zip 或 pack.json 不合丟 PackAdminError；
    掃描沒過丟 GateRefused（暫存清掉，摘要裡有報告）。"""
    if not blob:
        raise PackAdminError("沒有收到檔案")
    if len(blob) > MAX_UPLOAD:
        raise PackAdminError("檔案太大（最多 5 MB）")
    # zipfile 會從檔尾找目錄，前面接了別的東西（自解壓 exe、polyglot）也打得開；.synoxpack 一律從 zip 檔頭開始
    if not blob.startswith(ZIP_MAGIC):
        raise PackAdminError("不是 zip 檔（.synoxpack 要是 pack 資料夾壓成的 zip）")
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise PackAdminError("不是 zip 檔（.synoxpack 要是 pack 資料夾壓成的 zip）")
    with z:
        files = _strip_root(_members(z))
        # __pycache__ 不解出來（P7）：SYNOX 不用它，作者打包時本來就該排除；留著的話 Python 子程序會 import 那裡的 .pyc
        files = [(i, p) for i, p in files if "__pycache__" not in p[:-1]]
        token = secrets.token_urlsafe(16)
        root = os.path.join(staging_root(data_dir), token)
        folder = os.path.join(root, "pack")
        os.makedirs(folder)
        exec_bits = sorted("/".join(p) for i, p in files if (i.external_attr >> 16) & 0o111)
        try:
            for info, parts in files:
                target = os.path.join(folder, *parts)
                if len(os.path.abspath(target)) > MAX_FULL_PATH:
                    raise PackAdminError(f"zip 裡的路徑太長，這台解不開（{'/'.join(parts)[:80]}）："
                                         "請 pack 作者把資料夾層數或檔名縮短")
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with z.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                except OSError as e:                      # 審查 C #C6：原生錯誤不要變成網頁 500
                    raise PackAdminError(f"zip 裡的 {'/'.join(parts)[:80]} 解不開（{e.strerror or type(e).__name__}）："
                                         "路徑太長或檔名這台不收，請 pack 作者改短／改名")
            m, report, hashes, problems = run_gates(folder, exec_bits)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
    summary = summary_of(m, report, hashes, problems, token)
    if problems:
        shutil.rmtree(root, ignore_errors=True)
        summary["token"] = ""
        listing = "；".join(problems[:12]) + ("…" if len(problems) > 12 else "")
        raise GateRefused(f"拒裝（安全檢查沒過）：{listing}", summary)
    with open(os.path.join(root, STAGED_META), "w", encoding="utf-8") as f:
        json.dump({"name": m.name, "hashes": hashes, "summary": summary, "exec_bits": exec_bits}, f,
                  ensure_ascii=False)
    return token, summary


def staged_meta(token: str, data_dir: str) -> dict:
    """暫存那一份的 staged.json（hashes、summary、exec_bits）；讀不了丟 PackAdminError。"""
    root = _staged_root(token, data_dir)
    try:
        with open(os.path.join(root, STAGED_META), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise PackAdminError("找不到這次上傳的檢查結果（重新上傳一次）")
    return data if isinstance(data, dict) else {}


def stage_file(path: str, data_dir: str) -> Tuple[str, Dict]:
    """`python -m synox install <檔>` 用：讀檔再 stage。"""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise PackAdminError(f"讀不到 {path}：{e}")
    if size > MAX_UPLOAD:
        raise PackAdminError("檔案太大（最多 5 MB）")
    with open(path, "rb") as f:
        return stage(f.read(), data_dir)


def _staged_root(token: str, data_dir: str) -> str:
    if not TOKEN_RE.match(token or ""):
        raise PackAdminError("找不到這次上傳（重新上傳一次）")
    root = os.path.join(staging_root(data_dir), token)
    if not os.path.isdir(os.path.join(root, "pack")):
        raise PackAdminError("找不到這次上傳（重新上傳一次）")
    return root


def staged_summary(token: str, data_dir: str) -> dict:
    """暫存中的那一份的摘要（`synox install` 開網頁時，網頁用 token 拿報告）。"""
    root = _staged_root(token, data_dir)
    try:
        with open(os.path.join(root, STAGED_META), "r", encoding="utf-8") as f:
            return json.load(f)["summary"]
    except (OSError, ValueError, KeyError):
        raise PackAdminError("找不到這次上傳的檢查結果（重新上傳一次）")


STAGED_MAX_AGE = 7 * 24 * 3600      # 暫存（還沒按確認）超過 7 天＝過期，list_staged 時清掉
STAGED_HALF_DONE = 3600             # 沒有 staged.json 的暫存（解壓縮到一半、或當機留下的）超過 1 小時才清


def list_staged(data_dir: str, now: Optional[float] = None, max_age: float = STAGED_MAX_AGE) -> List[dict]:
    """等擁有者核准的暫存 pack（網頁「功能與安裝」的待核准清單；不用知道 token 也看得到）。
    順便清掉過期的（staged.json 超過 max_age）與半套的（沒有 staged.json、超過 STAGED_HALF_DONE）。
    只看 staging_root 底下名字像 token 的資料夾；符號連結一律不跟、不刪。新的排前面。"""
    now = time.time() if now is None else now
    base = staging_root(data_dir)
    try:
        names = os.listdir(base)
    except OSError:
        return []
    out = []
    for token in names:
        root = os.path.join(base, token)
        if not TOKEN_RE.match(token) or os.path.islink(root) or not os.path.isdir(root):
            continue
        meta_path = os.path.join(root, STAGED_META)
        try:
            age = now - os.path.getmtime(meta_path)
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            summary = meta["summary"]
        except (OSError, ValueError, KeyError, TypeError):
            try:
                half_done = now - os.path.getmtime(root) > STAGED_HALF_DONE
            except OSError:
                half_done = False
            if half_done:
                shutil.rmtree(root, ignore_errors=True)
            continue
        if age > max_age or not os.path.isdir(os.path.join(root, "pack")):
            shutil.rmtree(root, ignore_errors=True)
            logging.info("[PACKS] dropped stale staged upload %s (%s)", token[:6], summary.get("name"))
            continue
        tier = summary.get("tier") or {}
        out.append({"token": token, "name": str(summary.get("name") or ""), "version": str(summary.get("version") or ""),
                    "title": str(summary.get("title") or ""), "tier": str(tier.get("tier") or ""),
                    "staged_at": int(now - age), "expires_in": int(max(0, max_age - age))})
    out.sort(key=lambda s: -s["staged_at"])
    return out


def discard_staged(token: str, data_dir: str) -> None:
    """「不要裝」：把暫存那一份整個刪掉（staging_root 底下；token 格式不對或找不到丟 PackAdminError）。"""
    root = _staged_root(token, data_dir)
    if os.path.islink(root):
        raise PackAdminError("找不到這次上傳（重新上傳一次）")
    shutil.rmtree(root, ignore_errors=True)


def format_summary(summary: dict) -> str:
    """摘要＋掃描報告 → 給終端機看的字（`python -m synox install`）。"""
    labels = {"network": "連網", "subprocess": "開別的程式", "filesystem:own": "讀寫檔案",
              "filesystem:any": "讀寫 pack 以外的檔案", "exec": "動態執行程式碼"}

    def caps(xs) -> str:
        return "、".join(labels.get(c, c) for c in xs or []) or "（沒有）"

    scan_ = summary.get("scan") or {}
    lines = [f"📦 {summary.get('title')}（{summary.get('name')} {summary.get('version')}，{summary.get('kind')}）",
             f"  {summary.get('summary')}",
             f"  穩定度：{stage_label(summary.get('stage') or DEFAULT_STAGE, long=True)}"
             + ("" if summary.get("stage_declared", True) else "（pack.json 沒寫 stage，當作 alpha）"),
             f"  誰能用：{summary.get('access')}　發行者：{summary.get('publisher') or '（沒寫）'}　"
             f"{len(summary.get('files') or [])} 個檔" + ("　有打包時的雜湊" if summary.get("integrity") else ""),
             f"🔍 靜態掃描：宣告要 {caps(scan_.get('declared_capabilities'))}；"
             f"掃描看到要 {caps(scan_.get('required_capabilities'))}"]
    for f in scan_.get("findings") or []:
        where = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
        lines.append(f"  · {where}  {f.get('label')}  {f.get('detail') or f.get('snippet')}")
    problems = scan_.get("problems") or []
    if problems:
        lines.append("❌ 拒裝：")
        lines += [f"  - {p}" for p in problems]
    else:
        lines.append("✅ 宣告檢查、靜態掃描都過了")
    lines += format_mcp(summary)
    lines += format_theme(summary)
    lines += format_scope(summary)
    lines += format_tier(summary.get("tier") or {})
    lines += format_runtime(summary)
    env = summary.get("env") or {}
    if env.get("needed"):
        lines.append("🧱 要建環境（按確認之後才建）：")
        lines += [f"  · {line}" for line in env.get("lines") or []]
        lines.append(f"  （要網路，最多 10 分鐘；建在 data/envs/{summary.get('name')}/；失敗的話 pack 照樣裝好，"
                     f"doctor 會標「環境沒建好」）")
        lines += [f"  ⚠️ {p}" for p in env.get("problems") or []]
    lines += [f"⚠️ {w}" for w in summary.get("warnings") or []]
    return "\n".join(lines)


def format_theme(summary: dict) -> List[str]:
    """終端機的「🎨 外觀」那一段（kind=theme）。"""
    th = summary.get("theme") or {}
    if not th:
        return []
    light = th.get("tokens", {}).get("light") or {}
    lines = [f"🎨 外觀包：淺色主色 {light.get('accent', '?')}、底色 {light.get('bg', '?')}；"
             f"換掉的位置：{'、'.join(th.get('slots') or []) or '（沒有，只換顏色）'}"]
    if th.get("fonts"):
        lines.append(f"  附的字型：{'、'.join(th['fonts'])}（不會連到外面抓字型）")
    lines.append("  裝好後到網頁「設定 → 外觀」挑它按「套用」（看得到預覽）")
    return lines


def red(text: str) -> str:
    """終端機的紅字（不是終端機＝原樣，測試、log 看得到字）。"""
    import sys
    try:
        tty = sys.stdout.isatty()
    except (AttributeError, ValueError):
        tty = False
    return f"\033[31m{text}\033[0m" if tty else text


def format_tier(tier: dict) -> List[str]:
    """信任層級那一段：T2 用 🔴＋紅字；其他一行。"""
    if not tier:
        return []
    if tier.get("tier") != pack_tier.T2:
        return [f"🧩 信任層級：{tier.get('text') or tier.get('tier')}"]
    out = [red(f"🔴 信任層級：{tier.get('text')}——T2 不是沙盒保證，只是讓你知道你在信任誰")]
    out += [red(f"🔴 {line}") for line in tier.get("warning_lines") or []]
    for o in tier.get("opaque") or []:
        out.append(f"   · {o['path']}  {o['size']} bytes  sha256 {o['sha256']}  {o['why']}")
    return out


# 審查 B #B：第 2 關對 python 是提醒不是門（個人版、伺服器版都適用）
PYTHON_SCAN_NOTE = ("靜態掃描只攔得到直接寫出來的名字和常見的間接取用，是提醒、不是門：有心的人寫得出掃描看不出來的程式。"
                    "python pack 在 SYNOX 程序裡跑，個人版沒有任何隔離（讀得到你全部的資料、保管箱解開的東西、整台電腦的檔案）；"
                    "伺服器版第三方的 python pack 只給擁有者用（PERM-8）。")


def warnings_for(m: Manifest, report: Optional[ScanReport] = None) -> List[str]:
    out = []
    if m.stage != "stable":                   # 穩定度（作者自己標的；沒寫＝alpha）：網頁報告的提醒清單也看得到
        out.append(f"穩定度 {stage_label(m.stage, long=True)}：{stage_text(m.stage)}"
                   + ("" if m.stage_declared else "（pack.json 沒寫 stage，當作 alpha）") + "。")
    if m.kind == "theme":
        out.append("這是外觀包：只換網頁的顏色、字型和吉祥物圖案，沒有程式。裡面的 SVG／CSS 都重新消毒過"
                   "（不收程式、事件屬性、外部網址）；字型只能跟著包一起來，網頁不會連到外面抓字型。")
        out.append("裝好之後不會自己套用：到「設定 → 外觀」挑它、按「套用」；隨時可以按「換回原本的 SYNOX」。")
        if not m.publisher:
            out.append("沒有寫發行者（publisher）。")
        return out
    if m.kind == "python":
        out.append("這是 python pack：它的程式會在 SYNOX 裡面、用你的 Windows 帳號權限執行。只裝你信得過的人給的。")
        out.append(PYTHON_SCAN_NOTE)
    if m.kind == "cli":
        out.append("這是 cli pack：會在這台電腦上執行它指定的程式（那支程式本身掃描看不到）。")
    if m.mcp_http:
        from urllib.parse import urlsplit
        out.append(f"這是遠端 MCP（T0，只有宣告）：你的請求和 token 會送到 {urlsplit(m.mcp.get('url', '')).netloc}；"
                   "那台伺服器做什麼掃描看不到。只會用上面列的工具，effect 照這份宣告（不照伺服器自己說的）。")
    elif m.mcp_stdio:
        out.append("這是 MCP（stdio）pack：會在這台電腦上開一個長駐的子程序跑它的 MCP 伺服器。")
    if m.access == "everyone":
        out.append("access 是 everyone：伺服器版裡任何傳訊息給 bot 的人都用得到。")
    if "channel" in m.surfaces:
        out.append("它宣告可以在頻道（群組）裡用：頻道裡的人都看得到它的回覆。")
    if m.data == "shared":
        out.append("它的資料是大家共用一份（data: shared）：伺服器版只有管理員能用它會寫入的指令。")
    labels = {"network": "連網", "subprocess": "開別的程式", "filesystem:own": "讀寫檔案",
              "filesystem:any": "讀寫 pack 以外的任何檔案", "exec": "動態執行程式碼"}
    if m.capabilities:
        out.append("它宣告要：" + "、".join(labels.get(c, c) for c in m.capabilities) + "。")
    if report is not None and any(f.kind == "env" for f in report.findings):
        out.append("它會讀環境變數（可能讀得到放在環境變數裡的密鑰）。")
    if m.panel_path:
        out.append("它有網頁面板：面板跟 Web UI 同源，能做你在網頁上能做的事。")
    if not m.publisher:
        out.append("沒有寫發行者（publisher）。")
    from synox.packs.manifest import doc_warnings
    out += doc_warnings(m)                    # 說明不齊（SKILL.md frontmatter、summary、ask）：提醒、不擋
    return out


# ── 第 3 關＋安裝 ──────────────────────────────────────────────────────

def install_staged(token: str, data_dir: str, packs_dir: str, approved_by=None, via: str = "web",
                   trust: Optional[str] = None, trust_publisher: Optional[str] = None,
                   runtime: Optional[str] = None) -> str:
    """按了確認：再跑一次 1、2 關、檔案要跟看報告時一模一樣 → 搬進 packs/ → 寫 packs.lock。
    trust：擁有者在報告上選的 core｜third-party（沒給＝third-party），寫進鎖。
    trust_publisher：T2 pack（packs/tier.py）一定要給，而且跟 pack.json 的 publisher 一字不差；寫進鎖的
    trusted_publisher／trusted_at。T0／T1 不用（給了也不記）。
    runtime：container｜host（S2；沒給＝有提供容器就 container），寫進鎖的 runtime（跟 trust 並列）。"""
    trust = _trust(trust)
    root = _staged_root(token, data_dir)
    folder = os.path.join(root, "pack")
    meta = staged_meta(token, data_dir)
    m, report, hashes, problems = run_gates(folder, meta.get("exec_bits") or ())
    if problems:
        raise GateRefused("拒裝（安全檢查沒過）：" + "；".join(problems[:12]),
                          summary_of(m, report, hashes, problems))
    runtime = check_runtime(m, runtime)
    reviewed = meta.get("hashes") or {}
    if reviewed != hashes:
        raise PackAdminError("暫存的檔案在你看報告之後被改過了，不裝（重新上傳一次）："
                             + "、".join(pack_lock.diff(reviewed, hashes)[:10]))
    target = os.path.join(packs_dir, m.name)
    if os.path.exists(target):                     # 同名＝升級：看過「改了什麼」再用 upgrade.upgrade_staged
        raise PackAdminError(f"已經裝了 {m.name}：這是升級，要先看「改了什麼」再按「確認升級」"
                             "（終端機：python -m synox install <檔> --yes 會自動走升級）。")
    info = pack_tier.assess(m, report)
    refused = pack_tier.confirm_problem(info, m, trust_publisher)        # T2：要明確輸入 publisher
    if refused:
        raise PackAdminError(refused)
    os.makedirs(packs_dir, exist_ok=True)
    try:
        shutil.move(folder, target)
    except OSError as e:                                   # 審查 C #C6：例如 packs 資料夾的路徑比暫存的長
        shutil.rmtree(target, ignore_errors=True)
        raise PackAdminError(f"搬進 packs 資料夾失敗（{e.strerror or type(e).__name__}）：路徑可能太長；"
                             "暫存那一份還在，可以重新按一次或請 pack 作者把路徑改短")
    shutil.rmtree(root, ignore_errors=True)
    fields = pack_tier.lock_fields(info, trust_publisher if info["tier"] == pack_tier.T2 else None)
    pack_lock.approve(data_dir, m, report, approved_by, via=via, hashes=hashes, folder=target, trust=trust,
                      tier_fields=fields, runtime=runtime if offers_container(m) else None)
    logging.info("[PACKS] installed %s %s (approved by %s via %s, trust %s, runtime %s, tier %s%s)", m.name, m.version,
                 approved_by, via, trust, runtime, info["tier"],
                 f", trusted publisher {fields.get('trusted_publisher')!r}" if fields.get("trusted_publisher") else "")
    return m.name


def approve_installed(folder: str, data_dir: str, approved_by=None, via: str = "cli",
                      trust: Optional[str] = None, trust_publisher: Optional[str] = None,
                      runtime: Optional[str] = None) -> Tuple[Manifest, ScanReport, List[str]]:
    """已經在 packs/ 裡的 pack（工程師自己放的、自己改過的）：跑 1、2 關，過了就寫 packs.lock。
    trust 沒給＝沿用舊鎖的（沒有舊鎖：出廠的＝core，其他＝third-party）。回 (manifest, 報告, 拒裝理由)；有理由就沒有寫鎖。
    T2：舊鎖確認過同一個 publisher、可執行的東西沒變多、沒新增 exec＝沿用；否則要 trust_publisher（一字不差），
    不合的話理由放進回傳的清單（沒有寫鎖）。"""
    m, report, hashes, problems = run_gates(folder)
    if trust is None:
        trust = pack_lock.trust_of(data_dir, m.name)
    if trust is None and loader.is_bundled(m):
        trust = pack_lock.CORE          # 出廠的 pack 第一次鎖：沿用沒鎖時的 core（有鎖之後信任只看鎖）
    trust = _trust(trust)
    if problems:
        return m, report, problems
    info = pack_tier.assess(m, report)
    previous = pack_lock.entry(data_dir, m.name)
    typed = trust_publisher
    if info["tier"] == pack_tier.T2 and not typed:
        old_caps = (previous or {}).get("scan", {}).get("declared") or []
        from types import SimpleNamespace
        again = pack_tier.reconfirm_reasons(previous, SimpleNamespace(capabilities=old_caps), m, info)
        if again:
            refused = pack_tier.confirm_problem(info, m, None)
            return m, report, [refused + "（" + "；".join(again) + "）"] if refused else again
    else:
        refused = pack_tier.confirm_problem(info, m, typed)
        if refused:
            return m, report, [refused]
    fields = pack_tier.lock_fields(info, typed if info["tier"] == pack_tier.T2 else None, previous=previous)
    if runtime is None:                    # 沒給＝沿用舊鎖的（沒有舊鎖＝不寫，當作 host；packs runtime 可以改）
        runtime = pack_lock.runtime_mode(data_dir, m.name)
        if runtime == "container" and not offers_container(m):
            runtime = "host"
    else:
        runtime = check_runtime(m, runtime)
    pack_lock.approve(data_dir, m, report, approved_by, via=via, hashes=hashes, folder=folder, trust=trust,
                      tier_fields=fields, runtime=runtime if offers_container(m) else None)
    return m, report, []


def remove(name: str, packs_dir: str, now=None, data_dir: Optional[str] = None) -> str:
    """packs/<name> → packs/_removed/<name>-<版本>-<時間>（不刪，搬走；旁邊留當時的鎖，`packs rollback` 能放回）；
    packs.lock 的那一筆拿掉。回搬到哪。"""
    from synox.packs import upgrade
    if not name or not re.match(r"^[a-z][a-z0-9_-]{0,31}$", name):
        raise PackAdminError("pack 名字不對")
    folder = os.path.join(packs_dir, name)
    if not os.path.isfile(os.path.join(folder, "pack.json")):
        raise PackAdminError(f"packs/ 裡沒有 {name}（只有裝在 packs/ 的工具能從這裡移除；packs.dirs 指過去的請改 config.json）")
    installed = upgrade.installed_manifest(packs_dir, name)
    dest = upgrade.archive(folder, name, installed[0].version if installed else "", packs_dir, data_dir,
                           now=now, reason="remove")
    if data_dir:
        pack_lock.remove(data_dir, name)
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
