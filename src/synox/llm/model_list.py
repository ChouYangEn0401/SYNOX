"""
設定頁「列出模型」的共用小工具（API 金鑰來源與來源目錄上的來源；本地內建照舊用 llm/local_models.py）。

- 先用來源自己的列模型功能（ntu_easy_llm 0.6 adapter 的 `list_models`，llm/easy_llm.py 的 SourceAdapter）。
- 這台的 ntu_easy_llm 沒有那個來源的新 adapter（0.5，或 0.6 預發布版）時：**OpenAI 與 OpenAI 相容服務**
  照 OpenAI 的規格自己問一次 `GET <網址>/models`（唯讀、不載入模型、只帶金鑰當 Authorization）；
  Anthropic／Gemini 沒有退路，回一句「更新 SYNOX 或重裝選用套件」。
- 列不出來＝一句白話（連不到／金鑰不對／沒有權限…，照錯誤種類 llm/kinds.py），結尾一律說「還是可以自己輸入模型名稱」。
- **金鑰永遠不出現在回應、日誌、錯誤訊息裡**：伺服器回的內文先 `scrub()`（把這把金鑰、像金鑰的字換成 ***）才放進訊息。

這裡不 import ntu_easy_llm。
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from typing import Callable, List, Optional

from synox.llm import kinds
from synox.llm.base import LLMError

OPENAI_BASE = "https://api.openai.com/v1"
TIMEOUT = 15.0
MANUAL = "還是可以在下面自己輸入模型名稱。"
UPDATE_HINT = "更新 SYNOX，或重裝選用套件（在 SYNOX 資料夾跑 `.venv\\Scripts\\python.exe -m pip install -e .[llm]`）"
LABELS = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Gemini", "openai_compat": "OpenAI 相容服務"}
# OpenAI 的 /models 什麼都列（語音、畫圖、embedding…）：明顯不能拿來聊天的不列
_NOT_CHAT = ("embed", "whisper", "tts", "dall-e", "moderation", "transcribe", "gpt-image", "sora")
_SECRETISH = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}|\bAIza[0-9A-Za-z_\-]{20,}|\bgh[pousr]_[A-Za-z0-9]{12,}|"
                        r"(?i:\bbearer\s+[A-Za-z0-9._\-]{8,})")

Opener = Callable[[urllib.request.Request, float], object]


def scrub(text, *secrets: str) -> str:
    """把金鑰從字裡拿掉（伺服器有時會把收到的金鑰原樣回在錯誤裡）：這幾把金鑰本身＋像金鑰的字 → ***。"""
    out = str(text or "")
    for s in secrets:
        s = str(s or "")
        if len(s) >= 4:
            out = out.replace(s, "***")
    return _SECRETISH.sub("***", out)


def _default_opener(base_url: str) -> Opener:
    """本機／家裡網路的網址不走系統 proxy（跟本地模型一樣）；外面的服務照系統設定走。"""
    from synox.llm.local import default_opener, is_local_url
    if is_local_url(base_url):
        return default_opener
    return lambda request, timeout: urllib.request.urlopen(request, timeout=timeout)


def _models_url(base_url: str) -> str:
    return base_url.strip().rstrip("/") + "/models"


def _rows(data) -> List[dict]:
    rows = []
    items = data.get("data") if isinstance(data, dict) else data
    for m in items or []:
        mid = str(m.get("id") or "") if isinstance(m, dict) else str(m or "")
        if not mid or any(x in mid.lower() for x in _NOT_CHAT):
            continue
        rows.append({"id": mid, "label": str((m.get("display_name") or m.get("name") or "") if isinstance(m, dict)
                                              else ""), "context": None, "loaded": None, "vision": None,
                     "tools": None})
    rows.sort(key=lambda r: r["id"].lower())
    return rows


def openai_style(base_url: str, api_key: str = "", *, opener: Optional[Opener] = None,
                 timeout: float = TIMEOUT, where: str = "") -> List[dict]:
    """OpenAI 規格的 `GET <base_url>/models` → [{id, label, …}]（跟 SourceAdapter.list_models 同一種樣子）。
    失敗丟 LLMError（一句中文、帶 kind；內文裡的金鑰已經拿掉）。"""
    base_url = str(base_url or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise LLMError("要先填伺服器網址（http:// 或 https:// 開頭）。", kind="bad_request")
    where = where or base_url
    request = urllib.request.Request(_models_url(base_url), method="GET",
                                     headers={"Accept": "application/json", "User-Agent": "SYNOX"})
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    open_ = opener or _default_opener(base_url)
    try:
        resp = open_(request, timeout)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        kind = kinds.http_kind(e.code, body)
        if e.code == 404 and kind != "model_not_found":
            raise LLMError(f"{where}：這個服務沒有提供模型清單（404），或網址少了 /v1。", kind="bad_request")
        raise LLMError(kinds.message_for(kind, where, scrub(body, api_key), e.code), kind=kind)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        reason = str(getattr(e, "reason", "") or e).lower()
        kind = "timeout" if "timed out" in reason or isinstance(e, TimeoutError) else "connection"
        raise LLMError(kinds.message_for(kind, where), kind=kind)
    try:
        raw = resp.read()
        data = json.loads(raw.decode("utf-8", "replace") or "null")
    except ValueError:
        raise LLMError(kinds.message_for("bad_response", where), kind="bad_response")
    finally:
        close = getattr(resp, "close", None)
        if callable(close):
            close()
    if not isinstance(data, (dict, list)):
        raise LLMError(kinds.message_for("bad_response", where), kind="bad_response")
    return _rows(data)


def fallback(llm: dict) -> Optional[Callable[[], List[dict]]]:
    """沒有新 adapter 時的退路（只有 OpenAI 規格的兩種）；其他＝None。llm 的 api_key 要已經是明文。"""
    kind = str(llm.get("kind") or "")
    key = str(llm.get("api_key") or "")
    if kind == "openai_compat":
        base = str(llm.get("base_url") or "")
        return lambda: openai_style(base, key, where=base)
    if kind == "openai":
        return lambda: openai_style(OPENAI_BASE, key, where="OpenAI")
    return None


def cannot_list(kind: str) -> str:
    """這一版列不出這種來源的模型：一句話＋怎麼更新。"""
    label = LABELS.get(kind, "這個來源")
    return f"這一版的 ntu_easy_llm 還不能列出 {label} 的模型：{UPDATE_HINT}就可以。{MANUAL}"


def failed(error: BaseException, *secrets: str) -> str:
    """列不出來的原因（一句白話）＋「還是可以自己輸入」。金鑰拿掉。"""
    text = scrub(str(error), *secrets).strip() or "原因不明"
    return f"❌ 列不出模型：{text}" + ("" if text.endswith("。") else "。") + MANUAL


# ── 「測一下」失敗時：分辨「模型打錯／不能用」與「連不到」───────────────────


RELIST_KINDS = ("model_not_found", "permission")


def test_advice(kind: str) -> str:
    """測一下失敗時加在錯誤後面的一句（依種類）；空＝不加。"""
    kind = str(kind or "")
    if kind == "model_not_found":
        return "→ 模型名稱可能打錯，或伺服器上沒有這個模型：按「列出模型」重選一個。"
    if kind == "permission":
        return "→ 這個帳號／金鑰不能用這個模型：按「列出模型」看你能用哪些，重選一個。"
    if kind in ("connection", "timeout"):
        return "→ 這是連線的問題，跟模型名稱無關：先確認網址、網路，或伺服器有沒有開。"
    if kind == "auth_invalid":
        return "→ 金鑰的問題，跟模型名稱無關：重新填 API 金鑰。"
    return ""
