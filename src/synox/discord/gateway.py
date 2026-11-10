"""
Discord Gateway 收訊迴圈（WebSocket，bot 自己連出去：不開埠、不需要公開網址）。

    gw = Gateway(token, on_dispatch=lambda event, d: ...)
    gw.run_forever()        # ChannelHub 用執行緒跑；gw.stop() 停

流程（Gateway v10）：連上 → 收 op 10 Hello（heartbeat_interval）→ 送 op 2 Identify（或有 session 時 op 6 Resume）
→ 一直收 op 0 Dispatch（READY 記下 session_id、resume_gateway_url；其他交給 on_dispatch）。
- 心跳：第一次在 interval × 隨機(0–1) 之後，之後每 interval 一次（op 1，帶最後的序號 s）；
  送了心跳、下一次要送時還沒收到 op 11 ACK → 當作殭屍連線，斷線改 Resume。
- op 1（伺服器要心跳）立刻送；op 7 Reconnect → 斷線 Resume；op 9 Invalid Session（d=false）→ 丟掉 session 重新 Identify。
- 斷線自己重連，退避 1、2、4…最多 60 秒；認證錯（4004）、intent 沒開或不允許（4013、4014）等致命關閉碼丟 GatewayFatal
  （ChannelHub 會記下錯誤、退避再試，狀態頁看得到原因）。
- WebSocket 用 `websocket-client`（純 Python），只在真的連線時才 import；測試傳 connect= 假連線。
  假連線的介面：recv(timeout) → 字串或 None（逾時）、關閉時丟 Closed(code)；send(字串)；close()。
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Callable, Optional

GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
INTENTS = (1 << 12) | (1 << 15)        # DIRECT_MESSAGES | MESSAGE_CONTENT（私訊型 bot）
CHANNEL_INTENTS = (1 << 0) | (1 << 9) | (1 << 15)   # GUILDS | GUILD_MESSAGES | MESSAGE_CONTENT（頻道型 bot，PERM-5）
FATAL_CLOSE = {4004: "bot token 不對（4004）", 4010: "分片設定錯（4010）", 4011: "需要分片（4011）",
               4012: "Gateway 版本錯（4012）", 4013: "intents 數值不對（4013）",
               4014: "Developer Portal 沒開 Message Content intent（4014）"}
NO_RESUME_CLOSE = {4007, 4009}


class Closed(Exception):
    def __init__(self, code: int = 1000):
        super().__init__(f"websocket closed ({code})")
        self.code = code


class GatewayFatal(RuntimeError):
    pass


class _Reconnect(Exception):
    """這條連線不要了：重連（resume=True 試著接回原本的 session）。"""

    def __init__(self, resume: bool = True):
        super().__init__("reconnect")
        self.resume = resume


class WebSocketClientConn:
    """websocket-client 的薄包裝（真的連線用）。"""

    def __init__(self, url: str):
        try:
            import websocket          # websocket-client
        except ImportError:
            raise GatewayFatal("缺少套件 websocket-client：在 SYNOX 資料夾跑 .venv\\Scripts\\python.exe -m pip install -e .")
        self._mod = websocket
        self._ws = websocket.create_connection(url, timeout=30)

    def recv(self, timeout: float) -> Optional[str]:
        self._ws.settimeout(max(0.05, timeout))
        try:
            opcode, data = self._ws.recv_data()
        except self._mod.WebSocketTimeoutException:
            return None
        except self._mod.WebSocketConnectionClosedException:
            raise Closed(1006)
        if opcode == 8:               # close frame
            code = int.from_bytes(data[:2], "big") if data and len(data) >= 2 else 1000
            raise Closed(code)
        return data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)

    def send(self, text: str) -> None:
        try:
            self._ws.send(text)
        except self._mod.WebSocketConnectionClosedException:
            raise Closed(1006)

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


class Gateway:

    def __init__(self, token: str, on_dispatch: Callable[[str, dict], None], *, intents: int = INTENTS,
                 connect: Callable[[str], object] = WebSocketClientConn, url: str = GATEWAY_URL,
                 clock: Callable[[], float] = time.monotonic, rand: Callable[[], float] = random.random,
                 backoff_max: float = 60.0, label: str = "discord",
                 on_ready: Optional[Callable[[dict], None]] = None):
        self._token = token
        self.label = label                # log 用（多個 bot 時分得出是哪一條）
        self.on_dispatch = on_dispatch
        self.on_ready = on_ready          # READY 時拿到 bot 自己（頻道型 bot 認 @ 要用它的 id）
        self.intents = intents
        self._connect = connect
        self.url = url
        self._clock = clock
        self._rand = rand
        self._backoff_max = backoff_max
        self._stop = threading.Event()
        self._ws = None
        self.session_id: Optional[str] = None
        self.resume_url: Optional[str] = None
        self.seq: Optional[int] = None
        self.connects = 0                 # 連了幾次（測試、狀態用）
        self.user: dict = {}              # READY 裡的 bot 自己
        self._healthy = False             # 這條連線收過正常事件沒（重設退避用）

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run_forever(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            try:
                self._session()
            except GatewayFatal:
                raise
            except _Reconnect as r:
                if not r.resume:
                    self.session_id = self.seq = None
            except Closed as c:
                if self._stop.is_set():
                    break
                if c.code in FATAL_CLOSE:
                    raise GatewayFatal(f"Discord 拒絕連線：{FATAL_CLOSE[c.code]}")
                if c.code in NO_RESUME_CLOSE:
                    self.session_id = self.seq = None
                logging.warning("[DISCORD] %s gateway closed (%s); reconnecting", self.label, c.code)
            except (OSError, ValueError) as e:
                if self._stop.is_set():
                    break
                logging.warning("[DISCORD] %s gateway error: %s; reconnecting", self.label, type(e).__name__)
            if self._stop.is_set():
                break
            if self._healthy:
                delay = 1.0                      # 這條連線曾經正常：退避從頭算
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, self._backoff_max)

    # ── 一條連線 ─────────────────────────────────────────────────────

    def _send(self, op: int, d) -> None:
        self._ws.send(json.dumps({"op": op, "d": d}))

    def _session(self) -> None:
        """跑一條連線直到斷；回傳這條連線是否曾經正常收過事件（用來重設退避）。"""
        resume = bool(self.session_id and self.seq is not None)
        url = (self.resume_url or self.url) if resume else self.url
        if "?" not in url:
            url += "/?v=10&encoding=json"
        self._ws = ws = self._connect(url)
        self.connects += 1
        self._healthy = False
        try:
            hello = self._recv_json(ws, 30.0)
            if hello is None or hello.get("op") != 10:
                raise _Reconnect(resume=resume)
            interval = float((hello.get("d") or {}).get("heartbeat_interval") or 41250) / 1000.0
            next_beat = self._clock() + interval * self._rand()
            acked = True
            if resume:
                self._send(6, {"token": self._token, "session_id": self.session_id, "seq": self.seq})
            else:
                self._send(2, {"token": self._token, "intents": self.intents,
                               "properties": {"os": "windows", "browser": "synox", "device": "synox"}})
            while not self._stop.is_set():
                now = self._clock()
                if now >= next_beat:
                    if not acked:
                        raise _Reconnect(resume=True)          # 殭屍連線
                    self._send(1, self.seq)
                    acked = False
                    next_beat = now + interval
                msg = self._recv_json(ws, min(1.0, max(0.05, next_beat - now)))
                if msg is None:
                    continue
                op = msg.get("op")
                if msg.get("s") is not None:
                    self.seq = msg["s"]
                if op == 11:
                    acked = True
                elif op == 1:
                    self._send(1, self.seq)
                elif op == 7:
                    raise _Reconnect(resume=True)
                elif op == 9:
                    self._stop.wait(1.0 + 4.0 * self._rand())
                    raise _Reconnect(resume=bool(msg.get("d")))
                elif op == 0:
                    self._healthy = True
                    self._dispatch(msg.get("t") or "", msg.get("d") or {})
        finally:
            self._ws = None
            try:
                ws.close()
            except Exception:
                pass

    def _recv_json(self, ws, timeout: float) -> Optional[dict]:
        raw = ws.recv(timeout)
        if raw is None:
            return None
        try:
            msg = json.loads(raw)
        except ValueError:
            return None
        return msg if isinstance(msg, dict) else None

    def _dispatch(self, event: str, d: dict) -> None:
        if event == "READY":
            self.session_id = d.get("session_id")
            self.resume_url = d.get("resume_gateway_url")
            self.user = d.get("user") or {}
            logging.info("[DISCORD] %s connected as %s", self.label, self.user.get("username", "?"))
            if self.on_ready is not None:
                try:
                    self.on_ready(self.user)
                except Exception:
                    logging.exception("[DISCORD] %s on_ready failed", self.label)
            return
        if event == "RESUMED":
            return
        try:
            self.on_dispatch(event, d)
        except Exception:
            logging.exception("[DISCORD] %s handling %s failed", self.label, event)
