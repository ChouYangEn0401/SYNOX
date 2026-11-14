"""
外觀包（pack.json 的 kind=theme）：第 1 關（宣告）、第 2 關（每個檔都消毒一次）、載入時組成要送進網頁的東西。

    {"name": "costume-b-lantern", "kind": "theme", "version": "1.0.0", "title": "提燈", "summary": "…",
     "theme": {"contract": 1,
               "tokens": {"light": {"bg": "#f5f3ef", …}, "dark": {…}},
               "slots": {"mascot.idle": "slots/idle.svg", "opening": "slots/opening.svg", …},
               "css": "theme.css",
               "fonts": ["fonts/Fraunces.woff2", {"family": "Noto Serif TC", "file": "fonts/x.woff2", "weight": "700"}]}}

外觀包**沒有程式**：資料夾裡只能有 pack.json、.svg、.html（slot 用的小片段）、.css、.woff2、說明文字（.md、.txt、LICENSE）。
不能寫 python／cli／mcp／runtime／env／capabilities／web／auth 這些欄位。字型一定要附在包裡（.woff2），
網頁不會去 Google Fonts 之類的地方抓（隱私）。信任層級固定 T0（只有宣告），但一樣要看報告、按確認才裝。
"""

from __future__ import annotations

import base64
import os
import re
from typing import Dict, List, Optional, Tuple

from synox.theme import contract, sanitize, tokens as theme_tokens

MAX_SLOT_FILE = sanitize.MAX_MARKUP
MAX_CSS_FILE = sanitize.MAX_CSS
MAX_FONT = 400 * 1024
MAX_FONTS = 4
MAX_FONTS_TOTAL = 1024 * 1024
MAX_THEME_FILES = 40
TEXT_EXT = (".md", ".txt")
ALLOWED_EXT = (".svg", ".html", ".css", ".woff2") + TEXT_EXT
TEXT_NAMES = ("LICENSE", "NOTICE", "COPYING", "AUTHORS")
# 外觀包不能有的 pack.json 欄位（有＝第 1 關就拒：外觀不能帶程式、不能要權限）
CODE_KEYS = ("python", "cli", "commands", "mcp", "runtime", "env", "capabilities", "web", "auth", "health",
             "storage", "group", "surfaces", "data", "skill")
_FAMILY_RE = re.compile(r"^[A-Za-z0-9 _-]{1,40}$")
_WEIGHT_RE = re.compile(r"^(normal|bold|\d{3}( \d{3})?)$")
WOFF2_MAGIC = b"wOF2"


def _rel_problem(rel, folder: str, where: str, exts: Tuple[str, ...], limit: int) -> str:
    """pack 裡的相對路徑：不能是絕對路徑、不能有 ..、副檔名要對、檔要在、不能太大。"""
    if not isinstance(rel, str) or not rel.strip():
        return f"{where} 要是 pack 裡的檔名"
    norm = rel.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in norm.split("/"):
        return f"{where} 要是 pack 資料夾裡的相對路徑（不能有 ..）：{rel!r}"
    if not norm.lower().endswith(exts):
        return f"{where} 要是 {'／'.join(exts)} 檔：{rel!r}"
    path = os.path.join(folder, *norm.split("/"))
    real, base = os.path.realpath(path), os.path.realpath(folder)
    if not (real == base or real.startswith(base + os.sep)):
        return f"{where} 跑到 pack 資料夾外面了：{rel!r}"
    if not os.path.isfile(path):
        return f"{where} 找不到檔案 {rel}"
    if os.path.getsize(path) > limit:
        return f"{where} 的 {rel} 太大（最多 {limit // 1024} KB）"
    return ""


def parse_fonts(raw, folder: str) -> Tuple[List[dict], List[str]]:
    problems: List[str] = []
    out: List[dict] = []
    if raw is None:
        return out, problems
    if not isinstance(raw, list) or len(raw) > MAX_FONTS:
        return out, [f"theme.fonts 要是清單（最多 {MAX_FONTS} 個 .woff2）"]
    total = 0
    for i, item in enumerate(raw):
        where = f"theme.fonts[{i}]"
        if isinstance(item, str):
            item = {"file": item}
        if not isinstance(item, dict):
            problems.append(f"{where} 要是檔名或 {{\"family\", \"file\", \"weight\", \"style\"}}")
            continue
        rel = item.get("file")
        why = _rel_problem(rel, folder, where, (".woff2",), MAX_FONT)
        if why:
            problems.append(why)
            continue
        rel = rel.replace("\\", "/")
        family = item.get("family") or os.path.splitext(os.path.basename(rel))[0]
        weight = str(item.get("weight") or "normal")
        style = item.get("style") or "normal"
        if not isinstance(family, str) or not _FAMILY_RE.match(family):
            problems.append(f"{where}.family 只能用英數字、空白、-、_（40 字內）：{family!r}")
            continue
        if not _WEIGHT_RE.match(weight) or style not in ("normal", "italic"):
            problems.append(f"{where} 的 weight（400、700、\"100 900\"）或 style（normal｜italic）不對")
            continue
        total += os.path.getsize(os.path.join(folder, *rel.split("/")))
        out.append({"family": family, "file": rel, "weight": weight, "style": style})
    if total > MAX_FONTS_TOTAL:
        problems.append(f"theme.fonts 加起來太大（最多 {MAX_FONTS_TOTAL // 1024} KB）")
    return out, problems


def check_manifest(raw: dict, folder: str) -> Tuple[dict, List[str]]:
    """第 1 關：pack.json 的 theme 那一段（＋不能有的欄位）→ (整理過的 theme, 問題)。不讀 slot 檔的內容（第 2 關讀）。"""
    problems = [f"kind=theme 不能有 {k}（外觀包沒有程式、不要權限）" for k in CODE_KEYS if k in raw]
    requires = raw.get("requires")
    if isinstance(requires, dict) and any(k != "synox" for k in requires):
        problems.append("kind=theme 的 requires 只能寫 synox（最低版本）")
    theme = raw.get("theme")
    if not isinstance(theme, dict):
        return {}, problems + ['kind=theme 要有 "theme": {"tokens": …, "slots": …}']
    known = ("contract", "tokens", "slots", "css", "fonts")
    extra = [k for k in theme if k not in known]
    if extra:
        problems.append(f"theme 不認得 {'、'.join(map(str, extra))}（只收 {'、'.join(known)}）")
    version = theme.get("contract", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        problems.append("theme.contract 要是整數（照哪一版的外觀合約做的，現在是 1）")
        version = 1
    elif version > contract.CONTRACT_VERSION:
        problems.append(f"這個外觀包照第 {version} 版的外觀合約做的，這版 SYNOX 只認得到第 {contract.CONTRACT_VERSION} 版："
                        "請先更新 SYNOX")
    toks, why = theme_tokens.parse_tokens(theme.get("tokens"))
    problems += why
    slots: Dict[str, str] = {}
    raw_slots = theme.get("slots") or {}
    if not isinstance(raw_slots, dict):
        problems.append('theme.slots 要是 {"slot 名字": "檔名"}')
        raw_slots = {}
    for key, rel in raw_slots.items():
        name = contract.slot_name(key)
        if not name:
            problems.append(f"theme.slots 不認得 {key!r}（看 docs/themes.md 的 slot 清單：{'、'.join(contract.SLOTS)}）")
            continue
        exts = tuple("." + k for k in contract.SLOTS[name][2])
        err = _rel_problem(rel, folder, f"theme.slots.{name}", exts, MAX_SLOT_FILE)
        if err:
            problems.append(err)
            continue
        slots[name] = rel.replace("\\", "/")
    css = theme.get("css")
    if css is not None:
        err = _rel_problem(css, folder, "theme.css", (".css",), MAX_CSS_FILE)
        if err:
            problems.append(err)
            css = None
        else:
            css = css.replace("\\", "/")
    fonts, why = parse_fonts(theme.get("fonts"), folder)
    problems += why
    return {"contract": version, "tokens": toks, "slots": slots, "css": css or "", "fonts": fonts}, problems


def _files(folder: str) -> List[str]:
    out = []
    for base, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for n in sorted(names):
            out.append(os.path.relpath(os.path.join(base, n), folder).replace(os.sep, "/"))
    return out


def _read(folder: str, rel: str) -> str:
    with open(os.path.join(folder, *rel.split("/")), "r", encoding="utf-8-sig") as f:
        return f.read()


def scan_problems(folder: str, theme: dict) -> List[Tuple[str, str]]:
    """第 2 關：資料夾裡每個檔。回 [(檔名, 理由)]；空＝過了。
    只能有 ALLOWED_EXT 的檔；每個 .svg／.html 都消毒一次（不管有沒有被 slots 用到）；theme.css 消毒；字型要真的是 woff2。"""
    out: List[Tuple[str, str]] = []
    files = _files(folder)
    if len(files) > MAX_THEME_FILES:
        out.append(("pack.json", f"外觀包的檔案太多（{len(files)} 個，最多 {MAX_THEME_FILES}）"))
    used = {rel: name for name, rel in (theme.get("slots") or {}).items()}
    fonts = {f["file"] for f in theme.get("fonts") or []}
    for rel in files:
        low = rel.lower()
        base = rel.rsplit("/", 1)[-1]
        if rel == "pack.json":
            continue
        if not (low.endswith(ALLOWED_EXT) or base.upper().split(".")[0] in TEXT_NAMES and "." not in base):
            out.append((rel, "外觀包只能有 pack.json、.svg、.html、.css、.woff2 與說明文字（.md、.txt、LICENSE）"))
            continue
        try:
            if low.endswith((".svg", ".html")):
                slot = used.get(rel, "mascot.idle")
                kinds = contract.SLOTS[slot][2] if low.endswith(".html") else ("svg",)
                if low.endswith(".html") and "html" not in kinds:
                    out.append((rel, f"「{slot}」只收 SVG"))
                    continue
                sanitize.sanitize_markup(_read(folder, rel), slot, kinds=kinds, where=rel)
            elif low.endswith(".css"):
                if rel != theme.get("css"):
                    out.append((rel, "pack.json 的 theme.css 沒有用到這個 .css（一個外觀包只有一份 CSS）"))
                    continue
                sanitize.sanitize_css(_read(folder, rel), where=rel)
            elif low.endswith(".woff2"):
                if rel not in fonts:
                    out.append((rel, "pack.json 的 theme.fonts 沒有用到這個字型"))
                    continue
                with open(os.path.join(folder, *rel.split("/")), "rb") as f:
                    if f.read(4) != WOFF2_MAGIC:
                        out.append((rel, "不是 woff2 字型（檔頭不對）"))
            elif low.endswith(TEXT_EXT):
                _read(folder, rel)
        except sanitize.Rejected as e:
            out += [(rel, r) for r in e.reasons]
        except (OSError, UnicodeDecodeError) as e:
            out.append((rel, f"讀不了（{type(e).__name__}）"))
    return out


# ── 載入時：組成要送進網頁的東西 ──────────────────────────────────────────

def font_url(pack: str, rel: str) -> str:
    return f"/theme/font/{pack}/{rel}"


def font_css(pack: str, fonts: List[dict]) -> str:
    return "\n".join(f'@font-face {{ font-family: "{f["family"]}"; src: url("{font_url(pack, f["file"])}") '
                     f'format("woff2"); font-weight: {f["weight"]}; font-style: {f["style"]}; font-display: swap; }}'
                     for f in fonts)


def appicon_uri(markup: str) -> str:
    """消毒過的 SVG → favicon 用的 data: 網址（圖片裡的 SVG 本來就不會跑程式）。"""
    svg = markup if 'xmlns="' in markup[:200] else markup.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


class Bundle:
    """一個外觀（包或「原本的 SYNOX」）組好要送進網頁的東西。"""

    def __init__(self, css: str = "", slots: Optional[Dict[str, str]] = None, slot_css: str = "",
                 fonts_css: str = "", notes: Optional[List[str]] = None):
        self.css = css                      # token＋theme.css
        self.slots = dict(slots or {})      # slot → 消毒過的 markup
        self.slot_css = slot_css            # slot 裡 <style> 拿出來的（已經套好範圍）
        self.fonts_css = fonts_css
        self.notes = list(notes or [])

    def stylesheet(self) -> str:
        return "\n".join(p for p in (self.fonts_css, self.css, self.slot_css) if p)


def compile_theme(folder: str, name: str, theme: dict) -> Bundle:
    """裝好的外觀包 → Bundle。每次都重新消毒（防禦深度：檔案被改過、消毒規則更新了都照新的）；不合丟 Rejected。"""
    parts = [theme_tokens.token_css(theme.get("tokens") or {})]
    if theme.get("css"):
        parts.append(sanitize.sanitize_css(_read(folder, theme["css"]), where=theme["css"]))
    slots, slot_css, notes = {}, [], []
    for slot, rel in (theme.get("slots") or {}).items():
        kinds = contract.SLOTS[slot][2] if rel.lower().endswith(".html") else ("svg",)
        clean = sanitize.sanitize_markup(_read(folder, rel), slot, kinds=kinds, where=rel)
        slots[slot] = clean.markup
        if clean.css:
            slot_css.append(clean.css)
        notes += clean.notes
    return Bundle("\n".join(parts), slots, "\n".join(slot_css), font_css(name, theme.get("fonts") or []), notes)


def report(m, theme: dict) -> dict:
    """安裝報告的「🎨 外觀」那一段：顏色（給畫面畫色票）、有換哪些位置、字型。只在第 1、2 關都過了才有。"""
    out = {"tokens": theme.get("tokens") or {}, "slots": sorted(theme.get("slots") or {}),
           "fonts": [f["family"] for f in theme.get("fonts") or []], "css": bool(theme.get("css")),
           "contract": theme.get("contract", 1)}
    try:
        out["markup"] = compile_theme(m.folder, m.name, theme).slots
    except (sanitize.Rejected, OSError, UnicodeDecodeError):
        out["markup"] = {}
    return out
