"""攻擊清單（docs/security/web-threats.md）跟測試對得上：裡面每個反引號裡的 `tests/…::…` 都真的存在；每一列「已做」至少點名一個測試。"""

import ast
import os
import re

import pytest

pytestmark = pytest.mark.usefixtures("no_sockets")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "security", "web-threats.md")
REF = re.compile(r"`(tests/[A-Za-z0-9_/]+\.py)::([A-Za-z0-9_]+)`")


def rows():
    text = open(DOC, encoding="utf-8").read()
    table = text.split("| # | 攻擊 |", 1)[1].split("\n## ", 1)[0]
    return [line for line in table.splitlines() if re.match(r"^\| \d+b? \|", line)]


def _tests_in(path):
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}


def test_every_named_test_exists():
    refs = REF.findall(open(DOC, encoding="utf-8").read())
    assert len(refs) >= 30
    for path, name in refs:
        assert os.path.isfile(os.path.join(ROOT, path)), path
        assert name in _tests_in(path), f"{path}::{name}"


def test_every_done_row_names_a_test():
    done = [r for r in rows() if "已做" in r.rsplit("|", 2)[-2]]
    assert len(done) >= 20
    for r in done:
        assert REF.search(r), r[:60]
