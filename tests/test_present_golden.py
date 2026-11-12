"""呈現層的黃金檔案：tests/fixtures/present/<案例>/source.md → blocks.json、telegram.json、discord.json、web.html。

輸出改了而且確定是對的：`SYNOX_UPDATE_GOLDEN=1` 再跑這個檔就會重產（docs/presentation.md「黃金檔案」）。
每個案例也跑一次不變量（長度、標籤成對、白名單、沒有未跳脫的 <、非 system 產生不出按鈕）。"""

import pytest

from present_checks import OUTPUTS, UPDATE, cases, check_all, outputs, read, trust_of, write

from synox import present

CASES = cases()


def test_there_are_enough_cases():
    assert len(CASES) >= 19


@pytest.mark.parametrize("case", CASES)
def test_golden(case):
    got = outputs(case)
    assert set(got) == set(OUTPUTS)
    for name, text in got.items():
        if UPDATE:
            write(case, name, text)
            continue
        try:
            want = read(case, name)
        except FileNotFoundError:
            pytest.fail(f"{case}/{name} 不存在：SYNOX_UPDATE_GOLDEN=1 產生")
        assert text == want, f"{case}/{name} 跟黃金檔不一樣；確定新的是對的就用 SYNOX_UPDATE_GOLDEN=1 重產"


@pytest.mark.parametrize("case", CASES)
def test_invariants(case):
    doc = present.document(read(case, "source.md"), trust=trust_of(case))
    check_all(doc)
    for trust in present.blocks.TRUSTS:                 # 同一份字用每一種信任等級都要守
        check_all(present.document(read(case, "source.md"), trust=trust))
