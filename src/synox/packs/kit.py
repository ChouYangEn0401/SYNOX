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
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from isdtelekit.core.registry import Field, Group, Node, field_pattern


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
    errors = []
    for f in fields:
        value = values.get(f.name)
        if value is None:
            continue
        if f.choices and value.strip().lower() not in {c.lower() for c in f.choices}:
            errors.append(f"{f.ask} 只能是 {'/'.join(f.choices)}")
        elif f.check is not None and f.check(value):
            errors.append(f"{f.ask}{f.check(value)}")
    for f in fields:
        if f.name not in values and f.default:
            values[f.name] = f.default
    missing = [f for f in fields if f.required and f.name not in values]
    return values, missing, errors


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
        fn(api, chat_id, user, values)

    node = group.leaf(name, run, summary, usage=shown, **kw)
    node.fields = fields
    node.kit_positional = positional          # 範例跑不跑得動，照同一份規則檢查（helpui/examples.py）
    if doc:
        node.help_doc = doc
    return node
