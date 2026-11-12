"""
工具失敗信封 v1（docs/tool-health.md）：把工具的各種失敗（v1 信封、舊信封只有 code、例外、純文字、cli 叫不起來／逾時）
正規化成同一種 `Failure`，截長、去敏感，再產生「給 AI 的一行」與「給人看的字」。

    {"ok": false, "error": "資料來源的回傳格式變了。", "code": "upstream_changed",
     "failure": {"v": 1, "scope": "tool", "retry": {"ok": false, "after_s": null},
                 "remedy": {"kind": "needs_update", "id": "upgrade", "summary": "要換成 1.3.0 以上的版本。"},
                 "diag": {"tool_version": "1.2.0", "upstream": "KeyError: 'price'"}}}

- 類別碼是固定的一張表（`CODES`）：預設 scope、預設能不能重試、算不算進門檻、預設補救種類。不認得的碼一律 `unclassified`
  （SDK 舊版的 `usage`／`bad_value`／`internal`／`spec` 有固定的對照，`ALIASES`）。
- 所有文字欄位先過 `kit.TOKEN_PATTERNS`（跟 log 遮罩同一份）再存、再顯示；`error` 最多 300 字。
- `diag` 只給擁有者與 log 看，**不進 AI 的提示**：每個值最多 200 字、整包最多 1 KB。
- 補救說明（`remedy.summary`）看起來像指令（命令列、網址、管線…）就整段丟掉，換成固定的一句「請看工具說明」。
  SYNOX 這一版**不執行任何補救**，只把建議寫出來。
- 給 AI 的「下一步」由 SYNOX 依類別碼產生（`NEXT`），不採用工具自己的文字（避免工具結果夾帶指令）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

VERSION = 1
SCOPES = ("input", "user", "tool", "pack", "environment")
COUNTED_SCOPES = ("tool", "pack", "environment")          # 只有這三種算進門檻；user 只記在那個人身上
REMEDY_KINDS = ("auto_fixable", "needs_update", "needs_config", "needs_owner", "none")
REMEDY_ID_RE = re.compile(r"^[a-z0-9_]{1,32}$")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
DIAG_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
REASON_MAX = 300
AI_LINE_MAX = 300
DIAG_VALUE_MAX = 200
DIAG_MAX_BYTES = 1024
REMEDY_SUMMARY_MAX = 200
SAFE_REMEDY = "請看工具說明。"
UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class CodeInfo:
    scope: str           # 預設 scope
    retry: bool          # 預設能不能重試
    counts: bool         # 算不算進門檻（scope 是 input／user 的本來就不算）
    remedy: str          # 預設補救種類
    label: str           # 給人看的類別名稱
    next: str            # 給 AI 的「下一步」（SYNOX 自己的字）


_ASK = "跟使用者說明原因，不要再試同一個工具。"
CODES: Dict[str, CodeInfo] = {
    "bad_input": CodeInfo("input", False, False, "none", "參數不對", "照原因改參數再試一次，或先問使用者。"),
    "not_found": CodeInfo("input", False, False, "none", "找不到", "跟使用者確認名稱或編號，不要猜。"),
    "needs_config": CodeInfo("pack", False, True, "needs_config", "還沒設定好", "請使用者到工具頁完成設定；" + _ASK),
    "config_invalid": CodeInfo("pack", False, True, "needs_config", "設定有誤", "請使用者到工具頁檢查設定；" + _ASK),
    "auth_missing": CodeInfo("user", False, False, "needs_config", "還沒連接帳號", "請使用者到工具頁按「連接」；" + _ASK),
    "auth_expired": CodeInfo("user", False, False, "needs_config", "帳號憑證過期", "請使用者到工具頁重新連接；" + _ASK),
    "permission_denied": CodeInfo("user", False, False, "needs_owner", "沒有權限", "跟使用者說明沒有權限；" + _ASK),
    "rate_limited": CodeInfo("environment", True, False, "none", "被限流", "稍後再試，不要馬上重試。"),
    "network_unreachable": CodeInfo("environment", True, True, "none", "連不上網路", "稍後再試；先告訴使用者連不上。"),
    "upstream_unavailable": CodeInfo("tool", True, True, "none", "外部服務暫時不能用", "稍後再試；先告訴使用者服務暫時不能用。"),
    "upstream_changed": CodeInfo("tool", False, True, "needs_update", "外部服務改版了", "工具要更新；" + _ASK),
    "dependency_missing": CodeInfo("pack", False, True, "needs_update", "缺少需要的程式", "工具要重新安裝或補裝；" + _ASK),
    "dependency_outdated": CodeInfo("pack", False, True, "needs_update", "需要的程式版本太舊", "工具要更新；" + _ASK),
    "unsupported_platform": CodeInfo("environment", False, True, "needs_owner", "這台電腦不支援", "這台電腦用不了這個工具；" + _ASK),
    "resource_exhausted": CodeInfo("environment", True, True, "needs_owner", "資源不夠", "稍後再試；先告訴使用者資源不夠。"),
    "timeout": CodeInfo("tool", True, True, "none", "逾時", "稍後再試一次；還是逾時就告訴使用者。"),
    "internal_bug": CodeInfo("tool", False, True, "needs_update", "工具本身的錯誤", "工具要修；" + _ASK),
    UNCLASSIFIED: CodeInfo("tool", False, True, "none", "沒有分類的錯誤", "告訴使用者出錯了；不要一直重試。"),
}
# SDK 舊版（與 SYNOX 自己）用過的碼 → 表上的碼。其他不認得的一律 unclassified
ALIASES = {"usage": "bad_input", "bad_value": "bad_input", "internal": UNCLASSIFIED, "spec": "internal_bug",
           "timed_out": "timeout"}
# 工具自己明說這幾個（或 remedy.kind=needs_update）→ 立刻標壞（設定 health.trust_self_report 可以關掉）
IMMEDIATE_CODES = ("needs_config", "dependency_missing", "auth_expired")
REMEDY_LABELS = {"auto_fixable": "可以自動修（這一版 SYNOX 不會自動做）", "needs_update": "需要更新工具",
                 "needs_config": "需要設定", "needs_owner": "需要擁有者處理", "none": ""}

# 補救說明裡「看起來像指令」：命令列片段、管線與重導、網址、程式碼區塊。整段換成 SAFE_REMEDY。
_COMMAND_LIKE = [
    re.compile(r"`"),
    re.compile(r"\$\(|\$\{|&&|\|\||;\s*\w|\|\s*\w|>\s*\S|<\s*\S"),
    re.compile(r"(?i)\b(?:https?|ftp|file)://|\bwww\.\w"),
    re.compile(r"(?i)(?:^|\s)(?:\.?/|~/|[a-z]:\\)\S"),
    re.compile(r"(?im)^\s*[$#>]\s"),
    re.compile(r"(?i)\b(?:pip3?|npm|npx|yarn|pnpm|curl|wget|sudo|su|apt(?:-get)?|brew|winget|choco|powershell|pwsh|"
               r"cmd(?:\.exe)?|bash|sh|zsh|python3?|py|node|git|rm|del|rmdir|chmod|chown|regedit|reg|sc|net|"
               r"iex|invoke-\w+|start-process|set-executionpolicy)(?:\s+-{1,2}\w|\s+[a-z][\w.-]*\b)"),
    re.compile(r"(?i)\b(?:run|execute|type|paste|執行|輸入|貼上|打)\s*[:：]"),
]
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]")


def mask(text: Any) -> str:
    """遮掉像密鑰的片段（kit.TOKEN_PATTERNS，跟 log 遮罩同一份）、拿掉控制字元。"""
    from synox.packs.kit import mask_tokens
    return mask_tokens(_CONTROL.sub("", str(text if text is not None else "")))


def clip(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def one_line(text: Any, limit: int) -> str:
    """一行、遮掉密鑰、截長（順序：先遮再截，截不會把半個 token 留下來）。"""
    return clip(" ".join(mask(text).split()), limit)


def canonical(code: Any) -> str:
    """工具給的碼 → 表上的碼（不認得的、格式不對的＝unclassified）。"""
    text = str(code or "").strip().lower()
    text = ALIASES.get(text, text)
    return text if text in CODES else UNCLASSIFIED


def command_like(text: str) -> bool:
    return any(p.search(text) for p in _COMMAND_LIKE)


def clean_remedy_summary(text: Any) -> str:
    """補救說明：遮密鑰、一行、截長；看起來像指令就整段換成固定的一句（SYNOX 不執行任何補救）。"""
    raw = str(text or "")
    if not raw.strip():
        return ""
    if command_like(raw):
        return SAFE_REMEDY
    return one_line(raw, REMEDY_SUMMARY_MAX)


def clean_diag(diag: Any) -> Dict[str, str]:
    """diag：{短鍵: 字串}，每個值最多 200 字、整包（JSON）最多 1 KB；超過的鍵整個丟掉。值一律遮密鑰。"""
    if not isinstance(diag, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in list(diag.items())[:32]:
        if not isinstance(key, str) or not DIAG_KEY_RE.match(key):
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        item = one_line(value, DIAG_VALUE_MAX)
        trial = {**out, key: item}
        if len(json.dumps(trial, ensure_ascii=False).encode("utf-8")) > DIAG_MAX_BYTES:
            continue
        out = trial
    return out


@dataclass
class Failure:
    code: str = UNCLASSIFIED
    reason: str = ""
    scope: str = "tool"
    retry_ok: bool = False
    retry_after: Optional[int] = None
    remedy_kind: str = "none"
    remedy_id: str = ""
    remedy_summary: str = ""
    diag: Dict[str, str] = field(default_factory=dict)
    declared: bool = False          # 工具給了 v1 的 failure 物件（有合約）
    self_reported: bool = False     # 類別碼是工具自己說的（v1 或舊信封的 code；SYNOX 推的＝False）
    remedy_told: bool = False       # remedy.kind 是工具自己寫的（不是依類別碼補的預設）

    @property
    def info(self) -> CodeInfo:
        return CODES[self.code]

    @property
    def counts(self) -> bool:
        """算不算進門檻：scope 是 tool／pack／environment，而且這個碼本來就算（被限流不算）。"""
        return self.scope in COUNTED_SCOPES and self.info.counts

    @property
    def immediate(self) -> bool:
        """工具自己明說「要人處理」（needs_config、dependency_missing、auth_expired、remedy=needs_update）。"""
        if not self.self_reported or self.scope == "input":
            return False
        return self.code in IMMEDIATE_CODES or (self.remedy_told and self.remedy_kind == "needs_update")

    def retry_text(self) -> str:
        if self.retry_ok and self.retry_after:
            return f"after {int(self.retry_after)}s"
        return "yes" if self.retry_ok else "no"

    def to_envelope(self) -> dict:
        """正規化後的 v1 信封（給 log、網頁的擁有者看；diag 在這裡）。"""
        return {"ok": False, "error": self.reason, "code": self.code,
                "failure": {"v": VERSION, "scope": self.scope,
                            "retry": {"ok": self.retry_ok, "after_s": self.retry_after},
                            "remedy": {"kind": self.remedy_kind, "id": self.remedy_id, "summary": self.remedy_summary},
                            "diag": dict(self.diag)}}


def _defaults(code: str, reason: str, *, self_reported: bool) -> Failure:
    info = CODES[code]
    return Failure(code=code, reason=one_line(reason, REASON_MAX) or info.label, scope=info.scope, retry_ok=info.retry,
                   remedy_kind=info.remedy, remedy_id=info.remedy if info.remedy != "none" else "",
                   self_reported=self_reported)


def _apply_block(f: Failure, block: Any) -> Failure:
    """v1 的 failure 物件蓋過預設值（每個欄位各自檢查；不合的當作沒寫）。"""
    if not isinstance(block, dict):
        return f
    f.declared = True
    scope = block.get("scope")
    if isinstance(scope, str) and scope in SCOPES:
        f.scope = scope
    retry = block.get("retry")
    if isinstance(retry, dict):
        if isinstance(retry.get("ok"), bool):
            f.retry_ok = retry["ok"]
        after = retry.get("after_s")
        if isinstance(after, (int, float)) and not isinstance(after, bool) and 0 < after <= 7 * 86400:
            f.retry_after = int(after)
            f.retry_ok = True if not isinstance(retry.get("ok"), bool) else f.retry_ok
    remedy = block.get("remedy")
    if isinstance(remedy, dict):
        kind = remedy.get("kind")
        if isinstance(kind, str) and kind in REMEDY_KINDS:
            f.remedy_kind, f.remedy_told = kind, True
            f.remedy_id = kind if kind != "none" else ""
        rid = remedy.get("id")
        if isinstance(rid, str) and REMEDY_ID_RE.match(rid):
            f.remedy_id = rid
        f.remedy_summary = clean_remedy_summary(remedy.get("summary"))
    f.diag = clean_diag(block.get("diag"))
    return f


def from_envelope(envelope: Any, default_code: str = UNCLASSIFIED) -> Failure:
    """JSON 信封（v1、舊的只有 code、或只有 error／reason／message）→ Failure。"""
    if not isinstance(envelope, dict):
        return from_text(envelope)
    raw_code = envelope.get("code")
    reason = envelope.get("error") or envelope.get("reason") or envelope.get("message") or ""
    if not isinstance(reason, str):
        reason = json.dumps(reason, ensure_ascii=False, default=str)
    told = isinstance(raw_code, str) and bool(raw_code.strip())
    code = canonical(raw_code) if told else canonical(default_code)
    f = _defaults(code, reason, self_reported=told)
    return _apply_block(f, envelope.get("failure"))


def from_exception(error: BaseException) -> Failure:
    """例外 → Failure。SDK 的 ToolFailure／ToolError（kind=python 的 pack 也可以丟）照它的碼與 failure 物件；其他＝unclassified。"""
    code = getattr(error, "code", None)
    message = getattr(error, "message", None)
    block = getattr(error, "failure", None)
    if isinstance(code, str) and isinstance(message, str):
        envelope = {"ok": False, "error": message, "code": code}
        if isinstance(block, dict):
            envelope["failure"] = block
        return from_envelope(envelope)
    if isinstance(error, TimeoutError):
        f = _defaults("timeout", f"{type(error).__name__}: {error}", self_reported=False)
    else:
        f = _defaults(UNCLASSIFIED, f"{type(error).__name__}: {error}", self_reported=False)
    f.diag = clean_diag({"exception": type(error).__name__})
    return f


def from_text(text: Any, code: str = UNCLASSIFIED) -> Failure:
    """純文字的錯誤（沒有 JSON 信封）。"""
    return _defaults(canonical(code), str(text or ""), self_reported=False)


def from_cli_reply(reply: Any) -> Failure:
    """kind=cli 的 JsonCli 回覆（CliReply：code＝結束碼、data＝最後一個 JSON 物件）→ Failure。
    有 "ok": false 或 "code" 的 JSON＝工具的信封；結束碼 -1（叫不起來）＝dependency_missing；
    「沒有回 JSON（timed_out）」＝timeout；其他＝unclassified。"""
    data = getattr(reply, "data", None) or {}
    exit_code = getattr(reply, "code", None)
    if isinstance(data, dict) and (data.get("ok") is False or "code" in data or "failure" in data):
        return from_envelope(data)
    reason = ""
    if isinstance(data, dict):
        reason = str(data.get("reason") or data.get("error") or data.get("message") or "")
    reason = reason or f"結束碼 {exit_code}"
    if exit_code == -1:
        f = from_text(reason, "dependency_missing")
    elif "timed_out" in reason or "逾時" in reason:
        f = from_text(reason, "timeout")
    else:
        f = from_text(reason)
    f.diag = clean_diag({"exit_code": str(exit_code)})
    return f


def from_mcp_result(result: Any, text: str = "") -> Failure:
    """MCP tools/call 的 isError 結果：structuredContent 是 SDK 的信封就照它，否則用文字。"""
    sc = result.get("structuredContent") if isinstance(result, dict) else None
    if isinstance(sc, dict) and (sc.get("ok") is False or "failure" in sc):
        return from_envelope(sc)
    return from_text(text or "工具回報失敗")


def normalize(obj: Any) -> Failure:
    """任何一種失敗 → Failure（例外、dict 信封、CliReply、字串）。"""
    if isinstance(obj, Failure):
        return obj
    if isinstance(obj, BaseException):
        return from_exception(obj)
    if isinstance(obj, dict):
        return from_envelope(obj)
    if hasattr(obj, "data") and hasattr(obj, "code"):
        return from_cli_reply(obj)
    return from_text(obj)


def ai_line(f: Failure) -> str:
    """給 AI 的一行（≤ 300 字、沒有金鑰、沒有 diag）：
    FAIL <類別碼> retry=<yes|no|after Ns> | <人話原因> | 下一步：<SYNOX 依類別碼產生的建議>"""
    head = f"FAIL {f.code} retry={f.retry_text()} | "
    tail = f" | 下一步：{f.info.next}"
    room = AI_LINE_MAX - len(head) - len(tail)
    reason = one_line(f.reason, max(10, room)) or f.info.label
    return clip(head + reason + tail, AI_LINE_MAX)


def user_text(f: Failure, command: str) -> str:
    """給人看的：第一行照舊「❌ 指令：原因」，認得的類別再多一行（類別、補救建議）。"""
    lines = [f"❌ {command}：{one_line(f.reason, REASON_MAX)}"]
    extra = [] if f.code == UNCLASSIFIED else [f.info.label]
    if f.remedy_summary:
        extra.append(f.remedy_summary)
    elif REMEDY_LABELS.get(f.remedy_kind) and f.declared:
        extra.append(REMEDY_LABELS[f.remedy_kind])
    if f.retry_after:
        extra.append(f"{int(f.retry_after)} 秒後可以再試")
    if extra:
        lines.append("（" + "；".join(extra) + "）")
    return "\n".join(lines)


__all__ = ["ALIASES", "CODES", "COUNTED_SCOPES", "CodeInfo", "Failure", "IMMEDIATE_CODES", "REMEDY_KINDS", "SAFE_REMEDY",
           "SCOPES", "UNCLASSIFIED", "ai_line", "canonical", "clean_diag", "clean_remedy_summary", "command_like",
           "from_cli_reply", "from_envelope", "from_exception", "from_mcp_result", "from_text", "mask", "normalize",
           "one_line", "user_text"]
