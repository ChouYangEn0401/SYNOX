"""電腦提醒視窗與提醒哨兵（ADR 0029 §3.4–3.5；synox/notify/desk.py、synox/remindwin/）：資料夾裡的小檔案往返、
OS 獨占鎖（兩個只有一個拿得到）、讓位、哨兵一步一步（假的引擎）、啟動檔（假的資料夾）、視窗的邏輯（不開視窗）、
畫面只做 import 與語法檢查。不開埠、不開子程序、不開視窗、不碰真的啟動資料夾。"""

import ast
import json
import logging
import os
from datetime import datetime

import pytest

from synox.notify import desk
from synox.notify.delivery import ActionOutcome
from synox.notify.deskapp import DeskService, EngineGate
from synox.remindwin import launcher, logic, sentinel

pytestmark = pytest.mark.usefixtures("no_sockets", "no_subprocess")

OCC = "2026-11-16T00:51:00+08:00"


def card(token=None, rid=3, occ=OCC, text="倒垃圾", uid=1001, **kw):
    return desk.ShowCard(token=token or desk.make_token(uid, rid, occ), uid=uid, rid=rid, occurrence=occ, text=text,
                         when="今天 00:51", **kw)


# ── spool ─────────────────────────────────────────────────────────────

def test_spool_round_trip_and_who_deletes_what(tmp_path):
    spool = desk.spool_at(str(tmp_path))
    c = card()
    spool.put_show(c)
    spool.put_close(desk.CloseCard(token="1001-9-202611160800", note="✅ 在 Telegram 上做完了"))
    spool.put_todos(desk.TodoList(1001, [{"rid": i, "text": f"待辦 {i}"} for i in range(30)]))
    to_win = tmp_path / desk.FOLDER / desk.DESK / desk.TO_WIN
    assert sorted(os.listdir(to_win)) == ["close-1001-9-202611160800.json", "show-1001-3-202611160051.json",
                                          "todos-1001.json"]                              # 沒有留下 .tmp
    got = spool.pending_for_win()
    assert [type(x).__name__ for x in got] == ["CloseCard", "ShowCard"] and got[1].text == "倒垃圾"
    assert len(spool.todos_for_win(1001)[0].items) == desk.TODO_SHOW
    spool.put_shown(desk.ShownAck(token=c.token, at=1.0))
    spool.put_action(desk.DeskAction(token=c.token, rid=3, occurrence=OCC, action="done", at=2.0))
    (tmp_path / desk.FOLDER / desk.DESK / desk.FROM_WIN / ".act-half.json.tmp").write_text("{", encoding="utf-8")
    taken = spool.take_from_win()
    assert [type(x).__name__ for x in taken] == ["ShownAck", "DeskAction"]
    assert os.listdir(tmp_path / desk.FOLDER / desk.DESK / desk.FROM_WIN) == [".act-half.json.tmp"]   # 讀完刪；寫一半的不碰
    assert spool.take_from_win() == []
    spool.drop_show(c.token)
    assert not spool.has_show(c.token)


def test_broken_files_are_dropped_and_logged_without_content(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr(desk.logging, "warning", lambda m, *a: logged.append(m % a))
    spool = desk.spool_at(str(tmp_path))
    from_win = tmp_path / desk.FOLDER / desk.DESK / desk.FROM_WIN
    from_win.mkdir(parents=True)
    (from_win / "act-x-1.json").write_text("{秘密的提醒內容", encoding="utf-8")
    (from_win / "act-y-2.json").write_text(json.dumps({"type": "action", "token": "../../evil", "rid": 1,
                                                       "occurrence": "", "action": "done", "at": 1}), encoding="utf-8")
    assert spool.take_from_win() == [] and os.listdir(from_win) == []
    assert len(logged) == 2 and not any("秘密" in line for line in logged)


# ── 鎖與讓位 ─────────────────────────────────────────────────────────

def test_only_one_engine_lock_and_it_frees_on_release(tmp_path):
    a, b = desk.engine_lock_at(str(tmp_path)), desk.engine_lock_at(str(tmp_path))
    assert a.try_acquire(desk.WHO_APP) and not b.try_acquire(desk.WHO_SENTINEL)
    stamp = b.holder()                                                    # 拿著鎖的時候，別人讀得到 stamp
    assert stamp.who == desk.WHO_APP and stamp.pid == os.getpid()
    a.beat()
    a.release()
    assert b.try_acquire(desk.WHO_SENTINEL) and b.holder().who == desk.WHO_SENTINEL
    b.release()
    single = desk.sentinel_lock_at(str(tmp_path))
    assert single.try_acquire() and not desk.sentinel_lock_at(str(tmp_path)).try_acquire()
    assert not desk.sentinel_lock_at(str(tmp_path)).free()
    single.release()
    assert desk.popup_lock_at(str(tmp_path)).free()


class FakeEngine:
    def __init__(self):
        self.ticks = 0
        self.acts = []

    def tick(self, now=None):
        self.ticks += 1
        return []

    def act(self, uid, rid, occurrence, action, *, until=None, typed="", via=""):
        self.acts.append((uid, rid, occurrence, action, until, typed, via))
        return ActionOutcome(ok=True, note="✅ 在電腦上做完了")

    def on_delivery(self, *a):
        pass


class FakeOutbox:
    def __init__(self):
        self.pumps = 0
        self.resolved = []

    def pump(self, now=None):
        self.pumps += 1
        return []

    def find(self, uid, channel, field, value):
        return None

    def resolve(self, uid, key, *, note="", via=""):
        self.resolved.append((uid, key, note, via))


def make_sentinel(tmp_path):
    built = []

    def build():
        engine = FakeEngine()
        r = sentinel.Round(engine=engine, outbox=FakeOutbox(), desk=DeskService(str(tmp_path), owner_id=1001),
                           actions=engine)
        built.append(r)
        return r
    return sentinel.Sentinel(str(tmp_path), build=build), built


def test_sentinel_runs_engine_when_app_is_closed_and_yields_when_it_opens(tmp_path):
    s, built = make_sentinel(tmp_path)
    t = 1_000_000.0
    assert s.step(t) == "engine" and s.is_engine and built[0].engine.ticks == 1 and built[0].outbox.pumps == 1
    assert s.step(t + 2) == "engine" and built[0].engine.ticks == 1               # 15 秒一輪
    assert s.step(t + 15) == "engine" and built[0].engine.ticks == 2
    gate = EngineGate(str(tmp_path), clock=lambda: t + 20)
    assert gate.start() is False and desk.yield_requested(str(tmp_path)) is not None   # 主程式開起來：拿不到 → 請讓位
    desk.spool_at(str(tmp_path)).put_action(desk.DeskAction(token=desk.make_token(1001, 3, OCC), rid=3,
                                                            occurrence=OCC, action="done", at=t + 19))
    assert s.step(t + 20) == "yielded" and not s.is_engine
    assert built[0].engine.acts and built[0].engine.ticks == 2                    # 做完這一輪（視窗的回覆）才讓
    assert desk.yield_requested(str(tmp_path)) is None
    assert gate.check(t + 25) and gate.mine                                        # 主程式拿到了
    assert s.step(t + 60) == "waiting"
    gate.stop()                                                                    # 主程式關掉 → 哨兵 30 秒內接手
    assert s.step(t + 90) == "engine" and len(built) == 2                          # 重新組一份（快取重讀）
    s.release()


def test_sentinel_does_not_grab_while_app_is_asking(tmp_path):
    s, _ = make_sentinel(tmp_path)
    desk.request_yield(str(tmp_path), at=1_000_000.0)
    assert s.step(1_000_010.0) == "waiting" and not s.is_engine
    assert s.step(1_000_000.0 + sentinel.STALE_YIELD_S + sentinel.LOCK_TRY_S) == "engine"   # 主程式沒來拿：過期的請求不管
    s.release()


def test_sentinel_handles_window_actions_within_one_step(tmp_path):
    s, built = make_sentinel(tmp_path)
    t = 1_000_000.0
    s.step(t)
    model = logic.DeskModel(desk.spool_at(str(tmp_path)))
    desk.spool_at(str(tmp_path)).put_show(card())
    model.poll()
    token = desk.make_token(1001, 3, OCC)
    assert model.act(token, desk.BTN_SNOOZE_10, now=t)[0]
    s.step(t + sentinel.STEP_S)                                                    # 哨兵每 2 秒看一次視窗的回覆
    uid, rid, occ, action, until, typed, via = built[0].engine.acts[-1]
    assert (uid, rid, occ, action, via) == (1001, 3, OCC, "snooze", "desktop") and until
    assert built[0].outbox.resolved[0][3] == "desktop"
    assert not desk.spool_at(str(tmp_path)).has_show(token)
    s.release()


def test_sentinel_build_failure_releases_the_lock(tmp_path):
    def boom():
        raise NotImplementedError("engine not ready")
    s = sentinel.Sentinel(str(tmp_path), build=boom)
    assert s.step(1.0) == "error" and not s.is_engine
    assert desk.engine_lock_at(str(tmp_path)).try_acquire()


# ── 登入時啟動（假的資料夾）──────────────────────────────────────────

def test_autostart_goes_only_into_the_given_folder(tmp_path):
    folder = tmp_path / "Startup"
    command, cwd = launcher.sentinel_command(str(tmp_path / "我的 SYNOX" / "config.json"))
    assert command[-1] == "sentinel" and "--config" in command and cwd.endswith("我的 SYNOX")
    path = desk.install_autostart(str(folder), command, cwd)
    assert path == str(folder / "SYNOX-remind-sentinel.cmd") and desk.autostart_installed(str(folder))
    raw = open(path, "rb").read()
    assert raw.startswith(b"@echo off\r\nchcp 65001") and "我的 SYNOX".encode("utf-8") in raw
    assert desk.install_autostart(str(folder), command, cwd) == path and open(path, "rb").read() == raw   # 冪等
    assert desk.remove_autostart(str(folder)) and not desk.remove_autostart(str(folder))
    d = DeskService(str(tmp_path / "data"), owner_id=1, platform="win32")
    d.startup_folder = str(folder)
    assert d.sync_autostart(command, cwd) and d.view()["sentinel_installed"]
    d.save_settings(sentinel=False)
    assert d.sync_autostart(command, cwd) is None and os.listdir(folder) == []
    assert DeskService(str(tmp_path / "data"), owner_id=1, platform="linux").sync_autostart(command) is None


def test_popup_launcher_uses_windowless_python(tmp_path):
    calls = []
    launch = launcher.popup_launcher(str(tmp_path), popen=lambda cmd, **kw: calls.append((cmd, kw)))
    launch()
    cmd, kw = calls[0]
    assert cmd[1:4] == ["-m", "synox.remindwin", "--data"] and kw["stdout"] is not None
    d = DeskService(str(tmp_path), owner_id=1, launcher=lambda: calls.append("x"))
    d.launch()
    assert calls[-1] != "x"                                                        # 沒上膛：不開
    d.armed = True
    held = desk.popup_lock_at(str(tmp_path))
    assert held.try_acquire()
    d.launch()
    assert calls[-1] != "x"                                                        # 視窗程式已經開著：不再開
    held.release()
    d.launch()
    assert calls[-1] == "x"


# ── 視窗的邏輯（不開視窗）─────────────────────────────────────────────

def test_window_model_shows_acks_acts_and_closes(tmp_path):
    spool = desk.spool_at(str(tmp_path))
    now = [1_000_000.0]
    model = logic.DeskModel(spool, clock=lambda: now[0])
    spool.put_show(card(snooze_count=2, late_min=3))
    spool.put_show(card(rid=4, occ="2026-11-16T00:40:00+08:00", text="喝水"))
    spool.put_todos(desk.TodoList(1001, [{"rid": 7, "text": "繳電話費"}]))
    changes = model.poll()
    assert [c.text for c in changes.new] == ["喝水", "倒垃圾"] and changes.todos[0]["text"] == "繳電話費"
    title, sub = logic.card_lines(changes.new[1])
    assert title == "倒垃圾" and sub == "今天 00:51・晚了 3 分鐘・延後第 2 次之後"
    assert model.poll().new == []                                                  # 同一張不重複跳
    token = changes.new[1].token
    model.shown(token)
    ok, text = model.act(token, desk.BTN_SNOOZE_60)
    assert ok and text.startswith("好，") and "再叫你一次" in text
    acts = [x for x in spool.take_from_win() if isinstance(x, desk.DeskAction)]
    assert acts[0].action == "snooze" and acts[0].until and acts[0].rid == 3
    assert model.poll().closed == [] and token not in model.cards
    now[0] += logic.ACT_HIDE_S                                                     # 引擎沒處理（show 檔還在）→ 再跳
    assert [c.token for c in model.poll().new] == [token]
    spool.drop_show(token)                                                         # 引擎收回：先刪 show、再寫 close
    spool.put_close(desk.CloseCard(token=token, note="✅ 在 Telegram 上做完了"))
    assert model.poll().closed == [(token, "✅ 在 Telegram 上做完了")]
    assert not os.path.exists(tmp_path / desk.FOLDER / desk.DESK / desk.TO_WIN / desk.close_name(token))
    other = changes.new[0].token
    spool.drop_show(other)                                                         # 引擎刪了 show 檔＝別處處理掉
    assert model.poll().closed == [(other, "")]
    model.todo_done(1001, 7)
    todo_act = [x for x in spool.take_from_win() if isinstance(x, desk.DeskAction)][0]
    assert (todo_act.rid, todo_act.occurrence, todo_act.action) == (7, "", "done")
    assert desk.token_ok(todo_act.token)
    now[0] += logic.IDLE_EXIT_S
    assert model.idle()


def test_typed_snooze_needs_text_and_passes_the_raw_words(tmp_path):
    spool = desk.spool_at(str(tmp_path))
    model = logic.DeskModel(spool, clock=lambda: datetime(2026, 11, 16, 10, 0).timestamp())
    spool.put_show(card())
    model.poll()
    token = desk.make_token(1001, 3, OCC)
    assert model.act(token, desk.BTN_SNOOZE_TYPED, "  ") == (False, logic.T["typed_empty"])
    assert model.act(token, desk.BTN_SNOOZE_TYPED, "等我忙完")[0]                  # 看不懂也交給引擎
    act = spool.take_from_win()[0]
    assert act.typed == "等我忙完" and act.until is None


@pytest.mark.parametrize("text,expect", [
    ("15:30", datetime(2026, 11, 16, 15, 30)),
    ("9:00", datetime(2026, 11, 17, 9, 0)),            # 今天過了 → 明天
    ("3 點半", datetime(2026, 11, 17, 3, 30)),
    ("下午 3 點", datetime(2026, 11, 16, 15, 0)),
    ("+2h", datetime(2026, 11, 16, 12, 0)),
    ("+1h30m", datetime(2026, 11, 16, 11, 30)),
    ("+45m", datetime(2026, 11, 16, 10, 45)),
    ("半小時後", datetime(2026, 11, 16, 10, 30)),
    ("十分鐘後", datetime(2026, 11, 16, 10, 10)),
    ("2 小時後", datetime(2026, 11, 16, 12, 0)),
    ("明天 9 點", datetime(2026, 11, 17, 9, 0)),
    ("明天 09:15", datetime(2026, 11, 17, 9, 15)),
    ("明早 8 點", datetime(2026, 11, 17, 8, 0)),
    ("晚上八點", datetime(2026, 11, 16, 20, 0)),
    ("等等", None),
    ("25:00", None),
])
def test_parse_typed(text, expect):
    assert logic.parse_typed(text, datetime(2026, 11, 16, 10, 0)) == expect


def test_cards_stack_upwards_from_the_bottom_right():
    pos = logic.stack_positions(3, 1920, 1080, 360, 190)
    assert pos[0][0] == 1920 - 372 and pos[0][1] > pos[1][1] > pos[2][1]
    many = logic.stack_positions(12, 1920, 1080, 360, 190)
    assert len({x for x, _ in many}) == 3 and all(x >= 0 and y >= 0 for x, y in many)


# ── 畫面：只做 import 與語法檢查（不開視窗）───────────────────────────

def test_window_module_imports_without_opening_anything():
    import sys
    from synox.remindwin import window
    assert hasattr(window.DeskWindow, "run") and callable(window.run)
    base = os.path.dirname(window.__file__)
    for name in os.listdir(base):
        if name.endswith(".py"):
            with open(os.path.join(base, name), encoding="utf-8") as f:
                ast.parse(f.read(), filename=name)
    src = open(window.__file__, encoding="utf-8").read()
    top_imports = [n for n in ast.parse(src).body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any("tkinter" in ast.dump(n) for n in top_imports)                 # tkinter 只在 run() 裡 import
    assert "synox.remindwin.window" in sys.modules


def test_desk_service_ignores_actions_without_engine(tmp_path, caplog):
    d = DeskService(str(tmp_path), owner_id=1001, platform="linux")
    spool = desk.spool_at(str(tmp_path))
    spool.put_action(desk.DeskAction(token=desk.make_token(1001, 3, OCC), rid=3, occurrence=OCC, action="done", at=1.0))
    with caplog.at_level(logging.WARNING):
        assert d.process(None, None) == [("act", desk.make_token(1001, 3, OCC), False)]
    d.put_todos(1001, [{"rid": 5, "text": "繳電話費"}])
    assert spool.todos_for_win(1001) == []                                         # 不是 Windows 個人版：不寫
    d.platform = "win32"
    d.put_todos(1001, [{"rid": 5, "text": "繳電話費"}, {"text": "沒有 rid"}])
    assert spool.todos_for_win(1001)[0].items == [{"rid": 5, "text": "繳電話費"}]
    d.put_todos(2002, [{"rid": 6, "text": "別人的"}])
    assert spool.todos_for_win(2002) == []
