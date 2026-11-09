"""
pack 升級與退回（SDK P6）。同名的 pack 再裝一次＝升級：

    stage(...)                         跟一般安裝一樣：第 1、2 關（admin.stage）
    staged_upgrade(token, …)           已經裝了同名的 → 跟裝著的版本比對，回「改了什麼」報告（沒裝過回 None）
    （給人看報告、按「確認升級」）
    upgrade_staged(token, …)           再跑一次 1、2 關、檔案跟看報告時一樣、版本要比裝著的新
                                       → 舊資料夾搬到 packs/_removed/<name>-<版本>-<時間>（旁邊留一份舊的鎖）
                                       → 新的搬進 packs/ → 第 3 關：packs.lock 換成新的
                                       → （呼叫的人）環境要建／重建就跟全新安裝一樣 admin.build_env
    rollback(name, …)                  `python -m synox packs rollback <name>`：_removed 裡最近一份搬回、鎖改回舊的；
                                       舊版的環境對不上就提示重建（不自動建）

環境（runtime.python／node = auto）：報告裡的 env（env_change）＝新版要環境，而且舊版不用環境、或 requires.pip／
package-lock.json 跟舊版不同、或現在的 data/envs/<name>/ 對不上 → 確認升級後建（失敗不退回升級，doctor 會說）。

「改了什麼」：新增／移除的 command（cli 的 commands、mcp 的 tools_allow；python pack 的指令寫在程式裡，比不出來）；
effect 變寬（READ→WRITE→DANGER）、capabilities 新增、執行方式（kind、runtime、cli.argv／python／cwd／env、python.module）
或 auth 改動、access 變寬、多要密鑰環境變數、新加網頁面板、surfaces 多了 channel、data 變寬（none → user → shared）、
trust（擁有者這次選的，跟舊鎖不同；不在 pack.json）——這些 alert=True，畫面上用紅字標出來。

版本：新版本要是 semver（1.2.3、1.2.3-beta.1），而且要比裝著的大；一樣或比較小就拒絕，除非明確選「降級」（allow_downgrade）。

資料不在 pack 資料夾裡（data/<name>.json.enc、{user_data_dir}/<name>/），升級、退回都不會動到；
資料格式要不要升級是 pack 自己的事（docs/pack-format.md「升級」）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from typing import Dict, List, Optional, Tuple

from synox.packs import lock as pack_lock
from synox.packs.manifest import Manifest, ManifestError, read, secret_env_names

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                       r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$")
EFFECT_RANK = {"READ": 0, "WRITE": 1, "DANGER": 2}
ACCESS_RANK = {"owner": 0, "member": 1, "everyone": 2}
SIDECAR = ".lock.json"                    # _removed/<資料夾>.lock.json：搬走時那一份的鎖（退回時改回去）
UPGRADE, SAME, DOWNGRADE, INVALID = "upgrade", "same", "downgrade", "invalid"
_TS = r"(?P<ts>\d{8}-\d{6})(?:-(?P<n>\d+))?"


# ── 版本 ───────────────────────────────────────────────────────────────

def semver_key(version: str) -> Optional[tuple]:
    """semver 的排序鍵（正式版 > 同號的預覽版；預覽版逐段比，數字段 < 文字段）；不是 semver 回 None。"""
    m = SEMVER_RE.match(str(version or "").strip())
    if m is None:
        return None
    pre = m.group(4)
    if pre is None:
        tail: tuple = (1,)
    else:
        tail = (0,) + tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), tail)


def compare_versions(installed: str, new: str) -> Tuple[str, str]:
    """(upgrade｜same｜downgrade｜invalid, 給人看的一句話)。"""
    new_k, old_k = semver_key(new), semver_key(installed)
    if new_k is None:
        return INVALID, f"新版本 {new!r} 不是 semver（要像 1.2.3 或 1.2.3-beta.1），比不出新舊"
    if old_k is None:
        return INVALID, f"裝著的版本 {installed!r} 不是 semver，比不出新舊"
    if new_k > old_k:
        return UPGRADE, f"{installed} → {new}（升級）"
    if new_k == old_k:
        return SAME, f"版本一樣（都是 {new}）：要重裝同一版，得明確選「降級／重裝」"
    return DOWNGRADE, f"{new} 比裝著的 {installed} 舊：這是降級，得明確選「降級」才會換"


# ── 改了什麼 ───────────────────────────────────────────────────────────

def commands_of(m: Manifest) -> Optional[Dict[str, str]]:
    """{command 名字: effect}；python pack（指令寫在程式裡）回 None。"""
    if m.kind == "cli":
        return {c.get("name"): (c.get("effect") or "READ") for c in m.commands if isinstance(c, dict)}
    if m.kind == "mcp":
        return dict((m.mcp or {}).get("effects") or {})
    if m.kind == "connector":
        return {}
    return None


def _runtime_of(m: Manifest) -> Dict[str, object]:
    cli = m.cli or {}
    return {"kind": m.kind, "runtime": m.runtime or {}, "cli.argv": cli.get("argv") or [],
            "cli.python": cli.get("python") or "", "cli.cwd": cli.get("cwd") or "",
            "cli.env": cli.get("env") or {}, "python.module": (m.python or {}).get("module", "") if m.kind == "python"
            else "", "mcp.url": (m.mcp or {}).get("url", "")}


def _short(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = text or "（沒有）"
    return text if len(text) <= 120 else text[:117] + "…"


def diff_manifests(old: Manifest, new: Manifest) -> List[dict]:
    """裝著的 → 新的：[{"kind", "text", "alert"}…]；alert=True 的要醒目（紅字）。"""
    out: List[dict] = []

    def add(kind: str, text: str, alert: bool) -> None:
        out.append({"kind": kind, "text": text, "alert": alert})

    old_cmds, new_cmds = commands_of(old), commands_of(new)
    if old_cmds is None or new_cmds is None:
        if new.kind == "python" or old.kind == "python":
            add("commands", "python pack 的指令寫在程式裡，比不出新增／移除了哪些（看下面的檔案差異與掃描報告）", False)
    else:
        for name in sorted(set(new_cmds) - set(old_cmds)):
            eff = new_cmds[name]
            add("command_added", f"新增 command {name}（{eff}）", eff != "READ")
        for name in sorted(set(old_cmds) - set(new_cmds)):
            add("command_removed", f"移除 command {name}", False)
        for name in sorted(set(old_cmds) & set(new_cmds)):
            a, b = old_cmds[name], new_cmds[name]
            if a == b:
                continue
            wider = EFFECT_RANK.get(b, 2) > EFFECT_RANK.get(a, 2)
            add("effect", f"command {name} 的 effect {a} → {b}" + ("（變寬）" if wider else "（變窄）"), wider)
    for cap in new.capabilities:
        if cap not in old.capabilities:
            add("capability_added", f"新增能力 {cap}", True)
    for cap in old.capabilities:
        if cap not in new.capabilities:
            add("capability_removed", f"不再要能力 {cap}", False)
    a_rt, b_rt = _runtime_of(old), _runtime_of(new)
    for key in a_rt:
        if a_rt[key] != b_rt[key]:
            add("runtime", f"執行方式改了：{key} {_short(a_rt[key])} → {_short(b_rt[key])}", True)
    if (old.auth_info or {}) != (new.auth_info or {}):
        add("auth", f"帳號設定（auth）改了：{_short(old.auth_info or {})} → {_short(new.auth_info or {})}", True)
    added_env = [n for n in secret_env_names(new) if n not in secret_env_names(old)]
    if added_env:
        add("secrets", "多要這些密鑰環境變數：" + "、".join(added_env), True)
    if old.access != new.access:
        wider = ACCESS_RANK.get(new.access, 2) > ACCESS_RANK.get(old.access, 2)
        add("access", f"誰能用 {old.access} → {new.access}" + ("（變寬）" if wider else "（變窄）"), wider)
    if new.web.get("panel") and not old.web.get("panel"):
        add("panel", "新加了網頁面板（跟 Web UI 同源）", True)
    if old.storage != new.storage:
        add("storage", f"資料存法 {old.storage} → {new.storage}", new.storage == "plain")
    out += scope_changes(old, new)
    return out


# ── 權限宣告與信任（PERM-2） ───────────────────────────────────────────

DATA_RANK = {"none": 0, "user": 1, "shared": 2}
SURFACE_RANK = {"dm": 0, "channel": 1}


def scope_changes(old: Manifest, new: Manifest) -> List[dict]:
    """surfaces／data 的變化：變寬（多了 channel；none → user → shared）alert=True。"""
    out: List[dict] = []
    a, b = list(getattr(old, "surfaces", ["dm"])), list(getattr(new, "surfaces", ["dm"]))
    if a != b:
        wider = max(SURFACE_RANK.get(s, 1) for s in b) > max(SURFACE_RANK.get(s, 1) for s in a)
        out.append({"kind": "surfaces", "text": f"在哪裡用 {'＋'.join(a)} → {'＋'.join(b)}"
                    + ("（變寬：可以在頻道裡用了）" if wider else "（變窄）"), "alert": wider})
    da, db = getattr(old, "data", "none"), getattr(new, "data", "none")
    if da != db:
        wider = DATA_RANK.get(db, 2) > DATA_RANK.get(da, 2)
        out.append({"kind": "data", "text": f"資料歸屬 data {da} → {db}" + ("（變寬）" if wider else "（變窄）"),
                    "alert": wider})
    return out


def trust_change(installed: Optional[str], chosen: Optional[str]) -> Optional[dict]:
    """擁有者這次選的 trust 跟裝著那一份的鎖不一樣 → 一筆 alert（不管哪個方向都標紅）；沒選或一樣回 None。"""
    if chosen is None:
        return None
    before = installed or "（未鎖定）"
    if before == chosen:
        return None
    return {"kind": "trust", "text": f"信任 trust {before} → {chosen}", "alert": True}


def env_change(old: Manifest, new: Manifest, data_dir: Optional[str]) -> dict:
    """升級時環境（runtime.python／node = auto，packs/envs.py）要不要建／重建——跟安裝報告的「要建環境」同一份清單
    （EnvPlan.to_dict），另外加：
      needed   確認升級之後要建：新版要環境，而且（舊版不用環境｜requires.pip／package-lock.json 跟舊版不同｜
               現在的 data/envs/<name>/ 沒建好或對不上新版）
      rebuild  data/envs/<name>/ 已經有東西（重建）；reason 一句人話；keep＝新版要環境、但沿用現在的（不用重建）
    只看、不跑。"""
    from synox.packs import envs
    out = envs.builder(data_dir).plan(new).to_dict()
    needed, reason = False, ""
    if envs.needs_env(new):
        state = envs.read_state(data_dir, new.name)
        if not envs.needs_env(old):
            needed, reason = True, "舊版不用建環境，新版要"
        elif envs.spec_of(old) != envs.spec_of(new):
            needed, reason = True, "套件清單（requires.pip／package-lock.json）跟舊版不同"
        elif state.get("state") != envs.OK or state.get("spec") != envs.spec_of(new):
            needed, reason = True, "現在的環境沒建好或跟 pack.json 對不上"
        rebuild = needed and bool(state)
    else:
        rebuild = False
    out.update(needed=needed, rebuild=rebuild, reason=reason, keep=envs.needs_env(new) and not needed)
    if not needed:
        out["text"] = ""
    return out


def report_for(old: Manifest, old_folder: str, new: Manifest, new_hashes: Dict[str, str],
               data_dir: str, trust: Optional[str] = None) -> dict:
    """trust：擁有者這次選的（None＝還沒選：報告只給 installed_trust，畫面自己比）。"""
    status, message = compare_versions(old.version, new.version)
    try:
        old_hashes = pack_lock.hash_files(old_folder)
    except OSError:
        old_hashes = {}
    lock_state, _changes = pack_lock.verify(data_dir, old.name, old_folder)
    changes = diff_manifests(old, new)
    installed_trust = pack_lock.trust_of(data_dir, old.name)
    moved = trust_change(installed_trust, trust)
    if moved:
        changes.append(moved)
    return {"name": new.name, "installed_version": old.version, "new_version": new.version,
            "version_status": status, "version_ok": status == UPGRADE, "version_message": message, "changes": changes,
            "can_force": status != UPGRADE and semver_key(new.version) is not None,   # 可以明確選「降級／重裝」
            "alerts": sum(1 for c in changes if c["alert"]), "files": pack_lock.diff(old_hashes, new_hashes)[:50],
            "installed_lock": lock_state, "env": env_change(old, new, data_dir),
            "installed_trust": installed_trust, "trust": trust or installed_trust or pack_lock.DEFAULT_TRUST}


def installed_manifest(packs_dir: str, name: str) -> Optional[Tuple[Manifest, str]]:
    """packs/<name> 裝著的那一份 (manifest, 資料夾)；沒裝回 None。pack.json 壞了也當作有裝（版本 ?）。"""
    folder = os.path.join(packs_dir, name)
    if not os.path.exists(folder):
        return None
    try:
        return read(folder), folder
    except ManifestError:
        return Manifest(name=name, title=name, summary="", version="?", kind="?", folder=folder), folder


def staged_upgrade(token: str, data_dir: str, packs_dir: str, trust: Optional[str] = None) -> Optional[dict]:
    """暫存中的那一份如果跟已經裝的同名：回升級報告；沒裝過回 None。trust＝這次要選的（跟舊鎖不同就標紅）。"""
    from synox.packs import admin
    root = admin._staged_root(token, data_dir)
    folder = os.path.join(root, "pack")
    try:
        new = read(folder, strict=True)
    except ManifestError as e:
        raise admin.PackAdminError(f"pack.json 不合（第 1 關）：{e}")
    found = installed_manifest(packs_dir, new.name)
    if found is None:
        return None
    old, old_folder = found
    return report_for(old, old_folder, new, pack_lock.hash_files(folder), data_dir, trust=trust)


def format_upgrade(upg: dict) -> str:
    """升級報告 → 終端機的字；要醒目的前面標 🔴。"""
    lines = [f"🔁 這是升級：裝著的是 {upg.get('installed_version')}，新的是 {upg.get('new_version')}"]
    lines.append(("  ✅ " if upg.get("version_ok") else "  ⛔ ") + str(upg.get("version_message")))
    if upg.get("installed_lock") == pack_lock.TAMPERED:
        lines.append("  ⚠️ 裝著的那一份已經被改過（跟 packs.lock 不符）")
    lines.append("  改了什麼：" if upg.get("changes") else "  改了什麼：宣告沒有變")
    for c in upg.get("changes") or []:
        lines.append(("  🔴 " if c.get("alert") else "  · ") + c["text"])
    files = upg.get("files") or []
    if files:
        lines.append("  檔案：" + "、".join(files[:20]) + ("…" if len(files) > 20 else ""))
    if upg.get("trust"):
        lines.append(f"  🔑 信任：裝著的是 {upg.get('installed_trust') or '（未鎖定）'}，升級後 {upg['trust']}"
                     "（終端機 --trust 改）")
    lines += format_env(upg.get("env") or {}, upg.get("name") or "")
    lines.append("  資料（data/、使用者資料夾）不會動；資料格式要不要轉換由 pack 自己負責。")
    return "\n".join(lines)


def format_env(env: dict, name: str = "") -> List[str]:
    """升級報告的環境那一段（跟安裝報告 admin.format_summary 的「🧱 要建環境」同一個樣子）。"""
    where = f"data/envs/{name}/" if name else "data/envs/<pack>/"
    if env.get("keep"):
        return [f"  🧱 環境：套件清單跟舊版一樣，沿用 {where}（不重建）"]
    if not env.get("needed"):
        return []
    head = "要重建環境" if env.get("rebuild") else "要建環境"
    lines = [f"  🧱 {head}（按確認升級之後才建）：" + (env.get("reason") or "")]
    lines += [f"    · {line}" for line in env.get("lines") or []]
    lines.append(f"    （要網路，最多 10 分鐘；建在 {where}；失敗的話 pack 照樣升級好，doctor 會標「環境沒建好」）")
    lines += [f"    ⚠️ {p}" for p in env.get("problems") or []]
    return lines


# ── 搬到 _removed、退回 ────────────────────────────────────────────────

def removed_root(packs_dir: str) -> str:
    from synox.packs.admin import REMOVED
    return os.path.join(packs_dir, REMOVED)


def archive(folder: str, name: str, version: str, packs_dir: str, data_dir: Optional[str],
            now=None, reason: str = "upgrade") -> str:
    """packs/<name> → _removed/<name>-<版本>-<時間>；旁邊寫 <那個資料夾>.lock.json（搬走時的鎖，可能是 null）。
    不改 packs.lock（呼叫的人決定）。回搬到哪。"""
    dest_root = removed_root(packs_dir)
    os.makedirs(dest_root, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    base = f"{name}-{version}-{stamp}" if semver_key(version) is not None else f"{name}-{stamp}"
    dest, n = os.path.join(dest_root, base), 1
    while os.path.exists(dest) or os.path.exists(dest + SIDECAR):
        n += 1
        dest = os.path.join(dest_root, f"{base}-{n}")
    shutil.move(folder, dest)
    entry = pack_lock.entry(data_dir, name) if data_dir else None
    with open(dest + SIDECAR, "w", encoding="utf-8") as f:
        json.dump({"name": name, "version": version, "reason": reason, "lock": entry,
                   "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))}, f, ensure_ascii=False)
    return dest


def _sidecar(path: str) -> dict:
    try:
        with open(path + SIDECAR, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def backups(name: str, packs_dir: str) -> List[dict]:
    """_removed 裡這個 pack 的舊版本，新的在前：[{"path", "version", "stamp", "reason"}…]。"""
    root = removed_root(packs_dir)
    if not os.path.isdir(root):
        return []
    pat = re.compile(rf"^{re.escape(name)}-(?:(?P<ver>\d+\.\d+\.\d+[0-9A-Za-z.+-]*)-)?{_TS}$")
    out = []
    for entry in os.listdir(root):
        m = pat.match(entry)
        path = os.path.join(root, entry)
        if m is None or not os.path.isfile(os.path.join(path, "pack.json")):
            continue
        side = _sidecar(path)
        out.append({"path": path, "version": m.group("ver") or side.get("version") or "",
                    "stamp": m.group("ts"), "n": int(m.group("n") or 1), "reason": side.get("reason", "remove")})
    out.sort(key=lambda b: (b["stamp"], b["n"]), reverse=True)
    return out


def _verified_staged(token: str, data_dir: str):
    """跟 admin.install_staged 一樣的再檢查：再跑 1、2 關、檔案跟看報告時一樣。回 (root, folder, m, report, hashes)。"""
    from synox.packs import admin
    root = admin._staged_root(token, data_dir)
    folder = os.path.join(root, "pack")
    m, report, hashes, problems = admin.run_gates(folder)
    if problems:
        raise admin.GateRefused("拒裝（安全檢查沒過）：" + "；".join(problems[:12]),
                                admin.summary_of(m, report, hashes, problems))
    try:
        with open(os.path.join(root, admin.STAGED_META), "r", encoding="utf-8") as f:
            reviewed = json.load(f).get("hashes") or {}
    except (OSError, ValueError):
        raise admin.PackAdminError("找不到這次上傳的檢查結果（重新上傳一次）")
    if reviewed != hashes:
        raise admin.PackAdminError("暫存的檔案在你看報告之後被改過了，不裝（重新上傳一次）："
                                   + "、".join(pack_lock.diff(reviewed, hashes)[:10]))
    return root, folder, m, report, hashes


def upgrade_staged(token: str, data_dir: str, packs_dir: str, approved_by=None, via: str = "web",
                   allow_downgrade: bool = False, now=None, trust: Optional[str] = None) -> dict:
    """按了「確認升級」：再檢查 → 版本要比較新（或 allow_downgrade）→ 舊的搬到 _removed → 新的搬進來 → 鎖換新。
    trust 沒給＝沿用舊鎖的（舊的沒鎖＝third-party）。
    回 {"name", "from", "to", "backup", "report", "env"}；env＝report["env"]（needed＝要接著建環境：
    呼叫的人照全新安裝一樣叫 admin.build_env；建失敗不退回升級）。沒裝過同名的丟錯（用一般安裝）。"""
    from synox.packs import admin
    if trust is not None:
        trust = admin._trust(trust)
    root, folder, m, report, hashes = _verified_staged(token, data_dir)
    found = installed_manifest(packs_dir, m.name)
    if found is None:
        raise admin.PackAdminError(f"還沒裝過 {m.name}，不是升級（用一般的「確認安裝」）")
    old, target = found
    upg = report_for(old, target, m, hashes, data_dir, trust=trust)
    trust = upg["trust"]
    if not upg["version_ok"] and not (allow_downgrade and upg["can_force"]):
        hint = "（真的要換，明確選「降級／重裝」）" if upg["can_force"] else ""
        raise admin.PackAdminError(f"不升級：{upg['version_message']}{hint}")
    backup = archive(target, m.name, old.version, packs_dir, data_dir, now=now, reason="upgrade")
    try:
        shutil.move(folder, target)
    except Exception:
        if os.path.exists(target):
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(backup, target)
        try:
            os.remove(backup + SIDECAR)
        except OSError:
            pass
        raise
    shutil.rmtree(root, ignore_errors=True)
    pack_lock.approve(data_dir, m, report, approved_by, via=via, hashes=hashes, folder=target, trust=trust)
    logging.info("[PACKS] upgraded %s %s → %s (approved by %s via %s; old one in %s)",
                 m.name, old.version, m.version, approved_by, via, backup)
    return {"name": m.name, "from": old.version, "to": m.version, "backup": backup, "report": upg,
            "env": upg["env"]}


def rollback(name: str, packs_dir: str, data_dir: str, now=None) -> dict:
    """_removed 裡這個 pack 最近一份（升級或移除時搬走的；退回時搬走的那份跳過）搬回 packs/<name>、鎖改回當時的。
    現在裝著的那份先搬到 _removed（reason=rollback）。回 {"name", "version", "restored_from", "archived", "lock", "env"}；
    lock：restored（鎖改回了）｜unlocked（當時就沒鎖）｜mismatch（檔案跟當時的鎖不符：沒鎖，要重新核准）；
    env：舊版要環境、data/envs/<name>/ 卻跟它對不上（例如升級時重建成新版的套件）→ 一句人話（含重建指令）；
    沒問題或不用環境 → None。不自動重建（退回通常是新版出事，先讓人決定）。"""
    from synox.packs import admin
    if not name or not re.match(r"^[a-z][a-z0-9_-]{0,31}$", name):
        raise admin.PackAdminError("pack 名字不對")
    candidates = [b for b in backups(name, packs_dir) if b["reason"] != "rollback"]
    if not candidates:
        raise admin.PackAdminError(f"packs/_removed/ 裡沒有 {name} 的舊版可以退回")
    pick = candidates[0]
    try:
        restored = read(pick["path"])
    except ManifestError as e:
        raise admin.PackAdminError(f"{os.path.basename(pick['path'])} 的 pack.json 讀不了：{e}")
    if restored.name != name:
        raise admin.PackAdminError(f"{os.path.basename(pick['path'])} 裡的 pack 叫 {restored.name}，不是 {name}")
    target = os.path.join(packs_dir, name)
    archived = None
    current = installed_manifest(packs_dir, name)
    if current is not None:
        archived = archive(target, name, current[0].version, packs_dir, data_dir, now=now, reason="rollback")
    try:
        shutil.move(pick["path"], target)
    except Exception:
        if archived:
            shutil.move(archived, target)
            try:
                os.remove(archived + SIDECAR)
            except OSError:
                pass
        raise
    side = _sidecar(pick["path"])
    try:
        os.remove(pick["path"] + SIDECAR)
    except OSError:
        pass
    old_lock = side.get("lock") if isinstance(side.get("lock"), dict) else None
    state = "unlocked"
    if old_lock is not None:
        actual = pack_lock.hash_files(target)
        if actual == (old_lock.get("files") or {}):
            pack_lock.restore(data_dir, name, {**old_lock, "restored_at":
                                               time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))})
            state = "restored"
        else:
            pack_lock.remove(data_dir, name)
            state = "mismatch"
    else:
        pack_lock.remove(data_dir, name)
    env = None
    try:
        from synox.packs import envs
        back = read(target)
        if envs.needs_env(back):                   # 舊版要環境：data/envs/<name>/ 可能是新版建的 → 只提示，不自動建
            env = envs.env_problem(back, data_dir)
    except ManifestError:
        pass
    logging.info("[PACKS] rolled back %s to %s (lock %s%s)", name, restored.version, state,
                 "; env needs rebuild" if env else "")
    return {"name": name, "version": restored.version, "restored_from": pick["path"], "archived": archived,
            "lock": state, "env": env}
