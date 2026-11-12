"""SYNOX Link（兩台 SYNOX 連線）：身分、信封、配對、傳輸、主控台↔哨兵的任務來回。不綁埠、不連網（記憶體傳輸、socketpair）。"""

import json
import os
import socket
import threading
import time

import pytest
from isdtelekit.testing import OWNER_ID, FakeChannel

from conftest import SynoxBot
from synox import link as synox_link
from synox.app import build
from synox.config import SynoxConfig
from synox.link import pairing, protocol as P, settings as link_settings
from synox.link.bus import EventBus
from synox.link.envelope import LinkError, ReplayGuard, decode, encode, open_envelope, seal
from synox.link.identity import IdentityError, NodeCard, NodeIdentity, load_or_create, node_id_of
from synox.link.peers import PeerStore
from synox.link.transport import Conn, FolderTransport, MemoryFabric, MemoryTransport, TcpTransport, TransportError, \
    pack, read_frame
from synox.llm.fake import FakeAdapter
from synox.vault import Vault
from isdtelekit.host.config import ConfigError


# ── 身分 ─────────────────────────────────────────────────────────────

def test_identity_and_card_roundtrip(tmp_path):
    vault = Vault(b"k" * 32, str(tmp_path))
    me = load_or_create(vault, "客廳")
    again = load_or_create(vault, "客廳")
    assert again.node_id == me.node_id and me.node_id == node_id_of(me.sign_pub)
    assert me.node_id.count("-") == 5 and len(me.node_id) == 29
    card = NodeCard.from_text(me.card().to_text())
    assert card.node_id == me.node_id and card.name == "客廳"
    renamed = load_or_create(vault, "廚房")                       # 名字改了、金鑰不變
    assert renamed.node_id == me.node_id and renamed.card().name == "廚房"


def test_card_tamper_rejected():
    me = NodeIdentity.generate("a")
    raw = me.card().to_dict()
    other = NodeIdentity.generate("b")
    raw["box_pub"] = other.card().to_dict()["box_pub"]              # 換掉加密公鑰
    with pytest.raises(IdentityError):
        NodeCard.from_dict(raw)
    raw = me.card().to_dict()
    raw["name"] = "x"
    with pytest.raises(IdentityError):
        NodeCard.from_dict(raw)
    with pytest.raises(IdentityError):
        NodeCard.from_text("hello")


# ── 信封 ─────────────────────────────────────────────────────────────

def _pair():
    a, b = NodeIdentity.generate("a"), NodeIdentity.generate("b")
    cards = {a.node_id: a.card(), b.node_id: b.card()}
    return a, b, cards.get


def test_envelope_roundtrip_and_tamper():
    a, b, lookup = _pair()
    guard = ReplayGuard()
    env = seal(a, b.card(), "task.offer", {"id": "1", "command": "/note 買牛奶"}, seq=1)
    assert set(env) == {"v", "from", "to", "seq", "ts", "eph", "salt", "ct", "sig"}
    msg = open_envelope(b, lookup, decode(encode(env)), guard)
    assert (msg.kind, msg.body["command"], msg.sender, msg.seq) == ("task.offer", "/note 買牛奶", a.node_id, 1)
    assert "買牛奶" not in encode(env).decode("utf-8")              # 傳輸層看不到明文
    for key, value in (("ct", env["ct"][:-4] + "AAAA"), ("to", a.node_id), ("seq", 99), ("from", b.node_id)):
        bad = dict(env, **{key: value})
        with pytest.raises(LinkError):
            open_envelope(b, lookup, bad, ReplayGuard())
    with pytest.raises(LinkError):                                  # 不是寄給我的
        open_envelope(a, lookup, env, ReplayGuard())
    with pytest.raises(LinkError):                                  # 不認識的寄件者
        open_envelope(b, lambda _i: None, env, ReplayGuard())


def test_envelope_replay_seq_and_clock():
    a, b, lookup = _pair()
    now = [1_700_000_000.0]
    guard = ReplayGuard(clock=lambda: now[0])
    env1 = seal(a, b.card(), "ping", {}, seq=5, now=now[0])
    open_envelope(b, lookup, env1, guard)
    with pytest.raises(LinkError, match="重放"):
        open_envelope(b, lookup, env1, guard)
    env4 = seal(a, b.card(), "ping", {}, seq=4, now=now[0])
    with pytest.raises(LinkError, match="seq"):
        open_envelope(b, lookup, env4, guard, last_seq=lambda _s: 5)
    old = seal(a, b.card(), "ping", {}, seq=6, now=now[0] - 1000)
    with pytest.raises(LinkError, match="時間"):
        open_envelope(b, lookup, old, guard)


def test_envelope_pairing_card_only_when_allowed():
    a, b = NodeIdentity.generate("console"), NodeIdentity.generate("worker")
    lookup = {a.node_id: a.card()}.get                               # 主控台不認識哨兵
    env = seal(b, a.card(), P.PAIR_REQUEST, {"mac": "x"}, seq=1, card=b.card())
    with pytest.raises(LinkError, match="不認識"):
        open_envelope(a, lookup, env, ReplayGuard())
    msg = open_envelope(a, lookup, env, ReplayGuard(), allow_card=True)
    assert msg.card is not None and msg.card.node_id == b.node_id
    other = seal(b, a.card(), "task.result", {"id": "1"}, seq=2, card=b.card())   # 帶名片卻不是配對請求
    with pytest.raises(LinkError):
        open_envelope(a, lookup, other, ReplayGuard(), allow_card=True)


# ── 設定 ─────────────────────────────────────────────────────────────

def test_settings_parse():
    assert not link_settings.parse(None).enabled
    s = link_settings.parse({"enabled": True, "role": "worker", "transport": {"kind": "tcp", "connect": "10.0.0.5:8831"},
                             "max_effect": "read"})
    assert s.transport.connect == ("10.0.0.5", 8831) and s.max_effect == "read" and not s.is_console
    s = link_settings.parse({"enabled": True, "role": "console"})
    assert s.transport.listen == ("127.0.0.1", 8831)                 # 預設只聽本機
    s = link_settings.parse({"enabled": True, "transport": {"kind": "folder", "dir": "Z:/link"}})
    assert s.transport.kind == "folder" and s.transport.folder == "Z:/link"
    for bad in ({"role": "boss"}, {"enabled": True, "role": "worker"}, {"transport": {"kind": "udp"}},
                {"transport": {"kind": "tcp", "listen": "a", "connect": "b"}}, {"max_effect": "all"},
                {"transport": {"kind": "folder"}}, {"heartbeat": -1}, {"nope": 1}):
        with pytest.raises(ConfigError):
            link_settings.parse(bad)
    cfg = SynoxConfig.from_dict({"owner_id": OWNER_ID, "link": {"enabled": True}}, require_token=False, root="/tmp")
    assert cfg.link.enabled and cfg.link.is_console


# ── 事件匯流排 ───────────────────────────────────────────────────────

def test_bus_wildcards_and_isolation():
    bus = EventBus()
    got = []
    bus.subscribe("task.*", lambda t, e: 1 / 0)                      # 壞掉的 handler 不影響別人
    off = bus.subscribe("task.*", lambda t, e: got.append(t))
    assert bus.publish("task.done", id=1) == 2 and got == ["task.done"]
    bus.publish("peer.online")
    off()
    bus.publish("task.failed")
    assert got == ["task.done"]
    threading.Timer(0.05, lambda: bus.publish("link.in.pong", n=1)).start()
    assert bus.wait_for("link.in.*", 2.0) == ("link.in.pong", {"n": 1})
    assert bus.wait_for("never.*", 0.1) is None


# ── 傳輸層 ───────────────────────────────────────────────────────────

def test_folder_transport(tmp_path):
    a = FolderTransport(str(tmp_path / "share"), "aaaa-0000-0000-0000-0000-0000", poll=60)
    b = FolderTransport(str(tmp_path / "share"), "bbbb-0000-0000-0000-0000-0000", poll=60)
    got = []
    a._on_frame = lambda frame, conn: got.append(("a", frame))
    b._on_frame = lambda frame, conn: got.append(("b", frame))
    assert a.send(b.node_id, b"one") and a.send(b.node_id, b"two")
    assert b.poll_once() == 2 and got == [("b", b"one"), ("b", b"two")]
    assert os.listdir(b.inbox) == []                                 # 讀完就刪
    assert b.poll_once() == 0
    (tmp_path / "share" / a.node_id).mkdir(exist_ok=True)
    (tmp_path / "share" / a.node_id / "zzz.tmp").write_bytes(b"half")   # 還在寫的不讀
    assert a.poll_once() == 0


def test_tcp_framing_over_socketpair():
    left, right = socket.socketpair()
    try:
        left.sendall(pack(b"hello") + pack(b""))
        assert read_frame(right) == b"hello" and read_frame(right) == b""
        with pytest.raises(TransportError):
            pack(b"x" * (1024 * 1024 + 1))
        left.sendall(b"\x7f\xff\xff\xff")                           # 假的超大長度
        with pytest.raises(TransportError):
            read_frame(right)
    finally:
        left.close(), right.close()


def test_tcp_conn_serve_bind_and_bad(monkeypatch):
    t = TcpTransport(listen=("127.0.0.1", 0))                      # 不 start()：不聽埠
    got = []
    t._on_frame = lambda frame, conn: got.append((frame, conn))
    server_sock, client_sock = socket.socketpair()
    conn = Conn(server_sock, "test")
    thread = threading.Thread(target=t.serve_conn, args=(conn,), daemon=True)
    thread.start()
    client_sock.sendall(pack(b"env1"))
    deadline = time.time() + 2
    while not got and time.time() < deadline:
        time.sleep(0.01)
    assert got and got[0][0] == b"env1" and got[0][1] is conn
    t.bind("peer-1", conn)
    assert t.send("peer-1", b"reply") and read_frame(client_sock) == b"reply"
    assert t.status()["bound"] == ["peer-1"]
    t.bind("peer-1", conn)
    conn.peer_id = None
    for _ in range(3):
        t.bad(conn)                                                  # 沒驗過的連線三次就斷
    thread.join(2)
    assert conn.closed and not thread.is_alive()
    assert read_frame(client_sock) is None
    client_sock.close()


# ── 兩台（三台）SYNOX：主控台↔哨兵 ───────────────────────────────────

def _bot(tmp_path, name, raw):
    data = tmp_path / name / "data"
    cfg = {"owner_id": OWNER_ID, "data_dir": str(data), "vault": {"mode": "file"}, "llm": {"kind": "fake"}, **raw}
    config = SynoxConfig.from_dict(cfg, require_token=False, root=str(tmp_path / name))
    api = FakeChannel()
    vault = Vault(name.encode("ascii").ljust(32, b"k"), str(data))
    app = build(config, home=api, adapter=FakeAdapter(None), vault=vault)
    return SynoxBot(app, api)


@pytest.fixture
def fabric():
    fab = MemoryFabric()
    synox_link.set_transport_factory(lambda settings, node_id: MemoryTransport(fab, node_id))
    yield fab
    synox_link.set_transport_factory(None)


def _link(bot):
    return bot.app.extras[synox_link.EXTRA]


def _wait(bus, pattern, timeout=5.0, where=None):
    found = bus.wait_for(pattern, timeout, where)
    assert found is not None, f"no {pattern}"
    return found[1]


def _pair_up(console, worker):
    """主控台 link pair → 哨兵 link join → 哨兵送配對請求 → 主控台接受。"""
    cl, wl = _link(console), _link(worker)
    code = pairing.issue(cl.node.vault, cl.identity.card())
    card = pairing.save_join(wl.node.vault, code)
    wl.peers.add(card, role="console", via="join")
    assert wl.node.try_pairing()
    _wait(cl.bus, "link.paired", where=lambda t, e: e["peer"] == wl.identity.node_id)
    _wait(wl.bus, "link.paired")
    assert cl.peers.role_of(wl.identity.node_id) == "worker" and wl.peers.role_of(cl.identity.node_id) == "console"
    assert pairing.pending(cl.node.vault) is None and pairing.pending_join(wl.node.vault) is None


@pytest.fixture
def pair(tmp_path, fabric):
    console = _bot(tmp_path, "console", {"link": {"enabled": True, "role": "console", "name": "主控台",
                                                  "transport": {"kind": "memory"}, "heartbeat": 0}})
    worker = _bot(tmp_path, "worker", {"link": {"enabled": True, "role": "worker", "name": "客廳",
                                                "transport": {"kind": "memory"}, "heartbeat": 0}})
    for bot in (console, worker):
        _link(bot).node.start()
    _pair_up(console, worker)
    yield console, worker
    for bot in (console, worker):
        _link(bot).node.stop()


def test_install_only_when_enabled(tmp_path, fabric):
    bot = _bot(tmp_path, "plain", {})
    assert synox_link.EXTRA not in bot.app.extras
    bot.say(OWNER_ID, "/link_status")
    assert "未知指令" in bot.last(OWNER_ID)


def test_pairing_rejects_wrong_code(tmp_path, fabric):
    console = _bot(tmp_path, "c", {"link": {"enabled": True, "role": "console", "transport": {"kind": "memory"},
                                            "heartbeat": 0}})
    worker = _bot(tmp_path, "w", {"link": {"enabled": True, "role": "worker", "transport": {"kind": "memory"},
                                           "heartbeat": 0}})
    cl, wl = _link(console), _link(worker)
    cl.node.start(), wl.node.start()
    try:
        pairing.issue(cl.node.vault, cl.identity.card())                      # 主控台等著的碼
        forged, _ = pairing.make_code(cl.identity.card())                     # 另一個碼（秘密不一樣）
        pairing.save_join(wl.node.vault, forged)
        wl.peers.add(cl.identity.card(), role="console", via="join")
        assert wl.node.try_pairing()
        assert _wait(cl.bus, "link.rejected")["reason"] == "配對碼不對"
        assert cl.peers.ids() == []
        assert wl.bus.wait_for("link.paired", 0.3) is None                  # 不回任何東西
        # 沒有等著的碼：連名片都不看（當作不認識的寄件者）
        pairing.clear_pending(cl.node.vault)
        assert wl.node.try_pairing()
        assert "不認識" in _wait(cl.bus, "link.rejected")["reason"]
    finally:
        cl.node.stop(), wl.node.stop()


def test_task_roundtrip_and_status(pair):
    console, worker = pair
    cl, wl = _link(console), _link(worker)
    console.say(OWNER_ID, "/link_run 客廳 /note 買牛奶")
    assert "送給 客廳" in console.last(OWNER_ID)
    task = _wait(cl.bus, "task.done")["task"]
    assert task["state"] == P.DONE and "記下了" in task["result"]
    worker.say(OWNER_ID, "/note_list")
    assert "買牛奶" in worker.last(OWNER_ID)                           # 真的在哨兵上做了
    assert "✅ 任務" in console.last(OWNER_ID) and "記下了" in console.last(OWNER_ID)
    console.say(OWNER_ID, "/link_tasks")
    assert task["id"] in console.last(OWNER_ID) and "完成" in console.last(OWNER_ID)
    console.say(OWNER_ID, f"/link_task {task['id']}")
    assert "回覆：" in console.last(OWNER_ID)
    console.say(OWNER_ID, "/link_status")
    assert "主控台" in console.last(OWNER_ID) and "🟢 客廳" in console.last(OWNER_ID)
    worker.say(OWNER_ID, "/link_status")
    assert "哨兵" in worker.last(OWNER_ID)
    worker.say(OWNER_ID, "/link_run 客廳 /note x")
    assert "這台是哨兵" in worker.last(OWNER_ID)
    assert cl.book.get(task["id"]).requested_by == OWNER_ID
    assert [h[0] for h in wl.bus.history("worker.*")] == ["worker.accepted", "worker.done"]


def test_worker_refuses_danger_unknown_and_strangers(pair):
    console, worker = pair
    cl, wl = _link(console), _link(worker)
    console.say(OWNER_ID, "/link_run 客廳 /note_clear")                # DANGER > max_effect write
    task = _wait(cl.bus, "task.rejected")["task"]
    assert "危險" in task["error"] or "danger" in task["error"]
    assert "⛔" in console.last(OWNER_ID)
    console.say(OWNER_ID, "/link_run 客廳 /nope")
    assert _wait(cl.bus, "task.rejected")["task"]["error"] == "這台沒有這個指令"
    console.say(OWNER_ID, "/link_run 客廳 hello")
    assert "/ 開頭" in console.last(OWNER_ID)
    console.say(OWNER_ID, "/link_run 書房 /note x")
    assert "找不到哨兵" in console.last(OWNER_ID)
    # 陌生的第三台：名單上沒有 → 信直接丟掉
    stranger = NodeIdentity.generate("stranger")
    fab = wl.node.transport.fabric
    MemoryTransport(fab, stranger.node_id)
    env = seal(stranger, wl.identity.card(), P.TASK_OFFER, {"id": "x", "command": "/note hacked"}, seq=1)
    fab.deliver(stranger.node_id, wl.identity.node_id, encode(env))
    assert "不認識" in _wait(wl.bus, "link.rejected")["reason"]
    worker.say(OWNER_ID, "/note_list")
    assert "hacked" not in worker.last(OWNER_ID)
    # 名單上的另一台哨兵（不是主控台）派任務：不理
    peer = NodeIdentity.generate("peer-worker")
    MemoryTransport(fab, peer.node_id)
    wl.peers.add(peer.card(), role="worker")
    env = seal(peer, wl.identity.card(), P.TASK_OFFER, {"id": "y", "command": "/note sneaky"}, seq=1)
    fab.deliver(peer.node_id, wl.identity.node_id, encode(env))
    _wait(wl.bus, "link.in.task.offer")
    assert wl.bus.wait_for("worker.*", 0.3) is None
    worker.say(OWNER_ID, "/note_list")
    assert "sneaky" not in worker.last(OWNER_ID)


def test_redo_handoff_cancel_and_offline(pair, tmp_path):
    console, worker = pair
    cl = _link(console)
    third = _bot(tmp_path, "third", {"link": {"enabled": True, "role": "worker", "name": "書房",
                                              "transport": {"kind": "memory"}, "heartbeat": 0}})
    tl = _link(third)
    tl.node.start()
    try:
        _pair_up(console, third)
        console.say(OWNER_ID, "/link_run 客廳 /note 第一筆")
        first = _wait(cl.bus, "task.done")["task"]
        console.say(OWNER_ID, f"/link_redo {first['id']}")
        redo = _wait(cl.bus, "task.done")["task"]
        assert redo["lineage"] == first["id"] and redo["attempts"] == 2 and redo["worker"] == first["worker"]
        console.say(OWNER_ID, f"/link_handoff {redo['id']} 書房 /note 交接來的")
        handed = _wait(cl.bus, "task.done")["task"]
        assert handed["worker"] == tl.identity.node_id and handed["context"]["from_task"] == redo["id"]
        assert "記下了" in handed["context"]["result"]
        third.say(OWNER_ID, "/note_list")
        assert "交接來的" in third.last(OWNER_ID)
        console.say(OWNER_ID, f"/link_task {handed['id']}")
        assert "交接自" in console.last(OWNER_ID)
        # 對方沒連線：送不出去 → 失敗；取消一個已經結束的＝拒
        fab = tl.node.transport.fabric
        fab.drop(cl.identity.node_id, tl.identity.node_id)
        console.say(OWNER_ID, "/link_run 書房 /note 掉了")
        assert "送不出去" in console.last(OWNER_ID)
        console.say(OWNER_ID, f"/link_cancel {handed['id']}")
        assert "已經完成" in console.last(OWNER_ID)
        fab.drop(cl.identity.node_id, tl.identity.node_id, False)
        # 取消：丟給哨兵之前先讓它收不到，取消後再放行 → 結果不記
        fab.drop(cl.identity.node_id, tl.identity.node_id)
        task = cl.console.dispatch(tl.identity.node_id, "/note 不會記", requested_by=OWNER_ID)
        assert task.state == P.FAILED
        console.say(OWNER_ID, "/link_forget 書房")
        assert "從名單拿掉" in console.last(OWNER_ID) and tl.identity.node_id not in cl.peers.ids()
    finally:
        tl.node.stop()


def test_worker_cancel_before_run(pair):
    console, worker = pair
    cl, wl = _link(console), _link(worker)
    wl.worker.run_in_thread = False
    # 先把取消送到哨兵（手動），再送 offer：哨兵接了但不送結果
    task = P.Task(id="t-cancel", command="/note 不算", worker=wl.identity.node_id, requested_by=OWNER_ID)
    cl.book.add(task)
    cl.node.send(wl.identity.node_id, P.TASK_CANCEL, {"id": task.id})
    _wait(wl.bus, "link.in.task.cancel")
    cl.node.send(wl.identity.node_id, P.TASK_OFFER, task.wire())
    _wait(cl.bus, "link.in.task.accepted")
    assert cl.bus.wait_for("link.in.task.result", 0.5) is None
    worker.say(OWNER_ID, "/note_list")
    assert "不算" not in worker.last(OWNER_ID)


def test_heartbeat_presence(pair):
    console, worker = pair
    cl, wl = _link(console), _link(worker)
    assert cl.node.online(wl.identity.node_id)
    now = time.time()
    cl.node.tick(now + 3600)
    assert not cl.node.online(wl.identity.node_id)
    assert [t for t, _e in cl.bus.history("link.peer.*")][-1] == "link.peer.offline"
    wl.node.send(cl.identity.node_id, P.HEARTBEAT, {})
    _wait(cl.bus, "link.peer.online")
    assert cl.node.online(wl.identity.node_id)
    wl.node.send(cl.identity.node_id, P.PING, {})
    _wait(wl.bus, "link.in.pong")


def test_link_cli_pair_join_card(tmp_path, capsys):
    from synox.__main__ import main
    def cfg(name, role):
        folder = tmp_path / name
        folder.mkdir()
        path = folder / "config.json"
        path.write_text(json.dumps({"owner_id": OWNER_ID, "vault": {"mode": "file"}, "link": {
            "enabled": True, "role": role, "name": name, "transport": {"kind": "folder", "dir": str(tmp_path / "share")}}}),
            encoding="utf-8")
        return str(path)
    c, w = cfg("console", "console"), cfg("worker", "worker")
    assert main(["--config", c, "link", "card"]) == 0
    card_line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("SYNOX-CARD-1:")][0]
    assert main(["--config", c, "link", "pair"]) == 0
    code = [l for l in capsys.readouterr().out.splitlines() if l.startswith("SYNOX-PAIR-1:")][0]
    assert main(["--config", c, "link", "join", code]) == 2                    # 主控台不能 join
    assert main(["--config", w, "link", "join", code]) == 0
    assert "記住了主控台 console" in capsys.readouterr().out
    assert main(["--config", w, "link", "peers"]) == 0
    out = capsys.readouterr().out
    assert "console" in out and "主控台" in out and "還沒送出的配對請求" in out
    assert main(["--config", w, "link", "join", "garbage"]) == 2
    assert main(["--config", w, "link", "trust", card_line]) == 0            # 手動名片（已經在名單＝覆蓋）
    assert main(["--config", c, "link", "trust", card_line]) == 2            # 自己的名片
    assert main(["--config", w, "link", "forget", "console"]) == 0
    assert main(["--config", w, "link", "peers"]) == 0 and "名單是空的" in capsys.readouterr().out
    from synox import doctor
    lines = []
    assert isinstance(doctor.run(offline=True, config_path=c, out=lines.append), int)
    text = "\n".join(lines)
    assert "link：開，主控台（console）" in text and "folder" in text
