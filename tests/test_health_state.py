# -*- coding: utf-8 -*-
"""隔離清單的狀態機與 HealthRegistry（src/synox/health/state.py、__init__.py）、設定（settings.py）：
門檻、input／user 不算、工具自報立刻標壞、冷卻序列、好壞反覆→隔離、只有解除能放出來、試用每日上限、設定關掉不記。
存檔在 test_health_store.py。假時鐘，不碰檔案。"""
import pytest

from synox.config import ConfigError, SynoxConfig
from synox.health import BROKEN, HEALTHY, NEEDS_ACTION, QUARANTINED, HealthRegistry
from synox.health import failure as F
from synox.health import settings as hs

TOOL = "demo.price"


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def fail(code="upstream_unavailable", reason="服務 503", **block):
    env = {"ok": False, "error": reason, "code": code}
    if block:
        env["failure"] = {"v": 1, **block}
    return F.normalize(env)


def reg(clock=None, store=None, **settings):
    return HealthRegistry({**hs.defaults(), **settings}, store, clock=clock or Clock())


def test_three_in_a_row_with_the_same_root_cause_breaks():
    r = reg()
    declared = dict(scope="tool")                                     # 有合約（failure 物件）的工具：門檻 3
    for _ in range(2):
        r.record_failure(TOOL, fail(**declared), pack="demo")
    assert r.hidden(TOOL) is None
    entry = r.record_failure(TOOL, fail(**declared), pack="demo")
    assert entry.state == BROKEN and r.hidden(TOOL) is entry and entry.next_check == r.clock() + 300


def test_numbers_paths_and_times_do_not_change_the_root_cause():
    r = reg()
    for i, reason in enumerate(("讀 C:\\data\\a1.json 第 12 行失敗", "讀 /srv/x/b2.json 第 99 行失敗", "讀 D:\\q.json 第 3 行失敗")):
        r.record_failure(TOOL, fail(reason=reason, scope="tool"), pack="demo")
    assert r.hidden(TOOL) is not None
    r2 = reg()
    for reason in ("A 壞了", "B 壞了", "C 壞了"):                    # 不同的根因：連續數歸零
        r2.record_failure(TOOL, fail(reason=reason, scope="tool"), pack="demo")
    assert r2.hidden(TOOL) is None


def test_success_resets_the_streak_and_window_counts_too():
    clock = Clock()
    r = reg(clock)
    for _ in range(4):
        clock.now += 360
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
        r.record_success(TOOL)                                        # 兩次就成功一次：連續永遠不到 3 次
    assert r.hidden(TOOL) is None                                     # 10 分鐘內也只有 4 次
    r = reg(clock)                                                    # 時好時壞：10 分鐘內 5 次（中間有成功也算）
    for step in ("f", "f", "s", "f", "f", "s", "f"):
        clock.now += 60
        if step == "f":
            r.record_failure(TOOL, fail(scope="tool"), pack="demo")
        else:
            r.record_success(TOOL)
    assert r.hidden(TOOL).state == BROKEN


def test_untrusted_tools_break_after_two():
    r = reg()
    r.record_failure(TOOL, fail(), pack="demo", untrusted=True)       # 沒有合約（舊信封）／匯入的工具
    r.record_failure(TOOL, fail(), pack="demo", untrusted=True)
    assert r.hidden(TOOL).state == BROKEN


def test_input_and_user_scopes_do_not_count():
    r = reg()
    for _ in range(10):
        r.record_failure(TOOL, fail("bad_input", "參數不對"), pack="demo", untrusted=True)
        r.record_failure(TOOL, fail("not_found", "沒有"), pack="demo", untrusted=True)
        r.record_failure(TOOL, fail("permission_denied", "不給"), pack="demo", user=7, untrusted=True)
        r.record_failure(TOOL, fail("rate_limited", "慢一點"), pack="demo", untrusted=True)
    assert r.hidden(TOOL) is None and r.hidden(TOOL, 7) is None and r.hidden(TOOL, 8) is None


def test_self_reported_needs_config_is_needs_action_at_once():
    r = reg()
    entry = r.record_failure(TOOL, fail("needs_config", "還沒設定城市"), pack="demo")
    assert entry.state == NEEDS_ACTION and entry.next_check is None
    assert r.due() == []                                              # 不自動檢查
    entry = r.record_failure("demo.other", fail("upstream_changed", "改版", remedy={"kind": "needs_update"}), pack="demo")
    assert entry.state == NEEDS_ACTION
    off = reg(trust_self_report=False)                                # 可以關掉「立刻相信」
    assert off.record_failure(TOOL, fail("needs_config", "x"), pack="demo").state == HEALTHY
    synth = F.from_text("找不到 tool.exe", "dependency_missing")        # SYNOX 推的（不是工具自己說的）不算自報
    assert reg().record_failure(TOOL, synth, pack="demo").state == HEALTHY


def test_user_scope_lives_on_that_person_only():
    r = reg()
    entry = r.record_failure(TOOL, fail("auth_expired", "你的 token 過期了"), pack="demo", user=7)
    assert entry.state == NEEDS_ACTION and entry.key == f"{TOOL}@7"
    assert r.hidden(TOOL, 7) is entry and r.hidden(TOOL, 8) is None and r.hidden(TOOL) is None
    r.record_success(TOOL, 7)                                         # 他自己手動成功一次＝通過
    assert r.hidden(TOOL, 7) is None


def test_cooldowns_grow_and_flapping_quarantines():
    clock = Clock()
    r = reg(clock)
    for _ in range(3):
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
    entry = r.entry(TOOL)
    assert entry.state == BROKEN and entry.next_check == clock.now + 300
    clock.now += 301
    assert r.due() == [entry]
    r.check_result(entry, False)                                      # 自我檢查沒過：下一段冷卻（900）
    assert entry.state == BROKEN and entry.next_check == clock.now + 900
    clock.now += 901
    r.check_result(entry, True)                                       # 過了：放回
    assert entry.state == HEALTHY and r.hidden(TOOL) is None
    for _ in range(3):                                                # 第二次壞掉：從比較長的冷卻開始
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
    assert entry.state == BROKEN and entry.next_check == clock.now + 900
    r.check_result(entry, True)
    for _ in range(3):                                                # 24 小時內第三次壞掉 → 隔離
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
    assert entry.state == QUARANTINED and entry.next_check is None and r.due() == []
    r.record_success(TOOL)                                            # 成功也不會自己解除
    assert entry.state == QUARANTINED and r.hidden(TOOL) is entry
    assert r.release(TOOL) and entry.state == HEALTHY and entry.breaks == []
    assert not r.release("nope.tool")


def test_trials_for_tools_without_self_check_have_a_daily_cap():
    clock = Clock()
    r = reg(clock, daily_trials=2)
    for _ in range(3):
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")
    entry = r.entry(TOOL)
    for n in range(2):
        clock.now = entry.next_check + 1
        assert r.due() == [entry] and r.start_trial(entry)
        assert entry.trial and r.hidden(TOOL) is None                 # 試用中：放回清單一次
        r.record_failure(TOOL, fail(scope="tool"), pack="demo")       # 試用失敗：下一段冷卻
        assert not entry.trial and entry.state == BROKEN and r.hidden(TOOL) is entry
    clock.now = entry.next_check + 1
    assert not r.start_trial(entry) and r.hidden(TOOL) is entry       # 今天用完了：往後延到最早那次滿 24 小時
    assert entry.next_check == min(entry.trials) + 86400
    clock.now = entry.next_check + 1
    assert r.start_trial(entry)
    r.record_success(TOOL)                                            # 試用成功＝放回
    assert entry.state == HEALTHY and not entry.trial


def test_disabled_registry_never_hides():
    r = reg(enabled=False)
    for _ in range(5):
        r.record_failure(TOOL, fail("needs_config", "x"), pack="demo")
    assert r.hidden(TOOL) is None and r.entries == {} and r.due() == []


# ── 設定 ──────────────────────────────────────────────────────────────

def test_settings_defaults_and_checks(tmp_path):
    cfg = SynoxConfig.from_dict({"owner_id": 1, "data_dir": str(tmp_path)}, require_token=False, root=str(tmp_path))
    assert cfg.health == hs.DEFAULT_HEALTH and cfg.health["cooldowns_s"] == [300, 900, 3600, 21600, 86400]
    assert (cfg.health["consecutive"], cfg.health["window_count"], cfg.health["window_s"]) == (3, 5, 600)
    assert (cfg.health["untrusted_consecutive"], cfg.health["flip_limit"], cfg.health["daily_trials"]) == (2, 3, 4)
    assert cfg.health["prompt_lines"] == 5 and cfg.health["trust_self_report"] is True
    custom = hs.parse({"consecutive": 4, "cooldowns_s": [60, 60, 120]})
    assert custom["consecutive"] == 4 and custom["cooldowns_s"] == [60, 60, 120] and custom["window_count"] == 5
    for bad, word in (({"consecutive": 0}, "consecutive"), ({"enabled": "yes"}, "enabled"),
                      ({"cooldowns_s": [900, 300]}, "cooldowns_s"), ({"cooldowns_s": []}, "cooldowns_s"),
                      ({"typo": 1}, "typo"), ("on", "health"), ({"prompt_lines": True}, "prompt_lines")):
        with pytest.raises(hs.HealthConfigError) as e:
            hs.parse(bad)
        assert word in str(e.value)
    with pytest.raises(ConfigError) as e:
        SynoxConfig.from_dict({"owner_id": 1, "data_dir": str(tmp_path), "health": {"window_s": 1}},
                              require_token=False, root=str(tmp_path))
    assert "health.window_s" in str(e.value)
