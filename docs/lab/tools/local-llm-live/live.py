"""Live harness: real SYNOX AgentLoop + eval fake tools + a real local Ollama (127.0.0.1 only).
Lab script (docs/lab), not part of the product; it predates the llm/local.py adapter.
Usage: python live.py <model> <native|text> <case-id,...> [out.json]   (SYNOX_ROOT overrides the repo root)
Stands in for ntu_easy_llm (not installable at the time): same neutral->OpenAI wire conversion, POST /v1/chat/completions."""
import json, os, sys, tempfile, time
ROOT = os.environ.get("SYNOX_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "vendor"))
import requests
from synox.llm.base import ChatAdapter, LLMError, Reply, ToolCall
from synox.evals import cases as cases_mod, fake_tools, checks
from synox.evals import replay as rp
from synox.packs import kit

BASE = "http://127.0.0.1:11434/v1"


class OllamaAdapter(ChatAdapter):
    def __init__(self, model, native, think=False):
        self.model, self.supports_tools, self.think = model, native, think
        self.name = f"ollama:{model}"
        self.log = []          # one entry per chat() call

    def chat(self, messages, tools=()):
        msgs = []
        for m in messages:
            d = {"role": m.role, "content": m.content}
            if m.tool_calls:
                d["tool_calls"] = [{"id": c.id or f"c{i}", "type": "function",
                                    "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
                                   for i, c in enumerate(m.tool_calls)]
            if m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            msgs.append(d)
        body = {"model": self.model, "messages": msgs, "max_tokens": 1024, "stream": False}
        if not self.think:
            body["reasoning_effort"] = "none"
        if tools and self.supports_tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                              "parameters": t.parameters}} for t in tools]
        t0 = time.time()
        try:
            r = requests.post(BASE + "/chat/completions", json=body, timeout=600)
        except requests.RequestException as e:
            raise LLMError(f"connect: {e}")
        dt = time.time() - t0
        entry = {"secs": round(dt, 1), "status": r.status_code, "n_tools_offered": len(body.get("tools", []))}
        self.log.append(entry)
        if r.status_code != 200:
            entry["body"] = r.text[:300]
            raise LLMError(f"http {r.status_code}: {r.text[:200]}")
        j = r.json()
        msg = j["choices"][0]["message"]
        u = j.get("usage", {})
        entry.update(prompt_tokens=u.get("prompt_tokens"), out_tokens=u.get("completion_tokens"),
                     finish=j["choices"][0].get("finish_reason"), text=(msg.get("content") or "")[:300],
                     reasoning=bool(msg.get("reasoning") or msg.get("reasoning_content")))
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            fn = c.get("function", {})
            raw = fn.get("arguments")
            try:
                args = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or {})
            except ValueError:
                entry.setdefault("bad_json", []).append(str(raw)[:200])
                args = {}
            calls.append(ToolCall(name=fn.get("name", ""), args=args if isinstance(args, dict) else {}, id=c.get("id") or f"c{i}"))
        entry["calls"] = [(c.name, c.args) for c in calls]
        return Reply(text=msg.get("content") or "", tool_calls=calls,
                     usage={"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)})


def run_live(case, adapter, max_steps=6):
    run = rp.CaseRun(case.id)
    with tempfile.TemporaryDirectory(prefix="synox-live-", ignore_cleanup_errors=True) as tmp:
        app, api = rp._build(tmp, adapter, max_steps)
        log = fake_tools.install(app, case)
        desk = app.extras["synox_approval_desk"]
        cards = []
        original = desk.request

        def request(api_, chat_id, user, node, argv, *a, **kw):
            values, _m, _e = kit.parse_args(node.fields, argv, positional=0) if node.fields else ({}, [], [])
            cards.append(rp.Call(rp.tools_mod.tool_name(node), dict(values), node.effect_of(argv)))
            return original(api_, chat_id, user, node, argv, *a, **kw)

        desk.request = request
        loop = app.extras["synox_agent"]
        user = app.users.get_or_create(rp.EVAL_OWNER_ID)
        for said in case.turns:
            n0, sent0, ran0, c0 = len(adapter.log), len(api.sent), len(log.executed), len(cards)
            loop.run_turn(api, rp.EVAL_OWNER_ID, user, said)
            steps = adapter.log[n0:]
            turn = rp.TurnRun(said=said, steps=len(steps))
            turn.attempted = [rp.Call(n, {k: str(v) for k, v in a.items()}, rp._effect_of(app.registry, n))
                              for e in steps for n, a in e.get("calls", [])]
            turn.executed = [rp.Call(e.tool, e.args, rp._effect_of(app.registry, e.tool)) for e in log.executed[ran0:]]
            turn.carded = cards[c0:]
            plain = [m.text for m in api.sent[sent0:] if m.chat_id == rp.EVAL_OWNER_ID and m.reply_markup is None]
            turn.final = plain[-1] if plain and not turn.carded else ""
            turn.step_limit = (not turn.carded and bool(steps) and steps[-1].get("calls") and len(steps) >= loop.max_steps)
            run.turns.append(turn)
    return run


if __name__ == "__main__":
    model, mode, ids = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
    out = sys.argv[4] if len(sys.argv) > 4 else None
    lib = cases_mod.load_tool_library(os.path.join(ROOT, "evals", "assistant"))
    allc = {c.id: c for c in cases_mod.load_dir(os.path.join(ROOT, "evals", "assistant", "cases"))}
    results = []
    for cid in ids:
        case = allc[cid]
        ad = OllamaAdapter(model, native=(mode == "native"))
        t0 = time.time()
        try:
            run = run_live(case, ad)
            fails = checks.evaluate(case, run)
            rec = {"case": cid, "category": case.category, "mode": mode, "model": model,
                   "secs": round(time.time() - t0, 1), "passed": not fails,
                   "failures": [f"{f.check}: {f.detail}" if hasattr(f, 'check') else str(f) for f in fails],
                   "turns": [{"said": t.said, "attempted": [(c.tool, c.args) for c in t.attempted],
                              "executed": [c.tool for c in t.executed], "carded": [c.tool for c in t.carded],
                              "final": t.final[:300], "steps": t.steps, "step_limit": t.step_limit} for t in run.turns],
                   "calls": ad.log}
        except Exception as e:
            rec = {"case": cid, "mode": mode, "model": model, "error": f"{type(e).__name__}: {e}", "calls": ad.log}
        results.append(rec)
        print(cid, mode, "PASS" if rec.get("passed") else "FAIL/ERR", rec.get("secs"), rec.get("failures") or rec.get("error", ""), flush=True)
        if out:
            json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
