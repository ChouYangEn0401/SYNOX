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

    def add(self, command: str) -> None:
        with self._lock:
            self._commands.add(command)
            names = "|".join(re.escape(c) for c in sorted(self._commands, key=len, reverse=True))
            self._pattern = re.compile(r"(" + names + r")(?:@\w+)?(?![\w])[^'\"\n]*")

    def redact(self, text: str) -> str:
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


def redact_in_logs(command: str) -> None:
    """這個指令（例如 "/todoist_token"）後面跟的字不准出現在 log：裝在 root logger 上（SDK 的 dispatcher 用 logging.info）。
    給「參數是密鑰」的指令用；記得也設 ai=False，不讓密鑰經過 AI。"""
    _REDACT.add(command)
    install_log_redaction()


def number(value: str) -> Optional[str]:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return "要是數字"
    return None


def positive_int(value: str) -> Optional[str]:
    return None if value.isdigit() and int(value) > 0 else "要是正整數（例如 1）"


def hhmm(value: str) -> Optional[str]:
    parts = value.split(":")
    if len(parts) == 2 and all(p.isdigit() for p in parts) and 0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60 \
            and len(parts[1]) == 2:
        return None
    return "要是 HH:MM（例如 08:00）"


def amount(value: str) -> Optional[str]:
    """金額：大於 0、最多兩位小數、不超過十億（可以有千分位逗號）。"""
    text = value.replace(",", "").strip()
    if re.match(r"^\d{1,10}(\.\d{1,2})?$", text) and 0 < float(text) <= 1_000_000_000:
        return None
    return "要是金額（例如 120 或 99.5）"


def iso_date(value: str) -> Optional[str]:
    from datetime import date
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value.strip()):
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
            positional: Optional[int] = None, usage: Optional[str] = None, **kw) -> Node:
    """掛一個「照位置填」的指令。fn(api, chat_id, user, values)。其他參數同 Group.leaf。"""
    fields = tuple(fields)
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
    return node
