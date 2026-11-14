"""
外觀的消毒（docs/themes.md「消毒規則」）：外觀包（kind=theme）與「自己貼」的 SVG／HTML／CSS 都過這裡。

原則：**白名單重建**。輸入只拿來解析，送進網頁的字串是從白名單裡的元素、屬性、CSS 規則**重新組出來**的，
不是把輸入刪刪改改再送出去（所以輸入的怪寫法、解析器之間的差異帶不過來）。
- 看到危險的東西（程式、事件屬性、javascript:、外部網址、@import、<foreignObject>…）＝整份拒絕（Rejected，每個原因一句話）。
- 看不懂但無害的（編輯器的 metadata、inkscape:* 屬性、註解）＝丟掉，記在 notes（給人看「哪些東西被拿掉了」）。
- id 一律加前綴（ts-<slot>-…），不會蓋到網頁自己的元素；href／url() 只收同一份裡的 #id。
- CSS：只能是自訂屬性（:root 的 token）或套在 [data-slot]／.theme-slot-* 裡面的規則；@keyframes 要 th- 開頭；
  不收 !important（網頁替每個 slot 釘死的位置、大小規則才蓋不掉）、反斜線跳脫、<、兄弟選擇器（+ ~）、:has()。

網頁本身還有一層：CSP 只放行有 nonce 的 <script>／<style>，就算這裡漏了，貼進去的 <script> 也不會跑。
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from synox.theme import contract

MAX_MARKUP = 64 * 1024            # 一個 slot 的 SVG／HTML
MAX_CSS = 64 * 1024               # 一份 CSS
MAX_NODES = 4000
MAX_DEPTH = 40


class Rejected(ValueError):
    """不收：reasons 是給人看的理由（每個一句話）。"""

    def __init__(self, reasons):
        reasons = [str(r) for r in (reasons if isinstance(reasons, (list, tuple)) else [reasons])] or ["不收"]
        super().__init__("；".join(dict.fromkeys(reasons)))
        self.reasons = list(dict.fromkeys(reasons))


# ── 元素與屬性 ─────────────────────────────────────────────────────────

SVG_ELEMENTS = ("svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "defs",
                "linearGradient", "radialGradient", "stop", "clipPath", "mask", "symbol", "use", "title", "desc",
                "text", "tspan", "animate", "animateTransform", "pattern", "marker", "filter", "feGaussianBlur",
                "feOffset", "feMerge", "feMergeNode", "feFlood", "feComposite", "feBlend", "feColorMatrix",
                "feDropShadow", "feMorphology", "feTurbulence", "feDisplacementMap")
HTML_ELEMENTS = ("div", "span", "p", "b", "strong", "i", "em", "small", "br", "sup", "sub")
VOID = {"br", "img", "meta", "link", "input", "source", "track", "embed", "area", "base", "col", "hr", "param",
        "wbr", "keygen"}
# 看到就整份拒絕：會跑程式、會連到外面、會載入別的東西、或是解析器把戲的元素
REJECT_ELEMENTS = {
    "script": "有 <script>（外觀不能帶程式）",
    "foreignobject": "有 <foreignObject>（SVG 裡塞 HTML 的後門）",
    "iframe": "有 <iframe>", "frame": "有 <frame>", "frameset": "有 <frameset>", "object": "有 <object>",
    "embed": "有 <embed>", "applet": "有 <applet>", "portal": "有 <portal>",
    "img": "有 <img>（圖片會連到外面；請畫成 SVG）", "image": "有 <image>（圖片會連到外面；請畫成向量）",
    "feimage": "有 <feImage>（會載入外部圖片）", "picture": "有 <picture>", "video": "有 <video>",
    "audio": "有 <audio>", "source": "有 <source>", "track": "有 <track>",
    "a": "有 <a> 連結（外觀不能放連結）", "set": "有 <set>（可以把屬性改成程式）",
    "animatemotion": "有 <animateMotion>（請改用 animateTransform）",
    "link": "有 <link>（會載入外部檔案）", "base": "有 <base>", "meta": "有 <meta>（請只貼 <svg>…</svg> 或一小段 HTML）",
    "form": "有 <form>", "input": "有 <input>", "button": "有 <button>", "textarea": "有 <textarea>",
    "select": "有 <select>", "math": "有 <math>", "noscript": "有 <noscript>", "xmp": "有 <xmp>",
    "plaintext": "有 <plaintext>", "noembed": "有 <noembed>", "noframes": "有 <noframes>",
    "template": "有 <template>", "slot": "有 <slot>", "handler": "有 <handler>", "listener": "有 <listener>",
    "canvas": "有 <canvas>", "dialog": "有 <dialog>", "details": "有 <details>",
}
TRANSPARENT = {"html", "body", "head"}             # 貼了整份 HTML：外殼拿掉、留裡面

SVG_ATTRS = (
    "id", "class", "transform", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity",
    "d", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr", "width", "height",
    "viewBox", "preserveAspectRatio", "points", "offset", "stop-color", "stop-opacity", "gradientUnits",
    "gradientTransform", "spreadMethod", "clip-path", "clip-rule", "clipPathUnits", "mask", "maskUnits",
    "maskContentUnits", "patternUnits", "patternContentUnits", "patternTransform", "filter", "filterUnits",
    "primitiveUnits", "in", "in2", "result", "stdDeviation", "dx", "dy", "flood-color", "flood-opacity",
    "operator", "k1", "k2", "k3", "k4", "mode", "values", "type", "radius", "font-family", "font-size",
    "font-weight", "font-style", "text-anchor", "dominant-baseline", "letter-spacing", "word-spacing",
    "textLength", "lengthAdjust", "visibility", "display", "vector-effect", "paint-order", "pathLength",
    "shape-rendering", "color-interpolation-filters", "attributeName", "attributeType", "begin", "dur", "end",
    "repeatCount", "repeatDur", "from", "to", "by", "keyTimes", "keySplines", "calcMode", "additive",
    "accumulate", "restart", "href", "role", "aria-hidden", "aria-label", "focusable", "markerWidth",
    "markerHeight", "refX", "refY", "orient", "markerUnits", "marker-start", "marker-mid", "marker-end",
    "overflow", "color", "mix-blend-mode", "isolation", "style", "transform-origin",
    # <feTurbulence>（雜訊，自己算、不載入東西）與 <feDisplacementMap>（拿雜訊把圖扭一下）
    "baseFrequency", "numOctaves", "seed", "stitchTiles", "scale", "xChannelSelector", "yChannelSelector")
HTML_ATTRS = ("id", "class", "role", "aria-hidden", "aria-label", "title", "lang", "style")
# style 屬性（網頁的 CSP 不收 inline style）：SVG 裡這些換成同名的屬性，其他丟掉
PRESENTATION = {"fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
                "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity",
                "stop-color", "stop-opacity", "clip-path", "clip-rule", "mask", "filter", "flood-color",
                "flood-opacity", "font-family", "font-size", "font-weight", "font-style", "text-anchor",
                "dominant-baseline", "letter-spacing", "word-spacing", "visibility", "display", "vector-effect",
                "paint-order", "shape-rendering", "overflow", "color", "mix-blend-mode", "isolation",
                "transform-origin"}
# <animate attributeName="…">：只能動這些（不能動 href 之類，那是把 SVG 變成連結的老把戲）
ANIMATABLE = {"transform", "opacity", "fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-dashoffset",
              "fill-opacity", "stroke-opacity", "r", "rx", "ry", "cx", "cy", "x", "y", "width", "height", "d",
              "points", "offset", "stop-color", "stop-opacity", "visibility", "display", "x1", "y1", "x2", "y2",
              "font-size", "letter-spacing", "flood-color", "flood-opacity", "stdDeviation", "dx", "dy"}
HREF_ELEMENTS = {"use", "lineargradient", "radialgradient", "pattern", "filter"}

_SVG_CASE = {e.lower(): e for e in SVG_ELEMENTS}
_SVG_ATTR_CASE = {a.lower(): a for a in SVG_ATTRS}
_HTML_ATTRS = set(HTML_ATTRS)
_ID_RE = re.compile(r"^[A-Za-z_][\w.-]{0,60}$")
_CLASS_RE = re.compile(r"^[A-Za-z_][\w-]{0,40}$")
_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
_LOCAL_REF_RE = re.compile(r"^#([A-Za-z_][\w.-]{0,60})$")
_SYNC_RE = re.compile(r"(?<![\w.-])([A-Za-z_][\w-]{0,60})\.(begin|end|click|repeat\(\d+\)|mouseover|mouseout|"
                      r"mousedown|mouseup|focusin|focusout)\b")
_SPACE_CTRL = re.compile(r"[\x00-\x20\x7f ​-‍  ﻿]+")


def _squash(value: str) -> str:
    """拿掉空白與控制字元、轉小寫：java\tscript: 這種拆開的寫法一樣抓得到。"""
    return _SPACE_CTRL.sub("", str(value)).lower()


def prefix_id(key: str, ident: str) -> str:
    return f"ts-{key}-{ident}"


def _rewrite_urls(value: str, key: str, where: str, problems: List[str]) -> str:
    """值裡的 url(…)：只收 url(#id)（換成加了前綴的 id）；其他（外部網址、data:）＝拒絕。"""
    def fix(m):
        target = m.group(2).strip()
        local = _LOCAL_REF_RE.match(target)
        if not local:
            problems.append(f"{where} 有外部網址 url({target[:60]})（外觀只能用同一份裡的 #id）")
            return "none"
        return f"url(#{prefix_id(key, local.group(1)) if key else local.group(1)})"
    out = _URL_RE.sub(fix, value)
    if "url(" in _squash(_URL_RE.sub("", value)):
        problems.append(f"{where} 的 url( 沒寫完整")
    return out


def _value_problem(value: str) -> str:
    s = _squash(value)
    for bad, why in (("javascript:", "javascript:"), ("vbscript:", "vbscript:"), ("expression(", "expression()"),
                     ("@import", "@import"), ("-moz-binding", "-moz-binding")):
        if bad in s:
            return f"有 {why}"
    return ""


class _Builder(HTMLParser):
    """用 HTMLParser 解析（跟瀏覽器解 innerHTML 是同一種 HTML 規則），再從白名單重新組出字串。"""

    def __init__(self, key: str, where: str):
        super().__init__(convert_charrefs=True)
        self.key, self.where = key, where
        self.out: List[str] = []
        self.stack: List[Tuple[str, str, str]] = []      # (小寫名字, 種類 svg|html|drop|transparent|style, 輸出的名字)
        self.css: List[str] = []
        self.problems: List[str] = []
        self.notes: List[str] = []
        self.nodes = 0
        self.roots: List[str] = []                        # 最上層的元素（appicon、.svg 檔要剛好一個 <svg>）
        self.top_text = False

    # 狀態
    def _dropping(self) -> bool:
        return any(k in ("drop", "style") for _t, k, _p in self.stack)

    def _in_svg(self) -> bool:
        return any(k == "svg" for _t, k, _p in self.stack)

    def _level(self) -> int:
        return sum(1 for _t, k, _p in self.stack if k in ("svg", "html"))

    def note(self, text: str) -> None:
        if text not in self.notes and len(self.notes) < 30:
            self.notes.append(text)

    # 屬性
    def _attrs(self, tag: str, attrs, svg: bool) -> str:
        parts: List[str] = []
        seen = set()
        style_extra: List[Tuple[str, str]] = []
        for name, value in attrs:
            name = (name or "").lower()
            value = "" if value is None else str(value)
            if name.startswith("on"):
                self.problems.append(f"{self.where} 的 <{tag}> 有事件屬性 {name}（外觀不能帶程式）")
                continue
            why = _value_problem(value)
            if why:
                self.problems.append(f"{self.where} 的 <{tag} {name}> {why}")
                continue
            if name in ("xlink:href",):
                name = "href"
            if name.startswith(("xmlns", "xml:", "data-")) or name in ("version", "baseprofile"):
                continue                                   # innerHTML 用不到；data-* 不讓外觀碰網頁的資料屬性
            proper = _SVG_ATTR_CASE.get(name) if svg else (name if name in _HTML_ATTRS else None)
            if proper is None:
                self.note(f"拿掉了不認得的屬性 {name}")
                continue
            if name in seen:
                continue
            if name == "style":
                for prop, val in _style_pairs(value):
                    if svg and prop in PRESENTATION:
                        style_extra.append((prop, val))
                    else:
                        self.note(f"拿掉了 style 裡的 {prop}（請寫在 CSS 裡，用 class 對到）")
                continue
            if name == "href":
                if tag.lower() not in HREF_ELEMENTS:
                    self.problems.append(f"{self.where} 的 <{tag}> 有 href（只有 <use>、漸層可以指到同一份裡的 #id）")
                    continue
                local = _LOCAL_REF_RE.match(value.strip())
                if not local:
                    self.problems.append(f"{self.where} 的 <{tag} href> 指到外面：{value.strip()[:60]}（只能是 #id）")
                    continue
                value = "#" + prefix_id(self.key, local.group(1))
            elif name == "id":
                if not _ID_RE.match(value):
                    self.note(f"拿掉了寫法不對的 id {value[:30]!r}")
                    continue
                value = prefix_id(self.key, value)
            elif name == "class":
                classes = [c for c in value.split() if _CLASS_RE.match(c)][:8]
                if not classes:
                    continue
                value = " ".join(classes)
            elif name == "attributename":
                if value.strip() not in ANIMATABLE:
                    self.problems.append(f"{self.where} 的 <{tag}> 想動畫 {value.strip()[:30]!r}（只能動形狀、顏色、位置這類屬性）")
                    continue
            elif name in ("begin", "end"):
                value = _SYNC_RE.sub(lambda m: prefix_id(self.key, m.group(1)) + "." + m.group(2), value)
            if "url(" in _squash(value):
                value = _rewrite_urls(value, self.key, f"{self.where} 的 <{tag} {name}>", self.problems)
            seen.add(name)
            parts.append(f' {proper}="{html.escape(value, quote=True)}"')
        for prop, val in style_extra:
            if prop in seen:
                continue
            why = _value_problem(val)
            if why:
                self.problems.append(f"{self.where} 的 <{tag} style> {why}")
                continue
            if "url(" in _squash(val):
                val = _rewrite_urls(val, self.key, f"{self.where} 的 <{tag} style>", self.problems)
            seen.add(prop)
            parts.append(f' {_SVG_ATTR_CASE.get(prop, prop)}="{html.escape(val, quote=True)}"')
        return "".join(parts)

    # 解析事件
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        void = tag in VOID
        if self._dropping():
            if not void:
                self.stack.append((tag, "drop", ""))
            return
        self.nodes += 1
        if self.nodes > MAX_NODES:
            self.problems.append(f"{self.where} 的元素太多（最多 {MAX_NODES} 個）")
            self.stack.append((tag, "drop", "")) if not void else None
            return
        if self._level() >= MAX_DEPTH:
            self.problems.append(f"{self.where} 疊太多層（最多 {MAX_DEPTH} 層）")
            self.stack.append((tag, "drop", "")) if not void else None
            return
        if tag in REJECT_ELEMENTS:
            self.problems.append(f"{self.where} {REJECT_ELEMENTS[tag]}")
            if not void:
                self.stack.append((tag, "drop", ""))
            return
        if tag == "style":
            self.stack.append((tag, "style", ""))
            return
        if tag in TRANSPARENT:
            self.stack.append((tag, "transparent", ""))
            return
        in_svg = self._in_svg()
        if tag in _SVG_CASE and (tag == "svg" or in_svg):
            proper = _SVG_CASE[tag]
            if not self._level():
                self.roots.append(proper)
            self.out.append(f"<{proper}{self._attrs(proper, attrs, True)}>")
            self.stack.append((tag, "svg", proper))
            return
        if tag in HTML_ELEMENTS and not in_svg:
            if not self._level():
                self.roots.append(tag)
            self.out.append(f"<{tag}{self._attrs(tag, attrs, False)}>")
            if not void:
                self.stack.append((tag, "html", tag))
            return
        where = "SVG 裡" if in_svg else "HTML 裡"
        self.note(f"拿掉了 {where}不認得的 <{tag}>（連同裡面的東西）")
        if not void:
            self.stack.append((tag, "drop", ""))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if not any(t == tag for t, _k, _p in self.stack):
            return                                       # 沒有開過的結束標籤：忽略
        while self.stack:
            t, kind, proper = self.stack.pop()
            if kind in ("svg", "html"):
                self.out.append(f"</{proper}>")
            if t == tag:
                break

    def handle_data(self, data):
        if self.stack and self.stack[-1][1] == "style":
            if not any(k == "drop" for _t, k, _p in self.stack[:-1]):
                self.css.append(data)
            return
        if self._dropping() or not data:
            return
        if not self._level() and data.strip():
            self.top_text = True
        self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass                                             # <!DOCTYPE …>：不展開任何 entity

    def handle_pi(self, data):
        pass                                             # <?xml …?>

    def unknown_decl(self, data):
        pass                                             # <![CDATA[ … ]]>

    def finish(self) -> str:
        self.close()
        while self.stack:
            _t, kind, proper = self.stack.pop()
            if kind in ("svg", "html"):
                self.out.append(f"</{proper}>")
        return "".join(self.out).strip()


def _style_pairs(text: str) -> List[Tuple[str, str]]:
    out = []
    for part in _split_top(text, ";"):
        if ":" not in part:
            continue
        prop, val = part.split(":", 1)
        prop, val = prop.strip().lower(), val.strip()
        if prop and val:
            out.append((prop, val))
    return out


class Clean:
    """消毒過的一個 slot：markup（可以直接放進網頁）、css（已經套好這個 slot 的範圍）、notes（拿掉了什麼）。"""

    def __init__(self, markup: str, css: str, notes: List[str]):
        self.markup, self.css, self.notes = markup, css, notes

    def to_dict(self) -> dict:
        return {"markup": self.markup, "css": self.css, "notes": list(self.notes)}


def sanitize_markup(text, slot: str, *, kinds: Tuple[str, ...] = ("svg", "html"), where: str = "") -> Clean:
    """一個 slot 的 SVG 或 HTML 小片段 → Clean；有危險的東西丟 Rejected。
    kinds=("svg",)：一定要剛好是一張 <svg>（appicon、.svg 檔）。裡面的 <style> 拿出來當這個 slot 的 CSS。"""
    where = where or f"「{slot}」"
    if not isinstance(text, str):
        raise Rejected(f"{where} 要是文字")
    if len(text.encode("utf-8")) > MAX_MARKUP:
        raise Rejected(f"{where} 太大（最多 {MAX_MARKUP // 1024} KB）")
    if "\x00" in text:
        raise Rejected(f"{where} 有 NUL 字元")
    key = contract.slot_key(slot)
    b = _Builder(key, where)
    try:
        b.feed(text)
        markup = b.finish()
    except (ValueError, AssertionError) as e:            # HTMLParser 在極端輸入上可能丟例外：一律當作不收
        raise Rejected(f"{where} 解析不了（{type(e).__name__}）")
    problems = list(b.problems)
    css = ""
    if b.css:
        try:
            css = sanitize_css("\n".join(b.css), slot=slot, where=f"{where} 裡的 <style>")
        except Rejected as e:
            problems += e.reasons
    if kinds == ("svg",) and (b.roots != ["svg"] or b.top_text):
        problems.append(f"{where} 要剛好是一張 <svg>…</svg>")
    if not problems and not markup:
        problems.append(f"{where} 是空的（沒有可以顯示的東西）")
    if problems:
        raise Rejected(problems)
    return Clean(markup, css, b.notes)


# ── CSS ───────────────────────────────────────────────────────────────

ROOT_SELECTORS = (':root', ':root[data-theme="light"]', ':root[data-theme="dark"]',
                  ':root:not([data-theme="light"])', ':root:not([data-theme="dark"])')
_ROOT_PREFIX = r'(?::root(?:\[data-theme="(?:light|dark)"\]|:not\(\[data-theme="(?:light|dark)"\]\))?\s+)?'
_SCOPE_RE = re.compile(_ROOT_PREFIX + r"""(?:\[data-slot(?:=(?:"[a-z.]{1,30}"|'[a-z.]{1,30}'|[a-z.]{1,30}))?\]"""
                       r"|\.theme-slot-[a-z0-9-]{1,40})(?=$|[\s>:.\[#])")
_KEYFRAMES_RE = re.compile(r"^@keyframes\s+([A-Za-z_][\w-]{0,60})$", re.IGNORECASE)
_KEYSTOP_RE = re.compile(r"^(from|to|\d{1,3}(\.\d+)?%)(\s*,\s*(from|to|\d{1,3}(\.\d+)?%))*$", re.IGNORECASE)
_COND_RE = re.compile(r"^[\w\s():,.\-/]{1,200}$")
_PROP_RE = re.compile(r"^(--[A-Za-z0-9_-]{1,60}|-?[a-z][a-z0-9-]{0,40})$")
_CSS_BANNED = (("\\", "反斜線跳脫（\\…）"), ("<", "「<」"), ("@import", "@import"), ("@font-face",
               "@font-face（字型請寫在 pack.json 的 theme.fonts）"), ("@namespace", "@namespace"),
               ("@charset", "@charset"), ("expression(", "expression()"), ("javascript:", "javascript:"),
               ("vbscript:", "vbscript:"), ("-moz-binding", "-moz-binding"),
               ("image-set(", "image-set()"), ("cross-fade(", "cross-fade()"), ("element(", "element()"),
               ("src(", "src()"), ("!important", "!important（網頁替每個位置釘死的規則不能被蓋掉）"))
_BANNED_PROPS = {"behavior", "-moz-binding", "-ms-behavior"}


def _split_top(text: str, sep: str) -> List[str]:
    """照 sep 切，括號、中括號、字串裡的不算。"""
    out, depth, quote, start = [], 0, "", 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return [p for p in (x.strip() for x in out) if p]


def _blocks(text: str, where: str) -> List[Tuple[str, str]]:
    """'a { b } @media x { c { d } }' → [(前面那段, 大括號裡面)]；大括號不成對、外面多了字＝拒絕。"""
    out, i, n, start = [], 0, len(text), 0
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "}":
            raise Rejected(f"{where} 的大括號不成對")
        elif ch == "{":
            prelude = text[start:i].strip()
            depth, j, q2 = 1, i + 1, ""
            while j < n and depth:
                c = text[j]
                if q2:
                    if c == q2:
                        q2 = ""
                elif c in "\"'":
                    q2 = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                j += 1
            if depth:
                raise Rejected(f"{where} 的大括號不成對")
            out.append((prelude, text[i + 1:j - 1]))
            i = j
            start = j
            continue
        i += 1
    if quote:
        raise Rejected(f"{where} 有沒關起來的引號")
    rest = text[start:].strip()
    if rest:
        raise Rejected(f"{where} 有多出來、不在任何規則裡的字：{rest[:60]!r}")
    return out


def _outer(selector: str) -> str:
    """選擇器去掉 [...]、(...)、字串之後剩下的（看組合子用）。"""
    out, depth, quote = [], 0, ""
    for ch in selector:
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch in "([":
            depth += 1
            continue
        if ch in ")]":
            depth = max(0, depth - 1)
            continue
        if not depth:
            out.append(ch)
    return "".join(out)


def _rewrite_selector_ids(selector: str, key: str) -> str:
    """#id → #ts-<slot>-id（[...] 與字串裡的 # 不動）。"""
    out, depth, quote, i = [], 0, "", 0
    while i < len(selector):
        ch = selector[i]
        if quote:
            if ch == quote:
                quote = ""
            out.append(ch)
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "[":
            depth += 1
            out.append(ch)
        elif ch == "]":
            depth = max(0, depth - 1)
            out.append(ch)
        elif ch == "#" and not depth:
            m = re.match(r"#([A-Za-z_][\w-]{0,60})", selector[i:])
            if m:
                out.append("#" + prefix_id(key, m.group(1)))
                i += len(m.group(0))
                continue
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


class _Css:
    def __init__(self, slot: Optional[str], where: str):
        self.slot, self.where = slot, where
        self.key = contract.slot_key(slot) if slot else ""
        self.problems: List[str] = []
        self.renamed: Dict[str, str] = {}

    def custom_prop_ok(self, prop: str) -> bool:
        return prop.startswith("--th-") or bool(contract.token_name(prop))

    def decls(self, body: str, root: bool) -> str:
        out = []
        for part in _split_top(body, ";"):
            if ":" not in part:
                self.problems.append(f"{self.where} 有看不懂的宣告：{part[:60]!r}")
                continue
            prop, value = part.split(":", 1)
            prop, value = prop.strip(), " ".join(value.split())
            low = prop.lower()
            if not _PROP_RE.match(prop if prop.startswith("--") else low) or not value or len(value) > 2000:
                self.problems.append(f"{self.where} 的宣告寫法不對：{part[:60]!r}")
                continue
            if low in _BANNED_PROPS:
                self.problems.append(f"{self.where} 有 {low}")
                continue
            if root:
                if not prop.startswith("--") or not self.custom_prop_ok(prop):
                    self.problems.append(f"{self.where} 的 :root 只能設 token（--bg、--accent…）或 --th- 開頭的自訂屬性，"
                                         f"不能設 {prop}")
                    continue
                if contract.token_name(prop):
                    from synox.theme.tokens import token_value_problem
                    why = token_value_problem(contract.token_name(prop), value)
                    if why:
                        self.problems.append(f"{self.where} 的 {prop}：{why}")
                        continue
            if "{" in value or "}" in value:
                self.problems.append(f"{self.where} 的 {prop} 值裡有大括號")
                continue
            if "url(" in value.lower():
                value = _rewrite_urls(value, self.key, f"{self.where} 的 {prop}", self.problems)
            if self.renamed and low in ("animation", "animation-name"):
                value = re.sub(r"(?<![\w-])(" + "|".join(map(re.escape, self.renamed)) + r")(?![\w-])",
                               lambda m: self.renamed[m.group(1)], value)
            out.append(f"{prop if prop.startswith('--') else low}: {value}")
        return "; ".join(out)

    def selectors(self, prelude: str) -> Tuple[str, bool]:
        """→ (整理過的選擇器清單, 是不是 :root 那種)。"""
        sels = _split_top(prelude, ",")
        if not sels:
            self.problems.append(f"{self.where} 有空的選擇器")
            return "", False
        roots = [" ".join(s.split()) in ROOT_SELECTORS for s in sels]
        if any(roots) and not all(roots):
            self.problems.append(f"{self.where} 的 :root 規則請跟別的選擇器分開寫：{prelude[:60]!r}")
            return "", False
        if all(roots):
            if self.slot:
                self.problems.append(f"{self.where} 不能寫 :root（自己貼的 CSS 只會套在這個位置裡面）")
                return "", False
            return ", ".join(" ".join(s.split()) for s in sels), True
        out = []
        for s in sels:
            s = " ".join(s.split())
            if len(s) > 300 or re.search(r"[{};@\\<]", s):
                self.problems.append(f"{self.where} 的選擇器寫法不對：{s[:60]!r}")
                continue
            outer = _outer(s)
            if "+" in outer or "~" in outer:
                self.problems.append(f"{self.where} 的選擇器有兄弟組合子（+ 或 ~），會選到位置外面的東西：{s[:60]!r}")
                continue
            if ":has(" in s.lower() or ":host" in s.lower() or "::slotted" in s.lower():
                self.problems.append(f"{self.where} 的選擇器不能用 :has()／:host：{s[:60]!r}")
                continue
            if self.slot:
                if _SCOPE_RE.match(s) and not s.startswith(":root"):
                    scoped = s
                elif re.match(r"^(:root|html|body)\b", s, re.IGNORECASE):
                    self.problems.append(f"{self.where} 不能選 {s.split()[0]}（自己貼的 CSS 只會套在這個位置裡面）")
                    continue
                else:
                    scoped = f'[data-slot="{self.slot}"] {s}'
                out.append(_rewrite_selector_ids(scoped, self.key))
            else:
                if not _SCOPE_RE.match(s):
                    self.problems.append(f"{self.where} 的規則要套在 [data-slot] 或 .theme-slot-* 裡面"
                                         f"（或只在 :root 設 token）：{s[:60]!r}")
                    continue
                out.append(s)
        return ", ".join(out), False

    def rules(self, text: str, depth: int = 0) -> str:
        out = []
        for prelude, body in _blocks(text, self.where):
            low = prelude.lower()
            if prelude.startswith("@"):
                km = _KEYFRAMES_RE.match(" ".join(prelude.split()))
                if km:
                    name = km.group(1)
                    if self.slot:
                        new = f"th-{self.key}-{name}" if not name.startswith("th-") else name
                        self.renamed[name] = new
                        name = new
                    elif not name.startswith("th-"):
                        self.problems.append(f"{self.where} 的 @keyframes 名字要 th- 開頭（現在是 {name!r}）")
                        continue
                    frames = []
                    for stop, decl in _blocks(body, self.where):
                        stop = " ".join(stop.split())
                        if not _KEYSTOP_RE.match(stop):
                            self.problems.append(f"{self.where} 的 @keyframes {name} 有看不懂的時間點 {stop[:30]!r}")
                            continue
                        frames.append(f"{stop} {{ {self.decls(decl, False)} }}")
                    out.append(f"@keyframes {name} {{ " + " ".join(frames) + " }")
                    continue
                m = re.match(r"^@(media|supports)\s+(.+)$", " ".join(prelude.split()), re.IGNORECASE)
                if m and _COND_RE.match(m.group(2)) and depth < 2:
                    out.append(f"@{m.group(1).lower()} {m.group(2)} {{ {self.rules(body, depth + 1)} }}")
                    continue
                self.problems.append(f"{self.where} 不收這種 @ 規則：{prelude[:40]!r}"
                                     "（只收 @keyframes th-…、@media、@supports）")
                continue
            if "@" in low:
                self.problems.append(f"{self.where} 的選擇器寫法不對：{prelude[:60]!r}")
                continue
            sels, root = self.selectors(prelude)
            if sels:
                out.append(f"{sels} {{ {self.decls(body, root)} }}")
        return "\n".join(out)


def sanitize_css(text, *, slot: Optional[str] = None, where: str = "CSS") -> str:
    """一份 CSS → 重新組好的 CSS；有不收的東西丟 Rejected。
    slot=None（外觀包的 theme.css）：每條規則要自己寫在 [data-slot]／.theme-slot-* 裡（或 :root 只設 token）；
    slot="mascot.idle"（SVG 裡的 <style>、自己貼的）：每個選擇器自動套上 [data-slot="mascot.idle"]，#id 跟著加前綴，
    @keyframes 自動改名成 th-<slot>-…（animation 裡的名字一起改）。"""
    if not isinstance(text, str):
        raise Rejected(f"{where} 要是文字")
    if len(text.encode("utf-8")) > MAX_CSS:
        raise Rejected(f"{where} 太大（最多 {MAX_CSS // 1024} KB）")
    if "/*" in re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL):
        raise Rejected(f"{where} 有沒關起來的註解")
    body = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    low = _squash(body)
    problems = [f"{where} 有 {why}" for bad, why in _CSS_BANNED if _squash(bad) in low]
    for m in re.finditer(r"url\(", body, re.IGNORECASE):
        seg = body[m.start():m.start() + 200]
        um = _URL_RE.match(seg)
        if not um or not _LOCAL_REF_RE.match(um.group(2).strip()):
            problems.append(f"{where} 有外部網址 {seg[:60].split(')')[0]})（只收同一份裡的 url(#id)）")
    if problems:
        raise Rejected(problems)
    c = _Css(slot, where)
    if slot:                                           # 先收集 @keyframes 名字（animation 寫在前面也改得到）
        for name in re.findall(r"@keyframes\s+([A-Za-z_][\w-]{0,60})", body, re.IGNORECASE):
            c.renamed[name] = name if name.startswith("th-") else f"th-{c.key}-{name}"
    out = c.rules(body)
    if c.problems:
        raise Rejected(c.problems)
    return out
