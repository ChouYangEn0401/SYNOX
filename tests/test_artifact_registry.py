"""每一份線上 Artifact 都有本機 HTML 副本，而且頁尾的「線上網址＋頁面版本」對得上內容（擁有者的規則，2026-11-13）。

登記表：docs/artifacts.json（今天起做的頁面）與 docs/artifacts/registry-archive.json（更早的頁面，存在時才檢查）。
頁面改了內容卻沒重蓋頁面版本 → 這裡會失敗：跑 python scripts/page_stamp.py <檔>（介紹頁跑 scripts/make_landing.py），再重新發佈同一個網址。
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import page_stamp  # noqa: E402


def _rows():
    out = []
    with open(os.path.join(ROOT, "docs", "artifacts.json"), encoding="utf-8") as f:
        out += [r for r in json.load(f)["pages"] if r.get("repo") == "SYNOX"]
    archive = os.path.join(ROOT, "docs", "artifacts", "registry-archive.json")
    if os.path.exists(archive):
        with open(archive, encoding="utf-8") as f:
            out += [dict(r, repo="SYNOX") for r in json.load(f)]
    return out


ROWS = _rows()


def test_registry_is_not_empty_and_urls_are_unique():
    urls = [r["url"] for r in ROWS]
    assert urls and len(urls) == len(set(urls))
    assert all(u.startswith("https://claude.ai/artifact/") for u in urls)


@pytest.mark.parametrize("row", ROWS, ids=[r["local"] for r in ROWS])
def test_every_artifact_has_a_local_copy_with_url_and_current_stamp(row):
    path = os.path.join(ROOT, row["local"])
    assert os.path.isfile(path), f"沒有本機副本：{row['local']}（{row['url']}）"
    with open(path, encoding="utf-8") as f:
        html = f.read()
    url_id = row["url"].rsplit("/", 1)[-1].split("#")[0]
    assert url_id in html, f"{row['local']} 頁尾沒有寫線上網址 {row['url']}"
    assert page_stamp.check(path) == "", page_stamp.check(path)
