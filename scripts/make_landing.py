"""重做介紹頁 docs/landing/index.html（單一檔案、雙擊就能開，也是線上 Artifact 的原稿）。

    python scripts/make_landing.py            只組頁面：docs/landing/page.html ＋ docs/landing/shots/*.webp → index.html
    python scripts/make_landing.py --shoot    先重拍截圖再組（要 Playwright：pip install playwright pillow，
                                              再 python -m playwright install chromium；或用 --chromium <路徑> 指定現成的瀏覽器）

截圖拍的是 docs/ui/preview.html（scripts/make_ui_preview.py 產生的假資料預覽，不用開 SYNOX、不連網）：
- 電腦版 1360×820、2 倍解析度，淺色＋深色各一張；手機版 390×844（iPhone 尺寸），淺色＋深色各一張。
- 存成 WebP（docs/landing/shots/），組頁面時轉成 data URI 嵌進 index.html，所以整頁只有一個檔。
網頁介面改了樣子：先重跑 make_ui_preview.py，再跑這支加 --shoot；然後把 index.html 重新發佈成 Artifact（網址在 README）。

開場動畫（S 寶寶）跟網頁介面是同一份：組頁面時把 src/synox/web/static/splash.js 整支、splash.css 裡「開場」那一段
原封不動塞進 page.html 的 /*{{splash-js}}*/、/*{{splash-css}}*/。網頁版的開場改了，重組一次介紹頁就跟著變。
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANDING = os.path.join(ROOT, "docs", "landing")
SHOTS = os.path.join(LANDING, "shots")
PREVIEW = os.path.join(ROOT, "docs", "ui", "preview.html")
STATIC = os.path.join(ROOT, "src", "synox", "web", "static")

# (檔名, 網址 hash, 等多久)；檔名會加 -light／-dark
DESKTOP = [
    ("chat", "#chat"),
    ("tools", "#tools"),
    ("control", "#control"),
    ("settings", "#settings:ai"),
    ("packs", "#packs"),
    ("channels", "#settings:channels"),
]
MOBILE = [
    ("m-chat", "#chat"),
    ("m-tools", "#tools"),
    ("m-control", "#control"),
]
DESKTOP_WIDTH = 1800      # WebP 的寬（原圖 2720，縮一點讓整頁小一點，放大看仍清楚）
QUALITY = 82


def shoot(chromium: str | None) -> None:
    from PIL import Image
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    url = "file:///" + PREVIEW.replace(os.sep, "/").lstrip("/")

    def save(png: bytes, name: str, width: int | None) -> None:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        if width and im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        path = os.path.join(SHOTS, name + ".webp")
        im.save(path, "WEBP", quality=QUALITY, method=6)
        print("wrote", os.path.relpath(path, ROOT), im.size, os.path.getsize(path) // 1024, "KB")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium) if chromium else p.chromium.launch()
        for theme in ("light", "dark"):
            ctx = browser.new_context(viewport={"width": 1360, "height": 820}, device_scale_factor=2,
                                      color_scheme=theme)
            page = ctx.new_page()
            for name, hash_ in DESKTOP:
                page.goto(f"{url}?bar=0&splash=0&theme={theme}{hash_}")
                page.wait_for_timeout(900)
                save(page.screenshot(), f"{name}-{theme}", DESKTOP_WIDTH)
            ctx.close()
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                      color_scheme=theme, is_mobile=True, has_touch=True)
            page = ctx.new_page()
            for name, hash_ in MOBILE:
                page.goto(f"{url}?bar=0&splash=0&theme={theme}{hash_}")
                page.wait_for_timeout(900)
                save(page.screenshot(), f"{name}-{theme}", None)
            ctx.close()
        browser.close()


def splash_parts() -> tuple[str, str]:
    """splash.css 只取開場用的部分：最上面的 :root（--sx-* 曲線）和 .sx-splash … .sx-hint；
    後面那些是網頁介面自己的微動畫（側欄、卡片、按鈕），介紹頁用不到。找不到記號就停，不要默默組出壞頁面。"""
    with open(os.path.join(STATIC, "splash.css"), encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(STATIC, "splash.js"), encoding="utf-8") as f:
        js = f.read()
    root = re.search(r":root \{[^}]*\}", css)
    start = css.find(".sx-splash {")
    end = css.find("/* 開場時：")
    if not root or start < 0 or end < start:
        raise SystemExit("splash.css 的結構變了（找不到 :root／.sx-splash／「開場時：」），請更新 make_landing.py 的擷取規則")
    return root.group(0) + "\n  " + css[start:end].rstrip() + "\n", js


def build() -> None:
    with open(os.path.join(LANDING, "page.html"), encoding="utf-8") as f:
        html = f.read()

    def shot(m: re.Match) -> str:
        path = os.path.join(SHOTS, m.group(1) + ".webp")
        with open(path, "rb") as f:
            return "data:image/webp;base64," + base64.b64encode(f.read()).decode("ascii")

    html, n = re.subn(r"\{\{shot:([a-z0-9-]+)\}\}", shot, html)
    css, js = splash_parts()
    for mark, text in (("/*{{splash-css}}*/", css), ("/*{{splash-js}}*/", js)):
        if html.count(mark) != 1:
            raise SystemExit(f"page.html 要剛好有一個 {mark}")
        html = html.replace(mark, text)
    out = os.path.join(LANDING, "index.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"wrote {os.path.relpath(out, ROOT)}: {n} images, {os.path.getsize(out) // 1024} KB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shoot", action="store_true", help="先重拍截圖")
    ap.add_argument("--chromium", help="Chromium 執行檔路徑（不給就用 Playwright 自己裝的）")
    a = ap.parse_args()
    if a.shoot:
        shoot(a.chromium)
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
