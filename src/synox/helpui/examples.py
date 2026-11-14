"""
指令的白話說明與範例：pack.json 最上層的 `help` 區塊（為主）＋ python pack 的 `kit.command(..., plain=, examples=)`（為輔）。

    "help": {
      "featured": ["add", "month", "list"],             # /help 工具卡「最常用」（最多 5 個；沒寫＝主要動作＋有範例的）
      "commands": {
        "add": {
          "plain": "把一筆花掉的錢記下來",              # 一句白話（40 字內、不要括號補充、不要 = 這種符號）
          "examples": [                                  # 最多 3 個；text 只寫參數（不寫 /money，SYNOX 自己補）
            {"text": "120 午餐", "note": "午餐花了 120 元"},
            "350 交通 計程車"                              # 只有字＝{"text": …}
          ],
          "alias_suggest": ["記帳"]                       # 建議的自訂名字（網頁「我的指令」一鍵套用；最多 2 個）
        }
      }
    }

- 鍵＝這個 pack 的指令（葉節點）名字：`/money` 的主要動作是 add、`/money_month` 是 month。
- cli pack 也可以寫在 `commands[].plain`／`commands[].examples`；兩邊都寫以最上層的 `help` 為準。
- 第 1 關（安裝時 strict）：格式、長度、內容（不准網址、信箱、像在對 AI 下指令的字、像密鑰的字）。載入時寬鬆：壞的那一條丟掉、log 一行。
- 範例一定跑得動：載入後用那個指令真的參數規則（kit.parse_args）解析一次，缺必填或格式錯的範例丟掉，doctor 報（`dropped`）。
- 只給人看：不進 AI 的提示與工具說明（那是 commands[].ai.scenario 的事，docs/adr/0013）。
- 白話檢查只擋明顯的術語（JARGON；擁有者 2026-11-14 決定 10）：安裝報告提醒、不擋安裝。好不好懂要人唸過才知道。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

MAX_PLAIN = 40
MAX_EXAMPLES = 3
MAX_EXAMPLE_TEXT = 80
MAX_NOTE = 60
MAX_FEATURED = 5
MAX_SUGGEST = 2
HELP_KEYS = {"featured", "commands"}
COMMAND_KEYS = {"plain", "examples", "alias_suggest"}
EXAMPLE_KEYS = {"text", "note"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
# plain 不要「（例外情況）」這種補充、不要 key=value 這種符號（寫作守則 docs/tools.md）
PLAIN_BANNED = re.compile(r"[()（）\[\]［］<>＜＞{}｛｝=＝]")
# 範例與白話裡不准的內容（跟 commands[].ai.scenario 同一套，runtime/ledger.py 的 risk_flags）
CONTENT_RISKS = ("有網址或網域", "有電子郵件", "像在對 AI 下指令（忽略／改掉規則）", "要跳過確認或核准", "夾了標記或分隔符")
# 明顯的術語（只擋明顯的；比對不分大小寫、整個詞）。要加新詞：只加「一般人一定聽不懂」的
JARGON = ("API", "token", "integration", "CalDAV", "ics", "JSON", "OAuth", "webhook", "endpoint", "CLI", "argv",
          "stdin", "stdout", "regex", "UUID", "payload", "schema", "SDK", "MCP", "SQL", "YAML", "cron", "bool",
          "boolean", "string", "int", "null", "config", "參數", "字串", "布林", "陣列", "回傳值", "正規表示式",
          "整數型別", "物件")
_JARGON_RE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(w) for w in JARGON if w.isascii()) + r")(?![A-Za-z0-9])",
                        re.IGNORECASE)
_JARGON_CJK = tuple(w for w in JARGON if not w.isascii())


class HelpError(ValueError):
    pass


def one_line(value, label: str, limit: int, allow_empty: bool = False) -> str:
    from synox.packs.manifest import _CONTROL_RE
    if not isinstance(value, str):
        return f"{label} 要是一段字"
    if not value.strip() and not allow_empty:
        return f"{label} 不能是空的"
    if len(value) > limit:
        return f"{label} 太長了（最多 {limit} 字，現在 {len(value)}）"
    if _CONTROL_RE.search(value):
        return f"{label} 不能有換行或控制字元"
    return ""


def content_problem(value: str, label: str) -> str:
    """不准網址、信箱、像在對 AI 下指令或要跳過確認的字、分隔符、像密鑰的字（範例只能是佔位資料）。"""
    from synox.packs import kit
    from synox.runtime.ledger import risk_flags
    bad = [flag for flag in risk_flags(value) if flag in CONTENT_RISKS]
    if kit.mask_tokens(value) != value:
        bad.append("像密鑰或 token")
    return f"{label} 不能{'、'.join(bad)}（只放假的佔位資料）" if bad else ""


def jargon(text: str) -> List[str]:
    """一段給人看的字裡有哪些明顯的術語（白話檢查；只提醒）。"""
    found = [m.group(1) for m in _JARGON_RE.finditer(text or "")]
    found += [w for w in _JARGON_CJK if w in (text or "")]
    return list(dict.fromkeys(found))


def plain_problem(value, label: str = "plain") -> str:
    problem = one_line(value, label, MAX_PLAIN)
    if problem:
        return problem
    if PLAIN_BANNED.search(value):
        return f"{label} 不要用括號補充或 = 這種符號（一句話說會發生什麼；要示範怎麼打就寫成範例）"
    return content_problem(value, label)


def parse_example(raw, label: str) -> Tuple[Optional[dict], str]:
    """一個範例 → ({"text", "note"}, "") 或 (None, 原因)。"""
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None, f"{label} 要是一段字或 {{\"text\": …, \"note\": …}}"
    extra = set(raw) - EXAMPLE_KEYS
    if extra:
        return None, f"{label} 不認得 {'、'.join(sorted(map(str, extra)))}"
    text = raw.get("text", "")
    problem = one_line(text, f"{label}.text", MAX_EXAMPLE_TEXT, allow_empty=True)
    if not problem and text.strip()[:1] in ("/", "／"):
        problem = f"{label}.text 只寫參數，不要寫指令名（SYNOX 會照每個人的叫法補上，例如 \"120 午餐\"）"
    problem = problem or content_problem(text, f"{label}.text")
    note = raw.get("note", "")
    if not problem and "note" in raw:
        problem = one_line(note, f"{label}.note", MAX_NOTE) or content_problem(note, f"{label}.note")
    if problem:
        return None, problem
    out = {"text": " ".join(text.split())}
    if note.strip():
        out["note"] = note.strip()
    return out, ""


def parse_entry(raw, where: str) -> Tuple[dict, List[str]]:
    """一個指令的 {plain, examples, alias_suggest} → (整理好的, 問題)。壞的那一項丟掉，其他照收。"""
    problems: List[str] = []
    if not isinstance(raw, dict):
        return {}, [f"{where} 要是 {{\"plain\": …, \"examples\": […]}}"]
    extra = set(raw) - COMMAND_KEYS
    if extra:
        problems.append(f"{where} 不認得 {'、'.join(sorted(map(str, extra)))}（只收 plain、examples、alias_suggest）")
    out: dict = {}
    if "plain" in raw:
        problem = plain_problem(raw["plain"], f"{where}.plain")
        if problem:
            problems.append(problem)
        else:
            out["plain"] = raw["plain"].strip()
    if "examples" in raw:
        items = raw["examples"]
        if not isinstance(items, list):
            problems.append(f"{where}.examples 要是清單")
        else:
            if len(items) > MAX_EXAMPLES:
                problems.append(f"{where}.examples 最多 {MAX_EXAMPLES} 個（現在 {len(items)}）")
            good = []
            for i, item in enumerate(items[:MAX_EXAMPLES]):
                ex, problem = parse_example(item, f"{where}.examples[{i}]")
                if problem:
                    problems.append(problem)
                else:
                    good.append(ex)
            if good:
                out["examples"] = good
    if "alias_suggest" in raw:
        items = raw["alias_suggest"]
        if not isinstance(items, list) or len(items) > MAX_SUGGEST:
            problems.append(f"{where}.alias_suggest 要是名字的清單（最多 {MAX_SUGGEST} 個）")
        else:
            from synox import aliases
            good = []
            for name in items:
                problem = aliases.name_problem(name)
                if problem:
                    problems.append(f"{where}.alias_suggest {name!r}：{problem}")
                else:
                    good.append(name.strip())
            if good:
                out["alias_suggest"] = good
    return out, problems


def parse_block(raw, command_names: Optional[Sequence[str]] = None) -> Tuple[dict, List[str]]:
    """pack.json 的 help 區塊 → ({"featured": [...], "commands": {名字: {...}}}, 問題)。
    command_names：知道這個 pack 有哪些指令時（cli）順便檢查名字；python pack 要載入後才知道（給 None）。"""
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["help 要是 {\"featured\": […], \"commands\": {…}} 物件"]
    problems: List[str] = []
    extra = set(raw) - HELP_KEYS
    if extra:
        problems.append(f"help 不認得 {'、'.join(sorted(map(str, extra)))}（只收 featured、commands）")
    known = set(command_names) if command_names is not None else None
    out: dict = {"commands": {}}
    cmds = raw.get("commands", {})
    if not isinstance(cmds, dict):
        problems.append("help.commands 要是 {指令名: {…}} 物件")
        cmds = {}
    for name, entry in cmds.items():
        if not isinstance(name, str) or not NAME_RE.match(name):
            problems.append(f"help.commands 的鍵 {name!r} 要是指令名（小寫英數字、_）")
            continue
        if known is not None and name not in known:
            problems.append(f"help.commands.{name}：這個 pack 沒有叫 {name} 的指令")
            continue
        parsed, why = parse_entry(entry, f"help.commands.{name}")
        problems += why
        if parsed:
            out["commands"][name] = parsed
    if "featured" in raw:
        feat = raw["featured"]
        if not isinstance(feat, list) or len(feat) > MAX_FEATURED or \
                not all(isinstance(n, str) and NAME_RE.match(n) for n in feat):
            problems.append(f"help.featured 要是指令名的清單（最多 {MAX_FEATURED} 個）")
        else:
            bad = [n for n in feat if known is not None and n not in known]
            if bad:
                problems.append(f"help.featured 有這個 pack 沒有的指令：{'、'.join(bad)}")
            out["featured"] = [n for n in dict.fromkeys(feat) if n not in bad]
    return out, problems


def from_manifest(raw: dict, kind: str, cli_commands: Sequence[dict], strict: bool) -> Tuple[dict, List[str]]:
    """pack.json → 整理好的 help（最上層的 help 區塊＋cli 的 commands[].plain／examples，最上層優先）＋問題。
    cli 的範例另外照 pack.json 宣告的欄位解析一次（安裝時就知道跑不跑得動）。"""
    names = [c.get("name") for c in cli_commands if isinstance(c, dict)] if kind == "cli" else None
    block, problems = parse_block(raw.get("help"), names)
    block.setdefault("commands", {})
    if kind == "cli":
        for c in cli_commands:
            if not isinstance(c, dict) or not isinstance(c.get("name"), str):
                continue
            inline = {k: c[k] for k in ("plain", "examples") if k in c}
            if not inline:
                continue
            parsed, why = parse_entry(inline, f"command {c['name']}")
            problems += why
            if parsed:
                merged = dict(parsed)
                merged.update(block["commands"].get(c["name"], {}))
                block["commands"][c["name"]] = merged
        for c in cli_commands:
            entry = (block.get("commands") or {}).get(c.get("name")) if isinstance(c, dict) else None
            if not entry or not entry.get("examples"):
                continue
            fields, positional = cli_fields(c)
            for ex in entry["examples"]:
                why = example_problem(fields, positional, ex["text"])
                if why:
                    problems.append(f"help.commands.{c['name']} 的範例「{ex['text']}」跑不動：{why}")
    if not strict and problems:
        logging.warning("[PACKS] help block: %s (bad entries dropped)", "；".join(problems[:5]))
    return block if block.get("commands") or block.get("featured") else {}, problems


def cli_fields(c: dict):
    """cli 的 command（pack.json）→ (kit 用的 Field 清單, 照位置填幾個)：跟 loader 建指令時同一份規則。"""
    from isdtelekit.core.registry import Field
    fields = [Field(f["name"], f.get("ask", f["name"]), required=bool(f.get("required")),
                    choices=tuple(f.get("choices") or ()))
              for f in c.get("fields") or [] if isinstance(f, dict) and isinstance(f.get("name"), str)]
    n_required = sum(1 for f in fields if f.required)
    try:
        positional = int(c.get("positional", n_required))
    except (TypeError, ValueError):
        positional = n_required
    return fields, max(0, min(positional, len(fields)))


def example_problem(fields, positional: Optional[int], text: str) -> str:
    """這個範例用那個指令的參數規則解析得過嗎（""＝過）。"""
    from synox.packs import kit
    values, missing, errors = kit.parse_args(tuple(fields), text.split(), positional)
    if errors:
        return "；".join(errors)
    if missing:
        return "少了 " + "、".join(f.ask for f in missing)
    return ""


def lint_warnings(block: dict) -> List[str]:
    """白話檢查（只提醒、不擋）：plain／note 裡明顯的術語。"""
    out = []
    for name, entry in sorted((block.get("commands") or {}).items()):
        texts = [entry.get("plain", "")] + [ex.get("note", "") for ex in entry.get("examples") or []]
        words = jargon(" ".join(texts))
        if words:
            out.append(f"help.commands.{name} 的說明有術語「{'、'.join(words)}」：一般人可能看不懂，請改成白話"
                       "（寫作守則見 docs/tools.md「指令的白話說明」）")
    return out


# ── 載入後：每個指令的 plain／examples（給 /help、網頁） ────────────────────────────

META_KEYS = ("plain", "examples", "alias_suggest")


def node_runnable(node, text: str) -> str:
    """這個範例在這個節點上跑不跑得動（""＝可以，或沒辦法檢查）。kit.command 的指令才查得到規則。"""
    positional = getattr(node, "kit_positional", None)
    if positional is None:
        return ""
    return example_problem(node.fields, positional, text)


def attach(app, pack) -> List[str]:
    """loader 載入一個 pack 之後叫：把 help 區塊（＋kit.command 的 plain／examples）放進 synox_tool_meta[節點路徑]，
    跑不動的範例丟掉，回丟掉的說明（doctor 也看得到：app.extras["synox_help_dropped"]）。"""
    m = pack.manifest
    registry = app.registry
    group = registry.node(m.group)
    if group is None:
        return []
    block = getattr(m, "help", None) or {}
    declared = block.get("commands") or {}
    meta = app.extras.setdefault("synox_tool_meta", {})
    dropped: List[str] = []
    for node in [n for n in group.walk() if not n.is_group]:
        entry: dict = {}
        code = getattr(node, "help_doc", None) or {}          # kit.command(..., plain=, examples=)
        for key in META_KEYS:
            if key in code:
                entry[key] = code[key]
        entry.update({k: v for k, v in (declared.get(node.name) or {}).items() if k in META_KEYS})
        if "examples" in entry:
            keep = []
            for ex in entry["examples"]:
                why = node_runnable(node, ex["text"])
                if why:
                    dropped.append(f"{m.name}：{node.command} 的範例「{ex['text']}」跑不動（{why}），沒有顯示")
                else:
                    keep.append(ex)
            entry["examples"] = keep
        if entry:
            meta.setdefault(node.path, {}).update(entry)
    featured = [n for n in block.get("featured") or [] if n in group.children]
    if featured:
        app.extras.setdefault("synox_help_featured", {})[m.group] = featured
    if dropped:
        for line in dropped:
            logging.warning("[PACKS] %s", line)
        app.extras.setdefault("synox_help_dropped", []).extend(dropped)
    return dropped


def doc_of(app, node) -> dict:
    """{"plain", "examples": [{"text", "note"}], "alias_suggest"}（沒寫的不在裡面）。"""
    meta = (app.extras.get("synox_tool_meta") or {}).get(node.path) or {}
    out = {k: meta[k] for k in META_KEYS if meta.get(k)}
    if "examples" not in out:
        code = getattr(node, "help_doc", None) or {}       # 系統指令也可以用 kit.command(..., examples=)
        out.update({k: code[k] for k in META_KEYS if code.get(k) and k not in out})
    return out


def check_code_doc(plain: Optional[str], examples) -> dict:
    """kit.command(..., plain=, examples=) 的參數：寫錯就在載入時丟 ValueError（作者馬上看得到）。"""
    raw: dict = {}
    if plain is not None:
        raw["plain"] = plain
    if examples is not None:
        raw["examples"] = list(examples)
    parsed, problems = parse_entry(raw, "kit.command")
    if problems:
        raise ValueError("；".join(problems))
    return parsed
