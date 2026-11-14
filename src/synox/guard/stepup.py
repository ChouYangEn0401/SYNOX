"""手機驗證器（ADR 0025 §5）：每個人自己的金鑰、解鎖綁入口、一組碼只過一次、錯 5 次鎖 15 分鐘、備用碼。

    hub = StepUp(store, owner_id=…, minutes=15, clock=time.time, audit=Audit(…), notify=app.notify)
    hub.begin(uid) → {"secret", "uri", "expires_in"}     金鑰先只在記憶體（10 分鐘）
    hub.confirm(uid, code) → 10 組備用碼                  打對一組碼才存進保管箱
    hub.unlock(uid, code, origin=o)                       解鎖 minutes 分鐘；只對「這個入口」（origin.surface）有效
    hub.unlocked(uid, o)                                   policy.decide 問的就是這個

- 計算用 SDK 的 `isdtelekit.security.totp`（RFC 6238：6 位數、30 秒、SHA-1）。
- 來源不是人（或遠端）→ `not_human`：不計次、不碰金鑰。
- 用過的時段寫回保管箱（每次成功都存），所以重開 SYNOX 之後同一組碼仍然是重放。
- 備用碼：只存 HMAC-SHA256(salt, 正規化後的碼)；只在 allow_recovery=True（本機主機台、命令列）時試。
- 解鎖視窗與 begin 的暫存只在記憶體：SYNOX 重開＝全部上鎖。
- log 與稽核裡沒有碼、金鑰、備用碼。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from isdtelekit.security import totp

from synox.guard import origin as origin_mod
from synox.guard.limits import Attempts

RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_COUNT = 10
BEGIN_SECONDS = 600
ISSUER = "SYNOX"
ALLOWED_KINDS = origin_mod.HUMAN + ("remote",)

TEXT = {
    "need": "🔐 這個動作要先解鎖：/unlock <手機驗證器上的 6 位數>（在 SYNOX 網頁上會直接跳出輸入框）。",
    "unset": "🔐 這個動作一定要先設定手機驗證器：到 SYNOX 網頁 → 設定 → 🔐 安全。",
    "bad": "❌ 驗證碼不對。",
    "replay": "❌ 這組驗證碼剛剛用過了，等手機上換下一組再打。",
    "locked": "🔒 驗證碼錯太多次，先鎖住了，{m} 分鐘後再試。",
    "not_human": "🔐 驗證碼只能由你本人在 Telegram 或 SYNOX 網頁打。",
    "recovery_here": "備用碼只能在這台電腦的 SYNOX 網頁上用。",
    "expired": "設定的時間過了，請重新按「設定手機驗證器」。",
    "unreadable": "🔒 手機驗證器的資料現在讀不出來（保管箱打不開或壞了），為了安全先擋住需要驗證的動作。"
                  "修好保管箱，或在這台電腦跑 python -m synox stepup reset 重新設定。",
    "already": "已經設定過手機驗證器了。",
    "unlocked": "🔓 已解鎖 {m} 分鐘。用完可以 /unlock_off 馬上鎖回去。",
    "locked_now": "🔒 驗證碼連續錯了好幾次，先鎖 15 分鐘。不是你本人在試的話，請檢查 Telegram 的登入裝置。",
    "recovery_used": "你用掉了一組備用碼，還剩 {n} 組。",
    "disabled": "手機驗證器已經關掉了。不是你做的話，請馬上檢查這台電腦與 Telegram 的登入裝置。",
    "enrolled_notice": "你的帳號剛設定了手機驗證器；不是你做的請找管理員。",
}

# 主機台上「開了開關就要先解鎖」的敏感動作（路由 → 白話的動作名）。web 的 api() 在這些路由最前面問 gate()。
SENSITIVE = {
    "/api/packs/install": "安裝工具",
    "/api/packs/remove": "移除工具",
    "/api/packs/library/install": "從工具庫安裝",
    "/api/settings/llm": "改 AI 的設定",
    "/api/settings/channels/telegram": "改 Telegram 的設定",
    "/api/settings/channels/discord": "改 Discord 的設定",
    "/api/backup": "備份",
    "/api/accounts/role": "改帳號的角色",
    "/api/settings/update/launch": "更新 SYNOX",
}

# 預設就擋（deny-by-default）：這幾個前綴底下的非 GET 都算敏感（改設定、裝工具、金鑰、背景任務、帳號、備份），
# 除了下面明列的例外（不改任何東西、或只是丟掉一個還沒裝的上傳）。新加的路由沒列進例外就自動受保護。
SENSITIVE_PREFIXES = ("/api/settings/", "/api/packs/", "/api/pack-secrets/", "/api/runtime/", "/api/backup",
                      "/api/accounts/", "/api/tools/health")
SENSITIVE_EXEMPT = ("/api/packs/discard", "/api/packs/library", "/api/settings/llm/test", "/api/settings/llm/local-advice",
                    "/api/settings/update/check", "/api/settings/update/dismiss")   # 只查、只藏橫幅：不改東西
SENSITIVE_DEFAULT_LABEL = "改 SYNOX 的設定"


def sensitive_action(method: str, path: str) -> Optional[str]:
    """這個主機台請求要不要過 gate()：回白話的動作名，不用回 None。"""
    if str(method).upper() == "GET" or path in SENSITIVE_EXEMPT:
        return None
    if path in SENSITIVE:
        return SENSITIVE[path]
    if any(path == p.rstrip("/") or path.startswith(p) for p in SENSITIVE_PREFIXES):
        return SENSITIVE_DEFAULT_LABEL
    return None


Resp = Tuple[int, List[Tuple[str, str]], bytes]


class Result(NamedTuple):
    ok: bool
    code: str
    text: str


class Refused(Exception):
    def __init__(self, result: Result):
        self.result = result
        super().__init__(result.code)


def match_code(secret: str, code, now: float):
    """SDK 的 totp.match 前面先擋「不是 ASCII 的數字」（"١٢٣٤٥٦".isdigit() 是 True，compare_digest 會丟 TypeError）。
    vendor/ 不改，所以在這裡擋。回時段或 None。"""
    text = str(code or "").strip().replace(" ", "")
    if not text.isascii() or not text.isdigit():
        return None
    return totp.match(secret, text, now=now)


def _norm_recovery(code: str) -> str:
    return "".join(c for c in str(code or "").lower() if c not in "- ")


def looks_like_recovery(code: str) -> bool:
    n = _norm_recovery(code)
    return len(n) == 10 and all(c in RECOVERY_ALPHABET for c in n) and not n.isdigit()


def new_recovery_codes() -> List[str]:
    out: List[str] = []
    while len(out) < RECOVERY_COUNT:
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        code = raw[:5] + "-" + raw[5:]
        if code not in out:
            out.append(code)
    return out


def _hash(salt: str, code: str) -> str:
    return hmac.new(bytes.fromhex(salt), _norm_recovery(code).encode("ascii", "ignore"), hashlib.sha256).hexdigest()


def group_secret(secret: str) -> str:
    """金鑰四個字一組（手動輸入比較不會打錯）。"""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


class StepUp:
    def __init__(self, store, *, owner_id, minutes: int = 15, clock: Callable[[], float] = time.time, audit=None,
                 notify: Optional[Callable[[int, str], None]] = None):
        self.store = store
        self.owner_id = int(owner_id or 0)
        self.minutes = max(1, min(120, int(minutes or 15)))
        self.clock = clock
        self.audit = audit
        self.notify = notify
        self.attempts = Attempts(5, 900, 900, clock=clock)
        self._mu = threading.RLock()
        self._pending: Dict[int, Tuple[str, float]] = {}
        self._until: Dict[Tuple[int, str], float] = {}
        self._on_disable: List[Callable[[int], None]] = []
        self._on_change: List[Callable[[int], None]] = []
        self._bad_listeners: List[Callable[[str], None]] = []

    # ── 小工具 ───────────────────────────────────────────────────────

    def _read(self, uid: int):
        """("ok", data)｜("unset", None)｜("broken", None)：保管箱讀不出來（或內容壞了）≠ 沒設定。"""
        try:
            data = self.store.load(int(uid))
        except Exception as e:
            logging.error("[STEPUP] cannot read store: %s", type(e).__name__)
            return "broken", None
        if data is None:
            return "unset", None
        if isinstance(data, dict) and data.get("v") == 1 and isinstance(data.get("secret"), str):
            return "ok", data
        return "broken", None

    def _load(self, uid: int) -> Optional[dict]:
        return self._read(uid)[1]

    def unreadable(self, user_id) -> bool:
        """設定過、但現在讀不出來：**當作有設定、而且沒有人解鎖得了**（危險的動作一律擋、不能重新設定），
        直到保管箱修好或在這台電腦跑 `python -m synox stepup reset`。"""
        return self._read(int(user_id))[0] == "broken"

    def _log(self, event: str, uid: int, o=None, ok: bool = True, code: str = "", **nums) -> None:
        if self.audit is not None:
            self.audit.write(event, by=uid, origin=getattr(o, "kind", "") if o is not None else "", ok=ok, code=code,
                             **nums)

    def _tell(self, uid: int, text: str) -> None:
        if self.notify is not None:
            try:
                self.notify(int(uid), text)
            except Exception:
                logging.exception("[STEPUP] notify failed")

    def _fire(self, listeners, *args) -> None:
        for fn in list(listeners):
            try:
                fn(*args)
            except Exception:
                logging.exception("[STEPUP] listener failed")

    def on_disable(self, fn: Callable[[int], None]) -> None:
        self._on_disable.append(fn)

    def on_change(self, fn: Callable[[int], None]) -> None:
        """設定好或關掉之後叫 fn(uid)（app.stepup 要跟著換，guard/__init__.py）。"""
        self._on_change.append(fn)

    # ── 狀態 ─────────────────────────────────────────────────────────

    def enrolled(self, user_id) -> bool:
        return self._read(int(user_id))[0] != "unset"

    def protects_danger(self, user_id) -> bool:
        status, data = self._read(int(user_id))
        return status == "broken" or bool(data and data.get("protect_danger"))

    def unlocked(self, user_id, o) -> bool:
        return self.remaining(user_id, o) > 0

    def remaining(self, user_id, o) -> int:
        surface = getattr(o, "surface", "") or ""
        kind = getattr(o, "kind", "unknown")
        if not surface or kind not in ALLOWED_KINDS:
            return 0
        with self._mu:
            left = self._until.get((int(user_id), surface), 0.0) - self.clock()
        return max(0, int(left))

    def lock(self, user_id, o=None) -> bool:
        uid = int(user_id)
        with self._mu:
            if o is None:
                keys = [k for k in self._until if k[0] == uid]
            else:
                keys = [k for k in [(uid, getattr(o, "surface", ""))] if k in self._until]
            for k in keys:
                del self._until[k]
        return bool(keys)

    def status(self, user_id, o) -> dict:
        uid = int(user_id)
        data = self._load(uid)
        return {
            "enrolled": data is not None,
            "protect_danger": bool(data and data.get("protect_danger")),
            "unlocked": self.unlocked(uid, o),
            "unlock_left_s": self.remaining(uid, o),
            "recovery_left": len([r for r in (data or {}).get("recovery", []) if not r.get("used")]),
            "locked_for_s": int(self.attempts.locked(uid)),
            "minutes": self.minutes,
        }

    # ── 設定 ─────────────────────────────────────────────────────────

    def begin(self, user_id) -> dict:
        uid = int(user_id)
        if self.enrolled(uid):
            raise ValueError("already enrolled")
        secret = totp.new_secret()
        with self._mu:
            self._pending[uid] = (secret, self.clock() + BEGIN_SECONDS)
        account = "owner" if uid == self.owner_id else f"user-{uid}"
        return {"secret": secret, "uri": totp.provisioning_uri(secret, account, issuer=ISSUER),
                "expires_in": BEGIN_SECONDS}

    def confirm(self, user_id, code) -> List[str]:
        """打對 begin 那把金鑰的一組碼：存進保管箱、回 10 組備用碼（只有這一次）。不對丟 Refused。"""
        uid = int(user_id)
        o = origin_mod.current()
        if o.kind not in origin_mod.HUMAN:
            raise Refused(Result(False, "not_human", TEXT["not_human"]))
        if self.enrolled(uid):
            raise Refused(Result(False, "already", TEXT["already"]))
        with self._mu:
            pending = self._pending.get(uid)
            if pending is None or pending[1] <= self.clock():
                self._pending.pop(uid, None)
                raise Refused(Result(False, "expired", TEXT["expired"]))
            wait = self.attempts.locked(uid)
            if wait:
                raise Refused(Result(False, "locked", TEXT["locked"].format(m=int(wait // 60) + 1)))
            counter = match_code(pending[0], code, self.clock())
            if counter is None:
                self._failed(uid, o)
                raise Refused(Result(False, "bad", TEXT["bad"]))
            codes = new_recovery_codes()
            salt = secrets.token_hex(16)
            data = {"v": 1, "secret": pending[0], "created": int(self.clock()), "last_counter": counter,
                    "protect_danger": False, "recovery_salt": salt,
                    "recovery": [{"h": _hash(salt, c), "used": 0} for c in codes]}
            self.store.save(uid, data)
            self._pending.pop(uid, None)
            self.attempts.ok(uid)
        self._log("stepup_enroll", uid, o)
        if uid != self.owner_id:
            self._tell(uid, TEXT["enrolled_notice"])
        self._fire(self._on_change, uid)
        return codes

    # ── 驗證 ─────────────────────────────────────────────────────────

    def _failed(self, uid: int, o) -> None:
        just_locked = self.attempts.fail(uid)
        self._log("stepup_fail", uid, o, ok=False, code="bad")
        self._fire(self._bad_listeners, "A")
        if just_locked:
            self._log("stepup_locked", uid, o, ok=False, code="locked")
            self._tell(uid, TEXT["locked_now"])

    def verify(self, user_id, code, *, origin, purpose: str = "", allow_recovery: bool = False) -> Result:
        """一次性的驗證（不開解鎖視窗）。"""
        uid = int(user_id)
        o = origin if origin is not None else origin_mod.current()
        if getattr(o, "kind", "unknown") not in ALLOWED_KINDS:
            return Result(False, "not_human", TEXT["not_human"])
        code = str(code or "").strip()
        with self._mu:
            status, data = self._read(uid)
            if status == "broken":
                return Result(False, "unreadable", TEXT["unreadable"])
            if data is None:
                return Result(False, "unset", TEXT["unset"])
            wait = self.attempts.locked(uid)
            if wait:
                return Result(False, "locked", TEXT["locked"].format(m=int(wait // 60) + 1))
            if looks_like_recovery(code):
                if not allow_recovery:
                    return Result(False, "recovery_here", TEXT["recovery_here"])
                return self._use_recovery(uid, data, code, o)
            counter = match_code(data["secret"], code, self.clock())
            last = data.get("last_counter")
            if counter is not None and counter == last:
                return Result(False, "replay", TEXT["replay"])
            if counter is None or (isinstance(last, int) and counter < last):
                self._failed(uid, o)
                return Result(False, "bad", TEXT["bad"])
            data["last_counter"] = counter
            self.store.save(uid, data)
            self.attempts.ok(uid)
        return Result(True, "", "")

    def _use_recovery(self, uid: int, data: dict, code: str, o) -> Result:
        salt = data.get("recovery_salt") or ""
        want = _hash(salt, code)
        for item in data.get("recovery", []):
            if not item.get("used") and hmac.compare_digest(str(item.get("h", "")), want):
                item["used"] = int(self.clock())
                self.store.save(uid, data)
                self.attempts.ok(uid)
                left = len([r for r in data["recovery"] if not r.get("used")])
                self._log("stepup_recovery_used", uid, o, left=left)
                self._tell(uid, TEXT["recovery_used"].format(n=left))
                return Result(True, "", "")
        self._failed(uid, o)
        return Result(False, "bad", TEXT["bad"])

    def unlock(self, user_id, code, *, origin, allow_recovery: bool = False) -> Result:
        uid = int(user_id)
        o = origin if origin is not None else origin_mod.current()
        r = self.verify(uid, code, origin=o, purpose="unlock", allow_recovery=allow_recovery)
        if not r.ok:
            return r
        surface = getattr(o, "surface", "") or ""
        if not surface:
            return Result(False, "not_human", TEXT["not_human"])
        with self._mu:
            self._until[(uid, surface)] = self.clock() + self.minutes * 60
        self._log("stepup_unlock", uid, o, minutes=self.minutes)
        return Result(True, "", TEXT["unlocked"].format(m=self.minutes))

    # ── 開關、備用碼、關掉 ─────────────────────────────────────────────

    def set_protect(self, user_id, on, *, origin) -> Result:
        uid = int(user_id)
        o = origin if origin is not None else origin_mod.current()
        if getattr(o, "kind", "unknown") not in origin_mod.HUMAN:
            return Result(False, "not_human", TEXT["not_human"])
        with self._mu:
            data = self._load(uid)
            if data is None:
                return Result(False, "unset", TEXT["unset"])
            if not on and data.get("protect_danger") and not self.unlocked(uid, o):
                return Result(False, "need", TEXT["need"])
            data["protect_danger"] = bool(on)
            self.store.save(uid, data)
        self._log("stepup_protect", uid, o, on=int(bool(on)))
        return Result(True, "", "")

    def new_recovery(self, user_id, code, *, origin) -> List[str]:
        """要一組新的碼（不吃解鎖視窗）。舊的備用碼全部作廢。"""
        uid = int(user_id)
        r = self.verify(uid, code, origin=origin, purpose="recovery")
        if not r.ok:
            raise Refused(r)
        codes = new_recovery_codes()
        with self._mu:
            data = self._load(uid)
            if data is None:
                raise Refused(Result(False, "unset", TEXT["unset"]))
            salt = secrets.token_hex(16)
            data["recovery_salt"] = salt
            data["recovery"] = [{"h": _hash(salt, c), "used": 0} for c in codes]
            self.store.save(uid, data)
        self._log("stepup_recovery_new", uid, origin)
        return codes

    def disable(self, user_id, code, *, origin, allow_recovery: bool = True) -> Result:
        uid = int(user_id)
        r = self.verify(uid, code, origin=origin, purpose="disable", allow_recovery=allow_recovery)
        if not r.ok:
            return r
        self._drop(uid)
        self._log("stepup_disable", uid, origin)
        self._tell(uid, TEXT["disabled"])
        self._fire(self._on_disable, uid)
        self._fire(self._on_change, uid)
        return Result(True, "", "")

    def reset_local(self, user_id) -> None:
        """只給命令列（`python -m synox stepup reset`）：能在這台電腦用這個帳號跑程式的人本來就能改設定。"""
        uid = int(user_id)
        self._drop(uid)
        self._log("stepup_reset", uid, origin_mod.Origin("console", uid, surface="console"))
        self._fire(self._on_disable, uid)
        self._fire(self._on_change, uid)

    def _drop(self, uid: int) -> None:
        with self._mu:
            self.store.delete(uid)
            self._pending.pop(uid, None)
            self.lock(uid)
            self.attempts.ok(uid)

    # ── 主機台的敏感動作（K5）──────────────────────────────────────────

    def gate(self, user, action: str) -> Optional[Resp]:
        """開了「危險的動作也要先解鎖」而這個入口還沒解鎖 → 403 {"error", "code": "stepup"}；不用擋回 None。"""
        uid = int(getattr(user, "tg_id", 0) or 0)
        if not self.protects_danger(uid) or self.unlocked(uid, origin_mod.current()):
            return None
        label = SENSITIVE.get(action) or (SENSITIVE_DEFAULT_LABEL if str(action).startswith("/") else str(action))
        body = json.dumps({"error": f"「{label}」要先解鎖。", "code": "stepup"},
                          ensure_ascii=False).encode("utf-8")
        return 403, [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")], body

    # ── 接到 SDK（K3）────────────────────────────────────────────────

    def sdk(self) -> "SdkStepUp":
        return SdkStepUp(self)


class SdkStepUp:
    """給 SDK 的轉接物件：跟 `isdtelekit.security.stepup.StepUp` 同一組方法（registry.authorize、forms、accounts 用）。
    不帶使用者的那幾個（configured、verify_once、check）指的是擁有者；解鎖照「現在的來源」。"""

    def __init__(self, hub: StepUp):
        self._hub = hub

    @property
    def configured(self) -> bool:
        return self._hub.enrolled(self._hub.owner_id)

    @property
    def need_message(self) -> str:
        return TEXT["need"]

    @property
    def unset_message(self) -> str:
        return TEXT["unset"]

    def has_factor(self, factor: str = "A") -> bool:
        return factor == "A" and self.configured

    def is_elevated(self, tg_id: int) -> bool:
        return self._hub.unlocked(tg_id, origin_mod.current())

    def remaining(self, tg_id: int) -> int:
        return self._hub.remaining(tg_id, origin_mod.current())

    def elevate(self, tg_id: int, code: str) -> Tuple[bool, str]:
        r = self._hub.unlock(tg_id, code, origin=origin_mod.current())
        return r.ok, r.text

    def verify_once(self, code: str, factor: str = "A") -> Tuple[bool, str]:
        if factor != "A":
            return False, TEXT["unset"]
        o = origin_mod.current()
        uid = o.user_id or self._hub.owner_id
        r = self._hub.verify(uid, code, origin=o, purpose="form")
        return (True, "✅ 驗證碼正確。") if r.ok else (False, r.text)

    def check(self, code: str, factor: str = "A") -> bool:
        data = self._hub._load(self._hub.owner_id)
        return factor == "A" and data is not None and \
            match_code(data["secret"], code, self._hub.clock()) is not None

    def drop(self, tg_id: int) -> bool:
        return self._hub.lock(tg_id, origin_mod.current())

    def issue_ticket(self) -> str:
        raise NotImplementedError("SYNOX does not use step-up tickets (ADR 0025 §5.4)")

    def on_bad_code(self, listener: Callable[[str], None]) -> None:
        self._hub._bad_listeners.append(listener)
