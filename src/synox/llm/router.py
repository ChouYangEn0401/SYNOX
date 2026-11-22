"""
備援（waterfall，docs/adr/0046）：主要的 AI 來源不能用時換下一個。**換不換、換誰的邏輯在 ntu_easy_llm 的 router**；
SYNOX 只做三件事：把自己的 adapter 包成它的成員、把結果翻回 SYNOX 的 Reply、ask 模式出按鈕讓人選。

    "llm": {"kind": "openai", "api_key": "vault:llm_api_key", "model": "…",
            "waterfall": {"mode": "auto",                       # off（預設）｜auto｜ask
                          "backups": [{"kind": "local", "server": "ollama", "model": "…"},
                                      {"kind": "source", "source": "remote/api_key/llop", "model": "any",
                                       "source_options": {"llop_profile": "default"}}],
                          "triggers": ["quota_exhausted", "auth_invalid", "rate_limited"],   # 可省略＝預設三種
                          "retry_429": 2, "max_retry_wait_s": 30, "cooldown_s": 900, "ask_ttl_s": 600}}

- **沒寫 waterfall（或 mode=off）＝照舊只用主要來源**，跟以前一模一樣（不建 router、不 import ntu_easy_llm）。
- 順序就是使用者寫的順序；SYNOX 不預設任何來源的先後。backups 的每一項跟 llm 本身同一種寫法（不能再有 waterfall）。
- 主要來源＝成員 "primary"，備援依序＝"backup1"、"backup2"…（router 的事件與畫面用 SYNOX 自己的名字顯示）。
- `trust`（加密或金鑰核對失敗）永遠不能當觸發條件（ntu_easy_llm 也會擋）。
- ntu_easy_llm 沒有 router（沒裝、0.5、0.6 的預發布版還沒有）：照舊只用主要來源，設定頁／doctor 寫原因（`status_line`）。
- auto：換了來源，回覆另外一則「⚠️ AI 來源的提醒：已改用 X（原因：額度用完）」（Reply.warnings，agent 照常送）。
- ask：丟 `FallbackAsk`（LLMError）；agent 出一張按鈕卡（agent/fallback_card.py）。按了「改用 X 重送」＝在
  `pinned(X)` 裡把剛剛那句重送一次（那一輪每一次呼叫都直接用 X，不經 router；只在那條執行緒）。之後的輪照 router 的規則
  （失敗的那個在冷卻、會被跳過）。SYNOX 不呼叫 router 的 `resume`：一輪中斷後 SYNOX 重跑整輪，不接回 router 存的半輪
  （理由與限制：ADR 0046）。
- 成員的能力取交集（每個都支援工具才用原生工具呼叫，不然整條鏈走文字協定；看圖、停止詞同理）——換來源時不會格式對不上。
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from synox.llm import kinds
from synox.llm.base import ChatAdapter, ImagePart, LLMError, Message, Reply, ToolCall, ToolSpec

MODES = ("off", "auto", "ask")
POLICY_KEYS = ("triggers", "retry_429", "max_retry_wait_s", "cooldown_s", "ask_ttl_s")
TRIGGER_KINDS = ("quota_exhausted", "auth_invalid", "rate_limited", "permission", "overloaded", "context_too_long",
                 "model_not_found", "tools_unsupported", "bad_request", "timeout", "connection", "link_changed",
                 "server_error", "bad_response", "unknown")          # trust 不在裡面：永遠不能當觸發條件
MAX_BACKUPS = 4
NO_ROUTER = "備援沒有啟動：這台的 ntu_easy_llm 還沒有 router（要 0.6 正式版以上）；現在只用主要來源。"


def parse(raw) -> Optional[dict]:
    """config 的 llm.waterfall → 檢查過的 dict；沒寫＝None。只看形狀（不 import ntu_easy_llm）；寫錯丟 ValueError（中文）。
    backups 每一項的內容由呼叫端（config.py）用跟 llm 一樣的規則再檢查。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("llm.waterfall 要是一個 {…} 物件。")
    unknown = sorted(k for k in raw if k not in ("mode", "backups") + POLICY_KEYS and not str(k).startswith("_"))
    if unknown:
        raise ValueError(f"llm.waterfall 不認得 {'、'.join(unknown)}（只能是 mode、backups、{'、'.join(POLICY_KEYS)}）。")
    mode = str(raw.get("mode") or "off").strip().lower()
    if mode not in MODES:
        raise ValueError("llm.waterfall.mode 只能是 off（關）、auto（自動換）、ask（先問我）。")
    backups = raw.get("backups")
    backups = [] if backups is None else backups
    if not isinstance(backups, list) or not all(isinstance(b, dict) for b in backups):
        raise ValueError("llm.waterfall.backups 要是 [{…}, …]（每一項跟 llm 同一種寫法）。")
    if len(backups) > MAX_BACKUPS:
        raise ValueError(f"llm.waterfall.backups 最多 {MAX_BACKUPS} 個。")
    for i, b in enumerate(backups):
        if "waterfall" in b:
            raise ValueError(f"llm.waterfall.backups[{i}] 裡不能再有 waterfall。")
        if str(b.get("kind") or "none") in ("none", ""):
            raise ValueError(f"llm.waterfall.backups[{i}] 要寫 kind（不能是 none）。")
    out: Dict[str, Any] = {"mode": mode, "backups": [dict(b) for b in backups]}
    if "triggers" in raw:
        triggers = raw["triggers"]
        if not isinstance(triggers, list) or not all(isinstance(t, str) for t in triggers):
            raise ValueError("llm.waterfall.triggers 要是字串的清單（例如 [\"quota_exhausted\"]）。")
        bad = [t for t in triggers if t not in TRIGGER_KINDS]
        if bad:
            extra = "（trust＝加密或金鑰核對失敗，永遠不能自動換）" if "trust" in bad else ""
            raise ValueError(f"llm.waterfall.triggers 不認得 {'、'.join(bad)}{extra}。")
        out["triggers"] = list(triggers)
    for key in POLICY_KEYS[1:]:
        if key in raw:
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"llm.waterfall.{key} 要是 0 以上的數字。")
            out[key] = value
    return out


def active(llm: dict) -> bool:
    wf = (llm or {}).get("waterfall")
    return isinstance(wf, dict) and str(wf.get("mode") or "off").lower() in ("auto", "ask") and bool(wf.get("backups"))


def router_class():
    """ntu_easy_llm 的 router 類別（0.6 的設計稿叫 `LLM`）；沒有＝None。"""
    try:
        from ntu_easy_llm import router as mod
    except ImportError:
        return None
    return getattr(mod, "LLM", None) or getattr(mod, "Router", None)


def status_line(llm: dict) -> str:
    """設定頁、doctor 的一行：備援現在是什麼狀態（不建 adapter、不連網）。"""
    wf = (llm or {}).get("waterfall")
    if not isinstance(wf, dict) or str(wf.get("mode") or "off").lower() == "off":
        return "備援：關（只用主要來源）"
    n = len(wf.get("backups") or [])
    if not n:
        return "備援：沒有設定備援來源（只用主要來源）"
    if router_class() is None:
        return NO_ROUTER
    how = "自動換" if str(wf.get("mode")).lower() == "auto" else "先問我"
    return f"備援：{how}，{n} 個備援來源"


# ── SYNOX 的 adapter → ntu_easy_llm 的成員 ───────────────────────────────


def _weak(adapter) -> bool:
    """跟 agent/auto.weak_source 同一個判斷（llm/ 不 import agent/，invariant 2）。"""
    if getattr(adapter, "weak", False) or getattr(adapter, "kind", "") == "local":
        return True
    if getattr(adapter, "kind", "") == "openai_compat":
        from synox.llm.local import is_local_url
        return is_local_url(str(getattr(adapter, "base_url", "") or ""))
    return False


def source_of(adapter) -> str:
    """成員在分類樹上的位置（只是標示，router 不會拿它去找 adapter）。"""
    from synox.llm.easy_llm import LEGACY_SOURCES
    kind = getattr(adapter, "kind", "") or ""
    if kind == "local":
        return "local/synox_local"
    if kind == "claude_code":
        return "remote/subscription/synox_claude_code"
    if kind == "fake":
        return "local/fake"
    if kind in LEGACY_SOURCES:
        return LEGACY_SOURCES[kind]
    return str(getattr(adapter, "source", "") or "local/synox")


class AsEasyAdapter:
    """SYNOX 的 ChatAdapter 包成 ntu_easy_llm 的 Adapter 介面（router 的成員）。SYNOX 的 LLMError → 它的 LLMError（帶 kind）。"""

    def __init__(self, inner: ChatAdapter, member_id: str, label: str = ""):
        from ntu_easy_llm.profiles import Profile
        self.inner = inner
        self.label = label or getattr(inner, "name", member_id)
        self.profile = Profile(id=member_id, source=source_of(inner), model=str(getattr(inner, "model", "") or ""),
                               label=self.label[:120])

    def capabilities(self):
        from ntu_easy_llm.adapters import Capabilities
        return Capabilities(tools=bool(self.inner.supports_tools), vision=bool(self.inner.supports_vision),
                            stop=bool(self.inner.supports_stop), usage=True)

    def chat(self, messages, tools=None, *, max_tokens=None, temperature=None, stop=(), timeout=None, on_delta=None):
        from ntu_easy_llm.agent import ChatReply, LLMError as EasyError, ToolCall as EasyCall, Usage
        from ntu_easy_llm.types import as_messages
        msgs = []
        for m in as_messages(messages):
            msgs.append(Message(m.role, m.content or "",
                                tool_calls=[ToolCall(c.name, dict(c.arguments or {}), c.id) for c in m.tool_calls],
                                tool_call_id=m.tool_call_id or "", name=m.name or "",
                                images=[ImagePart(p.mime, p.data) for p in m.images]))
        specs = []
        for t in tools or ():
            name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else "")
            desc = getattr(t, "description", None) if not isinstance(t, dict) else t.get("description", "")
            params = getattr(t, "parameters", None) if not isinstance(t, dict) else t.get("parameters")
            specs.append(ToolSpec(str(name), str(desc or ""), dict(params or {"type": "object", "properties": {}})))
        kw = {"stop": tuple(stop)} if stop and self.inner.supports_stop else {}
        try:
            reply = self.inner.chat(msgs, specs if self.inner.supports_tools else (), **kw)
        except LLMError as e:
            raise EasyError(str(e), kind=e.kind or "unknown", profile_id=self.profile.id) from e
        calls = [EasyCall(c.id or f"call_{i}", c.name, dict(c.args or {})) for i, c in enumerate(reply.tool_calls)]
        usage = reply.usage or {}
        finish = reply.finish or ("tool_calls" if calls else "stop")
        return ChatReply(text=reply.text or "", tool_calls=calls,
                         usage=Usage(int(usage.get("input", 0) or 0), int(usage.get("output", 0) or 0)),
                         stop_reason=finish, finish=finish, warnings=list(reply.warnings or []))

    def list_models(self, *, timeout: float = 15.0):
        from ntu_easy_llm.adapters import ModelInfo
        model = str(getattr(self.inner, "model", "") or "")
        return [ModelInfo(id=model)] if model else []

    def probe(self, *, send: bool = False, timeout: float = 30.0):
        from ntu_easy_llm.adapters import ProbeResult
        if not send:
            return ProbeResult(True, "", None, tuple(self.list_models()))
        try:
            problem = self.inner.probe()
        except Exception as e:                       # probe 照約定不丟例外
            problem = f"{type(e).__name__}: {e}"
        return ProbeResult(problem is None, problem or "")


# ── router 包成 SYNOX 的 ChatAdapter ────────────────────────────────────


class FallbackAsk(LLMError):
    """ask 模式：某個來源因為 kind 失敗，要人決定換不換。choices＝[(成員 id, 名字)]（照鏈的順序）。"""

    def __init__(self, message: str, *, kind: str, pending, choices: List[Tuple[str, str]], adapter: "RouterAdapter",
                 failed: str = ""):
        super().__init__(message, kind=kind)
        self.pending = pending
        self.choices = list(choices)
        self.adapter = adapter
        self.failed = failed


class RouterAdapter(ChatAdapter):
    """包住 ntu_easy_llm 的 router（對外跟單一來源一樣）。"""

    def __init__(self, router, members: List[AsEasyAdapter], mode: str):
        self.router = router
        self.members = list(members)
        self.mode = mode
        inner = [m.inner for m in self.members]
        primary = inner[0]
        self.primary = primary
        self.kind = getattr(primary, "kind", "")
        self.model = getattr(primary, "model", "")
        self.base_url = getattr(primary, "base_url", "")
        self.labels = {m.profile.id: m.label for m in self.members}
        self.name = f"{getattr(primary, 'name', '主要來源')}＋{len(self.members) - 1} 個備援"
        self.supports_tools = all(bool(a.supports_tools) for a in inner)
        self.supports_vision = all(bool(a.supports_vision) for a in inner)
        self.supports_stop = all(bool(a.supports_stop) for a in inner)
        # 有任何一個成員是本地／弱來源，auto 開關就當弱來源（換過去時保護照樣在，agent/auto.py）
        self.weak = any(_weak(a) for a in inner)
        self.max_tokens = getattr(primary, "max_tokens", 0)
        self._local = threading.local()

    def check_vision(self) -> bool:
        return all(a.check_vision() for a in (m.inner for m in self.members))

    def label(self, member_id: str) -> str:
        return self.labels.get(member_id, member_id)

    def member(self, member_id: str) -> Optional[ChatAdapter]:
        found = next((m for m in self.members if m.profile.id == member_id), None)
        return found.inner if found is not None else None

    @contextlib.contextmanager
    def pinned(self, member_id: str):
        """ask 模式按了「改用 X 重送」：這條執行緒上（重送的那一輪）每一次 chat 都直接用 X，不經 router。
        只在這一輪、只在這條執行緒（別的聊天不受影響）；之後照 router 的規則（失敗的那個在冷卻，會被跳過）。"""
        if self.member(member_id) is None:
            raise LLMError("沒有這個備援來源了（設定剛改過？）。")
        before = getattr(self._local, "pin", None)
        self._local.pin = member_id
        try:
            yield self
        finally:
            self._local.pin = before

    def notice_of(self, result) -> str:
        """換了來源的那一句（用 SYNOX 的名字）；沒換＝""。"""
        if not getattr(result, "switched", False):
            return ""
        switched = [e for e in (getattr(result, "events", None) or []) if getattr(e, "name", "") == "switched"]
        if switched:
            last = switched[-1]
            return f"已改用 {self.label(last.to_id)}（原因：{kinds.label_of(last.reason)}）"
        notice = str(getattr(result, "notice", "") or "")
        return notice or f"已改用 {self.label(getattr(result, 'profile_id', ''))}"

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = (), *, stop: Sequence[str] = ()) -> Reply:
        from ntu_easy_llm.agent import LLMError as EasyError
        from synox.llm.easy_llm import error_from, from_easy_reply, to_easy_messages, to_easy_tools
        from ntu_easy_llm.waterfall import FallbackRequired, WaterfallExhausted
        pin = getattr(self._local, "pin", None)
        if pin is not None:                             # 使用者在卡上選的來源：直接用它（錯誤照它自己的中文）
            inner = self.member(pin)
            kw = {"stop": tuple(stop)} if stop and inner.supports_stop else {}
            return inner.chat(messages, tools if inner.supports_tools else (), **kw)
        try:
            kw = {"stop": tuple(stop)} if stop and self.supports_stop else {}
            result = self.router.chat(to_easy_messages(messages),
                                      to_easy_tools(tools) if tools and self.supports_tools else None, **kw)
        except FallbackRequired as e:
            p = e.pending
            choices = [(c, self.label(c)) for c in p.candidates]
            kind = str(p.reason)
            failed = self.label(p.profile_id)
            raise FallbackAsk(f"{failed}：{kinds.label_of(kind)}。要改用別的來源嗎？（下面的按鈕）", kind=kind,
                              pending=p, choices=choices, adapter=self, failed=failed)
        except WaterfallExhausted as e:
            parts = [f"{self.label(pid)}：{kinds.label_of(getattr(err, 'kind', 'unknown'))}" for pid, err in e.errors]
            raise LLMError("每一個 AI 來源都試過了，都不能用（" + "；".join(parts) + "）。",
                           kind=str(getattr(e, "kind", "") or "unknown"))
        except EasyError as e:
            cause = e.__cause__ if isinstance(e.__cause__, LLMError) else None
            if cause is not None:                       # SYNOX 自己的成員丟的：原本那句中文
                raise LLMError(str(cause), kind=cause.kind or str(getattr(e, "kind", "") or ""))
            raise error_from(e, self.label(getattr(e, "profile_id", "")) or self.name)
        reply = from_easy_reply(result)
        notice = self.notice_of(result)
        if notice:
            reply.warnings.insert(0, notice)
        return reply

    def probe(self) -> Optional[str]:
        """「測一下」只測主要來源（備援各自在設定頁測）。"""
        return self.primary.probe()

    def status(self) -> List[dict]:
        """每個成員現在的狀態（冷卻到什麼時候、上次的錯）；router 沒有 status() 就只列名字。"""
        rows = {m.profile.id: {"id": m.profile.id, "label": m.label, "cooling_until": None, "last_error": ""}
                for m in self.members}
        try:
            for s in self.router.status() or []:
                row = rows.get(getattr(s, "profile_id", ""))
                if row is not None:
                    row["cooling_until"] = getattr(s, "cooling_until", None)
                    row["last_error"] = str(getattr(s, "last_error", "") or "")
        except Exception:
            pass
        return list(rows.values())


def build(primary: ChatAdapter, backups: Sequence[ChatAdapter], wf: dict, *,
          router_cls: Optional[Callable] = None) -> Optional[RouterAdapter]:
    """主要來源＋備援 → RouterAdapter；ntu_easy_llm 沒有 router＝None（呼叫端照舊用主要來源）。設定不對丟 LLMError。"""
    cls = router_cls or router_class()
    if cls is None:
        logging.warning("[LLM] %s", NO_ROUTER)
        return None
    from ntu_easy_llm.waterfall import WaterfallPolicy
    policy_raw = {"mode": wf["mode"], **{k: wf[k] for k in POLICY_KEYS if k in wf}}
    try:
        policy = WaterfallPolicy.from_dict(policy_raw)
    except ValueError as e:
        raise LLMError(f"備援的設定不對：{e}")
    members = [AsEasyAdapter(primary, "primary")] + \
        [AsEasyAdapter(b, f"backup{i + 1}") for i, b in enumerate(backups)]
    router = cls(members, waterfall=policy, locale="zh-TW")
    return RouterAdapter(router, members, policy.mode)
