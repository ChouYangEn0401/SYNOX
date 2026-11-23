"""組一步一步安裝教學頁（docs/guide/index.html）裡由程式產生的兩段，再重蓋頁面版本。

    python scripts/build_guide.py           # 改寫下面兩段；有改就重蓋頁面版本（<span data-stamp>）
    python scripts/build_guide.py --check   # 只檢查（tests/test_build_guide.py 用）：教學步驟沒同步＝退出碼 1；
                                            # 版本與下載連結不是現在的版本＝只提醒（發版的關卡是 release.py check --tag）

1. 教學步驟：<script type="application/json" id="tour-steps">…</script>
   來自內建新手教學的步驟檔（src/synox/tour/tours/basics.json）。同一份字、兩個出口
   （docs/lab/2026-11-13-onboarding-help-aliases-plan.md §3.5，G1）：SYNOX 網頁裡的 /tutorial 在真的畫面上指給人看；
   安裝教學頁把同一份步驟當成「選讀：SYNOX 網頁導覽」那一段（示意畫面上的位置用同一份位置名字，synox/tour/anchors.py）。
   改教學的字只改 basics.json，再跑這支。用 SYNOX 自己的步驟檔檢查（synox.tour.schema）：不合格的步驟檔不會被放進頁面。
2. 版本與下載連結：<script type="application/json" id="release-info">…</script>
   來自 scripts/release.py 的 download_info()（版本讀 pyproject.toml 與 src/synox/__init__.py）：這一版的號碼、tag、
   SYNOX-<版本>.zip 與 SYNOX-Setup-<版本>.exe 的檔名和下載網址。頁面上的檔名、按鈕、示意畫面都讀這一段，所以
   每次發版（alpha、beta 也算）重跑這支就是最新的，再重新發佈同一個線上網址（docs/release-playbook.md 第 7 節）。

只用標準函式庫（＋上面兩個 SYNOX 自己的模組）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

GUIDE = os.path.join(ROOT, "docs", "guide", "index.html")
TOUR = os.path.join(ROOT, "src", "synox", "tour", "tours", "basics.json")
BLOCK_RE = re.compile(r'^(<script type="application/json" id="tour-steps">)(.*?)(</script>)', re.S | re.M)   # 一行的開頭
RELEASE_RE = re.compile(r'^(<script type="application/json" id="release-info">)(.*?)(</script>)', re.S | re.M)
RELEASE_KEYS = ("version", "tag", "prerelease", "zip", "exe", "zip_url", "exe_url", "page_url", "releases_url")


def _embed(data) -> str:
    """放進 <script type="application/json"> 的 JSON（不會提早結束 <script>）。"""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    return "\n" + text.replace("</", "<\\/").replace("<!--", "<\\!--") + "\n"


def steps_json(path: str = TOUR) -> str:
    """教學（擁有者看到的那一份步驟）→ 放進頁面的 JSON。"""
    from synox.tour import schema
    tour = schema.load_file(path)
    out = {"id": tour.id, "title": tour.title, "version": tour.version, "minutes": tour.minutes,
           "steps": []}
    for s in tour.steps_for(True):
        item = {"id": s.id, "title": s.title, "body": s.body, "anchors": list(s.anchors)}
        if s.go:
            item["view"] = s.go.get("view", "")
            if s.go.get("tab"):
                item["tab"] = s.go["tab"]
        if s.try_text:
            item["try"] = s.try_text
        out["steps"].append(item)
    return _embed(out)


def release_json(root: str = ROOT) -> str:
    """這一版的號碼、檔名、下載網址 → 放進頁面的 JSON（"version" 排第一個：release.py 的檢查靠它）。"""
    import release
    info = release.download_info(root)
    return _embed({k: info[k] for k in RELEASE_KEYS})


def build(html: str, data: str, release_data=None) -> str:
    if not BLOCK_RE.search(html):
        raise SystemExit("docs/guide/index.html 找不到 <script type=\"application/json\" id=\"tour-steps\">…</script>")
    html = BLOCK_RE.sub(lambda m: m.group(1) + data + m.group(3), html, count=1)
    if release_data is not None:
        if not RELEASE_RE.search(html):
            raise SystemExit("docs/guide/index.html 找不到 <script type=\"application/json\" id=\"release-info\">…</script>")
        html = RELEASE_RE.sub(lambda m: m.group(1) + release_data + m.group(3), html, count=1)
    return html


def shown_version(html: str) -> str:
    """頁面現在寫的是哪一版（release-info 那一段）；沒有回空字串。"""
    m = RELEASE_RE.search(html)
    try:
        return str(json.loads(m.group(2)).get("version", "")) if m else ""
    except ValueError:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只檢查，不改檔")
    args = ap.parse_args(argv)
    with open(GUIDE, encoding="utf-8") as f:
        html = f.read()
    if args.check:
        if build(html, steps_json()) != html:
            print("docs/guide/index.html 的教學步驟跟 basics.json 不同步：跑 python scripts/build_guide.py")
            return 1
        if build(html, steps_json(), release_json()) != html:
            import release
            print(f"提醒：docs/guide/index.html 寫的版本與下載連結是 {shown_version(html) or '（沒有）'}，"
                  f"現在是 {release.current_version(ROOT)}。發版時跑 python scripts/build_guide.py，再重新發佈線上頁面"
                  "（docs/release-playbook.md 第 7 節）。")
        print("ok")
        return 0
    import page_stamp
    new = build(html, steps_json(), release_json())
    if new != html:
        with open(GUIDE, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
    if new != html or page_stamp.check(GUIDE):          # 這兩段有改，或頁面別的地方手改過：重蓋頁面版本
        digest = page_stamp.stamp(GUIDE)
        print(f"wrote docs/guide/index.html（SYNOX {shown_version(new)}，頁面版本 {digest}）：記得重新發佈同一個線上網址")
    else:
        print("already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
