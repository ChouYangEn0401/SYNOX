"""
遷移步驟與「逐版連續升級」（ADR 0043、docs/data-migrations.md）。

    CONFIG = Chain("config.json", current=2)

    @CONFIG.step(0)                      # 0 → 1：舊檔沒有版本號
    def _v0(data):
        return data                      # 輸入舊內容、回新內容（不要碰檔案；框架負責讀寫、備份、鎖）

    @CONFIG.step(1)                      # 1 → 2
    def _v1(data):
        data["web"] = data.pop("http", {})
        return data

    upgrade_file(path, CONFIG)           # 檔案是 0 版：0→1→2 連續跑完、一次寫回；已經是 2 版：什麼都不做

規則：
- 一個步驟只跨一版（v → v+1）。從檔案的版本到 current 中間缺任何一步＝GapError，不跳過、不動檔案。
- 檔案版本 > current＝TooNewError（較新的程式寫的）：不讀成舊格式、不寫、不動檔案；不嘗試降級。
- 步驟是純函式：拿到的是一份深拷貝，回傳新內容；框架在每一步之後把版本鍵設成 v+1。
  步驟要冪等（拿到已經是新格式的內容再跑一次，結果一樣）：檔案寫回與版本號不是同一個動作的格式（旁檔、資料夾）
  中斷後可能重跑同一步。
- 全部步驟在記憶體跑完才寫回（暫存檔＋原子取代）；寫回前先備份原檔；寫回後重讀驗證，不對就還原備份。
- 同一份資料同時只有一個程序升級（versioned.FileLock）；後到的拿到鎖之後重讀版本，通常已經不用做。
"""

from __future__ import annotations

import copy
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from synox.datastore.versioned import (DEFAULT_KEY, KEEP_BACKUPS, LEGACY, LOCK_WAIT_S, DataError, FileLock, GapError,
                                  StepError, TooNewError, atomic_write_bytes, check_version, json_version,
                                  make_backup, restore_backup, sidecar_version, sqlite_version, too_new_text,
                                  write_sidecar)

# Outcome.action
MISSING, CURRENT, PLANNED, UPGRADED, TOO_NEW, FAILED = "missing", "current", "planned", "upgraded", "too_new", "failed"


@dataclass
class Chain:
    """一種資料（一種檔案）的遷移步驟。current＝這支程式寫出的版本；steps[v]＝v → v+1 的函式。
    version_key：JSON 頂層放版本號的鍵（新檔一律 schema_version；舊檔已經有自己的鍵就沿用，見 versioned.py）。"""
    kind: str
    current: int
    version_key: str = DEFAULT_KEY
    title: str = ""
    steps: Dict[int, Callable] = field(default_factory=dict)

    def __post_init__(self):
        check_version(self.current, self.kind)

    @property
    def label(self) -> str:
        return self.title or self.kind

    def step(self, frm: int):
        """登記 frm → frm+1 的步驟（decorator）。同一個 frm 登記兩次＝寫錯，丟 ValueError。"""
        check_version(frm, self.kind)

        def register(fn: Callable) -> Callable:
            if frm in self.steps:
                raise ValueError(f"{self.kind}: step {frm}->{frm + 1} registered twice")
            if frm >= self.current:
                raise ValueError(f"{self.kind}: step {frm}->{frm + 1} is beyond the current version {self.current}")
            self.steps[frm] = fn
            return fn
        return register

    def gaps(self, start: int = LEGACY) -> List[int]:
        """從 start 到 current 缺哪幾步（回 from 版本）。"""
        return [v for v in range(start, self.current) if v not in self.steps]

    def plan(self, frm: int) -> List[int]:
        """從 frm 升到 current 要跑哪幾步（from 版本，照順序）。比 current 新丟 TooNewError；缺步驟丟 GapError。"""
        check_version(frm, self.kind)
        if frm > self.current:
            raise TooNewError(too_new_text(self.label, frm, self.current))
        missing = self.gaps(frm)
        if missing:
            raise GapError(gap_text(self.label, frm, self.current, missing))
        return list(range(frm, self.current))

    def upgrade_data(self, data: Any, where: str = "") -> Any:
        """記憶體裡的一份 JSON 物件 → 目前版本（寫檔之前用：寫的人一律寫目前的格式、蓋上目前的版本號）。
        已經是目前版本＝原物件；比較新丟 TooNewError（不准用舊格式蓋過去）。"""
        frm = json_version(data, self.version_key, where or self.label)
        if frm == self.current:
            return data
        return run_steps(self, data, frm)


def gap_text(what: str, frm: int, to: int, missing: List[int]) -> str:
    steps = "、".join(f"{v}→{v + 1}" for v in missing)
    return (f"{what} 要從資料版本 {frm} 升到 {to}，但少了 {steps} 的升級步驟。"
            "為了不弄壞資料，這次不升級、不動檔案（這是程式的問題，請回報給作者）。")


def run_steps(chain: Chain, data: Any, frm: int) -> Any:
    """在記憶體裡從 frm 一路跑到 current（每一步拿深拷貝、回新內容；JSON 物件的版本鍵每步之後設成 v+1）。
    步驟丟例外或回 None＝StepError（訊息白話，原例外接在 __cause__）。"""
    for v in chain.plan(frm):
        fn = chain.steps[v]
        try:
            new = fn(copy.deepcopy(data))
        except DataError:
            raise
        except Exception as e:
            raise StepError(f"{chain.label} 從版本 {v} 升到 {v + 1} 時出錯（{type(e).__name__}: {e}）。") from e
        if new is None:
            raise StepError(f"{chain.label} 的 {v}→{v + 1} 升級步驟沒有回傳新內容（程式的問題）。")
        if chain.version_key and isinstance(new, dict):
            new[chain.version_key] = v + 1
        data = new
    return data


@dataclass
class Outcome:
    """一份資料的升級結果（給 doctor、設定頁、啟動訊息用）。"""
    path: str
    kind: str
    action: str
    before: Optional[int] = None
    after: Optional[int] = None
    current: Optional[int] = None
    steps: List[str] = field(default_factory=list)
    backup: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.action in (MISSING, CURRENT, PLANNED, UPGRADED)

    @property
    def needs_upgrade(self) -> bool:
        return self.action == PLANNED

    def to_dict(self) -> dict:
        return {"file": os.path.basename(self.path), "kind": self.kind, "action": self.action, "before": self.before,
                "after": self.after, "current": self.current, "steps": list(self.steps), "message": self.message,
                "backup": os.path.basename(self.backup) if self.backup else ""}

    def line(self) -> str:
        """一行人話。"""
        name = self.kind
        if self.action == MISSING:
            return f"{name}：還沒有這份資料"
        if self.action == CURRENT:
            return f"✅ {name}：資料版本 {self.after}（最新）"
        if self.action == PLANNED:
            return f"⬆️ {name}：資料版本 {self.before} → {self.current}，要升級（{'、'.join(self.steps)}）"
        if self.action == UPGRADED:
            return f"✅ {name}：已從資料版本 {self.before} 升到 {self.after}（升級前的備份：{os.path.basename(self.backup)}）"
        mark = "⛔" if self.action == TOO_NEW else "❌"
        return f"{mark} {name}：{self.message}"


def _steps_text(plan: List[int]) -> List[str]:
    return [f"{v}→{v + 1}" for v in plan]


# ── 編碼：檔案的 bytes ↔ 記憶體裡的內容 ─────────────────────────────────

class JsonCodec:
    """純文字 JSON（utf-8，讀時容許 BOM）。indent 照原本寫這種檔的程式。"""

    def __init__(self, indent: Optional[int] = 2):
        self.indent = indent

    def decode(self, blob: bytes, where: str) -> Any:
        import json
        try:
            return json.loads(blob.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as e:
            raise DataError(f"{where} 不是合法的 JSON（{e}），不升級、不動它。")

    def encode(self, data: Any) -> bytes:
        import json
        return (json.dumps(data, ensure_ascii=False, indent=self.indent) + ("\n" if self.indent else "")).encode("utf-8")


class VaultCodec:
    """保管箱的密文 JSON（vault.Vault 的兩行格式）：解開 → 升級 → 用同一把金鑰重新加密（新的 salt）。"""

    def __init__(self, vault):
        self.vault = vault

    def decode(self, blob: bytes, where: str) -> Any:
        from synox.vault.vault import VaultError
        try:
            return self.vault.decrypt(blob, where=where)
        except VaultError as e:
            raise DataError(str(e))

    def encode(self, data: Any) -> bytes:
        return self.vault.encrypt(data)


JSON = JsonCodec()


# ── 升級一份 JSON 檔（純文字或密文） ────────────────────────────────────

def inspect_file(path: str, chain: Chain, codec=JSON) -> Outcome:
    """只看不改（doctor、設定頁、--dry-run）：版本、要不要升級、缺不缺步驟。"""
    where = os.path.basename(path)
    if not os.path.exists(path):
        return Outcome(path, chain.label, MISSING, current=chain.current)
    try:
        with open(path, "rb") as f:
            data = codec.decode(f.read(), where)
        before = json_version(data, chain.version_key, where)
        plan = chain.plan(before)
    except TooNewError as e:
        return Outcome(path, chain.label, TOO_NEW, before=_safe_version(path, chain, codec), current=chain.current,
                       message=str(e))
    except DataError as e:
        return Outcome(path, chain.label, FAILED, current=chain.current, message=str(e))
    if not plan:
        return Outcome(path, chain.label, CURRENT, before=before, after=before, current=chain.current)
    return Outcome(path, chain.label, PLANNED, before=before, current=chain.current, steps=_steps_text(plan))


def _safe_version(path: str, chain: Chain, codec) -> Optional[int]:
    try:
        with open(path, "rb") as f:
            return json_version(codec.decode(f.read(), ""), chain.version_key)
    except Exception:
        return None


def upgrade_file(path: str, chain: Chain, codec=JSON, *, dry_run: bool = False, keep: int = KEEP_BACKUPS,
                 lock_wait: float = LOCK_WAIT_S, now: Optional[float] = None) -> Outcome:
    """一份 JSON 檔升到 chain.current。dry_run＝只回會做什麼（不拿鎖、不備份、不寫）。
    不會丟 DataError：太新、缺步驟、步驟失敗、看不懂都回 Outcome（ok=False，message 是人話），檔案原封不動。"""
    if dry_run:
        return inspect_file(path, chain, codec)
    if not os.path.exists(path):
        return Outcome(path, chain.label, MISSING, current=chain.current)
    where = os.path.basename(path)
    try:
        with FileLock(path, wait=lock_wait):
            with open(path, "rb") as f:
                original = f.read()              # 拿到鎖之後才讀：前一個程序可能已經升好了
            data = codec.decode(original, where)
            before = json_version(data, chain.version_key, where)
            plan = chain.plan(before)            # TooNewError／GapError：什麼都還沒動
            if not plan:
                return Outcome(path, chain.label, CURRENT, before=before, after=before, current=chain.current)
            new = run_steps(chain, data, before)  # 全在記憶體：失敗時檔案沒被碰過
            blob = codec.encode(new)
            backup = make_backup(path, before, keep=keep, now=now)
            try:
                atomic_write_bytes(path, blob)
                with open(path, "rb") as f:      # 寫回後重讀：看得懂、版本對，才算數
                    after = json_version(codec.decode(f.read(), where), chain.version_key, where)
                if after != chain.current:
                    raise StepError(f"{chain.label} 寫回後的版本是 {after}，不是 {chain.current}。")
            except Exception as e:
                _put_back(path, original, backup)
                if isinstance(e, DataError):
                    raise
                raise StepError(f"{chain.label} 升級後寫回失敗（{type(e).__name__}: {e}），原資料沒有被改。") from e
            return Outcome(path, chain.label, UPGRADED, before=before, after=after, current=chain.current,
                           steps=_steps_text(plan), backup=backup)
    except TooNewError as e:
        return Outcome(path, chain.label, TOO_NEW, before=_safe_version(path, chain, codec), current=chain.current,
                       message=str(e))
    except DataError as e:
        return Outcome(path, chain.label, FAILED, current=chain.current, message=str(e))


def _put_back(path: str, original: bytes, backup: str) -> None:
    """寫回失敗之後：檔案還是原樣（原子取代沒發生）就不用動；不是原樣就從備份換回。換不回來＝StepError（說備份在哪）。"""
    try:
        with open(path, "rb") as f:
            if f.read() == original:
                return
    except OSError:
        pass
    try:
        restore_backup(backup, path)
    except Exception as e:
        raise StepError(f"{os.path.basename(path)} 升級失敗，而且沒能自動換回原檔（{e}）："
                        f"升級前的備份在 {backup}，請把它複製回去。") from e


# ── 旁檔記版本的格式（YAML、純文字…）：步驟拿 bytes 回 bytes ─────────────

def upgrade_sidecar_file(path: str, chain: Chain, *, dry_run: bool = False, keep: int = KEEP_BACKUPS,
                         lock_wait: float = LOCK_WAIT_S, now: Optional[float] = None) -> Outcome:
    """版本在 <path>.schema 的檔：步驟 fn(bytes) -> bytes。先寫資料、再寫旁檔；兩步之間被中斷，下次會重跑最後一步
    （所以步驟一定要冪等）。任何一步失敗：資料檔從備份還原、旁檔不動。"""
    if not os.path.exists(path):
        return Outcome(path, chain.label, MISSING, current=chain.current)
    try:
        before = sidecar_version(path)
        plan = chain.plan(before)
        if not plan:
            return Outcome(path, chain.label, CURRENT, before=before, after=before, current=chain.current)
        if dry_run:
            return Outcome(path, chain.label, PLANNED, before=before, current=chain.current, steps=_steps_text(plan))
        with FileLock(path, wait=lock_wait):
            before = sidecar_version(path)
            plan = chain.plan(before)
            if not plan:
                return Outcome(path, chain.label, CURRENT, before=before, after=before, current=chain.current)
            with open(path, "rb") as f:
                blob = f.read()
            new = run_steps(Chain(chain.kind, chain.current, "", chain.title, chain.steps), blob, before)
            if not isinstance(new, (bytes, bytearray)):
                raise StepError(f"{chain.label} 的升級步驟要回傳 bytes。")
            backup = make_backup(path, before, keep=keep, now=now)
            try:
                atomic_write_bytes(path, bytes(new))
                write_sidecar(path, chain.current)
            except Exception as e:
                _put_back(path, blob, backup)
                raise StepError(f"{chain.label} 升級後寫回失敗（{type(e).__name__}: {e}），原資料沒有被改。") from e
            return Outcome(path, chain.label, UPGRADED, before=before, after=chain.current, current=chain.current,
                           steps=_steps_text(plan), backup=backup)
    except TooNewError as e:
        return Outcome(path, chain.label, TOO_NEW, current=chain.current, message=str(e))
    except DataError as e:
        return Outcome(path, chain.label, FAILED, current=chain.current, message=str(e))


# ── SQLite：PRAGMA user_version；全部步驟同一個交易 ─────────────────────

def upgrade_sqlite(path: str, chain: Chain, *, dry_run: bool = False, keep: int = KEEP_BACKUPS,
                   lock_wait: float = LOCK_WAIT_S, now: Optional[float] = None) -> Outcome:
    """步驟 fn(conn)（在交易裡改結構與資料，不要自己 commit）。全部步驟＋user_version 在同一個交易：
    任何一步失敗就 ROLLBACK，資料庫維持原樣（另外照樣先做檔案備份）。"""
    if not os.path.exists(path):
        return Outcome(path, chain.label, MISSING, current=chain.current)

    def version() -> int:
        conn = sqlite3.connect(path)
        try:
            return sqlite_version(conn)
        finally:
            conn.close()

    try:
        before = version()
        plan = chain.plan(before)
        if not plan or dry_run:
            return Outcome(path, chain.label, PLANNED if plan else CURRENT, before=before,
                           after=None if plan else before, current=chain.current, steps=_steps_text(plan))
        with FileLock(path, wait=lock_wait):
            before = version()
            plan = chain.plan(before)
            if not plan:
                return Outcome(path, chain.label, CURRENT, before=before, after=before, current=chain.current)
            backup = make_backup(path, before, keep=keep, now=now)
            conn = sqlite3.connect(path, isolation_level=None)
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for v in plan:
                        try:
                            chain.steps[v](conn)
                        except Exception as e:
                            raise StepError(f"{chain.label} 從版本 {v} 升到 {v + 1} 時出錯（{type(e).__name__}: {e}）。") from e
                        conn.execute(f"PRAGMA user_version = {int(v + 1)}")
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.close()
            return Outcome(path, chain.label, UPGRADED, before=before, after=version(), current=chain.current,
                           steps=_steps_text(plan), backup=backup)
    except TooNewError as e:
        return Outcome(path, chain.label, TOO_NEW, current=chain.current, message=str(e))
    except DataError as e:
        return Outcome(path, chain.label, FAILED, current=chain.current, message=str(e))


# ── 整個資料夾（工具的資料夾）：版本由呼叫的人記；失敗整個資料夾換回備份 ──────

def upgrade_folder(folder: str, label: str, before: int, plan: List[int], run_step: Callable[[int, str], None], *,
                   keep: int = KEEP_BACKUPS, now: Optional[float] = None) -> str:
    """資料夾先整份備份 → 照 plan 一步一步 run_step(from 版本, 資料夾)（就地改）→ 任何一步失敗：資料夾換回備份、
    丟 StepError。回備份路徑（資料夾不存在回 ""，什麼都不做）。版本號記在哪由呼叫的人決定（packdata.py 的登記表）。"""
    if not os.path.isdir(folder):
        return ""
    backup = make_backup(folder, before, keep=keep, now=now)
    for v in plan:
        try:
            run_step(v, folder)
        except Exception as e:
            restore_backup(backup, folder)
            if isinstance(e, DataError):
                raise StepError(f"{e}（資料夾已經從備份還原）") from e
            raise StepError(f"{label} 從版本 {v} 升到 {v + 1} 時出錯（{type(e).__name__}: {e}），"
                            "資料夾已經從備份還原。") from e
    return backup
