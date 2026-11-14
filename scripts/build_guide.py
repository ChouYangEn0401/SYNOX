"""把內建新手教學的步驟（src/synox/tour/tours/basics.json）放進一步一步安裝教學頁（docs/guide/index.html）。

    python scripts/build_guide.py           # 改寫 docs/guide/index.html 裡 <script type="application/json" id="tour-steps"> 那一段
    python scripts/build_guide.py --check   # 只檢查有沒有同步（tests/test_build_guide.py 用；沒同步＝退出碼 1）

同一份字、兩個出口（docs/lab/2026-11-13-onboarding-help-aliases-plan.md §3.5，G1）：SYNOX 網頁裡的 /tutorial 在真的畫面上指給人看；
安裝教學頁把同一份步驟當成「選讀：SYNOX 網頁導覽」那一段（示意畫面上的位置用同一份位置名字，synox/tour/anchors.py）。
改教學的字只改 basics.json，再跑這支（然後 python scripts/page_stamp.py docs/guide/index.html 重蓋頁面版本、重新發佈同一個網址）。

只用標準函式庫＋SYNOX 自己的步驟檔檢查（synox.tour.schema）：不合格的步驟檔不會被放進頁面。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

GUIDE = os.path.join(ROOT, "docs", "guide", "index.html")
TOUR = os.path.join(ROOT, "src", "synox", "tour", "tours", "basics.json")
BLOCK_RE = re.compile(r'^(<script type="application/json" id="tour-steps">)(.*?)(</script>)', re.S | re.M)   # 一行的開頭


def steps_json(path: str = TOUR) -> str:
    """教學（擁有者看到的那一份步驟）→ 放進頁面的 JSON（不會提早結束 <script>）。"""
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
    text = json.dumps(out, ensure_ascii=False, indent=1)
    return "\n" + text.replace("</", "<\\/").replace("<!--", "<\\!--") + "\n"


def build(html: str, data: str) -> str:
    if not BLOCK_RE.search(html):
        raise SystemExit("docs/guide/index.html 找不到 <script type=\"application/json\" id=\"tour-steps\">…</script>")
    return BLOCK_RE.sub(lambda m: m.group(1) + data + m.group(3), html, count=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只檢查，不改檔")
    args = ap.parse_args(argv)
    with open(GUIDE, encoding="utf-8") as f:
        html = f.read()
    new = build(html, steps_json())
    if args.check:
        if new != html:
            print("docs/guide/index.html 的教學步驟跟 basics.json 不同步：跑 python scripts/build_guide.py")
            return 1
        print("ok")
        return 0
    if new != html:
        with open(GUIDE, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        print("wrote docs/guide/index.html（記得 python scripts/page_stamp.py docs/guide/index.html）")
    else:
        print("already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
