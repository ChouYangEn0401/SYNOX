"""手機驗證器的核心（ADR 0025 §5；計畫 K2）：假時鐘、記憶體／真的保管箱，不開埠。"""

import os

import pytest

from isdtelekit.security import totp

from synox.guard import stepup as stepup_mod
from synox.guard.origin import Origin
from synox.guard.stepup import Refused, StepUp
from synox.guard.store import MemoryStore, VaultStore
from synox.guard.testing import Clock, as_origin, code_for, enroll
from synox.vault import Vault

pytestmark = pytest.mark.usefixtures("no_sockets")

TG = Origin("telegram", 1, surface="telegram")
WEB_A = Origin("web", 1, surface="web:aaaa")
WEB_B = Origin("web", 1, surface="web:bbbb")
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # "12345678901234567890"


class Notes:
    def __init__(self):
        self.sent = []

    def __call__(self, uid, text):
        self.sent.append((uid, text))


def hub(clock=None, notify=None, store=None):
    return StepUp(store or MemoryStore(), owner_id=1, clock=clock or Clock(), notify=notify)


@pytest.mark.parametrize("t,code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                    (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")])
def test_rfc6238_appendix_b_sha1(t, code):
    assert totp.code_at(RFC_SECRET, totp.counter_now(t)) == code


def test_window_one_step_each_side():
    c = Clock()
    assert totp.match(RFC_SECRET, code_for(RFC_SECRET, lambda: c.t - 30), now=c.t) is not None
    assert totp.match(RFC_SECRET, code_for(RFC_SECRET, lambda: c.t + 30), now=c.t) is not None
    assert totp.match(RFC_SECRET, code_for(RFC_SECRET, lambda: c.t - 60), now=c.t) is None
    assert totp.match(RFC_SECRET, code_for(RFC_SECRET, lambda: c.t + 60), now=c.t) is None


def test_begin_confirm():
    c = Clock()
    store = MemoryStore()
    h = hub(c, store=store)
    data = h.begin(1)
    assert data["expires_in"] == 600 and data["uri"].startswith("otpauth://totp/") and data["secret"] in data["uri"]
    with as_origin("web", 1):
        with pytest.raises(Refused) as e:
            h.confirm(1, "000000" if code_for(data["secret"], c) != "000000" else "111111")
        assert e.value.result.code == "bad" and store.load(1) is None
        codes = h.confirm(1, code_for(data["secret"], c))
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(len(x) == 11 and x[5] == "-" for x in codes)
    saved = repr(store.load(1))
    assert not any(x in saved or x.replace("-", "") in saved for x in codes)
    with pytest.raises(ValueError):
        h.begin(1)


def test_begin_expires_after_ten_minutes():
    c = Clock()
    h = hub(c)
    data = h.begin(1)
    c.t += 601
    with as_origin("web", 1), pytest.raises(Refused) as e:
        h.confirm(1, code_for(data["secret"], c))
    assert e.value.result.code == "expired" and not h.enrolled(1)


def test_confirm_from_ai_is_refused():
    c = Clock()
    h = hub(c)
    data = h.begin(1)
    with as_origin("ai", 1), pytest.raises(Refused) as e:
        h.confirm(1, code_for(data["secret"], c))
    assert e.value.result.code == "not_human"


def test_replay_survives_restart_and_old_counter_is_bad():
    c = Clock()
    store = MemoryStore()
    h = hub(c, store=store)
    secret = enroll(h, 1, c)
    code = code_for(secret, c)
    assert h.verify(1, code, origin=TG).ok
    assert h.verify(1, code, origin=TG).code == "replay"
    again = hub(c, store=store)                               # 模擬重開 SYNOX
    assert again.verify(1, code, origin=TG).code == "replay"
    assert again.attempts.count(1) == 0                       # 重放不計次
    old = code_for(secret, lambda: c.t - 30)                  # 前一個時段（比上次用過的舊）
    assert again.verify(1, old, origin=TG).code == "bad"


def test_five_bad_lock_notify_once_then_unlock_after_15_min():
    c = Clock()
    notes = Notes()
    h = hub(c, notify=notes)
    secret = enroll(h, 1, c)
    bad = "000000" if code_for(secret, c) != "000000" else "111111"
    assert [h.verify(1, bad, origin=TG).code for _ in range(5)] == ["bad"] * 5
    assert len([n for n in notes.sent if "連續錯" in n[1]]) == 1
    assert h.verify(1, code_for(secret, c), origin=TG).code == "locked"
    c.t += 15 * 60 + 1
    assert h.verify(1, code_for(secret, c), origin=TG).ok


@pytest.mark.parametrize("kind", ["ai", "schedule", "system", "unknown"])
def test_not_human_does_not_count_and_does_not_pass(kind):
    c = Clock()
    h = hub(c)
    secret = enroll(h, 1, c)
    o = Origin(kind, 1, surface=kind)
    for _ in range(6):
        assert h.verify(1, "000000", origin=o).code == "not_human"
    assert h.attempts.count(1) == 0 and h.attempts.locked(1) == 0
    assert h.unlock(1, code_for(secret, c), origin=o).code == "not_human"
    assert h.verify(1, code_for(secret, c), origin=TG).ok           # 那組碼沒有被用掉


def test_unlock_is_bound_to_the_entry():
    c = Clock()
    h = hub(c)
    secret = enroll(h, 1, c)
    assert h.unlock(1, code_for(secret, c), origin=TG).ok
    assert h.unlocked(1, TG) and not h.unlocked(1, WEB_A)
    c.t += 30
    assert h.unlock(1, code_for(secret, c), origin=WEB_A).ok
    assert h.unlocked(1, WEB_A) and not h.unlocked(1, WEB_B)
    assert h.remaining(1, WEB_A) == 15 * 60
    assert h.lock(1, WEB_A) and not h.unlocked(1, WEB_A) and h.unlocked(1, TG)
    c.t += 15 * 60
    assert not h.unlocked(1, TG)
    assert not h.unlocked(1, Origin("ai", 1, surface="telegram"))      # 不是人：就算 surface 一樣也不算


def test_recovery_codes():
    c = Clock()
    notes = Notes()
    h = hub(c, notify=notes)
    data = h.begin(1)
    with as_origin("web", 1):
        codes = h.confirm(1, code_for(data["secret"], c))
    assert h.verify(1, codes[0], origin=TG).code == "recovery_here"
    assert h.attempts.count(1) == 0
    assert h.verify(1, codes[0].upper().replace("-", ""), origin=WEB_A, allow_recovery=True).ok
    assert h.verify(1, codes[0], origin=WEB_A, allow_recovery=True).code == "bad"
    assert (1, "你用掉了一組備用碼，還剩 9 組。") in notes.sent
    assert h.status(1, WEB_A)["recovery_left"] == 9


def test_protect_toggle_needs_unlock_to_turn_off():
    c = Clock()
    h = hub(c)
    secret = enroll(h, 1, c)
    assert not h.protects_danger(1)
    assert h.set_protect(1, True, origin=TG).ok and h.protects_danger(1)
    assert h.set_protect(1, False, origin=TG).code == "need"
    h.unlock(1, code_for(secret, c), origin=TG)
    assert h.set_protect(1, False, origin=TG).ok and not h.protects_danger(1)
    assert h.set_protect(2, True, origin=TG).code == "unset"


def test_new_recovery_and_disable():
    c = Clock()
    notes = Notes()
    gone = []
    h = hub(c, notify=notes)
    h.on_disable(gone.append)
    secret = enroll(h, 1, c)
    fresh = h.new_recovery(1, code_for(secret, c), origin=WEB_A)
    assert len(fresh) == 10
    with pytest.raises(Refused):
        h.new_recovery(1, code_for(secret, c), origin=WEB_A)          # 同一組碼不能再用
    assert h.disable(1, fresh[0], origin=WEB_A, allow_recovery=False).code == "recovery_here"
    assert h.disable(1, fresh[0], origin=WEB_A).ok
    assert not h.enrolled(1) and gone == [1]
    assert any("關掉了" in t for _u, t in notes.sent)


def test_reset_local():
    c = Clock()
    h = hub(c)
    enroll(h, 1, c)
    h.reset_local(1)
    assert not h.enrolled(1) and h.status(1, TG)["enrolled"] is False


def test_server_mode_real_vault_per_person(tmp_path):
    c = Clock()
    vault = Vault(b"k" * 32, str(tmp_path))
    h = hub(c, store=VaultStore(vault, server_mode=True))
    secret_a = enroll(h, 101, c)
    a, b = Origin("telegram", 101, surface="telegram"), Origin("telegram", 202, surface="telegram")
    assert h.unlock(202, code_for(secret_a, c), origin=b).code == "unset"      # 乙沒設定，不影響甲
    secret_b = enroll(h, 202, c)
    assert secret_a != secret_b
    bad_for_b = code_for(secret_a, c)
    if bad_for_b != code_for(secret_b, c):
        assert h.unlock(202, bad_for_b, origin=b).code == "bad"               # 甲的碼解不了乙
    assert h.attempts.count(202) in (0, 1) and h.attempts.count(101) == 0     # 各自的錯誤次數
    assert h.unlock(101, code_for(secret_a, c), origin=a).ok
    for uid, secret in ((101, secret_a), (202, secret_b)):
        raw = open(vault.for_user(uid).path("stepup"), "rb").read()
        assert secret.encode() not in raw
    assert not os.path.exists(os.path.join(str(tmp_path), "stepup_totp.json"))


def test_personal_mode_vault_is_ciphertext(tmp_path):
    c = Clock()
    vault = Vault(b"k" * 32, str(tmp_path))
    h = hub(c, store=VaultStore(vault, server_mode=False))
    secret = enroll(h, 1, c)
    assert secret.encode() not in open(vault.path("stepup"), "rb").read()
    again = hub(c, store=VaultStore(vault, server_mode=False))
    assert again.enrolled(1) and not again.enrolled(2)


def test_audit_has_no_codes(tmp_path):
    from synox.guard.audit import Audit
    c = Clock()
    audit = Audit(str(tmp_path / "a.jsonl"), clock=c)
    h = StepUp(MemoryStore(), owner_id=1, clock=c, audit=audit)
    secret = enroll(h, 1, c)
    code = code_for(secret, c)
    h.unlock(1, code, origin=TG)
    h.verify(1, "999999", origin=TG)
    raw = open(tmp_path / "a.jsonl", encoding="utf-8").read()
    assert code not in raw and secret not in raw and "999999" not in raw
    events = [r["event"] for r in audit.tail()]
    assert "stepup_enroll" in events and "stepup_unlock" in events


def test_sdk_adapter():
    c = Clock()
    h = hub(c)
    sdk = h.sdk()
    assert not sdk.configured and not sdk.has_factor("A")
    secret = enroll(h, 1, c)
    assert sdk.configured and not sdk.has_factor("B")
    with as_origin("telegram", 1):
        assert not sdk.is_elevated(1)
        ok, _text = sdk.elevate(1, code_for(secret, c))
        assert ok and sdk.is_elevated(1) and sdk.remaining(1) > 0
        assert sdk.drop(1) and not sdk.is_elevated(1)
        c.t += 30
        assert sdk.verify_once(code_for(secret, c))[0]
        assert not sdk.verify_once("123456", factor="B")[0]
    with pytest.raises(NotImplementedError):
        sdk.issue_ticket()
    assert "unlock" in sdk.need_message and "安全" in sdk.unset_message
    assert stepup_mod.TEXT["need"] == sdk.need_message
