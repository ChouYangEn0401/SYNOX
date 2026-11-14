"""輸入的基本檢查（ADR 0025 §4）：**只擋、不改字**。人打字、AI、工具畫面、遠端四條路都先過這一份，
再跑欄位自己的 check。錯誤是固定的句子（`Bad.text`），**不把對方送來的字吐回去**。

    text(value, max=2000, multiline=False) -> 原字串       不合丟 Bad
    values(names, raw, max_fields=20, max=2000) -> dict   鍵要是這個指令的欄位、值是字串且過 text
    rel_path(raw) -> 相對路徑                              網址路徑（ADR 0026 §5 的規則）
    json_object(body, max_bytes=…, max_depth=4) -> dict    UTF-8 的 JSON 物件、不太深、沒有重複的鍵

這個檔不 import synox 的其他模組。
"""

from __future__ import annotations

import json
import posixpath
import re
from typing import Dict, Iterable, Mapping
from urllib.parse import unquote

TEXT = {
    "type": "格式不對（要是文字）。",
    "long": "太長了。",
    "nul": "裡面有不能用的字元（空字元）。",
    "control": "裡面有不能用的控制字元。",
    "encoding": "裡面有壞掉的字（編碼不對）。",
    "bidi": "裡面有會讓字看起來跟實際不一樣的排版字元。",
    "field": "有不認得的欄位。",
    "many": "欄位太多了。",
    "path": "路徑不對。",
    "json": "內容格式不對。",
    "dupkey": "內容格式不對（同一個欄位出現兩次）。",
    "deep": "內容格式不對（層數太多）。",
}

_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
_SEGMENT = re.compile(r"^[A-Za-z0-9_~-][A-Za-z0-9._~-]*$")
_BANNED_ESCAPES = ("%2f", "%5c", "%00", "%25")


class Bad(ValueError):
    """輸入不合。code 是固定代碼（TEXT 的鍵），text 是固定的白話；兩個都不含輸入的內容。"""

    def __init__(self, code: str):
        self.code = code if code in TEXT else "type"
        self.text = TEXT[self.code]
        super().__init__(self.code)


def text(value, *, max: int = 2000, multiline: bool = False) -> str:
    """value 是字串、不長於 max、沒有空字元、控制字元（multiline 留換行與 tab）、落單的代理字元、排版控制字元。回原字串。"""
    if not isinstance(value, str):
        raise Bad("type")
    if len(value) > max:
        raise Bad("long")
    for ch in value:
        o = ord(ch)
        if o == 0:
            raise Bad("nul")
        if o < 0x20 or 0x7F <= o <= 0x9F:
            if multiline and ch in "\n\r\t":
                continue
            raise Bad("control")
        if 0xD800 <= o <= 0xDFFF:
            raise Bad("encoding")
        if o in _BIDI:
            raise Bad("bidi")
    return value


def values(names: Iterable[str], raw: Mapping, *, max_fields: int = 20, max: int = 2000,
           multiline: bool = False) -> Dict[str, str]:
    """一個指令的欄位值：鍵都要在 names 裡、最多 max_fields 個、每個值過 text。回一個新的 dict（值不變）。"""
    if not isinstance(raw, Mapping):
        raise Bad("type")
    if len(raw) > max_fields:
        raise Bad("many")
    allowed = set(names)
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or key not in allowed:
            raise Bad("field")
        out[key] = text(value, max=max, multiline=multiline)
    return out


def rel_path(raw) -> str:
    """網址路徑（`/img/a.png`）→ 安全的相對路徑（`img/a.png`）。規則：ADR 0026 §5「路徑」那一列；
    另外每一段只收英數與 `._~-`、不以點開頭（擋 `..;`、`C:`、隱藏檔）。不合丟 Bad("path")。"""
    if not isinstance(raw, str) or not raw or len(raw) > 2048:
        raise Bad("path")
    if any(not (0x21 <= ord(c) <= 0x7E) for c in raw):
        raise Bad("path")
    low = raw.lower()
    if any(e in low for e in _BANNED_ESCAPES):
        raise Bad("path")
    try:
        path = unquote(raw, errors="strict")
    except UnicodeDecodeError:
        raise Bad("path")
    if any(not (0x21 <= ord(c) <= 0x7E) for c in path) or "\\" in path or "//" in path:
        raise Bad("path")
    rel = path[1:] if path.startswith("/") else path
    if not rel or rel.endswith("/"):
        raise Bad("path")
    segments = rel.split("/")
    if any(s in ("", ".", "..") or not _SEGMENT.match(s) for s in segments):
        raise Bad("path")
    if posixpath.normpath(rel) != rel:
        raise Bad("path")
    return rel


def _no_dup(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise Bad("dupkey")
        out[key] = value
    return out


def _bad_constant(_name):
    raise Bad("json")


def _walk(obj, limit: int, depth: int = 1) -> None:
    if isinstance(obj, (dict, list)):
        if depth > limit:
            raise Bad("deep")
        items = obj.items() if isinstance(obj, dict) else enumerate(obj)
        for key, value in items:
            if isinstance(key, str):
                text(key, max=256)
            _walk(value, limit, depth + 1)
    elif isinstance(obj, str):
        text(obj, max=1 << 20, multiline=True)


def json_object(body, *, max_bytes: int = 65536, max_depth: int = 4) -> dict:
    """請求內容 → dict：不超過 max_bytes、UTF-8、是 JSON 物件、最多 max_depth 層、同一個鍵不准兩次、
    沒有 NaN／Infinity；鍵與字串值過 text（字串值可以多行）。不合丟 Bad。"""
    if isinstance(body, str):
        body = body.encode("utf-8", "surrogatepass")
    if not isinstance(body, (bytes, bytearray)):
        raise Bad("type")
    if len(body) > max_bytes:
        raise Bad("long")
    try:
        decoded = bytes(body).decode("utf-8")
    except UnicodeDecodeError:
        raise Bad("encoding")
    try:
        obj = json.loads(decoded, object_pairs_hook=_no_dup, parse_constant=_bad_constant)
    except Bad:
        raise
    except RecursionError:
        raise Bad("deep")
    except (ValueError, TypeError):
        raise Bad("json")
    if not isinstance(obj, dict):
        raise Bad("json")
    _walk(obj, max_depth)
    return obj
