"""
本地模型的「清單、載入、卸載」（設定頁的模型下拉選單與「載入／釋放顯卡」按鈕用；docs/adr/0007 後續）。

    list_models(server, base_url, api_key="") -> {"models": [...], "can_load": bool, "notes": [...]}
    load(server, base_url, model, context_length=0, api_key="") -> 一句人話
    unload(server, base_url, model="", api_key="") -> 一句人話（model 空＝全部卸載＝釋放顯卡）

每個伺服器各自用官方的 API（都是本機 HTTP，不跑命令列程式）：
- LM Studio：`GET /api/v1/models`（0.4 起；key、loaded_instances、capabilities.vision／trained_for_tool_use、
  max_context_length）；舊版退回 `GET /api/v0/models`（type＝vlm、state）。載入 `POST /api/v1/models/load`
  {model, context_length}，卸載 `POST /api/v1/models/unload` {instance_id}（每個已載入的實例各一次）。
- Ollama：`GET /api/tags`＋`GET /api/ps`（哪些在記憶體裡）；載入＝`POST /api/generate` {model, keep_alive}（沒有 prompt
  ＝只載入），卸載＝同一個 API 帶 keep_alive 0。
- vLLM／其他：只有 `GET /v1/models`（模型是伺服器啟動時決定的，不能從這裡載入）。

清單與卸載是唯讀或可逆的；載入會佔記憶體，所以只有擁有者在設定頁按按鈕才會做——**不是 AI 工具**，AI 叫不到。
embedding 模型不列（不能拿來聊天）。
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from synox.llm.base import LLMError
from synox.llm.local import SERVER_LABELS, LocalAdapter, _close, _HTTPProblem

OLLAMA_KEEP_ALIVE = "30m"
CHAT_TYPES = ("llm", "vlm")


def _adapter(server: str, base_url: str, api_key: str = "", opener=None, model: str = "") -> LocalAdapter:
    return LocalAdapter(model, server=server, base_url=base_url, api_key=api_key, opener=opener)


def _call(a: LocalAdapter, path: str, payload=None, method: str = "GET", *, long: bool = False):
    """GET／POST JSON。long＝載入模型（可能要等很久，用無進展逾時，不用 15 秒的探測逾時）。"""
    if not long:
        return a._get_json(path, payload, method)
    resp = a._open_or_raise(a._request(path, payload, method), a.timeout)
    try:
        return json.loads(resp.read().decode("utf-8", "replace") or "null")
    except ValueError:
        raise LLMError(f"{a._where()} 回的格式看不懂。")
    finally:
        _close(resp)


def _say(a: LocalAdapter, p: _HTTPProblem) -> LLMError:
    return LLMError(a._http_text(p))


# ── 清單 ──────────────────────────────────────────────────────────────

def _row(model_id: str, **kw) -> dict:
    row = {"id": model_id, "label": model_id, "loaded": False, "instances": [], "context": None, "max_context": None,
           "vision": None, "tools": None, "size": 0, "quant": "", "params": ""}
    row.update({k: v for k, v in kw.items() if v is not None})
    return row


def _lmstudio_v1(data: dict) -> List[dict]:
    out = []
    for m in data.get("models") or []:
        if not isinstance(m, dict) or m.get("type") not in ("llm",) or not m.get("key"):
            continue
        caps = m.get("capabilities") or {}
        inst = [i for i in m.get("loaded_instances") or [] if isinstance(i, dict) and i.get("id")]
        ctx = next((int((i.get("config") or {}).get("context_length") or 0) for i in inst), 0) or None
        out.append(_row(str(m["key"]), label=str(m.get("display_name") or m["key"]), loaded=bool(inst),
                        instances=[str(i["id"]) for i in inst], context=ctx,
                        max_context=int(m["max_context_length"]) if m.get("max_context_length") else None,
                        vision=bool(caps.get("vision")), tools=bool(caps.get("trained_for_tool_use")),
                        size=int(m.get("size_bytes") or 0), quant=str((m.get("quantization") or {}).get("name") or ""),
                        params=str(m.get("params_string") or "")))
    return out


def _lmstudio_v0(data: dict) -> List[dict]:
    out = []
    for m in data.get("data") or []:
        if not isinstance(m, dict) or m.get("type") not in CHAT_TYPES or not m.get("id"):
            continue
        loaded = m.get("state") == "loaded"
        out.append(_row(str(m["id"]), loaded=loaded, instances=[str(m["id"])] if loaded else [],
                        context=int(m["loaded_context_length"]) if m.get("loaded_context_length") else None,
                        max_context=int(m["max_context_length"]) if m.get("max_context_length") else None,
                        vision=m.get("type") == "vlm", tools="tool_use" in (m.get("capabilities") or []),
                        quant=str(m.get("quantization") or "")))
    return out


def list_models(server: str, base_url: str, api_key: str = "", *, opener=None) -> dict:
    """唯讀：這台伺服器有哪些可以聊天的模型、哪些已經載入。連不上＝LLMError（一句人話）。"""
    a = _adapter(server, base_url, api_key, opener)
    notes: List[str] = []
    try:
        if server == "lmstudio":
            try:
                models = _lmstudio_v1(_call(a, "/api/v1/models") or {})
            except _HTTPProblem as p:
                if p.status not in (404, 405):
                    raise
                models = _lmstudio_v0(_call(a, "/api/v0/models") or {})
                notes.append("這版 LM Studio 比較舊（沒有 /api/v1）：可以列出模型，但不能從這裡載入或卸載，請在 LM Studio 裡操作。")
                return {"models": _sorted(models), "can_load": False, "notes": notes}
            return {"models": _sorted(models), "can_load": True, "notes": notes}
        if server == "ollama":
            tags = _call(a, "/api/tags") or {}
            try:
                running = {str(m.get("name") or m.get("model") or "") for m in (_call(a, "/api/ps") or {}).get("models") or []}
            except (_HTTPProblem, LLMError):
                running = set()
            models = []
            for m in tags.get("models") or []:
                name = str(m.get("name") or m.get("model") or "")
                if not name or "embed" in name.lower():
                    continue
                details = m.get("details") or {}
                models.append(_row(name, loaded=name in running, instances=[name] if name in running else [],
                                   size=int(m.get("size") or 0), quant=str(details.get("quantization_level") or ""),
                                   params=str(details.get("parameter_size") or "")))
            return {"models": _sorted(models), "can_load": True, "notes": notes}
        data = _call(a, "/v1/models") or {}
        models = [_row(str(m["id"]), loaded=True, instances=[str(m["id"])],
                       max_context=int(m["max_model_len"]) if m.get("max_model_len") else None)
                  for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]
        notes.append(f"{SERVER_LABELS.get(server, server)} 的模型是啟動伺服器時決定的，不能從這裡載入或卸載。")
        return {"models": _sorted(models), "can_load": False, "notes": notes}
    except _HTTPProblem as p:
        raise _say(a, p)


def _sorted(models: List[dict]) -> List[dict]:
    return sorted(models, key=lambda m: (not m["loaded"], m["id"].lower()))


# ── 載入／卸載 ─────────────────────────────────────────────────────────

def load(server: str, base_url: str, model: str, context_length: int = 0, api_key: str = "", *, opener=None) -> str:
    model = (model or "").strip()
    if not model:
        raise LLMError("先選一個模型。")
    a = _adapter(server, base_url, api_key, opener, model)
    try:
        if server == "lmstudio":
            body: Dict[str, object] = {"model": model}
            if context_length:
                body["context_length"] = int(context_length)
            got = _call(a, "/api/v1/models/load", body, "POST", long=True) or {}
            secs = got.get("load_time_seconds")
            return f"✅ 已載入 {model}" + (f"（花了 {float(secs):.1f} 秒）" if isinstance(secs, (int, float)) else "") + \
                (f"，context {int(context_length)}" if context_length else "") + "。"
        if server == "ollama":
            body = {"model": model, "keep_alive": OLLAMA_KEEP_ALIVE}
            if context_length:
                body["options"] = {"num_ctx": int(context_length)}
            _call(a, "/api/generate", body, "POST", long=True)
            return f"✅ 已載入 {model}（閒置 30 分鐘後 Ollama 會自己釋放）。"
    except _HTTPProblem as p:
        raise _say(a, p)
    raise LLMError(f"{SERVER_LABELS.get(server, server)} 不能從這裡載入模型（要在伺服器啟動時指定）。")


def unload(server: str, base_url: str, model: str = "", api_key: str = "", *, opener=None) -> str:
    """model 空＝這台伺服器上已載入的全部卸載（「釋放顯卡」）。"""
    listing = list_models(server, base_url, api_key, opener=opener)
    if not listing["can_load"]:
        raise LLMError(f"{SERVER_LABELS.get(server, server)} 不能從這裡卸載模型。")
    targets = [m for m in listing["models"] if m["loaded"] and (not model or m["id"] == model)]
    if not targets:
        return "沒有已載入的模型，顯卡本來就是空的。" if not model else f"{model} 本來就沒有載入。"
    a = _adapter(server, base_url, api_key, opener)
    done: List[str] = []
    try:
        for m in targets:
            if server == "lmstudio":
                for inst in m["instances"] or [m["id"]]:
                    _call(a, "/api/v1/models/unload", {"instance_id": inst}, "POST")
            else:
                _call(a, "/api/generate", {"model": m["id"], "keep_alive": 0}, "POST")
            done.append(m["id"])
    except _HTTPProblem as p:
        raise _say(a, p)
    return "✅ 已卸載 " + "、".join(done) + "，記憶體／顯卡已經釋放。"


def pick_default(models: List[dict]) -> Optional[str]:
    """還沒填模型時幫忙選：已載入的第一個；都沒載入＝None（讓人自己選）。"""
    loaded = [m for m in models if m.get("loaded")]
    return loaded[0]["id"] if loaded else None
