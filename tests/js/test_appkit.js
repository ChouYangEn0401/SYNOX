// 工具服務的共用元件（src/synox/web/static/appkit.js）：自備最小的假 DOM、假 fetch、假 sessionStorage、假 history。
// tests/test_appkit.py 用 node 跑（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const K = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "appkit.js"));

class Elem {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.parentNode = null; this.className = ""; this._text = "";
    this.attrs = {}; this.listeners = {}; this.value = ""; this.submitted = 0;
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) { c.parentNode = this; const i = ref ? this.children.indexOf(ref) : -1; if (i < 0) { this.children.push(c); } else { this.children.splice(i, 0, c); } return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; return c; }
  set textContent(t) { this.children = []; this._text = String(t); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  fire(t, e) { (this.listeners[t] || []).forEach((fn) => fn(e || { preventDefault() {} })); }
  submit() { this.submitted += 1; }
  focus() {}
  set innerHTML(_v) { throw new Error("innerHTML must not be used"); }
}
function walk(n, out = []) { out.push(n); (n.children || []).forEach((c) => walk(c, out)); return out; }
function texts(doc) { return walk(doc.body).map((n) => n._text || "").join("|"); }
function find(doc, pred) { return walk(doc.body).find(pred); }
function makeDoc() {
  const doc = { body: new Elem("body"), listeners: {}, visibilityState: "visible",
                createElement: (t) => new Elem(t), createTextNode: (t) => { const e = new Elem("#text"); e._text = t; return e; },
                addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
                fire(t, e) { (this.listeners[t] || []).forEach((fn) => fn(e)); } };
  return doc;
}
function makeEnv(responses, opts = {}) {
  const calls = [];
  const order = [];
  const store = {};
  let clock = opts.clock || 1000000;
  const env = {
    document: makeDoc(),
    location: { hash: opts.hash || "" },
    history: { replaceState: (_a, _b, url) => { order.push("replace"); env.location.hash = ""; env.url = url; } },
    sessionStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
                      removeItem: (k) => { delete store[k]; } },
    fetch: (p, init) => {
      order.push("fetch");
      calls.push([p, init]);
      const r = responses.shift();
      if (r === "down") { return Promise.reject(new Error("down")); }
      const res = r || { status: 200, body: { ok: true } };
      return Promise.resolve({ status: res.status, ok: res.status >= 200 && res.status < 300,
                               json: () => Promise.resolve(res.body) });
    },
    now: () => clock,
    consoleUrl: "CONSOLE",
  };
  if (opts.token) { store["synox.app.token"] = opts.token; }
  return { env, calls, order, store, tick: (ms) => { clock += ms; } };
}
const ME = { ok: true, user: { id: 1, name: "我", owner: true }, app: { name: "counter", title: "計數器", app_title: "計數器" },
             reads: ["state"], alive_every_s: 60, console_url: "CONSOLE",
             actions: { add: { effect: "write", summary: "加一個數", fields: [{ name: "n", label: "數字", required: true, kind: "int" }] },
                        kind: { effect: "write", summary: "選", fields: [{ name: "k", label: "種類", required: false, choices: ["a", "b"] }] } },
             exports: { state_csv: { available: true, reason: "" }, off_csv: { available: false, reason: "這台不能匯出" } } };
const flush = () => new Promise((r) => setImmediate(r));
const tests = [];
function test(name, fn) { tests.push([name, fn]); }
async function started(responses, opts) {
  const t = makeEnv(responses, opts);
  const kit = K.create(t.env);
  await kit.start();
  await flush();
  return Object.assign(t, { kit });
}

test("ticket in hash: replaceState before fetch, enter, token stored, ready called", async () => {
  let ready = 0;
  const t = makeEnv([{ status: 200, body: { ok: true, token: "TOKEN1", me: ME } }], { hash: "#t=abcdefghijklmnopqrstuvwxyz" });
  const kit = K.create(t.env);
  kit.ready(() => { ready += 1; });
  await kit.start();
  assert.deepStrictEqual(t.order.slice(0, 2), ["replace", "fetch"]);
  assert.strictEqual(t.env.url, "/");
  assert.ok(!String(t.env.location.hash).includes("abcdefghij"));
  assert.strictEqual(t.calls[0][0], "/api/enter");
  assert.deepStrictEqual(JSON.parse(t.calls[0][1].body), { ticket: "abcdefghijklmnopqrstuvwxyz" });
  assert.strictEqual(t.store["synox.app.token"], "TOKEN1");
  assert.strictEqual(ready, 1);
});

test("stored token: GET /api/me with header, credentials omit", async () => {
  const t = await started([{ status: 200, body: ME }], { token: "TOK" });
  assert.strictEqual(t.calls[0][0], "/api/me");
  assert.strictEqual(t.calls[0][1].headers["X-SYNOX-App"], "TOK");
  assert.strictEqual(t.calls[0][1].credentials, "omit");
  assert.ok(texts(t.env.document).includes("計數器"));
});

test("nothing: no request, mask, ready not called", async () => {
  let ready = 0;
  const t = makeEnv([]);
  const kit = K.create(t.env);
  kit.ready(() => { ready += 1; });
  await kit.start();
  assert.strictEqual(t.calls.length, 0);
  assert.ok(texts(t.env.document).includes(K.TEXT.fromSynox));
  assert.strictEqual(ready, 0);
});

test("401 on /api/me clears token and masks", async () => {
  const t = await started([{ status: 401, body: { ok: false, code: "login" } }], { token: "OLD" });
  assert.ok(!("synox.app.token" in t.store));
  assert.ok(texts(t.env.document).includes(K.TEXT.fromSynox) || texts(t.env.document).includes(K.TEXT.again));
});

test("act: strings, empty dropped, confirm flow ok and cancel", async () => {
  const t = await started([{ status: 200, body: ME }], { token: "T" });
  t.env.fetch = ((orig) => orig)(t.env.fetch);
  const resp = [{ status: 409, body: { ok: false, code: "confirm", confirm: { text: "真的嗎？", button: "確定" } } },
                { status: 200, body: { ok: true, data: { n: 0 } } }];
  const calls = [];
  t.env.fetch = (p, init) => { calls.push([p, init]); const r = resp.shift();
    return Promise.resolve({ status: r.status, ok: r.status < 300, json: () => Promise.resolve(r.body) }); };
  const kit = K.create(t.env); kit._state.token = "T"; kit._state.me = ME;
  const p = kit.act("reset", { n: 3, empty: "", nil: null });
  await flush(); await flush();
  const modal = find(t.env.document, (n) => n.className === "synox-modal");
  assert.ok(modal && texts({ body: modal }).includes("真的嗎？"));
  find({ body: modal }, (n) => n.tagName === "button" && n._text === "確定").fire("click");
  assert.deepStrictEqual(await p, { n: 0 });
  assert.deepStrictEqual(JSON.parse(calls[0][1].body), { values: { n: "3" } });
  assert.deepStrictEqual(JSON.parse(calls[1][1].body), { values: { n: "3" }, confirmed: true });
  assert.strictEqual(calls[1][1].headers["X-SYNOX-App"], "T");
  resp.push({ status: 409, body: { ok: false, code: "confirm", confirm: { text: "再一次", button: "確定" } } });
  const p2 = kit.act("reset", {});
  await flush(); await flush();
  const m2 = find(t.env.document, (n) => n.className === "synox-modal");
  find({ body: m2 }, (n) => n.tagName === "button" && n._text === K.TEXT.cancel).fire("click");
  await assert.rejects(p2, (e) => e.code === "cancelled");
  assert.strictEqual(calls.length, 3);
});

test("act invalid returns fields", async () => {
  const t = makeEnv([{ status: 400, body: { ok: false, code: "invalid", error: "不對", fields: { n: "數字要是正整數" } } }]);
  const kit = K.create(t.env); kit._state.token = "T"; kit._state.me = ME;
  await assert.rejects(kit.act("add", { n: "x" }, { quiet: true }), (e) => e.fields.n === "數字要是正整數");
});

test("read: params encoded; network down masks; 401 different text", async () => {
  const t = makeEnv([{ status: 200, body: { ok: true, data: 5 } }, "down"]);
  const kit = K.create(t.env); kit._state.token = "T"; kit._state.me = ME;
  assert.strictEqual(await kit.read("state", { q: "中 & 文" }), 5);
  assert.strictEqual(t.calls[0][0], "/api/read/state?q=%E4%B8%AD%20%26%20%E6%96%87");
  await assert.rejects(kit.read("state"));
  assert.ok(texts(t.env.document).includes(K.TEXT.closed));
  const t2 = makeEnv([{ status: 401, body: { ok: false, code: "login" } }]);
  const k2 = K.create(t2.env); k2._state.token = "T"; k2._state.me = ME;
  await assert.rejects(k2.read("state"));
  assert.ok(texts(t2.env.document).includes(K.TEXT.again));
});

test("form: required, choices, field errors land on the right field", async () => {
  const t = makeEnv([{ status: 400, body: { ok: false, code: "invalid", error: "x", fields: { n: "數字要是正整數" } } }]);
  const kit = K.create(t.env); kit._state.token = "T"; kit._state.me = ME;
  const f = kit.form("add", {});
  const input = find({ body: f }, (n) => n.tagName === "input");
  assert.ok(input.required && input.type === "number");
  f.fire("submit");
  assert.strictEqual(t.calls.length, 0);                       // 必填沒填不送
  input.value = "-1";
  f.fire("submit");
  await flush(); await flush();
  assert.ok(texts({ body: f }).includes("數字要是正整數"));
  const sel = kit.form("kind", {});
  assert.ok(find({ body: sel }, (n) => n.tagName === "select"));
});

test("alive: trusted+visible+61s → one; burst → none; hidden/untrusted → none; no events → none", async () => {
  const t = await started([{ status: 200, body: ME }], { token: "T" });
  const doc = t.env.document;
  const n0 = t.calls.length;
  t.tick(3600 * 1000);
  assert.strictEqual(t.calls.length, n0);                       // 沒有輸入就什麼都不送
  doc.fire("mousemove", { isTrusted: true });
  assert.strictEqual(t.calls.length, n0 + 1);
  assert.strictEqual(t.calls[n0][0], "/api/alive");
  for (let i = 0; i < 10; i++) { doc.fire("keydown", { isTrusted: true }); }
  assert.strictEqual(t.calls.length, n0 + 1);
  t.tick(61000);
  doc.visibilityState = "hidden";
  doc.fire("scroll", { isTrusted: true });
  doc.visibilityState = "visible";
  doc.fire("scroll", { isTrusted: false });
  assert.strictEqual(t.calls.length, n0 + 1);
  t.env.fetch = () => Promise.reject(new Error("down"));
  doc.fire("wheel", { isTrusted: true });
  await flush();
  assert.ok(!find(doc, (n) => n.className === "synox-mask"));   // 失敗不遮罩、不 toast
  assert.deepStrictEqual(K.ACTIVITY, ["mousemove", "keydown", "pointerdown", "wheel", "scroll", "touchstart"]);
});

test("read success resets the alive clock", async () => {
  const t = await started([{ status: 200, body: ME }], { token: "T" });
  t.tick(120000);
  t.env.fetch = ((calls) => (p, init) => { calls.push([p]); return Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve({ ok: true, data: 1 }) }); })(t.calls);
  const kit = t.kit;
  await kit.read("state");
  const n = t.calls.length;
  t.tick(30000);
  t.env.document.fire("mousemove", { isTrusted: true });
  assert.strictEqual(t.calls.length, n);
});

test("download: unavailable → no request; flow builds a post form with t and confirmed", async () => {
  const t = makeEnv([{ status: 409, body: { ok: false, code: "confirm", confirm: { text: "沒有加密", button: "下載" } } }]);
  const kit = K.create(t.env); kit._state.token = "TT"; kit._state.me = ME;
  assert.strictEqual(await kit.download("off_csv", {}), false);
  assert.strictEqual(t.calls.length, 0);
  assert.ok(texts(t.env.document).includes("這台不能匯出"));
  const p = kit.download("state_csv", { y: "2026" });
  await flush(); await flush();
  assert.strictEqual(t.calls[0][1].headers["Content-Type"], "application/x-www-form-urlencoded");
  assert.ok(t.calls[0][1].body.includes("t=TT") && !t.calls[0][1].body.includes("confirmed"));
  const modal = find(t.env.document, (n) => n.className === "synox-modal");
  assert.ok(texts({ body: modal }).includes("沒有加密"));
  let built = null;
  const orig = t.env.document.createElement;
  t.env.document.createElement = (tag) => { const e = orig(tag); if (tag === "form") { built = e; } return e; };
  find({ body: modal }, (n) => n.tagName === "button" && n._text === "下載").fire("click");
  assert.strictEqual(await p, true);
  assert.strictEqual(built.method, "post");
  const fields = Object.fromEntries(built.children.map((i) => [i.name, i.value]));
  assert.deepStrictEqual(fields, { t: "TT", y: "2026", confirmed: "1" });
  assert.strictEqual(built.submitted, 1);
});

test("download cancel → no form", async () => {
  const t = makeEnv([{ status: 409, body: { ok: false, code: "confirm", confirm: { text: "x", button: "下載" } } }]);
  const kit = K.create(t.env); kit._state.token = "TT"; kit._state.me = ME;
  let forms = 0;
  const orig = t.env.document.createElement;
  t.env.document.createElement = (tag) => { if (tag === "form") { forms += 1; } return orig(tag); };
  const p = kit.download("state_csv", {});
  await flush(); await flush();
  const modal = find(t.env.document, (n) => n.className === "synox-modal");
  find({ body: modal }, (n) => n.tagName === "button" && n._text === K.TEXT.cancel).fire("click");
  assert.strictEqual(await p, false);
  assert.strictEqual(forms, 0);
});

test("remote: no back link, no export request, close-remote button", async () => {
  const meR = Object.assign({}, ME, { remote: true, remote_until: "2026-11-14T10:30:00" });
  const t = await started([{ status: 200, body: meR }], { token: "T" });
  const all = texts(t.env.document);
  assert.ok(!all.includes(K.TEXT.back));
  assert.ok(all.includes(K.TEXT.closeRemote) && all.includes("10:30"));
  const n = t.calls.length;
  assert.strictEqual(await t.kit.download("state_csv", {}), false);
  assert.strictEqual(t.calls.length, n);
  const t2 = await started([{ status: 200, body: ME }], { token: "T" });
  assert.ok(texts(t2.env.document).includes(K.TEXT.back));
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + (e && e.stack || e)); }
  }
  process.exit(failed ? 1 : 0);
})();
