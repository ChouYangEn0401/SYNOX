"""
提升權限（sudo）：Telegram 帳號被盜時的第二道門。

owner_only 只確認「訊息來自擁有者的 Telegram 帳號」。帳號被盜（另一台裝置登入、SIM 被換、session 檔被偷）時，
對方就是擁有者。所以會動到這台電腦、錢、或對外開門的指令標成 elevated，要先 /sudo <手機驗證器上的 6 位數>
解鎖一段時間才能用。驗證碼來自擁有者手機上的驗證器 App，不經過 Telegram，偷到 Telegram 帳號也拿不到。

- 密鑰只在這台電腦上設定（`python -m isdtelekit.security.setup`），永遠不經過 Telegram：
  聊天紀錄裡出現過密鑰，帳號被盜時就等於沒設。存在 data/stepup_totp.json（不進 git）。
- 沒設定密鑰時 elevated 指令一律拒絕（fail closed），回覆怎麼設定。
- 解鎖狀態只在記憶體：bot 重啟就要重新 /sudo。
- 同一個驗證碼只能用一次（記住用過的時段）；連錯 MAX_FAILURES 次鎖 LOCK_MINUTES 分鐘。
  重放（剛驗過的同一組碼再送一次）回「等下一組」，但不算錯——那不是猜碼。
- 排程觸發（via=routine）不用驗證：建立排程時已經驗過（registry.authorize 的 SCHEDULE）。
- verify_once()：給「每次都要重新看手機」的高風險指令用（表單的 Field(fresh_code=True)，core/forms.py）。
  跟 elevate() 共用同一套防重放／連錯鎖定，但不設定解鎖視窗——驗證完這一次，下一次一樣要新的碼。
- 第二組驗證器（factor B）：另一把密鑰（data/stepup_totp_b.json，`... setup --factor B`），建議放在另一個帳號
  或另一支手機的驗證器 App。只有最危險的動作要兩組（Field(factor="B")）。防重放各算各的，連錯鎖定兩組共用；
  沒設定 B 時，要 B 的動作一律拒絕。
- 票（issue_ticket）：使用者在核准卡上當場驗過碼之後，程式代替他執行時用的一次性、60 秒的內部票；
  驗證碼本身不用再傳一次。
- 打錯的碼會通知 on_bad_code 的聽眾（例如連錯就自動關掉某個放寬的開關）。
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from isdtelekit.core.jsonstore import load_json, save_json
from isdtelekit.security import totp

SECRET_PATH = "data/stepup_totp.json"
FACTOR_A, FACTOR_B = "A", "B"
DEFAULT_MINUTES = 30
MAX_FAILURES = 5
LOCK_MINUTES = 15
TICKET_PREFIX = "ticket-"
TICKET_SECONDS = 60

SETUP_COMMAND = ".venv\\Scripts\\python.exe -m isdtelekit.security.setup"
NOT_CONFIGURED = f"🔐 還沒設定手機驗證器，這類指令先全部停用。\n在電腦上執行：{SETUP_COMMAND}"
NOT_CONFIGURED_B = (f"🔐 第二組驗證器（B）還沒設定，要兩組碼的動作先全部停用。\n在電腦上執行：{SETUP_COMMAND} --factor B\n"
                    "（建議放在另一個帳號或另一支手機的驗證器 App：一支手機被拿走，另一組還在。）")
NEED_SUDO = "🔐 這個指令要先解鎖：/sudo <手機驗證器上的 6 位數>"


class StepUp:

    def __init__(self, path: str = SECRET_PATH, minutes: int = DEFAULT_MINUTES, clock=time.time,
                 path_b: Optional[str] = None):
        self.path = path
        root, ext = os.path.splitext(path)
        self.path_b = path_b or f"{root}_b{ext}"         # 第二組驗證器：data/stepup_totp_b.json
        self.minutes = max(1, int(minutes))
        self._clock = clock
        self._lock = threading.Lock()
        self._until: Dict[int, float] = {}
        self._last_counter: Optional[int] = None          # factor A 用過的最後一個時段（防重放）
        self._last_counter_b: Optional[int] = None        # factor B 的
        self._failures: list = []
        self._locked_until = 0.0
        self._tickets: Dict[str, float] = {}
        self._bad_code_listeners: List[Callable[[str], None]] = []

    def on_bad_code(self, listener: Callable[[str], None]) -> None:
        """打錯驗證碼（不含重放）時呼叫 listener(factor)。在鎖外面呼叫。"""
        self._bad_code_listeners.append(listener)

    # 🔐 指令被擋下時給人看的話。core/registry.py 的 authorize 跟這裡拿（registry 不 import 這支檔案）
    @property
    def need_message(self) -> str:
        return NEED_SUDO

    @property
    def unset_message(self) -> str:
        return NOT_CONFIGURED

    # ── secret ─────────────────────────────────────────────────────────

    def _path(self, factor: str) -> str:
        return self.path_b if factor == FACTOR_B else self.path

    def _secret(self, factor: str = FACTOR_A) -> Optional[str]:
        data = load_json(self._path(factor), {})
        return (data.get("secret") if isinstance(data, dict) else None) or None

    @property
    def configured(self) -> bool:
        return self._secret() is not None

    def has_factor(self, factor: str) -> bool:
        return self._secret(factor) is not None

    def check(self, code: str, factor: str = FACTOR_A) -> bool:
        """只驗證、不解鎖也不記錄（給本機設定程式確認 App 設對了）。"""
        secret = self._secret(factor)
        return secret is not None and totp.match(secret, code, now=self._clock()) is not None

    def create_secret(self, factor: str = FACTOR_A) -> str:
        """只給本機的設定程式用（還有測試）。換新密鑰會讓舊的驗證器失效。"""
        secret = totp.new_secret()
        save_json(self._path(factor), {"secret": secret, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        return secret

    # ── elevation ──────────────────────────────────────────────────────

    def is_elevated(self, tg_id: int) -> bool:
        with self._lock:
            return self._until.get(tg_id, 0) > self._clock()

    def remaining(self, tg_id: int) -> int:
        """剩幾秒；沒解鎖回 0。"""
        with self._lock:
            return max(0, int(self._until.get(tg_id, 0) - self._clock()))

    def _consume_code(self, code: str, factor: str = FACTOR_A) -> Tuple[bool, str, bool]:
        """核心驗證：防重放、連錯鎖定。回 (成功, 訊息, 算不算打錯)。呼叫時已經持有 self._lock。"""
        now = self._clock()
        if code.startswith(TICKET_PREFIX):
            expires = self._tickets.pop(code, 0.0)
            return (True, "", False) if expires > now else (False, "❌ 核准已經過期，請重新核准。", False)
        secret = self._secret(factor)
        if secret is None:
            return False, (NOT_CONFIGURED_B if factor == FACTOR_B else NOT_CONFIGURED), False
        if self._locked_until > now:
            wait = int((self._locked_until - now) // 60) + 1
            return False, f"🔒 驗證碼錯太多次，{wait} 分鐘後再試。", False
        last = self._last_counter_b if factor == FACTOR_B else self._last_counter
        counter = totp.match(secret, code, now=now)
        if counter is not None and counter == last:
            return False, "❌ 這組驗證碼剛剛用過了，等手機上換下一組再打。", False   # 重放：不是猜碼，不計入鎖定
        if counter is None or (last is not None and counter <= last):
            self._failures = [t for t in self._failures if now - t < LOCK_MINUTES * 60] + [now]
            if len(self._failures) >= MAX_FAILURES:
                self._locked_until = now + LOCK_MINUTES * 60
                self._failures = []
                return False, (f"🔒 連續錯 {MAX_FAILURES} 次，鎖 {LOCK_MINUTES} 分鐘。如果不是你本人在試，"
                               "請立刻檢查 Telegram 的登入裝置。"), True
            reused = counter is not None
            label = "第二組（B）" if factor == FACTOR_B else ""
            return False, ("❌ 這個驗證碼已經用過了，等下一組。" if reused else f"❌ {label}驗證碼不對。"), True
        if factor == FACTOR_B:
            self._last_counter_b = counter
        else:
            self._last_counter = counter
        self._failures = []
        return True, "", False

    def _bad(self, factor: str) -> None:
        for listener in list(self._bad_code_listeners):
            try:
                listener(factor)
            except Exception:
                logging.exception("[STEPUP] bad-code listener failed")

    def elevate(self, tg_id: int, code: str) -> Tuple[bool, str]:
        """驗證碼對了就解鎖 minutes 分鐘。"""
        with self._lock:
            ok, msg, bad = self._consume_code(str(code or "").strip())
            if ok:
                self._until[tg_id] = self._clock() + self.minutes * 60
        if not ok:
            if bad:
                self._bad(FACTOR_A)
            return False, msg
        return True, f"🔓 已解鎖 {self.minutes} 分鐘。用完可以 /sudo_off 提早鎖回去。"

    def verify_once(self, code: str, factor: str = FACTOR_A) -> Tuple[bool, str]:
        """驗證一次性的碼，成功也不延長任何人的解鎖視窗。factor="B" 驗第二組驗證器（沒設定就失敗）。"""
        with self._lock:
            ok, msg, bad = self._consume_code(str(code or "").strip(), factor)
        if bad:
            self._bad(factor)
        return (True, "✅ 驗證碼正確。") if ok else (False, msg)

    def issue_ticket(self) -> str:
        """一次性、TICKET_SECONDS 秒的內部票：使用者已經當場驗過碼，程式代替他執行時用它代替驗證碼。"""
        token = TICKET_PREFIX + secrets.token_hex(16)
        now = self._clock()
        with self._lock:
            self._tickets = {t: exp for t, exp in self._tickets.items() if exp > now}
            self._tickets[token] = now + TICKET_SECONDS
        return token

    def drop(self, tg_id: int) -> bool:
        """提早鎖回去。本來就沒解鎖回 False。"""
        with self._lock:
            return self._until.pop(tg_id, None) is not None
