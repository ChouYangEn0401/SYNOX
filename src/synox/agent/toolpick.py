"""
每輪工具數上限（docs/adr/0014；研究交接書規格 5，卡片 D2、D3）：工具一多，小模型就挑錯或乾脆不叫。

    tools = pick(full, query, limit, keep=("remind__",))

- limit ≤ 0，或「一般工具」（不算永遠保留的）≤ limit：原樣回（同一個 list 內容、同一個順序）。
- 否則每個一般工具打分數＝使用者這句話與（名稱去掉 __、說明（含 scenario）、參數名與參數說明）的**字元 2-gram 重疊數**
  （不用嵌入模型、不用第三方套件），取前 limit 個；同分照原本的順序。輸出**照原本的順序**（不照分數排，前段穩定）。
- **永遠保留**：system__cannot_do（做不到的出口）、skill_read、keep 給的開頭——挑工具不能讓「做不到」的出口或系統指令消失。
  系統指令不再寫死在這裡（以前的 SYSTEM_PREFIXES）：問工具登記索引（agent/index.py，ADR 0029）——
  `keep_for(app)`＝load=always 的項目（提醒）＋app 登記的系統群組。
- **觸發字**（pack.json 的 agent.triggers，ADR 0029）：這句話含某個工具的觸發字 → 那個工具的分數加 TRIGGER_BONUS，排在前面。
  `pick_for(app, tools, query, limit, also)` 一次做完（keep＋觸發字）。
- 誰開：`llm.max_tools`＝"auto"（預設；本地／弱來源＝12，雲端與 Claude Code＝0 不限，判斷共用 agent/auto.py）｜0（不限）｜正整數。
- 權限不在這裡：清單只是「這一輪先給 AI 看哪些」；模型叫了清單外、但他有權的工具，loop.call_tool 照常判斷與執行
  （ai_decision 才是唯一的判斷），而且下一步退回全集（loop._turn）。同一輪內清單不另外重排（D3：前段穩定）。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from synox.agent import auto as auto_mod
from synox.agent.skills import SKILL_READ
from synox.agent.tools import CANNOT_DO
from synox.llm.base import ToolSpec

DEFAULT_LOCAL_LIMIT = 12                  # 本地模型的建議（AnyTool／Less is More：工具越少越好，12 是保守值）
MAX_LIMIT = 200
ALWAYS = (CANNOT_DO, SKILL_READ)
TRIGGER_BONUS = 1000                      # 命中觸發字＝排在任何只靠字面相似的工具前面
_WORD = re.compile(r"[0-9a-z㐀-鿿豈-﫿]+")


def grams(text: str) -> Set[str]:
    """字元 2-gram（小寫；只看英數字與漢字，標點與空白當斷點；單一字元的片段就算它自己）。"""
    out: Set[str] = set()
    for run in _WORD.findall((text or "").lower()):
        if len(run) == 1:
            out.add(run)
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def tool_text(tool: ToolSpec) -> str:
    props = ((tool.parameters or {}).get("properties") or {}) if isinstance(tool.parameters, dict) else {}
    parts = [tool.name.replace("__", " ").replace("_", " "), tool.description or ""]
    for name, spec in props.items():
        parts.append(str(name).replace("_", " "))
        if isinstance(spec, dict) and isinstance(spec.get("description"), str):
            parts.append(spec["description"])
    return " ".join(parts)


def score(tool: ToolSpec, query: Set[str]) -> int:
    return len(query & grams(tool_text(tool)))


def kept(name: str, keep: Iterable[str] = ()) -> bool:
    """永遠保留的工具：做不到的出口、skill_read、keep 給的名字開頭（系統指令：keep_for(app)）。"""
    if name in ALWAYS:
        return True
    return any(name.startswith(p) for p in tuple(keep or ()))


def triggered(query: str, triggers: Optional[Dict[str, Sequence[str]]]) -> Tuple[str, ...]:
    """這句話命中觸發字的工具名開頭（不分大小寫、子字串比對）。"""
    text = (query or "").lower()
    return tuple(prefix for prefix, words in (triggers or {}).items()
                 if any(w and w.lower() in text for w in words))


def pick(tools: Sequence[ToolSpec], query: str, limit: int, *, keep: Iterable[str] = (),
         triggers: Optional[Dict[str, Sequence[str]]] = None) -> List[ToolSpec]:
    tools = list(tools)
    keep = tuple(keep or ())
    if not limit or limit <= 0:
        return tools
    others = [i for i, t in enumerate(tools) if not kept(t.name, keep)]
    if len(others) <= limit:
        return tools
    q = grams(query)
    hit = triggered(query, triggers)

    def total(i: int) -> int:
        bonus = TRIGGER_BONUS if hit and tools[i].name.startswith(hit) else 0
        return score(tools[i], q) + bonus

    ranked = sorted(others, key=lambda i: (-total(i), i))[:limit]
    chosen = set(ranked)
    return [t for i, t in enumerate(tools) if i in chosen or kept(t.name, keep)]


def keep_for(app) -> Tuple[str, ...]:
    """這個 app 永遠保留的工具名開頭：問工具登記索引（load=always 的系統層／核心工具＋登記的系統群組）。"""
    from synox.agent import index
    return index.keep_prefixes(app)


def pick_for(app, tools: Sequence[ToolSpec], query: str, limit: int, also: Iterable[str] = ()) -> List[ToolSpec]:
    """pick＋這個 app 的 keep（keep_for）＋觸發字（index.trigger_map）。also＝這一輪另外一定要給的開頭（例如自訂名字）。"""
    from synox.agent import index
    return pick(tools, query, limit, keep=keep_for(app) + tuple(also or ()), triggers=index.trigger_map(app))


def outside(calls, offered: Sequence[ToolSpec], full: Sequence[ToolSpec]) -> List[str]:
    """這一步叫到、不在這次給的清單、但在全集裡（他有權）的工具名——有的話迴圈下一步退回全集。"""
    shown = {t.name for t in offered}
    everything = {t.name for t in full}
    return [c.name for c in calls if c.name not in shown and c.name in everything]


# ── 設定 ──────────────────────────────────────────────────────────────

def parse_max_tools(value):
    """llm.max_tools：auto（預設）｜0（不限）｜1～200 的整數。字串的數字也收。寫錯丟 ValueError。"""
    if value is None or value == "" or (isinstance(value, str) and value.strip().lower() == "auto"):
        return "auto"
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_LIMIT:
        raise ValueError(f"llm.max_tools 只能是 auto、0（不限）或 1～{MAX_LIMIT} 的整數。")
    return value


def limit_for(llm: Optional[dict], adapter) -> int:
    """這一輪的上限：auto＝本地／弱來源 12、其他 0（不限）；寫錯＝0（config.py 會先擋下）。"""
    try:
        value = parse_max_tools((llm or {}).get("max_tools"))
    except ValueError:
        return 0
    if value == "auto":
        return DEFAULT_LOCAL_LIMIT if auto_mod.weak_source(adapter) else 0
    return int(value)
