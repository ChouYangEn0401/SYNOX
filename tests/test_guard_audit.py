"""門禁核心：安全紀錄（ADR 0025 §4）。只收數字的額外欄位、換檔、沒有自由文字。"""

import json
import os

import pytest

from synox.guard.audit import Audit

pytestmark = pytest.mark.usefixtures("no_sockets")

SPECIAL = "ZZ-秘密-‮-123456"


def test_only_numbers_and_identifiers(tmp_path):
    path = str(tmp_path / "security_audit.jsonl")
    a = Audit(path, clock=lambda: 5.0)
    a.write("stepup_fail", by=42, origin="telegram", target=SPECIAL, ok=False, code="bad", tries=3,
            note=SPECIAL, flag=True)
    a.write(SPECIAL, code=SPECIAL + "\n{\"event\":\"fake\"}")
    raw = open(path, encoding="utf-8").read()
    assert SPECIAL not in raw and "秘密" not in raw and "fake" not in raw
    rows = a.tail()
    assert rows[0] == {"t": 5.0, "event": "stepup_fail", "by": 42, "origin": "telegram", "target": "?", "ok": False,
                       "code": "bad", "tries": 3}
    assert rows[1]["event"] == "?" and rows[1]["code"] == "?"
    assert all(len(line.splitlines()) == 1 for line in raw.splitlines(True))


def test_rotates_at_limit_keeps_one(tmp_path):
    path = str(tmp_path / "a.jsonl")
    a = Audit(path, max_bytes=400)
    for i in range(30):
        a.write("e", n=i)
    assert os.path.exists(path + ".1") and not os.path.exists(path + ".2")
    assert os.path.getsize(path) <= 400
    assert json.loads(open(path).read().splitlines()[-1])["n"] == 29


def test_unwritable_does_not_raise(tmp_path):
    folder = tmp_path / "x"
    folder.write_text("file, not a folder")
    Audit(str(folder / "a.jsonl")).write("e")
