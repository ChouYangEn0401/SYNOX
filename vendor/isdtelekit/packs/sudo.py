"""
/sudo、/sudo_off（只有機器擁有者、只在私訊）：用手機驗證器的 6 位數解鎖 🔐 指令一段時間（security/stepup.py）。

- /sudo 123456 直接解鎖；只打 /sudo 就開一段只等 code_prompt 秒（120）的問答，下一則訊息才是驗證碼——
  不然「先打 /sudo、再貼 6 位數」時，那串數字會被當成自由文字丟給別的東西。新的 /sudo 取代任何舊的問答。
- 被 🔐 擋下的指令，2 分鐘（choice_ttl）內 /sudo 成功 → 附一顆「▶ 繼續 /xxx」，不用重打一次（SudoContinue，
  接在 dispatcher 的 observers 上收「被擋下」）。按「繼續」＝把原本那則重送一次，權限照常重新檢查。
- 驗證器的密鑰只在本機設定：`.venv\\Scripts\\python.exe -m isdtelekit.security.setup`。沒設定就一律拒絕。
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Callable, Dict, Tuple

from isdtelekit.core.channel import Inbound
from isdtelekit.core.registry import WRITE
from isdtelekit.core.timing import Pending
from isdtelekit.packs.basics import EXPIRED_CHOICE


class SudoContinue:
    """記下最近被 🔐 擋下的指令；解鎖成功時附「繼續」按鈕。"""

    def __init__(self, app, clock: Callable[[], float] = time.time):
        self._app = app
        self._clock = clock
        self.pending = Pending(clock)
        self._denied: Dict[int, Tuple[Inbound, float]] = {}

    # DispatchObserver.denied
    def denied(self, api, inbound, user, node, decision) -> None:
        if decision.reason == "stepup" and inbound.text:
            self._denied[inbound.user_id] = (inbound, self._clock())

    def offer(self, api, chat_id: int, user_id: int) -> None:
        item = self._denied.pop(user_id, None)
        if item is None or self._clock() - item[1] > self._app.timing.choice_ttl:
            return
        inbound = item[0]
        token = self.pending.put(inbound, user_id, self._app.timing.choice_ttl)
        command = inbound.text.split()[0]
        api.send_message(chat_id, f"剛剛被擋下的 {command}，要繼續嗎？",
                         reply_markup={"inline_keyboard": [[{"text": f"▶ 繼續 {command}",
                                                             "callback_data": f"sudo_go:{token}"}]]})

    def on_button(self, api, cb) -> None:
        token = cb.data.split(":", 1)[1] if ":" in cb.data else ""
        inbound = self.pending.take(token, cb.clicker_id)
        api.answer_callback_query(cb.cq_id)
        api.remove_buttons(cb.chat_id, cb.message_id)
        if inbound is None:
            api.send_message(cb.chat_id, EXPIRED_CHOICE)
            return
        logging.info("[SUDO] continue %s", inbound.text.split()[0])
        self._app.dispatcher.handle(api, replace(inbound, chat_id=cb.chat_id, sent_at=self._clock(), edited=False))


def install(app, *, group: str = "sudo") -> None:
    if app.stepup is None:
        raise ValueError("packs.sudo 需要 build_app(use_stepup=True)。")
    stepup, conv = app.stepup, app.conversations
    app.registry.ensure_group(group, "🔐 解鎖", "用手機驗證器解鎖 🔐 指令一段時間", owner_only=True, private_only=True)
    cont = SudoContinue(app)
    app.dispatcher.add_observer(cont)

    def cmd_sudo(api, chat_id, user, args):
        if not stepup.configured:
            api.send_message(chat_id, stepup.unset_message)
            return
        if args:
            _try(api, chat_id, user, args[0])
            return
        left = stepup.remaining(user.tg_id)
        if left:
            api.send_message(chat_id, f"🔓 已解鎖，還剩 {left // 60 + 1} 分鐘。")
            return
        conv.supersede(api, chat_id)
        wait = conv.timing.code_prompt
        conv.start(chat_id, user.tg_id, "sudo", _on_code, idle_seconds=wait, label="/sudo")
        api.send_message(chat_id, f"🔐 貼上手機驗證器現在顯示的 6 位數（{int(wait)} 秒內）。\n（/exit 取消）")

    def _on_code(api, chat_id, user, text):
        """對話中收到的那一則就是驗證碼。對或錯都結束，不要一直纏著使用者（也防一直猜）。"""
        conv.end(chat_id)
        _try(api, chat_id, user, text.strip().split()[0] if text.strip() else "")

    def _try(api, chat_id, user, code: str) -> None:
        ok, text = stepup.elevate(user.tg_id, code)
        api.send_message(chat_id, text if ok else f"{text}\n\n再試一次就直接打 /sudo <6 位數>。")
        if ok:
            cont.offer(api, chat_id, user.tg_id)

    def cmd_sudo_off(api, chat_id, user, args):
        api.send_message(chat_id, "🔒 已鎖回去。" if stepup.drop(user.tg_id) else "本來就沒解鎖。")

    g = app.registry.group(group)
    on = g.leaf("on", cmd_sudo, "用手機驗證器的 6 位數解鎖 🔐 指令一段時間", default=True, usage="<6 位數>",
                effect=WRITE, ai=False)
    g.leaf("off", cmd_sudo_off, "提早鎖回去", effect=WRITE, ai=False)
    app.registry.bind_callback("sudo_go:", on.path, cont.on_button)
