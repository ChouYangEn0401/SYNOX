# -*- coding: utf-8 -*-
"""
給 AI 的結構化結果（核心合一規劃 11.6；SDK 0.2.4 的信封 "ai"）。

工具（kind=cli）回的 JSON 信封以前只有一種用法：`packs/render.py` 攤平成最多 25 行 × 160 字，人和 AI 看的都是那幾行，
AI 拿不到算好的數字、id、日期（只能從給人看的字裡猜，或自己心算）。現在分兩份：

- **人**：照舊（`render.render(for_people(信封))`；信封的 "ai" 不出現在給人看的字裡）。
- **AI**（經 AI 呼叫，`api.via_ai`；核准卡按 ✅ 之後交給 AI 的那一份也是）：`message`＋一段精簡 JSON。
  信封有 "ai" 用它，沒有用 "data"，兩個都沒有＝照舊（給人看的那幾行）。

精簡 JSON 的規則（`compact`）：
- 上限＝呼叫端給的字數（loop 用 `llm.tool_result_chars`；沒有上限時用 DEFAULT_CHARS）。
- 放得下就原樣（只把 JSON 不支援的型別換成字串、NaN／無限大換成字串）。
- 放不下就**結構化地截**：清單留前 N 項，最後一項換成 `{"_more": <剩幾項>}`；物件留前 N 個欄位＋`"_more": <剩幾個>`；
  太長的字串截短加「…」；太深的層換成一句摘要（「{…5 個欄位}」「[…12 項]」）。一層一層收緊，第一個放得下的就用。
- 結果**一定是合法 JSON**（json.loads 讀得回來），而且不超過上限。
- 使用者存的 secret 先遮掉（`scrub`，同一支 `packs.mcp.redact`；鍵與值都遮）。

這裡只產生字；包第 5 關的分隔符（delimit.wrap）是 loop 的事，跟其他工具結果一樣。
"""

from __future__ import annotations

import json
import math
from typing import Any, List, Optional, Sequence, Tuple

DEFAULT_CHARS = 4000            # 沒有 llm.tool_result_chars 時的上限（以前攤平的字最多 25 行 × 160 字，差不多這麼長）
MIN_JSON = 120                  # JSON 至少留這麼多字（message 太長就先截 message）
LABEL = "結構化結果（JSON）："
MORE = "_more"
# 一層一層收緊：(清單／物件最多幾項, 字串最多幾字, 最多幾層)；None＝不限
LEVELS: Tuple[Tuple[Optional[int], Optional[int], Optional[int]], ...] = (
    (None, None, None),
    (50, 500, 8),
    (20, 200, 6),
    (10, 120, 5),
    (5, 80, 4),
    (3, 40, 3),
    (1, 24, 2),
    (0, 12, 1),
)


# ── 信封 ──────────────────────────────────────────────────────────────

def payload_of(envelope: Any) -> Tuple[bool, Any]:
    """(有沒有給 AI 的結構化結果, 那一份)：信封有 "ai" 用它，沒有用 "data"；都沒有（或是 None）＝(False, None)。"""
    if not isinstance(envelope, dict):
        return False, None
    for key in ("ai", "data"):
        if envelope.get(key) is not None:
            return True, envelope[key]
    return False, None


def for_people(envelope: Any) -> Any:
    """給 render 的那一份：拿掉 "ai"（人看到的跟以前一樣）。不是 dict 原樣回。"""
    if isinstance(envelope, dict) and "ai" in envelope:
        return {k: v for k, v in envelope.items() if k != "ai"}
    return envelope


def message_of(envelope: Any) -> str:
    """信封的 message（給人看的那一句）；沒有＝""。"""
    if isinstance(envelope, dict) and isinstance(envelope.get("message"), str):
        return envelope["message"].strip()
    return ""


# ── 遮 secret ──────────────────────────────────────────────────────────

def scrub(value: Any, secrets: Sequence[str]) -> Any:
    """把使用者存的 secret 從每個字串（含物件的鍵）遮掉；回新的一份，不改原本的。"""
    secrets = [s for s in (secrets or ()) if isinstance(s, str)]
    if not secrets:
        return value
    from synox.packs.mcp import redact

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            return redact(v, secrets)
        if isinstance(v, dict):
            return {redact(str(k), secrets): walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        return v
    return walk(value)


# ── 精簡 JSON ──────────────────────────────────────────────────────────

def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _cut(text: str, chars: Optional[int]) -> str:
    if chars is None or len(text) <= chars:
        return text
    return text[:max(0, chars - 1)] + "…"


def _shrink(value: Any, items: Optional[int], chars: Optional[int], depth: Optional[int]) -> Any:
    """照這一級的限制產生一份只含 JSON 型別的副本。"""
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _cut(value, chars)
    if isinstance(value, dict):
        if depth is not None and depth <= 0:
            return f"{{…{len(value)} 個欄位}}"
        keys = list(value.keys())
        keep = keys if items is None else keys[:max(items, 1)]
        out = {_cut(str(k), chars if chars is None else max(chars, 24)): _shrink(value[k], items, chars,
                                                                             None if depth is None else depth - 1)
               for k in keep}
        if len(keys) > len(keep):
            out[MORE if MORE not in out else MORE + "_"] = len(keys) - len(keep)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        seq = list(value)
        if depth is not None and depth <= 0:
            return f"[…{len(seq)} 項]"
        keep = seq if items is None else seq[:items]
        out_list: List[Any] = [_shrink(x, items, chars, None if depth is None else depth - 1) for x in keep]
        if len(seq) > len(keep):
            out_list.append({MORE: len(seq) - len(keep)})
        return out_list
    return _cut(str(value), chars)


def compact(value: Any, limit: int) -> str:
    """value → 合法 JSON 字串，長度不超過 limit（limit 太小時至少回 "{}"）。"""
    limit = max(2, int(limit or 0))
    for items, chars, depth in LEVELS:
        try:
            text = _dumps(_shrink(value, items, chars, depth))
        except (TypeError, ValueError):
            continue
        if len(text) <= limit:
            return text
    try:
        size = len(_dumps(_shrink(value, None, None, None)))
    except (TypeError, ValueError):
        size = 0
    for fallback in ({"_omitted": True, "_chars": size}, {"_omitted": True}):
        text = _dumps(fallback)
        if len(text) <= limit:
            return text
    return "{}"


def compose(message: str, payload: Any, limit: int) -> str:
    """給 AI 的一段：message（有的話）＋一行「結構化結果（JSON）：{…}」，總長不超過 limit（message 太長先截它）。"""
    limit = max(int(limit or 0), len(LABEL) + MIN_JSON)
    message = (message or "").strip()
    room = limit - len(LABEL) - (len(message) + 1 if message else 0)
    if room < MIN_JSON and message:
        message = _cut(message, max(0, limit - len(LABEL) - MIN_JSON - 1))
        room = limit - len(LABEL) - (len(message) + 1 if message else 0)
    body = LABEL + compact(payload, max(2, room))
    return f"{message}\n{body}" if message else body


def parse(text: str) -> Any:
    """測試與評測用：從 compose 的結果把 JSON 讀回來（沒有就丟 ValueError）。"""
    at = (text or "").rfind(LABEL)
    if at < 0:
        raise ValueError("沒有結構化結果")
    return json.loads(text[at + len(LABEL):].split("\n", 1)[0])
