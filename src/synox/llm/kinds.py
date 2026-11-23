"""
錯誤種類 → 一句中文（docs/adr/0046）。

ntu_easy_llm 0.6 的錯誤都帶 `.kind`（ErrorKind，字串值固定）：SYNOX 照種類說人話，不再靠狀態碼猜。
這裡只用字串，不 import ntu_easy_llm（沒裝它也能用；它的 ErrorKind 是 StrEnum，str() 就是這些值）。

    message_for("quota_exhausted", "OpenAI")        → 「OpenAI：額度用完了……」
    message_for("connection", "http://127.0.0.1:1234/v1")
"""

from __future__ import annotations

from typing import Optional

# 種類 → (短標籤, 下一步怎麼做)。{where} 換成來源的名字或網址。
HINTS = {
    "quota_exhausted": ("額度用完", "等額度重置，或到設定改用別的來源。"),
    "auth_invalid": ("金鑰不對或已失效", "到設定重新填金鑰（只在這台電腦的網頁填）。"),
    "rate_limited": ("請求太頻繁", "等一下再試。"),
    "permission": ("沒有權限", "這把金鑰不能用這個模型或功能。"),
    "overloaded": ("服務忙碌", "等一下再試。"),
    "context_too_long": ("對話太長", "超過模型收得下的長度：用 /ai_reset 清掉對話紀錄，或換 context 比較大的模型。"),
    "model_not_found": ("找不到模型", "檢查模型名稱（設定頁可以「列出模型」）。"),
    "tools_unsupported": ("不支援工具呼叫", "到設定把「工具呼叫」關掉（改用文字協定），或換一個模型。"),
    "bad_request": ("請求被拒", "模型名稱或參數不對。"),
    "timeout": ("等太久沒有回應", "模型可能還在載入或太忙；等一下再試，或把逾時調長。"),
    "connection": ("連不到 {where}", "檢查網址、網路，或伺服器有沒有開。"),
    "link_changed": ("API 連結已更換", "請向服務提供者拿新連結，在這台的終端機換掉。"),
    "trust": ("加密或金鑰核對失敗", "為了安全不會自動換來源；請檢查這個來源的設定。"),
    "server_error": ("伺服器出錯", "等一下再試。"),
    "bad_response": ("回的格式看不懂", "是不是網址填錯了？"),
    "unknown": ("出錯了", ""),
}


def label_of(kind) -> str:
    """種類的短標籤（「額度用完」…）；不認得＝「出錯了」。"""
    return HINTS.get(str(kind or "unknown"), HINTS["unknown"])[0].replace("{where}", "服務")


def message_for(kind, where: str, detail: str = "", status: Optional[int] = None) -> str:
    """一句給人看的錯誤：「<來源>：<標籤>（狀態碼）。<下一步>」＋（有的話）伺服器說的話（最多 160 字、壓成一行）。
    detail 不可以放金鑰；呼叫端只傳伺服器回的內文。"""
    key = str(kind or "unknown")
    label, hint = HINTS.get(key, HINTS["unknown"])
    code = f"（{int(status)}）" if status else ""
    if "{where}" in label:
        text = label.format(where=where) + code + "。"
    else:
        text = f"{where}：{label}{code}。"
    if hint:
        text += hint
    snippet = " ".join((detail or "").split())[:160]
    return text + (f"\n伺服器說：{snippet}" if snippet else "")


_QUOTA = ("insufficient_quota", "quota_exceeded", "key_exhausted", "exceeded your current quota", "credit balance")
_CONTEXT = ("context_length_exceeded", "maximum context length", "context size has been exceeded")
# 模型名稱打錯／伺服器上沒有：OpenAI 是 404＋model_not_found，相容伺服器常常是 400／404＋「model … not found／does not exist」
_MODEL = ("model_not_found", "no such model", "model not found", "does not exist", "not found")


def http_kind(status: int, body: str = "") -> str:
    """HTTP 狀態碼＋內文 → 種類（SYNOX 自己打 HTTP 的 adapter 用，例如 llm/local.py；規則跟 ntu_easy_llm 0.6 的通用規則一致的子集）。"""
    low = (body or "").lower()
    status = int(status or 0)
    if 400 <= status < 500 and any(m in low for m in _QUOTA) or status == 402:
        return "quota_exhausted"
    if status == 401:
        return "auth_invalid"
    if status == 429:
        return "rate_limited"
    if status == 403:
        return "permission"
    if status in (408, 504, 524):
        return "timeout"
    if status == 413 or any(m in low for m in _CONTEXT):
        return "context_too_long"
    if status == 404 and "model" in low or status in (400, 404, 422) and "model" in low and \
            any(m in low for m in _MODEL):
        return "model_not_found"
    if status in (503, 529):
        return "overloaded"
    if 400 <= status < 500:
        return "bad_request"
    if status >= 500:
        return "server_error"
    return "unknown"


def kind_of(error) -> Optional[str]:
    """任何例外的種類字串（有 `.kind` 才有；沒有＝None）。"""
    value = getattr(error, "kind", None)
    if value is None or value == "":
        return None
    return str(value)
