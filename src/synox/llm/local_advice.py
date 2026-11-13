"""
本地模型的 context-size 建議（docs/adr/0007）：純函式（記憶體由呼叫的人傳進來，或 system_ram() 量），可以單獨測。

    advice = advise(avail_ram=…, total_ram=…, weights_bytes=…, kv_per_token=…, model_max_ctx=…,
                    prompt_tokens=…, max_tokens=1024)
    advice["options"]       每個預設選項：ctx、level（ok｜tight｜risky｜unknown）、truncates、說明
    advice["recommended"]   推薦的值（偏保守：夠放 SYNOX 的提示＋對話紀錄＋回覆的最小那個）
    advice["notes"]         「這是估算」與估算的根據

估算（**是估算，不是量測**）：需要的記憶體 ≈ 模型權重（/api/tags 的 size）＋ KV cache
（每個 token：2（K、V）× 有注意力的層數 × kv_heads × head_dim × 2 bytes（f16），資料取自 /api/show 的 model_info，
缺就用保守估計）＋ 執行時的額外（0.6 GB＋權重的 10%）。對照「這台現在可用的 RAM」：≤ 60%＝建議、≤ 85%＝吃緊、
其他＝可能撐不住。這台是 CPU 推論、資源脆弱，所以門檻刻意偏保守；模型已經載入時可用記憶體會少算（也是偏保守）。

截斷：SYNOX 的提示（系統說明＋全部工具規格）用字元數 ÷ 2.5 估 token（中文偏保守）；context 小於
「提示＋回覆上限」的選項標成「會截斷」（測試紀錄：Ollama 預設 4096 超過時會靜默丟掉最前面）。
"""

from __future__ import annotations

import math
import sys
from typing import List, Optional, Tuple

OPTIONS = (4096, 8192, 16384, 32768, 65536, 131072)
CHARS_PER_TOKEN = 2.5
DEFAULT_PROMPT_TOKENS = 3000          # 量不到 SYNOX 實際提示時的保守估計（soul.md 最多 2000 字＋工具說明）
HISTORY_RESERVE = 1536                # 對話紀錄（最近 6 輪）與工具結果要留的空間
OVERHEAD_BYTES = 0.6e9
OVERHEAD_RATIO = 0.10
OK_RATIO, TIGHT_RATIO = 0.60, 0.85
# 沒連上 Ollama 時的靜態假設：常見 7–9B、Q4 的模型
STATIC_WEIGHTS = 6.0e9
STATIC_KV_PER_TOKEN = 2 * 36 * 8 * 128 * 2       # 36 層、8 個 kv head、head_dim 128、f16 ≈ 144 KB／token
LEVEL_TEXT = {"ok": "建議", "tight": "吃緊", "risky": "可能撐不住", "unknown": "量不到記憶體"}


def tokens_from_chars(chars: int) -> int:
    return int(math.ceil(max(0, int(chars or 0)) / CHARS_PER_TOKEN))


def system_ram() -> Tuple[Optional[int], Optional[int]]:
    """(可用, 總共) bytes；Windows 用 GlobalMemoryStatusEx，其他系統試 sysconf；量不到＝(None, None)。"""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            mem = _Mem()
            mem.dwLength = ctypes.sizeof(_Mem)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                return None, None
            return int(mem.ullAvailPhys), int(mem.ullTotalPhys)
        import os
        page = os.sysconf("SC_PAGE_SIZE")
        return int(os.sysconf("SC_AVPHYS_PAGES") * page), int(os.sysconf("SC_PHYS_PAGES") * page)
    except Exception:
        return None, None


def kv_bytes_per_token(model_info: Optional[dict]) -> Tuple[int, str]:
    """(每個 token 的 KV cache bytes, 怎麼來的：exact｜rough｜static)。"""
    info = model_info or {}
    arch = info.get("general.architecture") or ""

    def get(name):
        value = info.get(f"{arch}.{name}")
        return value if value not in (None, "", []) else None

    layers = get("block_count")
    heads = get("attention.head_count")
    if isinstance(heads, list):
        heads = max((int(h) for h in heads), default=0) or None
    kv = get("attention.head_count_kv")
    embed = get("embedding_length")
    key_len = get("attention.key_length") or (int(embed) // int(heads) if embed and heads else None)
    val_len = get("attention.value_length") or key_len
    if layers and key_len and (kv is not None or heads):
        if isinstance(kv, list):                       # 每層不同（混合架構：線性注意力的層是 0）
            total_kv = sum(int(x) for x in kv)
        else:
            total_kv = int(layers) * int(kv if kv is not None else heads)
        return int(total_kv * (int(key_len) + int(val_len)) * 2), "exact"
    if layers and embed:                               # 缺 kv head：當成沒有 GQA（每層 K、V 各一份 embedding），偏大
        return int(int(layers) * int(embed) * 2 * 2), "rough"
    return STATIC_KV_PER_TOKEN, "static"


def _gb(n) -> str:
    return f"{n / 1e9:.1f} GB"


def advise(*, avail_ram: Optional[int], total_ram: Optional[int] = None, weights_bytes: Optional[int] = None,
           kv_per_token: Optional[int] = None, kv_source: str = "static", model_max_ctx: Optional[int] = None,
           prompt_tokens: Optional[int] = None, max_tokens: int = 1024, source: str = "ollama",
           options=OPTIONS) -> dict:
    """純函式：每個選項的等級＋建議值＋說明。source：ollama（讀到模型資料）｜static（沒連上，用靜態假設）。"""
    measured = prompt_tokens is not None
    prompt = int(prompt_tokens) if measured else DEFAULT_PROMPT_TOKENS
    weights = int(weights_bytes) if weights_bytes else int(STATIC_WEIGHTS)
    per_token = int(kv_per_token) if kv_per_token else STATIC_KV_PER_TOKEN
    min_ctx = prompt + int(max_tokens)
    comfortable = prompt + HISTORY_RESERVE + int(max_tokens)
    choices = [c for c in options if not model_max_ctx or c <= int(model_max_ctx)]
    if model_max_ctx and int(model_max_ctx) < options[0]:
        choices = [int(model_max_ctx)]
    rows = []
    for ctx in choices:
        need = weights + per_token * ctx + OVERHEAD_BYTES + OVERHEAD_RATIO * weights
        if not avail_ram:
            level = "unknown"
        elif need <= avail_ram * OK_RATIO:
            level = "ok"
        elif need <= avail_ram * TIGHT_RATIO:
            level = "tight"
        else:
            level = "risky"
        truncates = ctx < min_ctx
        text = LEVEL_TEXT[level] + f"（估計要 {_gb(need)}）"
        if truncates:
            text += "；會截斷 SYNOX 的提示"
        elif ctx < comfortable:
            text += "；只夠放提示，對話一長就會截斷"
        rows.append({"ctx": ctx, "level": level, "need_bytes": int(need), "truncates": truncates,
                     "roomy": ctx >= comfortable, "text": text})
    good = [r for r in rows if r["level"] in ("ok", "unknown") and not r["truncates"] and r["ctx"] >= comfortable * 1.25]
    if not good:
        good = [r for r in rows if r["level"] != "risky" and not r["truncates"]]
    recommended = good[0]["ctx"] if good else None
    for r in rows:
        r["recommended"] = r["ctx"] == recommended
    notes = ["⚠️ 以下都是**估算**，不是量測：實際用量看模型、量化、伺服器版本與同時開著的程式。"]
    if source == "static":
        notes.append("沒連上 Ollama（或不是 Ollama）：用常見 7–9B、Q4 模型的假設（權重約 6 GB）粗估。連上之後會照你的模型重算。")
    else:
        kv_text = {"exact": "照模型資料算", "rough": "模型資料不齊，用偏大的估計", "static": "沒有模型資料，用保守假設"}[kv_source]
        notes.append(f"根據：權重約 {_gb(weights)}＋KV cache 每 1000 tokens 約 {per_token * 1000 / 1e6:.0f} MB（{kv_text}）"
                     f"＋執行時額外約 {_gb(OVERHEAD_BYTES + OVERHEAD_RATIO * weights)}。")
    if avail_ram:
        notes.append(f"這台現在可用的記憶體約 {_gb(avail_ram)}" + (f"（共 {_gb(total_ram)}）" if total_ram else "")
                     + f"：估計值 ≤ 可用的 {int(OK_RATIO * 100)}%＝建議、≤ {int(TIGHT_RATIO * 100)}%＝吃緊，其他＝可能撐不住"
                     "（CPU 推論，刻意偏保守；模型已經載入時可用記憶體會少算）。")
    else:
        notes.append("量不到這台的可用記憶體：只能看會不會截斷。")
    notes.append((f"SYNOX 的提示（系統說明＋全部工具規格）估計約 {prompt} tokens（字元數 ÷ 2.5，中文偏保守）"
                  if measured else f"還沒量到這台 SYNOX 實際的提示（工具還沒載入或沒連上），先用 {prompt} tokens 估")
                 + f"；context 小於 {min_ctx}（提示＋回覆上限 {max_tokens}）一定會被截斷，"
                   f"建議至少 {comfortable}（再留對話紀錄的空間）。")
    if model_max_ctx:
        notes.append(f"這個模型最多 {model_max_ctx}；選項不會超過它。")
    if recommended is None:
        notes.append("❌ 沒有一個選項夠放 SYNOX 的提示又不吃緊：換小一點的模型、關掉其他程式，或少裝幾個工具。")
    return {"options": rows, "recommended": recommended, "min_context": min_ctx, "comfortable": comfortable,
            "prompt_tokens": prompt, "prompt_measured": measured, "source": source, "notes": notes,
            "avail_ram": avail_ram, "total_ram": total_ram, "model_max_ctx": model_max_ctx}


def from_report(report: Optional[dict], *, prompt_chars: Optional[int] = None, max_tokens: int = 1024,
                server: str = "ollama", ram=None) -> dict:
    """LocalAdapter.inspect() 的結果（或 None＝沒探測）→ advise()。ram：(可用, 總共)，測試傳假的；None＝量這台。"""
    avail, total = ram if ram is not None else system_ram()
    prompt_tokens = tokens_from_chars(prompt_chars) if prompt_chars else None
    usable = bool(report) and report.get("reachable") and report.get("model_found") and server == "ollama"
    if usable:
        per_token, how = kv_bytes_per_token(report.get("model_info"))
        out = advise(avail_ram=avail, total_ram=total, weights_bytes=report.get("model_size") or None,
                     kv_per_token=per_token, kv_source=how, model_max_ctx=report.get("max_context"),
                     prompt_tokens=prompt_tokens, max_tokens=max_tokens, source="ollama")
    else:
        out = advise(avail_ram=avail, total_ram=total, model_max_ctx=(report or {}).get("max_context"),
                     prompt_tokens=prompt_tokens, max_tokens=max_tokens, source="static")
        if report and report.get("problems"):
            out["notes"].insert(1, "探測：" + report["problems"][0])
    if server != "ollama":
        out["notes"].insert(1, "提醒：vLLM／LM Studio／其他伺服器的 context 要在伺服器那邊設，SYNOX 只拿來對照截斷。")
    out["server"] = server
    return out


def lines(advice: dict) -> List[str]:
    """文字版（init、doctor）。"""
    out = []
    for r in advice.get("options") or []:
        mark = {"ok": "✅", "tight": "⚠️", "risky": "❌", "unknown": "•"}[r["level"]]
        out.append(f"  {mark} {r['ctx']:>6}：{r['text']}" + ("　← 推薦" if r.get("recommended") else ""))
    out += ["  " + n for n in advice.get("notes") or []]
    return out


def option_label(row: dict) -> str:
    """下拉選單上的字：「8192（建議）」。"""
    tag = "推薦" if row.get("recommended") else ("會截斷" if row.get("truncates") else LEVEL_TEXT[row["level"]])
    return f"{row['ctx']}（{tag}）"
