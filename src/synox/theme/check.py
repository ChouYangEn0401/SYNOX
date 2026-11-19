"""
套用外觀時的逐項清單（ADR 0042）：每一個顏色 token、每一個 slot 是「外觀包有給」還是「沒給 → 沿用」。

這份清單是**提示，不擋套用**：沒給的一律有值（SYNOX 的預設，或用外觀包自己的顏色算），不會缺色。
用在：安裝報告（終端機、網頁）、設定 → 外觀的「套用」、`synox packs theme-check`。給 AI 看的用 to_dict 的結構。

    c = coverage(m.theme)
    c["tokens"]["light"] → [{"token": "bg", "group": "core", "status": "provided", "value": "#f5f3ef", "issue": False}, …]
    c["slots"]           → [{"slot": "mascot.idle", "status": "provided", "issue": False}, …]
    c["issues"]          → 要注意的那幾項（忽略的、沒給又只能用 SYNOX 預設顏色的）

status：
    provided  外觀包有給（深色沒給圓角、字型時用它淺色的那一個：from＝light）
    derived   外觀包沒給 → 用外觀包自己的核心色算（contract.DERIVED），顏色會跟著這套外觀
    default   外觀包沒給 → 沿用 SYNOX 原本的（contract.DEFAULTS）；顏色 token 這樣的話會標「要注意」
    ignored   外觀包給了，但這版 SYNOX 不認得 → 不用（外觀包可能比 SYNOX 新）
"""

from __future__ import annotations

from typing import Dict, List

from synox.theme import contract

STATUS_TEXT: Dict[str, str] = {
    "provided": "外觀包有給",
    "derived": "沒給 → 用外觀包自己的顏色算",
    "default": "沒給 → 沿用 SYNOX 預設",
    "ignored": "給了但這版 SYNOX 不認得 → 忽略",
}
SLOT_TEXT: Dict[str, str] = {
    "provided": "外觀包有換",
    "default": "沒換 → 沿用 SYNOX 原本的",
    "ignored": "給了但這版 SYNOX 沒有這個位置 → 忽略",
}
MODE_TEXT = {"light": "淺色", "dark": "深色"}


def _group(name: str) -> str:
    if name in contract.CORE_COLORS:
        return "core"
    if name in contract.SHAPE_TOKENS + contract.FONT_TOKENS:
        return "shape-font"
    if name in contract.MASCOT_TOKENS:
        return "mascot"
    return "advanced"


def _is_issue(name: str, status: str) -> bool:
    """要注意＝忽略了的；或顏色 token 沒給、也算不出來，只能用 SYNOX 的顏色（可能跟這套外觀不搭）。"""
    if status == "ignored":
        return True
    return (status == "default" and contract.TOKEN_KIND.get(name, "color") == "color"
            and name not in contract.NEUTRAL_TOKENS)


def coverage(theme: dict) -> dict:
    """外觀包的 theme（manifest 整理過的：tokens、slots、notes）→ 逐項清單。"""
    tokens = theme.get("tokens") or {}
    notes = list(theme.get("notes") or [])
    deferred = {(n.get("mode"), n.get("token")): n.get("why", "") for n in notes if n.get("code") == "unknown-ref"}
    out_tokens: Dict[str, List[dict]] = {}
    counts: Dict[str, Dict[str, int]] = {}
    issues: List[dict] = []
    for mode in ("light", "dark"):
        given = tokens.get(mode) or {}
        light = tokens.get("light") or {}
        defaults = contract.default_tokens(mode)
        rows: List[dict] = []
        for name in contract.ALL_TOKENS:
            row = {"token": name, "group": _group(name)}
            if name in given:
                row.update(status="provided", value=given[name])
            elif mode == "dark" and name in contract.SHAPE_TOKENS + contract.FONT_TOKENS and name in light:
                row.update(status="provided", value=light[name], **{"from": "light"})
            elif name in contract.DERIVED and (mode, name) not in deferred:
                row.update(status="derived", value=contract.DERIVED[name])
            else:
                row.update(status="default", value=defaults.get(name, ""))
                if (mode, name) in deferred:
                    row["why"] = deferred[(mode, name)]
            row["issue"] = _is_issue(name, row["status"])
            rows.append(row)
        for n in notes:
            if n.get("code") == "unknown-token" and n.get("mode") == mode:
                rows.append({"token": n.get("token", ""), "group": "unknown", "status": "ignored", "value": "",
                             "why": n.get("why", ""), "issue": True})
        for row in rows:
            if row["issue"]:
                issues.append({"kind": "token", "mode": mode, "name": row["token"], "status": row["status"],
                               "why": row.get("why") or STATUS_TEXT[row["status"]]})
        out_tokens[mode] = rows
        counts[mode] = {s: sum(1 for r in rows if r["status"] == s) for s in STATUS_TEXT}
    given_slots = theme.get("slots") or {}
    slots: List[dict] = [{"slot": name, "status": "provided" if name in given_slots else "default", "issue": False}
                         for name in contract.SLOTS]
    for n in notes:
        if n.get("code") == "unknown-slot":
            slots.append({"slot": n.get("slot", ""), "status": "ignored", "why": n.get("why", ""), "issue": True})
            issues.append({"kind": "slot", "mode": "", "name": n.get("slot", ""), "status": "ignored",
                           "why": n.get("why", "")})
    counts["slots"] = {s: sum(1 for r in slots if r["status"] == s) for s in SLOT_TEXT}
    return {"blocking": False, "contract": theme.get("contract", 1), "synox_contract": contract.CONTRACT_VERSION,
            "tokens": out_tokens, "slots": slots, "counts": counts, "issues": issues}


def _count_line(c: dict) -> str:
    return "、".join(f"{STATUS_TEXT[s]} {n}" for s, n in c.items() if n)


def format_lines(check: dict, details: bool = False, indent: str = "  ") -> List[str]:
    """終端機用：預設只有摘要＋要注意的；details＝每一項都列（淺色、深色分開，slot 另一段）。"""
    if not check:
        return []
    counts = check.get("counts") or {}
    issues = check.get("issues") or []
    lines = [f"{indent}套用檢查（只是提示，不擋套用；沒給的都有值）："]
    for mode in ("light", "dark"):
        lines.append(f"{indent}  {MODE_TEXT[mode]}：{_count_line(counts.get(mode) or {})}")
    sc = counts.get("slots") or {}
    lines.append(f"{indent}  吉祥物與開場的位置：" + "、".join(f"{SLOT_TEXT[s]} {n}" for s, n in sc.items() if n))
    if issues:
        lines.append(f"{indent}  ⚠️ 要注意 {len(issues)} 項：")
        for it in issues:
            where = f"{MODE_TEXT.get(it['mode'], '')} " if it.get("mode") else ""
            name = f"--{it['name']}" if it["kind"] == "token" else it["name"]
            lines.append(f"{indent}    · {where}{name}：{it['why']}")
    else:
        lines.append(f"{indent}  ✅ 沒有要注意的")
    if not details:
        lines.append(f"{indent}  （要看每一項：加 --details）")
        return lines
    for mode in ("light", "dark"):
        lines.append(f"{indent}  ── {MODE_TEXT[mode]}的每一個 token ──")
        for r in (check.get("tokens") or {}).get(mode) or []:
            mark = "⚠️" if r["issue"] else "  "
            extra = "（跟淺色同一個）" if r.get("from") == "light" else ""
            value = f"  {r['value']}" if r.get("value") else ""
            lines.append(f"{indent}  {mark} --{r['token']}：{STATUS_TEXT[r['status']]}{extra}{value}")
    lines.append(f"{indent}  ── 吉祥物與開場的位置（slot）──")
    for r in check.get("slots") or []:
        mark = "⚠️" if r["issue"] else "  "
        lines.append(f"{indent}  {mark} {r['slot']}：{SLOT_TEXT[r['status']]}")
    return lines
