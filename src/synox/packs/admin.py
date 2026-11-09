"""
pack 裝卸：上傳 .synoxpack → 安全管線第 1–3 關 → 按確認才裝；移除＝搬到 packs/_removed/；重新載入。
Web UI 設定頁、`python -m synox install <檔>`、`python -m synox packs lock` 都用這裡。

.synoxpack＝一個 pack 資料夾壓成的 zip（pack.json 在最上層，或在唯一的那個資料夾裡）。

    stage(blob, data_dir)            zip 檢查 → 解到 data/web_uploads/<token>/pack/ → 第 1 關（宣告，嚴格版）
                                     → 第 2 關（靜態掃描＋integrity 對檔）→ (token, 摘要＋掃描報告)；過不了丟 GateRefused
    （給人看報告＋「要建環境」那一段（runtime.python／node = auto，packs/envs.py）、按確認）
    install_staged(token, …)         再跑一次 1、2 關、確認檔案跟看報告時一樣 → 搬進 packs/ → 第 3 關：寫 packs.lock（誰、何時）
    build_env(name, …, jobs, on_done)  裝好之後才建環境（JobRunner、最多 10 分鐘）；失敗＝pack 已裝、doctor 標環境沒建好

zip 本身：不能有絕對路徑、`..`、磁碟代號、符號連結；最多 MAX_FILES 個檔、解開最多 MAX_UNZIPPED。
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
import zipfile
from typing import Dict, List, Optional, Tuple

from synox.packs import envs, loader
from synox.packs import lock as pack_lock
from synox.packs.manifest import Manifest, ManifestError, read, synox_problem
from synox.packs.scan import ScanReport, scan

MAX_UPLOAD = 5 * 1024 * 1024
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


# ── 第 1、2 關 ─────────────────────────────────────────────────────────

def run_gates(folder: str) -> Tuple[Manifest, ScanReport, Dict[str, str], List[str]]:
    """一個 pack 資料夾跑第 1 關（嚴格的宣告檢查）與第 2 關（靜態掃描＋integrity 對檔）。
    回 (manifest, 掃描報告, 每個檔的 sha256, 拒裝理由)。pack.json 本身不合丟 PackAdminError。"""
    try:
        m = read(folder, strict=True)
    except ManifestError as e:
        raise PackAdminError(f"pack.json 不合（第 1 關）：{e}")
    report = scan(m)
    hashes = pack_lock.hash_files(folder)
    problems = report.problems(m) + pack_lock.check_integrity(m, hashes)
    too_old = synox_problem(m)                     # requires.synox：版本不合就不裝
    if too_old:
        problems.append(too_old)
    return m, report, hashes, problems


def summary_of(m: Manifest, report: ScanReport, hashes: Dict[str, str], problems: List[str],
               token: str = "") -> dict:
    return {"token": token, "name": m.name, "title": m.title, "summary": m.summary, "version": m.version,
            "kind": m.kind, "access": m.access, "storage": m.storage, "publisher": m.publisher,
            "files": sorted(hashes)[:100], "panel": bool(m.web.get("panel")), "api": list(m.web.get("api", [])),
            "capabilities": list(m.capabilities), "integrity": bool(m.integrity),
            "scan": {**report.to_dict(m), "problems": problems, "ok": not problems},
            "warnings": warnings_for(m, report), "env": env_plan(m).to_dict()}


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
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise PackAdminError("不是 zip 檔（.synoxpack 要是 pack 資料夾壓成的 zip）")
    with z:
        files = _strip_root(_members(z))
        token = secrets.token_urlsafe(16)
        root = os.path.join(staging_root(data_dir), token)
        folder = os.path.join(root, "pack")
        os.makedirs(folder)
        try:
            for info, parts in files:
                target = os.path.join(folder, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            m, report, hashes, problems = run_gates(folder)
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
        json.dump({"name": m.name, "hashes": hashes, "summary": summary}, f, ensure_ascii=False)
    return token, summary


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


def format_summary(summary: dict) -> str:
    """摘要＋掃描報告 → 給終端機看的字（`python -m synox install`）。"""
    labels = {"network": "連網", "subprocess": "開別的程式", "filesystem:own": "讀寫檔案",
              "filesystem:any": "讀寫 pack 以外的檔案", "exec": "動態執行程式碼"}

    def caps(xs) -> str:
        return "、".join(labels.get(c, c) for c in xs or []) or "（沒有）"

    scan_ = summary.get("scan") or {}
    lines = [f"📦 {summary.get('title')}（{summary.get('name')} {summary.get('version')}，{summary.get('kind')}）",
             f"  {summary.get('summary')}",
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
    env = summary.get("env") or {}
    if env.get("needed"):
        lines.append("🧱 要建環境（按確認之後才建）：")
        lines += [f"  · {line}" for line in env.get("lines") or []]
        lines.append(f"  （要網路，最多 10 分鐘；建在 data/envs/{summary.get('name')}/；失敗的話 pack 照樣裝好，"
                     f"doctor 會標「環境沒建好」）")
        lines += [f"  ⚠️ {p}" for p in env.get("problems") or []]
    lines += [f"⚠️ {w}" for w in summary.get("warnings") or []]
    return "\n".join(lines)


def warnings_for(m: Manifest, report: Optional[ScanReport] = None) -> List[str]:
    out = []
    if m.kind == "python":
        out.append("這是 python pack：它的程式會在 SYNOX 裡面、用你的 Windows 帳號權限執行。只裝你信得過的人給的。")
    if m.kind == "cli":
        out.append("這是 cli pack：會在這台電腦上執行它指定的程式（那支程式本身掃描看不到）。")
    if m.access == "everyone":
        out.append("access 是 everyone：伺服器版裡任何傳訊息給 bot 的人都用得到。")
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
    return out


# ── 第 3 關＋安裝 ──────────────────────────────────────────────────────

def install_staged(token: str, data_dir: str, packs_dir: str, approved_by=None, via: str = "web") -> str:
    """按了確認：再跑一次 1、2 關、檔案要跟看報告時一模一樣 → 搬進 packs/ → 寫 packs.lock。"""
    root = _staged_root(token, data_dir)
    folder = os.path.join(root, "pack")
    m, report, hashes, problems = run_gates(folder)
    if problems:
        raise GateRefused("拒裝（安全檢查沒過）：" + "；".join(problems[:12]),
                          summary_of(m, report, hashes, problems))
    try:
        with open(os.path.join(root, STAGED_META), "r", encoding="utf-8") as f:
            reviewed = json.load(f).get("hashes") or {}
    except (OSError, ValueError):
        raise PackAdminError("找不到這次上傳的檢查結果（重新上傳一次）")
    if reviewed != hashes:
        raise PackAdminError("暫存的檔案在你看報告之後被改過了，不裝（重新上傳一次）："
                             + "、".join(pack_lock.diff(reviewed, hashes)[:10]))
    target = os.path.join(packs_dir, m.name)
    if os.path.exists(target):                     # 同名＝升級：看過「改了什麼」再用 upgrade.upgrade_staged
        raise PackAdminError(f"已經裝了 {m.name}：這是升級，要先看「改了什麼」再按「確認升級」"
                             "（終端機：python -m synox install <檔> --yes 會自動走升級）。")
    os.makedirs(packs_dir, exist_ok=True)
    shutil.move(folder, target)
    shutil.rmtree(root, ignore_errors=True)
    pack_lock.approve(data_dir, m, report, approved_by, via=via, hashes=hashes, folder=target)
    logging.info("[PACKS] installed %s %s (approved by %s via %s)", m.name, m.version, approved_by, via)
    return m.name


def approve_installed(folder: str, data_dir: str, approved_by=None,
                      via: str = "cli") -> Tuple[Manifest, ScanReport, List[str]]:
    """已經在 packs/ 裡的 pack（工程師自己放的、自己改過的）：跑 1、2 關，過了就寫 packs.lock。
    回 (manifest, 報告, 拒裝理由)；有理由就沒有寫鎖。"""
    m, report, hashes, problems = run_gates(folder)
    if not problems:
        pack_lock.approve(data_dir, m, report, approved_by, via=via, hashes=hashes, folder=folder)
    return m, report, problems


def remove(name: str, packs_dir: str, now=None, data_dir: Optional[str] = None) -> str:
    """packs/<name> → packs/_removed/<name>-<版本>-<時間>（不刪，搬走；旁邊留當時的鎖，`packs rollback` 能放回）；
    packs.lock 的那一筆拿掉。回搬到哪。"""
    from synox.packs import upgrade
    if not name or not re.match(r"^[a-z][a-z0-9_-]{0,31}$", name):
        raise PackAdminError("pack 名字不對")
    folder = os.path.join(packs_dir, name)
    if not os.path.isfile(os.path.join(folder, "pack.json")):
        raise PackAdminError(f"packs/ 裡沒有 {name}（出廠的 connector 設計稿不能從這裡移除）")
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
