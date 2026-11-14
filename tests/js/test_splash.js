// 開場動畫（src/synox/web/static/splash.js）：什麼時候播、畫面怎麼長、一定收得掉。
// tests/test_motion.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const S = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "splash.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("plays once per tab session", () => {
  assert.strictEqual(S.decide("", null, null, false), true);
  assert.strictEqual(S.decide("", "1", null, false), false);
  assert.strictEqual(S.decide("?pack=abcdefgh", null, null, false), true);
});

test("reduced motion always wins", () => {
  assert.strictEqual(S.decide("", null, null, true), false);
  assert.strictEqual(S.decide("?splash=1", null, null, true), false);
});

test("?splash=1 replays, ?splash=0 skips, localStorage off turns it off", () => {
  assert.strictEqual(S.decide("?splash=1", "1", "off", false), true);
  assert.strictEqual(S.decide("?theme=dark&splash=1", "1", null, false), true);
  assert.strictEqual(S.decide("?splash=0", null, null, false), false);
  assert.strictEqual(S.decide("", null, "off", false), false);
  assert.strictEqual(S.decide("?splash=10", null, null, false), true);       // 不是 0／1：照一般規則
  assert.strictEqual(S.decide("?xsplash=0", null, null, false), true);
});

test("timeline: fades out before it is removed, safety net comes last", () => {
  assert.ok(S.OUT_AT < S.TOTAL && S.TOTAL < S.SAFETY);
  assert.ok(S.TOTAL >= 1200 && S.TOTAL <= 2000, "開場 1.2～2 秒");
});

test("opening box follows the SVG's aspect ratio (wide scenes get the wider stage)", () => {
  const svg = (a) => ({ getAttribute: (k) => (k in a ? a[k] : null) });
  assert.ok(Math.abs(S.ratio(svg({ viewBox: "0 0 480 250" })) - 1.92) < 1e-9);
  assert.strictEqual(S.ratio(svg({ viewBox: "0,0,220,220" })), 1);
  assert.strictEqual(S.ratio(svg({ width: "300", height: "150" })), 2);
  assert.strictEqual(S.ratio(svg({})), 1, "讀不到比例：當正方形（照舊 220×220）");
  assert.strictEqual(S.ratio(svg({ viewBox: "0 0 0 0" })), 1);
});

// 最小的假 DOM：只夠 build／play 用
function fakeDoc() {
  const listeners = {};
  function node(tag) {
    return {
      tag, children: [], className: "", textContent: "", attrs: {}, parentNode: null, events: {},
      appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
      removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; },
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(t, fn) { this.events[t] = fn; },
      classList: null
    };
  }
  function withClassList(n) {
    const set = new Set();
    n.classList = { add: (...c) => c.forEach((x) => set.add(x)), remove: (...c) => c.forEach((x) => set.delete(x)),
                    contains: (c) => set.has(c) };
    return n;
  }
  const html = withClassList(node("html"));
  const body = node("body");
  return {
    documentElement: html, body,
    createElement(tag) { return withClassList(node(tag)); },
    addEventListener(t, fn) { listeners[t] = fn; },
    removeEventListener(t) { delete listeners[t]; },
    listeners
  };
}
function walk(n, fn) { fn(n); n.children.forEach((c) => walk(c, fn)); }

test("build uses text only and is decorative", () => {
  const doc = fakeDoc();
  const s = S.build(doc);
  assert.strictEqual(s.className, "sx-splash");
  assert.strictEqual(s.attrs["aria-hidden"], "true");
  let text = "";
  walk(s, (n) => { text += n.textContent; });
  assert.ok(text.includes("SYNOX") || text.includes("S"));
  assert.ok(text.includes("略過"));
});

test("play adds the overlay, skip and the timers always take it away", () => {
  const timers = [];
  const saved = global.setTimeout;
  global.setTimeout = (fn, ms) => { timers.push([ms, fn]); return timers.length; };
  try {
    const doc = fakeDoc();
    S.play(doc);
    assert.strictEqual(doc.body.children.length, 1);
    assert.ok(doc.documentElement.classList.contains("sx-hold"));
    assert.ok(doc.listeners.keydown, "按任何鍵略過");
    doc.listeners.keydown();                                 // 略過
    assert.ok(!doc.documentElement.classList.contains("sx-hold"), "略過時內容馬上開始進場");
    const seen = [];
    while (timers.length) {                                   // 依時間跑完全部（含跑的時候才排的）
      timers.sort((a, b) => a[0] - b[0]);
      const t = timers.shift();
      seen.push(t[0]);
      t[1]();
    }
    timers.push(...seen.map((ms) => [ms]));
    assert.strictEqual(doc.body.children.length, 0);
    assert.ok(!doc.listeners.keydown);
    assert.ok(!doc.documentElement.classList.contains("sx-intro"));
    assert.ok(timers.some((t) => t[0] === S.SAFETY), "保險的計時器");
  } finally { global.setTimeout = saved; }
});

test("a broken DOM still releases the page", () => {
  const timers = [];
  const saved = global.setTimeout;
  global.setTimeout = (fn, ms) => { timers.push([ms, fn]); return timers.length; };
  try {
    const doc = fakeDoc();
    doc.createElement = () => { throw new Error("boom"); };
    S.play(doc);
    assert.ok(!doc.documentElement.classList.contains("sx-hold"), "出錯時不能讓內容停在看不見");
  } finally { global.setTimeout = saved; }
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + (e && e.stack || e)); }
}
process.exit(failed ? 1 : 0);
