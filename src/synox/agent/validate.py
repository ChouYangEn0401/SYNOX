"""
安全管線第 4 關：呼叫驗證（架構 v1 §4；規則照 ClawBot core/argvcheck.py）。

agent/loop.py 在執行**任何**工具呼叫之前問 `check_call(app, node, args, user)`：

- 參數要是 JSON 物件；最多 MAX_FIELDS 個欄位；**不認得的欄位一律拒**（只收 node 的欄位；沒有欄位的節點只收 args）。
- 值要是字串（null 當作沒給）；每個最多 MAX_LEN 字；NUL 一律拒；kind=cli（argv）的 pack 連換行、控制字元都拒。
- 值裡面不能夾「另一個欄位名=」（ClawBot argvcheck 的威脅 3：to_argv 把值切成 key=value 片段，
  `memo="x amount=999"` 會變成設定 amount；驗證碼欄位也算，雖然 AI 看不到它）。
- 會變成單獨一段 argv（positional）的值不能以 - 開頭（不然對方的命令列會當成旗標，例如 -rf、--delete-all）：
  kind=cli 的 `{欄位}` 單獨一段的那些、沒有欄位的節點的 args 每一段。
- `kind: path` 的欄位：解析後一定要在這個人的資料夾裡（伺服器版 data/users/<id>，個人版 data），用 `inside()`；
  像密鑰的檔名（.env、id_rsa、*.pem、*.key、credentials*、*.pfx…）一律拒；kind=cli 的其他單段值也看檔名。

不合 → 回一句短短的中文（交回給 AI 當工具結果，讓它自己改），**不執行**。合 → None。
打字的那一條（人自己打的 cli 指令）由 loader 掛的 `typed_check()` 做不需要「是誰」的那幾項。
"""

from __future__ import annotations

import os
import re
from typing import Callable, Dict, Optional, Tuple

MAX_FIELDS = 20
MAX_LEN = 2000

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_SAFE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".pub")
_SECRET_PREFIXES = (".env", "credentials")
_SECRET_EXACT = (".netrc", ".npmrc", ".pypirc", ".dockercfg", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
                 "secrets.json", "service-account.json", ".synox.key", "config.json")
_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".jks", ".keystore", ".ppk", ".kdbx", ".json.enc")


def looks_secret(path: str) -> Optional[str]:
    """這個檔名看起來是密鑰嗎；是就回原因，不是回 None。只看檔名、不開檔案（照 ClawBot argvcheck.looks_secret）。"""
    name = os.path.basename((path or "").strip().replace("\\", "/").rstrip("/")).lower()
    if not name or name.endswith(_SECRET_SAFE_SUFFIXES):
        return None
    if name.startswith(_SECRET_PREFIXES):
        return "環境變數或憑證檔"
    if name in _SECRET_EXACT:
        return "憑證或設定檔"
    if name.endswith(_SECRET_SUFFIXES):
        return "金鑰／憑證檔"
    return None


def inside(root: str, candidate: str) -> Tuple[str, Optional[str]]:
    """candidate 解析成絕對路徑，確認在 root 底下（或就是 root）。回 (絕對路徑, 錯誤)。
    不直接拿 os.path.commonpath 當判斷式：不同磁碟機、UNC 會丟 ValueError（ClawBot 2026-10-08 實測）。"""
    candidate = candidate or ""
    if not candidate.strip():
        return "", "路徑不能空白"
    if _CONTROL.search(candidate):
        return "", "路徑不能有換行或控制字元"
    root_real = os.path.realpath(root)
    full = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
    full_real = os.path.realpath(full)
    try:
        ok = os.path.commonpath([root_real, full_real]) == root_real
    except ValueError:
        ok = False
    if not ok:
        return "", "不在你的資料夾裡"
    return full_real, None


def _value_problem(value: str, *, argv: bool) -> Optional[str]:
    if len(value) > MAX_LEN:
        return f"太長了（最多 {MAX_LEN} 字）"
    if "\x00" in value:
        return "不能有 NUL 字元"
    if argv and _CONTROL.search(value):
        return "不能有換行或控制字元"
    return None


def typed_check(kind: str = "text") -> Callable[[str], Optional[str]]:
    """kind=cli 的欄位在「人打字」那一條也跑的檢查（不需要知道是誰的那幾項）。"""
    def check(value: str) -> Optional[str]:
        problem = _value_problem(value or "", argv=True)
        if problem:
            return problem
        if kind == "path" or not re.search(r"\s", value or ""):
            secret = looks_secret(value or "")
            if secret:
                return f"看起來是{secret}，不收"
        return None
    return check


def _meta(app, node) -> dict:
    return (getattr(app, "extras", {}) or {}).get("synox_tool_meta", {}).get(node.path, {})


def _user_dir(app, user) -> str:
    from synox.packs.loader import user_data_dir
    config = app.extras.get("synox_config") or app.config
    return user_data_dir(config, getattr(user, "tg_id", None))


def check_call(app, node, args, user, tool: str = "") -> Optional[str]:
    """None＝可以執行；否則回給 AI 的一句話（不執行）。"""
    tool = tool or node.path.replace(".", "__")

    def no(reason: str) -> str:
        return f"沒有執行 {tool}：{reason}。改好再呼叫一次。"

    if args is None:
        args = {}
    if not isinstance(args, dict):
        return no("參數要是 JSON 物件（{\"欄位\": \"值\"}）")
    if len(args) > MAX_FIELDS:
        return no(f"欄位太多（最多 {MAX_FIELDS} 個）")
    fields = [f for f in (node.fields or ())]
    allowed = [f.name for f in fields if not f.fresh_code] if fields else ["args"]
    unknown = [str(k) for k in args if k not in allowed]
    if unknown:
        return no(f"不認得欄位 {'、'.join(unknown)}（只收 {'、'.join(allowed) or '（沒有參數）'}）")
    meta = _meta(app, node)
    argv = bool(meta.get("argv"))
    positional = set(meta.get("positional") or ())
    kinds: Dict[str, str] = dict(meta.get("kinds") or {})
    all_names = [f.name for f in fields]
    for key, value in args.items():
        if value is None:
            continue
        if not isinstance(value, str):
            return no(f"欄位 {key} 要是字串（例如 \"80\"，不是 {type(value).__name__}）")
        problem = _value_problem(value, argv=argv)
        if problem:
            return no(f"欄位 {key} {problem}")
        others = [n for n in all_names if n != key]
        if others:
            names = "|".join(sorted((re.escape(n) for n in others), key=len, reverse=True))
            hit = re.search(rf"(?:^|(?<=\s))({names})=", value, re.IGNORECASE)
            if hit:
                return no(f"欄位 {key} 的值裡不能出現「{hit.group(1)}=」（那會變成在設定另一個欄位）")
        if key == "args" and not fields:
            bad = [t for t in value.split() if t.startswith("-")]
            if bad:
                return no(f"參數 {bad[0]} 不能以 - 開頭（會被當成命令列旗標）")
        if key in positional and value.strip().startswith("-"):
            return no(f"欄位 {key} 不能以 - 開頭（會被當成命令列旗標）")
        if kinds.get(key) == "path":
            _full, problem = inside(_user_dir(app, user), value.strip())
            if problem:
                return no(f"欄位 {key} 的路徑{problem}")
        if kinds.get(key) == "path" or (argv and value.strip() and not re.search(r"\s", value.strip())):
            secret = looks_secret(value)
            if secret:
                return no(f"欄位 {key} 看起來是{secret}，不收")
    return None


def check_skill_read(args) -> Optional[str]:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return "沒有執行 skill_read：參數要是 JSON 物件。改好再呼叫一次。"
    extra = [str(k) for k in args if k != "name"]
    if extra:
        return f"沒有執行 skill_read：不認得欄位 {'、'.join(extra)}（只收 name）。改好再呼叫一次。"
    name = args.get("name", "")
    if not isinstance(name, str) or len(name) > 100:
        return "沒有執行 skill_read：name 要是技能名稱（字串）。改好再呼叫一次。"
    return None


def mark(app, node_path: str, *, argv: bool = False, positional=(), kinds: Optional[Dict[str, str]] = None) -> None:
    """python pack 也能替自己的節點宣告欄位種類，例如 mark(app, "x.open", kinds={"file": "path"})。"""
    meta = app.extras.setdefault("synox_tool_meta", {})
    meta[node_path] = {"argv": argv, "positional": list(positional), "kinds": dict(kinds or {})}
