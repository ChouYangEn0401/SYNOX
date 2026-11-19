"""
pack 寫指令用的小工具（pack 之間不互相 import，要共用的放這裡）。

    kit.command(group, "add", add, "記一筆", default=True, effect=WRITE, fields=[
        Field("amount", "金額", required=True, check=kit.number),
        Field("category", "類別", required=True),
        Field("memo", "備註")])

    def add(api, chat_id, user, values): ...      # values 已經檢查過

跟 SDK 的 Forms 差在**照位置填**：`/money 120 午餐 跟同事` → amount=120、category=午餐、memo=跟同事
（最後一個位置欄位吃掉剩下的字）。也收 `key=value`（AI 走這條：工具參數一律變成 key=value），兩種可以混用。
缺必填就回用法，不開問答（SYNOX 的指令都很短，問答留給 SDK 的 Forms）。

node.fields 照樣設好：/help 的用法、AI 工具的參數 schema（agent/tools.py）都從這裡來。
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from isdtelekit.core.registry import Field, Group, Node, field_pattern

from synox.guard import inputs


MASK = "***"

# 看起來是 token 的樣式（頻道 AI 的回覆遮罩 agent/room.py、log 的 [ROUTE]／[AGENT] 行都用這一份）
TOKEN_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{16,}=*"),
    re.compile(r"\b[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{20,}\b"),   # Discord bot token、JWT
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b"),                                  # Telegram bot token
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),                                          # OpenAI／Anthropic 類
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
]
TOKEN_LOG_PREFIXES = ("[ROUTE]", "[AGENT]")       # 這幾種 log 行會帶人打的字或 AI 的參數：一律先遮 token 樣式


def mask_tokens(text: str) -> str:
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


class _RedactArgs(logging.Filter):
    """把 log 裡「/指令 後面的字」換成 ***（SDK dispatcher 的 [ROUTE] 那一行會印人打的整句話）；
    [ROUTE]／[AGENT] 開頭的行另外把看起來是 token 的片段換成 ***（審查 A #7：人把 token 貼在指令裡）。"""

    def __init__(self):
        super().__init__("synox-redact")
        self._commands: set = set()
        self._lock = threading.Lock()
        self._pattern: Optional["re.Pattern"] = None
        self._secrets: tuple = ()                     # 已知的密鑰值（mask_in_logs）：出現在任何 log 行都遮

    def add(self, command: str) -> None:
        with self._lock:
            self._commands.add(command)
            names = "|".join(re.escape(c) for c in sorted(self._commands, key=len, reverse=True))
            self._pattern = re.compile(r"(" + names + r")(?:@\w+)?(?![\w])[^'\"\n]*")

    def add_secret(self, value: str) -> None:
        with self._lock:
            if value not in self._secrets:
                self._secrets = tuple(sorted(self._secrets + (value,), key=len, reverse=True))

    def redact(self, text: str) -> str:
        for value in self._secrets:
            if value in text:
                text = text.replace(value, MASK)
        pattern = self._pattern
        if pattern is not None:
            text = pattern.sub(lambda m: m.group(1) + " ***", text)
        if text.startswith(TOKEN_LOG_PREFIXES):
            text = mask_tokens(text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = self.redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


_REDACT = _RedactArgs()


def install_log_redaction() -> None:
    """把遮罩裝在 root logger 上（SDK 的 dispatcher 用 logging.info）。重複叫沒關係。"""
    root = logging.getLogger()
    if _REDACT not in root.filters:
        root.addFilter(_REDACT)


def mask_in_logs(value: str) -> None:
    """這串值（例如解出來的 Telegram bot token）不准出現在 log：任何一行有它就換成 ***。
    裝在 root logger 和它現有的 handler 上（子 logger 的紀錄只經過 handler）；重複叫沒關係。"""
    value = str(value or "")
    if len(value) < 8:
        return
    _REDACT.add_secret(value)
    install_log_redaction()
    for handler in logging.getLogger().handlers:
        if _REDACT not in handler.filters:
            handler.addFilter(_REDACT)


def redact_in_logs(command: str) -> None:
    """這個指令（例如 "/todoist_token"）後面跟的字不准出現在 log：裝在 root logger 上（SDK 的 dispatcher 用 logging.info）。
    給「參數是密鑰」的指令用；記得也設 ai=False，不讓密鑰經過 AI。"""
    _REDACT.add(command)
    install_log_redaction()


def _ascii_digits(text: str) -> bool:
    """只收 0-9（"²"、"١" 的 isdigit() 也是 True，int() 卻會丟例外）。"""
    return bool(text) and text.isascii() and text.isdigit()


def number(value: str) -> Optional[str]:
    """一般的數字：只收 ASCII、有限的數（nan、inf、1e999 都不收）。"""
    import math
    text = value.replace(",", "").strip()
    try:
        if not text.isascii() or not math.isfinite(float(text)):
            return "要是數字"
    except ValueError:
        return "要是數字"
    return None


def positive_int(value: str) -> Optional[str]:
    return None if _ascii_digits(value) and int(value) > 0 else "要是正整數（例如 1）"


def hhmm(value: str) -> Optional[str]:
    parts = value.split(":")
    if len(parts) == 2 and all(_ascii_digits(p) for p in parts) and 0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60 \
            and len(parts[1]) == 2:
        return None
    return "要是 HH:MM（例如 08:00）"


def amount(value: str) -> Optional[str]:
    """金額：大於 0、最多兩位小數、不超過十億（可以有千分位逗號）。"""
    text = value.replace(",", "").strip()
    if re.match(r"^[0-9]{1,10}(\.[0-9]{1,2})?$", text) and 0 < float(text) <= 1_000_000_000:
        return None
    return "要是金額（例如 120 或 99.5）"


def iso_date(value: str) -> Optional[str]:
    from datetime import date
    try:
        if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", value.strip()):
            date.fromisoformat(value.strip())
            return None
    except ValueError:
        pass
    return "要是日期 YYYY-MM-DD（例如 2026-11-14）"


def one_line(value: str) -> Optional[str]:
    return "要是一行字（不能換行）" if ("\n" in value or "\r" in value) else None


def max_len(n: int) -> Callable[[str], Optional[str]]:
    def check(value: str) -> Optional[str]:
        return None if len(value) <= n else f"最多 {n} 個字"
    return check


class _Checks:
    """`Field(check=kit.checks.amount)`：一組現成的欄位檢查（回 None＝對；回一句話＝錯在哪）。
    基本檢查（長度上限 2000、空字元、控制字元、騙人的排版字元）SYNOX 在這之前已經做完（guard/inputs.py）。"""
    number = staticmethod(number)
    positive_int = staticmethod(positive_int)
    hhmm = staticmethod(hhmm)
    amount = staticmethod(amount)
    iso_date = staticmethod(iso_date)
    one_line = staticmethod(one_line)
    max_len = staticmethod(max_len)


checks = _Checks()


# ── 誰叫的（ADR 0025 §2）：工具看得到、改不了；「自己再檢查一次」用，不是邊界 ──────────

class Caller(NamedTuple):
    kind: str          # telegram／discord／web／console／remote／ai／schedule／system／unknown
    human: bool        # 人在 Telegram／Discord／SYNOX 網頁／終端機


NOT_HUMAN = "🔐 這個動作要你本人在 Telegram 或 SYNOX 網頁做。"


class Refused(Exception):
    """丟出去＝回使用者一句話、不算工具壞掉（kit.command 會接住）。"""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = str(text)


def caller() -> Caller:
    from synox.guard import origin
    o = origin.current()
    return Caller(o.kind, o.human)


def require_human() -> None:
    """不是人（AI、排程、遠端、背景工作、不明）→ 丟 Refused（使用者看到「這個動作要你本人…」）。"""
    if not caller().human:
        raise Refused(NOT_HUMAN)


def usage_of(fields: Sequence[Field], positional: int) -> str:
    parts = []
    for i, f in enumerate(fields):
        if i < positional:
            parts.append(f"<{f.ask}>" if f.required else f"[{f.ask}]")
        else:
            parts.append(f"[{f.name}=…]")
    return " ".join(parts)


def parse_args(fields: Sequence[Field], args: Sequence[str], positional: Optional[int] = None
               ) -> Tuple[Dict[str, str], List[Field], List[str]]:
    """args → (values, 缺的必填, 錯誤)。"""
    fields = tuple(fields)
    positional = len(fields) if positional is None else positional
    text = " ".join(str(a) for a in args)
    values: Dict[str, str] = {}
    head = text
    if fields:
        marks = list(field_pattern(fields).finditer(text))
        if marks:
            head = text[:marks[0].start()]
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            value = text[m.end():end].strip()
            if value:
                values[m.group(1).lower()] = value
    slots = [f for f in fields[:positional] if f.name not in values]
    tokens = head.split()
    for i, f in enumerate(slots):
        if i >= len(tokens):
            break
        values[f.name] = " ".join(tokens[i:]) if i == len(slots) - 1 else tokens[i]
    return check_values(fields, values)


def field_errors(fields: Sequence[Field], values: Dict[str, str]) -> Dict[str, str]:
    """{欄位名: 錯誤的那一句}（choices、check）。訊息跟 Telegram 那條同一句（「金額要是數字」）。"""
    out: Dict[str, str] = {}
    for f in fields:
        value = values.get(f.name)
        if value is None:
            continue
        if f.choices and value.strip().lower() not in {c.lower() for c in f.choices}:
            out[f.name] = f"{f.ask} 只能是 {'/'.join(f.choices)}"
        elif f.check is not None and f.check(value):
            out[f.name] = f"{f.ask}{f.check(value)}"
    return out


def check_values(fields: Sequence[Field], values: Dict[str, str]
                 ) -> Tuple[Dict[str, str], List[Field], List[str]]:
    """已經照名字放好的 values → (clean, 缺的必填, 錯誤)。人打字（parse_args）、AI、工具畫面、手機入口都走這裡：
    第一步是門禁核心的基本檢查（guard/inputs.py：不認得的欄位、太多、太長、空字元、控制字元、排版字元；固定的句子），
    再跑欄位自己的 choices／check、補 default、找缺的必填。"""
    fields = tuple(fields)
    try:
        inputs.values([f.name for f in fields], values, multiline=True)
    except inputs.Bad as bad:
        return {}, [], [bad.text]
    clean = dict(values)
    errors = list(field_errors(fields, clean).values())
    for f in fields:
        if f.name not in clean and f.default:
            clean[f.name] = f.default
    missing = [f for f in fields if f.required and f.name not in clean]
    return clean, missing, errors


# ── 工具服務（ADR 0024；SDK 0.2.3）：pack.app_read／app_action／app_export 用的小東西 ─────────

class AppError(Exception):
    """工具的畫面函式裡丟：message 原樣顯示給使用者（所以是寫給人看的一句話）。別的例外的訊息永遠不會出現在回應、log、稽核。"""

    def __init__(self, message: str, code: str = "refused", status: int = 409):
        super().__init__(message)
        self.message, self.code, self.status = str(message), str(code or "refused"), int(status or 409)


@dataclass(frozen=True)
class Download:
    """一個要給使用者存下來的檔（pack.app_export 的函式回這個）。"""
    filename: str
    content_type: str
    data: bytes


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_bytes(header: Sequence, rows: Iterable[Sequence]) -> bytes:
    """CSV：UTF-8、開頭 BOM、CRLF、標準函式庫 csv 的引號規則。int／float 原樣寫；None 寫空的；
    字串開頭是 = + - @ Tab CR LF 的前面加一個 '（防試算表把它當公式）。每個工具的 CSV 都用它，不要自己組。"""
    import csv
    import io

    def cell(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, (int, float)):
            return value
        text = str(value)
        return "'" + text if text.startswith(_FORMULA_START) else text

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([cell(v) for v in header])
    for row in rows:
        writer.writerow([cell(v) for v in row])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def command(group: Group, name: str, fn: Callable, summary: str, *, fields: Sequence[Field] = (),
            positional: Optional[int] = None, usage: Optional[str] = None, plain: Optional[str] = None,
            examples: Optional[Sequence] = None, **kw) -> Node:
    """掛一個「照位置填」的指令。fn(api, chat_id, user, values)。其他參數同 Group.leaf。
    plain＝一句白話（40 字內）、examples＝範例的參數（["120 午餐", {"text": …, "note": …}]，最多 3 個）：
    /help 與網頁「💡 範例」用（synox/helpui；pack.json 最上層的 help 區塊寫了同一個指令的話以 pack.json 為準）。"""
    fields = tuple(fields)
    doc = None
    if plain is not None or examples is not None:
        from synox.helpui.examples import check_code_doc
        doc = check_code_doc(plain, examples)
    if any(f.fresh_code for f in fields):
        raise ValueError("kit.command does not take fresh_code fields; use app.forms.leaf (SDK Forms)")
    positional = len(fields) if positional is None else positional
    shown = usage if usage is not None else usage_of(fields, positional)

    def run(api, chat_id, user, args):
        values, missing, errors = parse_args(fields, args, positional)
        if errors:
            api.send_message(chat_id, "❌ " + "；".join(errors))
            return
        if missing:
            api.send_message(chat_id, f"用法：{node.command} {shown}\n（少了：{'、'.join(f.ask for f in missing)}）")
            return
        try:
            fn(api, chat_id, user, values)
        except Refused as refused:
            api.send_message(chat_id, refused.text)

    node = group.leaf(name, run, summary, usage=shown, **kw)
    node.fields = fields
    node.kit_positional = positional          # 範例跑不跑得動，照同一份規則檢查（helpui/examples.py）
    if doc:
        node.help_doc = doc
    return node


# ── 回覆帶圖（docs/sdk.md「回覆帶圖」；SDK 0.2.5 起）──────────────────────────────────────

IMAGE_FALLBACK_MAX = 10                # Telegram 一組相簿最多 10 張


def send_image(api, chat_id, images, caption: str = "", reply_markup=None) -> dict:
    """回覆帶圖。images：每張是 bytes（PNG／JPEG…）或 {"svg": SVG 字串或 bytes, "png": PNG bytes, "alt": "說明"}。

    - 網頁對話（channel 有 send_image）：一則訊息、圖畫在泡泡裡（SVG 照白名單重寫；不收的退回 PNG）；reply_markup 照樣有按鈕。
    - Telegram／Discord（沒有 send_image）：PNG 寫進暫存檔、用 send_photo（好幾張用 send_media_group）送，送完刪掉；
      按鈕放不上圖，有 reply_markup 時照片不帶字、緊接著送一則「caption＋按鈕」（caption 只出現一次）。
    - 都送不了（沒有 PNG、channel 不收圖）：回 {"ok": False}，呼叫的人自己改送文字。
    經 AI 呼叫時（agent/capture.CaptureApi）圖直接給使用者，AI 拿到「已經傳了 N 張圖」。"""
    images = list(images or [])
    if not images:
        return {"ok": False, "error": "沒有圖"}
    fn = getattr(api, "send_image", None)
    if callable(fn):
        try:
            out = fn(chat_id, images, caption=caption, reply_markup=reply_markup)
        except Exception:
            logging.exception("[KIT] send_image failed")
            out = {"ok": False}
        if (out or {}).get("ok"):
            return out
    rasters = []
    for item in images[:IMAGE_FALLBACK_MAX]:
        data = item if isinstance(item, (bytes, bytearray)) else (item or {}).get("png") or (item or {}).get("data")
        if data:
            rasters.append(bytes(data))
    if not rasters:
        return {"ok": False, "error": "這個 channel 不能顯示 SVG，也沒有 PNG"}
    import os
    import shutil
    import tempfile
    folder = tempfile.mkdtemp(prefix="synox-img-")
    try:
        paths = []
        for i, data in enumerate(rasters):
            ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".png"
            path = os.path.join(folder, f"image{i + 1}{ext}")
            with open(path, "wb") as f:
                f.write(data)
            paths.append(path)
        short = "" if reply_markup is not None else (caption or "")[:1000]     # 有按鈕：字跟按鈕放同一則，不重複
        try:
            if len(paths) == 1:
                out = api.send_photo(chat_id, paths[0], caption=short)
            else:
                out = api.send_media_group(chat_id, paths, short, "photo")
        except Exception:
            logging.exception("[KIT] send_photo failed")
            out = {"ok": False}
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if (out or {}).get("ok") and reply_markup is not None:
        api.send_message(chat_id, caption or "👇", reply_markup=reply_markup)
    return out or {"ok": False}


def edit_image(api, chat_id, message_id, images, caption: Optional[str] = None, reply_markup=None) -> dict:
    """換掉之前 send_image 送出的那則（例如「下一個按法」）。channel 不能改圖（Telegram…）＝改送一則新的（send_image）。"""
    fn = getattr(api, "edit_image", None)
    if callable(fn):
        try:
            out = fn(chat_id, message_id, images, caption=caption, reply_markup=reply_markup)
        except Exception:
            logging.exception("[KIT] edit_image failed")
            out = {"ok": False}
        if (out or {}).get("ok"):
            return out
    return send_image(api, chat_id, images, caption or "", reply_markup)


def can_show_images(api) -> bool:
    """這個 channel 能不能把 send_image 畫在同一則訊息裡（網頁＝True）。不能的照樣可以送 PNG（send_photo）。"""
    real = getattr(api, "_real", None) or api            # agent/capture.CaptureApi 包在外面：看裡面那個
    return callable(getattr(real, "send_image", None))
