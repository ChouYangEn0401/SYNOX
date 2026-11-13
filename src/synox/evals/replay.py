"""
離線重放：一個「照劇本回話」的假 adapter 取代真的 AI，接在**真的** AgentLoop 上跑一題（synox.app.build 建出整支
SYNOX：暫存資料夾、真的保管箱、空的 pack 資料夾＋這題的假工具）。工具清單、ai_decision、第 4 關、核准卡、步數上限、
對話記憶都是真的外框；只有「AI 回什麼」照劇本。

劇本（evals/assistant/replies/<來源>/<題目 id>.json）＝每一輪、每一步 AI 回了什麼，對應 Reply／ToolCall：

    {"case": "note-01", "source": "reference",
     "turns": [[{"tool_calls": [{"name": "note__add", "args": {"text": "明天帶傘"}, "result": "已記下：明天帶傘"}]},
                {"text": "記好了。"}]]}

`result`＝錄的時候這個呼叫交回 AI 的字（拿掉分隔符之後）；重放時對不上，代表題目或外框改了、後面的回覆已經不成立，
這一題標 replay_mismatch（不硬算）。其他會標 replay_mismatch 的：輪數不同、劇本叫了這一輪沒有提供的工具、
迴圈要的步數比劇本多、或劇本還有沒用到的步（迴圈提早結束，而且不是因為步數上限）。`stamp()` 把實際的結果填進 result。

完成宣稱檢查（agent/claims.py，docs/adr/0008）：劇本可以寫 `"completion_guard": "on"`（錄的時候閘門開著，
劇本裡就有「宣稱 → 系統修正 → 真的呼叫」那幾步）；沒寫＝"off"（以前錄的劇本都是沒有閘門的外框）。
內建的系統指令（remind__add…）真的執行了也算進 executed（從迴圈的證據帳本拿，不是假工具的紀錄）。
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from synox.agent import delimit
from synox.agent import tools as tools_mod
from synox.evals import fake_tools
from synox.evals.cases import BUILTIN_TOOLS, Case
from synox.llm.base import TOOL, ChatAdapter, LLMError, Message, Reply, ToolCall, ToolSpec
from synox.packs import kit

DEFAULT_MAX_STEPS = 6            # 跟 config 的 llm.max_steps 預設一樣
EVAL_OWNER_ID = 100001           # 暫存的 SYNOX 裡的擁有者（假的 id）
MISMATCH = "replay_mismatch"


class ReplayError(ValueError):
    """劇本檔格式不對。"""


# ── 劇本檔 ─────────────────────────────────────────────────────────────

def parse_recording(raw, where: str = "（劇本）") -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("case"), str):
        raise ReplayError(f"{where}：最外層要是有 case 的物件")
    unknown = set(raw) - {"case", "source", "note", "turns", "expected_failures", "completion_guard"}
    if unknown:
        raise ReplayError(f"{where}：有不認得的欄位 {sorted(unknown)}")
    turns = raw.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ReplayError(f"{where}：turns 要是「每一輪的步驟清單」的清單")
    for t, steps in enumerate(turns, 1):
        if not isinstance(steps, list) or not steps:
            raise ReplayError(f"{where}：第 {t} 輪要至少一步")
        for s, step in enumerate(steps, 1):
            if not isinstance(step, dict) or set(step) - {"text", "tool_calls"} or not step:
                raise ReplayError(f"{where}：第 {t} 輪第 {s} 步要是 {{\"text\": …}} 或 {{\"tool_calls\": […]}}")
            if "text" in step and not isinstance(step["text"], str):
                raise ReplayError(f"{where}：第 {t} 輪第 {s} 步的 text 要是字串")
            for call in step.get("tool_calls", []):
                if (not isinstance(call, dict) or not isinstance(call.get("name"), str)
                        or not isinstance(call.get("args", {}), dict) or set(call) - {"name", "args", "result"}
                        or not isinstance(call.get("result", ""), str)):
                    raise ReplayError(f"{where}：第 {t} 輪第 {s} 步的 tool_calls 每項要是 {{name, args, result?}}")
    if raw.get("completion_guard", "off") not in ("on", "off"):
        raise ReplayError(f"{where}：completion_guard 只能是 on 或 off")
    failures = raw.get("expected_failures", [])
    if not isinstance(failures, list) or not all(isinstance(f, str) for f in failures):
        raise ReplayError(f"{where}：expected_failures 要是檢查名稱的清單")
    return raw


def load_replies(folder: str) -> Dict[str, dict]:
    """資料夾裡每個 <題目 id>.json → {題目 id: 劇本}。"""
    if not os.path.isdir(folder):
        raise ReplayError(f"找不到回覆資料夾：{folder}")
    out: Dict[str, dict] = {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError) as e:
            raise ReplayError(f"{name}：讀不了（{type(e).__name__}: {e}）")
        rec = parse_recording(raw, name)
        if os.path.splitext(name)[0] != rec["case"]:
            raise ReplayError(f"{name}：檔名要跟 case 一樣（{rec['case']}.json）")
        out[rec["case"]] = rec
    return out


def dump_recording(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, indent=2) + "\n"


# ── 照劇本回話的 adapter ────────────────────────────────────────────────

class ReplayAdapter(ChatAdapter):
    """一次 chat 吐劇本的一步。不同步時記下 mismatch 並丟 LLMError（迴圈收掉這一輪）。"""

    kind = "replay"
    name = "照劇本回話（離線重放）"
    supports_tools = True
    supports_vision = True            # 看圖題（docs/adr/0021）：圖照常放進 user 訊息，劇本照錄的回

    def __init__(self, turns: Sequence[Sequence[dict]], *, check_results: bool = True):
        self.turns = [list(t) for t in turns]
        self.check_results = check_results
        self.turn = -1
        self.step = 0
        self.mismatch: Optional[str] = None
        self.attempted: List[List[Tuple[str, dict]]] = []
        self.offered: List[str] = []
        self.observed: Dict[Tuple[int, int, int], str] = {}   # (輪, 步, 第幾個呼叫) → 實際交回 AI 的字
        self.last_had_calls = False
        self._pending: List[Tuple[str, dict, Tuple[int, int, int]]] = []

    def begin_turn(self) -> None:
        self.turn += 1
        self.step = 0
        self.last_had_calls = False
        self._pending = []
        self.attempted.append([])

    def remaining(self) -> int:
        return len(self.turns[self.turn]) - self.step if 0 <= self.turn < len(self.turns) else 0

    def _fail(self, reason: str) -> Reply:
        if self.mismatch is None:
            self.mismatch = reason
        raise LLMError(f"重放不同步：{reason}")

    def _collect(self, messages: Sequence[Message]) -> None:
        if not self._pending:
            return
        results = {m.tool_call_id: delimit.unwrap(m.content)[1] for m in messages if m.role == TOOL}
        pending, self._pending = self._pending, []
        for call_id, call, key in pending:
            if call_id not in results:
                continue
            actual = results[call_id]
            self.observed[key] = actual
            if self.check_results and "result" in call and call["result"].strip() != actual.strip():
                self._fail(f"第 {key[0] + 1} 輪第 {key[1] + 1} 步的 {call['name']} 交回的結果跟錄的時候不同"
                           f"（錄：{_short(call['result'])}；現在：{_short(actual)}）")

    def chat(self, messages: Sequence[Message], tools: Sequence[ToolSpec] = ()) -> Reply:
        self._collect(messages)
        script = self.turns[self.turn]
        if self.step >= len(script):
            return self._fail(f"第 {self.turn + 1} 輪：迴圈要第 {self.step + 1} 步，劇本只錄了 {len(script)} 步")
        step = script[self.step]
        offered = {t.name for t in tools}
        if not self.offered:
            self.offered = sorted(offered)
        calls = []
        for i, raw in enumerate(step.get("tool_calls") or []):
            if raw["name"] not in offered:
                return self._fail(f"第 {self.turn + 1} 輪第 {self.step + 1} 步叫了這一輪沒有提供的工具 {raw['name']}")
            call_id = f"replay-{self.turn}-{self.step}-{i}"
            args = copy.deepcopy(raw.get("args") or {})
            calls.append(ToolCall(name=raw["name"], args=args, id=call_id))
            self._pending.append((call_id, raw, (self.turn, self.step, i)))
            self.attempted[-1].append((raw["name"], copy.deepcopy(args)))
        self.step += 1
        self.last_had_calls = bool(calls)
        return Reply(text=step.get("text", ""), tool_calls=calls, usage={"input": 0, "output": 0})

    def probe(self) -> Optional[str]:
        return None


def _short(text: str, n: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n] + "…"


# ── 一題跑完的紀錄 ─────────────────────────────────────────────────────

@dataclass
class Call:
    tool: str
    args: Dict[str, str]
    effect: str = ""                 # read／write／danger；不是工具（AI 亂叫的名字）＝""


@dataclass
class TurnRun:
    said: str
    steps: int = 0
    attempted: List[Call] = field(default_factory=list)      # AI 叫的（不管有沒有過第 4 關）
    executed: List[Call] = field(default_factory=list)       # 真的執行了（假工具被叫到）
    carded: List[Call] = field(default_factory=list)         # 迴圈走到確認卡（沒有執行）
    final: str = ""                                          # 這一輪最後送給使用者的字（停在確認卡＝""）
    step_limit: bool = False                                 # 迴圈做滿步數還沒做完

    @property
    def accepted(self) -> List[Call]:
        return self.executed + self.carded


@dataclass
class CaseRun:
    case_id: str
    turns: List[TurnRun] = field(default_factory=list)
    mismatch: Optional[str] = None
    offered: List[str] = field(default_factory=list)
    observed: Dict[Tuple[int, int, int], str] = field(default_factory=dict)


def _build(tmp: str, adapter: ChatAdapter, max_steps: int, guard: str = "off"):
    from isdtelekit.testing import FakeChannel

    from synox.app import build
    from synox.config import SynoxConfig
    from synox.vault import Vault

    data = os.path.join(tmp, "data")
    config = SynoxConfig.from_dict({"owner_id": EVAL_OWNER_ID, "data_dir": data, "vault": {"mode": "file"},
                                    "llm": {"kind": "fake", "max_steps": max_steps, "completion_guard": guard}},
                                   require_token=False, root=tmp)
    api = FakeChannel()
    app = build(config, home=api, adapter=adapter, vault=Vault(os.urandom(32), data), pack_dirs=())
    return app, api


def _images(case: Case, turn: int):
    """這一輪附的假圖 → ImagePart 清單（跟私訊傳照片同一條 vision.prepare）；沒附圖＝None（照舊的 run_turn）。"""
    paths = case.image_paths(turn)
    if not paths:
        return None
    from synox.llm import vision
    blobs = []
    for path in paths:
        with open(path, "rb") as f:
            blobs.append(f.read())
    parts, problems = vision.prepare_all(blobs)
    if problems:
        raise ReplayError(f"{case.id}：題目的圖不能用：{'；'.join(problems)}")
    return parts


def _effect_of(registry, name: str) -> str:
    node = tools_mod.node_for(registry, name)
    return node.effect if node is not None else ""


def run_case(case: Case, recording: dict, *, max_steps: int = DEFAULT_MAX_STEPS,
             check_results: bool = True) -> CaseRun:
    """在暫存資料夾裡建一支 SYNOX、掛上這題的假工具，照劇本一輪一輪跑。"""
    run = CaseRun(case.id)
    turns = recording.get("turns") or []
    if len(turns) != len(case.turns):
        run.mismatch = f"劇本錄了 {len(turns)} 輪，題目有 {len(case.turns)} 輪"
        return run
    adapter = ReplayAdapter(turns, check_results=check_results)
    with tempfile.TemporaryDirectory(prefix="synox-eval-", ignore_cleanup_errors=True) as tmp:
        app, api = _build(tmp, adapter, max_steps, recording.get("completion_guard", "off"))
        log = fake_tools.install(app, case)
        fakes = {t.name for t in case.tools}
        registry = app.registry
        desk = app.extras["synox_approval_desk"]
        cards: List[Call] = []
        original = desk.request

        def request(api_, chat_id, user, node, argv, *a, **kw):          # 只記下「走到確認卡」，卡照常送
            values, _m, _e = kit.parse_args(node.fields, argv, positional=0) if node.fields else ({}, [], [])
            cards.append(Call(tools_mod.tool_name(node), dict(values), node.effect_of(argv)))
            return original(api_, chat_id, user, node, argv, *a, **kw)

        desk.request = request
        loop = app.extras["synox_agent"]
        user = app.users.get_or_create(EVAL_OWNER_ID)
        chat_id = EVAL_OWNER_ID
        for index, said in enumerate(case.turns):
            adapter.begin_turn()
            sent_before, ran_before, cards_before = len(api.sent), len(log.executed), len(cards)
            images = _images(case, index)
            if images is None:
                loop.run_turn(api, chat_id, user, said)
            else:
                loop.run_turn(api, chat_id, user, said, images=images)
            turn = TurnRun(said=said, steps=adapter.step)
            turn.attempted = [Call(n, {k: str(v) for k, v in a.items()}, _effect_of(registry, n))
                              for n, a in adapter.attempted[-1]]
            turn.executed = [Call(e.tool, e.args, _effect_of(registry, e.tool)) for e in log.executed[ran_before:]]
            turn.executed += [Call(e.tool, {k: str(v) for k, v in e.args.items()}, e.effect) for e in loop.last_ledger()
                              if e.ok and not e.carded and e.tool not in fakes and e.tool in BUILTIN_TOOLS]
            turn.carded = cards[cards_before:]
            plain = [m.text for m in api.sent[sent_before:] if m.chat_id == chat_id and m.reply_markup is None]
            turn.final = plain[-1] if plain and not turn.carded else ""
            turn.step_limit = (adapter.mismatch is None and not turn.carded and adapter.last_had_calls
                               and adapter.step >= loop.max_steps)
            run.turns.append(turn)
            if adapter.mismatch is None and adapter.remaining() and not turn.step_limit:
                adapter.mismatch = (f"第 {adapter.turn + 1} 輪：迴圈在第 {adapter.step} 步就結束了"
                                    f"（{'走到確認卡' if turn.carded else '回了文字'}），劇本還有 {adapter.remaining()} 步")
            if adapter.mismatch is not None:
                break
        run.mismatch = adapter.mismatch
        run.offered = adapter.offered
        run.observed = dict(adapter.observed)
    return run


def run_all(cases: Sequence[Case], recordings: Dict[str, dict], *, max_steps: int = DEFAULT_MAX_STEPS) -> list:
    """每一題重放＋檢查 → [checks.CaseResult]（照 id 排序）。沒有回覆檔＝missing；不同步＝replay_mismatch（不跑檢查）。"""
    from synox.evals import checks
    out = []
    for case in sorted(cases, key=lambda c: c.id):
        rec = recordings.get(case.id)
        if rec is None:
            out.append(checks.CaseResult(case, checks.MISSING))
            continue
        run = run_case(case, rec, max_steps=max_steps)
        if run.mismatch is not None:
            out.append(checks.CaseResult(case, checks.MISMATCH, run=run, mismatch=run.mismatch))
            continue
        failures = checks.evaluate(case, run)
        out.append(checks.CaseResult(case, checks.FAIL if failures else checks.PASS, failures, run=run))
    return out


def stamp(case: Case, recording: dict, *, max_steps: int = DEFAULT_MAX_STEPS) -> Tuple[dict, Optional[str]]:
    """照現在的題目重放一次（不比對 result），把每個呼叫實際交回 AI 的字填進 result；回 (新劇本, 不同步的原因或 None)。
    用來補參考回覆：先寫好每一步，再 stamp，之後題目或外框一改就會被抓到。"""
    run = run_case(case, recording, max_steps=max_steps, check_results=False)
    out = copy.deepcopy(recording)
    for t, steps in enumerate(out.get("turns") or []):
        for s, step in enumerate(steps):
            for i, call in enumerate(step.get("tool_calls") or []):
                if (t, s, i) in run.observed:
                    call["result"] = run.observed[(t, s, i)]
                else:
                    call.pop("result", None)
    return out, run.mismatch
