"""替單一檔案的網頁（Artifact 的本機副本）蓋「頁面版本」：給開發者比對線上版和本機版是不是同一份。

    python scripts/page_stamp.py docs/installer/spec.html [--online https://claude.ai/artifact/…]

頁面裡要有一個 <span data-stamp>…</span>；--online 會把頁面裡的 ONLINE_URL 換成網址。
頁面版本＝把 data-stamp 裡的字清空後整頁的 sha256 前 10 碼＋今天日期。線上版、本機版一樣＝同一份。只用標準函式庫。
（docs/landing 由 scripts/make_landing.py 自己蓋；SYNOX_Libs 的 docs/site 用那邊的 scripts/site_stamp.py。）
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import sys

STAMP = re.compile(r"(<span data-stamp>)(.*?)(</span>)", re.S)


def stamp(path: str, online: str = "") -> str:
    with open(path, encoding="utf-8") as f:
        html = f.read()
    if online:
        html = html.replace("ONLINE_URL", online)
    if len(STAMP.findall(html)) != 1:
        raise SystemExit(f"{path}：要剛好有一個 <span data-stamp>…</span>")
    digest = hashlib.sha256(STAMP.sub(r"\1\3", html).encode("utf-8")).hexdigest()[:10]
    html = STAMP.sub(lambda m: f"{m.group(1)}{digest} · {datetime.date.today().isoformat()}{m.group(3)}", html)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    return digest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="替網頁蓋頁面版本")
    ap.add_argument("path")
    ap.add_argument("--online", default="", help="線上版網址（取代頁面裡的 ONLINE_URL）")
    a = ap.parse_args(argv)
    print(f"{a.path}: {stamp(a.path, a.online)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
