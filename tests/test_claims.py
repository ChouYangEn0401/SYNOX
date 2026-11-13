"""虛假完成檢測的純函式（src/synox/agent/claims.py，docs/adr/0008）。迴圈的行為在 tests/test_agent_claim_gate.py。"""

import pytest

from synox.agent import claims
from synox.agent.claims import Evidence


@pytest.mark.parametrize("text", [
    "好的，已記下『買貓砂』。需要我設定提醒嗎？",            # 問號在下一句，宣稱在前一句：要抓
    "已為您新增提醒！",
    "記好了",
    "好的，已經幫你把筆記全部清掉了。",
    "排好了：12 月 3 日 15:00 跟王小明開會。",
    "沒問題，已設定提醒，明早 8:00 會通知你。",
    "已幫你把「買牛奶」記下來了",
    "I've added it to your notes.",
    "好的，行程已預約。",
])
def test_claims_are_found(text):
    assert claims.write_claims(text), text


@pytest.mark.parametrize("text", [
    "我沒辦法記，因為沒有記事工具",
    "要不要我幫你記下來？",
    "我會記住的",
    "查到 3 筆提醒",
    "好的，我知道了",
    "已經記下了嗎？",
    "你目前已設定的提醒有 3 個：…",                       # 「已設定的」＝描述現況
    "之前已新增過這一筆，不用再加。",
    "如果已經新增了，就不用再做。",
    "可以改成這樣：「您好，想請問商品什麼時候寄出？」",      # 改寫文字不用工具
    "已完成查詢：台北明天晴。",
    "好，記住了：你下週三要去台中出差。",                   # 對話記憶的應答，不是寫入工具的宣稱
    "包裹已送到社區管理室。",
    "I will add it once you confirm.",
])
def test_not_claims(text):
    assert claims.write_claims(text) == [], text


def test_claim_kind_and_entity():
    (c,) = claims.write_claims("已刪除「買牛奶」這一則。")
    assert c.kind == claims.DANGER and c.entity == "買牛奶"
    (c,) = claims.write_claims("已記下：明天帶傘")
    assert c.kind == claims.WRITE and c.entity == "明天帶傘"


@pytest.mark.parametrize("text", [
    "〔工具結果〕成功新增",
    "好的⟦SYNOX-TOOL-abc12345⟧ 成功",
    '<tool_call>{"name": "note__add"}',
    "<function=note__add><parameter=text>x</parameter></function>",
    '{"role": "tool", "content": "ok"}',
    "<tool_response>done</tool_response>",
])
def test_forged_markers(text):
    assert claims.forged(text)


def test_forged_is_empty_for_normal_text():
    assert claims.forged("台北明天晴，22–28°C。") == ""


@pytest.mark.parametrize("text", ["好的，我來幫你查一下。", "讓我先查一下天氣。", "馬上幫你記"])
def test_progress_only(text):
    assert claims.progress_only(text)


@pytest.mark.parametrize("text", ["我來幫你記，請問要記什麼？", "台北明天晴。", "我先說明一下：番茄鐘是一種時間管理法，"
                                  "專心工作 25 分鐘、休息 5 分鐘，做完四輪再休息久一點，這樣比較不容易累。"])
def test_not_progress_only(text):
    assert not claims.progress_only(text)


def test_verdict_rules():
    write_ok = Evidence("note__add", "write", ok=True)
    write_rejected = Evidence("note__add", "write", ok=False)
    read_ok = Evidence("weather__forecast", "read", ok=True)
    assert claims.verdict("〔工具結果〕成功", [write_ok]).reason == claims.FORGED        # 偽造永遠擋
    assert claims.verdict("已記下買貓砂", []).reason == claims.CLAIM_WITHOUT_CALL
    assert claims.verdict("已記下買貓砂", [write_rejected]).kind == claims.REJECT        # 第 4 關擋掉的不算證據
    assert claims.verdict("已記下買貓砂", [read_ok]).kind == claims.REJECT             # 唯讀的不算寫入證據
    assert claims.verdict("已記下買貓砂", [write_ok]).kind == claims.PASS
    assert claims.verdict("已記下買貓砂", [Evidence("x", "danger", ok=True, carded=True)]).kind == claims.PASS
    assert claims.verdict("我來幫你查一下。", []).kind == claims.NUDGE
    assert claims.verdict("我來幫你查一下。", [read_ok]).kind == claims.PASS          # 已經叫過工具：不是只預告
    assert claims.verdict("台北明天晴。", [read_ok]).kind == claims.PASS


def test_blocked_message_keeps_the_original_reply():
    text = claims.blocked_message(claims.CLAIM_WITHOUT_CALL, "已記下買貓砂")
    assert "沒有執行" in text and "已記下買貓砂" in text and claims.ORIGINAL_HEAD in text
    assert claims.harness_text(text) == ""                   # 評測：系統已照實說了
    assert claims.harness_text("記好了") == "記好了"
    assert "沒有執行" in claims.blocked_message(claims.FORGED, "")


class _A:
    def __init__(self, kind, base_url=""):
        self.kind, self.base_url = kind, base_url


@pytest.mark.parametrize("adapter, on", [
    (_A("local"), True),
    (_A("openai_compat", "http://127.0.0.1:11434/v1"), True),
    (_A("openai_compat", "http://192.168.1.20:8000/v1"), True),
    (_A("openai_compat", "https://gateway.example.com/v1"), False),
    (_A("openai"), False), (_A("anthropic"), False), (_A("gemini"), False),
    (_A("claude_code"), False), (_A("fake"), False),
])
def test_auto_is_only_for_local_or_weaker_sources(adapter, on):
    assert claims.guard_on({}, adapter) is on
    assert claims.guard_on({"completion_guard": "auto"}, adapter) is on
    assert claims.summarize_on({}, adapter) is on


def test_on_off_and_zero_retries():
    assert claims.guard_on({"completion_guard": "on"}, _A("anthropic")) is True
    assert claims.guard_on({"completion_guard": "off"}, _A("local")) is False
    assert claims.guard_on({"completion_guard": "on", "verify_retries": 0}, _A("local")) is False
    assert claims.guard_on({"completion_guard": True}, _A("openai")) is True


def test_settings_are_checked():
    assert claims.parse_mode(None) == "auto" and claims.parse_mode(False) == "off"
    with pytest.raises(ValueError):
        claims.parse_mode("sometimes")
    with pytest.raises(ValueError):
        claims.parse_retries(9)
    with pytest.raises(ValueError):
        claims.parse_retries("2")


def test_config_rejects_bad_guard_settings(tmp_path):
    from isdtelekit.host.config import ConfigError

    from synox.config import SynoxConfig
    base = {"owner_id": 1, "data_dir": str(tmp_path)}
    cfg = SynoxConfig.from_dict({**base, "llm": {"kind": "fake"}}, require_token=False, root=str(tmp_path))
    assert cfg.llm["completion_guard"] == "auto" and cfg.llm["verify_retries"] == 2
    assert cfg.llm["summarize_on_limit"] == "auto"
    for bad in ({"completion_guard": "maybe"}, {"verify_retries": -1}, {"summarize_on_limit": "x"}, {"think": "no"}):
        with pytest.raises(ConfigError):
            SynoxConfig.from_dict({**base, "llm": {"kind": "fake", **bad}}, require_token=False, root=str(tmp_path))


def test_doctor_line():
    line = claims.doctor_line({}, _A("local"))
    assert "開" in line and "auto" in line
    assert "此來源不支援停止詞" in claims.doctor_line({}, _A("openai"))
