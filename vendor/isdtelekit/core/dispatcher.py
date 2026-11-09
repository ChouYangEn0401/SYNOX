"""
入口分流，跟 channel 無關：Inbound（誰、在哪、說了什麼）→ 下面其中一條路，回覆走 inbound 來的那個 api。

  1. 「/」開頭、在指令樹上 → authorize → 直接呼叫那個函數（快速路徑）
  2. 有進行中的多輪對話 → session.handler（樹上沒有的 /save、/list 也當文字交給它）
  3. 自由文字 → 私訊、fallback 願意接 → fallback（例如 AI 助理、把文字當成服務的輸入）
               其他人 → 提示用指令；群組裡不回
  按鈕：依 callback_data 前綴找到綁定的節點，以點擊者身分 authorize 後才呼叫。

打字、按鈕、排程全部經 registry.authorize()。各 channel 負責把平台訊息轉成 Inbound，並提供回覆用的
api（core/channel.py 的 Channel）。dispatcher 只認得自己的掛勾，不 import 任何功能模組：

  fallback     自由文字的出口（FreeTextFallback）
  observers    旁觀者（DispatchObserver）：看得到每個指令與按鈕、被擋下的指令，但不改決定（事件日誌、稽核…）
  group_menu   打群組名（/user）時列出那一組的指令；packs/help.py 會換成 /help 的版面
  stale        bot 離線時累積、現在才收到的非唯讀指令：先問要不要執行（packs/basics.py 的 StaleGuard）
  rate_limiter 每則訊息先問 admit()（limits/rate_limiter.py）
  texts        所有回覆的字（DispatcherTexts），想換語氣或語言就換

handle() 回傳 Route（做了什麼決定），並在執行之前印一行 [ROUTE] log：
    [ROUTE] telegram @alice(123) '/remind 買牛奶' → command remind.add
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional, Protocol, Sequence

from isdtelekit.core.channel import Channel, Inbound
from isdtelekit.core.conversation import ConversationManager
from isdtelekit.core.registry import BUTTON, DANGER, READ, ROUTINE, TYPED, CommandRegistry, Node
from isdtelekit.core.timing import Timing

# Route.kind：dispatcher 對一則 Inbound 做了什麼
COMMAND = "command"                  # 執行了指令樹上的葉節點（path）
GROUP_MENU = "group_menu"            # 打的是群組名，列出那組能用的指令（path）
DENIED = "denied"                    # authorize 擋掉（path、reason）
UNKNOWN_COMMAND = "unknown_command"  # 「/」開頭但樹上沒有，也不在對話中（擁有者專用的指令對別人也是這個）
CONVERSATION = "conversation"        # 交給進行中的多輪對話（reason＝session_type）
FALLBACK = "fallback"                # 交給自由文字的出口（fallback 也可以回自己的 kind）
NOT_UNDERSTOOD_ROUTE = "not_understood"  # 自由文字、沒有人接：提示用指令
IGNORED = "ignored"                  # 不回：群組裡的閒聊（reason=group）、空訊息、編輯過的、ignore_messages 罰則
RATE_LIMITED = "rate_limited"        # 速率限制擋掉（reason：muted / no_self_service / warn / blocked）
BUTTON_ROUTE = "button"              # 按鈕，handler 被呼叫了（path）
BUTTON_DENIED = "button_denied"      # 按鈕，點擊者沒有那個節點的權限、或按鈕過期了（path、reason）
BUTTON_UNKNOWN = "button_unknown"    # 沒有綁定的按鈕前綴
STALE = "stale"                      # 送出太久（bot 當時離線）的非唯讀指令：先問要不要執行（path、reason=幾分鐘前）

ROUTE_KINDS = (COMMAND, GROUP_MENU, DENIED, UNKNOWN_COMMAND, CONVERSATION, FALLBACK, NOT_UNDERSTOOD_ROUTE,
               IGNORED, RATE_LIMITED, BUTTON_ROUTE, BUTTON_DENIED, BUTTON_UNKNOWN, STALE)

# observer 的 around(kind, …) 收到的 kind：現在跑的是指令（打字或排程）還是按鈕
STEP_COMMAND, STEP_BUTTON = "command", "button"


@dataclass(frozen=True)
class Route:
    """dispatcher 的決定。終端機的 [ROUTE] log、測試都看它。"""
    kind: str
    path: str = ""      # 指令節點路徑（command / group_menu / denied / button*）
    reason: str = ""    # 為什麼（denied 的 authorize reason、rate_limited 的狀態、ignored 的原因）
    error: str = ""     # handler 執行時丟出的例外（決定是對的，但執行失敗）

    def to_dict(self) -> dict:
        return {"kind": self.kind, "path": self.path, "reason": self.reason, "error": self.error}


@dataclass(frozen=True)
class DispatcherTexts:
    """dispatcher 自己會回的每一句話。{command}、{name}、{span}、{minutes} 會被代換。"""
    not_understood: str = "我看得懂的是指令，輸入 /help 看看能做什麼。"
    edited: str = "✏️ 編輯過的訊息不會重新執行。要執行請重新傳一次。"
    unknown_command: str = "未知指令：{command}，輸入 /help 查看可用指令。"
    command_error: str = "指令執行時發生錯誤，請稍後再試。"
    conversation_error: str = "對話處理時發生錯誤，請輸入 /exit 結束後重試。"
    expired: str = "⌛ 上一個「{name}」的問答閒置超過 {span}，已經結束了；這句照一般訊息處理。"
    button_unknown: str = "未知的按鈕操作。"
    button_expired: str = "⌛ 這顆按鈕是 {minutes} 分鐘前的，已經過期；請重新下指令。"


class DispatchObserver(Protocol):
    """看著 dispatcher 做事、但不改變它的決定。兩個方法都可以不寫，dispatcher 用 hasattr 找。

    denied(api, inbound, user, node, decision)   authorize 擋下一個指令之後（提示已經送了）
    around(kind, api, inbound, user, node, run)  要跑 handler 時：自己呼叫 run(api)（可以先把 api 包一層，
                                                 例如記下回了什麼），跑完再記。handler 丟例外時例外會穿過
                                                 around 往外丟，dispatcher 照舊接住——所以失敗的不會被記成成功。
    """

    def denied(self, api, inbound: Inbound, user, node: Node, decision) -> None: ...

    def around(self, kind: str, api, inbound: Inbound, user, node: Node, run: Callable) -> None: ...


class FreeTextFallback(Protocol):
    """自由文字最後交給誰（不是指令、也沒有進行中的對話、而且是私訊）。沒有 fallback、或 accepts() 回 False，
    就回 texts.not_understood。

    accepts(user, chat_id, via) -> bool                 這個人在這裡打的字要不要接
    handle(api, inbound, user, text, age) -> Route      接手；age＝這則訊息送出到現在幾秒（dispatcher 的時鐘）。
                                                        要在動手之前用 Dispatcher.log_route() 印 [ROUTE]。
    busy（選配屬性）                                     還在處理上一句
    """

    def accepts(self, user, chat_id: int, via: str) -> bool: ...

    def handle(self, api, inbound: Inbound, user, text: str, age: float) -> Route: ...


class StaleHandler(Protocol):
    """bot 離線時累積、age 秒前送出的非唯讀指令：決定怎麼辦（通常是送一顆「現在執行」的按鈕）。"""

    def stale_command(self, api, inbound: Inbound, node: Node, age: float) -> None: ...


def plain_group_menu(registry: CommandRegistry, user, group: Node) -> str:
    """沒有注入 group_menu 時用的群組選單：只列這個人能用的指令和說明。"""
    leaves = [n for n in group.walk() if not n.is_group and registry.visible(user, n)]
    if not leaves:
        return "你沒有這個群組裡的任何指令。"
    return "\n".join([group.title, ""] + [f"  {n.command} — {n.summary}" for n in leaves])


class Dispatcher:

    def __init__(
        self,
        registry: CommandRegistry,
        user_manager,
        rate_limiter=None,
        conv_manager: Optional[ConversationManager] = None,
        *,
        fallback: Optional[FreeTextFallback] = None,
        timing: Optional[Timing] = None,
        stale: Optional[StaleHandler] = None,
        observers: Sequence[DispatchObserver] = (),
        group_menu: Optional[Callable[[object, Node], str]] = None,
        texts: Optional[DispatcherTexts] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.registry = registry
        self.user_manager = user_manager
        self.rate_limiter = rate_limiter
        self.conv_manager = conv_manager
        self.fallback = fallback
        self.timing = timing or Timing()
        self.stale = stale
        self.observers = list(observers)
        self.group_menu = group_menu or (lambda user, node: plain_group_menu(registry, user, node))
        self.texts = texts or DispatcherTexts()
        self._clock = clock

    def add_observer(self, observer: DispatchObserver) -> None:
        self.observers.append(observer)

    def handle(self, api: Channel, inbound: Inbound, via: str = TYPED) -> Route:
        """via=ROUTINE：排程造的訊息，不計速率限制、不問「要現在執行嗎」。"""
        if inbound.button is not None:
            try:
                return self._on_button(api, inbound)
            except Exception as exc:
                logging.exception("Error handling button via %s", inbound.channel)
                return Route(BUTTON_ROUTE, error=str(exc))

        text = (inbound.text or "").strip()
        if not inbound.user_id or not text:
            return Route(IGNORED, reason="empty")
        chat_id = inbound.chat_id
        if inbound.edited:
            # 編輯舊訊息不會重跑：不然改一下幾小時前的危險指令就又執行一次
            route = self.log_route(inbound, text, Route(IGNORED, reason="edited"))
            if text.startswith("/"):
                api.send_message(chat_id, self.texts.edited)
            return route
        user = self.user_manager.get_or_create(inbound.user_id, inbound.username)

        if text.startswith("/"):
            node, args = self.registry.resolve(text)
            if via != ROUTINE:
                limited = self._rate_limited(api, chat_id, user, node, is_command=True)
                if limited:
                    return self.log_route(inbound, text, limited)
            return self._run(api, inbound, user, text, node, args, via)
        if via != ROUTINE:
            limited = self._rate_limited(api, chat_id, user, None, is_command=False)
            if limited:
                return self.log_route(inbound, text, limited)
        return self._handle_freetext(api, inbound, user, text, via)

    # ── the log line ───────────────────────────────────────────────────

    @staticmethod
    def log_route(inbound: Inbound, what: str, route: Route, note: str = "") -> Route:
        """印 [ROUTE] 那一行並回傳 route（fallback 也用它，在動手之前先印）。
        note：只印在終端機、不放進 Route 的說明（例如對別人隱形的擁有者指令其實是哪一個）。"""
        detail = " ".join(x for x in (route.path, f"({route.reason})" if route.reason else "",
                                      f"[{note}]" if note else "") if x)
        shown = what if len(what) <= 120 else what[:120] + "…"
        logging.info("[ROUTE] %s @%s(%s) %r → %s%s", inbound.channel, inbound.username or "-", inbound.user_id,
                     shown, route.kind, f" {detail}" if detail else "")
        return route

    # ── commands ───────────────────────────────────────────────────────

    def _run(self, api, inbound, user, text, node, args, via) -> Route:
        chat_id = inbound.chat_id
        if node is None:
            # 對話中的子指令（/save、/list…）不在樹上，照文字交給對話 handler
            if self.conv_manager and self.conv_manager.is_active(chat_id):
                return self._handle_freetext(api, inbound, user, text, via)
            self._expired_notice(api, chat_id)
            return self._unknown(api, inbound, text)
        if node.is_group:
            if self._hidden_from(user, node):
                return self._unknown(api, inbound, text, node)
            route = self.log_route(inbound, text, Route(GROUP_MENU, node.path))
            api.send_message(chat_id, self.group_menu(user, node))
            return route
        decision = self.registry.authorize(user, node, via, chat_id)
        if decision.reason == "owner_only":
            return self._unknown(api, inbound, text, node)
        if not decision.allowed:
            route = self.log_route(inbound, text, Route(DENIED, node.path, decision.reason))
            api.send_message(chat_id, decision.message)
            for observer in self.observers:
                if hasattr(observer, "denied"):
                    observer.denied(api, inbound, user, node, decision)
            return route
        age = self.age(inbound)
        if via == TYPED and node.effect != READ and age > self.timing.stale_message and self.stale is not None:
            # bot 離線時累積的舊指令：唯讀的照跑，會改東西的先問（core/timing.py）
            route = self.log_route(inbound, text, Route(STALE, node.path, f"{int(age // 60)}m"))
            self.stale.stale_command(api, inbound, node, age)
            return route
        route = self.log_route(inbound, text, Route(COMMAND, node.path))
        try:
            self._observed(STEP_COMMAND, api, inbound, user, node, lambda a: node.fn(a, chat_id, user, args))
        except Exception as e:
            logging.exception("Error in command %s: %s", node.path, e)
            api.send_message(chat_id, self.texts.command_error)
            return replace(route, error=str(e))
        return route

    def _observed(self, kind: str, api, inbound: Inbound, user, node: Node, call: Callable) -> None:
        """call(api) 跑 handler；有 around 的 observer 一層包一層（洋蔥式，第一個 observer 在最外層）。"""

        def wrap(observer, inner):
            return lambda a: observer.around(kind, a, inbound, user, node, inner)

        run = call
        for observer in reversed(self.observers):
            if hasattr(observer, "around"):
                run = wrap(observer, run)
        run(api)

    def _unknown(self, api, inbound: Inbound, text: str, hidden=None) -> Route:
        """樹上沒有的指令。擁有者專用的節點對別人也走這裡（hidden＝那個節點）：回的話、Route 都跟
        真的不存在一模一樣，別人連「有這個指令」都不該知道。真正的原因只印在終端機。"""
        note = f"其實是擁有者專用的 {hidden.path}，對別人隱形" if hidden is not None else ""
        route = self.log_route(inbound, text, Route(UNKNOWN_COMMAND), note)
        api.send_message(inbound.chat_id, self.texts.unknown_command.format(command=text.split()[0]))
        return route

    def _hidden_from(self, user, node) -> bool:
        """整個節點（或群組）只給擁有者，而這個人不是：對他來說它不存在。"""
        return node.policy.owner_only and not self.registry.is_owner(user)

    def _rate_limited(self, api, chat_id, user, node, is_command: bool) -> Optional[Route]:
        """None 表示放行；擋下來就回 Route（提示訊息已經送了）。誰擋、為什麼擋全在 RateLimiter.admit()。"""
        if self.rate_limiter is None:
            return None
        verdict = self.rate_limiter.admit(user, is_command=is_command,
                                          quota_exempt=node is not None and node.quota_exempt)
        if verdict is None:
            return None
        if verdict.message:
            api.send_message(chat_id, verdict.message)
        return Route(IGNORED if verdict.silent else RATE_LIMITED, reason=verdict.reason)

    # ── buttons ────────────────────────────────────────────────────────

    def _on_button(self, api, inbound: Inbound) -> Route:
        cb = inbound.button
        what = f"[按鈕] {cb.data}"
        found = self.registry.callback_for(cb.data)
        if found is None:
            api.answer_callback_query(cb.cq_id, text=self.texts.button_unknown)
            return self.log_route(inbound, what, Route(BUTTON_UNKNOWN))
        node, handler = found
        clicker = self.user_manager.get_or_create(cb.clicker_id)
        if self._hidden_from(clicker, node):
            # 跟沒綁定的前綴回一樣的話：別人偽造擁有者專用的按鈕，看不出那是什麼（同 _unknown）
            api.answer_callback_query(cb.cq_id, text=self.texts.button_unknown)
            return self.log_route(inbound, what, Route(BUTTON_UNKNOWN), f"其實是擁有者專用的 {node.path}，對別人隱形")
        # 危險或 🔐 指令的按鈕有期限（core/timing.py）：幾天前的危險按鈕不該還按得動
        if cb.message_date and (node.effect == DANGER or node.policy.elevated):
            age = self._clock() - float(cb.message_date)
            if age > self.timing.button_ttl:
                api.answer_callback_query(cb.cq_id, text=self.texts.button_expired.format(minutes=int(age // 60)))
                api.remove_buttons(cb.chat_id, cb.message_id)
                return self.log_route(inbound, what, Route(BUTTON_DENIED, node.path, "expired"))
        # callback_data 是客戶端送來的、可以偽造：用點擊者的身分檢查按鈕所屬節點的權限
        decision = self.registry.authorize(clicker, node, BUTTON, cb.chat_id)
        if not decision.allowed:
            api.answer_callback_query(cb.cq_id, text=decision.message)
            return self.log_route(inbound, what, Route(BUTTON_DENIED, node.path, decision.reason))
        route = self.log_route(inbound, what, Route(BUTTON_ROUTE, node.path))
        self._observed(STEP_BUTTON, api, inbound, clicker, node, lambda a: handler(a, cb))
        return route

    # ── free text ──────────────────────────────────────────────────────

    def _handle_freetext(self, api, inbound: Inbound, user, text: str, via: str) -> Route:
        chat_id = inbound.chat_id
        session = self.conv_manager.get(chat_id) if self.conv_manager else None
        if session is not None:
            self.conv_manager.touch(chat_id)
            route = self.log_route(inbound, text, Route(CONVERSATION, reason=session.session_type))
            try:
                session.handler(api, chat_id, user, text)
            except Exception as e:
                logging.exception("Error in conversation handler for chat %s: %s", chat_id, e)
                api.send_message(chat_id, self.texts.conversation_error)
                return replace(route, error=str(e))
            return route
        self._expired_notice(api, chat_id)
        if chat_id != user.tg_id:
            return self.log_route(inbound, text, Route(IGNORED, reason="group"))   # 群組裡的閒聊不回
        if self.fallback is not None and self.fallback.accepts(user, chat_id, via):
            return self.fallback.handle(api, inbound, user, text, self.age(inbound))
        route = self.log_route(inbound, text, Route(NOT_UNDERSTOOD_ROUTE))
        api.send_message(chat_id, self.texts.not_understood)
        return route

    def _expired_notice(self, api, chat_id: int) -> None:
        """剛剛有一段問答因為閒置太久過期了：先說一聲，這句再照一般訊息處理（不會被舊問答吃掉）。"""
        old = self.conv_manager.pop_expired(chat_id) if self.conv_manager else None
        if old is not None:
            idle = old.idle_seconds
            span = f"{int(idle // 60)} 分鐘" if idle >= 60 else f"{int(idle)} 秒"
            api.send_message(chat_id, self.texts.expired.format(name=old.name, span=span))

    def age(self, inbound: Inbound) -> float:
        """這則訊息送出到現在幾秒（不知道就是 0）。"""
        return max(0.0, self._clock() - inbound.sent_at) if inbound.sent_at else 0.0
