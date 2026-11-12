"""產生終端機歡迎畫面的純文字預覽（給人打開看長相，不用開 SYNOX）。

    .venv\\Scripts\\python.exe scripts\\make_cli_welcome.py

寫出 docs/ui/cli-welcome.txt（UTF-8）：UTF-8 終端機看到的版本、Windows 舊主控台（cp950）看到的 ASCII 版本、
`synox run` 這類指令開頭的短版、`TERM=dumb` 的一行版。時間固定在中午、小提示固定第一則，所以每次產生的都一樣。
版面只寫在 src/synox/brand.py 一處；改了就重跑（tests/test_brand.py 會檢查有沒有同步）。顏色在純文字裡看不到。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "ui", "cli-welcome.txt")


def render() -> str:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from synox import brand
    now = datetime(2026, 11, 12, 13, 0)
    tip = brand.TIPS[0].format(prog="synox")
    kw = dict(now=now, prog="synox", ver="X.Y.Z")
    parts = [
        ("`synox`（沒參數）— UTF-8 終端機（Windows Terminal、chcp 65001、macOS／Linux）",
         brand.render_banner(None, unicode=True, tip_text=tip, **kw)),
        ("`synox`（沒參數）— Windows 舊主控台（cp950）或 SYNOX_ASCII=1：純 ASCII logo、不放 emoji",
         brand.render_banner(None, unicode=False, tip_text=tip, **kw)),
        ("`synox run`／`open`／`wizard`／`doctor` 開頭的短版（UTF-8）",
         brand.render_banner("run", unicode=True, **kw)),
        ("TERM=dumb：一行純文字", brand.render_line("open", ver="X.Y.Z", prog="synox")),
    ]
    out = ["SYNOX 終端機歡迎畫面預覽（scripts/make_cli_welcome.py 產生；版本號寫成 X.Y.Z，實際印 synox.__version__）",
           "管線／重導向／CI／--quiet／SYNOX_NO_BANNER=1：完全不印。NO_COLOR：版面一樣、不上色。", ""]
    for title, text in parts:
        out += ["=" * 72, title, "=" * 72, text]
    return "\n".join(out)


def main() -> int:
    text = render()
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(f"寫好了：{OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
