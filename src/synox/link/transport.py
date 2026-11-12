"""
傳輸層（SYNOX Link，架構 v1 §L3）：只搬 bytes（封好的信封），不碰內容。三種：

- MemoryTransport：同一個程序裡（測試、示範）。MemoryFabric 把幾台接在一起。
- FolderTransport：共用資料夾（SMB 分享、Syncthing／Dropbox 同步、USB 隨身碟）。
      <dir>/<收件者 node_id>/<時間>-<序>-<亂數>.msg   寫暫存檔再 rename，讀完就刪。兩邊各自輪詢。
  沒有伺服器、不開埠、不連外；只要兩台都看得到同一個資料夾就能通（哪怕是 NAS 的一個分享）。
- TcpTransport：區域網路 TCP。一邊 listen（主控台）、一邊 connect（哨兵，斷了自己退避重連）。
      框架：4 bytes big-endian 長度 ＋ 信封 JSON；一封最多 MAX_FRAME。
  沒有 TLS：信封本身端對端加密＋簽章，傳輸層看到的只是密文；沒驗過的連線送來的東西除了丟掉什麼都不做
  （驗不過 BAD_FRAMES 次就斷線）。對外聽的位址只建議內網或 WireGuard 裡（docs/link.md）。

介面（node.py 用）：
    t.start(on_frame, on_connect=None)   on_frame(frame: bytes, conn) 收到一封；on_connect(conn) 連上了（tcp connect 端）
    t.send(peer_id, frame, conn=None)    → bool（False＝現在送不出去：沒連線、資料夾不在）
    t.bind(peer_id, conn)                node 驗過信封之後：這條連線是這一台的（之後 send 走它）
    t.bad(conn)                          這條連線送了驗不過的東西
    t.stop() / t.status()
"""

from __future__ import annotations

import logging
import os
import queue
import secrets
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, Optional

from synox.link.envelope import MAX_FRAME

OnFrame = Callable[[bytes, Any], None]
OnConnect = Callable[[Any], None]
BAD_FRAMES = 3
MAX_CONNS = 32
BACKOFF_MAX = 60.0
_LEN = struct.Struct("!I")


class TransportError(Exception):
    pass


# ── 記憶體（測試）────────────────────────────────────────────────────

class MemoryFabric:
    """把幾個 MemoryTransport 接在一起。drop(a, b)：a→b 的信全丟（測斷線）。"""

    def __init__(self):
        self._ends: Dict[str, "MemoryTransport"] = {}
        self._dropped = set()
        self.delivered = 0

    def attach(self, node_id: str, end: "MemoryTransport") -> None:
        self._ends[node_id] = end

    def drop(self, src: str, dst: str, yes: bool = True) -> None:
        (self._dropped.add if yes else self._dropped.discard)((src, dst))

    def deliver(self, src: str, dst: str, frame: bytes) -> bool:
        end = self._ends.get(dst)
        if end is None or not end.running or (src, dst) in self._dropped:
            return False
        end._queue.put((frame, src))
        self.delivered += 1
        return True


class MemoryTransport:
    name = "memory"

    def __init__(self, fabric: MemoryFabric, node_id: str):
        self.fabric = fabric
        self.node_id = node_id
        self._queue: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self.running = False
        self._on_frame: Optional[OnFrame] = None
        fabric.attach(node_id, self)

    def start(self, on_frame: OnFrame, on_connect: Optional[OnConnect] = None) -> None:
        self._on_frame = on_frame
        self.running = True
        self._thread = threading.Thread(target=self._pump, daemon=True, name=f"Link-mem-{self.node_id[:4]}")
        self._thread.start()
        if on_connect is not None:
            on_connect(None)

    def _pump(self) -> None:
        while self.running:
            try:
                frame, src = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._on_frame(frame, src)
            except Exception:
                logging.exception("[LINK] memory on_frame failed")

    def send(self, peer_id: str, frame: bytes, conn=None) -> bool:
        return self.fabric.deliver(self.node_id, peer_id, frame)

    def bind(self, peer_id: str, conn) -> None:
        pass

    def bad(self, conn) -> None:
        pass

    def stop(self) -> None:
        self.running = False

    def status(self) -> dict:
        return {"kind": "memory", "running": self.running}


# ── 共用資料夾 ──────────────────────────────────────────────────────

class FolderTransport:
    name = "folder"
    SUFFIX = ".msg"

    def __init__(self, folder: str, node_id: str, poll: float = 2.0):
        self.folder = folder
        self.node_id = node_id
        self.poll = poll
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._on_frame: Optional[OnFrame] = None
        self._counter = 0
        self._lock = threading.Lock()
        self.error = ""

    @property
    def inbox(self) -> str:
        return os.path.join(self.folder, self.node_id)

    def start(self, on_frame: OnFrame, on_connect: Optional[OnConnect] = None) -> None:
        self._on_frame = on_frame
        self._stop.clear()
        try:
            os.makedirs(self.inbox, exist_ok=True)
            self.error = ""
        except OSError as e:
            self.error = f"資料夾開不了：{e}"
            logging.error("[LINK] folder transport: %s", self.error)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Link-folder")
        self._thread.start()
        if on_connect is not None:
            on_connect(None)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                logging.exception("[LINK] folder poll failed")
            self._stop.wait(self.poll)

    def poll_once(self) -> int:
        """讀一輪（測試也直接叫）。回傳收了幾封。"""
        if not os.path.isdir(self.inbox):
            try:
                os.makedirs(self.inbox, exist_ok=True)
            except OSError:
                return 0
        count = 0
        for name in sorted(os.listdir(self.inbox)):
            if not name.endswith(self.SUFFIX):
                continue
            path = os.path.join(self.inbox, name)
            try:
                with open(path, "rb") as f:
                    frame = f.read(MAX_FRAME + 4096)
                os.remove(path)
            except OSError:
                continue                                  # 另一邊還在寫、或同步工具鎖著：下一輪再看
            count += 1
            try:
                self._on_frame(frame, None)
            except Exception:
                logging.exception("[LINK] folder on_frame failed")
        return count

    def send(self, peer_id: str, frame: bytes, conn=None) -> bool:
        outbox = os.path.join(self.folder, peer_id)
        with self._lock:
            self._counter += 1
            name = f"{int(time.time() * 1000):013d}-{self._counter:06d}-{secrets.token_hex(3)}"
        try:
            os.makedirs(outbox, exist_ok=True)
            tmp = os.path.join(outbox, name + ".tmp")
            with open(tmp, "wb") as f:
                f.write(frame)
            os.replace(tmp, os.path.join(outbox, name + self.SUFFIX))
            return True
        except OSError as e:
            self.error = f"寫不進資料夾：{e}"
            logging.warning("[LINK] folder send failed: %s", e)
            return False

    def bind(self, peer_id: str, conn) -> None:
        pass

    def bad(self, conn) -> None:
        pass

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        return {"kind": "folder", "dir": self.folder, "error": self.error}


# ── 區域網路 TCP ────────────────────────────────────────────────────

def pack(frame: bytes) -> bytes:
    if len(frame) > MAX_FRAME:
        raise TransportError("frame too large")
    return _LEN.pack(len(frame)) + frame


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket) -> Optional[bytes]:
    """讀一封；對方關了回 None；長度超過 MAX_FRAME 丟 TransportError（呼叫的人要斷線）。"""
    head = _recv_exact(sock, _LEN.size)
    if head is None:
        return None
    (length,) = _LEN.unpack(head)
    if length > MAX_FRAME:
        raise TransportError(f"frame too large ({length})")
    return _recv_exact(sock, length)


class Conn:
    def __init__(self, sock: socket.socket, label: str):
        self.sock = sock
        self.label = label
        self.peer_id: Optional[str] = None
        self.bad = 0
        self._lock = threading.Lock()
        self.closed = False

    def send(self, frame: bytes) -> bool:
        with self._lock:
            if self.closed:
                return False
            try:
                self.sock.sendall(pack(frame))
                return True
            except (OSError, TransportError) as e:
                logging.info("[LINK] send to %s failed: %s", self.label, e)
                self.close()
                return False

    def close(self) -> None:
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def __repr__(self) -> str:
        return f"<Conn {self.label} peer={self.peer_id}>"


class TcpTransport:
    name = "tcp"

    def __init__(self, *, listen: Optional[tuple] = None, connect: Optional[tuple] = None,
                 sock_factory=socket.socket, backoff_max: float = BACKOFF_MAX):
        if (listen is None) == (connect is None):
            raise ValueError("TcpTransport: listen 或 connect 其中一個")
        self.listen_at = listen
        self.connect_to = connect
        self._sock_factory = sock_factory
        self._backoff_max = backoff_max
        self._stop = threading.Event()
        self._on_frame: Optional[OnFrame] = None
        self._on_connect: Optional[OnConnect] = None
        self._by_peer: Dict[str, Conn] = {}
        self._conns: set = set()
        self._lock = threading.Lock()
        self._server: Optional[socket.socket] = None
        self._threads: list = []
        self.error = ""
        self.connected = False

    # ── 啟動 ────────────────────────────────────────────────────

    def start(self, on_frame: OnFrame, on_connect: Optional[OnConnect] = None) -> None:
        self._on_frame, self._on_connect = on_frame, on_connect
        self._stop.clear()
        target = self._accept_loop if self.listen_at else self._connect_loop
        t = threading.Thread(target=target, daemon=True, name="Link-tcp")
        t.start()
        self._threads.append(t)

    def _accept_loop(self) -> None:
        host, port = self.listen_at
        try:
            server = self._sock_factory(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((host, port))
            server.listen(8)
            server.settimeout(0.5)
            self._server = server
            self.error = ""
            logging.info("[LINK] listening on %s:%s", host, port)
        except OSError as e:
            self.error = f"{host}:{port} 聽不了：{e}"
            logging.error("[LINK] %s", self.error)
            return
        while not self._stop.is_set():
            try:
                sock, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                if len(self._conns) >= MAX_CONNS:
                    sock.close()
                    continue
            conn = Conn(sock, f"{addr[0]}:{addr[1]}")
            t = threading.Thread(target=self.serve_conn, args=(conn,), daemon=True, name="Link-tcp-conn")
            t.start()
        try:
            server.close()
        except OSError:
            pass

    def _connect_loop(self) -> None:
        host, port = self.connect_to
        delay = 1.0
        while not self._stop.is_set():
            try:
                sock = self._sock_factory(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((host, port))
                sock.settimeout(None)
            except OSError as e:
                self.error = f"連不上 {host}:{port}：{e}"
                self._stop.wait(delay)
                delay = min(delay * 2, self._backoff_max)
                continue
            self.error = ""
            delay = 1.0
            conn = Conn(sock, f"{host}:{port}")
            self.connected = True
            logging.info("[LINK] connected to %s:%s", host, port)
            if self._on_connect is not None:
                try:
                    self._on_connect(conn)
                except Exception:
                    logging.exception("[LINK] on_connect failed")
            self.serve_conn(conn)                    # 斷了才回來
            self.connected = False
            self._stop.wait(delay)

    def serve_conn(self, conn: Conn) -> None:
        """讀這條連線直到對方關掉（測試用 socketpair 直接叫）。"""
        with self._lock:
            self._conns.add(conn)
        try:
            while not self._stop.is_set():
                try:
                    frame = read_frame(conn.sock)
                except TransportError as e:
                    logging.info("[LINK] %s: %s", conn.label, e)
                    break
                except OSError:
                    break
                if frame is None:
                    break
                try:
                    self._on_frame(frame, conn)
                except Exception:
                    logging.exception("[LINK] on_frame failed")
        finally:
            conn.close()
            with self._lock:
                self._conns.discard(conn)
                if conn.peer_id and self._by_peer.get(conn.peer_id) is conn:
                    del self._by_peer[conn.peer_id]

    # ── 送 ──────────────────────────────────────────────────────

    def bind(self, peer_id: str, conn) -> None:
        if not isinstance(conn, Conn):
            return
        conn.peer_id = peer_id
        with self._lock:
            old = self._by_peer.get(peer_id)
            self._by_peer[peer_id] = conn
        if old is not None and old is not conn:
            old.close()

    def bad(self, conn) -> None:
        if isinstance(conn, Conn):
            conn.bad += 1
            if conn.bad >= BAD_FRAMES and conn.peer_id is None:
                logging.info("[LINK] dropping %s after %s bad frames", conn.label, conn.bad)
                conn.close()

    def send(self, peer_id: str, frame: bytes, conn=None) -> bool:
        target = conn if isinstance(conn, Conn) else self._by_peer.get(peer_id)
        if target is None and self.connect_to is not None:
            with self._lock:
                target = next(iter(self._conns), None)       # connect 端只有一條連線（主控台）
        return target.send(frame) if target is not None else False

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            conns = list(self._conns)
        for c in conns:
            c.close()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass

    def status(self) -> dict:
        with self._lock:
            peers = sorted(self._by_peer)
            n = len(self._conns)
        where = f"listen {self.listen_at[0]}:{self.listen_at[1]}" if self.listen_at else \
            f"connect {self.connect_to[0]}:{self.connect_to[1]}"
        return {"kind": "tcp", "where": where, "connections": n, "bound": peers, "error": self.error}


__all__ = ["MemoryFabric", "MemoryTransport", "FolderTransport", "TcpTransport", "Conn", "TransportError",
           "pack", "read_frame", "BAD_FRAMES", "MAX_CONNS"]
