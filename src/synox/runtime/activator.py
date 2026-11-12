"""
連動（activator，docs/adr/0004）：任務的狀態一變，照規則**馬上**做下一件事（或留給心跳做）；防循環、防暴衝。

    act = Activator(loop, settings=conf["activator"])      runtime.install 建、掛在 loop.listeners
    act.add(Rule(id="system.x", on="pack.diary", tag="diary-image", do=fn, owner="system"))
                                                             登記（同 id＝換掉，保留暫停狀態）；會繞回自己＝丟 RuleError
    loop 每次任務做完、逾時、pack 回報 → act.observe(change)   （loop._emit 叫的）
    act.drain()                                              心跳叫：把 timing="heartbeat" 留下來的待處理項目做掉
    act.view()                                               網頁 API 的 activator 物件
    act.reset_rule(id) / act.resume() / act.dismiss(id)      主控面板的按鈕

一條規則＝「任務 on 變成 state（可加：從 from 變過來、標籤 tag、程式條件 when）→ 做一件事」：
  run_task（跑一個登記了 fn 的任務）、notify（通知擁有者一句話）、do（程式；只有系統與 python pack 的程式能給）。
  timing："now"＝馬上（在自己的執行緒做，不卡回報的那一方）；"heartbeat"＝留成待處理，下一次心跳（或主控面板按「現在處理」）再做。

防無限連動（每一條都測過，tests/test_activator.py）：
  1. 登記時：靜態找循環（規則 A 的動作會讓任務 T 有新狀態、規則 B 聽 T＝A 接 B；有環＝不收）。只認得 run_task 與宣告的 emits。
  2. 執行時：每個事件帶「連動串」（chain id、第幾層、走過的規則）。同一條規則在同一串裡第二次＝循環 → 暫停那條規則；
     超過 max_depth 層、同一串做了超過 max_chain_actions 件事 → 暫停那條規則。程式動作裡回報的狀態、叫的 run_now 自動接在同一串
     （loop.caused_by；程式自己開執行緒就接不上——那時靠 3、4 擋）。
  3. 每條規則：cooldown_s 內不再做（安靜略過）；一小時超過 max_per_hour 次 → 暫停；上一次還沒做完 → 略過（Home Assistant 的 single）；
     動作連續失敗 NOTIFY_AFTER（5）次 → 暫停。
  4. 全部：budget_window_min 分鐘內全部規則加起來超過 budget_max_actions 件 → 全部暫停；一個事件最多觸發 max_fanout 條規則。
  暫停（斷路器）＝不再做、通知擁有者一次（10 分鐘內多條被暫停只說一次，其餘寫在主控面板）、主控面板看得到原因、按「重設」才恢復。

存檔（ADR 0001 的規則：沒有個人資料的結構才落地）：data/runtime/state.json 的 "activator"：每條規則的暫停原因與時間、
上一次觸發時間、連續失敗數；全部暫停的原因；待處理項目；有規則在聽的最近 50 個事件（任務 id、state、標籤、時間、串 id、
哪些規則做了／略過；沒有規則在聽的事件不記，任務狀態本來就存在 tasks）。
任務的訊息（可能有個人資料）只在記憶體，只交給同一個 owner 的程式（別人的事件 message＝""，跟 peer_status 一樣）。
"""

from __future__ import annotations

import dataclasses
import logging
import secrets
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

from synox.runtime import settings as rs
from synox.runtime.loop import MESSAGE_MAX, NOTIFY_AFTER, Cause, caused_by, clean_text, iso

EVENT_KEEP = 50              # 記憶體＋存檔裡最近幾個事件
EVENT_VIEW = 20              # status 給幾個
PENDING_MAX = 100            # 留給心跳的最多幾件（滿了新的略過）
PENDING_TTL = 24 * 3600.0    # 留超過一天＝丟掉（心跳關著時不會一直堆）
CHAIN_KEEP = 500             # 記幾串的「做了幾件事」
TRIP_NOTIFY_GAP = 600.0      # 暫停通知：10 分鐘內最多一則
HOUR = 3600.0
MAX_TOTAL_RULES = 200        # 系統＋config＋pack 全部

SYSTEM = "system"
CONFIG = "config"


class RuleError(ValueError):
    """規則寫錯、或會繞回自己；訊息是給人看的一句話。"""


@dataclass(frozen=True)
class Event:
    """一次狀態變化。message 只在記憶體（交給程式動作時，不是同一個 owner 的會清掉）。"""
    id: str
    task: str
    state: str
    prev: str
    tag: str
    owner: str
    at: float
    chain: str
    depth: int = 0
    path: Tuple[str, ...] = ()
    message: str = ""


def _parse_emit(text: str) -> Tuple[str, Optional[str]]:
    """"pack.diary" → ("pack.diary", None)（什麼標籤都可能）；"pack.diary#asked" → ("pack.diary", "asked")。"""
    task, _sep, tag = text.partition("#")
    return task, (tag if _sep else None)


@dataclass
class Rule:
    id: str
    on: str
    states: Tuple[str, ...] = ("ok",)
    from_states: Tuple[str, ...] = ()
    tag: Optional[str] = None
    run_task: str = ""
    notify: str = ""
    do: Optional[Callable[[Event], None]] = field(default=None, repr=False)
    when: Optional[Callable[[Event], bool]] = field(default=None, repr=False)
    emits: Tuple[str, ...] = ()
    timing: str = "now"
    cooldown_s: int = 0
    max_per_hour: int = rs.DEFAULT_PER_HOUR
    owner: str = SYSTEM
    name: str = ""
    enabled: bool = True

    @classmethod
    def from_config(cls, data: dict) -> "Rule":
        """settings.parse_rule 檢查過的 dict → Rule（owner＝config）。"""
        return cls(id=data["id"], on=data["on"], states=tuple(data["state"]), from_states=tuple(data["from"]),
                   tag=data["tag"], run_task=data["run_task"], notify=data["notify"], timing=data["timing"],
                   cooldown_s=data["cooldown_s"], max_per_hour=data["max_per_hour"], owner=CONFIG,
                   name=data["name"], enabled=data["enabled"])

    def check(self) -> "Rule":
        """形狀與權限（誰能做什麼）。錯丟 RuleError。"""
        def bad(text):
            raise RuleError(f"連動規則 {self.id!r}：{text}")
        if not isinstance(self.id, str) or not rs.RULE_ID_RE.match(self.id):
            bad("id 要是小寫英數字與 . _ -（128 字內）")
        if not isinstance(self.on, str) or not rs.TASK_ID_RE.match(self.on):
            bad("on 要是任務 id")
        self.states = tuple(self.states) if not isinstance(self.states, str) else (self.states,)
        self.from_states = tuple(self.from_states) if not isinstance(self.from_states, str) else (self.from_states,)
        if not self.states or any(s not in rs.RULE_STATES for s in self.states + self.from_states):
            bad(f"state／from 只能是 {'／'.join(rs.RULE_STATES)}")
        if self.tag is not None and (not isinstance(self.tag, str) or not rs.TAG_RE.match(self.tag)):
            bad("tag 要是小寫英數字與 . _ -（32 字內），或 None＝什麼標籤都算")
        actions = [bool(self.run_task), bool(self.notify), self.do is not None]
        if sum(actions) != 1:
            bad("要剛好有一個動作：run_task、notify 或 do")
        if self.run_task and not rs.TASK_ID_RE.match(self.run_task):
            bad("run_task 要是任務 id")
        if self.notify and (not isinstance(self.notify, str) or len(self.notify) > rs.NOTIFY_MAX):
            bad(f"notify 要是 {rs.NOTIFY_MAX} 字內的一句話")
        if self.do is not None and not callable(self.do):
            bad("do 要是函式")
        if self.when is not None and not callable(self.when):
            bad("when 要是函式")
        self.emits = tuple(self.emits)
        for item in self.emits:
            task, tag = _parse_emit(item) if isinstance(item, str) else ("", None)
            if not rs.TASK_ID_RE.match(task) or (tag is not None and not rs.TAG_RE.match(tag)):
                bad(f"emits 的 {item!r} 要寫成任務 id 或「任務 id#標籤」")
        if self.timing not in rs.TIMINGS:
            bad("timing 要是 now 或 heartbeat")
        for key, high in (("cooldown_s", rs.COOLDOWN_MAX), ("max_per_hour", rs.PER_HOUR_MAX)):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or not (1 if key == "max_per_hour" else 0) <= value <= high:
                bad(f"{key} 要是整數（{'1' if key == 'max_per_hour' else '0'}～{high}）")
        # 權限：誰定義的就只能做誰能做的事（不是另一套權限：pack 能碰的本來就只有自己的任務與自己的程式）
        if self.owner == CONFIG:
            if self.id.startswith(rs.RESERVED_PREFIXES):
                bad("config.json 的規則 id 不能用 system. 或 pack. 開頭")
            if self.do is not None or self.when is not None or self.emits:
                bad("config.json 的規則只能用 run_task 或 notify（不收程式）")
        elif self.owner == SYSTEM:
            if not self.id.startswith("system."):
                bad("系統的規則 id 要用 system. 開頭")
        else:
            mine = f"pack.{self.owner}"
            if not self.id.startswith(mine + "."):
                bad(f"工具的規則 id 要用 {mine}. 開頭")
            if self.run_task and self.run_task != mine and not self.run_task.startswith(mine + "."):
                bad(f"工具只能跑自己的任務（{mine}），不能跑 {self.run_task}")
        self.name = (self.name or self.id)[:60]
        return self

    def matches(self, ev: Event) -> bool:
        return (ev.task == self.on and ev.state in self.states
                and (not self.from_states or ev.prev in self.from_states)
                and (self.tag is None or ev.tag == self.tag))

    def emitted(self) -> List[Tuple[str, Optional[str]]]:
        """做完會讓哪些任務有新狀態（靜態找循環用）：run_task＝那個任務（沒有標籤）；程式＝宣告的 emits。"""
        if self.run_task:
            return [(self.run_task, "")]
        return [_parse_emit(e) for e in self.emits]

    def action_text(self) -> str:
        if self.run_task:
            return f"跑任務 {self.run_task}"
        if self.notify:
            return f"通知你：{self.notify}"
        return "程式（" + ("系統" if self.owner == SYSTEM else f"工具 {self.owner}") + "）"


class _RuleState:
    """一條規則跑起來的狀態（同 id 換掉規則時留著，暫停不會因為重新登記就消失）。"""

    def __init__(self, saved: Optional[dict] = None):
        saved = saved if isinstance(saved, dict) else {}
        self.fired: Deque[float] = deque()
        self.last_fired_at: Optional[float] = _num(saved.get("last_fired_at"))
        self.failures = saved.get("failures") if isinstance(saved.get("failures"), int) and saved["failures"] > 0 else 0
        self.tripped: Optional[str] = saved.get("tripped") if isinstance(saved.get("tripped"), str) else None
        self.tripped_at: Optional[float] = _num(saved.get("tripped_at")) if self.tripped else None
        self.running = False
        self.skipped = 0
        self.last_note: Optional[str] = None      # 上一次的結果（給人看；只在記憶體）


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _new_id() -> str:
    return secrets.token_hex(4)


class Activator:

    def __init__(self, loop, *, settings: Optional[dict] = None):
        self.loop = loop
        self.settings = dict(rs.defaults()["activator"])
        self.settings.update({k: v for k, v in (settings or {}).items() if k != "rules"})
        self.rules: Dict[str, Rule] = {}
        self.rejected: Dict[str, str] = {}             # 登記不進來的（會繞回自己）：id → 原因
        self.paused: Optional[dict] = None             # 全部暫停：{"reason", "at"}
        self.pending: List[dict] = []
        self.events: Deque[dict] = deque(maxlen=EVENT_KEEP)
        self._st: Dict[str, _RuleState] = {}
        self._saved_rules: Dict[str, dict] = {}
        self._chains: "OrderedDict[str, int]" = OrderedDict()
        self._budget: Deque[float] = deque()
        self._last_trip_say: Optional[float] = None
        self._unsaid = 0
        self._outbox: List[str] = []
        self._lock = threading.RLock()
        self._load(loop.saved("activator", {}))
        loop.listeners.append(self.observe)

    # ── 設定、時間 ───────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled", True))

    def _limit(self, key: str) -> int:
        return int(self.settings.get(key, rs.DEFAULT_RUNTIME["activator"][key]))

    def _now(self) -> float:
        return self.loop._clock()

    # ── 存檔 ─────────────────────────────────────────────────────────

    def _load(self, saved) -> None:
        if not isinstance(saved, dict):
            return
        rules = saved.get("rules")
        if isinstance(rules, dict):
            self._saved_rules = {k: v for k, v in rules.items() if isinstance(k, str) and isinstance(v, dict)}
        paused = saved.get("paused")
        if isinstance(paused, dict) and isinstance(paused.get("reason"), str):
            self.paused = {"reason": paused["reason"], "at": _num(paused.get("at"))}
        for item in saved.get("pending") or []:
            if (isinstance(item, dict) and all(isinstance(item.get(k), str) for k in ("id", "rule", "task", "state", "chain"))
                    and _num(item.get("at")) is not None):
                self.pending.append(item)
        self.pending = self.pending[:PENDING_MAX]
        for item in (saved.get("events") or [])[-EVENT_KEEP:]:
            if isinstance(item, dict) and isinstance(item.get("task"), str):
                self.events.append(item)

    def _state(self) -> dict:
        with self._lock:
            rules = dict(self._saved_rules)
            for rid, st in self._st.items():
                rules[rid] = {"tripped": st.tripped, "tripped_at": st.tripped_at, "last_fired_at": st.last_fired_at,
                              "failures": st.failures}
            rules = {k: v for k, v in rules.items() if v.get("tripped") or v.get("last_fired_at") or v.get("failures")}
            return {"rules": rules, "paused": dict(self.paused) if self.paused else None,
                    "pending": [dict(p) for p in self.pending], "events": [dict(e) for e in self.events]}

    def _save(self) -> None:
        self.loop.save(activator=self._state())

    def _flush(self) -> None:
        """鎖裡排好的通知，出鎖再送（通知慢不能卡住連動）。"""
        with self._lock:
            out, self._outbox = self._outbox, []
        for text in out:
            self.loop._say(text)

    # ── 登記 ─────────────────────────────────────────────────────────

    def add(self, rule: Rule, *, strict: bool = True) -> Optional[Rule]:
        """登記（同 id＝換掉）。形狀錯一律丟 RuleError；會繞回自己：strict 丟 RuleError，否則記在 rejected、回 None。"""
        rule.check()
        with self._lock:
            if rule.id not in self.rules and len(self.rules) >= MAX_TOTAL_RULES:
                raise RuleError(f"連動規則最多 {MAX_TOTAL_RULES} 條。")
            trial = dict(self.rules)
            trial[rule.id] = rule
            cycle = rs.find_cycle([(r.id, r.on, r.tag, r.emitted()) for r in trial.values()])
            if cycle:
                reason = "會繞回自己（無限連動）：" + " → ".join(cycle)
                if strict:
                    raise RuleError(f"連動規則 {rule.id!r} {reason}")
                self.rejected[rule.id] = reason
                logging.warning("[ACTIVATOR] rule %s rejected: %s", rule.id, reason)
                return None
            self.rules[rule.id] = rule
            self.rejected.pop(rule.id, None)
            if rule.id not in self._st:
                self._st[rule.id] = _RuleState(self._saved_rules.pop(rule.id, None))
        return rule

    def remove(self, rule_id: str) -> bool:
        with self._lock:
            return self.rules.pop(rule_id, None) is not None

    # ── 事件進來 ─────────────────────────────────────────────────────

    def observe(self, change: dict) -> None:
        """loop 的狀態變化（loop._emit）→ 事件 → 看規則。"""
        cause = change.get("cause")
        if not isinstance(cause, Cause):
            cause = None
        ev = Event(id=_new_id(), task=str(change.get("task", "")), state=str(change.get("state", "")),
                   prev=str(change.get("prev") or ""), tag=str(change.get("tag") or ""),
                   owner=str(change.get("owner") or ""), at=_num(change.get("at")) or self._now(),
                   chain=cause.chain if cause else _new_id(), depth=cause.depth if cause else 0,
                   path=tuple(cause.path) if cause else (), message=str(change.get("message") or ""))
        self.dispatch(ev)

    def dispatch(self, ev: Event) -> List[str]:
        """照規則處理一個事件；回這次做了（或排進待處理）的規則 id。"""
        with self._lock:
            candidates = [r for _id, r in sorted(self.rules.items()) if r.enabled and r.matches(ev)]
        candidates = [r for r in candidates if self._when_ok(r, ev)]
        if not candidates:
            return []            # 沒有規則在聽：不記事件（任務的狀態 loop 已經存了；不然每 30 秒的排程會把紀錄洗掉）
        now_list: List[Rule] = []
        fired: List[str] = []
        skipped: List[dict] = []
        with self._lock:
            now = self._now()
            for r in candidates:
                reason = "連動整個關著（runtime.activator.enabled=false）" if not self.enabled else self._guard(r, ev, now, len(fired))
                if reason:
                    self._st[r.id].skipped += 1
                    self._st[r.id].last_note = reason
                    skipped.append({"rule": r.id, "reason": reason})
                    continue
                self._book(r, ev, now)
                fired.append(r.id)
                if r.timing == "heartbeat":
                    self._enqueue(r, ev, now)
                else:
                    self._st[r.id].running = True
                    now_list.append(r)
            self.events.append({"id": ev.id, "task": ev.task, "state": ev.state, "prev": ev.prev, "tag": ev.tag,
                                "at": ev.at, "chain": ev.chain, "depth": ev.depth, "fired": fired, "skipped": skipped})
        self._flush()
        self._save()
        for r in now_list:
            self.loop._spawn(lambda r=r: self._act(r, ev), f"act-{r.id}")
        return fired

    def _when_ok(self, r: Rule, ev: Event) -> bool:
        if r.when is None:
            return True
        try:
            return bool(r.when(self._event_for(r, ev)))
        except Exception:
            logging.exception("[ACTIVATOR] condition of %s failed", r.id)
            return False

    def _guard(self, r: Rule, ev: Event, now: float, n_fired: int) -> str:
        """這次能不能做：""＝可以；否則回略過的原因（必要時順便暫停規則或全部）。在鎖裡叫。"""
        st = self._st[r.id]
        if st.tripped:
            return f"這條規則暫停中（{st.tripped}）"
        if self.paused:
            return f"全部連動暫停中（{self.paused['reason']}）"
        if r.id in ev.path:
            return self._trip(r, "同一串連動又回到這條規則（循環）", now)
        if ev.depth >= self._limit("max_depth"):
            return self._trip(r, f"連動串超過 {self._limit('max_depth')} 層", now)
        if self._chains.get(ev.chain, 0) >= self._limit("max_chain_actions"):
            return self._trip(r, f"同一串連動做了超過 {self._limit('max_chain_actions')} 件事", now)
        if n_fired >= self._limit("max_fanout"):
            return f"一個事件最多觸發 {self._limit('max_fanout')} 條規則，這條略過"
        if r.timing == "now" and st.running:
            return "上一次還沒做完，這次略過"
        if r.timing == "heartbeat" and len(self.pending) >= PENDING_MAX:
            return f"留給心跳的待處理已經滿了（{PENDING_MAX} 件），這次略過"
        if r.cooldown_s and st.last_fired_at is not None and now - st.last_fired_at < r.cooldown_s:
            return f"冷卻中（{r.cooldown_s} 秒內做過）"
        while st.fired and now - st.fired[0] >= HOUR:
            st.fired.popleft()
        if len(st.fired) >= r.max_per_hour:
            return self._trip(r, f"一小時內觸發超過 {r.max_per_hour} 次", now)
        window = self._limit("budget_window_min") * 60.0
        while self._budget and now - self._budget[0] >= window:
            self._budget.popleft()
        if len(self._budget) >= self._limit("budget_max_actions"):
            reason = f"{self._limit('budget_window_min')} 分鐘內全部連動加起來超過 {self._limit('budget_max_actions')} 件"
            self.paused = {"reason": reason, "at": now}
            self._outbox.append(f"⏸ 連動全部暫停了：{reason}（可能有規則在互相觸發）。到網頁主控面板看是哪些規則，處理好再按「恢復」。")
            return f"全部連動暫停：{reason}"
        return ""

    def _trip(self, r: Rule, reason: str, now: float) -> str:
        st = self._st[r.id]
        st.tripped, st.tripped_at = reason, now
        logging.warning("[ACTIVATOR] rule %s tripped: %s", r.id, reason)
        if self._last_trip_say is None or now - self._last_trip_say >= TRIP_NOTIFY_GAP:
            more = f"（另外還有 {self._unsaid} 條規則也被暫停）" if self._unsaid else ""
            self._outbox.append(f"⏸ 連動規則「{r.name}」暫停了：{reason}{more}。不會再自己動；"
                                "到網頁主控面板看原因，處理好再按「重設」。")
            self._last_trip_say, self._unsaid = now, 0
        else:
            self._unsaid += 1
        return f"暫停這條規則：{reason}"

    def _book(self, r: Rule, ev: Event, now: float) -> None:
        st = self._st[r.id]
        st.fired.append(now)
        st.last_fired_at = now
        self._budget.append(now)
        self._chains[ev.chain] = self._chains.get(ev.chain, 0) + 1
        self._chains.move_to_end(ev.chain)
        while len(self._chains) > CHAIN_KEEP:
            self._chains.popitem(last=False)

    def _enqueue(self, r: Rule, ev: Event, now: float) -> None:
        self.pending.append({"id": _new_id(), "rule": r.id, "task": ev.task, "state": ev.state, "prev": ev.prev,
                             "tag": ev.tag, "owner": ev.owner, "at": now, "chain": ev.chain, "depth": ev.depth,
                             "path": list(ev.path)})
        self._st[r.id].last_note = "留給下一次心跳"

    # ── 做 ───────────────────────────────────────────────────────────

    def _event_for(self, r: Rule, ev: Event) -> Event:
        """交給程式的事件：不是同一個 owner 的訊息拿掉（pack 之間不互相讀資料，跟 peer_status 一樣）。"""
        if r.owner == SYSTEM or r.owner == ev.owner:
            return ev
        return dataclasses.replace(ev, message="")

    def _act(self, r: Rule, ev: Event) -> None:
        child = Cause(ev.chain, ev.depth + 1, tuple(ev.path) + (r.id,))
        error, note = None, "做了"
        try:
            if r.run_task:
                if not self.loop.run_now(r.run_task, manual=False, cause=child):
                    note = f"任務 {r.run_task} 正在跑、或沒有這個任務，這次略過"
            elif r.notify:
                text = r.notify.replace("{task}", ev.task).replace("{state}", ev.state).replace("{tag}", ev.tag)
                self.loop._say(f"🔗 {text}")
            else:
                with caused_by(child):
                    r.do(self._event_for(r, ev))
        except Exception as e:
            logging.exception("[ACTIVATOR] action of %s failed", r.id)
            error = clean_text(f"{type(e).__name__}: {e}", MESSAGE_MAX)
        with self._lock:
            st = self._st.get(r.id)
            if st is not None:
                st.running = False
                if error is None:
                    st.failures, st.last_note = 0, note
                else:
                    st.failures += 1
                    st.last_note = f"失敗：{error}"
                    if st.failures >= NOTIFY_AFTER and not st.tripped:
                        self._trip(r, f"動作連續失敗 {st.failures} 次", self._now())
        self._flush()
        self._save()

    def drain(self) -> int:
        """心跳（或主控面板「現在處理」）叫：留著的待處理項目做掉。回這次開始做的件數。
        規則不見了／關掉了＝丟掉；規則或全部暫停中＝留著（重設後下一次再做）；超過一天＝丟掉。"""
        todo: List[Tuple[Rule, Event]] = []
        with self._lock:
            now = self._now()
            keep = []
            for item in self.pending:
                r = self.rules.get(item["rule"])
                if now - float(item["at"]) > PENDING_TTL or r is None or not r.enabled:
                    continue
                st = self._st[r.id]
                if st.tripped or self.paused:
                    keep.append(item)
                    continue
                path = item.get("path") if isinstance(item.get("path"), list) else []
                todo.append((r, Event(id=item["id"], task=item["task"], state=item["state"],
                                      prev=str(item.get("prev") or ""), tag=str(item.get("tag") or ""),
                                      owner=str(item.get("owner") or ""), at=float(item["at"]), chain=item["chain"],
                                      depth=int(item.get("depth") or 0), path=tuple(str(p) for p in path))))
                st.running = True
            self.pending = keep
        self._save()
        for r, ev in todo:
            self.loop._spawn(lambda r=r, ev=ev: self._act(r, ev), f"act-{r.id}")
        return len(todo)

    # ── 主控面板 ─────────────────────────────────────────────────────

    def reset_rule(self, rule_id: str) -> bool:
        """解除一條規則的暫停（連同連續失敗數、這一小時的次數）。沒有這條＝False。"""
        with self._lock:
            st = self._st.get(rule_id)
            if rule_id not in self.rules or st is None:
                return False
            st.tripped = st.tripped_at = None
            st.failures = 0
            st.fired.clear()
            st.last_note = "你按了重設"
        self._save()
        return True

    def resume(self) -> bool:
        """解除「全部暫停」（連同這段時間的總數）。本來就沒暫停＝False。"""
        with self._lock:
            was = self.paused is not None
            self.paused = None
            self._budget.clear()
        self._save()
        return was

    def dismiss(self, pending_id: str) -> bool:
        with self._lock:
            before = len(self.pending)
            self.pending = [p for p in self.pending if p["id"] != pending_id]
            gone = len(self.pending) != before
        if gone:
            self._save()
        return gone

    def view(self) -> dict:
        with self._lock:
            now = self._now()
            window = self._limit("budget_window_min") * 60.0
            used = sum(1 for t in self._budget if now - t < window)
            order = {CONFIG: 0, SYSTEM: 1}
            rules = sorted(self.rules.values(), key=lambda r: (order.get(r.owner, 2), r.id))
            return {
                "enabled": self.enabled,
                "paused": {"reason": self.paused["reason"], "at": iso(self.paused.get("at"))} if self.paused else None,
                "limits": {k: self._limit(k) for k in ("max_depth", "max_chain_actions", "max_fanout",
                                                       "budget_window_min", "budget_max_actions")},
                "budget_used": used,
                "rules": [self._rule_view(r, now) for r in rules],
                "rejected": [{"id": k, "reason": v} for k, v in sorted(self.rejected.items())],
                "pending": [{"id": p["id"], "rule": p["rule"], "task": p["task"], "state": p["state"],
                             "tag": p.get("tag") or "", "at": iso(p["at"])} for p in self.pending],
                "events": [self._event_view(e) for e in list(self.events)[::-1][:EVENT_VIEW]],
            }

    def _rule_view(self, r: Rule, now: float) -> dict:
        st = self._st[r.id]
        status = "tripped" if st.tripped else ("off" if not r.enabled or not self.enabled else "active")
        return {"id": r.id, "name": r.name, "owner": r.owner, "on": r.on, "states": list(r.states),
                "from": list(r.from_states), "tag": r.tag, "action": r.action_text(), "timing": r.timing,
                "status": status, "reason": st.tripped, "tripped_at": iso(st.tripped_at),
                "last_fired_at": iso(st.last_fired_at), "fired_last_hour": sum(1 for t in st.fired if now - t < HOUR),
                "max_per_hour": r.max_per_hour, "cooldown_s": r.cooldown_s, "failures": st.failures,
                "skipped": st.skipped, "last_note": st.last_note}

    @staticmethod
    def _event_view(e: dict) -> dict:
        return {"id": e.get("id"), "task": e.get("task"), "state": e.get("state"), "prev": e.get("prev") or "",
                "tag": e.get("tag") or "", "at": iso(_num(e.get("at"))), "chain": e.get("chain"),
                "depth": e.get("depth") or 0, "fired": list(e.get("fired") or []),
                "skipped": [dict(s) for s in e.get("skipped") or [] if isinstance(s, dict)]}


def rules_from_config(rules: Sequence[dict]) -> List[Rule]:
    return [Rule.from_config(r) for r in rules or []]


__all__ = ["Activator", "Event", "Rule", "RuleError", "rules_from_config"]
