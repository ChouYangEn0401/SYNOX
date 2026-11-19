"""
工具登記與索引（docs/adr/0030；pack.json 的 agent 區塊見 docs/pack-format.md「agent 區塊」）。

系統層（提醒、排程、通知）與裝上的工具走**同一個登記口**：每一項是一筆 Entry——名稱、標題、「什麼時候找我」一行、
觸發字、載入方式、說明書主題、能力代號、可以背書的未來承諾、每輪都要的一小段。

    index.register_system(app, "remind", title="⏰ 提醒（系統）", index="…", group="remind",
                          triggers=["提醒"], load="always", promises={"add": "schedule"})
    built = index.build(app, config)          # packs/loader.load_all 的結尾：彙整、寫 data/agent_index.json
    index.lines_for(app, user)                # 這個人看得到的能力清單（每項一行，總量 INDEX_MAX 字內）
    index.always_lines(app, user)             # agent.always（只有系統層與核心信任的工具）
    index.keep_prefixes(app)                  # 挑工具時永遠保留的（load=always 的群組）
    index.trigger_map(app)                    # 觸發字 → 群組（toolpick 加分）
    index.promised_tools(app)                 # 工具名 → schedule｜watch（成功後可以背書「會…」）

- 總量上限 INDEX_MAX＝1,500 字：超過就把每行的說明照 LINE_STEPS（60 → 40 → 28 → 20 → 12 → 0）逐級縮短；
  縮到只剩標題還超過，才把最後幾行併成「…另有 N 項」。固定守則不在這裡，不會被截。
- 看得到誰照權限（跟 agent/loop.visible_packs 同一個規則：群組對這個人可見；只登記的 connector／mcp 不列）。
- 沒寫 agent 區塊的舊工具：一行＝summary（截到 60 字）、沒有觸發字、on_trigger——跟以前一樣的挑法。
- data/agent_index.json 給健康檢查、網頁看；提示用記憶體裡那一份（app.extras[INDEX_KEY]）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

INDEX_MAX = 1500
LINE_STEPS = (60, 40, 28, 20, 12, 0)
INDEX_FILE = "agent_index.json"
INDEX_KEY = "synox_agent_index"
SYSTEM_KEY = "synox_agent_system"
SEP = "__"
# SYNOX 這一版一定有的系統能力（requires.system 對這些＋登記過的名字）
CORE_SYSTEM = ("notify", "schedule", "remind")
LOADS = ("on_trigger", "on_call", "always")
PROMISE_KINDS = ("schedule", "watch")
ALWAYS_MAX = 200
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@dataclass
class Entry:
    name: str
    title: str
    index: str = ""                                   # 「什麼時候找我」一行（60 字內）
    source: str = "pack"                              # pack｜system
    group: str = ""                                   # 指令群組（工具名的開頭：group__指令）
    triggers: List[str] = field(default_factory=list)
    load: str = "on_trigger"
    provides: List[str] = field(default_factory=list)
    promises: Dict[str, str] = field(default_factory=dict)    # 指令名 → schedule｜watch
    always: str = ""
    skill: str = ""                                   # SKILL.md frontmatter 的 name（skill_read 用的名字）
    topics: List[str] = field(default_factory=list)
    commands: List[dict] = field(default_factory=list)        # [{"name", "tool", "effect", "summary"}]
    kind: str = ""
    version: str = ""
    sha256: str = ""                                  # pack.json 的雜湊（系統層＝""）
    listed: bool = True                               # 只登記的 connector／mcp＝False（不進能力清單）
    # pack.json 的標記警告（ADR 0041）：[{"code", "text", "advice"}]；agent_index.json 也有這一欄（結構化，AI 不能略過）
    warnings: List[dict] = field(default_factory=list)

    def line(self, limit: Optional[int] = None) -> str:
        """能力清單的一行。limit＝說明最多幾個字（None＝不縮；0＝只剩標題）。說明書主題在 limit ≥ 20 時才附。
        標記警告緊接在標題後面、永遠不縮掉（limit 小的時候只剩 code 與 text，不帶 advice）。"""
        from synox.packs.packwarn import agent_note
        text = self.index
        if limit is not None and len(text) > limit:
            text = text[:max(0, limit - 1)] + "…" if limit > 0 else ""
        suffix = f"〔主題：{'、'.join(self.topics)}〕" if self.topics and (limit is None or limit >= 20) else ""
        title = self.title + agent_note(self.warnings, long=limit is None or limit >= 20)
        return f"- {title}：{text}{suffix}" if text or suffix else f"- {title}"

    @property
    def tools(self) -> List[str]:
        return [c["tool"] for c in self.commands]

    def chars(self) -> int:
        """每輪大約多佔幾個字：能力清單那一行＋agent.always＋（load=always）每輪都給的工具規格（名稱、說明、約 60 字的參數）。"""
        n = len(self.line()) + 1 if self.listed and (self.index or self.topics) else 0
        if self.always:
            n += len(self.always) + 1
        if self.load == "always":
            n += sum(len(c["tool"]) + len(c.get("summary") or "") + 60 for c in self.commands)
        return n


@dataclass
class AgentIndex:
    entries: List[Entry] = field(default_factory=list)

    def get(self, name: str) -> Optional[Entry]:
        return next((e for e in self.entries if e.name == name), None)

    def total_chars(self) -> int:
        return sum(len(line) + 1 for line in shrink(self.entries))

    def to_dict(self) -> dict:
        return {"version": 1, "max_chars": INDEX_MAX, "total_chars": self.total_chars(),
                "entries": [{**asdict(e), "chars": e.chars()} for e in self.entries]}


# ── 系統層的登記口 ─────────────────────────────────────────────────────

def register_system(app, name: str, *, title: str, index: str = "", group: str = "", triggers: Sequence[str] = (),
                    load: str = "always", provides: Sequence[str] = (), promises: Optional[Dict[str, str]] = None,
                    always: str = "") -> Entry:
    """SYNOX 自己的系統能力（提醒、排程、通知…）登記進索引。同名再登記＝換掉（系統自己的程式在載入工具前呼叫最好；
    之後呼叫也會更新已經彙整好的索引）。寫錯丟 ValueError。"""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError(f"系統能力名字只能是小寫英數字、_：{name!r}")
    if load not in LOADS:
        raise ValueError(f"load 只能是 {'、'.join(LOADS)}")
    promises = dict(promises or {})
    bad = [k for k, v in promises.items() if v not in PROMISE_KINDS]
    if bad:
        raise ValueError(f"promises 的值只能是 {'、'.join(PROMISE_KINDS)}：{'、'.join(bad)}")
    if len(always or "") > ALWAYS_MAX:
        raise ValueError(f"always 最多 {ALWAYS_MAX} 字")
    entry = Entry(name=name, title=str(title or name), index=" ".join(str(index or "").split())[:60], source="system",
                  group=group, triggers=[str(t).strip() for t in triggers if str(t).strip()][:12], load=load,
                  provides=list(provides), promises=promises, always=(always or "").strip())
    _systems(app)[name] = entry
    built = (getattr(app, "extras", None) or {}).get(INDEX_KEY)
    if built is not None:                              # 已經彙整過（例如系統層在工具之後才登記）：就地更新
        _fill_commands(app, entry)
        built.entries = [e for e in built.entries if not (e.source == "system" and e.name == name)]
        built.entries.insert(sum(1 for e in built.entries if e.source == "system"), entry)
    return entry


def _systems(app) -> Dict[str, Entry]:
    return app.extras.setdefault(SYSTEM_KEY, {})


# 出廠一定有的系統能力：系統自己的程式還沒登記時用這幾筆（登記過就以它們的為準）。
CORE_ENTRIES = {
    "remind": dict(title="⏰ 提醒（系統）", group="remind", load="always",
                   index="在指定的時間提醒使用者一件事（每天或某一天）、記沒有時間的待辦、看／完成／刪",
                   triggers=["提醒", "叫我", "鬧鐘", "記得", "別忘了", "待辦", "試響"],
                   provides=["remind.add", "remind.todo", "remind.done", "remind.list", "remind.rm", "remind.test"],
                   promises={"add": "schedule", "test": "schedule"}),
    "schedule": dict(title="🗓 排程（系統）", group="schedule", load="on_trigger",
                     index="到了時間替使用者執行一個指令（每天或某一天）",
                     triggers=["排程", "定時", "每天幫我", "自動執行"],
                     provides=["schedule.add", "schedule.list", "schedule.rm"], promises={"add": "schedule"}),
    "notify": dict(title="🔔 通知（系統）", group="", load="on_call", index=""),
}


def ensure_core(app) -> None:
    """出廠的系統能力沒登記的補登記（setdefault）。packs/loader.load_all 開頭呼叫。"""
    systems = _systems(app)
    for name, spec in CORE_ENTRIES.items():
        if name not in systems:
            register_system(app, name, **spec)


def system_names(app) -> List[str]:
    """這台有的系統能力（requires.system 對這份）。"""
    return sorted(set(CORE_SYSTEM) | set(_systems(app)))


# ── 彙整 ───────────────────────────────────────────────────────────────

def _leaves_under(app, group: str):
    registry = getattr(app, "registry", None)
    if registry is None or not group:
        return []
    prefix = group + "."
    return [n for n in registry.leaves() if n.path.startswith(prefix)]


def _fill_commands(app, entry: Entry) -> None:
    entry.commands = [{"name": n.path[len(entry.group) + 1:], "tool": n.path.replace(".", SEP),
                       "effect": str(getattr(n, "effect", "") or ""), "summary": str(getattr(n, "summary", "") or "")}
                      for n in _leaves_under(app, entry.group)]


def _sha(folder: str) -> str:
    try:
        with open(os.path.join(folder, "pack.json"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _skill_name(m) -> str:
    try:
        from synox.agent.skills import parse, read_text
        meta, _ = parse(read_text(m.skill_path))
        return str(meta.get("name") or "")
    except (OSError, UnicodeDecodeError):
        return ""


def entry_from_manifest(m) -> Entry:
    """不用載入、只看 pack.json 的 Entry（安裝報告、健康檢查用）：指令只有 cli／mcp 看得到（python 寫在程式裡）。"""
    agent = getattr(m, "agent", None) or {}
    text = agent.get("index") or " ".join(str(m.summary or "").split())
    if len(text) > 60:
        text = text[:59] + "…"
    names = [c.get("name") for c in m.commands if isinstance(c, dict)] if m.kind == "cli" else \
        list((m.mcp or {}).get("tools_allow") or []) if m.kind == "mcp" else []
    summaries = {c.get("name"): str(c.get("summary") or "") for c in m.commands if isinstance(c, dict)}
    return Entry(name=m.name, title=m.title, index=text, group=m.group,
                 triggers=list(agent.get("triggers") or []), load=agent.get("load") or "on_trigger",
                 provides=list(agent.get("provides") or []), promises=dict(agent.get("promises") or {}),
                 always=agent.get("always") or "", topics=sorted((agent.get("topics") or {}).keys()),
                 commands=[{"name": n, "tool": f"{m.group}{SEP}{n}", "effect": "", "summary": summaries.get(n, "")}
                           for n in names if isinstance(n, str)],
                 kind=m.kind, version=m.version, listed=not getattr(m, "registered_only", False),
                 warnings=[dict(w) for w in getattr(m, "warnings", None) or []])


def static_index(manifests: Iterable) -> AgentIndex:
    """出廠的系統能力＋這些工具的 pack.json → 索引（不載入；健康檢查用）。"""
    entries = [Entry(name=n, source="system", **{k: v for k, v in spec.items()}) for n, spec in sorted(CORE_ENTRIES.items())]
    entries += [entry_from_manifest(m) for m in manifests if getattr(m, "kind", "") != "theme"]
    return AgentIndex(entries)


def entry_for_pack(app, pack) -> Entry:
    """一個已載入的工具 → Entry（沒寫 agent 區塊＝summary 當那一行）。promises 指到不存在的指令：丟掉、記 log。"""
    m = pack.manifest
    entry = entry_from_manifest(m)
    entry.skill = _skill_name(m)
    entry.sha256 = _sha(m.folder)
    _fill_commands(app, entry)                    # 真的掛上去的指令（python 的指令寫在程式裡，載入後才知道）
    known = {c["name"] for c in entry.commands}
    dropped = [k for k in entry.promises if k not in known]
    if dropped:
        logging.warning("[AGENT] %s: agent.promises names %s, which are not its commands; ignored",
                        m.name, ", ".join(dropped))
        entry.promises = {k: v for k, v in entry.promises.items() if k in known}
    return entry


def build(app, config=None, packs: Optional[Iterable] = None, write: bool = True) -> AgentIndex:
    """系統層＋已載入的工具 → 索引（記憶體一份；write＝也寫 data/agent_index.json）。回索引。"""
    ensure_core(app)
    systems = _systems(app)
    entries: List[Entry] = []
    for name in sorted(systems):
        entry = systems[name]
        _fill_commands(app, entry)
        entries.append(entry)
    if packs is None:
        packs = app.extras.get("synox_packs", [])
    for pack in packs:
        if getattr(pack.manifest, "kind", "") == "theme":
            continue
        try:
            entries.append(entry_for_pack(app, pack))
        except Exception:
            logging.exception("[AGENT] %s: index entry failed (left out)", getattr(pack, "name", "?"))
    built = AgentIndex(entries)
    app.extras[INDEX_KEY] = built
    data_dir = getattr(config, "data_dir", None) or getattr(getattr(app, "config", None), "data_dir", None)
    if write and data_dir:
        write_file(built, data_dir)
    return built


def write_file(built: AgentIndex, data_dir: str) -> Optional[str]:
    path = os.path.join(data_dir, INDEX_FILE)
    try:
        os.makedirs(data_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(built.to_dict(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return path
    except OSError as e:
        logging.warning("[AGENT] cannot write %s: %s", path, e)
        return None


def current(app) -> AgentIndex:
    """記憶體裡的索引（還沒彙整過＝現在彙整一次，不寫檔）。"""
    built = (getattr(app, "extras", None) or {}).get(INDEX_KEY)
    if built is None:
        built = build(app, write=False)
    return built


# ── 給提示（第 3、4 層）與挑工具用 ──────────────────────────────────────

def shrink(entries: Sequence[Entry], limit: int = INDEX_MAX) -> List[str]:
    """能力清單的每一行：總量（每行＋換行）超過 limit 就照 LINE_STEPS 逐級縮短說明；縮到只剩標題還超過，
    從後面併成「…另有 N 項」。只列 listed 的、有東西可說的（有說明、主題或指令）。"""
    shown = [e for e in entries if e.listed and (e.index or e.topics or e.commands)]
    if not shown:
        return []
    for step in (None,) + LINE_STEPS:
        lines = [e.line(step) for e in shown]
        if sum(len(x) + 1 for x in lines) <= limit:
            return lines
    # 只剩標題還超過：從後面併成「…另有 N 項」。有標記警告的（ADR 0041）最後才併——警告不能因為清單太長就不見
    order = sorted(range(len(shown)), key=lambda i: (bool(shown[i].warnings), -i))   # 先丟沒警告、排在後面的
    kept = list(range(len(shown)))
    for drop in [None] + order:
        if drop is not None:
            kept.remove(drop)
        if not kept:
            break
        lines = [shown[i].line(0) for i in kept]
        more = len(shown) - len(kept)
        tail = [f"- …另有 {more} 項（用 skill_read 或直接問）"] if more else []
        if sum(len(x) + 1 for x in lines + tail) <= limit:
            return lines + tail
    return []


def _visible(app, entry: Entry, user, names: Optional[set]) -> bool:
    if entry.source == "pack" and names is not None:
        return entry.name in names
    if user is None or not entry.group:
        return True
    registry = app.registry
    node = registry.node(entry.group)
    if node is None:
        return entry.source == "system" and not entry.commands
    return bool(registry.visible(user, node))


def visible_entries(app, user=None, packs: Optional[Iterable] = None) -> List[Entry]:
    """這個人看得到的項目。packs＝他看得到的工具（例如 loop.visible_packs(user)）；沒給＝照群組權限自己算。"""
    names = {p.manifest.name for p in packs} if packs is not None else None
    return [e for e in current(app).entries if _visible(app, e, user, names)]


def lines_for(app, user=None, packs: Optional[Iterable] = None, limit: int = INDEX_MAX) -> List[str]:
    """提示第 3、4 層的能力清單：這個人看得到的系統能力＋工具，每項一行，總量 limit 字內（超過自動縮短）。"""
    return shrink(visible_entries(app, user, packs), limit)


def prompt_block(app, user=None, packs: Optional[Iterable] = None, limit: int = INDEX_MAX,
                 heading: str = "## 能力清單（要細節：skill_read 讀說明書，〔主題〕用 topic 讀那一章）") -> str:
    entries = visible_entries(app, user, packs)
    rule = []
    if any(e.warnings for e in entries if e.listed):          # 有工具標了警告（ADR 0041）：多一行守則，告訴 AI 怎麼對待
        from synox.packs.packwarn import AGENT_RULE
        rule = [AGENT_RULE]
    lines = shrink(entries, max(0, limit - sum(len(r) + 1 for r in rule)))
    return "\n".join([heading] + rule + lines) if lines else ""


def always_lines(app, user=None, packs: Optional[Iterable] = None) -> List[str]:
    """每輪都要進提示的一小段（agent.always；只有系統層與核心信任的工具——第三方寫了 loader 不會載入）。"""
    return [e.always for e in visible_entries(app, user, packs) if e.always]


def keep_prefixes(app) -> tuple:
    """挑工具時永遠保留的工具名開頭：load=always 的項目＋app 登記的系統群組（loader.SYSTEM_GROUPS_KEY）。"""
    from synox.packs.loader import SYSTEM_GROUPS_KEY
    groups = [e.group for e in current(app).entries if e.load == "always" and e.group]
    groups += list((getattr(app, "extras", None) or {}).get(SYSTEM_GROUPS_KEY) or {})
    return tuple(f"{g}{SEP}" for g in dict.fromkeys(groups))


def trigger_map(app) -> Dict[str, List[str]]:
    """{工具名開頭（group__）: [觸發字…]}：使用者這句話有其中一個字，那個群組的工具這一輪優先排進來。"""
    return {f"{e.group}{SEP}": list(e.triggers) for e in current(app).entries if e.triggers and e.group}


def promised_tools(app) -> Dict[str, str]:
    """{工具名: schedule｜watch}：這些指令成功之後，AI 才可以說「會…／到時候…」（承諾把關用）。"""
    return {f"{e.group}{SEP}{cmd}": kind for e in current(app).entries if e.group
            for cmd, kind in e.promises.items()}


def topics_of(app, pack_name: str) -> Dict[str, str]:
    """工具的說明書主題：{主題名: 檔案的完整路徑}（只給 agent.skill.topics 宣告過的）。"""
    for pack in app.extras.get("synox_packs", []):
        if pack.manifest.name == pack_name:
            topics = (getattr(pack.manifest, "agent", None) or {}).get("topics") or {}
            return {k: os.path.join(pack.manifest.folder, v) for k, v in topics.items()}
    return {}


# ── 相依（loader、doctor 共用） ─────────────────────────────────────────

def dependency_problems(m, loaded: Dict[str, str], systems: Iterable[str]) -> List[str]:
    """requires.packs／requires.system 缺了什麼（loaded＝{已載入的工具名: 版本}）；都有＝[]。"""
    from synox.packs.manifest import pack_version_problem, required_packs, required_system
    out: List[str] = []
    try:
        packs = required_packs(m.requires)
        system = required_system(m.requires)
    except ValueError as e:
        return [str(e)]
    for name, spec in packs:
        problem = pack_version_problem(name, spec, loaded.get(name))
        if problem:
            out.append(f"工具 {problem}")
    have = set(systems)
    out += [f"系統能力 {s}（這台的 SYNOX 沒有）" for s in system if s not in have]
    return out


def usage_lines(built: AgentIndex, top: int = 3) -> List[str]:
    """健康檢查用：總量、每項每輪佔用（最大的 top 個標 ⚠️）。"""
    total = built.total_chars()
    rows = sorted(((e.chars(), e) for e in built.entries if e.chars()), key=lambda x: (-x[0], x[1].name))
    head = f"AI 能力清單：每輪約 {total} 字（上限 {INDEX_MAX}，超過會自動縮短每行）" + \
        ("　⚠️ 已經在縮短" if sum(len(e.line()) + 1 for e in built.entries if e.listed and e.index) > INDEX_MAX else "")
    out = [head]
    for i, (n, e) in enumerate(rows):
        out.append(f"  {'⚠️ ' if i < top else '· '}{e.name}：每輪約 {n} 字" + ("（系統）" if e.source == "system" else ""))
    return out
