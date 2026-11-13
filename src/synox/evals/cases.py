"""
評測題目：一題一個 JSON 檔（evals/assistant/cases/<id>.json），共用的假工具在 evals/assistant/tools.json。

    {
      "id": "note-01", "category": "note", "split": "tune", "title": "一句話說這題在考什麼",
      "turns": ["使用者第一句", "（多回合才有）第二句"],
      "tools": [{"name": "note__add"},                         ← tools.json 有的：只寫名字（要改的欄位寫在這裡蓋過）
                {"name": "x__y", "summary": "…", "effect": "read|write|danger", "confirm": false,
                 "params": [{"name": "text", "ask": "內容", "required": true, "choices": []}],
                 "results": [{"when": {"text": {"contains": "傘"}}, "reply": "記好了：{text}"}, {"reply": "預設"}]}],
      "expect": {"must_call": [{"tool": "note__add", "args": {"text": {"contains": "傘"}}}],
                 "must_not_call": ["note__clear"], "confirm_card": false, "ask_back": false, "refuse": true,
                 "max_steps": 2, "final_contains": ["…"], "final_not_contains": ["…"]},
      "soft": [{"name": "語氣", "rubric": "給人看的評分重點（1～5 分，不自動打分）"}]
    }

must_call 的一項也可以是 {"any_of": [{"tool": …, "args": …}, …]}（任一個被接受就算；any_of 裡可以寫 BUILTIN_TOOLS 的內建工具，
例如 remind__add）。expect 的 "claimed_without_call": false 關掉「說做好了卻沒有呼叫」的檢查（預設每題都跑）。
比對值（must_call 的 args、results 的 when）：字串＝去掉頭尾空白後一模一樣；{"contains": "x" 或 ["x", "y"]}＝全部都要出現；
{"regex": "…"}＝re.search 找得到。各欄位的意思與判定規則：evals/assistant/README.md。
"""

from __future__ import annotations

import copy
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

CATEGORIES = ("note", "rewrite", "lookup", "schedule", "clarify", "no_clarify", "refuse", "injection", "memory",
              "chain", "fake_done")
CATEGORY_LABELS = {
    "note": "記事", "rewrite": "改寫與摘要", "lookup": "查資料", "schedule": "行程與時間", "clarify": "模糊該追問",
    "no_clarify": "模糊不該追問", "refuse": "拒絕", "injection": "提示注入", "memory": "多回合記憶", "chain": "工具鏈",
    "fake_done": "假裝做完（完成宣稱檢查）",
}
SPLITS = ("tune", "holdout")
# 題數分配（brief §4）：類別 → (tune, holdout)。改題目數量時一起改這張表與 README。
DISTRIBUTION: Dict[str, Tuple[int, int]] = {
    "note": (3, 1), "rewrite": (2, 1), "lookup": (3, 1), "schedule": (2, 1), "clarify": (2, 1),
    "no_clarify": (1, 1), "refuse": (2, 1), "injection": (2, 1), "memory": (2, 1), "chain": (1, 1),
    "fake_done": (1, 1),
}
EFFECTS = ("read", "write", "danger")
EXPECT_KEYS = ("must_call", "must_not_call", "confirm_card", "ask_back", "refuse", "max_steps", "final_contains",
               "final_not_contains", "claimed_without_call")
# SYNOX 內建、每題都在工具清單裡的系統指令（假工具不能用這些群組名）：must_call 的 any_of 可以寫它們（名字 → 參數名）
BUILTIN_TOOLS: Dict[str, Tuple[str, ...]] = {"remind__add": ("time", "text", "date")}
ID_RE = re.compile(r"^[a-z][a-z_]*-\d{2}$")
TOOL_RE = re.compile(r"^[a-z][a-z0-9]{0,14}__[a-z][a-z0-9_]{0,14}$")       # 群組__葉節點（指令名 /群組_葉節點 ≤ 32 字）
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
# 題目裡的信箱與網址一律用保留給範例的網域（RFC 2606），不放任何真的人或網站
EXAMPLE_DOMAINS = ("example.com", "example.net", "example.org")
TOOLS_FILE = "tools.json"


class CaseError(ValueError):
    """題目格式不對；訊息是給人看的一句話（含檔名）。"""


@dataclass
class ToolDef:
    name: str
    summary: str
    effect: str = "read"
    confirm: bool = False
    params: List[dict] = field(default_factory=list)
    results: List[dict] = field(default_factory=list)


@dataclass
class Case:
    id: str
    category: str
    split: str
    title: str
    turns: List[str]
    tools: List[ToolDef]
    expect: dict
    soft: List[dict] = field(default_factory=list)
    path: str = ""

    def tool(self, name: str) -> Optional[ToolDef]:
        return next((t for t in self.tools if t.name == name), None)


# ── 比對值 ─────────────────────────────────────────────────────────────

def matcher_problem(m) -> Optional[str]:
    if isinstance(m, str):
        return None
    if isinstance(m, dict) and len(m) == 1:
        (kind, value), = m.items()
        if kind == "contains" and (isinstance(value, str) or
                                   (isinstance(value, list) and value and all(isinstance(v, str) for v in value))):
            return None
        if kind == "regex" and isinstance(value, str):
            try:
                re.compile(value)
            except re.error as e:
                return f"正規式寫錯：{e}"
            return None
    return '比對值要是字串、{"contains": …} 或 {"regex": …}'


def matches(m, value) -> bool:
    value = "" if value is None else str(value).strip()
    if isinstance(m, str):
        return value == m.strip()
    (kind, want), = m.items()
    if kind == "contains":
        return all(w in value for w in ([want] if isinstance(want, str) else want))
    return re.search(want, value) is not None


def args_match(pattern: Dict[str, object], values: Dict[str, str]) -> bool:
    """只比對 pattern 列出的鍵（其他鍵不管）。"""
    return all(k in values and matches(m, values[k]) for k, m in (pattern or {}).items())


# ── 載入與檢查 ─────────────────────────────────────────────────────────

def load_tool_library(folder: str) -> Dict[str, dict]:
    path = os.path.join(folder, TOOLS_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise CaseError(f"{TOOLS_FILE}：最外層要是 {{工具名: 定義}}")
    return data


def _tool_from(raw, library: Dict[str, dict], where: str) -> ToolDef:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise CaseError(f"{where}：每個工具要是有 name 的物件")
    merged = copy.deepcopy(library.get(raw["name"], {}))
    merged.update(copy.deepcopy(raw))
    name = merged["name"]
    if not TOOL_RE.match(name):
        raise CaseError(f"{where}：工具名 {name!r} 要是「群組__動作」（小寫英數，例如 note__add）")
    unknown = set(merged) - {"name", "summary", "effect", "confirm", "params", "results", "result"}
    if unknown:
        raise CaseError(f"{where}：工具 {name} 有不認得的欄位 {sorted(unknown)}")
    if not isinstance(merged.get("summary"), str) or not merged["summary"].strip():
        raise CaseError(f"{where}：工具 {name} 少了 summary（tools.json 也沒有）")
    effect = merged.get("effect", "read")
    if effect not in EFFECTS:
        raise CaseError(f"{where}：工具 {name} 的 effect 只能是 {'/'.join(EFFECTS)}")
    params = merged.get("params", [])
    if not isinstance(params, list):
        raise CaseError(f"{where}：工具 {name} 的 params 要是清單")
    seen = set()
    for p in params:
        if not isinstance(p, dict) or not PARAM_RE.match(str(p.get("name", ""))) or not str(p.get("ask", "")).strip():
            raise CaseError(f"{where}：工具 {name} 的參數要有 name（小寫英數）與 ask")
        if p["name"] in seen or p["name"] == "args":
            raise CaseError(f"{where}：工具 {name} 的參數 {p['name']} 重複或保留字")
        seen.add(p["name"])
        if set(p) - {"name", "ask", "required", "choices"}:
            raise CaseError(f"{where}：工具 {name} 的參數 {p['name']} 有不認得的欄位")
    results = merged.pop("result", None)
    if results is not None:
        merged.setdefault("results", [{"reply": results}])
    rules = merged.get("results", [])
    if not isinstance(rules, list) or not rules:
        raise CaseError(f"{where}：工具 {name} 要有 results（被叫到時回什麼）")
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("reply"), str) or set(rule) - {"when", "reply"}:
            raise CaseError(f"{where}：工具 {name} 的 results 每項要是 {{\"when\": …, \"reply\": \"…\"}}")
        for key, m in (rule.get("when") or {}).items():
            if key not in seen:
                raise CaseError(f"{where}：工具 {name} 的 when 用了沒有的參數 {key}")
            problem = matcher_problem(m)
            if problem:
                raise CaseError(f"{where}：工具 {name} 的 when.{key}：{problem}")
    return ToolDef(name=name, summary=merged["summary"].strip(), effect=effect, confirm=bool(merged.get("confirm")),
                   params=params, results=rules)


def _check_call_item(item, tools: Dict[str, ToolDef], where: str, builtin: bool = False) -> None:
    known = item.get("tool") in tools or (builtin and item.get("tool") in BUILTIN_TOOLS) if isinstance(item, dict) else False
    if not known:
        raise CaseError(f"{where}：must_call 的每項要是 {{\"tool\": 這題有的工具, \"args\": …}}"
                        + ("（any_of 裡也可以寫內建的 " + "、".join(BUILTIN_TOOLS) + "）" if builtin else ""))
    if set(item) - {"tool", "args"}:
        raise CaseError(f"{where}：must_call 的 {item['tool']} 有不認得的欄位")
    name = item["tool"]
    params = {p["name"] for p in tools[name].params} if name in tools else set(BUILTIN_TOOLS[name])
    for key, m in (item.get("args") or {}).items():
        if key not in params:
            raise CaseError(f"{where}：must_call 的 {name} 沒有參數 {key}")
        problem = matcher_problem(m)
        if problem:
            raise CaseError(f"{where}：must_call 的 {name}.{key}：{problem}")


def _check_expect(expect, tools: Dict[str, ToolDef], where: str) -> dict:
    if not isinstance(expect, dict) or not expect:
        raise CaseError(f"{where}：expect 要是有內容的物件")
    unknown = set(expect) - set(EXPECT_KEYS)
    if unknown:
        raise CaseError(f"{where}：expect 有不認得的檢查 {sorted(unknown)}（只收 {', '.join(EXPECT_KEYS)}）")
    for item in expect.get("must_call", []):
        if isinstance(item, dict) and set(item) == {"any_of"}:
            options = item["any_of"]
            if not isinstance(options, list) or len(options) < 2:
                raise CaseError(f"{where}：must_call 的 any_of 要是兩個以上的 {{\"tool\": …, \"args\": …}}")
            for option in options:
                _check_call_item(option, tools, where, builtin=True)
            continue
        _check_call_item(item, tools, where)
    for name in expect.get("must_not_call", []):
        if name not in tools:
            raise CaseError(f"{where}：must_not_call 的 {name!r} 不是這題的工具（要測「不可以叫」就把它放進 tools）")
    for key in ("confirm_card", "ask_back", "refuse", "claimed_without_call"):
        if key in expect and not isinstance(expect[key], bool):
            raise CaseError(f"{where}：{key} 要是 true／false")
    if "max_steps" in expect and (not isinstance(expect["max_steps"], int) or expect["max_steps"] < 1):
        raise CaseError(f"{where}：max_steps 要是 1 以上的整數")
    for key in ("final_contains", "final_not_contains"):
        if not all(isinstance(s, str) and s for s in expect.get(key, [])):
            raise CaseError(f"{where}：{key} 要是非空字串的清單")
    return expect


def privacy_problems(text: str) -> List[str]:
    """題目裡的信箱與網址只能用範例網域。"""
    out = []
    for domain in EMAIL_RE.findall(text) + URL_RE.findall(text):
        d = domain.lower().rstrip(".")
        if not any(d == e or d.endswith("." + e) for e in EXAMPLE_DOMAINS):
            out.append(domain)
    return out


def parse_case(raw, library: Optional[Dict[str, dict]] = None, path: str = "") -> Case:
    where = os.path.basename(path) or "（題目）"
    library = library or {}
    if not isinstance(raw, dict):
        raise CaseError(f"{where}：最外層要是物件")
    unknown = set(raw) - {"id", "category", "split", "title", "turns", "tools", "expect", "soft"}
    if unknown:
        raise CaseError(f"{where}：有不認得的欄位 {sorted(unknown)}")
    cid = raw.get("id")
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise CaseError(f"{where}：id 要像 note-01（類別-兩位數）")
    if path and os.path.splitext(os.path.basename(path))[0] != cid:
        raise CaseError(f"{where}：檔名要跟 id 一樣（{cid}.json）")
    if raw.get("category") not in CATEGORIES:
        raise CaseError(f"{where}：category 只能是 {', '.join(CATEGORIES)}")
    if not cid.startswith(raw["category"] + "-"):
        raise CaseError(f"{where}：id 要以類別開頭（{raw['category']}-NN）")
    if raw.get("split") not in SPLITS:
        raise CaseError(f"{where}：split 只能是 tune 或 holdout")
    if not isinstance(raw.get("title"), str) or not raw["title"].strip():
        raise CaseError(f"{where}：少了 title")
    turns = raw.get("turns")
    if not isinstance(turns, list) or not turns or not all(isinstance(t, str) and t.strip() for t in turns):
        raise CaseError(f"{where}：turns 要是使用者說的話的清單（至少一句）")
    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise CaseError(f"{where}：tools 要是清單")
    tools = [_tool_from(t, library, where) for t in tools_raw]
    by_name = {t.name: t for t in tools}
    if len(by_name) != len(tools):
        raise CaseError(f"{where}：tools 裡有重複的工具名")
    expect = _check_expect(raw.get("expect"), by_name, where)
    soft = raw.get("soft", [])
    if not isinstance(soft, list) or not all(isinstance(s, dict) and s.get("name") and s.get("rubric")
                                             and not set(s) - {"name", "rubric"} for s in soft):
        raise CaseError(f"{where}：soft 每項要是 {{\"name\": …, \"rubric\": …}}")
    leaked = privacy_problems(json.dumps({"turns": turns, "tools": [t.__dict__ for t in tools], "expect": expect},
                                         ensure_ascii=False))
    if leaked:
        raise CaseError(f"{where}：信箱／網址要用範例網域（{', '.join(EXAMPLE_DOMAINS)}），不是 {', '.join(leaked)}")
    return Case(id=cid, category=raw["category"], split=raw["split"], title=raw["title"].strip(), turns=list(turns),
                tools=tools, expect=expect, soft=list(soft), path=path)


def load_dir(folder: str) -> List[Case]:
    """資料夾裡每個 *.json（tools.json 除外）是一題；照 id 排序。格式不對丟 CaseError。"""
    if not os.path.isdir(folder):
        raise CaseError(f"找不到題目資料夾：{folder}")
    library = load_tool_library(folder) or load_tool_library(os.path.dirname(os.path.abspath(folder)))
    cases = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or name == TOOLS_FILE:
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError) as e:
            raise CaseError(f"{name}：讀不了（{type(e).__name__}: {e}）")
        cases.append(parse_case(raw, library, path))
    ids = [c.id for c in cases]
    dup = [i for i, n in Counter(ids).items() if n > 1]
    if dup:
        raise CaseError(f"id 重複：{', '.join(dup)}")
    return sorted(cases, key=lambda c: c.id)


def distribution(cases: List[Case]) -> Dict[str, Tuple[int, int]]:
    """類別 → (tune 題數, holdout 題數)。"""
    out = {c: [0, 0] for c in CATEGORIES}
    for case in cases:
        out[case.category][SPLITS.index(case.split)] += 1
    return {c: (n[0], n[1]) for c, n in out.items()}


def distribution_problems(cases: List[Case]) -> List[str]:
    got = distribution(cases)
    return [f"{c}：tune／holdout 要 {DISTRIBUTION[c][0]}／{DISTRIBUTION[c][1]}，現在 {got[c][0]}／{got[c][1]}"
            for c in CATEGORIES if got[c] != DISTRIBUTION[c]]


def select(cases: List[Case], split: str = "all") -> List[Case]:
    if split == "all":
        return list(cases)
    if split not in SPLITS:
        raise CaseError("split 只能是 tune、holdout 或 all")
    return [c for c in cases if c.split == split]
