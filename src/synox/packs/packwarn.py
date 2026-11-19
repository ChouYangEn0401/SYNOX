"""
pack.json 的標記警告（`warnings`，ADR 0041）：作者自己標「這個工具有什麼要先知道的風險」，SYNOX 在每個看得到工具的地方都顯示。

    "warnings": [{"code": "vendor_no_security_guarantee",
                  "text": "官方不保證安全",
                  "advice": "建議在 docker 或 sandbox 執行"}]

- code：小寫英數字與 _（開頭是字母，48 字內）；固定的代號，程式與確認都用它。
- text：給人看的一句話（MAX_TEXT 字內）；advice：建議怎麼做（選填，MAX_ADVICE 字內）。
  兩個都先清掉換行、控制字元、零寬與雙向文字控制字元，太長截斷加「…」。
- 最多 MAX_WARNINGS 條；同一個 code 只留第一條。
- 選填：沒寫 `warnings` 的舊 pack 行為完全不變（parse 回 ([], [])）。

壞掉的寫法**不讓整個 pack 掛掉，也不靜默吞掉**：
- 每一個問題都回一句給人看的話（problems）：安裝報告列出來、載入時寫 log、doctor 看得到。
- 看不懂的那一條不丟掉，換成一條 MALFORMED 警告（「這個工具的警告格式不對」）——作者想警告卻寫錯，
  比較安全的那一邊是「照樣當作有警告」，一樣要擁有者確認才會啟用。
- 不認得的欄位（例如 severity）：那一條照樣收，problems 記一句。

規則（packs/admin.py、upgrade.py、loader.py 都照這裡）：
- 帶 NO_OFFICIAL_CODES（vendor_no_security_guarantee）的 pack 不能同時是「✅ 官方」簽章：安裝時拒、載入時拒（official_problem）。
- 帶警告的 pack 第一次啟用（安裝、核准、升級多了新的 code）要擁有者明確確認每一個 code
  （終端機 `--accept-warning <code>`、網頁勾選）；確認過的 code 寫進 packs.lock 的 `accepted_warnings`，
  載入時鎖裡沒有確認的 code＝不載入（unaccepted_codes）。
- 簽章（pack.sig.json）涵蓋 pack.json 的每一個位元組：拿掉或改掉 warnings＝簽章驗不過（⛔ 被改過）；
  裝好之後改＝packs.lock 的雜湊對不上（tampered，不載入）。這裡不另外簽。
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
MAX_WARNINGS = 5
MAX_TEXT = 60
MAX_ADVICE = 120
KEYS = ("code", "text", "advice")

VENDOR_NO_GUARANTEE = "vendor_no_security_guarantee"
MALFORMED = "malformed_warning"
# SYNOX 認得的 code：作者沒寫 text／advice（或寫的字不能用）時用這裡的字
KNOWN = {
    VENDOR_NO_GUARANTEE: ("官方不保證安全", "建議在 docker 或 sandbox 執行"),
    MALFORMED: ("這個工具的警告寫壞了，SYNOX 看不懂", "當作有風險的工具：先問作者，或在 docker 或 sandbox 執行"),
}
GENERIC_TEXT = "作者標了一個警告（沒有寫說明）"
# 帶這些 code 的 pack 不能同時是官方簽章（ADR 0041 §3）
NO_OFFICIAL_CODES = (VENDOR_NO_GUARANTEE,)

# 換行、控制字元（C0、DEL、C1）、零寬（U+200B–U+200F）、雙向文字控制（U+202A–U+202E、U+2066–U+2069）、
# word joiner 那一段（U+2060–U+2064）、軟連字號、BOM
_STRIP_RE = re.compile("[\x00-\x1f\x7f-\x9f­​-‏‪-‮⁠-⁤⁦-⁩﻿]")


def clean_text(value, limit: int) -> Tuple[str, bool, bool]:
    """給人看的字 → (清過的字, 有沒有拿掉字元, 有沒有截斷)。不是字串回 ("", False, False)。
    看不見的字元直接拿掉（不換成空白：零寬字元夾在字中間，換成空白會變成兩個字）；連續空白併成一個。"""
    if not isinstance(value, str):
        return "", False, False
    spaced = re.sub(r"[\t\r\n\v\f]", " ", value)            # 換行、tab 換成空白（兩行字不黏在一起）
    stripped = _STRIP_RE.sub("", spaced)
    removed = stripped != value
    text = " ".join(stripped.split())
    cut = len(text) > limit
    if cut:
        text = text[:limit - 1].rstrip() + "…"
    return text, removed, cut


def _risky(text: str) -> List[str]:
    """這段字會進 AI 的提示：像在對 AI 下指令、要跳過確認、夾分隔符的 → 理由（跟 agent.index 同一套）。"""
    if not text:
        return []
    from synox.packs.manifest import SCENARIO_RISKS
    from synox.runtime.ledger import risk_flags
    return [flag for flag in risk_flags(text) if flag in SCENARIO_RISKS]


def malformed() -> dict:
    """看不懂的那一條換成這條（照樣算警告、照樣要確認）。"""
    text, advice = KNOWN[MALFORMED]
    return {"code": MALFORMED, "text": text, "advice": advice}


def _entry(item, where: str, problems: List[str]) -> dict:
    if not isinstance(item, dict):
        problems.append(f"{where} 要是 {{\"code\", \"text\", \"advice\"}} 物件（現在是 {type(item).__name__}）：當作「警告寫壞了」")
        return malformed()
    unknown = sorted(str(k) for k in item if k not in KEYS)
    if unknown:
        problems.append(f"{where} 不認得 {'、'.join(unknown)}（只收 {'、'.join(KEYS)}；那幾個欄位沒有用）")
    code = item.get("code")
    if not isinstance(code, str) or not CODE_RE.match(code):
        problems.append(f"{where}.code 要是小寫英數字與 _（字母開頭，48 字內），現在是 {str(code)[:60]!r}：當作「警告寫壞了」")
        return malformed()
    default_text, default_advice = KNOWN.get(code, (GENERIC_TEXT, ""))
    out = {"code": code}
    for key, limit, fallback in (("text", MAX_TEXT, default_text), ("advice", MAX_ADVICE, default_advice)):
        value = item.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if key == "text":
                problems.append(f"{where}.text 沒寫：用「{fallback}」")
            out[key] = fallback
            continue
        if not isinstance(value, str):
            problems.append(f"{where}.{key} 要是字串：用「{fallback or '（沒有）'}」")
            out[key] = fallback
            continue
        text, removed, cut = clean_text(value, limit)
        if removed:
            problems.append(f"{where}.{key} 有換行、控制字元或看不見的字元（零寬、雙向文字控制）：已經拿掉")
        if cut:
            problems.append(f"{where}.{key} 太長（最多 {limit} 字）：截斷了")
        risky = _risky(text)
        if "✅" in text:                     # 警告的字顯示在標章下面：不准冒充「✅ 官方」那種標章（ADR 0028 §9）
            risky.append("有 ✅（看起來像 SYNOX 的標章）")
        if risky or not text:
            if risky:
                problems.append(f"{where}.{key} 不能{'、'.join(risky)}（這段字會給 AI 看）：用「{fallback or '（沒有）'}」")
            text = fallback
        out[key] = text
    return out


def parse(value, present: bool = True) -> Tuple[List[dict], List[str]]:
    """pack.json 的 warnings → (整理過的清單, 問題清單)。不丟例外。
    present=False（pack.json 沒有這個欄位）→ ([], [])：舊 pack 行為完全不變。"""
    if not present:
        return [], []
    problems: List[str] = []
    if value is None:
        problems.append("warnings 寫了 null：當作「警告寫壞了」（不要警告就整個拿掉這個欄位）")
        return [malformed()], problems
    if not isinstance(value, list):
        problems.append(f"warnings 要是清單（[{{\"code\", \"text\", \"advice\"}}…]），現在是 {type(value).__name__}：當作「警告寫壞了」")
        return [malformed()], problems
    out: List[dict] = []
    seen = set()
    for i, item in enumerate(value):
        entry = _entry(item, f"warnings[{i}]", problems)
        if entry["code"] in seen:
            if entry["code"] != MALFORMED:
                problems.append(f"warnings[{i}] 的 code {entry['code']} 重複了：只留第一條")
            continue
        seen.add(entry["code"])
        out.append(entry)
    if len(out) > MAX_WARNINGS:
        problems.append(f"warnings 最多 {MAX_WARNINGS} 條（現在 {len(out)} 條）：只留 SYNOX 認得的與前面幾條")
        # SYNOX 認得的（例如 vendor_no_security_guarantee）一定留：不讓作者把重要的那條擠到第 6 條以後消失
        known = [w for w in out if w["code"] in KNOWN]
        rest = [w for w in out if w["code"] not in KNOWN]
        keep = {w["code"] for w in (known + rest)[:MAX_WARNINGS]}
        out = [w for w in out if w["code"] in keep]
    return out, problems


# ── 規則 ────────────────────────────────────────────────────────────────

def codes(warnings: Optional[Iterable[dict]]) -> List[str]:
    return [w["code"] for w in warnings or () if isinstance(w, dict) and isinstance(w.get("code"), str)]


def official_problem(m, signature: str) -> str:
    """帶 NO_OFFICIAL_CODES 的 pack 是「✅ 官方」簽章 → 拒絕的一句話；沒事 → ""。"""
    if signature != "official":
        return ""
    bad = [c for c in codes(getattr(m, "warnings", None)) if c in NO_OFFICIAL_CODES]
    if not bad:
        return ""
    return (f"這個工具標了「{'、'.join(bad)}」（官方不保證安全），卻是官方鑰匙簽的：兩個不能同時成立。"
            "不能裝也不載入：請發行者拿掉其中一個（官方的工具不標這個；標這個的工具不用官方鑰匙簽）")


def accepted_of(record: Optional[dict]) -> List[str]:
    """packs.lock 那一筆記的已確認 code（沒寫＝[]）。"""
    value = record.get("accepted_warnings") if isinstance(record, dict) else None
    return [c for c in value if isinstance(c, str) and CODE_RE.match(c)] if isinstance(value, list) else []


def unaccepted_codes(m, accepted: Iterable[str]) -> List[str]:
    """pack 的警告裡，還沒確認過的 code（[]＝都確認過，或沒有警告）。"""
    have = set(accepted or ())
    return [c for c in codes(getattr(m, "warnings", None)) if c not in have]


def normalize_accept(values) -> List[str]:
    """擁有者給的確認（終端機 --accept-warning 可以重複、也可以逗號分隔；網頁給清單）→ code 清單（不認得格式的丟掉）。"""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out: List[str] = []
    for v in values:
        for part in str(v or "").split(","):
            part = part.strip()
            if CODE_RE.match(part) and part not in out:
                out.append(part)
    return out


def accept_problem(m, accepted: Iterable[str], how: str = "cli") -> str:
    """啟用前的確認：還有沒確認的 code → 一句話（說明原因與怎麼確認）；都確認過 → ""。"""
    missing = unaccepted_codes(m, accepted)
    if not missing:
        return ""
    items = {w["code"]: w for w in getattr(m, "warnings", None) or []}
    listing = "；".join(f"{c}：{line(items[c])}" for c in missing if c in items)
    flags = " ".join(f"--accept-warning {c}" for c in missing)
    hint = (f"在網頁的報告上逐條勾選「我知道」（終端機：{flags}）" if how == "web" else
            f"終端機加 {flags}（網頁：在報告上逐條勾選「我知道」）")
    return f"這個工具標了警告，要你明確確認才會啟用（{listing}）。看過、決定要用就{hint}；不確定就不要裝"


def merge_accepted(previous: Optional[dict], m, accepted: Iterable[str]) -> List[str]:
    """寫進鎖的 accepted_warnings：這一次確認的＋舊鎖確認過、新版還有的（只留這個 pack 現在有的 code）。"""
    now = set(codes(getattr(m, "warnings", None)))
    keep = [c for c in accepted_of(previous) if c in now]
    keep += [c for c in accepted or () if c in now and c not in keep]
    return keep


# ── 顯示 ────────────────────────────────────────────────────────────────

def line(w: dict) -> str:
    """一條警告給人看的一行：「官方不保證安全——建議在 docker 或 sandbox 執行」。"""
    text = str(w.get("text") or GENERIC_TEXT)
    advice = str(w.get("advice") or "")
    return f"{text}——{advice}" if advice else text


def lines(warnings: Optional[Sequence[dict]]) -> List[str]:
    return [line(w) for w in warnings or ()]


def badge(warnings: Optional[Sequence[dict]]) -> str:
    """清單、標題旁邊的短標記：「⚠️ 官方不保證安全」；兩條以上「⚠️ 官方不保證安全（另 1 個警告）」；沒有＝""。"""
    items = list(warnings or ())
    if not items:
        return ""
    more = f"（另 {len(items) - 1} 個警告）" if len(items) > 1 else ""
    return f"⚠️ {items[0].get('text') or GENERIC_TEXT}{more}"


def for_agent(warnings: Optional[Sequence[dict]]) -> List[dict]:
    """給 AI／結構化輸出的形狀：[{"code", "text", "advice"}]（清過的字，原樣）。"""
    return [{"code": w.get("code", ""), "text": w.get("text", ""), "advice": w.get("advice", "")}
            for w in warnings or ()]


def agent_note(warnings: Optional[Sequence[dict]], long: bool = True) -> str:
    """給 AI 的提示裡附在工具旁邊的那一段：「〔⚠️警告 vendor_no_security_guarantee：官方不保證安全；建議…〕」；沒有＝""。
    long=False：只有 code 與 text（能力清單縮短時用；警告本身永遠不縮掉）。"""
    items = list(warnings or ())
    if not items:
        return ""
    parts = []
    for w in items:
        part = f"{w.get('code')}：{w.get('text') or GENERIC_TEXT}"
        if long and w.get("advice"):
            part += f"；{w['advice']}"
        parts.append(part)
    return "〔⚠️警告 " + "｜".join(parts) + "〕"


AGENT_RULE = ("能力清單、技能或工具說明裡標〔⚠️警告 …〕的工具：作者標了風險（例如官方不保證安全）。"
              "要用它之前先把警告原文告訴使用者，不要省略、不要說它是官方或安全的。"
              "旁邊的〔實況：…〕是 SYNOX 查這台的結果，照它說；它沒寫在容器或沙盒裡跑，就不要說它被關起來了。")
