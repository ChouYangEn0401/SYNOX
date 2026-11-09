"""
保管箱：pack 的資料落地就是密文（spec §6）。

    vault = Vault(master_key, data_dir)          # master_key：32 bytes 隨機（keyring.py 管）
    vault.save_json("money", {"entries": []})    # → data/money.json.enc
    vault.load_json("money", default={})

檔案格式（兩行，UTF-8）：
    第 1 行  header JSON：{"synox_vault": 1, "kdf": "scrypt", "n": 16384, "r": 8, "p": 1, "salt": "<b64>"}
    第 2 行  Fernet token（AES-128-CBC + HMAC-SHA256，cryptography 套件）

每次存檔換一個新 salt；檔案金鑰 = scrypt(master_key, salt)。header 被改、密文被改、金鑰不對，
一律丟 VaultError——**不會**默默當成空的再蓋過去（那會把使用者的資料洗掉）。
寫入是暫存檔 + os.replace（跟 SDK 的 jsonstore 同一套），寫到一半被砍掉時舊檔仍完整。

伺服器版（config mode=server）每個人一個保管箱：vault.for_user(tg_id) → 資料夾 data/users/<tg_id>/，
主金鑰換成 HKDF-SHA256(master_key, salt="synox-user-v1", info="user:<tg_id>")。A 的保管箱解不開 B 的檔
（金鑰不同 → VaultError）；但跑著的程式拿得到主金鑰，所以**營運者仍然讀得到**（見 docs/security.md）。
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT = 1
SUFFIX = ".json.enc"
KDF_PARAMS = {"n": 2 ** 14, "r": 8, "p": 1}
_REPLACE_RETRIES = 5
USER_SALT = b"synox-user-v1"
USERS_DIR = "users"


class VaultError(Exception):
    """解不開（金鑰不對、檔案被改過、格式不對）。訊息是給人看的。"""


def user_key(master_key: bytes, tg_id: int) -> bytes:
    """一個使用者的主金鑰：HKDF-SHA256(master_key, salt=USER_SALT, info="user:<tg_id>")，32 bytes。"""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=USER_SALT,
                info=f"user:{int(tg_id)}".encode("ascii")).derive(master_key)


def _derive(master_key: bytes, salt: bytes, n: int, r: int, p: int) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=n, r=r, p=p)
    return base64.urlsafe_b64encode(kdf.derive(master_key))


class Vault:

    def __init__(self, master_key: bytes, data_dir: str):
        if not isinstance(master_key, (bytes, bytearray)) or len(master_key) < 32:
            raise ValueError("vault master key must be at least 32 bytes")
        self._key = bytes(master_key)
        self.data_dir = data_dir
        self._cache: Dict[tuple, bytes] = {}
        self._lock = threading.RLock()
        self._users: Dict[int, "Vault"] = {}

    def for_user(self, tg_id: int) -> "Vault":
        """這個人自己的保管箱（data/users/<tg_id>/，金鑰由主金鑰＋id 用 HKDF 衍生）。同一個人回同一個物件。"""
        if isinstance(tg_id, bool) or not isinstance(tg_id, int):
            raise ValueError(f"tg_id must be an int, got {tg_id!r}")
        with self._lock:
            found = self._users.get(tg_id)
            if found is None:
                folder = os.path.join(self.data_dir, USERS_DIR, str(tg_id))
                found = self._users[tg_id] = Vault(user_key(self._key, tg_id), folder)
            return found

    # ── 路徑 ─────────────────────────────────────────────────────────

    def path(self, name: str) -> str:
        if not name or any(c in name for c in "/\\:") or name.startswith("."):
            raise ValueError(f"bad vault name {name!r}")
        return os.path.join(self.data_dir, name + SUFFIX)

    def exists(self, name: str) -> bool:
        return os.path.exists(self.path(name))

    # ── 加解密 ───────────────────────────────────────────────────────

    def _fernet(self, salt: bytes, n: int, r: int, p: int) -> Fernet:
        cache_key = (salt, n, r, p)
        with self._lock:
            key = self._cache.get(cache_key)
            if key is None:
                key = self._cache[cache_key] = _derive(self._key, salt, n, r, p)
        return Fernet(key)

    def encrypt(self, data: Any) -> bytes:
        salt = os.urandom(16)
        header = {"synox_vault": FORMAT, "kdf": "scrypt", **KDF_PARAMS,
                  "salt": base64.b64encode(salt).decode("ascii"), "saved": int(time.time())}
        plain = json.dumps(data, ensure_ascii=False).encode("utf-8")
        token = self._fernet(salt, **KDF_PARAMS).encrypt(plain)
        return json.dumps(header).encode("ascii") + b"\n" + token + b"\n"

    def decrypt(self, blob: bytes, where: str = "保管箱檔案") -> Any:
        try:
            head, token = blob.strip().split(b"\n", 1)
            header = json.loads(head.decode("ascii"))
            if header.get("synox_vault") != FORMAT or header.get("kdf") != "scrypt":
                raise ValueError("unknown format")
            salt = base64.b64decode(header["salt"])
            n, r, p = int(header["n"]), int(header["r"]), int(header["p"])
            if n > 2 ** 20 or r > 32 or p > 16:
                raise ValueError("kdf parameters out of range")
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
            raise VaultError(f"{where} 的格式不對（{e}），可能被改過或不是 SYNOX 的檔案。")
        try:
            plain = self._fernet(salt, n, r, p).decrypt(token.strip())
        except InvalidToken:
            raise VaultError(f"{where} 解不開：金鑰不對（換了電腦或 Windows 帳號？）或檔案被改過。")
        return json.loads(plain.decode("utf-8"))

    # ── 檔案 ─────────────────────────────────────────────────────────

    def load_json(self, name: str, default: Any = None) -> Any:
        path = self.path(name)
        if not os.path.exists(path):
            return default
        with open(path, "rb") as f:
            blob = f.read()
        return self.decrypt(blob, where=os.path.basename(path))

    def save_json(self, name: str, data: Any) -> None:
        path = self.path(name)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        blob = self.encrypt(data)
        tmp = f"{path}.{os.getpid()}-{threading.get_ident()}.tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    os.remove(tmp)
                    raise
                time.sleep(0.05 * (attempt + 1))

    # ── 小工具 ───────────────────────────────────────────────────────

    def secret(self, name: str) -> Optional[str]:
        """data/secrets.json.enc 裡的一個值（精靈存的 LLM 金鑰）。"""
        return (self.load_json("secrets", {}) or {}).get(name)

    def set_secret(self, name: str, value: str) -> None:
        with self._lock:
            secrets = self.load_json("secrets", {}) or {}
            secrets[name] = value
            self.save_json("secrets", secrets)
