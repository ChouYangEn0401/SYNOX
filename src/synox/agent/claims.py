"""
虛假完成檢測（docs/adr/0008）：AI 的回覆說「已記下／已新增／done」，但**這一輪**沒有對應的成功工具呼叫 → 不放行。

    v = verdict(said, ledger)      ledger＝這一輪每次工具呼叫的 Evidence（loop._turn 記）
    v.kind：PASS（照送）｜REJECT（forged 或 claim_without_call）｜NUDGE（progress_only：只預告、沒做）

- 純函式、無 I/O；詞表是這裡的常數，**不放進 pack.json、不讓 pack 放寬**。詞表只能加嚴（少抓），
  不能放寬到會抓「我知道了」「好的」。
- 只在迴圈「這一步沒有任何工具呼叫」的分支用（loop._turn），只看 write／danger 類宣稱；
  這一輪有任何 ok 的 write／danger 證據就放行（不細到工具名，避免誤判；entity 只寫 log）。
- 排除（控誤判）：同一個子句裡宣稱前面有否定、條件、未來式、過去／現況描述（之前、目前…）；宣稱所在的句子以問號結尾；
  宣稱後面接「的」（「已設定的提醒」是在描述現況）。
- 誰開：`guard_on(llm, adapter)`：config `llm.completion_guard` = "auto"（預設）｜"on"｜"off"。auto＝本地／較弱的來源才開：
  kind=local，或 kind=openai_compat 指到 loopback／私網；claude_code 與雲端來源預設不開（判斷共用 agent/auto.py）。
  `llm.verify_retries`（預設 2，0＝關）。
- 標定（誤判率）：tests/test_claims_calibration.py，用真實的本地模型回覆與 evals 劇本；數字寫在 ADR 0008。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from synox.agent import auto as auto_mod
from synox.agent import delimit

PASS, REJECT, NUDGE = "pass", "reject", "nudge"
FORGED, CLAIM_WITHOUT_CALL, PROGRESS_ONLY = "forged", "claim_without_call", "progress_only"
WRITE, DANGER = "write", "danger"
GUARD_MODES = auto_mod.MODES
DEFAULT_RETRIES = 2
MAX_RETRIES = 5
LOCAL_KINDS = auto_mod.LOCAL_KINDS

# ── 偽造的工具結果／洩漏的呼叫標記 ─────────────────────────────────────────

RESULT_PREFIX = "〔工具結果〕"                     # textproto.result_message 的開頭（只有系統會產生）
FORGED_MARKERS = (RESULT_PREFIX, "<tool_response>", "</tool_response>", "<tool_call>", "<function=", "<invoke ",
                  "<minimax:tool_call>")
_ROLE_TOOL = re.compile(r"""["']role["']\s*:\s*["']tool["']""")


def forged(text: str) -> str:
    """回覆裡有只有系統（或解析器）才會產生的標記＝模型在偽造工具結果或把呼叫印成文字；回原因（給 log），沒有＝""。"""
    text = text or ""
    if delimit.looks_forged(text):
        return "delimiter"
    for marker in FORGED_MARKERS:
        if marker in text:
            return f"marker {marker.strip()}"
    if _ROLE_TOOL.search(text):
        return 'marker "role": "tool"'
    return ""


# ── 完成宣稱 ─────────────────────────────────────────────────────────

def _cls(chars: str) -> str:
    return "[" + chars + "]"


# 繁中為主，附常見的簡體寫法（本地模型偶爾吐簡體）
_JI, _SHE, _SHAN, _FA, _CHUAN = _cls("記记"), _cls("設设"), _cls("刪删"), _cls("發发"), _cls("傳传")
_LU, _YU, _YUE, _CHU, _DENG = _cls("錄录"), _cls("預预"), _cls("約约"), _cls("儲储"), _cls("登")
_WRITE_VERBS = [
    f"{_JI}下", f"{_JI}{_LU}", f"紀{_LU}", f"{_JI}好", f"{_JI}住", "新增", "加入", "加上", "添加", "建立", f"{_SHE}定",
    f"{_SHE}好", f"{_SHE}置", "排好", "排定", "排程", "安排", f"{_YU}{_YUE}", f"{_YU}訂", "訂好", "更新", "修改", "更改",
    "變更", "变更", "寄出", "寄送", "送出", f"{_FA}送", f"{_FA}出", f"{_CHUAN}送", f"{_CHU}存", "存好", "存下", "保存",
    f"{_DENG}{_JI}", "提交", "完成",
]                                                   # 單獨的「記」不收：「已幫你把筆記…」的「筆記」會誤中
_DANGER_VERBS = [f"{_SHAN}除", f"{_SHAN}掉", "移除", "取消", "清空", "清除", "清掉"]
_VERB = "(?P<verb>" + "|".join(_DANGER_VERBS + _WRITE_VERBS) + ")"
_DANGER_RE = re.compile("|".join(_DANGER_VERBS))
_WHO = r"(?:為|为|幫|帮|替|給|给)?(?:您|你)?"
_BA = r"(?:把[^，,。！？!?\n]{0,20}?)?"

DONE_PATTERNS = [
    # 已(經)記下／已為您新增／已幫你把…記下（後面接「的」＝在描述現況，不算）
    re.compile(r"已(?:經|经)?" + _WHO + _BA + _VERB + r"(?!的)"),
    # 記好了／設好了／排好了／記下來了／刪掉了／寄出了（「改好了」不收：改寫文字的回覆本來就不用工具）
    re.compile(r"(?P<verb>" + f"{_JI}|{_SHE}定|{_SHE}|排|存|加|{_SHAN}|寄|送|新增|建立|{_LU}" + r")(?:好|下來?|下来|完|掉|出|成功)了"),
    # 幫你記了／幫您設好／幫你把…排進去了
    re.compile(r"(?:幫|帮|替)(?:你|您)" + _BA + r"(?P<verb>" + f"{_JI}|{_SHE}|排|加|{_SHAN}|新增|建立|寄|安排|{_YU}{_YUE}"
               + r")(?:了|好|下|進|进|成)"),
    # 都完成／全部完成（「已完成」在第一條）
    re.compile(r"(?:都|全部)(?P<verb>完成)"),
    re.compile(r"(?i)\bI(?:'ve| have)\s+(?:just\s+|already\s+)?(?P<verb>added|saved|set|scheduled|deleted|created|sent|"
               r"removed|updated|booked|noted)\b"),
    re.compile(r"(?i)\b(?:has|have) been (?:successfully\s+)?(?P<verb>added|saved|set|scheduled|deleted|created|sent|"
               r"removed|updated|booked)\b"),
    re.compile(r"(?i)\b(?P<verb>done)\b"),
]
_ENGLISH_DANGER = re.compile(r"(?i)deleted|removed")

# 同一個子句裡、宣稱前面 12 字內有這些＝不算（否定、問、提議、條件、未來式、過去或現況的描述）
EXCLUDE_BEFORE = (
    "沒", "没", "未", "無法", "无法", "不能", "不會", "不会", "不了", "還沒", "尚未", "要不要", "需要我", "是否", "可以幫", "可以帮",
    "我會", "我会", "會幫", "会帮", "會在", "会在", "會再", "会再", "就會", "就会", "將會", "将会", "將於", "将于", "即將", "即将",
    "可以", "準備", "准备", "打算", "稍後", "稍后", "等一下", "如果", "若", "假如", "一旦", "請", "请",
    "之前", "以前", "先前", "稍早", "上次", "目前", "原本", "本來", "本来",
    "not ", "n't", "never", "unable", "will ", "going to", "can ", "could ", "should ", "would ", "if ", "when ",
    "once ", "until ", "after ", "before ",
)
# 宣稱後面緊接著這些＝做完的是「查／讀／改寫」這類不用寫入工具的事（「已完成查詢」「已更新摘要」不算）
READ_OBJECTS = ("查", "搜", "讀", "读", "閱", "阅", "看", "換算", "换算", "計算", "计算", "翻譯", "翻译", "整理", "摘要", "分析",
                "改寫", "改写", "潤", "润", "撰寫", "撰写", "草擬", "草拟")
_HARMLESS = ("沒問題", "没问题", "沒關係", "没关系", "沒錯", "没错")
WINDOW = 12
_SENTENCE_END = "。！？!?\n"
_CLAUSE_CUT = "，,、；;：:（(「『\"“"
QUESTION_END = ("？", "?")


@dataclass
class Claim:
    kind: str                 # write｜danger
    span: tuple               # (start, end)，在原文裡的位置
    entity: str = ""          # 同句裡「」『』或「：」後面的片段（只寫 log）


@dataclass
class Evidence:
    """這一輪的一次工具呼叫（loop._turn 記）。ok＝真的執行成功、或走到確認卡；第 4 關拒絕、失敗信封、不認得的工具＝False。
    args 只在記憶體（評測用來比對參數），不寫 log。"""
    tool: str
    effect: str = "read"
    ok: bool = False
    carded: bool = False
    args: Dict[str, object] = field(default_factory=dict)
    result: str = ""


@dataclass
class Verdict:
    kind: str = PASS
    reason: str = ""
    claims: List[Claim] = field(default_factory=list)
    detail: str = ""


def _sentence_bounds(text: str, start: int, end: int) -> tuple:
    left = max((text.rfind(ch, 0, start) for ch in _SENTENCE_END), default=-1) + 1
    right = len(text)
    for ch in _SENTENCE_END:
        j = text.find(ch, end)
        if j != -1:
            right = min(right, j + 1)
    for j in range(end, len(text)):                 # 英文句點（後面接空白或結尾，不是小數點）
        if text[j] == "." and (j + 1 == len(text) or text[j + 1].isspace()):
            right = min(right, j + 1)
            break
    return left, right


def _excluded(text: str, start: int, end: int) -> bool:
    left, right = _sentence_bounds(text, start, end)
    sentence = text[left:right].rstrip()
    if sentence.endswith(QUESTION_END):
        return True
    clause_start = max([left] + [text.rfind(ch, left, start) + 1 for ch in _CLAUSE_CUT])
    window = text[max(clause_start, start - WINDOW):start]
    for harmless in _HARMLESS:
        window = window.replace(harmless, "")
    low = window.lower()
    return any(word in low for word in EXCLUDE_BEFORE)


def _entity(text: str, end: int) -> str:
    left, right = _sentence_bounds(text, end, end)
    rest = text[end:right]
    m = re.search(r"[「『]([^」』]{1,60})[」』]", rest) or re.search(r"[：:]\s*([^。！？!?\n]{1,60})", rest)
    return m.group(1).strip() if m else ""


def claims(text: str) -> List[Claim]:
    """回覆裡的完成宣稱（write／danger），排除否定、問句、未來式等；同一段文字只算一次。"""
    text = text or ""
    out: List[Claim] = []
    taken: List[tuple] = []
    for pattern in DONE_PATTERNS:
        for m in pattern.finditer(text):
            s, e = m.span()
            if any(s < b and a < e for a, b in taken):
                continue
            if _excluded(text, s, e) or text[e:e + 4].startswith(READ_OBJECTS):
                continue
            verb = m.group("verb") or ""
            danger = bool(_DANGER_RE.search(verb) or _ENGLISH_DANGER.search(verb))
            out.append(Claim(DANGER if danger else WRITE, (s, e), _entity(text, e)))
            taken.append((s, e))
    return sorted(out, key=lambda c: c.span)


_PROGRESS = re.compile(
    r"(?:讓我|让我|我(?:馬上|马上|現在|现在|接著|接着|先|就|來|来|去)?|接下來我?|接下来我?|馬上|马上)"
    r"(?:來|来|去|先|就)?(?:幫你|幫您|替你|替您|帮你|帮您)?"
    r"(?:查|記|记|設定|设定|設|设|排|寄|加|刪|删|改|處理|处理|讀|读|看|找|搜尋|搜索|新增|建立|安排)")
PROGRESS_TAIL = 120
PROGRESS_AFTER = 40


def progress_only(text: str) -> bool:
    """最後 120 字裡在「預告」要做（我來查／馬上幫你記），而且後面不到 40 字、沒有在問 → 只是說要做，沒做（Arize 的 Implicit Finish）。"""
    text = (text or "").strip()
    tail_at = max(0, len(text) - PROGRESS_TAIL)
    for m in _PROGRESS.finditer(text, tail_at):
        after = text[m.end():]
        if len(after) >= PROGRESS_AFTER or any(q in after for q in QUESTION_END):
            continue
        if _excluded(text, m.start(), m.end()) and not text[m.start():m.end()].startswith(("讓我", "让我")):
            continue
        return True
    return False


def write_claims(text: str) -> List[Claim]:
    return [c for c in claims(text) if c.kind in (WRITE, DANGER)]


def verdict(text: str, ledger: Sequence[Evidence]) -> Verdict:
    """規則（照順序）：偽造標記 → REJECT(forged)；有 write／danger 宣稱、這一輪沒有任何 ok 的 write／danger 證據 →
    REJECT(claim_without_call)；沒有宣稱、只是預告、這一輪什麼都沒叫 → NUDGE(progress_only)；其他 PASS。"""
    why = forged(text)
    if why:
        return Verdict(REJECT, FORGED, detail=why)
    found = write_claims(text)
    if found and not any(e.ok and e.effect in (WRITE, DANGER) for e in ledger):
        return Verdict(REJECT, CLAIM_WITHOUT_CALL, found, detail=",".join(c.kind for c in found))
    if not found and not ledger and progress_only(text):
        return Verdict(NUDGE, PROGRESS_ONLY)
    return Verdict(PASS)


# ── 字句（中性、具體；LessWrong 的 Inspect 字句消融：中性的修正字句作弊率約 1%）─────────────────

CORRECTION = {
    CLAIM_WITHOUT_CALL: ("系統檢查：你說已經做了，但這一輪沒有呼叫任何工具，所以沒有任何東西被記錄或執行。"
                         "如果要做，現在就呼叫對應的工具；如果做不到，直接說做不到，不要說已經做了。"),
    FORGED: ("系統檢查：你的回覆裡出現了工具結果的標記，但那不是真的工具結果。只有系統會產生工具結果。"
             "要用工具就呼叫它，然後等結果。"),
    PROGRESS_ONLY: "系統檢查：你說接下來要做，但沒有呼叫工具。要做就現在呼叫；做完了就直接回答使用者。",
}
BLOCKED_PREFIX = "（AI 說做好了，"
BLOCKED_NOTICE = {
    CLAIM_WITHOUT_CALL: "（AI 說做好了，但這一輪沒有真的呼叫對應的工具，所以沒有執行。可以再說一次，或自己打指令。）",
    FORGED: "（AI 說做好了，但它的回覆裡有自己寫的「工具結果」；這一輪沒有真的呼叫工具，所以沒有執行。可以再說一次，或自己打指令。）",
}
ORIGINAL_HEAD = "AI 原本的回覆（沒有執行，僅供參考）："
NUDGE_NOTE = "（AI 說要做，但這一輪沒有呼叫任何工具，所以還沒有執行。可以再說一次，或自己打指令。）"
MEMORY_NOTE = "（AI 宣稱完成但未執行，已攔下）"
ORIGINAL_MAX = 1500


def blocked_message(reason: str, said: str) -> str:
    """重試用完仍不放行時給使用者的字：先照實說「沒有執行」，再附上 AI 原本的回覆（不吞掉）。"""
    notice = BLOCKED_NOTICE.get(reason, BLOCKED_NOTICE[CLAIM_WITHOUT_CALL])
    said = (said or "").strip()
    if not said:
        return notice
    if len(said) > ORIGINAL_MAX:
        said = said[:ORIGINAL_MAX] + "…"
    return f"{notice}\n\n{ORIGINAL_HEAD}\n{said}"


def nudged_message(said: str) -> str:
    said = (said or "").strip()
    return f"{said}\n\n{NUDGE_NOTE}" if said else NUDGE_NOTE


def harness_text(text: str) -> str:
    """評測用：使用者看到的字裡「AI 自己說的」部分。被閘門攔下的訊息（BLOCKED_NOTICE 開頭）＝系統已經照實說了，回 ""。"""
    text = text or ""
    return "" if text.startswith(BLOCKED_PREFIX) else text


# ── 設定 ──────────────────────────────────────────────────────────────

def parse_mode(value) -> str:
    """llm.completion_guard：auto｜on｜off（true／false 也收）。不合丟 ValueError。"""
    if value is None or value == "":
        return "auto"
    if isinstance(value, bool):
        return "on" if value else "off"
    mode = str(value).strip().lower()
    if mode not in GUARD_MODES:
        raise ValueError(f"llm.completion_guard 只能是 auto、on 或 off（現在是 {value!r}）。")
    return mode


def parse_retries(value) -> int:
    if value is None or value == "":
        return DEFAULT_RETRIES
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_RETRIES:
        raise ValueError(f"llm.verify_retries 要是 0～{MAX_RETRIES} 的整數（0＝不檢查）。")
    return value


# auto 的判斷與 auto｜on｜off 的開關是共用的（agent/auto.py）：這裡留舊名字給既有的呼叫端
parse_switch = auto_mod.parse_switch
weak_source = auto_mod.weak_source
_resolve = auto_mod.resolve


def guard_on(llm: Optional[dict], adapter) -> bool:
    llm = llm or {}
    try:
        mode, retries = parse_mode(llm.get("completion_guard")), parse_retries(llm.get("verify_retries"))
    except ValueError:
        return False
    return retries > 0 and _resolve(mode, adapter)


def retries_of(llm: Optional[dict]) -> int:
    try:
        return parse_retries((llm or {}).get("verify_retries"))
    except ValueError:
        return DEFAULT_RETRIES


def summarize_on(llm: Optional[dict], adapter) -> bool:
    try:
        mode = parse_switch((llm or {}).get("summarize_on_limit"), "summarize_on_limit")
    except ValueError:
        return False
    return _resolve(mode, adapter)


def doctor_line(llm: Optional[dict], adapter) -> str:
    """doctor 的一行：完成宣稱檢查開不開（為什麼）、停止詞支不支援。"""
    llm = llm or {}
    mode = str(llm.get("completion_guard") or "auto")
    on = guard_on(llm, adapter)
    why = "本地／私網來源" if weak_source(adapter) else "雲端或 Claude Code"
    head = (f"完成宣稱檢查（llm.completion_guard={mode}）：" + (f"開，重試最多 {retries_of(llm)} 次" if on else "關")
            + (f"（auto：{why}）" if mode == "auto" else ""))
    stop = "停止詞：" + ("有送" if getattr(adapter, "supports_stop", False) else "此來源不支援停止詞（不送）")
    return f"{head}；{stop}"
