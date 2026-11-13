// 工具服務的主機台畫面（src/synox/web/static/apps.js）：卡片、打開的表單、閒置設定。假 DOM，不開瀏覽器、不開埠。
// tests/test_app_console.py 用 node 跑；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const FILE = path.join(__dirname, "..", "..", "src", "synox", "web", "static", "apps.js");
const A = require(FILE);

class Elem {
  constructor(tag) { this.tagName = tag; this.children = []; this._text = ""; this.className = ""; this.attrs = {}; this.listeners = {};
    const self = this; this.classList = { add(c) { self.className += " " + c; }, remove(c) { self.className = self.className.replace(c, ""); },
      toggle(c, on) { if (on === undefined ? !self.className.includes(c) : on) { this.add(c); } else { this.remove(c); } },
      contains(c) { return self.className.includes(c); } }; }
  appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); }
  set textContent(t) { this.children = []; this._text = String(t); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  click() { (this.listeners.click || []).forEach((f) => f({})); }
}
const doc = { createElement: (t) => new Elem(t) };
function walk(n, out = []) { out.push(n); n.children.forEach((c) => walk(c, out)); return out; }
const tests = [];
function test(n, f) { tests.push([n, f]); }
const EXPLAIN = { what: "WHAT", why_close: "WHY", restart: "RESTART", in_use: "INUSE" };
function view(over) {
  return Object.assign({ name: "money", title: "💰 記帳", state: "off", open: "", port: 8841, idle_min: 0, suggest_close: false,
                         policy: { mode: "auto", close_min: 120, suggest_min: 30, text: "120 分鐘沒用就關，30 分鐘先提醒" },
                         problem: "", error: "" }, over || {});
}
function ctx(over) {
  const calls = [];
  return Object.assign({ canManage: true, csrf: "C1", explain: EXPLAIN, calls,
    onStart: (v) => calls.push(["start", v.name]), onStop: (v) => calls.push(["stop", v.name]),
    onKeep: (v) => calls.push(["keep", v.name]), onPolicy: (v, b) => calls.push(["policy", b]),
    confirm: () => Promise.resolve(false) }, over || {});
}
function buttons(card) { return walk(card).filter((n) => n.tagName === "button").map((b) => b._text); }

test("off card: start button, explanation, no open form", () => {
  const card = A.renderCard(doc, view(), ctx());
  assert.ok(buttons(card).includes(A.TEXT.start));
  assert.ok(!walk(card).some((n) => n.tagName === "form"));
  assert.ok(card.textContent.includes("WHAT") && card.textContent.includes("120 分鐘沒用就關"));
});

test("on card: open is a post form to self with csrf, target _blank, rel noopener", () => {
  const card = A.renderCard(doc, view({ state: "on", open: "/apps/money/open", idle_min: 12 }), ctx());
  const form = walk(card).find((n) => n.tagName === "form");
  assert.strictEqual(form.method, "post");
  assert.strictEqual(form.action, "/apps/money/open");
  assert.strictEqual(form.target, "_blank");
  assert.ok(String(form.rel).includes("noopener"));
  const hidden = form.children.find((c) => c.name === "csrf");
  assert.strictEqual(hidden.value, "C1");
  assert.ok(card.textContent.includes("開著 · 12 分鐘沒用"));
  assert.ok(buttons(card).includes(A.TEXT.stop) && !buttons(card).includes(A.TEXT.keep));
  const idle = A.renderCard(doc, view({ state: "on", open: "/apps/money/open", suggest_close: true }), ctx());
  assert.ok(buttons(idle).includes(A.TEXT.keep));
});

test("error/problem cards show the reason and no start", () => {
  const p = A.renderCard(doc, view({ problem: "畫面的動作 rm 沒有同名的指令" }), ctx());
  assert.ok(p.textContent.includes("沒有同名的指令") && !buttons(p).includes(A.TEXT.start));
  const e = A.renderCard(doc, view({ state: "error", error: "埠被別的程式占用了。" }), ctx());
  assert.ok(e.textContent.includes("占用"));
});

test("member: only the open form when on and the one line", () => {
  const off = A.renderCard(doc, view(), ctx({ canManage: false }));
  assert.deepStrictEqual(buttons(off), []);
  assert.ok(off.textContent.includes(A.TEXT.ownerOnly) && off.textContent.includes("沒在用的時候"));
  const on = A.renderCard(doc, view({ state: "on", open: "/apps/money/open" }), ctx({ canManage: false }));
  assert.deepStrictEqual(buttons(on), [A.TEXT.open]);
});

test("six idle choices; keep needs the warning confirmed; blocked hides start", async () => {
  assert.deepStrictEqual(A.POLICY_CHOICES.map((c) => c.key), ["auto120", "auto30", "custom", "suggest", "keep", "blocked"]);
  assert.deepStrictEqual(A.policyBody("keep"), { mode: "keep", understood: true });
  assert.deepStrictEqual(A.policyBody("custom", "45"), { mode: "auto", close_min: 45 });
  assert.strictEqual(A.policyBody("custom", "4"), null);
  assert.strictEqual(A.policyBody("custom", "1441"), null);
  const c = ctx({ confirm: () => Promise.resolve(false) });
  const card = A.renderCard(doc, view(), c);
  const radios = walk(card).filter((n) => n.tagName === "input" && n.type === "radio");
  assert.strictEqual(radios.length, 6);
  const keepRadio = radios.find((r) => r.value === "keep");
  keepRadio.listeners.change[0]();
  walk(card).find((n) => n.tagName === "button" && n._text === A.TEXT.save).click();
  await new Promise((r) => setImmediate(r));
  assert.deepStrictEqual(c.calls, []);                                // 沒按確認不送
  const c2 = ctx({ confirm: () => Promise.resolve(true) });
  const card2 = A.renderCard(doc, view(), c2);
  walk(card2).filter((n) => n.type === "radio").find((r) => r.value === "keep").listeners.change[0]();
  walk(card2).find((n) => n.tagName === "button" && n._text === A.TEXT.save).click();
  await new Promise((r) => setImmediate(r));
  assert.deepStrictEqual(c2.calls, [["policy", { mode: "keep", understood: true }]]);
  const blocked = A.renderCard(doc, view({ policy: { mode: "blocked", text: "不開放這個工具的畫面" } }), ctx());
  assert.ok(!buttons(blocked).includes(A.TEXT.start));
  const keepTag = A.renderCard(doc, view({ policy: { mode: "keep", text: "一直開著" } }), ctx());
  assert.ok(walk(keepTag).some((n) => n._text === A.TEXT.keepTag));
});

test("side badge text", () => {
  assert.strictEqual(A.sideText({ apps: [] }).count, 0);
  assert.strictEqual(A.sideText({ apps: [view({ state: "on" })] }).text, "● 1 個工具服務開著");
  const s = A.sideText({ apps: [view({ state: "on", suggest_close: true })] });
  assert.ok(s.warn && s.text.includes("很久沒用"));
});

test("file rules: no window.open, no 127.0.0.2, texts without jargon", () => {
  const src = fs.readFileSync(FILE, "utf8");
  assert.ok(!src.includes("window.open") && !src.includes("127.0.0.2"));
  const words = JSON.stringify(Object.values(A.TEXT).map((v) => (typeof v === "object" ? Object.values(v) : v)));
  for (const w of ["port", "session", "token", "CSRF", "csrf", "Port"]) { assert.ok(!words.includes(w), w); }
});

(async () => {
  let failed = 0;
  for (const [n, f] of tests) {
    try { await f(); console.log("ok - " + n); } catch (e) { failed += 1; console.log("FAIL - " + n + "\n" + e.stack); }
  }
  process.exit(failed ? 1 : 0);
})();
