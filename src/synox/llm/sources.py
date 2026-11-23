"""
AI 來源目錄（docs/adr/0046）：設定頁「來源 → 認證 → 服務 → 模型 → 細節」那幾步的資料，以及 kind=source 的檢查。

目錄本身來自 ntu_easy_llm 0.6 的 `catalog()`（分類樹：local／remote/api_key／remote/subscription）；SYNOX 只加自己的東西：

- 「本地」底下第一個是 **SYNOX 內建的本地模型**（kind=local，llm/local.py，ADR 0007：context 建議、載入／卸載…照舊）。
- 「訂閱登入」底下第一個是 **SYNOX 內建的 Claude Code**（kind=claude_code，`claude -p`）。
- API 金鑰的 OpenAI／Anthropic／Gemini／OpenAI 相容：照舊存成舊的 kind（openai、anthropic、gemini、openai_compat），
  所以舊版 SYNOX 也讀得懂；這台的 ntu_easy_llm 沒有那個來源的新 adapter 時照舊走 `agent.chat`（llm/easy_llm.py）。
- 其他（LLOP、訂閱、ntu_easy_llm 的本地 adapter…）存成 kind=source：

    {"kind": "source", "source": "remote/api_key/llop", "model": "any",
     "source_options": {"llop_profile": "default", "transport": "auto", "max_tokens": 4096}}

  `api_key`（要的來源才有）跟舊的一樣：保管箱引用 "vault:…"、"env:…"；網頁收到明文就放進保管箱。
- 沒裝 ntu_easy_llm（或是 0.5）：目錄只有 SYNOX 內建的兩個＋四個舊來源（反灰、寫怎麼裝）；其他來源要 0.6 才看得到。
- 訂閱來源標「只給本人使用」（不推薦拿來服務別人、條款由使用者自己確認：只標，不擋；使用聲明見 docs/security.md）。

這個模組 import 時不 import ntu_easy_llm；`validate` 只檢查形狀（config.py 讀設定時用，沒裝套件也能檢查）。
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional

KIND = "source"
TEST_SOURCE = "local/fake"     # ntu_easy_llm 的測試來源（照劇本回話）：不在目錄上；選項可以是劇本（清單）
SOURCE_RE = re.compile(r"^(local/[a-z0-9_]+|remote/(api_key|subscription)/[a-z0-9_]+)$")
OPTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_OPTIONS = 24
# 選項的名字不能是金鑰欄位（金鑰只放 api_key，而且是引用）
SECRET_NAMES = frozenset({"api_key", "apikey", "key", "token", "access_token", "refresh_token", "auth_token", "bearer",
                          "password", "passwd", "pass", "secret", "secret_key", "client_secret", "private_key",
                          "authorization"})
_SECRET_LIKE = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}|\bAIza[0-9A-Za-z_\-]{30,}|\bgh[pousr]_[A-Za-z0-9]{20,}|"
                          r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:\bbearer\s+[A-Za-z0-9._\-]{12,})")
SUBSCRIPTION_NOTE = "只給本人使用（你個人的訂閱帳號；不建議拿來服務別人。使用前請自行閱讀該服務的使用條款）"
MORE_HINT = "裝 ntu_easy_llm 0.6 以上，這裡會多出 LLOP、訂閱登入等更多來源。"

# 內建的兩個（SYNOX 自己的 adapter），在目錄上的位置與名字
BUILTIN_LOCAL = {"id": "synox/local", "label": "SYNOX 內建（Ollama、vLLM、LM Studio、其他相容伺服器）",
                 "kind": "local", "note": "有 context 建議、列出模型、載入／卸載（ADR 0007）"}
BUILTIN_CLAUDE = {"id": "synox/claude_code", "label": "Claude Code（SYNOX 內建：這台登入的 claude）",
                  "kind": "claude_code", "note": ""}
# 舊的四種 kind ↔ 目錄位置
LEGACY_BY_SOURCE = {"remote/api_key/openai": "openai", "remote/api_key/anthropic": "anthropic",
                    "remote/api_key/gemini": "gemini", "remote/api_key/openai_compatible": "openai_compat"}
LEGACY_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic（Claude API）", "gemini": "Google Gemini",
                 "openai_compat": "其他 OpenAI 相容服務（公司閘道等）"}
FAMILY_LABELS = {"local": "本地（這台或家裡網路的電腦）", "remote": "遠端服務", "none": "先不用 AI"}
AUTH_LABELS = {"api_key": "API 金鑰", "subscription": "訂閱登入（這台已登入的官方程式）"}


def _looks_secret(value) -> bool:
    return isinstance(value, str) and bool(_SECRET_LIKE.search(value))


def check_url(url: str, where: str = "llm.base_url") -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{where} 要以 http:// 或 https:// 開頭。")
    if parts.username or parts.password or _looks_secret(url):
        raise ValueError(f"{where} 不能帶帳號、密碼或金鑰（金鑰另外填）。")
    return url.rstrip("/")


def validate(llm: dict) -> dict:
    """kind=source 的 llm 那一塊 → {"source","model","base_url","api_key","options"}。只看形狀；寫錯丟 ValueError（中文）。"""
    source = str(llm.get("source") or "").strip()
    if not SOURCE_RE.match(source):
        raise ValueError("llm.source 要是來源目錄上的路徑（例如 remote/api_key/llop、local/ollama、"
                         "remote/subscription/claude）。")
    base_url = check_url(llm.get("base_url") or "")
    options = llm.get("source_options")
    options = {} if options is None else options
    if not isinstance(options, dict):
        raise ValueError("llm.source_options 要是一個 {…} 物件。")
    if len(options) > MAX_OPTIONS:
        raise ValueError(f"llm.source_options 最多 {MAX_OPTIONS} 項。")
    clean = {}
    for k, v in options.items():
        name = str(k)
        if not OPTION_RE.match(name):
            raise ValueError(f"llm.source_options 的名字只能是小寫英數與底線（{name!r} 不行）。")
        if name in SECRET_NAMES:
            raise ValueError(f"llm.source_options 不能放金鑰（{name}）：金鑰填在 api_key（存進保管箱）。")
        if v is not None and not isinstance(v, (str, int, float, bool)) and source != TEST_SOURCE:
            raise ValueError(f"llm.source_options.{name} 只能是字、數字或 true／false。")
        if _looks_secret(v):
            raise ValueError(f"llm.source_options.{name} 看起來像金鑰：金鑰填在 api_key（存進保管箱）。")
        clean[name] = v
    api_key = llm.get("api_key") or ""
    if not isinstance(api_key, str):
        raise ValueError("llm.api_key 要是字串（\"vault:…\" 或 \"env:…\"）。")
    return {"source": source, "model": str(llm.get("model") or "").strip(), "base_url": base_url,
            "api_key": api_key, "options": clean}


def default_timeout(source: str, base_url: str = "") -> float:
    """沒寫 source_options.timeout：本地（或指到這台／家裡網路）＝450 秒；訂閱＝180 秒；其他＝90 秒。"""
    from synox.llm.local import DEFAULT_TIMEOUT, is_local_url
    if source.startswith("local/") or (base_url and is_local_url(base_url)):
        return float(DEFAULT_TIMEOUT)
    if source.startswith("remote/subscription/"):
        return 180.0
    return 90.0


# ── 目錄（給設定頁）───────────────────────────────────────────────────


def _catalog(locale: str = "zh-TW"):
    """ntu_easy_llm 0.6 的目錄根節點；沒有＝None。"""
    from synox.llm.easy_llm import contract
    if contract() is None:
        return None
    try:
        from ntu_easy_llm.catalog import catalog
    except ImportError:
        return None
    return catalog(locale=locale)


def label_of(source: str, locale: str = "zh-TW") -> str:
    root = _catalog(locale)
    node = root.find(source) if root is not None else None
    if node is not None and node.label:
        return str(node.label)
    legacy = LEGACY_BY_SOURCE.get(source)
    return LEGACY_LABELS.get(legacy, source) if legacy else source


def unavailable_text(source: str, reason: str = "") -> str:
    """這台不能用某個來源：一句中文（ntu_easy_llm 給的英文原因翻一下；中文的原樣用）。"""
    label = label_of(source)
    why = str(reason or "").strip()
    if " / " in why and re.search(r"[一-鿿]", why.split(" / ", 1)[0]):
        why = why.split(" / ", 1)[0].strip()          # 「中文 / English」只留中文
    low = why.lower()
    if not why:
        why = "這台還不能用"
    elif "no adapter" in low:
        why = "這一版的 ntu_easy_llm 還沒有這個來源的 adapter（等新版）"
    elif low.startswith("install ") or "ntu_easy_llm[" in low and not re.search(r"[\u4e00-\u9fff]", why):
        why = f"要先安裝 {why.split('install ', 1)[-1].split(' first')[0]}"
    elif low.startswith("adapter"):
        why = f"這台的 adapter 不能用（{why}）"
    return f"{label}：{why}。"


def _field(f) -> dict:
    d = f.to_dict() if hasattr(f, "to_dict") else dict(f)
    d["choices"] = list(d.get("choices") or [])
    return d


def _llop_choices(field: dict) -> dict:
    """LLOP 設定檔：列這台已註冊的（經 ntu_easy_llm；SYNOX 不 import llmop）。註冊在這台的終端機做。"""
    try:
        from ntu_easy_llm.catalog import list_llop_profiles
        names = list_llop_profiles()
    except Exception:
        names = []
    field = dict(field)
    field["choices"] = list(names)
    field["help"] = ("先在這台電腦的終端機用 LLOP 的 SDK 註冊（服務提供者會給你指令）；註冊好按「重新整理」，"
                     "這裡只選設定檔名稱。")
    return field


def _service(node, auth: str, legacy_ok: bool) -> dict:
    path = node.path
    legacy = LEGACY_BY_SOURCE.get(path)
    available = bool(node.available)
    reason = "" if available else unavailable_text(path, node.unavailable_reason)
    if legacy and not available and legacy_ok:      # 0.6 預發布版還沒有新 adapter：SYNOX 照舊走 agent.chat，照樣能用
        available, reason = True, ""
    fields = [_field(f) for f in node.fields]
    fields = [_llop_choices(f) if f.get("kind") == "llop_profile" else f for f in fields]
    out = {"id": path, "source": path, "label": node.label or path, "available": available, "reason": reason,
           "kind": legacy or KIND, "fields": fields, "detail_fields": [_field(f) for f in node.detail_fields],
           "builtin": False, "note": SUBSCRIPTION_NOTE if auth == "subscription" else "",
           "extra": getattr(node, "extra", "") or ""}
    if legacy:
        out["provider"] = legacy
    return out


def _legacy_only(legacy_ok: bool, reason: str) -> List[dict]:
    """沒有 0.6 目錄時：四個舊來源（裝了 0.5 就能用；沒裝就反灰寫怎麼裝）。"""
    from synox.llm.easy_llm import LEGACY_SOURCES
    rows = []
    for kind, path in LEGACY_SOURCES.items():
        fields = [{"name": "secret", "kind": "secret", "required": kind != "openai_compat", "secret": True,
                   "default": None, "choices": [], "label": "API 金鑰", "help": ""},
                  {"name": "model", "kind": "model", "required": True, "secret": False, "default": None,
                   "choices": [], "label": "模型", "help": ""}]
        if kind == "openai_compat":
            fields.insert(0, {"name": "base_url", "kind": "url", "required": True, "secret": False, "default": None,
                              "choices": [], "label": "伺服器網址", "help": ""})
        rows.append({"id": path, "source": path, "label": LEGACY_LABELS[kind], "available": legacy_ok,
                     "reason": "" if legacy_ok else reason, "kind": kind, "provider": kind, "fields": fields,
                     "detail_fields": [], "builtin": False, "note": "", "extra": ""})
    return rows


def tree(*, locale: str = "zh-TW") -> dict:
    """設定頁的目錄：{"families": [{id, label, auths: [{id, label, services: [...]}]}], "easy_llm", "contract", "hint"}。
    每個 service：id、label、available、reason（不能用的原因）、kind（存進 config 的 llm.kind）、source（目錄路徑）、
    provider（舊的四種）、fields（連線那一步）、detail_fields（細節）、builtin、note。每次重算（裝了新東西馬上看得到）。"""
    from synox.llm.easy_llm import MISSING, NEEDS_06, installed, version_text
    legacy_ok = installed()
    root = _catalog(locale)
    local_services = [dict(BUILTIN_LOCAL, available=True, reason="", builtin=True, source="", fields=[],
                           detail_fields=[])]
    sub_services = [dict(BUILTIN_CLAUDE, available=True, reason="", builtin=True, source="", fields=[],
                         detail_fields=[])]
    key_services: List[dict] = []
    if root is None:
        key_services = _legacy_only(legacy_ok, MISSING)
        hint = MORE_HINT if legacy_ok else ""
    else:
        hint = ""
        for fam in root.children:
            if fam.path == "local":
                local_services += [_service(n, "", legacy_ok) for n in fam.leaves()]
                continue
            for group in fam.children:
                auth = group.path.rsplit("/", 1)[-1]
                rows = [_service(n, auth, legacy_ok) for n in group.leaves()]
                if auth == "api_key":
                    key_services += rows
                elif auth == "subscription":
                    sub_services += rows
    families = [
        {"id": "local", "label": FAMILY_LABELS["local"], "auths": [{"id": "", "label": "", "services": local_services}]},
        {"id": "remote", "label": FAMILY_LABELS["remote"], "auths": [
            {"id": "api_key", "label": AUTH_LABELS["api_key"], "services": key_services},
            {"id": "subscription", "label": AUTH_LABELS["subscription"], "services": sub_services}]},
        {"id": "none", "label": FAMILY_LABELS["none"], "auths": []},
    ]
    version = version_text()
    if version and root is None and legacy_ok:
        hint = NEEDS_06.split("。")[0] + "。" + MORE_HINT
    return {"families": families, "easy_llm": version, "contract": root is not None, "hint": hint}


def find_service(source: str, *, locale: str = "zh-TW") -> Optional[dict]:
    """目錄上的一個服務（kind=source 或舊的四種用路徑找）；沒有＝None。"""
    for fam in tree(locale=locale)["families"]:
        for auth in fam["auths"]:
            for s in auth["services"]:
                if s.get("source") == source:
                    return s
    return None


def clean_options(service: dict, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """網頁送來的選項 → 只留這個服務宣告的欄位（連線那一步的非網址／模型／金鑰欄位＋細節欄位），照型別轉好。
    空字串＝沒填（不寫進設定）。型別不對丟 ValueError（中文）。"""
    raw = dict(raw or {})
    specs = [f for f in service.get("fields", []) if f["name"] not in ("base_url", "model", "secret")] + \
        list(service.get("detail_fields", []))
    out: Dict[str, Any] = {}
    for f in specs:
        name, kind = f["name"], f.get("kind")
        if name not in raw:
            continue
        value = raw[name]
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        label = f.get("label") or name
        try:
            if kind == "int":
                value = int(value)
                if value < 0:
                    raise ValueError
            elif kind == "float":
                value = float(value)
                if value < 0:
                    raise ValueError
            elif kind == "bool":
                if isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "on")
                value = bool(value)
            else:
                value = str(value).strip()
        except (TypeError, ValueError):
            raise ValueError(f"「{label}」要是{'整數' if kind == 'int' else '數字'}（0 以上）。")
        if kind == "choice" and f.get("choices") and value not in f["choices"]:
            raise ValueError(f"「{label}」只能是 " + "、".join(str(c) for c in f["choices"]) + "。")
        if kind == "llop_profile" and not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", str(value)):
            raise ValueError(f"「{label}」只能是英數與 _ . -。")
        if isinstance(value, str) and _looks_secret(value):
            raise ValueError(f"「{label}」看起來像金鑰：金鑰填在 API 金鑰那一格。")
        out[name] = value
    return out
