"""
表單指令：一個指令宣告它要哪些欄位，打字的人和 AI 各用最順的方式填完。

    forms = Forms(conversations, stepup)
    forms.leaf(registry.group("clip"), "add", save_clip, "收藏一支影片", fields=[
        Field("url", "影片網址", required=True, check=must_be_url),
        Field("title", "標題"), Field("category", "分類")], default=True, effect=WRITE)

    def save_clip(api, chat_id, user, values):     # 欄位都檢查過之後才被呼叫一次
        ...

- 打字：`/clip https://… title=教學 category=剪輯` 一次給齊就直接存。
  缺必填欄位 → 一題一題問；只給了必填（沒有任何 key=）而還有選填欄位 → 用一則訊息問要不要補，
  回 key=value（可多個、可換行）或 ok。
- AI（之後接 AI 工具橋時）：拿到的是具名參數（Field → JSON schema），必填沒給齊就回錯誤、在聊天裡問齊再呼叫一次。
- 排程：必填欄位沒寫齊的不能排（用 registry.parse_fields 檢查）。
- 表單指令不是 interactive：值給齊時是一次性的，可以排程。問答只在打字缺欄位時出現。
- 驗證碼欄位（Field.fresh_code）在這裡統一驗（StepUp.verify_once），handler 裡不再自己驗碼：
  打字帶 code=、問答時當場打、或依核准單執行時放進來的一次性票，都在送出前驗。
  問答時是**收到就驗**（兩組碼時第一組不會等到第二組打完才驗，碼一分鐘就過期）。
- 有條件的驗證碼欄位（Field.needed，例如風險高才要第二組驗證器）：其他欄位填完才判斷要不要。
- precheck（Node.precheck）：在問驗證碼之前跑的檢查（在不在白名單、凍結了沒、能不能從這個入口下令…），
  不過就直接說不行——不會讓人打了碼才被拒絕。送出前會再跑一次（中間狀態可能變了）。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence

from isdtelekit.core.conversation import ConversationManager
from isdtelekit.core.registry import Field, Group, Node, codes_needed, field_pattern, parse_fields

SKIP_WORDS = ("ok", "好", "不用", "-", "skip")


def usage_of(fields: Sequence[Field]) -> str:
    """'<影片網址> [title=…] [category=a|b]'：沒寫 usage 的表單指令自動產生這一行。"""
    parts = []
    for i, f in enumerate(fields):
        if i == 0 and f.required:
            parts.append(f"<{f.ask}>")
        else:
            hint = "|".join(f.choices) if f.choices else "…"
            parts.append(f"[{f.name}={hint}]" if not f.required else f"{f.name}=<{f.ask}>")
    return " ".join(parts)


class Forms:

    def __init__(self, conv_manager: ConversationManager, stepup=None):
        self._conv = conv_manager
        self._stepup = stepup                 # 有 fresh_code 欄位的表單才用到；沒給就一律拒絕（fail closed）
        self._submits: Dict[str, Callable] = {}

    def leaf(self, group: Group, name: str, submit: Callable, summary: str, *,
             fields: Sequence[Field], precheck: Optional[Callable] = None, **kw) -> Node:
        """掛一個表單指令。submit(api, chat_id, user, values: dict)；其他參數同 Group.leaf。"""
        fields = tuple(fields)

        def run(api, chat_id, user, args):
            text = " ".join(args)
            values, missing, errors = parse_fields(fields, text)
            if errors:
                api.send_message(chat_id, "❌ " + "；".join(errors))
                return
            # 有寫任何欄位名= 就當作已經填完（網址裡的 ?v= 不算）
            gave_keys = bool(field_pattern(fields).search(text))
            optional = [f for f in fields if not f.required and not f.fresh_code and f.name not in values]
            missing = [f for f in missing if not f.fresh_code]   # 驗證碼另外算（codes_needed），永遠最後問
            if not missing and (gave_keys or not optional):
                if not any(f.name not in values for f in codes_needed(fields, values)):
                    self._submit(submit, api, chat_id, user, node, values)
                    return
                optional = []                       # 只差驗證碼：不再問選填的
            if getattr(api, "via_ai", False):
                # 依核准單執行：要的每一組碼都該在核准時驗過（票）。少了就是核准之後情況變了，
                # 重新核准，不在工具呼叫中間另開問答。
                api.send_message(chat_id, "❌ 這個動作現在要的驗證碼沒有在核准時驗過（情況可能變了），請重新請求核准。")
                return
            self._conv.supersede(api, chat_id)      # 新的互動指令取代舊的問答（core/timing.py）
            self._wizard(api, chat_id, user, node, submit, values, missing, optional)

        node = group.leaf(name, run, summary, usage=kw.pop("usage", usage_of(fields)), **kw)
        node.fields = fields
        node.precheck = precheck
        self._submits[node.path] = submit
        return node

    def prefill(self, node: Node, api, chat_id, user, values: Dict[str, str]) -> None:
        """按鈕帶進來的值先填好，其他的照問答問（選填的也問一次，例如「要不要指定時間」）。"""
        values = {k: v for k, v in values.items() if v}
        missing = [f for f in node.fields if f.required and not f.fresh_code and f.name not in values]
        optional = [f for f in node.fields if not f.required and not f.fresh_code and f.name not in values]
        self._conv.supersede(api, chat_id)
        self._wizard(api, chat_id, user, node, self._submits[node.path], values, missing, optional)

    @staticmethod
    def _with_defaults(fields, values: Dict[str, str]) -> Dict[str, str]:
        for f in fields:
            if f.name not in values and f.default:
                values[f.name] = f.default
        return values

    @staticmethod
    def _refused(node: Node, api, values: Dict[str, str]) -> Optional[str]:
        if node.precheck is None:
            return None
        return node.precheck(values, bool(getattr(api, "via_ai", False)), str(getattr(api, "channel_name", "")))

    def _verify(self, api, chat_id, f: Field, code: str) -> bool:
        if self._stepup is None:
            api.send_message(chat_id, "❌ 這個指令要驗證碼，但這裡沒有接上驗證器。")
            return False
        ok, msg = self._stepup.verify_once(str(code or ""), factor=f.factor)
        if not ok:
            api.send_message(chat_id, msg if msg.startswith(("❌", "🔒", "🔐")) else f"❌ {msg}")
        return ok

    def _submit(self, submit, api, chat_id, user, node: Node, values: Dict[str, str],
                verified: Sequence[str] = ()) -> None:
        values = self._with_defaults(node.fields, values)
        problem = self._refused(node, api, values)
        if problem:
            api.send_message(chat_id, problem)
            return
        for f in codes_needed(node.fields, values):
            if f.name not in verified and not self._verify(api, chat_id, f, values.get(f.name, "")):
                return
        submit(api, chat_id, user, values)

    def _wizard(self, api, chat_id, user, node: Node, submit, values, missing: List[Field],
                optional: List[Field]) -> None:
        # 驗證碼類的欄位（fresh_code）永遠最後問：收到就驗，最後一組驗過就送出，不會先存起來等你回完選填欄位才驗。
        # 要哪幾組碼（Field.needed）等其他欄位都填完才知道，所以到要問碼的時候才算。
        fields = node.fields
        queue = [f for f in missing if not f.fresh_code]
        state = {"optional_asked": False, "waiting": None, "codes": None, "verified": []}

        def ask_next():
            if queue:
                f = queue[0]
                state["waiting"] = f
                choices = f"（{'/'.join(f.choices)}）" if f.choices else ""
                api.send_message(chat_id, f"✏️ {f.ask}{choices}\n（/exit 取消）")
                return
            rest = [f for f in optional if f.name not in values]
            if rest and not state["optional_asked"]:
                state["optional_asked"] = True
                state["waiting"] = None
                lines = [f"  {f.name}=  {f.ask}" + (f"（{'/'.join(f.choices)}）" if f.choices else "") for f in rest]
                api.send_message(chat_id, "要補充這些嗎？回 key=value（可以多個、可以換行），或回 ok 直接存：\n"
                                 + "\n".join(lines))
                return
            if state["codes"] is None:
                self._with_defaults(fields, values)
                problem = self._refused(node, api, values)
                if problem:                          # 問碼之前先確定這件事能做
                    self._conv.end(chat_id)
                    api.send_message(chat_id, problem)
                    return
                state["codes"] = [f for f in codes_needed(fields, values) if f.name not in values]
            if state["codes"]:
                f = state["codes"][0]
                state["waiting"] = f
                wait = int(self._conv.timing.code_prompt)
                self._conv.set_idle(chat_id, self._conv.timing.code_prompt)
                api.send_message(chat_id, f"🔐 {f.ask}（{wait} 秒內回覆，收到就驗）\n（/exit 取消）")
                return
            self._conv.end(chat_id)
            self._submit(submit, api, chat_id, user, node, values, state["verified"])

        def handler(api_, chat_id_, user_, text):
            text = text.strip()
            f = state["waiting"]
            if f is not None and f.fresh_code:
                code = text.split()[0] if text else ""
                if not self._verify(api, chat_id, f, code):   # 收到就驗；錯了就結束，重打指令（防一直猜）
                    self._conv.end(chat_id)
                    return
                values[f.name] = code
                state["verified"].append(f.name)
                state["codes"].remove(f)
            elif f is not None:
                got, _missing, errors = parse_fields((f,), text)
                if errors or f.name not in got:
                    api.send_message(chat_id, "❌ " + ("；".join(errors) or f"{f.ask}不能空白") + "，再輸入一次。")
                    return
                values[f.name] = got[f.name]
                queue.remove(f)
            elif text.lower() not in SKIP_WORDS:
                got, _missing, errors = parse_fields(fields, "\n" + text if field_pattern(fields).search(text) else "")
                if errors or not got:
                    api.send_message(chat_id, "❌ " + ("；".join(errors) or "看不懂，請用 key=value，或回 ok")
                                     + "。")
                    return
                values.update(got)
            ask_next()

        self._conv.start(chat_id, user.tg_id, node.command, handler, label=node.command)
        ask_next()
