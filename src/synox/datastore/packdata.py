"""
工具（pack）的資料版本與 data-adapter 契約（ADR 0044 §工具契約；作者看 docs/data-migrations.md）。

pack.json 選填欄位（沒有持久化資料的工具不用寫）：

    "data_schema": {"version": 3, "files": ["store", "store:history", "dir"]}

    version   這一版工具寫出的資料版本（整數 ≥ 1）；改了資料格式就 +1，並補上一個遷移步驟
    files     這個工具有哪些資料要跟著升級：
                "store"         pack.store 的主檔（data/<name>.json(.enc)；伺服器版每人一份 data/users/<id>/…）
                "store:<key>"   pack.store 的其他檔（pack.store.save(x, key="<key>")）
                "dir"           工具自己的資料夾（data/packs/<name>/、data/<name>/、data/users/<id>/<name>/，有的才算）

（欄位名是 data_schema 不是 data：pack.json 的 data 早就是「資料屬於誰」none｜user｜shared，PERM-2。）

遷移步驟：
    kind=python   工具資料夾裡的 migrations.py（或 migrations/ 資料夾裡的 *.py），頂層函式：
                    def migrate_1_to_2(data): ... return 新的 data        store 的檔：拿到解開的 JSON、回新的
                    def migrate_1_to_2_dir(path): ...                     dir：就地改這個資料夾
                  只能用標準函式庫（不能 import 工具自己的模組）；SYNOX 照 packs.lock 對過 sha256 才編譯執行。
    kind=cli      `<cli.argv> migrate --from 1 --to 2 --data <資料夾>`（每一步叫一次；走跟一般指令一樣的沙盒、環境變數規則）；
                  結束碼 0＝成功（最後一行 JSON 有 "ok": false 也算失敗）。只支援 "dir"。
    其他 kind     不支援（mcp、connector、theme 宣告了＝安裝時拒）。

版本記在 data/pack_data.json（核心的登記表，自己也有版本，core.PACK_DATA）：{"packs": {"<name>": {"version": N, …}}}。
沒有紀錄：有資料＝0 版（宣告 data_schema 以前就有的資料）；沒有資料＝直接記成目前版本（新裝的）。

什麼時候升：每次載入工具（loader.load_all）在工具的程式第一次執行**之前**——升級工具後重新載入、SYNOX 重開都一樣。
失敗＝全部從備份還原、工具不載入、狀態寫原因；資料比工具新（退回舊版之後）＝不載入、不動資料。
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
import subprocess
import time
import types
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from synox.datastore import core
from synox.datastore.migrate import (CURRENT, FAILED, MISSING, PLANNED, TOO_NEW, UPGRADED, JsonCodec, Outcome, VaultCodec,
                                gap_text, upgrade_folder)
from synox.datastore.versioned import (KEEP_BACKUPS, DataError, FileLock, GapError, StepError, TooNewError,
                                  atomic_write_bytes, make_backup, restore_backup, too_new_text)

KEY = "data_schema"
REGISTRY = "pack_data.json"
KINDS = {"python": ("store", "dir"), "cli": ("dir",)}
STORE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
STEP_RE = re.compile(r"^migrate_(\d+)_to_(\d+)(_dir)?$")
MAX_VERSION = 10_000
CLI_TIMEOUT = 600
USERS_DIR = "users"
# data/ 底下核心自己的資料夾：工具剛好同名時，data/<名字>/ 不當成工具的資料夾
RESERVED_DIRS = frozenset({"packs", "users", "envs", "prefs", "tour", "job_logs", "web_uploads", "web_chats",
                           "claude_workspace", "_migration_backups"})


# ── pack.json 的 data_schema ──────────────────────────────────────────

def parse(raw: dict, kind: str) -> Tuple[dict, List[str]]:
    """pack.json → ({"version", "files"} 或 {}（沒寫）, 問題清單)。安裝、載入都一樣嚴格：
    寫壞了還照樣跑，工具新版可能就用舊格式讀新資料（或反過來），所以寧可不載入。"""
    if KEY not in raw:
        return {}, []
    value = raw.get(KEY)
    if not isinstance(value, dict):
        return {}, [f'{KEY} 要是物件，例如 {{"version": 1, "files": ["store"]}}']
    problems = []
    unknown = sorted(str(k) for k in value if k not in ("version", "files"))
    if unknown:
        problems.append(f"{KEY} 不認得 {'、'.join(unknown)}（只收 version、files）")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= MAX_VERSION:
        problems.append(f"{KEY}.version 要是 1 以上的整數（這一版工具寫出的資料版本）")
    allowed = KINDS.get(kind)
    if allowed is None:
        problems.append(f"{KEY} 只支援 kind=python 與 kind=cli（{kind} 的資料 SYNOX 升級不了；見 docs/data-migrations.md）")
        allowed = ()
    files = value.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) for f in files):
        problems.append(f'{KEY}.files 要是非空的字串清單（"store"、"store:<key>"、"dir"）')
        files = []
    out_files: List[str] = []
    for f in files:
        base = f.split(":", 1)[0]
        if base not in ("store", "dir") or (f.startswith("store:") and not STORE_KEY_RE.match(f[6:])) or f == "dir:":
            problems.append(f"{KEY}.files 的 {f!r} 看不懂（只能是 store、store:<小寫英數字>、dir）")
        elif base not in allowed:
            problems.append(f"{KEY}.files 的 {f!r}：kind={kind} 只能用 {'、'.join(allowed)}")
        elif f not in out_files:
            out_files.append(f)
    if problems:
        return {}, problems
    return {"version": version, "files": out_files}, []


def needs(spec: dict) -> Tuple[bool, bool]:
    """(有 store 的檔, 有 dir)。"""
    files = spec.get("files") or []
    return any(f.split(":", 1)[0] == "store" for f in files), "dir" in files


# ── python 工具的 migrations 模組 ─────────────────────────────────────

def migration_files(folder: str) -> List[str]:
    """工具資料夾裡的遷移程式（相對路徑，/ 分隔）：migrations.py，或 migrations/ 裡的 *.py（照名字排）。"""
    single = os.path.join(folder, "migrations.py")
    if os.path.isfile(single):
        return ["migrations.py"]
    pkg = os.path.join(folder, "migrations")
    if os.path.isdir(pkg):
        return [f"migrations/{n}" for n in sorted(os.listdir(pkg))
                if n.endswith(".py") and os.path.isfile(os.path.join(pkg, n))]
    return []


def declared_steps(folder: str) -> Tuple[Dict[int, str], Dict[int, str], List[str]]:
    """**不執行**，只用 AST 看頂層函式名（安裝時第 1 關、synox-sdk check 用）：
    ({from: 檔名} store 的步驟, {from: 檔名} dir 的步驟, 問題)。migrate_1_to_3 這種跨兩版的＝問題。"""
    store: Dict[int, str] = {}
    dirs: Dict[int, str] = {}
    problems: List[str] = []
    for rel in migration_files(folder):
        try:
            with open(os.path.join(folder, *rel.split("/")), "rb") as f:
                tree = ast.parse(f.read(), filename=rel)
        except (OSError, SyntaxError, ValueError) as e:
            problems.append(f"{rel} 讀不了或有語法錯誤（{e}）")
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            m = STEP_RE.match(node.name)
            if m is None:
                continue
            frm, to = int(m.group(1)), int(m.group(2))
            if to != frm + 1:
                problems.append(f"{rel} 的 {node.name}：一個步驟只能升一版（要寫成 migrate_{frm}_to_{frm + 1}）")
                continue
            target = dirs if m.group(3) else store
            if frm in target:
                problems.append(f"{node.name} 寫了兩次（{target[frm]}、{rel}）")
                continue
            target[frm] = rel
    return store, dirs, problems


def step_problems(spec: dict, folder: str, kind: str) -> Tuple[List[str], List[str]]:
    """步驟序列檢查（不執行程式）：(會擋安裝的問題, 只是提醒)。
    擋：有洞（最低的那一步到 version 之間缺任何一步）、超過 version 的步驟、version ≥ 2 卻一個步驟都沒有、跨版的函式名。
    提醒：最低的步驟不是 0→1（宣告 data_schema 以前就有資料的使用者升不上來）。cli 工具只能提醒（步驟在程式裡，看不到）。"""
    if not spec:
        return [], []
    version = spec["version"]
    if kind == "cli":
        return [], [f"cli 工具的遷移步驟在程式裡（`migrate --from N --to N+1 --data <資料夾>`），"
                    f"這裡看不到；請自己用舊版資料測過 0→…→{version} 每一步"]
    has_store, has_dir = needs(spec)
    store, dirs, problems = declared_steps(folder)
    notes: List[str] = []
    for label, wanted, steps, suffix in (("store", has_store, store, ""), ("dir", has_dir, dirs, "_dir")):
        if not wanted:
            if steps:
                notes.append(f"有 migrate_*{suffix} 函式，但 data_schema.files 沒有 {label}：用不到")
            continue
        beyond = sorted(v for v in steps if v >= version)
        if beyond:
            problems.append("、".join(f"migrate_{v}_to_{v + 1}{suffix}" for v in beyond)
                            + f" 超過 data_schema.version（{version}）")
        below = sorted(v for v in steps if v < version)
        if not below:
            if version >= 2:
                problems.append(f"data_schema.version 是 {version}，卻沒有任何 migrate_N_to_N+1{suffix} 步驟"
                                "（舊資料升不上來）")
            continue
        holes = [v for v in range(below[0], version) if v not in steps]
        if holes:
            problems.append("遷移步驟有洞：少了 " + "、".join(f"migrate_{v}_to_{v + 1}{suffix}" for v in holes))
        if below[0] > 0:
            notes.append(f"最低的步驟是 migrate_{below[0]}_to_{below[0] + 1}{suffix}：資料版本低於 {below[0]} 的使用者"
                         "（包括宣告 data_schema 以前就有資料的＝0 版）升不上來，工具會停用並說明")
    return problems, notes


def load_steps(folder: str, locked: Optional[Dict[str, str]] = None) -> Tuple[Dict[int, Callable], Dict[int, Callable]]:
    """編譯並執行 migrations 模組，回 ({from: fn} store, {from: fn} dir)。
    跟 pkgload 一樣只讀 .py 原始碼；locked（packs.lock 的 {相對路徑: sha256}）有給就逐檔對過才執行，不符＝DataError。"""
    store: Dict[int, Callable] = {}
    dirs: Dict[int, Callable] = {}
    for rel in migration_files(folder):
        path = os.path.join(folder, *rel.split("/"))
        with open(path, "rb") as f:
            source = f.read()
        if locked:
            want = locked.get(rel)
            if want is None or hashlib.sha256(source).hexdigest() != want:
                raise DataError(f"{rel} 跟核准時不一樣（或核准時沒有這個檔），不執行它的資料升級。")
        module = types.ModuleType(f"synox_pack_migrations_{abs(hash(path))}")
        module.__file__ = path
        exec(compile(source, path, "exec"), module.__dict__)
        for name, fn in vars(module).items():
            m = STEP_RE.match(name)
            if m is None or not callable(fn) or int(m.group(2)) != int(m.group(1)) + 1:
                continue
            (dirs if m.group(3) else store)[int(m.group(1))] = fn
    return store, dirs


# ── 登記表 data/pack_data.json ────────────────────────────────────────

def registry_path(data_dir: str) -> str:
    return os.path.join(data_dir, REGISTRY)


def _read_registry(data_dir: str) -> dict:
    import json
    path = registry_path(data_dir)
    if not os.path.exists(path):
        return {"packs": {}}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise DataError(f"{REGISTRY} 讀不了（{e}）：工具資料的版本不確定，先不升級也不載入要升級的工具。")
    if not isinstance(data, dict):
        raise DataError(f"{REGISTRY} 最外層不是物件。")
    return data


def recorded(data_dir: str, name: str) -> Optional[int]:
    """登記表記的版本；沒有紀錄回 None。"""
    rec = (_read_registry(data_dir).get("packs") or {}).get(name)
    if isinstance(rec, dict) and isinstance(rec.get("version"), int) and not isinstance(rec.get("version"), bool):
        return rec["version"]
    return None


def record(data_dir: str, name: str, version: int, pack_version: str = "", now: Optional[float] = None) -> None:
    """寫一筆（登記表一律寫目前的格式；登記表本身比較新＝TooNewError、不寫）。"""
    import json
    with FileLock(registry_path(data_dir)):
        data = core.PACK_DATA.upgrade_data(_read_registry(data_dir), REGISTRY)
        packs = data.setdefault("packs", {})
        packs[name] = {"version": int(version), "pack_version": str(pack_version or ""),
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))}
        atomic_write_bytes(registry_path(data_dir),
                           (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# ── 這個工具的資料在哪 ─────────────────────────────────────────────────

@dataclass
class Location:
    path: str
    kind: str                     # store｜dir
    user: Optional[int] = None    # 伺服器版：哪個人的
    vault: object = field(default=None, repr=False)


def _user_ids(data_dir: str) -> List[int]:
    root = os.path.join(data_dir, USERS_DIR)
    if not os.path.isdir(root):
        return []
    return sorted(int(n) for n in os.listdir(root) if n.isdigit() and os.path.isdir(os.path.join(root, n)))


def locations(m, data_dir: str, vault=None) -> List[Location]:
    """data_schema.files 說的資料，磁碟上**存在**的那些（個人版、伺服器版的位置都看：從一種模式換到另一種的舊資料也要升）。"""
    spec = getattr(m, "data_schema", None) or {}
    out: List[Location] = []
    use_vault = getattr(m, "storage", "plain") == "vault"
    suffix = ".json.enc" if use_vault else ".json"
    users = _user_ids(data_dir)
    for f in spec.get("files") or []:
        if f.split(":", 1)[0] == "store":
            stem = m.name if f == "store" else f"{m.name}.{f[6:]}"
            candidates = [(os.path.join(data_dir, stem + suffix), None, vault)]
            candidates += [(os.path.join(data_dir, USERS_DIR, str(u), stem + suffix), u,
                            vault.for_user(u) if (vault is not None and use_vault) else None) for u in users]
            for path, user, box in candidates:
                if os.path.isfile(path):
                    out.append(Location(path, "store", user, box if use_vault else None))
        elif f == "dir":
            folders = [(os.path.join(data_dir, "packs", m.name), None)]
            if m.name not in RESERVED_DIRS:              # data/<名字>/ 跟核心自己的資料夾同名時不算（不去動核心的）
                folders.append((os.path.join(data_dir, m.name), None))
            folders += [(os.path.join(data_dir, USERS_DIR, str(u), m.name), u) for u in users]
            for path, user in folders:
                if os.path.isdir(path):
                    out.append(Location(path, "dir", user))
    return out


# ── cli 工具：<cli.argv> migrate --from N --to N+1 --data <資料夾> ─────────

def cli_runner(m, config, *, run=subprocess.run, timeout: float = CLI_TIMEOUT) -> Callable[[int, str, Optional[int]], None]:
    """回 step(from, folder, user)：照 loader 叫一般指令的同一套組 argv（{python} 代換、沙盒包一層、容器路徑、
    clean_env＋cli.env＋context_env）。結束碼不是 0、或最後一行 JSON 是 "ok": false＝StepError（訊息帶工具說的原因）。"""
    from types import SimpleNamespace

    from isdtelekit.jobs.cli import clean_env, last_json

    from synox import sandbox
    from synox.packs import loader
    from synox.packs.manifest import secret_env_names

    def step(frm: int, folder: str, user: Optional[int] = None) -> None:
        who = SimpleNamespace(tg_id=user) if user is not None else None
        ph = loader.placeholders(m, config, who)
        box = sandbox.box_for(config, m)
        view = sandbox.view_for(box, ph)
        data_arg = _view_path(folder, ph, view)
        cwd = os.path.normpath(os.path.join(m.folder, loader.substitute(m.cli.get("cwd") or ".", ph)))
        env = loader.cli_env(m, view)
        env.update(loader.context_env(m, config, view))
        env["SYNOX_MIGRATE"] = "1"
        keep = list(secret_env_names(m))
        grants = sandbox.grants_for(m, config, ph, pass_env=keep)
        argv, env = box.wrap(loader.cli_prefix(m, view) + ["migrate", "--from", str(frm), "--to", str(frm + 1),
                                                            "--data", data_arg], env, cwd, grants)
        try:
            done = run(argv, cwd=cwd, env=clean_env(env, keep=keep), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            raise StepError(f"{m.title} 的資料從版本 {frm} 升到 {frm + 1} 超過 {int(timeout)} 秒沒有做完。")
        except OSError as e:
            raise StepError(f"{m.title} 的資料升級程式叫不起來（{e}）。")
        reply = last_json(done.stdout or "") or {}
        if done.returncode != 0 or reply.get("ok") is False:
            why = str(reply.get("error") or reply.get("message") or (done.stderr or "").strip()[-300:] or
                      f"結束碼 {done.returncode}")
            raise StepError(f"{m.title} 的資料從版本 {frm} 升到 {frm + 1} 失敗：{why}")
    return step


def _view_path(folder: str, ph: Dict[str, str], view: Dict[str, str]) -> str:
    """本機的資料夾 → 子程序看得到的路徑（容器後端：data/… 換成容器裡的路徑；其他後端原樣）。"""
    for key in ("user_data_dir", "data_dir"):
        base, mapped = ph.get(key), view.get(key)
        if not base or not mapped or base == mapped:
            continue
        rel = os.path.relpath(folder, base)
        if not rel.startswith(".."):
            return mapped.rstrip("/") + "/" + rel.replace("\\", "/")
    return folder


# ── 升級一個工具的資料 ─────────────────────────────────────────────────

def _outcome(m, action: str, *, before=None, after=None, steps=(), backup="", message="") -> Outcome:
    spec = getattr(m, "data_schema", None) or {}
    return Outcome(m.name, f"{m.title} 的資料", action, before=before, after=after, current=spec.get("version"),
                   steps=list(steps), backup=backup, message=message)


def ensure(m, config, vault=None, *, dry_run: bool = False, runner=None, locked: Optional[Dict[str, str]] = None,
           keep: int = KEEP_BACKUPS, now: Optional[float] = None) -> Outcome:
    """載入工具之前：把這個工具的資料升到 data_schema.version。回 Outcome（ok=False 的＝不要載入這個工具，message 是原因）。
    沒宣告 data_schema 的工具：MISSING（什麼都不做、不記）。
    runner：cli 工具的步驟（測試給假的；沒給＝cli_runner）。locked：packs.lock 的檔案雜湊（python 的 migrations 要對）。"""
    spec = getattr(m, "data_schema", None) or {}
    if not spec:
        return _outcome(m, MISSING)
    data_dir = config.data_dir
    target = spec["version"]
    try:
        if dry_run:                                    # 只看：不拿鎖、不寫任何東西
            return _ensure_locked(m, config, vault, spec, target, data_dir, True, runner, locked, keep, now)
        with FileLock(os.path.join(data_dir, f"pack_data.{m.name}")):
            return _ensure_locked(m, config, vault, spec, target, data_dir, False, runner, locked, keep, now)
    except TooNewError as e:
        return _outcome(m, TOO_NEW, message=str(e))
    except DataError as e:
        return _outcome(m, FAILED, message=str(e))


def _ensure_locked(m, config, vault, spec, target, data_dir, dry_run, runner, locked, keep, now) -> Outcome:
    before = recorded(data_dir, m.name)
    locs = locations(m, data_dir, vault)
    if before is None:
        if not locs:                                  # 新裝的、還沒有資料：直接記成目前版本
            if not dry_run:
                record(data_dir, m.name, target, m.version, now)
            return _outcome(m, CURRENT, before=target, after=target)
        before = 0                                    # 宣告 data_schema 以前就有的資料
    if before > target:
        raise TooNewError(too_new_text(f"{m.title} 的資料", before, target))
    if before == target:
        return _outcome(m, CURRENT, before=before, after=before)
    plan = list(range(before, target))
    steps_text = [f"{v}→{v + 1}" for v in plan]
    has_store = any(loc.kind == "store" for loc in locs)
    has_dir = any(loc.kind == "dir" for loc in locs)
    store_steps: Dict[int, Callable] = {}
    dir_steps: Dict[int, Callable] = {}
    if m.kind == "python":
        if dry_run:
            store_found, dir_found, _bad = declared_steps(m.folder)
            store_steps = {k: None for k in store_found}
            dir_steps = {k: None for k in dir_found}
        else:
            store_steps, dir_steps = load_steps(m.folder, locked)
        for wanted, steps, suffix in ((has_store, store_steps, ""), (has_dir, dir_steps, "_dir")):
            missing = [v for v in plan if v not in steps] if wanted else []
            if missing:
                raise GapError(gap_text(f"{m.title} 的資料", before, target, missing)
                               .replace("升級步驟", f"升級步驟（migrate_N_to_N+1{suffix}）"))
    if dry_run:
        return _outcome(m, PLANNED, before=before, steps=steps_text)
    if m.kind == "cli" and runner is None:
        runner = cli_runner(m, config)
    done: List[Tuple[str, str]] = []                  # (原位置, 備份)：任何一步失敗，全部換回來
    try:
        for loc in locs:
            if loc.kind == "store":
                done.append((loc.path, _upgrade_store(m, loc, before, plan, store_steps, keep, now)))
            else:
                if m.kind == "python":
                    def run_step(v, folder, _steps=dir_steps):
                        _steps[v](folder)
                else:
                    def run_step(v, folder, _user=loc.user):
                        runner(v, folder, _user)
                backup = upgrade_folder(loc.path, f"{m.title} 的資料", before, plan, run_step, keep=keep, now=now)
                done.append((loc.path, backup))
        record(data_dir, m.name, target, m.version, now)
    except Exception as e:
        for path, backup in reversed(done):
            try:
                restore_backup(backup, path)
            except Exception:
                logging.exception("[DATA] could not restore %s from %s", path, backup)
        if isinstance(e, DataError):
            raise StepError(f"{e}（{m.title} 的資料已經全部從備份還原、沒有被改）") from e
        raise StepError(f"{m.title} 的資料升級失敗（{type(e).__name__}: {e}），已經全部從備份還原、沒有被改。") from e
    logging.info("[DATA] %s data upgraded %s -> %s (%d place(s))", m.name, before, target, len(done))
    return _outcome(m, UPGRADED, before=before, after=target, steps=steps_text,
                    backup=done[0][1] if done else "")


def _upgrade_store(m, loc: Location, before: int, plan: List[int], steps: Dict[int, Callable], keep, now) -> str:
    """一份 pack.store 的檔：解開 → 每一步 fn(深拷貝) → 一次寫回（先備份）。回備份路徑。"""
    import copy
    codec = VaultCodec(loc.vault) if loc.vault is not None else JsonCodec(indent=2)
    with open(loc.path, "rb") as f:
        data = codec.decode(f.read(), os.path.basename(loc.path))
    for v in plan:
        try:
            new = steps[v](copy.deepcopy(data))
        except Exception as e:
            raise StepError(f"{m.title} 的資料（{os.path.basename(loc.path)}）從版本 {v} 升到 {v + 1} 時出錯"
                            f"（{type(e).__name__}: {e}）") from e
        if new is None:
            raise StepError(f"{m.title} 的 migrate_{v}_to_{v + 1} 沒有回傳新的資料（程式的問題）")
        data = new
    blob = codec.encode(data)
    backup = make_backup(loc.path, before, keep=keep, now=now)
    atomic_write_bytes(loc.path, blob)
    return backup


def plan_text(old_spec: dict, new_spec: dict, data_dir: str, name: str) -> Optional[dict]:
    """升級報告用（不執行任何工具程式）：{"from", "to", "alert", "text"}；資料版本不變回 None。"""
    to = (new_spec or {}).get("version")
    try:
        have = recorded(data_dir, name)
    except DataError:
        have = None
    if have is None:
        have = (old_spec or {}).get("version") if old_spec else None
    if not to:
        if have:
            return {"from": have, "to": None, "alert": True,
                    "text": f"新版沒有宣告 data_schema，但現在的資料是版本 {have}：SYNOX 不會幫它升級資料"}
        return None
    if have is None or have == to:
        return None
    if have > to:
        return {"from": have, "to": to, "alert": True,
                "text": f"這一版只認得到資料版本 {to}，你現在的資料是版本 {have}：裝了會停用（不會動資料）"}
    return {"from": have, "to": to, "alert": False,
            "text": f"資料會在新版第一次啟動前從版本 {have} 升到 {to}（先自動備份；失敗就還原、工具停用）"}
