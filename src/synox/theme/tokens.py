"""
外觀包的 token（pack.json 的 theme.tokens）：檢查值、組成 CSS（docs/themes.md「token」）。

值只能是顏色／長度／字型名單這種「一個值」：沒有 url()、沒有分號大括號、沒有反斜線；函式只收顏色與計算用的那幾個
（rgb、hsl、oklch、color-mix、var(--token)、calc…）。組出來的 CSS 放在網頁的 <style> 裡（有 nonce）。
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from synox.theme import contract

_COLOR_RE = re.compile(r"^[#A-Za-z0-9(),.%\s/+*-]{1,200}$")
_LENGTH_RE = re.compile(r"^(0|\d{1,3}(\.\d{1,3})?(px|rem|em))$")
_FONT_RE = re.compile(r"^[^;{}<>\\@()!:]{1,240}$")
_VAR_ONLY_RE = re.compile(r"^var\(--([a-z0-9-]{1,40})\)$")
COLOR_FUNCS = {"rgb", "rgba", "hsl", "hsla", "hwb", "lab", "lch", "oklab", "oklch", "color-mix", "color", "var",
               "calc", "min", "max", "clamp"}


def token_value_problem(name: str, value) -> str:
    """一個 token 的值合不合（""＝合）。name 是 contract 裡的名字（不帶 --）。"""
    if not isinstance(value, str) or not value.strip():
        return "要是不空的字串"
    value = value.strip()
    low = value.lower()
    if any(bad in low for bad in ("url", "expression", "image", "javascript", "!important", "attr(")):
        return f"不能有網址、圖片或程式：{value[:40]!r}"
    kind = contract.TOKEN_KIND.get(name, "color")
    if kind == "length":
        return "" if _LENGTH_RE.match(value) or _VAR_ONLY_RE.match(value) else f"要是長度（例如 10px、0.6rem）：{value[:40]!r}"
    if kind == "font":
        if _VAR_ONLY_RE.match(value):
            return _var_problem(value)
        return "" if _FONT_RE.match(value) else f"要是字型名單（例如 \"Fraunces\", serif；不能有括號、分號）：{value[:40]!r}"
    if not _COLOR_RE.match(value):
        return f"不像顏色：{value[:40]!r}"
    for fn in re.findall(r"([A-Za-z-]+)\s*\(", value):
        if fn.lower() not in COLOR_FUNCS:
            return f"不收 {fn}()（只收 rgb、hsl、oklch、color-mix、var… 這種顏色函式）"
    return _var_problem(value)


def _var_problem(value: str) -> str:
    for ref in re.findall(r"var\(\s*--([A-Za-z0-9_-]+)", value):
        if not (contract.token_name(ref) or ref.startswith("th-")):
            return f"var(--{ref}) 不是 SYNOX 的 token"
    return ""


def parse_tokens(raw, where: str = "theme.tokens") -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """pack.json 的 theme.tokens → ({"light": {名字: 值}, "dark": {…}}, 問題)。
    light、dark 都要有，而且核心 12 色（contract.CORE_COLORS）都要給齊：換色才會整個畫面一起換。"""
    problems: List[str] = []
    out: Dict[str, Dict[str, str]] = {"light": {}, "dark": {}}
    if not isinstance(raw, dict):
        return out, [f'{where} 要是 {{"light": {{…}}, "dark": {{…}}}}']
    extra = [k for k in raw if k not in ("light", "dark")]
    if extra:
        problems.append(f"{where} 只能有 light、dark（多了 {'、'.join(map(str, extra))}）")
    for mode in ("light", "dark"):
        block = raw.get(mode)
        if not isinstance(block, dict):
            problems.append(f"{where}.{mode} 要是 {{token: 值}}（淺色、深色都要給）")
            continue
        for key, value in block.items():
            name = contract.token_name(key)
            if not name:
                problems.append(f"{where}.{mode} 不認得 {key!r}（看 docs/themes.md 的 token 清單）")
                continue
            why = token_value_problem(name, value)
            if why:
                problems.append(f"{where}.{mode}.{name} {why}")
                continue
            out[mode][name] = " ".join(str(value).split())
        missing = [t for t in contract.CORE_COLORS if t not in out[mode]]
        if missing and isinstance(block, dict):
            problems.append(f"{where}.{mode} 少了 {'、'.join(missing)}（核心 12 色都要給，畫面才會整個一起換）")
    return out, problems


def _decls(values: Dict[str, str]) -> str:
    return " ".join(f"--{k}: {v};" for k, v in values.items())


def token_css(tokens: Dict[str, Dict[str, str]]) -> str:
    """{"light", "dark"} → 蓋過 app.html 預設 token 的 CSS（淺色、跟隨系統的深色、強制深色三段，跟 app.html 同樣的選擇器）。
    外觀包沒寫的進階 token 用 contract.DERIVED 從核心 token 算；字型、圓角沒寫就沿用 SYNOX 的。"""
    def block(mode: str) -> Dict[str, str]:
        values = dict(tokens.get(mode) or {})
        for name, formula in contract.DERIVED.items():
            values.setdefault(name, formula)
        if mode == "dark":                       # 深色沒寫字型／圓角：跟淺色同一個
            for name in contract.SHAPE_TOKENS + contract.FONT_TOKENS:
                if name in (tokens.get("light") or {}):
                    values.setdefault(name, tokens["light"][name])
        return values
    light, dark = block("light"), block("dark")
    return (f":root {{ {_decls(light)} color-scheme: light; }}\n"
            f"@media (prefers-color-scheme: dark) {{ :root:not([data-theme=\"light\"]) {{ {_decls(dark)} "
            f"color-scheme: dark; }} }}\n"
            f":root[data-theme=\"dark\"] {{ {_decls(dark)} color-scheme: dark; }}")
