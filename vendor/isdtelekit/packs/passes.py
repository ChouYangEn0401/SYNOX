"""
通行證：管理員發一組碼，拿到碼的人打 /join <碼>（或點 t.me/<bot>?start=<碼>）就升到那個角色。
範本 B（服務操作台）用它當「誰能進來用這個服務」的門：不用一個一個 /user_role，把碼給朋友就好。

    /pass_new [角色] [uses=1] [days=7] [note=給誰的]   發一組碼（表單指令：一次打齊，或一題一題問）
    /pass_list                                       還有效的通行證（不會再顯示碼，只有 id）
    /pass_revoke <id>                                作廢
    /join <碼>                                       用碼（任何人；深連結 /start <碼> 也是它）

安全上的決定：
- 碼是 8 個字（去掉 0/O/1/I 這種會看錯的），約 40 bit；**只存 SHA-256**，passes.json 外流也拿不到能用的碼。
  碼只在發的那一刻顯示一次。
- 只能發比自己低的角色（擁有者例外，什麼都能發）：管理員不能發一張「管理員通行證」給自己的分身。
- 猜碼：同一個人 10 分鐘內錯 5 次就鎖 30 分鐘（另外每則 /join 照樣吃每日訊息配額）。
- 已經是那個角色（或更高）的人用碼不會扣次數。用掉時通知發碼的人。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from isdtelekit.core.jsonstore import load_json, save_json
from isdtelekit.core.registry import DANGER, WRITE, Field, parse_fields
from isdtelekit.packs._util import parse_id, role_name, tell
from isdtelekit.packs.basics import add_start_handler
from isdtelekit.users.roles import by_name, choices

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
MAX_FAILURES, FAILURE_WINDOW, LOCK_SECONDS = 5, 600, 1800


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


class PassStore:
    """data/passes.json：[{id, hash, role, uses_left（None＝不限）, expires（epoch，None＝不過期）, note,
    created_by, created_at, redeemed_by: [id…]}]。讀改寫在一把鎖裡。"""

    def __init__(self, path: str, clock=time.time):
        self.path = path
        self._clock = clock
        self._lock = threading.Lock()
        raw = load_json(path, [])
        self._passes: List[dict] = [p for p in raw if isinstance(p, dict) and "hash" in p] if isinstance(raw, list) else []

    def create(self, role: int, *, uses: Optional[int], days: Optional[float], note: str, created_by: int) -> tuple:
        """回傳 (碼, 那一筆)。碼只在這裡出現一次。"""
        code = new_code()
        now = self._clock()
        entry = {"id": "p" + secrets.token_hex(3), "hash": _hash(code), "role": int(role),
                 "uses_left": uses if uses else None, "expires": now + days * 86400 if days else None,
                 "note": note, "created_by": created_by, "created_at": now, "redeemed_by": []}
        with self._lock:
            self._passes.append(entry)
            self._save()
        return code, dict(entry)

    def active(self) -> List[dict]:
        now = self._clock()
        with self._lock:
            return [dict(p) for p in self._passes if self._usable(p, now)]

    def revoke(self, pass_id: str) -> bool:
        with self._lock:
            before = len(self._passes)
            self._passes = [p for p in self._passes if p["id"] != pass_id]
            if len(self._passes) == before:
                return False
            self._save()
            return True

    def find(self, code: str) -> Optional[dict]:
        """碼對得上、還能用的那一筆（不扣次數）。"""
        digest = _hash(code)
        now = self._clock()
        with self._lock:
            for p in self._passes:
                if hmac.compare_digest(p["hash"], digest) and self._usable(p, now):
                    return dict(p)
        return None

    def redeem(self, pass_id: str, user_id: int) -> Optional[dict]:
        """扣一次、記下誰用的；用完的留著（/pass_list 不再列出），回傳更新後的那一筆。"""
        now = self._clock()
        with self._lock:
            for p in self._passes:
                if p["id"] == pass_id and self._usable(p, now):
                    if p["uses_left"] is not None:
                        p["uses_left"] -= 1
                    p["redeemed_by"].append(user_id)
                    self._save()
                    return dict(p)
        return None

    @staticmethod
    def _usable(p: dict, now: float) -> bool:
        return (p.get("uses_left") is None or p["uses_left"] > 0) and (p.get("expires") is None or p["expires"] > now)

    def _save(self) -> None:
        save_json(self.path, self._passes)


def install(app, *, group: str = "pass", issuer_role: Optional[int] = None, default_role: Optional[int] = None,
            bot_username: Optional[str] = None) -> PassStore:
    """issuer_role：誰能發／列出／作廢（預設最高一級）；default_role：沒寫角色時發哪一級（預設最低的上一級）。
    bot_username：組 t.me 深連結用（沒給就看 config 的 bot_username；都沒有就只顯示 /join <碼>）。"""
    registry, users = app.registry, app.users
    roles = users.roles
    ladder = sorted(set(roles))
    issuer_role = users.top_role if issuer_role is None else issuer_role
    default_role = (ladder[1] if len(ladder) > 1 else ladder[0]) if default_role is None else default_role
    store = PassStore(app.config.path("passes.json"))
    app.extras["passes"] = store
    failures: Dict[int, List[float]] = {}
    locked: Dict[int, float] = {}
    registry.ensure_group(group, "🎫 通行證", "發通行證給朋友：拿到碼的人用 /join 進來", role=issuer_role)

    def username() -> str:
        return bot_username or app.config.get("bot_username") or app.extras.get("bot_username") or ""

    # ── 發碼 ─────────────────────────────────────────────────────────

    def check_role(value: str) -> Optional[str]:
        return None if by_name(roles, value) is not None else f"角色只能是 {choices(roles)}"

    def check_count(value: str) -> Optional[str]:
        number = parse_id(value)
        return None if number is not None and number >= 0 else "要是 0 以上的整數（0＝不限）"

    def submit(api, chat_id, user, values):
        role = by_name(roles, values["role"])
        if not registry.is_owner(user) and role >= user.role:
            api.send_message(chat_id, f"❌ 只能發比自己低的角色（你是 {role_name(user.role)}）。")
            return
        uses, days = int(values["uses"]), int(values["days"])
        code, entry = store.create(role, uses=uses, days=days, note=values.get("note", ""), created_by=user.tg_id)
        link = f"\n連結：https://t.me/{username()}?start={code}" if username() else ""
        limits = (f"可以用 {uses} 次" if uses else "次數不限") + "，" + (
            f"{datetime.fromtimestamp(entry['expires']):%m/%d %H:%M} 前有效" if days else "不會過期")
        api.send_message(chat_id, f"🎫 通行證已建立（id {entry['id']}）\n碼：{code}{link}\n"
                                  f"拿到的人打 /join {code}\n給：{role_name(role)}，{limits}。\n"
                                  "⚠️ 碼只顯示這一次，之後 /pass_list 只看得到 id。")

    node = app.forms.leaf(registry.group(group), "new", submit, "發一組通行證碼", effect=WRITE, fields=[
        Field("role", "給什麼角色", default=role_name(default_role).lower(), check=check_role),
        Field("uses", "可以用幾次（0＝不限）", default="1", check=check_count),
        Field("days", "幾天內有效（0＝不過期）", default="7", check=check_count),
        Field("note", "備註（給誰的）"),
    ])
    form = node.fn

    def guarded(api, chat_id, user, args):
        """打字時已經寫了角色，就先擋「發比自己高的」——不要問完選填欄位才說不行（問答中才填的由 submit 擋）。"""
        values, _missing, _errors = parse_fields(node.fields, " ".join(args))
        role = by_name(roles, values.get("role", ""))
        if role is not None and not registry.is_owner(user) and role >= user.role:
            api.send_message(chat_id, f"❌ 只能發比自己低的角色（你是 {role_name(user.role)}）。")
            return
        form(api, chat_id, user, args)

    node.fn = guarded

    def cmd_list(api, chat_id, user, args):
        rows = store.active()
        if not rows:
            api.send_message(chat_id, f"目前沒有有效的通行證。發一組：/{group}_new")
            return
        lines = ["🎫 有效的通行證（碼只在發的時候顯示過）"]
        for p in rows:
            left = "不限" if p["uses_left"] is None else f"剩 {p['uses_left']} 次"
            until = f"到 {datetime.fromtimestamp(p['expires']):%m/%d %H:%M}" if p["expires"] else "不過期"
            note = f"  {p['note']}" if p.get("note") else ""
            lines.append(f"  {p['id']}  {role_name(roles(p['role']))}  {left}  {until}  已用 {len(p['redeemed_by'])}{note}")
        lines.append(f"\n作廢：/{group}_revoke <id>")
        api.send_message(chat_id, "\n".join(lines))

    def cmd_revoke(api, chat_id, user, args):
        if not args:
            api.send_message(chat_id, f"用法：/{group}_revoke <id>（id 看 /{group}_list）")
            return
        api.send_message(chat_id, f"✅ 已作廢 {args[0]}。" if store.revoke(args[0]) else f"❌ 沒有這張通行證：{args[0]}")

    g = registry.group(group)
    g.leaf("list", cmd_list, "列出還有效的通行證")
    g.leaf("revoke", cmd_revoke, "作廢一張通行證", usage="<id>", effect=DANGER)

    # ── 用碼 ─────────────────────────────────────────────────────────

    def redeem(api, chat_id, user, code: str) -> None:
        now = time.time()
        if locked.get(user.tg_id, 0) > now:
            api.send_message(chat_id, f"🔒 錯太多次了，{int((locked[user.tg_id] - now) // 60) + 1} 分鐘後再試。")
            return
        found = store.find(code)
        if found is None:
            recent = [t for t in failures.get(user.tg_id, []) if now - t < FAILURE_WINDOW] + [now]
            failures[user.tg_id] = recent
            if len(recent) >= MAX_FAILURES:
                locked[user.tg_id] = now + LOCK_SECONDS
                failures.pop(user.tg_id, None)
            api.send_message(chat_id, "❌ 這組碼不對、已經用完、或過期了。")
            return
        failures.pop(user.tg_id, None)
        role = roles(found["role"])
        if user.role >= role:
            api.send_message(chat_id, f"ℹ️ 你已經是 {role_name(user.role)} 了，這組碼不用用（沒有扣次數）。")
            return
        entry = store.redeem(found["id"], user.tg_id)
        if entry is None:
            api.send_message(chat_id, "❌ 這組碼剛剛被用完了。")
            return
        users.set_role(user.tg_id, role, actor_id=found["created_by"])
        api.send_message(chat_id, f"🎉 歡迎！你現在是 {role_name(role)}。輸入 /help 看看能做什麼。")
        left = "不限" if entry["uses_left"] is None else f"剩 {entry['uses_left']} 次"
        tell(api, found["created_by"], f"🎫 @{user.username or user.tg_id}（{user.tg_id}）用了通行證 {found['id']}，"
                                       f"現在是 {role_name(role)}（{left}）。")

    def cmd_join(api, chat_id, user, args):
        if not args:
            api.send_message(chat_id, "用法：/join <通行證碼>（跟管理員拿）")
            return
        redeem(api, chat_id, user, args[0])

    def on_start(api, chat_id, user, args) -> bool:
        code = args[0].strip().upper()
        if len(code) != CODE_LENGTH or any(ch not in ALPHABET for ch in code):
            return False
        redeem(api, chat_id, user, code)
        return True

    registry.root_leaf("join", cmd_join, "用通行證碼加入", usage="<碼>", effect=WRITE, private_only=True)
    add_start_handler(app, on_start)
    return store
