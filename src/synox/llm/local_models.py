"""
本地模型的「清單、載入、卸載」（設定頁的模型下拉選單與「載入／釋放顯卡」按鈕用；docs/adr/0007 後續）。

    list_models(server, base_url, api_key="") -> {"models": [...], "can_load": bool, "notes": [...]}
    load(server, base_url, model, context_length=0, api_key="") -> 一句人話
    unload(server, base_url, model="", api_key="") -> 一句人話（model 空＝全部卸載＝釋放顯卡）
    reload(server, base_url, model, context_length, api_key="") -> {"ok", "message", "loaded_context", ...}
        （LM Studio：先估記憶體，撐不住就不動；只卸載**這個模型**的實例、用新的 context 載入、再讀回來確認）

**LM Studio 載入後一定讀回來確認**：`POST /api/v1/models/load` 帶了 context_length，之後再讀一次 `/api/v1/models`，
那個實例的 `loaded_instances[].config.context_length` 等於要的值才算成功；不一樣（伺服器沒照做）或讀不到＝失敗，
說 LM Studio 實際回報的是多少——畫面絕不說「換好了」而後端其實沒換。

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
           "vision": None, "tools": None, "size": 0, "quant": "", "params": "", "contexts": {}}
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
                        contexts={str(i["id"]): int((i.get("config") or {}).get("context_length") or 0) or None
                                  for i in inst},
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
            took = f"（花了 {float(secs):.1f} 秒）" if isinstance(secs, (int, float)) else ""
            if not context_length:
                return f"✅ 已載入 {model}{took}。"
            actual = loaded_context_of(server, base_url, model, api_key, opener=opener,
                                       instance=str(got.get("instance_id") or ""))
            if actual != int(context_length):
                raise LLMError(f"送出了 context {int(context_length)}，但 LM Studio 回報 {model} 現在載入的是 "
                               f"{actual or '（讀不到）'}：沒有換成功。" + manual_steps(model, int(context_length)))
            return f"✅ 已載入 {model}{took}，LM Studio 回報 context 是 {actual}。"
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


def loaded_context_of(server: str, base_url: str, model: str, api_key: str = "", *, opener=None,
                      instance: str = "") -> Optional[int]:
    """重新讀一次清單：這個模型（有給 instance 就是那個實例）**現在載入的** context；沒載入或讀不到＝None。"""
    try:
        listing = list_models(server, base_url, api_key, opener=opener)
    except LLMError:
        return None
    row = next((m for m in listing["models"] if m["id"] == model), None)
    if not row or not row["loaded"]:
        return None
    if instance and instance in row.get("contexts", {}):
        return row["contexts"][instance]
    return row["context"]


def manual_steps(model: str, context_length: int) -> str:
    """API 換不了時，自己在 LM Studio 怎麼做（GUI 或 lms 命令列）。"""
    return (f"自己換的做法：在 LM Studio 把 {model} 退出（Eject），再載入時把 Context Length 設成 {context_length}；"
            f"或在終端機跑 lms unload {model}，然後 lms load {model} --context-length {context_length}。")


def memory_check(row: dict, context_length: int, *, ram=None, options=None) -> dict:
    """載入前先估記憶體（local_advice 同一套估算，偏保守）：{"ok", "level", "need", "avail", "largest_safe", "message"}。
    可用記憶體不把這個模型現在佔的算回來（它可能在顯卡上），所以偏保守；量不到記憶體＝放行並說明。"""
    from synox.llm import local_advice
    avail, _total = ram if ram is not None else local_advice.system_ram()
    weights = int(row.get("size") or 0) or None
    need = local_advice.need_bytes(context_length, weights)
    level = local_advice.level_of(need, avail)
    cap = row.get("max_context")
    safe = [c for c in (options or local_advice.OPTIONS) if (not cap or c <= cap)
            and local_advice.level_of(local_advice.need_bytes(c, weights), avail) in ("ok", "tight")]
    largest = max(safe) if safe else None
    out = {"ok": level != "risky", "level": level, "need": need, "avail": avail, "largest_safe": largest, "message": ""}
    if level == "risky":
        out["message"] = (f"❌ 沒有載入：context {context_length} 估計要 {need / 1e9:.1f} GB，這台現在可用的記憶體約 "
                          f"{(avail or 0) / 1e9:.1f} GB，可能撐不住（估算，偏保守）。"
                          + (f"這台估計撐得住的最大是 {largest}。" if largest else "換小一點的模型，或先關掉其他吃記憶體的程式。"))
    elif level == "unknown":
        out["message"] = "量不到這台的可用記憶體，沒辦法先檢查撐不撐得住。"
    return out


def reload(server: str, base_url: str, model: str, context_length: int, api_key: str = "", *, opener=None,
           ram=None) -> dict:
    """LM Studio：用 context_length 重新載入這個模型。只在擁有者按按鈕時做（設定頁會先跳確認框）。
    順序：找到模型 → 檢查不超過模型上限、記憶體估得過 → 卸載**這個模型**的實例（別的模型不動）→ 用新的 context 載入
    → 讀回來確認。載入失敗就試著用原本的 context 載回去。回 {"ok", "message", "loaded_context", "requested"}；
    ok 只在讀回來的 context＝要的值時才是 True。"""
    model = (model or "").strip()
    if not model:
        raise LLMError("先選一個模型。")
    try:
        ctx = int(context_length)
    except (TypeError, ValueError):
        raise LLMError("context 要是整數。")
    from synox.llm.local import CONTEXT_MAX, CONTEXT_MIN
    if not CONTEXT_MIN <= ctx <= CONTEXT_MAX:
        raise LLMError(f"context 要在 {CONTEXT_MIN}～{CONTEXT_MAX}（0＝伺服器預設不能拿來重新載入）。")
    if server == "ollama":
        raise LLMError("Ollama 不用重新載入：context 是 SYNOX 每次請求帶過去的，Context 長度選好按「存起來」就會用。")
    if server != "lmstudio":
        raise LLMError(f"{SERVER_LABELS.get(server, server)} 的 context 是伺服器啟動時決定的（vLLM：--max-model-len），"
                       "SYNOX 換不了：改啟動參數再重開伺服器。")
    listing = list_models(server, base_url, api_key, opener=opener)
    if not listing["can_load"]:
        raise LLMError("這版 LM Studio 不能從 SYNOX 載入模型。" + manual_steps(model, ctx))
    row = next((m for m in listing["models"] if m["id"] == model), None)
    if row is None:
        raise LLMError(f"LM Studio 上找不到 {model}：按「列出模型」看有哪些。")
    if row.get("max_context") and ctx > int(row["max_context"]):
        raise LLMError(f"{model} 本身最多 {row['max_context']}，不能用 {ctx} 載入。")
    check = memory_check(row, ctx, ram=ram)
    if not check["ok"]:
        return {"ok": False, "message": check["message"], "loaded_context": row.get("context"), "requested": ctx,
                "largest_safe": check["largest_safe"]}
    old = row.get("context") if row["loaded"] else None
    if row["loaded"]:
        unload(server, base_url, model, api_key, opener=opener)
    try:
        load(server, base_url, model, ctx, api_key, opener=opener)
    except LLMError as e:
        tail = ""
        actual = loaded_context_of(server, base_url, model, api_key, opener=opener)
        if old and actual is None:                  # 這個模型被我們卸載了又沒載起來：試著照原本的載回去
            try:
                load(server, base_url, model, old, api_key, opener=opener)
                tail = f"已經用原本的 context {old} 載回去了。"
            except LLMError:
                tail = "原本的也沒能載回去：請在 LM Studio 手動載入。"
            actual = loaded_context_of(server, base_url, model, api_key, opener=opener)
        elif actual:
            tail = f"LM Studio 回報現在載入的是 {actual}。"
        return {"ok": False, "message": f"❌ 沒有換成 {ctx}：{e}" + ("　" + tail if tail else ""),
                "loaded_context": actual, "requested": ctx}
    actual = loaded_context_of(server, base_url, model, api_key, opener=opener)
    if actual != ctx:                                # load() 已經比過；這裡再保險一次（例如多個實例）
        return {"ok": False, "message": f"❌ 送出了 context {ctx}，但 LM Studio 回報現在載入的是 {actual or '（讀不到）'}："
                "沒有換成功。" + manual_steps(model, ctx), "loaded_context": actual, "requested": ctx}
    note = "（" + check["message"] + "）" if check["message"] else ""
    return {"ok": True, "message": f"✅ 已用 context {ctx} 重新載入 {model}，LM Studio 回報現在是 {actual}。{note}",
            "loaded_context": actual, "requested": ctx}


def pick_default(models: List[dict]) -> Optional[str]:
    """還沒填模型時幫忙選：已載入的第一個；都沒載入＝None（讓人自己選）。"""
    loaded = [m for m in models if m.get("loaded")]
    return loaded[0]["id"] if loaded else None
