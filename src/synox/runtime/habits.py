"""
習慣與規則（核心統一規劃 11.4）：使用者的習慣寫在 soul.md 的「## 習慣與規則」段，一行一條，人話在前、程式讀的值在後：

    ## 習慣與規則
    - 上完課一段時間內不排東西。〔schedule.class.after_minutes=90〕
    - 一天最多排一部，不要切段。〔schedule.plan.per_day=1〕〔schedule.plan.split=no〕

- 〔key=value〕可以有好幾個；value 是 JSON 字面值（90、true、["a"]、"字串"）或不含 〕 的純字串。
- 有哪些鍵、什麼型別、預設多少：由各工具的 pack.json `agent.prefs` 宣告（`parse_decls`）；SYNOX 自己不寫死任何鍵。
- 這一段是擁有者的：常駐助理（append_notes／filter_notes）、soul 帳本的整理都碰不到；只有擁有者直接改，
  或 AI 用 `soul__propose_habit` 提議、擁有者按 ✅（runtime/habit_card.py）才會寫。
- 工具拿到值的方式：kind=cli 的 `{prefs_file}`（只有那個工具宣告的鍵、每次一個資料夾、用完就刪；`write_prefs_file`）、
  kind=python 的 `pack.prefs(user, chat_id)`。只有擁有者自己的對話才帶 soul 裡的值；成員、頻道＝宣告的預設值（`values_for`）。

這個檔只有純函式（不碰保管箱、不碰 registry），SoulStore、loader、網頁、匯入程式都用它。
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HEADING = "## 習慣與規則"
TYPES = ("int", "number", "bool", "time", "str", "regex", "list", "json")
LOOSER = ("smaller", "larger")
PREFS_MAX = 40                     # 一個工具最多宣告幾個鍵
KEY_MAX = 64
ASK_MAX = 60
LINE_MAX = 500                     # 一行（含〔〕）最多幾個字（JSON 值，例如吃飯時窗、標題規則，可能比較長）
TEXT_MAX = 200                     # 人話那段最多幾個字
REGEX_MAX = 200
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")
_GROUP = re.compile(r"〔([^〔〕]*)〕")
_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
TRUE_WORDS = {"true", "yes", "on", "是", "要", "開"}
FALSE_WORDS = {"false", "no", "off", "否", "不要", "關"}
PREFS_DIR = "prefs"                # data/prefs/<工具>/<每次一個亂數資料夾>/prefs.json：{prefs_file}（用完連資料夾刪）

UNUSED = "目前沒有工具在用"
LOOSER_WORD = "放寬"


class HabitError(ValueError):
    """一句給人看的話。"""


# ── 宣告（pack.json agent.prefs） ─────────────────────────────────────

@dataclass(frozen=True)
class Pref:
    key: str
    type: str
    default: Any = None
    ask: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    looser: str = ""
    pack: str = ""                 # 宣告它的工具（名字）
    title: str = ""                # 宣告它的工具（給人看的名字）

    def as_dict(self) -> dict:
        out = {"key": self.key, "type": self.type, "default": self.default}
        for name in ("ask", "min", "max", "looser"):
            value = getattr(self, name)
            if value not in ("", None):
                out[name] = value
        return out


def parse_decls(raw, *, pack: str = "", title: str = "") -> Tuple[List[Pref], List[str]]:
    """pack.json 的 agent.prefs → (Pref 清單, 問題清單)。壞掉的那一項不收（安裝時 strict＝有問題就拒裝）。"""
    if raw is None:
        return [], []
    if not isinstance(raw, list) or len(raw) > PREFS_MAX:
        return [], [f"agent.prefs 要是清單（最多 {PREFS_MAX} 項），每項 {{\"key\", \"type\", \"default\"}}"]
    out: List[Pref] = []
    bad: List[str] = []
    seen = set()
    for i, item in enumerate(raw):
        where = f"agent.prefs[{i}]"
        if not isinstance(item, dict):
            bad.append(f"{where} 要是物件")
            continue
        unknown = sorted(str(k) for k in item if k not in ("key", "type", "default", "ask", "min", "max", "looser"))
        if unknown:
            bad.append(f"{where} 不認得 {'、'.join(unknown)}")
            continue
        key = item.get("key")
        if not isinstance(key, str) or len(key) > KEY_MAX or not KEY_RE.match(key):
            bad.append(f"{where}.key 要是小寫英數字與點（像 schedule.plan.per_day，{KEY_MAX} 字內）")
            continue
        where = f"agent.prefs 的 {key}"
        if key in seen:
            bad.append(f"{where} 宣告了兩次")
            continue
        kind = item.get("type")
        if kind not in TYPES:
            bad.append(f"{where}：type 只能是 {'、'.join(TYPES)}")
            continue
        ask = item.get("ask", "")
        if not isinstance(ask, str) or len(ask) > ASK_MAX or "\n" in ask or "〔" in ask or "〕" in ask:
            bad.append(f"{where}：ask 要是一行字（{ASK_MAX} 字內，不能有〔〕）")
            continue
        lo, hi = item.get("min"), item.get("max")
        if any(v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))) for v in (lo, hi)):
            bad.append(f"{where}：min／max 要是數字")
            continue
        if (lo is not None or hi is not None) and kind not in ("int", "number"):
            bad.append(f"{where}：只有 int／number 可以寫 min／max")
            continue
        looser = item.get("looser", "")
        if looser not in ("",) + LOOSER:
            bad.append(f"{where}：looser 只能是 smaller（越小越寬鬆）或 larger（越大越寬鬆）")
            continue
        if looser and kind not in ("int", "number", "time"):
            bad.append(f"{where}：只有 int／number／time 可以寫 looser")
            continue
        pref = Pref(key=key, type=kind, default=item.get("default"), ask=ask.strip(),
                    min=lo, max=hi, looser=looser, pack=pack, title=title or pack)
        if "default" not in item:
            bad.append(f"{where}：要寫 default（沒有設定時工具拿到的值）")
            continue
        _value, problem = coerce(pref, item.get("default"))
        if problem:
            bad.append(f"{where}：default {problem}")
            continue
        seen.add(key)
        out.append(pref)
    return out, bad


# ── 值 ─────────────────────────────────────────────────────────────

def read_raw(raw: str) -> Any:
    """〔key=raw〕的 raw → 值：JSON 字面值優先，不是 JSON 就當純字串（去頭尾空白）。"""
    text = (raw or "").strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def coerce(pref: Pref, value: Any, raw: Optional[str] = None) -> Tuple[Any, str]:
    """照宣告的型別檢查／轉換 → (值, 問題)；問題是 "" 才算合格。raw＝原本寫的字（字串型別用它，"007" 不會變成 7）。"""
    kind = pref.type
    text = raw.strip() if isinstance(raw, str) else (value if isinstance(value, str) else None)
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "要是整數"
        return _range(pref, value)
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, "要是數字"
        return _range(pref, value)
    if kind == "bool":
        if isinstance(value, bool):
            return value, ""
        word = str(value).strip().lower() if isinstance(value, str) else ""
        if word in TRUE_WORDS:
            return True, ""
        if word in FALSE_WORDS:
            return False, ""
        return None, "要是 true／false（或 yes／no）"
    if kind == "time":
        s = value if isinstance(value, str) else text
        if not isinstance(s, str) or (s and not _TIME.match(s)):
            return None, "要是 HH:MM（00:00～23:59；\"\" 是不檢查）"
        return s, ""
    if kind in ("str", "regex"):
        s = value if isinstance(value, str) else text
        if not isinstance(s, str):
            return None, "要是字串"
        if kind == "regex":
            if len(s) > REGEX_MAX:
                return None, f"太長（{REGEX_MAX} 字內）"
            try:
                re.compile(s)
            except re.error as e:
                return None, f"不是正規表示式（{e}）"
        return s, ""
    if kind == "list":
        if not isinstance(value, list):
            return None, "要是清單（像 [\"a\", \"b\"]）"
        return value, ""
    return value, ""                       # json：任何 JSON 值


def _range(pref: Pref, n) -> Tuple[Any, str]:
    if pref.min is not None and n < pref.min:
        return None, f"最小是 {_num(pref.min)}"
    if pref.max is not None and n > pref.max:
        return None, f"最大是 {_num(pref.max)}"
    return n, ""


def _num(n) -> str:
    return str(int(n)) if isinstance(n, float) and n.is_integer() else str(n)


def format_value(value: Any) -> str:
    """值 → 寫進〔〕的字。字串：讀回來還是同一個字串、而且沒有〕就照寫，不然寫成 JSON（〕寫成 \\u3015）。"""
    if isinstance(value, str):
        if value == value.strip() and value and "〕" not in value and "\n" not in value and read_raw(value) == value:
            return value
        return json.dumps(value, ensure_ascii=False).replace("〕", "\\u3015")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("〕", "\\u3015")


def _minutes(value) -> Optional[int]:
    if isinstance(value, str) and _TIME.match(value):
        return int(value[:2]) * 60 + int(value[3:])
    return None


def is_looser(pref: Optional[Pref], old: Any, new: Any) -> bool:
    """new 比 old 寬鬆嗎（照宣告的 looser）。沒宣告 looser、比不了＝False。time 的 ""（不檢查）比任何時間都寬鬆。"""
    if pref is None or not pref.looser or old == new:
        return False
    if pref.type == "time":
        if new == "" and old != "":
            return True
        a, b = _minutes(old), _minutes(new)
    else:
        a = old if isinstance(old, (int, float)) and not isinstance(old, bool) else None
        b = new if isinstance(new, (int, float)) and not isinstance(new, bool) else None
    if a is None or b is None:
        return False
    return b < a if pref.looser == "smaller" else b > a


# ── 一行與一段 ──────────────────────────────────────────────────────

@dataclass
class Line:
    row: int                                        # 在全文的第幾行（0 起算）
    line: str                                       # 整行（"- …"）
    text: str                                       # 人話（拿掉〔〕）
    pairs: List[Tuple[str, str]] = field(default_factory=list)   # [(key, raw)]

    @property
    def keys(self) -> List[str]:
        return [k for k, _r in self.pairs]


@dataclass
class Habits:
    lines: List[Line] = field(default_factory=list)
    values: Dict[str, Any] = field(default_factory=dict)          # 鍵 → 值（同鍵兩次：後面的贏）
    raw: Dict[str, str] = field(default_factory=dict)             # 鍵 → 原本寫的字
    conflicts: Dict[str, List[str]] = field(default_factory=dict)  # 鍵 → 寫到它的每一行（兩行以上才算）
    problems: List[Tuple[str, str]] = field(default_factory=list)  # (那一行, 為什麼)


def split_line(line: str) -> Tuple[str, List[Tuple[str, str]]]:
    """"- 人話〔a.b=1〕〔c.d=x〕" → ("人話", [("a.b", "1"), ("c.d", "x")])。語法壞掉丟 HabitError。"""
    body = (line or "").strip()
    if body.startswith("- "):
        body = body[2:]
    if len(line or "") > LINE_MAX:
        raise HabitError(f"一行最多 {LINE_MAX} 字")
    pairs: List[Tuple[str, str]] = []
    for m in _GROUP.finditer(body):
        inner = m.group(1)
        key, eq, raw = inner.partition("=")
        key = key.strip()
        if not eq:
            raise HabitError(f"〔{inner}〕少了 =（要寫〔鍵=值〕）")
        if not KEY_RE.match(key) or len(key) > KEY_MAX:
            raise HabitError(f"〔{inner}〕的鍵要是小寫英數字與點（像 schedule.plan.per_day）")
        if not raw.strip():
            raise HabitError(f"〔{inner}〕沒有值（要清空就寫 \"\" 或 []）")
        pairs.append((key, raw.strip()))
    rest = _GROUP.sub("", body)
    if "〔" in rest or "〕" in rest:
        raise HabitError("〔〕沒有成對（一個〔要配一個〕，裡面不能再有〔〕）")
    text = " ".join(rest.split())
    if len(text) > TEXT_MAX:
        raise HabitError(f"人話那段最多 {TEXT_MAX} 字")
    return text, pairs


def make_line(text: str, pairs: Iterable[Tuple[str, Any]] = ()) -> str:
    """人話＋[(鍵, 值)] → "- 人話〔鍵=值〕…"（值經 format_value）。"""
    text = " ".join(str(text or "").split()).lstrip("-• ").strip()
    return "- " + text + "".join(f"〔{k}={format_value(v)}〕" for k, v in pairs)


def span(rows: Sequence[str]) -> Optional[Tuple[int, int]]:
    """「## 習慣與規則」段在 rows 裡的（標題那一行, 下一個 ## 的位置）；沒有這段＝None。"""
    start = next((i for i, r in enumerate(rows) if r.strip() == HEADING), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(rows)) if rows[i].startswith("## ")), len(rows))
    return start, end


_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _rows(text: str) -> List[str]:
    """全文的每一行（註解換成同樣多行的空白，行號不變）。"""
    norm = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    blanked = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), norm)
    return blanked.split("\n")


def parse(text: str, decls: Optional[Dict[str, Pref]] = None) -> Habits:
    """soul.md 全文 → Habits。decls 有給＝宣告過的鍵照型別檢查（不合的記進 problems、不進 values）。"""
    out = Habits()
    rows = _rows(text)
    where = span(rows)
    if where is None:
        return out
    decls = decls or {}
    writers: Dict[str, List[str]] = {}
    for i in range(where[0] + 1, where[1]):
        row = rows[i].strip()
        if not row.startswith("- "):
            continue
        try:
            human, pairs = split_line(row)
        except HabitError as e:
            out.problems.append((row, str(e)))
            continue
        line = Line(row=i, line=row, text=human, pairs=pairs)
        out.lines.append(line)
        for key, raw in pairs:
            value = read_raw(raw)
            pref = decls.get(key)
            if pref is not None:
                value, problem = coerce(pref, value, raw)
                if problem:
                    out.problems.append((row, f"{key} {problem}"))
                    continue
            writers.setdefault(key, []).append(row)
            out.values[key] = value
            out.raw[key] = raw
    out.conflicts = {k: v for k, v in writers.items() if len(v) > 1}
    return out


def check_text(text: str, decls: Optional[Dict[str, Pref]] = None) -> str:
    """寫進 soul.md 之前：「習慣與規則」段有語法壞掉、型別不合宣告的行 → 一句話；沒事 → ""。"""
    problems = parse(text, decls).problems
    if not problems:
        return ""
    line, why = problems[0]
    more = f"（還有 {len(problems) - 1} 行也有問題）" if len(problems) > 1 else ""
    return f"「{HEADING[3:]}」這一行看不懂：{line}——{why}{more}"


def check_line(line: str, decls: Optional[Dict[str, Pref]] = None) -> Tuple[str, List[Tuple[str, Any]]]:
    """一行（要加進去的）→ (整理過的行, [(鍵, 值)])；壞掉丟 HabitError。"""
    raw_line = " ".join(str(line or "").split())
    if not raw_line:
        raise HabitError("是空的")
    if not raw_line.startswith("- "):
        raw_line = "- " + raw_line.lstrip("-• ")
    human, pairs = split_line(raw_line)
    if not human:
        raise HabitError("要有一句人話（〔〕前面寫這條是什麼意思）")
    values: List[Tuple[str, Any]] = []
    for key, raw in pairs:
        value = read_raw(raw)
        pref = (decls or {}).get(key)
        if pref is not None:
            value, problem = coerce(pref, value, raw)
            if problem:
                raise HabitError(f"{key} {problem}")
        values.append((key, value))
    return raw_line, values


def insert(text: str, line: str) -> Tuple[str, List[str], List[str]]:
    """把 line 加進「習慣與規則」段（加或取代）→ (新全文, 取代掉的行, 還有寫到同一個鍵的其他行)。

    - 鍵完全一樣的行（沒有〔〕的：字一樣的行）拿掉；新的一行放在這段最後（同鍵兩次是後面的贏，所以新的一定生效）。
    - 只有部分鍵重疊的行留著（那一行還寫了別的鍵），回在第三個值裡讓人知道。
    - 沒有這段：放在「## 助理筆記」之前；連那段都沒有就放檔尾。"""
    _human, pairs = split_line(line)
    keys = {k for k, _r in pairs}
    rows = (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n")
    where = span(rows)
    if where is None:
        from synox.runtime.soul import NOTES_HEADING
        at = next((i for i, r in enumerate(rows) if r.strip() == NOTES_HEADING), None)
        block = [HEADING, ""] if at is not None else ["", HEADING]
        if at is None:
            rows += block
        else:
            rows[at:at] = block
        where = span(rows)
    start, end = where
    replaced: List[str] = []
    shadowed: List[str] = []
    kept: List[str] = []
    for i in range(start + 1, end):
        row = rows[i]
        stripped = row.strip()
        if stripped.startswith("- "):
            try:
                _t, other = split_line(stripped)
            except HabitError:
                other = None
            if other is not None:
                other_keys = {k for k, _r in other}
                if (keys and other_keys == keys) or (not keys and not other_keys and stripped == line):
                    replaced.append(stripped)
                    continue
                if keys & other_keys:
                    shadowed.append(stripped)
        kept.append(row)
    while kept and not kept[-1].strip():
        kept.pop()
    tail = rows[end:]
    new_rows = rows[:start + 1] + kept + [line] + ([""] + tail if tail else [])
    return "\n".join(new_rows) + "\n", replaced, shadowed


# ── 誰宣告了什麼 ─────────────────────────────────────────────────────

def pack_prefs(pack) -> List[Pref]:
    """一個已載入工具宣告的 Pref（manifest.agent["prefs"] 是整理過的 dict 清單）。"""
    m = getattr(pack, "manifest", pack)
    agent = getattr(m, "agent", None) or {}
    out = []
    for d in agent.get("prefs") or []:
        try:
            out.append(Pref(key=d["key"], type=d["type"], default=d.get("default"), ask=d.get("ask", ""),
                            min=d.get("min"), max=d.get("max"), looser=d.get("looser", ""),
                            pack=getattr(m, "name", ""), title=getattr(m, "title", "") or getattr(m, "name", "")))
        except (KeyError, TypeError):
            continue
    return out


def declarations(app) -> Dict[str, Pref]:
    """已載入的工具宣告的鍵（同一個鍵兩個工具都宣告：先載入的那個的型別算數）。"""
    out: Dict[str, Pref] = {}
    for pack in (getattr(app, "extras", None) or {}).get("synox_packs", []) or []:
        for pref in pack_prefs(pack):
            out.setdefault(pref.key, pref)
    return out


def users_of(app) -> Dict[str, List[str]]:
    """鍵 → 宣告它的工具（給人看的名字）。"""
    out: Dict[str, List[str]] = {}
    for pack in (getattr(app, "extras", None) or {}).get("synox_packs", []) or []:
        for pref in pack_prefs(pack):
            names = out.setdefault(pref.key, [])
            if pref.title not in names:
                names.append(pref.title)
    return out


def owner_values(app) -> Dict[str, Any]:
    """擁有者 soul.md 裡的值（照目前的宣告檢查過；保管箱沒開＝{}）。"""
    from synox import runtime
    rt = runtime.of(app)
    soul = getattr(rt, "soul", None)
    if soul is None or not getattr(soul, "available", False):
        return {}
    try:
        return parse(soul.text(), declarations(app)).values
    except Exception:
        return {}


def is_owners_own(app, user, chat_id) -> bool:
    """擁有者自己的對話（私訊、網頁：chat_id 就是他自己）。chat_id 一定要給——None、群組、頻道、成員、訪客一律 False
    （不知道是哪個對話就當作不是他的，拿預設值）。"""
    if user is None or chat_id is None or not app.registry.is_owner(user):
        return False
    return chat_id == getattr(user, "tg_id", None)


def values_for(app, pack, user, chat_id) -> Dict[str, Any]:
    """這個工具宣告的鍵 → 這一次的值：擁有者自己的對話＝soul.md 的值蓋過預設；其他人、頻道＝預設值。
    只回這個工具宣告的鍵（別的工具的、沒人宣告的都不給）。"""
    prefs = pack_prefs(pack)
    out = {p.key: p.default for p in prefs}
    if prefs and is_owners_own(app, user, chat_id):
        mine = owner_values(app)
        out.update({k: mine[k] for k in out if k in mine})
    return out


def prefs_dir(data_dir: str, pack_name: str) -> str:
    return os.path.join(data_dir, PREFS_DIR, pack_name)


PREFS_FILE = "prefs.json"


def write_prefs_file(data_dir: str, pack_name: str, values: Dict[str, Any]) -> str:
    """{prefs_file}：每一次呼叫自己開一個資料夾 data/prefs/<工具>/<亂數>/，裡面只有 prefs.json；回那個檔的完整路徑。
    沙盒只准讀這一個資料夾（sandbox.grants_for 用檔案所在的資料夾），所以同一個工具同時被兩個人叫，彼此讀不到對方的檔。
    用完呼叫 remove_prefs_file（連資料夾一起刪）。"""
    base = prefs_dir(data_dir, pack_name)
    os.makedirs(base, exist_ok=True)
    while True:
        folder = os.path.join(base, secrets.token_hex(8))
        try:
            os.mkdir(folder)                         # 一定是新的（亂數撞到就再抽一次）
            break
        except FileExistsError:
            continue
    path = os.path.join(folder, PREFS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "prefs": values}, f, ensure_ascii=False)
    return path


def remove_prefs_file(path: str) -> None:
    """刪掉 {prefs_file} 與它那一次的資料夾（只刪 write_prefs_file 開的：檔名對、資料夾在 data/prefs/<工具>/ 底下）。"""
    if not path or os.path.basename(path) != PREFS_FILE:
        return
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        os.rmdir(os.path.dirname(path))
    except OSError:
        pass


def uses_prefs_file(m) -> bool:
    """這個 cli 工具的樣板有沒有 {prefs_file}（argv、env、stdin）。"""
    texts: List[str] = [str(t) for t in (getattr(m, "cli", {}) or {}).get("argv") or []]
    texts += [str(v) for v in ((getattr(m, "cli", {}) or {}).get("env") or {}).values()]
    for c in getattr(m, "commands", []) or []:
        texts += [str(t) for t in c.get("argv") or []]
        if c.get("stdin"):
            texts.append(str(c["stdin"]))
    return any("{prefs_file}" in t for t in texts)


# ── 網頁、doctor 看的 ────────────────────────────────────────────────

def view(text: str, decls: Dict[str, Pref], users: Dict[str, List[str]]) -> dict:
    """SOUL 頁的「習慣與規則」：每一行的鍵、值、誰在用、比預設寬鬆（紅字）、看不懂的行、同鍵兩次。"""
    h = parse(text, decls)
    winners = {k: rows[-1] for k, rows in h.conflicts.items()}
    lines = []
    for ln in h.lines:
        keys = []
        for key, raw in ln.pairs:
            pref = decls.get(key)
            value, problem = (coerce(pref, read_raw(raw), raw) if pref is not None else (read_raw(raw), ""))
            keys.append({"key": key, "value": format_value(value) if not problem else raw,
                         "used_by": users.get(key, []), "unused": key not in decls,
                         "looser": not problem and is_looser(pref, pref.default if pref else None, value),
                         "default": format_value(pref.default) if pref is not None else None,
                         "problem": problem,
                         "overridden": key in winners and winners[key] != ln.line})
        lines.append({"line": ln.line, "text": ln.text, "keys": keys})
    parsed = {x["line"] for x in lines}
    return {"heading": HEADING, "lines": lines,
            "problems": [{"line": line, "why": why} for line, why in h.problems if line not in parsed],
            "conflicts": sorted(h.conflicts),
            "declared": [dict(p.as_dict(), used_by=users.get(p.key, [])) for p in sorted(decls.values(), key=lambda p: p.key)]}


def doctor_lines(text: str) -> List[str]:
    """doctor：「習慣與規則」幾條、看不懂的行、同鍵兩次（不載入工具，所以不查型別）。"""
    h = parse(text)
    if not h.lines and not h.problems:
        return []
    out = [f"• 習慣與規則（soul.md）：{len(h.lines)} 條"]
    for line, why in h.problems[:5]:
        out.append(f"  ⚠️ 看不懂：{line[:80]}——{why}")
    for key in sorted(h.conflicts)[:5]:
        out.append(f"  ⚠️ {key} 寫了 {len(h.conflicts[key])} 次（後面那一行算數）")
    return out
