"""
SKILL.md（agentskills.io 格式）：開頭的 frontmatter（name、description，可選 when）進系統提示，每個約 100 token；
正文由 `skill_read` 工具按需讀（三層漸進載入）。

    ---
    name: money
    description: 使用者提到花了多少錢…時使用。
    ---
    # 正文…

主題檔（pack.json 的 agent.skill.topics，ADR 0030）：說明書太長時拆成幾章，`skill_read` 多一個 `topic` 參數只讀那一章
（先讀總表、再讀主題）。主題檔永遠不自動進脈絡。沒有任何工具宣告主題時，`skill_read` 的規格跟以前一模一樣（只有 name）。
能力清單（提示第 3、4 層）改由工具登記索引產生：agent/index.py 的 lines_for／prompt_block；這裡的 prompt_block 是舊的寫法，
留給還沒換過去的呼叫端。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from synox.llm.base import ToolSpec

SKILL_READ = "skill_read"
TOPIC_MAX_CHARS = 20000


@dataclass
class Skill:
    name: str
    description: str
    path: str
    when: str = ""
    topics: Dict[str, str] = field(default_factory=dict)      # 主題名 → 檔案的完整路徑
    warnings: List[dict] = field(default_factory=list)       # 這個工具的標記警告（ADR 0041；pack.json 的 warnings）

    def body(self) -> str:
        return parse(read_text(self.path))[1]

    def note(self, long: bool = True) -> str:
        """附在名字後面的警告標記（沒有警告＝""）。"""
        from synox.packs.packwarn import agent_note
        return agent_note(self.warnings, long=long)


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
            topics = (getattr(pack.manifest, "agent", None) or {}).get("topics") or {}
            skill.topics = {k: os.path.join(pack.manifest.folder, v) for k, v in topics.items()}
            skill.warnings = [dict(w) for w in getattr(pack.manifest, "warnings", None) or []]
            out.append(skill)
    return out


def prompt_block(skills: List[Skill]) -> str:
    if not skills:
        return ""
    lines = ["## 技能（要知道細節時，用 skill_read 讀全文）"]
    if any(s.warnings for s in skills):
        from synox.packs.packwarn import AGENT_RULE
        lines.append(AGENT_RULE)
    lines += [f"- {s.name}{s.note()}：{s.description}" + (f"（{s.when}）" if s.when else "") for s in skills]
    return "\n".join(lines)


def read_tool_spec(skills: List[Skill]) -> ToolSpec:
    names = "、".join(s.name for s in skills) or "（沒有）"
    props = {"name": {"type": "string", "description": "技能名稱"}}
    desc = f"讀一個技能的完整說明（什麼時候用哪個工具、注意事項）。可讀：{names}"
    with_topics = [s for s in skills if s.topics]
    if with_topics:                              # 有工具宣告主題才多 topic（沒有的話跟以前一模一樣）
        listing = "；".join(f"{s.name}：{'、'.join(sorted(s.topics))}" for s in with_topics)
        props["topic"] = {"type": "string", "description": "選填：只讀這個技能的某一章（主題名）"}
        desc += f"。先讀總表，要細節再帶 topic 讀那一章。主題：{listing}"
    return ToolSpec(SKILL_READ, desc, {"type": "object", "properties": props, "required": ["name"]})


def read_skill(skills: List[Skill], name: str, topic: Optional[str] = None) -> str:
    """技能的正文；topic＝只讀那一章（agent.skill.topics 宣告過的主題檔）。"""
    for s in skills:
        if s.name == str(name or "").strip():
            head = _warning_head(s)                  # 標記警告（ADR 0041）：正文、主題都先附上，AI 讀說明書一定看得到
            topic = str(topic or "").strip()
            if topic:
                return head + read_topic(s, topic)
            try:
                return head + (s.body() or "（這個技能沒有正文）")
            except OSError as e:
                return f"讀不到：{e}"
    return f"沒有叫 {name!r} 的技能。可讀：{'、'.join(s.name for s in skills) or '（沒有）'}"


def _warning_head(skill: Skill) -> str:
    """skill_read 回的字最前面：「〔⚠️警告 …〕＋守則」；沒有警告＝""（跟以前一模一樣）。"""
    if not skill.warnings:
        return ""
    from synox.packs.packwarn import AGENT_RULE
    return f"{skill.note()}\n{AGENT_RULE}\n\n"


def read_topic(skill: Skill, topic: str) -> str:
    path = skill.topics.get(topic)
    if path is None:
        have = "、".join(sorted(skill.topics)) or "（這個技能沒有主題，不帶 topic 讀總表）"
        return f"{skill.name} 沒有 {topic!r} 這個主題。有：{have}"
    try:
        text = parse(read_text(path))[1]
    except (OSError, UnicodeDecodeError) as e:
        return f"讀不到：{e}"
    if len(text) > TOPIC_MAX_CHARS:
        text = text[:TOPIC_MAX_CHARS] + "\n…（後面太長，沒有給）"
    return text or "（這個主題沒有內容）"


def skill_paths(skills: List[Skill]) -> List[str]:
    return [os.path.abspath(s.path) for s in skills]
