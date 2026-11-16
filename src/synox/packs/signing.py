"""
工具（.synoxpack）的簽章與「官方」標章（docs/adr/0027 §1–3）。

每個 .synoxpack 可以自帶一個 `pack.sig.json`（跟 pack.json 並排）：列出其他每個檔的路徑＋sha256，再用 Ed25519 簽這份清單。

    {"version": 1, "algorithm": "ed25519", "key_id": "<16 個十六進位字>", "public_key": "<base64，44 字>",
     "files": {"pack.json": "<sha256>", …}, "signature": "<base64，64 位元組>"}

- 簽的位元組＝canonical_bytes(前五個欄位)：json.dumps(sort_keys, 沒有空白, ensure_ascii) 的 UTF-8。
- files＝去掉唯一的最上層資料夾之後，除了 pack.sig.json 本身、__pycache__/ 底下的檔以外的**每一個檔**（"/" 接）。
- 驗（verify_folder，admin.stage 解完壓縮、跑第 1 關之前）：對**磁碟上**解出來的檔算 sha256，清單要完全一樣，
  用檔裡的 public_key 驗；鑰匙在 OFFICIAL_PACK_PUBLIC_KEYS＝official，不在＝author；沒有簽章檔＝none；
  其他任何一步不過＝invalid（拒裝，沒有確認鈕）。
- 標章只看這裡驗出來的結果；工具自己寫的名字、說明一律不算（lookalike_problems 把「官方」「SYNOX」「✅」這類字標紅）。
- 私鑰只在作者／擁有者手上（synox-sdk keygen 產生、用密語加密）；這個檔只有公鑰。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

# ── 官方鑰匙 ───────────────────────────────────────────────────────────
# 擁有者產生官方工具鑰匙之後（`synox-sdk keygen --out <repo 以外的路徑>\synox-packs.pem`），把它印出的
# `public_key` 那一行（32 位元組公鑰的 base64，44 個字，結尾是 =）貼在這裡，隨下一版發出去。
# 可以同時放兩把（現用＋備用，換鑰匙時並存）；寫壞的那一項不算。這是發「工具」的鑰匙，
# 跟發 SYNOX 本體的 src/synox/update/signing.py RELEASE_PUBLIC_KEYS 是兩組，不要混用。
# 例：OFFICIAL_PACK_PUBLIC_KEYS: Sequence[str] = ("AAAA…=",)
OFFICIAL_PACK_PUBLIC_KEYS: Sequence[str] = ()

SIG_FILE = "pack.sig.json"
SIG_VERSION = 1
ALGORITHM = "ed25519"
MAX_SIG_FILE = 1024 * 1024                 # pack.sig.json 最大 1 MB（300 個檔的清單遠小於這個）
KEY_PASSWORD_ENV = "SYNOX_PACK_KEY_PASSWORD"
RELEASE_KEY_PASSWORD_ENV = "SYNOX_RELEASE_KEY_PASSWORD"

OFFICIAL, AUTHOR, NONE, INVALID = "official", "author", "none", "invalid"
STATUSES = (OFFICIAL, AUTHOR, NONE, INVALID)
LABELS = {OFFICIAL: "✅ 官方", AUTHOR: "✍️ 作者簽章", NONE: "⚠️ 不是官方", INVALID: "⛔ 被改過"}
TEXTS = {
    OFFICIAL: "SYNOX 驗過擁有者的簽章：這個檔是官方發的，而且沒有被改過。",
    AUTHOR: "作者自己簽的，不是官方。SYNOX 只能確認「檔案跟作者簽的時候一樣」，不能確認作者是誰。",
    NONE: "沒有簽章：SYNOX 無法確認是誰做的、有沒有被改過。只裝你信得過的人給的。",
    INVALID: "這個工具有簽章，但檔案跟簽章對不上——簽章之後有人改過它，或是檔案在傳輸中壞掉。不能裝。"
             "請重新下載一次，或向給你這個檔的人要一份新的。",
}
NO_OFFICIAL_KEYS_TEXT = "（這一版 SYNOX 還沒有官方鑰匙，所以暫時沒有工具會顯示官方）"
INVALID_MESSAGE = ("⛔ 被改過：這個工具有簽章，但檔案跟簽章對不上——簽章之後有人改過它，或是檔案在傳輸中壞掉。不能裝。"
                   "請重新下載一次，或向給你這個檔的人要一份新的。")
SAFETY_NOTICE = ("安全提醒：公開流通的工具裡，有一些帶著會偷資料或做壞事的程式。不管來源是哪裡，裝之前請看完這份報告；"
                 "不確定就不要裝。")

_SIG_KEYS = ("algorithm", "files", "key_id", "public_key", "signature", "version")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[0-9a-f]{16}$")
# 看不見的字元（look-alike 比對前拿掉）：零寬、雙向文字控制、BOM、軟連字號、word joiner
_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁤⁦-⁩﻿]")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class SigningError(ValueError):
    """給人看的錯誤（私鑰、簽章檔、zip）。"""


@dataclass
class SignatureResult:
    status: str
    key_id: str = ""
    public_key: str = ""
    reason: str = ""                       # 為什麼是這個結果（給 synox-sdk verify、log；白話）
    label: str = ""
    text: str = ""
    no_official_keys: bool = False

    def lock_block(self) -> dict:
        """寫進 packs.lock 的那一塊：{"status", "key_id", "public_key"}（none／invalid 只有 status）。"""
        if self.status in (OFFICIAL, AUTHOR):
            return {"status": self.status, "key_id": self.key_id, "public_key": self.public_key}
        return {"status": self.status}


# ── 零件 ───────────────────────────────────────────────────────────────

def key_id(raw_pubkey: bytes) -> str:
    """sha256(32 位元組原始公鑰) 十六進位的前 16 字。"""
    return hashlib.sha256(bytes(raw_pubkey)).hexdigest()[:16]


def canonical_bytes(payload: dict) -> bytes:
    """簽的位元組：algorithm、files、key_id、public_key、version 這五個欄位（不含 signature），排序、沒有空白、全 ASCII。"""
    body = {k: payload[k] for k in ("algorithm", "files", "key_id", "public_key", "version")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def official_raw_keys(keys: Optional[Iterable[str]] = None) -> List[bytes]:
    """可以用的官方公鑰（32 位元組）；寫壞的那一項不算。keys=None＝OFFICIAL_PACK_PUBLIC_KEYS（呼叫時才讀）。"""
    from synox.update.signing import public_keys
    return public_keys(OFFICIAL_PACK_PUBLIC_KEYS if keys is None else keys)


def _counted(parts: List[str]) -> bool:
    """這個檔算不算進簽章清單：pack.sig.json 本身、__pycache__ 底下的不算。"""
    return parts != [SIG_FILE] and "__pycache__" not in parts[:-1]


def hash_folder(folder: str) -> Dict[str, str]:
    """解開的 pack 資料夾 → {相對路徑（/ 接）: sha256}：除了 pack.sig.json、__pycache__ 底下以外的每一個檔。"""
    from synox.packs.lock import sha256_file
    from synox.packs.scan import pack_files
    return {rel: sha256_file(os.path.join(folder, *rel.split("/")))
            for rel in pack_files(folder, include_cache=True) if _counted(rel.split("/"))}


def _b64(value, size: int) -> Optional[bytes]:
    if not isinstance(value, str):
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == size else None


def _result(status: str, reason: str, no_keys: bool, kid: str = "", pub: str = "") -> SignatureResult:
    return SignatureResult(status=status, key_id=kid, public_key=pub, reason=reason, label=LABELS[status],
                           text=TEXTS[status], no_official_keys=no_keys)


def verify_folder(folder: str, official_keys: Optional[Iterable[str]] = None) -> SignatureResult:
    """解開的 pack 資料夾 → SignatureResult（official｜author｜none｜invalid）。對**磁碟上**的檔算；不丟例外。
    official_keys：None＝OFFICIAL_PACK_PUBLIC_KEYS（呼叫時才讀，測試可以 monkeypatch）。"""
    trusted = official_raw_keys(official_keys)
    no_keys = not trusted
    path = os.path.join(folder, SIG_FILE)
    if not os.path.lexists(path):
        return _result(NONE, "沒有簽章檔（pack.sig.json）", no_keys)

    def bad(why: str) -> SignatureResult:
        return _result(INVALID, why, no_keys)

    if os.path.islink(path) or not os.path.isfile(path):
        return bad("pack.sig.json 不是一般的檔案")
    try:
        if os.path.getsize(path) > MAX_SIG_FILE:
            return bad("pack.sig.json 太大")
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return bad("pack.sig.json 看不懂（不是 UTF-8 的 JSON）")
    if not isinstance(data, dict) or sorted(data) != sorted(_SIG_KEYS):
        return bad("pack.sig.json 的欄位不對（要剛好有 version、algorithm、key_id、public_key、files、signature）")
    if type(data["version"]) is not int or data["version"] != SIG_VERSION:
        return bad(f"pack.sig.json 的 version 不是 {SIG_VERSION}（這一版 SYNOX 看不懂）")
    if data["algorithm"] != ALGORITHM:
        return bad("pack.sig.json 的 algorithm 不是 ed25519")
    pub = _b64(data["public_key"], 32)
    if pub is None:
        return bad("pack.sig.json 的 public_key 不是 32 位元組的 base64")
    sig = _b64(data["signature"], 64)
    if sig is None:
        return bad("pack.sig.json 的 signature 不是 64 位元組的 base64")
    kid = data["key_id"]
    if not isinstance(kid, str) or not _KEY_ID.match(kid) or kid != key_id(pub):
        return bad("pack.sig.json 的 key_id 跟 public_key 對不上")
    files = data["files"]
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) and _HEX64.match(v)
                                              for k, v in files.items()):
        return bad("pack.sig.json 的 files 格式不對（要是 {路徑: sha256}）")
    try:
        actual = hash_folder(folder)
    except OSError as e:
        return bad(f"讀不了解開的檔案（{e.strerror or type(e).__name__}）")
    if files != actual:
        from synox.packs.lock import diff
        return bad("檔案跟簽章的清單對不上：" + "、".join(diff(files, actual)[:10]))
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, canonical_bytes(data))
    except (InvalidSignature, ValueError):
        return bad("簽章驗不過（清單被改過，或不是這把鑰匙簽的）")
    pub_b64 = base64.b64encode(pub).decode("ascii")
    if pub in trusted:
        return _result(OFFICIAL, "官方鑰匙驗過", no_keys, kid, pub_b64)
    return _result(AUTHOR, "作者的鑰匙驗過（不是官方鑰匙）", no_keys, kid, pub_b64)


# ── 簽、驗 .synoxpack ──────────────────────────────────────────────────

def _read_pack_zip(path: str) -> bytes:
    from synox.packs import admin
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise SigningError(f"讀不到 {path}：{e.strerror or e}")
    if size > admin.MAX_UPLOAD:
        raise SigningError("檔案太大（最多 5 MB，SYNOX 也裝不了更大的）")
    with open(path, "rb") as f:
        blob = f.read()
    if not blob.startswith(admin.ZIP_MAGIC):
        raise SigningError("不是 .synoxpack（要是 pack 資料夾壓成的 zip；先用 synox-sdk zip 打包）")
    return blob


def _open_zip(blob: bytes):
    import io
    import zipfile
    try:
        return zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise SigningError("不是 .synoxpack（zip 打不開；先用 synox-sdk zip 重新打包）")


def sign_zip(path: str, private_key, out: Optional[str] = None) -> str:
    """.synoxpack → 加上 pack.sig.json 的新 zip（原檔覆寫；out 另存）。回 key_id。
    zip 先過跟安裝一樣的檢查（admin._members／_strip_root：路徑、連結、重複、大小寫相撞…）；簽的是 zip 裡的每個檔
    （去掉最上層資料夾之後；不含 __pycache__ 與舊的 pack.sig.json）。寫完自己再驗一次。"""
    import zipfile
    from cryptography.hazmat.primitives import serialization
    from synox.packs import admin
    blob = _read_pack_zip(path)
    z = _open_zip(blob)
    with z:
        members = admin._members(z)
        files = admin._strip_root(members)
        original = {id(i): p for i, p in members}
        first, first_parts = files[0]
        prefix = original[id(first)][0] + "/" if len(original[id(first)]) != len(first_parts) else ""
        hashes: Dict[str, str] = {}
        budget = [admin.MAX_UNZIPPED]
        for info, parts in files:
            if not _counted(parts):
                continue
            h = hashlib.sha256()
            admin._copy_member(z, info, parts, h.update, budget)
            hashes["/".join(parts)] = h.hexdigest()
        raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        payload = {"version": SIG_VERSION, "algorithm": ALGORITHM, "key_id": key_id(raw),
                   "public_key": base64.b64encode(raw).decode("ascii"), "files": dict(sorted(hashes.items()))}
        payload["signature"] = base64.b64encode(private_key.sign(canonical_bytes(payload))).decode("ascii")
        old_sig = {id(info) for info, parts in files if parts == [SIG_FILE]}
        target = os.path.abspath(out or path)
        fd, tmp = tempfile.mkstemp(prefix=".synoxpack-", suffix=".tmp", dir=os.path.dirname(target) or ".")
        try:
            with os.fdopen(fd, "wb") as f, zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in z.infolist():
                    if id(info) in old_sig:
                        continue
                    zout.writestr(info, z.read(info))
                zout.writestr(prefix + SIG_FILE, json.dumps(payload, ensure_ascii=True, indent=2) + "\n")
            check = verify_zip(tmp)                  # 自己先驗一次（寫壞了不蓋原檔）
            if check.status not in (OFFICIAL, AUTHOR):
                raise SigningError(f"簽好之後自己驗不過（{check.reason}）：原檔沒有改")
            os.replace(tmp, target)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    return payload["key_id"]


def verify_zip(path: str, official_keys: Optional[Iterable[str]] = None) -> SignatureResult:
    """.synoxpack → SignatureResult：跟安裝一樣解到暫存資料夾（同一套 zip 檢查）再 verify_folder。
    zip 本身不合丟 PackAdminError／SigningError（都是 ValueError）。"""
    from synox.packs import admin
    blob = _read_pack_zip(path)
    z = _open_zip(blob)
    with z, tempfile.TemporaryDirectory(prefix="synox-verify-") as tmp:
        files = admin._strip_root(admin._members(z))
        files = [(i, p) for i, p in files if "__pycache__" not in p[:-1]]
        folder = os.path.join(tmp, "pack")
        os.makedirs(folder)
        admin._extract(z, files, folder)
        return verify_folder(folder, official_keys=official_keys)


# ── 看起來像官方（只標紅、不拒裝；ADR 0027 §9 第 1 點） ─────────────────

LOOKALIKE_WORDS = (("官方", "官方"), ("official", "official"), ("synox", "SYNOX"), ("✅", "✅"))
LOOKALIKE_FIELDS = (("name", "名字"), ("title", "標題"), ("summary", "說明"), ("publisher", "發行者"),
                    ("web.app.title", "畫面標題"), ("skill", "SKILL.md 的說明"))


def _fold(text) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    return _INVISIBLE.sub("", text).casefold()


def lookalike_problems(m, skill_description: str = "") -> List[str]:
    """工具自己寫的字裡有「官方」「official」「SYNOX」「✅」→ 每一處一行白話（呼叫的人只在不是官方時用）。
    比對前先 NFKC（全形 ＳＹＮＯＸ＝SYNOX）、拿掉零寬與雙向控制字元（官​方＝官方）、不分大小寫。"""
    values = {"name": getattr(m, "name", ""), "title": getattr(m, "title", ""),
              "summary": getattr(m, "summary", ""), "publisher": getattr(m, "publisher", ""),
              "web.app.title": ((getattr(m, "web", None) or {}).get("app") or {}).get("title", ""),
              "skill": skill_description}
    out = []
    for key, where in LOOKALIKE_FIELDS:
        folded = _fold(values.get(key))
        for needle, shown in LOOKALIKE_WORDS:
            if needle.casefold() in folded:
                out.append(f"{where}裡有「{shown}」，但這個工具不是官方的")
    return out


def summary_block(result: SignatureResult, lookalike: Sequence[str] = ()) -> dict:
    """安裝報告的 signature 那一塊（ADR 0027 §3）。"""
    text = result.text or TEXTS.get(result.status, "")
    if result.status == NONE and result.no_official_keys:
        text += NO_OFFICIAL_KEYS_TEXT
    return {"status": result.status, "label": result.label or LABELS.get(result.status, ""),
            "key_id": result.key_id, "public_key": result.public_key, "text": text,
            "lookalike": list(lookalike), "no_official_keys": bool(result.no_official_keys)}


# ── 私鑰（synox-sdk keygen／sign 用；SYNOX 本身從不讀私鑰） ─────────────

def _inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return os.path.normcase(path) == os.path.normcase(root) or \
        os.path.normcase(path).startswith(os.path.normcase(root.rstrip(os.sep) + os.sep))


def key_path_problem(path: str, root: str = REPO_ROOT) -> str:
    """私鑰檔的位置能不能用（""＝可以）：不能在 SYNOX 資料夾裡、不能在任何 git 資料夾裡（不小心就 commit 出去了）。"""
    if not path:
        return "要給私鑰檔的路徑"
    if _inside(path, root):
        return "私鑰檔不能放在 SYNOX 的資料夾裡：請放在別的地方（例如加密的隨身碟），不要放進 git、雲端硬碟或聊天"
    here = os.path.dirname(os.path.realpath(path))
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return (f"私鑰檔不能放在 git 資料夾裡（{here}）：一不小心就會 commit 出去。"
                    "請放在別的地方（例如加密的隨身碟）")
        parent = os.path.dirname(here)
        if parent == here:
            return ""
        here = parent


def stdin_is_terminal() -> bool:
    """可以問密語嗎：stdin 是真的終端機。Windows 上 NUL 也說自己是 tty，所以另外問主控台（GetConsoleMode）。"""
    import sys
    try:
        if not (sys.stdin and sys.stdin.isatty()):
            return False
        if os.name == "nt":
            import ctypes
            import msvcrt
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            mode = ctypes.c_uint32()
            return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
        return True
    except (AttributeError, ValueError, OSError):
        return False


def key_needs_passphrase(path: str) -> bool:
    """私鑰檔是不是用密語加密的 PEM（要不要問密語）。讀不到回 False（讓 load_private_key 說清楚）。"""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return b"-----BEGIN ENCRYPTED PRIVATE KEY-----" in head


def load_private_key(path: str, passphrase: Optional[str] = None, root: str = REPO_ROOT):
    """私鑰檔（PEM PKCS8，或一行 base64＝32 位元組 seed）→ Ed25519PrivateKey。位置不對、密語不對丟 SigningError。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    problem = key_path_problem(path, root)
    if problem:
        raise SigningError(problem)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise SigningError(f"讀不到私鑰檔 {path}（{e.strerror or e}）：檢查路徑對不對")
    if raw.lstrip().startswith(b"-----BEGIN"):
        try:
            key = serialization.load_pem_private_key(raw, password=passphrase.encode("utf-8") if passphrase else None)
        except TypeError:
            if passphrase:
                raise SigningError("這個私鑰檔沒有密語保護，卻給了密語：拿掉 SYNOX_PACK_KEY_PASSWORD 再試一次")
            raise SigningError(f"這個私鑰檔有密語保護：請輸入密語（或設環境變數 {KEY_PASSWORD_ENV}）")
        except ValueError:
            raise SigningError("私鑰檔打不開：密語不對，或檔案壞了。請再試一次")
    else:
        seed = _b64(raw.strip().decode("ascii", "replace"), 32)
        if seed is None:
            raise SigningError("私鑰檔的格式不對（要是 synox-sdk keygen 產生的 PEM，或一行 base64 的 32 位元組）")
        key = Ed25519PrivateKey.from_private_bytes(seed)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError("這把私鑰不是 Ed25519（請用 synox-sdk keygen 產生）")
    return key


def generate_private_key_pem(passphrase: str) -> bytes:
    """新的 Ed25519 私鑰 → PEM（PKCS8）位元組。passphrase 不空＝用它加密（BestAvailableEncryption）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    enc = (serialization.BestAvailableEncryption(passphrase.encode("utf-8")) if passphrase
           else serialization.NoEncryption())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)


def public_key_b64(key) -> str:
    """私鑰 → 公鑰的 base64（44 字；貼進 OFFICIAL_PACK_PUBLIC_KEYS 的就是這一行）。"""
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")
