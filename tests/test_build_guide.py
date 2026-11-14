# -*- coding: utf-8 -*-
"""一步一步安裝教學頁（docs/guide/index.html）的「選讀：SYNOX 網頁導覽」讀的是內建新手教學的步驟檔
（src/synox/tour/tours/basics.json；scripts/build_guide.py 放進頁面）：同一份字、兩個出口。不連網、不開瀏覽器。"""
import json
import os
import re
import sys

from synox.config import ROOT
from synox.tour import anchors

sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_guide  # noqa: E402

GUIDE = os.path.join(ROOT, "docs", "guide", "index.html")


def _html():
    with open(GUIDE, encoding="utf-8") as f:
        return f.read()


def test_guide_is_in_sync_with_the_tutorial():
    assert build_guide.main(["--check"]) == 0, "跑 python scripts/build_guide.py（再 scripts/page_stamp.py）"


def test_embedded_steps_are_data_and_cannot_break_out():
    html = _html()
    block = build_guide.BLOCK_RE.search(html).group(2)
    assert "</" not in block and "<!--" not in block
    data = json.loads(block)
    assert data["id"] == "basics" and data["steps"]
    ids = [s["id"] for s in data["steps"]]
    assert "ask-help" in ids and "catalog" in ids                    # 擁有者看到的那一份（含裝工具的步驟）


def test_every_anchor_in_the_tutorial_has_a_place_on_the_guide_mock():
    html = _html()
    mock = html[html.index('"web-tour": function'):html.index('"tg-help": function')]
    data = json.loads(build_guide.BLOCK_RE.search(html).group(2))
    used = {a for s in data["steps"] for a in s["anchors"]}
    drawn = set(re.findall(r'data-hl="([a-z.]+)"', mock))
    drawn |= {f"nav.{n}" for n in ("chat", "tools", "settings")}
    drawn |= {f"settings.tab.{t}" for t in ("ai", "channels", "packs", "system", "commands", "help")}
    assert used <= drawn, used - drawn
    assert used <= set(anchors.ANCHORS)


def test_help_step_describes_the_new_help():
    html = _html()
    step = html[html.index('{ id: "help"'):html.index('{ id: "done"')]
    assert "每個工具一顆按鈕" in step and "/help all" in step and "下一頁" not in step
    assert 'jump: { to: "web-welcome"' in step
