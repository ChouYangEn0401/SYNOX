"""
SKILL.md（agentskills.io 格式）：開頭的 frontmatter（name、description，可選 when）進系統提示，每個約 100 token；
正文由 `skill_read` 工具按需讀（三層漸進載入）。

    ---
    name: money
    description: 使用者提到花了多少錢…時使用。
    ---
    # 正文…
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from synox.llm.base import ToolSpec

SKILL_READ = "skill_read"


@dataclass
class Skill:
    name: str
    description: str
    path: str
    when: str = ""

    def body(self) -> str:
        return parse(read_text(self.path))[1]


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def parse(text: str) -> Tuple[Dict[str, str], str]:
    """'---\\nname: x\\n---\\nbody' → ({name: x}, body)。沒有 frontmatter → ({}, 全文)。只認單行的 key: value。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    meta: Dict[str, str] = {}
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:]).strip()
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return {}, text.strip()                      # 沒有收尾的 ---：當作沒有 frontmatter


def load(path: str) -> Optional[Skill]:
    try:
        meta, _body = parse(read_text(path))
    except OSError:
        return None
    if not meta.get("name") or not meta.get("description"):
        return None
    return Skill(meta["name"], meta["description"], path, meta.get("when", ""))


def from_packs(packs) -> List[Skill]:
    """已載入的 pack（只登記的 connector／mcp 除外：還沒接，不放進 AI 的清單；mcp stdio／http 照放）。"""
    out = []
    for pack in packs:
        if getattr(pack.manifest, "registered_only", pack.manifest.kind in ("connector", "mcp")):
            continue
        skill = load(pack.manifest.skill_path)
        if skill is not None:
            out.append(skill)
    return out


def prompt_block(skills: List[Skill]) -> str:
    if not skills:
        return ""
    lines = ["## 技能（要知道細節時，用 skill_read 讀全文）"]
    lines += [f"- {s.name}：{s.description}" + (f"（{s.when}）" if s.when else "") for s in skills]
    return "\n".join(lines)


def read_tool_spec(skills: List[Skill]) -> ToolSpec:
    names = "、".join(s.name for s in skills) or "（沒有）"
    return ToolSpec(SKILL_READ, f"讀一個技能的完整說明（什麼時候用哪個工具、注意事項）。可讀：{names}",
                    {"type": "object", "properties": {"name": {"type": "string", "description": "技能名稱"}},
                     "required": ["name"]})


def read_skill(skills: List[Skill], name: str) -> str:
    for s in skills:
        if s.name == str(name or "").strip():
            try:
                return s.body() or "（這個技能沒有正文）"
            except OSError as e:
                return f"讀不到：{e}"
    return f"沒有叫 {name!r} 的技能。可讀：{'、'.join(s.name for s in skills) or '（沒有）'}"


def skill_paths(skills: List[Skill]) -> List[str]:
    return [os.path.abspath(s.path) for s in skills]
