// 開場動畫＋「點一下打開 SYNOX」的門（src/synox/web/static/splash.js）：什麼時候出現、畫面怎麼長、會等你點、點了一定收得掉。
// tests/test_motion.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const S = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "splash.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("shows every time the web UI is opened", () => {
  assert.strictEqual(S.decide("", null, undefined), true);
  assert.strictEqual(S.decide("?pack=abcdefgh", null, undefined), true);
  assert.strictEqual(S.decide("#chat", null, false), true);
});

test("?splash=0 skips, localStorage off and window.SYNOX_NO_SPLASH skip, ?splash=1 always shows", () => {
  assert.strictEqual(S.decide("?splash=0", null, undefined), false);
  assert.strictEqual(S.decide("?theme=dark&splash=0", null, undefined), false);
  assert.strictEqual(S.decide("", "off", undefined), false);
  assert.strictEqual(S.decide("", null, true), false);
  assert.strictEqual(S.decide("", null, "yes"), true, "只有真的 true 才算");
  assert.strictEqual(S.decide("?splash=1", "off", true), true);
  assert.strictEqual(S.decide("?theme=dark&splash=1", null, true), true);
  assert.strictEqual(S.decide("?splash=10", null, undefined), true);      // 不是 0／1：照一般規則
  assert.strictEqual(S.decide("?xsplash=0", null, undefined), true);
});

test("timeline: leaving is short", () => {
  assert.ok(S.READY_AT >= 1000 && S.READY_AT <= 1800, "播到最後一格 1～1.8 秒");
  assert.ok(S.LEAVE >= 200 && S.LEAVE <= 700, "點了之後半秒內進去");
  assert.strictEqual(S.DONE, "synox:splash-done");
});

test("opening box follows the SVG's aspect ratio (wide scenes get the wider stage)", () => {
  const svg = (a) => ({ getAttribute: (k) => (k in a ? a[k] : null) });
  assert.ok(Math.abs(S.ratio(svg({ viewBox: "0 0 480 250" })) - 1.92) < 1e-9);
  assert.strictEqual(S.ratio(svg({ viewBox: "0,0,220,220" })), 1);
  assert.strictEqual(S.ratio(svg({ width: "300", height: "150" })), 2);
  assert.strictEqual(S.ratio(svg({})), 1, "讀不到比例：當正方形（照舊 220×220）");
  assert.strictEqual(S.ratio(svg({ viewBox: "0 0 0 0" })), 1);
});

// 最小的假 DOM：只夠 build／open 用
function fakeDoc() {
  const listeners = {};
  const events = [];
  const doc = {
    activeElement: null,
    createElement(tag) { return withClassList(node(tag)); },
    addEventListener(t, fn) { listeners[t] = fn; },
    removeEventListener(t) { delete listeners[t]; },
    dispatchEvent(e) { events.push(e.type); return true; },
    listeners, events
  };
  function node(tag) {
    return {
      tag, children: [], textContent: "", attrs: {}, parentNode: null, events: {},
      appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
      removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; },
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(t, fn) { this.events[t] = fn; },
      focus() { doc.activeElement = this; },
      classList: null
    };
  }
  function withClassList(n) {
    const set = new Set();
    Object.defineProperty(n, "className", {
      get: () => Array.from(set).join(" "),
      set: (v) => { set.clear(); String(v).split(/\s+/).filter(Boolean).forEach((c) => set.add(c)); }
    });
    n.classList = { add: (...c) => c.forEach((x) => set.add(x)), remove: (...c) => c.forEach((x) => set.delete(x)),
                    contains: (c) => set.has(c) };
    return n;
  }
  doc.documentElement = withClassList(node("html"));
  doc.body = node("body");
  return doc;
}
function walk(n, fn) { fn(n); n.children.forEach((c) => walk(c, fn)); }
function find(n, pred) { let hit = null; walk(n, (x) => { if (!hit && pred(x)) { hit = x; } }); return hit; }
function text(n) { let t = ""; walk(n, (x) => { t += x.textContent; }); return t; }
function key(k) { let stopped = false; return { key: k, preventDefault() { stopped = true; }, get stopped() { return stopped; } }; }

// 假的計時器：把排好的全部照時間跑完（含跑的時候才排的）
function withTimers(fn) {
  const timers = [];
  const saved = global.setTimeout;
  global.setTimeout = (cb, ms) => { timers.push([ms || 0, cb]); return timers.length; };
  const flush = () => { while (timers.length) { timers.sort((a, b) => a[0] - b[0]); timers.shift()[1](); } };
  try { fn(flush, timers); } finally { global.setTimeout = saved; }
}

test("build: a dialog with a real, labelled button and the hint text (text only)", () => {
  const doc = fakeDoc();
  const s = S.build(doc, false);
  assert.ok(s.classList.contains("sx-splash") && s.classList.contains("sx-gate"));
  assert.strictEqual(s.attrs.role, "dialog");
  assert.strictEqual(s.attrs["aria-modal"], "true");
  const btn = find(s, (x) => x.tag === "button");
  assert.ok(btn, "門的按鈕");
  assert.strictEqual(btn.attrs.type, "button");
  assert.strictEqual(btn.attrs["aria-label"], "點一下打開 SYNOX");
  assert.ok(find(btn, (x) => x.classList.contains("sx-mascot")), "S 寶寶在按鈕裡");
  assert.ok(text(s).includes("SYNOX") && text(s).includes("點一下打開 SYNOX"));
  assert.ok(text(s).includes("Enter"), "有鍵盤的：提示也寫按 Enter");
  assert.ok(!text(S.build(fakeDoc(), true)).includes("Enter"), "觸控螢幕：只寫點一下");
});

test("open waits for the click: no timer takes it away", () => {
  withTimers((flush) => {
    const doc = fakeDoc();
    const gate = S.open(doc, false, false);
    assert.strictEqual(doc.body.children.length, 1);
    assert.ok(S.isOpen() && gate.isOpen());
    assert.ok(doc.documentElement.classList.contains("sx-hold"), "後面的內容先停著");
    assert.strictEqual(doc.activeElement && doc.activeElement.tag, "button", "焦點在門的按鈕上");
    flush();
    assert.strictEqual(doc.body.children.length, 1, "不會自己消失");
    assert.ok(S.isOpen());
    assert.strictEqual(S.open(doc, false, false), gate, "同時只會有一個門");
    assert.strictEqual(doc.body.children.length, 1);
    doc.body.children[0].events.click();               // 點一下
    assert.ok(doc.body.children[0].classList.contains("sx-leave"), "放大淡出");
    assert.ok(!doc.documentElement.classList.contains("sx-hold"), "點了內容馬上開始浮上來");
    flush();
    assert.strictEqual(doc.body.children.length, 0);
    assert.ok(!S.isOpen());
    assert.ok(!doc.listeners.keydown);
    assert.ok(!doc.documentElement.classList.contains("sx-intro"));
    assert.deepStrictEqual(doc.events, [S.DONE], "通知教學：門關了");
  });
});

test("keyboard: Enter / Space / Escape enter, Tab stays on the button, other keys do nothing", () => {
  for (const k of ["Enter", " ", "Escape"]) {
    withTimers((flush) => {
      const doc = fakeDoc();
      S.open(doc, false, false);
      const other = key("a");
      doc.listeners.keydown(other);
      assert.ok(!other.stopped && S.isOpen());
      doc.activeElement = null;
      const tab = key("Tab");
      doc.listeners.keydown(tab);
      assert.ok(tab.stopped && doc.activeElement.tag === "button", "Tab 不會跑到後面");
      const ev = key(k);
      doc.listeners.keydown(ev);
      assert.ok(ev.stopped, k);
      flush();
      assert.strictEqual(doc.body.children.length, 0, k);
      assert.ok(!S.isOpen());
    });
  }
});

test("reduced motion: a still last frame that still waits, then goes away at once", () => {
  withTimers((flush) => {
    const doc = fakeDoc();
    S.open(doc, true, true);
    const gate = doc.body.children[0];
    assert.ok(gate.classList.contains("sx-still"));
    assert.strictEqual(doc.activeElement, null, "觸控螢幕不搶焦點");
    flush();
    assert.ok(S.isOpen(), "一樣等你點");
    gate.events.click();
    assert.strictEqual(doc.body.children.length, 0, "點了馬上進去");
    assert.ok(!S.isOpen());
  });
});

test("focus goes back to what opened it (the S in the corner)", () => {
  withTimers((flush) => {
    const doc = fakeDoc();
    const corner = doc.createElement("button");
    corner.focus();
    S.open(doc, false, false);
    assert.notStrictEqual(doc.activeElement, corner);
    doc.listeners.keydown(key("Enter"));
    flush();
    assert.strictEqual(doc.activeElement, corner);
  });
});

test("a broken DOM still releases the page", () => {
  withTimers(() => {
    const doc = fakeDoc();
    doc.createElement = () => { throw new Error("boom"); };
    S.open(doc, false, false);
    assert.ok(!doc.documentElement.classList.contains("sx-hold"), "出錯時不能讓內容停在看不見");
    assert.ok(!S.isOpen(), "不能讓人卡在門口");
    assert.ok(!doc.listeners.keydown);
  });
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + (e && e.stack || e)); }
}
process.exit(failed ? 1 : 0);
