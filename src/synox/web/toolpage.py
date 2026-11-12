"""
網頁「工具」頁的後端：每個工具的說明與參數表單資訊，以及每個人自己的群組排版。

畫面（static/tools.js）：頁內左側是「群組」，選一個群組後，群組裡的工具用分頁（tab）隔開；
每個工具分頁有說明、指令清單（參數說明）、輸入欄、執行。執行照舊經 /api/chat/tools/send（dispatcher、同一個 authorize）。

一個「工具」＝registry 最上層的一個群組（pack 的群組，或 SYNOX 內建的群組；`_basics`＝/start、/help 這些根節點指令）。
工具 id 就是群組名（registry 保證不重複）。

排版（每個人自己的，不寫進 pack 資料夾）：

    {"version": 1, "groups": [{"id": "g1", "title": "生活", "tools": ["notes", "money"]}, …]}

- 存在 `data/web_prefs/<tg_id>.json.enc`（有保管箱：那個人的金鑰，跟對話紀錄同一套）裡的 `tool_layout`；
  沒有保管箱＝`data/web_prefs/<tg_id>.json`。擁有者、成員各自一份，互相看不到。
- 畫面上的排版＝使用者存的群組（照他的順序）＋還沒被排進任何群組的工具：照 pack.json 的 `category`
  放進同名的群組（沒有就在最後面新增一個），沒寫 category 的 pack＝「未分類」、SYNOX 內建的＝「內建」。
  **使用者排過的優先於 pack 的建議**。
- 看不到的工具（沒權限、pack 暫時沒載入）不會出現在畫面上；存檔時它原本在哪個群組照樣記著，之後看得到了就回原位。
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from typing import Dict, Iterable, List, Tuple

from isdtelekit.core import jsonstore

from synox.packs.manifest import MAX_CATEGORY, one_line_problem

UNCATEGORIZED = "未分類"
BUILTIN = "內建"
BASICS_ID = "_basics"
LAYOUT_KEY = "tool_layout"
LAYOUT_VERSION = 1
MAX_GROUPS = 30
MAX_TOOLS = 300                       # 一份排版裡全部的工具 id（含暫時看不到的）
TOOL_ID_RE = re.compile(r"^_?[a-z][a-z0-9_]{0,31}$")
GROUP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class LayoutError(ValueError):
    """送來的排版不合（訊息是給人看的一句話）。"""


# ── 工具的資訊（給表單用） ─────────────────────────────────────────────────

def _kind_of(field, kinds: Dict[str, str]) -> str:
    """欄位的格式：pack.json／MCP 宣告的 kind 優先；python pack（kit.command）沒有宣告，照檢查函式猜。"""
    kind = kinds.get(field.name)
    if kind:
        return kind
    from synox.packs import kit
    check = getattr(field, "check", None)
    if check is kit.number:
        return "number"
    if check is kit.positive_int:
        return "int"
    return "choice" if field.choices else "text"


def field_info(field, kinds: Dict[str, str], helps: Dict[str, str]) -> dict:
    out = {"name": field.name, "label": field.ask or field.name, "required": bool(field.required),
           "kind": _kind_of(field, kinds), "default": field.default or ""}
    if field.choices:
        out["choices"] = list(field.choices)
    if helps.get(field.name):
        out["help"] = helps[field.name]
    from synox.packs import kit
    if getattr(field, "check", None) is kit.hhmm:
        out["help"] = out.get("help") or "時間，例如 08:00"
    return out


def command_info(node, meta: dict) -> dict:
    """一個葉節點 → 工具頁的一張指令卡：指令、用法、說明、危險程度、參數（驗證碼欄位不列：SDK 之後會問）。"""
    kinds = dict(meta.get("kinds") or {})
    helps = dict(meta.get("help") or {})
    fields = [field_info(f, kinds, helps) for f in node.fields if not getattr(f, "fresh_code", False)]
    return {"command": node.command, "usage": node.usage, "summary": node.summary, "effect": node.effect,
            "path": node.path, "default": bool(getattr(node, "default", False)), "ai": bool(getattr(node, "ai", True)),
            "confirm": meta.get("confirm") is True, "fields": fields,
            "asks_code": any(getattr(f, "fresh_code", False) for f in node.fields)}


def skill_description(manifest) -> str:
    """SKILL.md frontmatter 的 description（給 AI 的「什麼時候用」，工具頁的說明也用）。讀不到回 ""。"""
    from synox.agent import skills
    try:
        meta, _body = skills.parse(skills.read_text(manifest.skill_path))
    except (OSError, UnicodeDecodeError):
        return ""
    text = str(meta.get("description") or "").strip()
    return text[:400]


# ── 排版 ──────────────────────────────────────────────────────────────

def auto_group_id(title: str) -> str:
    """照 category 自動產生的群組：id 由名字算（同一個名字每次都一樣）。"""
    return "a-" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:10]


def parse_layout(data) -> dict:
    """POST /api/tools/layout 的 {"groups": [{"id", "title", "tools": [...]}, …]} → 乾淨的排版；不合丟 LayoutError。"""
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        raise LayoutError("排版要是 {\"groups\": [{\"id\", \"title\", \"tools\": [...]}, …]}")
    groups = data["groups"]
    if len(groups) > MAX_GROUPS:
        raise LayoutError(f"群組最多 {MAX_GROUPS} 個")
    out, ids, titles, seen_tools = [], set(), set(), set()
    total = 0
    for i, g in enumerate(groups):
        if not isinstance(g, dict):
            raise LayoutError(f"第 {i + 1} 個群組要是物件")
        gid = g.get("id")
        if not isinstance(gid, str) or not GROUP_ID_RE.match(gid):
            raise LayoutError(f"第 {i + 1} 個群組的 id 不對（小寫英數字、-、_，32 字內）")
        if gid in ids:
            raise LayoutError(f"群組 id {gid} 重複了")
        ids.add(gid)
        title = g.get("title")
        problem = one_line_problem(title, "群組名稱", MAX_CATEGORY)
        if problem:
            raise LayoutError(problem)
        title = title.strip()
        if title in titles:
            raise LayoutError(f"群組名稱「{title}」重複了")
        titles.add(title)
        tools = g.get("tools") or []
        if not isinstance(tools, list) or not all(isinstance(t, str) and TOOL_ID_RE.match(t) for t in tools):
            raise LayoutError(f"群組「{title}」的 tools 要是工具 id 的清單")
        kept = []
        for t in tools:                      # 一個工具只在一個群組（重複的留第一個）
            if t not in seen_tools:
                seen_tools.add(t)
                kept.append(t)
        total += len(kept)
        if total > MAX_TOOLS:
            raise LayoutError(f"工具太多了（最多 {MAX_TOOLS} 個）")
        out.append({"id": gid, "title": title, "tools": kept})
    return {"version": LAYOUT_VERSION, "groups": out}


def _stored_groups(stored) -> List[dict]:
    """存檔裡的群組；格式不對（舊版、手改壞了）就當作沒有排過（不丟錯：排版只是偏好）。"""
    try:
        return parse_layout(stored)["groups"] if stored else []
    except LayoutError:
        return []


def effective(stored, tools: Iterable[Tuple[str, str]]) -> dict:
    """畫面上的排版。tools＝這個人看得到的 (工具 id, 建議群組名)，照顯示順序。
    回 {"groups": [{"id", "title", "tools", "auto"}], "custom": 有沒有自己排過}。"""
    visible = dict(tools)
    order = list(visible)
    groups, assigned = [], set()
    for g in _stored_groups(stored):
        kept = [t for t in g["tools"] if t in visible and t not in assigned]
        assigned.update(kept)
        groups.append({"id": g["id"], "title": g["title"], "tools": kept, "auto": False})
    by_title = {g["title"]: g for g in groups}
    autos: List[dict] = []
    for tid in order:
        if tid in assigned:
            continue
        title = (visible[tid] or "").strip() or UNCATEGORIZED
        g = by_title.get(title)
        if g is None:
            g = {"id": auto_group_id(title), "title": title, "tools": [], "auto": True}
            by_title[title] = g
            autos.append(g)
        g["tools"].append(tid)
    # 自動產生的群組：照第一次出現的順序，「未分類」「內建」放最後
    tail = {UNCATEGORIZED: 1, BUILTIN: 2}
    autos.sort(key=lambda g: tail.get(g["title"], 0))
    return {"groups": groups + autos, "custom": bool(stored and _stored_groups(stored))}


def merge_hidden(new: dict, old, visible: Iterable[str]) -> dict:
    """存檔時：送來的排版只有看得到的工具；原本排好、現在看不到的工具留在原本那個群組（群組還在的話）。"""
    visible = set(visible)
    placed = {t for g in new["groups"] for t in g["tools"]}
    by_id = {g["id"]: g for g in new["groups"]}
    for g in _stored_groups(old):
        target = by_id.get(g["id"])
        if target is None:
            continue
        for t in g["tools"]:
            if t not in visible and t not in placed:
                target["tools"].append(t)
                placed.add(t)
    return new


# ── 每個人的偏好檔 ─────────────────────────────────────────────────────

class UserPrefs:
    """每個人一份的網頁偏好（目前只有工具頁的排版）。有保管箱＝密文（那個人的金鑰）；
    解不開時丟 VaultError，絕不當成空的再蓋過去（AGENT.md）。"""

    def __init__(self, folder: str, vault=None):
        self.folder = folder
        self._vault = vault
        self._lock = threading.Lock()

    def _user_vault(self, tg_id: int):
        return self._vault.for_user(int(tg_id)).at(self.folder) if self._vault is not None else None

    def path(self, tg_id: int) -> str:
        vault = self._user_vault(tg_id)
        return vault.path(str(int(tg_id))) if vault is not None else os.path.join(self.folder, f"{int(tg_id)}.json")

    def _load(self, tg_id: int) -> dict:
        vault = self._user_vault(tg_id)
        data = vault.load_json(str(int(tg_id)), None) if vault is not None else \
            jsonstore.load_json(self.path(tg_id), None)
        return data if isinstance(data, dict) else {}

    def get(self, tg_id: int, key: str, default=None):
        with self._lock:
            return self._load(tg_id).get(key, default)

    def set(self, tg_id: int, key: str, value) -> None:
        with self._lock:
            data = self._load(tg_id)
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
            os.makedirs(self.folder, exist_ok=True)
            vault = self._user_vault(tg_id)
            if vault is not None:
                vault.save_json(str(int(tg_id)), data)
            else:
                jsonstore.save_json(self.path(tg_id), data)
