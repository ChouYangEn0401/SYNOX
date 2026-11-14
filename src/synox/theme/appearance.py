"""
「設定 → 外觀」的後端：裝了哪些外觀包、誰選了哪一個、自己貼的東西、淺色／深色，以及送網頁時要多塞進 <head> 的東西。

存在哪裡、誰的算數（docs/themes.md「存在哪裡」）：
- 存在每個人的網頁偏好（data/web_prefs/<tg_id>.json(.enc)，web/toolpage.UserPrefs）的 "appearance"：
      {"theme": "<外觀包名字>"｜""（原本的 SYNOX）, "mode": "auto"｜"light"｜"dark", "custom": {"<slot>": "<貼的原文>"}}
- **個人版**：只有擁有者，擁有者的那一份就是這台的外觀。
- **伺服器版**：每個人自己選、自己貼（只影響自己的畫面）；**沒選過的欄位跟擁有者的一樣**（擁有者的那一份＝這台的預設）。
  還沒登入的畫面（登入卡）用擁有者的。外觀包只有擁有者能裝（跟其他 pack 一樣）。
- 存的是貼上的原文；每次送網頁都重新消毒（消毒規則更新了，舊的東西照新規則；過不了＝那一格當作沒貼）。
"""

from __future__ import annotations

import hashlib
import html as html_mod
import logging
import os
import threading
from typing import Dict, List, Optional, Tuple

from synox.theme import contract, defaults, sanitize
from synox.theme import pack as theme_pack
from synox.theme import tokens as theme_tokens

PREF_KEY = "appearance"
MAX_CUSTOM = 32 * 1024            # 自己貼的一格最多多大
FIELDS = ("theme", "mode", "custom")


class AppearanceError(ValueError):
    """給人看的一句話。"""


def _signature(folder: str) -> tuple:
    out = []
    for base, _dirs, names in os.walk(folder):
        for n in sorted(names):
            p = os.path.join(base, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append((os.path.relpath(p, folder), st.st_mtime_ns, st.st_size))
    return tuple(sorted(out))


def clean_prefs(raw) -> dict:
    """存檔裡的 appearance → 只留認得的（壞掉的當作沒寫：外觀只是偏好，不能讓網頁打不開）。"""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("theme"), str) and len(raw["theme"]) <= 32:
        out["theme"] = raw["theme"]
    if raw.get("mode") in contract.MODES:
        out["mode"] = raw["mode"]
    custom = raw.get("custom")
    if isinstance(custom, dict):
        out["custom"] = {k: v for k, v in custom.items()
                         if contract.slot_name(k) == k and isinstance(v, str) and len(v.encode("utf-8")) <= MAX_CUSTOM}
    return out


class Appearance:
    def __init__(self, app, config, prefs):
        self.app, self.config, self.prefs = app, config, prefs
        self._lock = threading.Lock()
        self._bundles: Dict[str, tuple] = {}            # 名字 → (signature, Bundle 或 None)
        self._custom: Dict[str, sanitize.Clean] = {}    # (slot, sha256) → Clean

    # ── 裝了哪些 ──
    def installed(self) -> List:
        """載入過、狀態 loaded 的外觀包（過了第 3 關的鎖；被停用、被改過的不算）→ [Manifest]。"""
        from synox.packs.manifest import ManifestError, read
        report = self.app.extras.get("synox_pack_report")
        out = []
        for item in (report.items if report else []):
            if getattr(item, "kind", "") != "theme" or item.status != "loaded":
                continue
            try:
                out.append(read(item.folder))
            except ManifestError as e:
                logging.warning("[THEME] %s unreadable: %s", item.name, e)
        return out

    def manifest(self, name: str):
        return next((m for m in self.installed() if m.name == name), None)

    def bundle_of(self, m) -> Optional[theme_pack.Bundle]:
        """外觀包 → Bundle（照檔案的 mtime／大小快取）；消毒不過＝None（記 log，畫面照原本的）。"""
        sig = _signature(m.folder)
        with self._lock:
            hit = self._bundles.get(m.name)
            if hit and hit[0] == sig:
                return hit[1]
        try:
            bundle = theme_pack.compile_theme(m.folder, m.name, m.theme)
        except (sanitize.Rejected, OSError, UnicodeDecodeError) as e:
            logging.error("[THEME] %s could not be compiled: %s", m.name, e)
            bundle = None
        with self._lock:
            self._bundles[m.name] = (sig, bundle)
        return bundle

    # ── 誰選了什麼 ──
    def owner_id(self) -> int:
        return int(getattr(self.config, "owner_id", 0) or 0)

    def own(self, tg_id: Optional[int]) -> dict:
        if not tg_id:
            return {}
        try:
            return clean_prefs(self.prefs.get(int(tg_id), PREF_KEY))
        except Exception:                                # 保管箱解不開之類：外觀當作沒選（不擋網頁）
            logging.exception("[THEME] could not read appearance of %s", tg_id)
            return {}

    def effective(self, tg_id: Optional[int]) -> dict:
        """這個人看到的（伺服器版：自己沒選的欄位用擁有者的）。tg_id=None＝還沒登入。"""
        owner = self.own(self.owner_id())
        mine = owner if tg_id in (None, self.owner_id()) else self.own(tg_id)
        out = {"theme": "", "mode": "auto", "custom": {}}
        for key in FIELDS:
            if key in mine:
                out[key] = mine[key]
            elif key in owner:
                out[key] = owner[key]
        return out

    def save(self, tg_id: int, changes: dict) -> dict:
        """改這個人的外觀（只改給了的欄位）。theme 要是裝好的外觀包或 ""；custom 每一格先消毒過才存。"""
        current = self.own(tg_id)
        if "theme" in changes:
            name = changes["theme"]
            if name in (None, ""):
                current["theme"] = ""
            elif not isinstance(name, str) or self.manifest(name) is None:
                raise AppearanceError("沒有裝這個外觀包（或它現在不能用）。")
            elif self.bundle_of(self.manifest(name)) is None:
                raise AppearanceError("這個外觀包的檔案過不了消毒，不能套用（doctor 或 log 有原因）。")
            else:
                current["theme"] = name
        if "mode" in changes:
            if changes["mode"] not in contract.MODES:
                raise AppearanceError("淺色／深色只能是 auto、light、dark。")
            current["mode"] = changes["mode"]
        if "custom" in changes:
            slot, text = changes["custom"].get("slot"), changes["custom"].get("text")
            if contract.slot_name(slot) != slot:
                raise AppearanceError("不認得這個位置。")
            custom = dict(current.get("custom") or self.effective(tg_id).get("custom") or {})
            if text in (None, ""):
                custom.pop(slot, None)
            else:
                self.clean_custom(slot, text)            # 過不了丟 AppearanceError
                custom[slot] = text
            current["custom"] = custom
        if changes.get("reset"):
            current = {}
        self.prefs.set(int(tg_id), PREF_KEY, current or None)
        return self.effective(tg_id)

    def clean_custom(self, slot: str, text) -> sanitize.Clean:
        if not isinstance(text, str) or not text.strip():
            raise AppearanceError("是空的。")
        if len(text.encode("utf-8")) > MAX_CUSTOM:
            raise AppearanceError(f"太大了（一格最多 {MAX_CUSTOM // 1024} KB）。")
        key = (slot, hashlib.sha256(text.encode("utf-8")).hexdigest())
        with self._lock:
            hit = self._custom.get(key)
        if hit is not None:
            return hit
        try:
            clean = sanitize.sanitize_markup(text, slot, kinds=contract.SLOTS[slot][2], where="貼上的內容")
        except sanitize.Rejected as e:
            raise AppearanceError("不收：" + "；".join(e.reasons[:8]))
        with self._lock:
            if len(self._custom) > 200:
                self._custom.clear()
            self._custom[key] = clean
        return clean

    # ── 送網頁 ──
    def parts(self, tg_id: Optional[int]) -> Tuple[str, str, str, Dict[str, str], str]:
        """(mode, 外觀包名字或 "", CSS, {slot: markup}, appicon 的 data: 網址)。"""
        pref = self.effective(tg_id)
        css, slots, icon, name = [], {}, "", ""
        if pref.get("theme"):
            m = self.manifest(pref["theme"])
            bundle = self.bundle_of(m) if m is not None else None
            if bundle is not None:
                name = m.name
                css.append(bundle.stylesheet())
                slots.update(bundle.slots)
        for slot, text in (pref.get("custom") or {}).items():
            try:
                clean = self.clean_custom(slot, text)
            except AppearanceError as e:
                logging.warning("[THEME] custom %s dropped: %s", slot, e)
                continue
            slots[slot] = clean.markup                    # 自己貼的蓋過外觀包的
            if clean.css:
                css.append(clean.css)
        if "appicon" in slots:
            icon = theme_pack.appicon_uri(slots.pop("appicon"))
        return pref.get("mode") or "auto", name, "\n".join(c for c in css if c), slots, icon

    def head(self, tg_id: Optional[int], nonce: str) -> Tuple[str, str, str]:
        """→ (mode, 外觀包名字, 要塞進 <head> 的 HTML)。"""
        mode, name, css, slots, icon = self.parts(tg_id)
        return mode, name, head_html(nonce, css, slots, icon)

    def describe(self, tg_id: int, owner: bool, server: bool) -> dict:
        """GET /api/appearance：給「設定 → 外觀」畫的資料。"""
        mine = self.own(tg_id)
        eff = self.effective(tg_id)
        themes = []
        for m in self.installed():
            themes.append({"name": m.name, "title": m.title, "summary": m.summary, "version": m.version,
                           "publisher": m.publisher, "tokens": m.theme.get("tokens") or {},
                           "slots": sorted(m.theme.get("slots") or {}), "ok": self.bundle_of(m) is not None})
        custom = {}
        for slot, text in (eff.get("custom") or {}).items():
            try:
                clean = self.clean_custom(slot, text)
                custom[slot] = {"text": text, "markup": clean.markup, "css": clean.css, "notes": clean.notes, "ok": True}
            except AppearanceError as e:
                custom[slot] = {"text": text, "ok": False, "error": str(e)}
        if not server:
            scope = "install"
        else:
            scope = "owner-default" if owner else "user"
        return {"themes": themes, "theme": eff["theme"], "mode": eff["mode"], "custom": custom,
                "inherited": [k for k in FIELDS if k not in mine and tg_id != self.owner_id()],
                "slots": [{"name": n, "text": d, "kinds": list(k)} for n, (d, _v, k) in contract.SLOTS.items()],
                "tokens": list(contract.TOKENS), "contract": contract.CONTRACT_VERSION, "owner": owner,
                "server": server, "scope": scope, "defaults": contract.DEFAULTS}


def head_html(nonce: str, css: str, slots: Dict[str, str], icon: str = "") -> str:
    """<style nonce>（外觀的 CSS）＋每個換掉的 slot 一個 <template data-slot-src>＋favicon。
    （原本的 SYNOX 的 <template data-slot-default> 由 web/server.render_app 一律放，見 default_templates。）
    CSS、markup 都是消毒過的：CSS 裡不會有 <（不會提早結束 </style>）、markup 是白名單重建的。"""
    parts = []
    if css:
        if "<" in css:                                    # 防禦深度：消毒過的不該有，有就整段不送
            logging.error("[THEME] stylesheet contains '<'; not sent")
        else:
            parts.append(f'<style nonce="{html_mod.escape(nonce, quote=True)}" id="synox-theme">\n{css}\n</style>')
    for slot, markup in slots.items():
        if contract.slot_name(slot) == slot:
            parts.append(f'<template data-slot-src="{slot}">{markup}</template>')
    if icon.startswith("data:image/svg+xml;base64,"):
        parts.append(f'<link rel="icon" href="{html_mod.escape(icon, quote=True)}">')
    return "\n".join(parts)


def default_templates() -> str:
    """原本的 SYNOX 在 slot 裡放的 SVG（defaults.MARKUP）→ <template data-slot-default>：每一頁都有。"""
    return "\n".join(f'<template data-slot-default="{slot}">{markup}</template>'
                     for slot, markup in defaults.MARKUP.items())


# ── 預覽頁（/theme/preview）：沒有程式的一小頁，用 iframe 掛在設定頁與安裝報告上 ───────────────────

PREVIEW_CSS = """
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--text);font:12.5px/1.45 var(--font-ui,system-ui,sans-serif);overflow:hidden}
.top{display:flex;align-items:center;gap:7px;padding:7px 10px;background:var(--surface);border-bottom:1px solid var(--line)}
.name{font:800 12px/1 var(--font-brand,var(--font-ui,system-ui));letter-spacing:.12em;min-width:0;flex:1}
.mark{width:24px;height:24px;flex:none;border-radius:calc(var(--radius,10px)*.9);display:grid;place-items:center;
 font:800 12px/1 var(--font-brand,var(--font-ui,system-ui));color:var(--accent-ink);
 background:linear-gradient(140deg,var(--accent),color-mix(in srgb,var(--accent) 55%,var(--accent2)))}
.mark.slot-host{background:none}
.sw{display:flex;gap:2px}.sw i{width:9px;height:18px;border-radius:3px}
.sw .c1{background:var(--accent)}.sw .c2{background:var(--accent2)}.sw .c3{background:var(--soft)}.sw .c4{background:var(--ok)}
.sw .c5{background:var(--warn)}.sw .c6{background:var(--bad)}
main{padding:8px 10px;display:flex;flex-direction:column;gap:6px;min-width:0}
.msg{max-width:88%;padding:5px 9px;border-radius:calc(var(--radius,10px)*1.6)}
.me{align-self:flex-end;background:var(--me);color:var(--me-ink)}
.bot{align-self:flex-start;background:var(--surface-2);border:1px solid var(--line)}
.pending{display:flex;align-items:center;gap:7px;color:var(--muted)}
.think{width:22px;height:22px;flex:none;display:block}
.row{display:flex;gap:5px;flex-wrap:wrap;align-items:center}
.btn{font-size:11.5px;padding:3px 9px;border-radius:var(--radius,10px);border:1px solid var(--line-strong);background:var(--surface);color:var(--text)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:650}
.badge{font-size:10.5px;padding:1px 6px;border-radius:999px}
.badge.ok{background:var(--ok-soft);color:var(--ok)}.badge.warn{background:var(--warn-soft);color:var(--warn)}
.badge.bad{background:var(--bad-soft);color:var(--bad)}
.moods{display:flex;gap:8px;align-items:center;margin-top:2px}
.mood{width:34px;height:34px;display:block;flex:none}
.open{width:60px;height:60px;flex:none;margin-left:auto;border:1px dashed var(--line-strong);border-radius:var(--radius,10px);
 background:var(--bg-glow);overflow:hidden;display:grid;place-items:center}
.open > [data-slot]{width:56px;height:56px}
[data-slot]{position:relative!important;inset:auto!important;margin:0!important;transform:none!important;
 translate:none!important;scale:none!important;rotate:none!important;contain:paint!important;overflow:clip!important;
 z-index:auto!important;float:none!important;display:block}
[data-slot]>svg{width:100%;height:100%;display:block}
.name [data-slot]{display:inline-block;max-width:100%}.name [data-slot]>svg{height:1.35em;width:auto}
.mark [data-slot]{width:100%;height:100%;display:grid;place-items:center}
.cb-side{fill:var(--m1)}.cb-top{fill:var(--m-hi)}.cb-right{fill:var(--m2)}.cb-eye{fill:var(--mi)}
.sb-face{fill:var(--accent)}.sb-ink{fill:var(--accent-ink)}.sb-line{fill:none;stroke:var(--accent-ink);stroke-width:2.4;stroke-linecap:round}
.sb-blush{fill:var(--mb)}.sb-drop{fill:var(--accent2)}
"""


def preview_tokens(tokens: Optional[dict]) -> str:
    """預覽頁的 token：外觀包的（沒給＝原本的 SYNOX，進階的用算的）。"""
    if not tokens:
        light = dict(contract.DEFAULTS["light"])
        dark = {**{k: light[k] for k in contract.MASCOT_TOKENS + ("m-hi",) if k in light}, **contract.DEFAULTS["dark"]}
        tokens = {"light": light, "dark": dark}
    return theme_tokens.token_css(tokens)


def preview_page(title: str, mode: str, bundle: Optional[theme_pack.Bundle], tokens: Optional[dict]) -> str:
    """一小頁假的對話畫面（側欄、泡泡、等回覆、按鈕、狀態、開心／擔心、開場），套上這個外觀。沒有 <script>。"""
    slots = dict(bundle.slots) if bundle else {}
    slots.pop("appicon", None)

    def slot(name: str, fallback: str = "", cls: str = "") -> str:
        markup = slots.get(name) or defaults.MARKUP.get(name) or fallback
        key = contract.slot_key(name)
        return f'<span class="slot theme-slot-{key}{" " + cls if cls else ""}" data-slot="{name}">{markup}</span>'

    css = PREVIEW_CSS + "\n" + preview_tokens(tokens)
    if bundle is not None:
        css += "\n" + bundle.stylesheet()
    host = " slot-host" if "mascot.idle" in slots else ""
    swatches = "".join(f'<i class="c{i}"></i>' for i in range(1, 7))
    opening = f'<div class="open">{slot("opening", "")}</div>' if "opening" in slots else ""
    mode_attr = f' data-theme="{mode}"' if mode in ("light", "dark") else ""
    return ("<!doctype html><html lang=\"zh-Hant\"" + mode_attr + "><head><meta charset=\"utf-8\">"
            f"<title>{html_mod.escape(title)}</title><style>{css}</style></head><body>"
            f"<div class=\"top\"><span class=\"mark{host}\">{slot('mascot.idle', 'S')}</span>"
            f"<span class=\"name\">{slot('wordmark', 'SYNOX')}</span><span class=\"sw\" aria-hidden=\"true\">{swatches}</span></div>"
            "<main><div class=\"msg me\">幫我記：明天要買牛奶</div>"
            "<div class=\"msg bot\">好，記下來了 ✅</div>"
            f"<div class=\"msg bot pending\">{slot('mascot.think', '', 'think')}<span>正在想…</span></div>"
            "<div class=\"row\"><span class=\"btn primary\">確認</span><span class=\"btn\">稍後</span>"
            "<span class=\"badge ok\">能用</span><span class=\"badge warn\">注意</span><span class=\"badge bad\">壞了</span></div>"
            f"<div class=\"moods\">{slot('mascot.happy', '', 'mood')}{slot('mascot.warn', '', 'mood')}{opening}</div>"
            "</main></body></html>")
