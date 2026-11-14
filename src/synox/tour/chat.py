"""
/tutorial：開始或接著上次的新手教學。

    /tutorial              開始／接著上次（走完過的＝從頭複習）
    /tutorial restart      從頭來（做過的清掉）
    /tutorial list         有哪些教學（工具也可以附自己的）
    /tutorial <名字>       走那一份
別的叫法：/tour、/start tutorial，以及私訊直接打「開始教學」「教學」「新手教學」「start tutorial」「tutorial」。

- 網頁：回一則訊息＋一個 tour 區塊（WebText.blocks），網頁的 static/tour.js 看到就在**真的畫面上**指給他看
  （聚光圈＋小卡）；那則訊息也有「在畫面上帶我走」的按鈕，之後隨時能再按。
- Telegram／Discord：沒有畫面可以指，一步一則步驟卡（原地改）＋〔上一步〕〔下一步〕〔先離開〕；
  要在網頁上做的那幾步，說一聲「在網頁打 /tutorial，我會直接指給你看」。
- 按鈕 callback：tour:go:<教學>:<第幾步>、tour:x:<教學>:<第幾步>（離開）、tour:end:<教學>（走完）；按的人要過 /tutorial 的 authorize。
- /tutorial 是唯讀的系統指令（只存這個人自己的進度）、不給 AI 當工具（ai=False）、不算額度。
"""

from __future__ import annotations

import re
from typing import List

from synox.tour.schema import Step, Tour

COMMAND = "tutorial"
PREFIX = "tour:"
RESTART_WORDS = ("restart", "重來", "從頭", "reset")
LIST_WORDS = ("list", "清單", "全部")
START_ARGS = ("tutorial", "tour", "教學")
PHRASES = ("start tutorial", "start the tutorial", "tutorial", "開始教學", "教學", "新手教學", "帶我走一遍")
HELP_LINE = "🎓 第一次用？打 /tutorial，我一步一步帶你走一遍（約 5 分鐘）。忘了隨時再打一次就能複習。"
WEB_NOTE = "🖥️ 這一步在網頁上看最清楚：在電腦打開 SYNOX 網頁，打 /tutorial，我會直接在畫面上指給你看。"
_TRAIL = re.compile(r"[\s。．.!！?？~～]+$")


def normalize(text: str) -> str:
    return _TRAIL.sub("", re.sub(r"\s+", " ", (text or "").strip().lower()))


def is_phrase(text: str) -> bool:
    return normalize(text) in PHRASES


def _visible(eng, user, tour: Tour) -> List[Step]:
    return eng.steps(user, tour)


def card(tour: Tour, steps: List[Step], at: int) -> str:
    step = steps[at]
    head = f"🎓 {tour.title}（{at + 1}／{len(steps)}）"
    if tour.source:
        head += f"\n（這份教學是工具「{tour.source}」附的）"
    lines = [head, "", f"【{step.title}】", step.chat or step.body]
    if step.try_text:
        lines += ["", f"可以直接打：{step.try_text}"]
    if step.anchors and not step.chat:
        lines += ["", WEB_NOTE]
    return "\n".join(lines)


def keyboard(tour: Tour, steps: List[Step], at: int) -> dict:
    row = []
    if at > 0:
        row.append({"text": "◀️ 上一步", "callback_data": f"{PREFIX}go:{tour.id}:{at - 1}"})
    if at + 1 < len(steps):
        row.append({"text": "下一步 ▶️", "callback_data": f"{PREFIX}go:{tour.id}:{at + 1}"})
    else:
        row.append({"text": "✅ 完成", "callback_data": f"{PREFIX}end:{tour.id}"})
    return {"inline_keyboard": [row, [{"text": "先離開", "callback_data": f"{PREFIX}x:{tour.id}:{at}"}]]}


def finish_text(tour: Tour) -> str:
    return (f"🎉 「{tour.title}」走完了！\n"
            "之後忘了怎麼用，隨時打 /tutorial 再看一次（/tutorial restart 從頭來）。")


def install(app, eng) -> None:
    registry = app.registry

    def send_list(api, chat_id, user):
        tours = [t for t in eng.tours() if eng.steps(user, t)]
        if not tours:
            api.send_message(chat_id, "現在沒有教學可以看。")
            return
        lines = ["🎓 可以看的教學："]
        for t in tours:
            rec = eng.record(user, t)
            mark = "✅ 走完過" if eng.finished(user, t) else ("⏸ 走到一半" if rec else "還沒走過")
            src = f"（工具「{t.source}」附的）" if t.source else ""
            lines.append(f"• {t.title}{src}：/tutorial {t.id}（約 {t.minutes} 分鐘，{mark}）")
        lines.append("從頭來：/tutorial restart 或 /tutorial restart <名字>")
        api.send_message(chat_id, "\n".join(lines))

    def run(api, chat_id, user, tour_id: str = "", restart: bool = False):
        if tour_id and eng.get(tour_id) is None:
            api.send_message(chat_id, f"找不到教學「{tour_id}」。打 /tutorial list 看有哪些。")
            return
        tour, at = eng.start(user, tour_id, restart=restart)
        if tour is None:
            api.send_message(chat_id, "現在沒有教學可以看。")
            return
        steps = _visible(eng, user, tour)
        if getattr(api, "channel_name", "") == "web":
            from synox.present.web import WebText
            again = "從頭" if at == 0 else f"從第 {at + 1} 步接著"
            text = (f"🎓 好，{again}走「{tour.title}」（共 {len(steps)} 步，約 {tour.minutes} 分鐘）。\n"
                    "看畫面上亮起來的地方，照著小卡做就好；隨時可以按「先離開」，之後打 /tutorial 會接著走。")
            api.send_message(chat_id, WebText(text, [{"type": "tour", "tour": tour.id, "step": steps[at].id}]))
            return
        api.send_message(chat_id, card(tour, steps, at), reply_markup=keyboard(tour, steps, at))

    def cmd_tutorial(api, chat_id, user, args):
        words = [a for a in (args or []) if a]
        if words and words[0].lower() in LIST_WORDS:
            send_list(api, chat_id, user)
            return
        restart = bool(words) and words[0].lower() in RESTART_WORDS
        if restart:
            words = words[1:]
        run(api, chat_id, user, words[0].lower() if words else "", restart=restart)

    def on_button(api, cb):
        user = app.users.get_or_create(cb.clicker_id)
        parts = cb.data[len(PREFIX):].split(":")
        what, tour_id = (parts + ["", ""])[:2]
        tour = eng.get(tour_id)
        if tour is None or not _visible(eng, user, tour):
            api.answer_callback_query(cb.cq_id, text="這份教學不在了。")
            return
        steps = _visible(eng, user, tour)
        try:
            at = min(max(0, int(parts[2])), len(steps) - 1) if len(parts) > 2 else 0
        except ValueError:
            at = 0
        if what == "end":
            eng.save(user, tour.id, step=steps[-1].id, state="finished", done=[s.id for s in steps])
            api.edit_message_text(cb.chat_id, cb.message_id, finish_text(tour))
        elif what == "x":
            eng.save(user, tour.id, step=steps[at].id, state="paused")
            api.edit_message_text(cb.chat_id, cb.message_id,
                                  f"好，先停在「{steps[at].title}」。之後打 /tutorial 就會從這裡接著走。")
        else:
            prev = [s.id for s in steps[:at]]
            eng.save(user, tour.id, step=steps[at].id, state="active", done=prev)
            api.edit_message_text(cb.chat_id, cb.message_id, card(tour, steps, at),
                                  reply_markup=keyboard(tour, steps, at))
        api.answer_callback_query(cb.cq_id)

    registry.root_leaf(COMMAND, cmd_tutorial, "新手教學：一步一步帶你認識 SYNOX（隨時可以再看）",
                       usage="[restart|list|名字]", legacy=("/tour",), ai=False, quota_exempt=True)
    registry.bind_callback(PREFIX, COMMAND, on_button)
    _wrap_start(app, cmd_tutorial)
    _wrap_help(app)
    _wrap_phrases(app)


def _wrap_start(app, cmd_tutorial) -> None:
    """/start tutorial＝/tutorial（擁有者說「command 就是 start tutorial」）。"""
    node = app.registry.root.children.get("start")
    if node is None or node.fn is None:
        return
    original = node.fn

    def start(api, chat_id, user, args):
        if args and str(args[0]).lower() in START_ARGS:
            return cmd_tutorial(api, chat_id, user, list(args[1:]))
        return original(api, chat_id, user, args)

    node.fn = start


def _wrap_help(app) -> None:
    """/help（沒帶參數時）多一行指到 /tutorial。要在 packs/library.install 之前包，「去哪裡裝工具」才會留在最後一則。"""
    node = app.registry.root.children.get("help")
    if node is None or node.fn is None:
        return
    original = node.fn

    def help_with_tutorial(api, chat_id, user, args):
        original(api, chat_id, user, args)
        if not args:
            api.send_message(chat_id, HELP_LINE)

    node.fn = help_with_tutorial


def _wrap_phrases(app) -> None:
    """私訊裡只打「開始教學」「start tutorial」這種話（整句就是這幾個字）＝/tutorial。
    在 dispatcher 收到之前改寫（跟打 /tutorial 走同一條路、同一個 authorize）；正在問答中的不改（那是在回答問題）。"""
    from dataclasses import replace

    dispatcher = app.dispatcher
    original = dispatcher.handle

    def handle(api, inbound, *args, **kw):
        text = inbound.text or ""
        if inbound.button is None and text and not text.startswith("/") and is_phrase(text) \
                and inbound.chat_id == inbound.user_id:
            conv = getattr(dispatcher, "conv_manager", None)
            if conv is None or conv.get(inbound.chat_id) is None:
                inbound = replace(inbound, text="/" + COMMAND)
        return original(api, inbound, *args, **kw)

    dispatcher.handle = handle
