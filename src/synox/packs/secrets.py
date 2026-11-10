"""
pack 的 secret（pack.json 的 auth.fields[]）：使用者在 Web UI 工具頁按「連接」填，SYNOX 收進保管箱。

    "auth": {"type": "token",                                   token｜file（oauth 這一版不做）
             "fields": [{"name": "api_key", "label": "Todoist API token", "secret": true,
                         "env": "TODOIST_API_KEY"}]}

- 存哪裡：保管箱的 pack_secrets（data/pack_secrets.json.enc），裡面的鍵是 `packs/<pack>/<field>`；
  伺服器版每人一份（vault.for_user(tg_id) → data/users/<id>/pack_secrets.json.enc，別人的解不開）。
- 誰能設：只有 Web UI（走既有的登入、CSRF、Origin 檢查）。個人版只有擁有者；伺服器版每個人設自己的。
  Telegram 不收 secret（聊天紀錄會留在 Telegram 的伺服器上）。
- 誰拿得到：kind=cli → 有寫 env 的欄位放進子程序環境（JsonCli 的 keep_env 放行那個名字），**絕不放進 argv**；
  kind=python → pack.secret(name, user=None)。值永遠不回給網頁（只回「有填」與最後 4 碼）。
- 第 4 關（agent/validate.py）：AI 帶的欄位值等於（或夾著）任何一個已存的 secret ＝拒，不執行。
  「夾著」只對 8 字以上的 secret 做；短的（4–7 字）只在**它自己那個 pack 的工具**的呼叫值裡做子字串比對，
  對其他 pack 只擋完全相等（不然 4 位數 PIN 會讓所有含那串數字的一般值都被擋）。存短 secret 時網頁與
  connect 指令會警告「太短無法完整保護」（short_warning）。

哪些 pack 由 SYNOX 管（managed）：auth.type 是 token／file、有 fields，而且
  kind=cli、真的會連的 kind=mcp（stdio：放進子程序環境；http：當 Authorization: Bearer，P4b），
  或 kind=python 的原始碼有呼叫 `.secret(…)`（pack.secret）；`auth.managed` 可以明講
  "synox"（一定管）或 "pack"（pack 自己管，例如內建 connector 的 /todoist_token）。
內建的 connector（notion／todoist／google-calendar／apple-reminders）都沒有呼叫 pack.secret，所以不受影響。
"""

from __future__ import annotations

import ast
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

VAULT_NAME = "pack_secrets"
TYPES = ("token", "file")
FIELD_KINDS = ("text", "file")
MAX_VALUE = 32000          # Windows 一個環境變數最多 32767 字
_USES: Dict[tuple, bool] = {}
_USES_LOCK = threading.Lock()


class SecretError(Exception):
    """存不了／讀不了（保管箱沒開、伺服器版沒給 user…）。訊息是給人看的。"""


def key(pack: str, field: str) -> str:
    return f"packs/{pack}/{field}"


def fields_of(m) -> List[dict]:
    """auth.fields[] 整理成 [{name, label, secret, env, kind, required}]（只有 auth.type 是 token／file 才有）。"""
    auth = getattr(m, "auth_info", None) or {}
    if auth.get("type") not in TYPES:
        return []
    out = []
    for f in auth.get("fields") or []:
        if isinstance(f, str):
            f = {"name": f}
        if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not f["name"]:
            continue
        kind = f.get("kind") or ("file" if auth.get("type") == "file" else "text")
        out.append({"name": f["name"], "label": str(f.get("label") or f.get("ask") or f["name"]),
                    "secret": bool(f.get("secret", False)), "env": f.get("env") if isinstance(f.get("env"), str) else "",
                    "kind": kind if kind in FIELD_KINDS else "text", "required": f.get("required", True) is not False,
                    "help": str(f.get("help") or "")})
    return out


def _uses_pack_secret(folder: str) -> bool:
    """pack 的 .py 裡有沒有呼叫 X.secret(…)（ast，不執行）。依檔案修改時間快取。"""
    files = []
    for base, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        files += [os.path.join(base, n) for n in names if n.lower().endswith(".py")]
    try:
        stamp = (folder, tuple(sorted((p, os.path.getmtime(p)) for p in files)))
    except OSError:
        stamp = None
    if stamp is not None:
        with _USES_LOCK:
            if stamp in _USES:
                return _USES[stamp]
    found = False
    for path in files:
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "secret"
               for n in ast.walk(tree)):
            found = True
            break
    if stamp is not None:
        with _USES_LOCK:
            _USES[stamp] = found
    return found


def managed(m) -> bool:
    """這個 pack 的 auth.fields 由 SYNOX 收（工具頁有「連接」按鈕）嗎。"""
    flag = (getattr(m, "auth_info", None) or {}).get("managed")
    if flag == "pack" or not fields_of(m):
        return False
    if flag == "synox" or m.kind == "cli" or getattr(m, "mcp_connected", False):
        return True
    return m.kind == "python" and _uses_pack_secret(m.folder)


def managed_fields(m) -> List[dict]:
    return fields_of(m) if managed(m) else []


def last4(value: str) -> str:
    """給人認的最後 4 碼；太短（< 8 字）不給（不然幾乎等於整個值）。"""
    v = (value or "").strip()
    return v[-4:] if len(v) >= 8 else ""


SHORT_SECRET = 8           # 比這短的 secret：第 4 關只能擋「完全相等」（夾在別的字裡太容易誤傷一般字）
SHORT_SUBSTRING_MIN = 4    # 短 secret 在「它自己那個 pack 的呼叫值」裡也做子字串比對，但至少要這麼長
SHORT_WARNING = ("⚠️ {labels} 太短（不到 {n} 個字），SYNOX 沒辦法完整保護：AI 把它夾在別的字裡送給其他工具時認不出來。"
                 "可以的話換一組長一點的。")


def short_labels(fields: List[dict], values: Dict[str, str]) -> List[str]:
    """這次要存的 secret 裡太短的（label）：給網頁「連接」與 connect 指令警告用。"""
    by_name = {f["name"]: f for f in fields}
    out = []
    for name, value in (values or {}).items():
        f = by_name.get(name)
        if f is not None and f.get("secret") and f.get("kind") != "file" and isinstance(value, str) \
                and 0 < len(value.strip()) < SHORT_SECRET:
            out.append(f["label"])
    return out


def short_warning(labels: List[str]) -> str:
    return SHORT_WARNING.format(labels="、".join(labels), n=SHORT_SECRET) if labels else ""


def check_value(field: dict, value) -> Optional[str]:
    """網頁送來的一個值合不合；不合回一句話。"""
    if not isinstance(value, str):
        return f"{field['label']} 要是文字"
    if len(value) > MAX_VALUE:
        return f"{field['label']} 太長了（最多 {MAX_VALUE} 字）"
    if "\x00" in value:
        return f"{field['label']} 不能有 NUL 字元"
    if field["kind"] == "text" and any(c in value for c in "\r\n"):
        return f"{field['label']} 不能換行（要貼一整個檔案，作者要把欄位寫成 kind=file）"
    return None


class PackSecrets:
    """全部 pack 的 secret。vault=None（保管箱沒開）時什麼都存不了、也讀不到。

    server=True（伺服器版）：一定要給 user（有 tg_id 的物件或 int），每個人一份；False：大家共用一份。"""

    def __init__(self, vault, server: bool = False):
        self.vault = vault
        self.server = server
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return self.vault is not None

    def _vault_for(self, user):
        if self.vault is None:
            raise SecretError("保管箱沒有打開，secret 沒地方放。")
        if not self.server:
            return self.vault
        tg_id = user if isinstance(user, int) and not isinstance(user, bool) else getattr(user, "tg_id", None)
        if not isinstance(tg_id, int) or isinstance(tg_id, bool):
            raise SecretError("伺服器版的 secret 每人一份：要給 user（pack.secret(name, user)）。")
        return self.vault.for_user(tg_id)

    def _load(self, user) -> Dict[str, dict]:
        data = self._vault_for(user).load_json(VAULT_NAME, {}) or {}
        return data if isinstance(data, dict) else {}

    def get(self, pack: str, field: str, user=None) -> Optional[str]:
        entry = self._load(user).get(key(pack, field))
        return entry.get("value") if isinstance(entry, dict) else None

    def update(self, pack: str, fields: List[dict], values: Dict[str, str], user=None,
               clear=()) -> List[str]:
        """values：{欄位: 值}，空字串＝沿用原值；clear：要刪掉的欄位。先全部檢查過才寫。
        回這次存的 secret 裡太短（< SHORT_SECRET 字）的 label（呼叫的人照 short_warning 提醒；照樣存）。"""
        by_name = {f["name"]: f for f in fields}
        for name in list(values) + list(clear):
            if name not in by_name:
                raise SecretError(f"{pack} 沒有宣告欄位 {name}")
        for name, value in values.items():
            problem = check_value(by_name[name], value)
            if problem:
                raise SecretError(problem)
        vault = self._vault_for(user)
        with self._lock:
            data = vault.load_json(VAULT_NAME, {}) or {}
            for name in clear:
                data.pop(key(pack, name), None)
            for name, value in values.items():
                if by_name[name]["kind"] == "text":
                    value = value.strip()
                if value == "":
                    continue
                data[key(pack, name)] = {"value": value, "secret": by_name[name]["secret"], "saved": int(time.time())}
            vault.save_json(VAULT_NAME, data)
        return short_labels(fields, values)

    def status(self, pack: str, fields: List[dict], user=None) -> List[dict]:
        """給網頁看的：每個欄位「有填」、最後 4 碼（secret 永遠不回值；不是 secret 的回值）。"""
        data = self._load(user)
        out = []
        for f in fields:
            entry = data.get(key(pack, f["name"]))
            value = entry.get("value", "") if isinstance(entry, dict) else ""
            row = {"name": f["name"], "label": f["label"], "secret": f["secret"], "kind": f["kind"],
                   "required": f["required"], "help": f["help"], "set": bool(value)}
            if value and f["kind"] == "file":
                row["size"] = len(value)
            elif value and f["secret"]:
                row["last4"] = last4(value)
            elif value:
                row["value"] = value
            out.append(row)
        return out

    def missing(self, pack: str, fields: List[dict], user=None) -> List[str]:
        """還沒填的必填欄位（label）。保管箱沒開＝全部都算缺。"""
        try:
            data = self._load(user)
        except SecretError:
            data = {}
        except Exception:                        # 保管箱解不開（VaultError）：當作沒填，doctor 會另外報
            logging.exception("[SECRETS] could not read pack secrets for %s", pack)
            data = {}
        return [f["label"] for f in fields if f["required"] and not
                (isinstance(data.get(key(pack, f["name"])), dict) and data[key(pack, f["name"])].get("value"))]

    def env_for(self, pack: str, fields: List[dict], user=None) -> Dict[str, str]:
        """kind=cli 子程序要的環境變數：只有寫了 env 的欄位。"""
        wanted = [f for f in fields if f.get("env")]
        if not wanted:
            return {}
        data = self._load(user)
        out = {}
        for f in wanted:
            entry = data.get(key(pack, f["name"]))
            if isinstance(entry, dict) and entry.get("value"):
                out[f["env"]] = entry["value"]
        return out

    def secret_values(self, user=None, pack: Optional[str] = None) -> List[str]:
        """這個人存的全部 secret 值（第 4 關比對用；不是 secret 的欄位不算）。讀不到回 []。
        pack：只要這個 pack 的（短 secret 的子字串比對只對它自己的呼叫做）。"""
        if self.vault is None:
            return []
        try:
            data = self._load(user)
        except SecretError:
            return []
        except Exception:
            logging.exception("[SECRETS] could not read pack secrets for the gate-4 check")
            return []
        prefix = key(pack, "") if pack else ""
        return [e["value"] for k, e in data.items()
                if (not prefix or str(k).startswith(prefix))
                and isinstance(e, dict) and e.get("secret") and isinstance(e.get("value"), str) and e["value"].strip()]


def of(app) -> Optional[PackSecrets]:
    return (getattr(app, "extras", {}) or {}).get("synox_pack_secrets")


def leaks(value: str, secrets: List[str], own: Optional[List[str]] = None) -> bool:
    """AI 帶的值是不是已存的 secret：一樣，或 8 字以上的 secret 夾在裡面。
    own：這個工具「自己那個 pack」的 secret——短的（4–7 字）也做子字串比對（只對自己的 pack 做，
    不然 4 位數 PIN 之類會把所有含那串數字的一般值都擋掉）。"""
    v = (value or "").strip()
    if not v:
        return False
    for s in secrets:
        s = s.strip()
        if v == s or (len(s) >= SHORT_SECRET and s in v):
            return True
    for s in own or ():
        s = s.strip()
        if len(s) >= SHORT_SUBSTRING_MIN and s in v:
            return True
    return False
