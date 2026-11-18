// 「回覆某一則」的畫面零件（src/synox/web/static/reply.js）：回覆按鈕、引用塊、引用列、跳到原訊息。
// 假的 document，不開瀏覽器、不開埠；tests/test_web_reply.py 用 node 跑，退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const R = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "reply.js"));

class Text { constructor(t) { this.nodeType = 3; this.data = t; } get textContent() { return this.data; } }
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = tag; this.children = []; this.className = ""; this.attrs = {}; this.listeners = {};
    const self = this;
    this.classList = {
      add(c) { if (!self.classList.contains(c)) { self.className = (self.className + " " + c).trim(); } },
      remove(c) { self.className = self.className.split(" ").filter((x) => x && x !== c).join(" "); },
      contains(c) { return self.className.split(" ").includes(c); },
    };
  }
  get firstChild() { return this.children[0] || null; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); }
  set textContent(t) { this.children = [new Text(String(t))]; }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  set innerHTML(_v) { throw new Error("innerHTML must not be used"); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  click() { (this.listeners.click || []).forEach((f) => f({ stopPropagation() {} })); }
}
const doc = { createElement: (t) => new Elem(t), createTextNode: (t) => new Text(t) };
function walk(n, out = []) { out.push(n); (n.children || []).forEach((c) => walk(c, out)); return out; }
const byClass = (n, c) => walk(n).filter((x) => x.classList && x.classList.contains(c));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("reply button is a real, labelled <button> and calls back", () => {
  let n = 0;
  const b = R.button(doc, () => { n += 1; });
  assert.strictEqual(b.tagName, "button");
  assert.strictEqual(b.type, "button");
  assert.strictEqual(b.attrs["aria-label"], R.TEXT.reply_label);
  assert.strictEqual(b.textContent, R.TEXT.reply);
  b.click();
  assert.strictEqual(n, 1);
});

test("quote block shows who + excerpt and jumps to the original id", () => {
  let jumped = null;
  const q = R.quote(doc, { id: 7, from: "bot", excerpt: "Am7：A C E G" }, (id) => { jumped = id; });
  assert.strictEqual(q.tagName, "button");                                   // 鍵盤按得到
  assert.strictEqual(byClass(q, "rq-who")[0].textContent, "SYNOX");
  assert.strictEqual(byClass(q, "rq-text")[0].textContent, "Am7：A C E G");
  q.click();
  assert.strictEqual(jumped, 7);
  assert.strictEqual(R.quote(doc, null, () => {}), null);
  assert.strictEqual(byClass(R.quote(doc, { id: 1, from: "me", excerpt: "x" }, () => {}), "rq-who")[0].textContent, "你");
});

test("message text is only ever text (no html)", () => {
  const evil = "<img src=x onerror=alert(1)><script>x</script>";
  const q = R.quote(doc, { id: 1, from: "<b>bot</b>", excerpt: evil }, () => {});
  assert.ok(walk(q).every((n) => n.nodeType === 3 || ["button", "span"].includes(n.tagName)));
  assert.strictEqual(byClass(q, "rq-text")[0].textContent, evil);
  assert.strictEqual(byClass(q, "rq-who")[0].textContent, "SYNOX");          // 不認得的身分不照抄
  const box = new Elem("div");
  R.bar(doc, box, { id: 1, from: "bot", text: evil }, () => {});
  assert.ok(walk(box).every((n) => n.nodeType === 3 || ["div", "span", "button"].includes(n.tagName)));
});

test("quote bar: shows, one-line excerpt, ✕ cancels, null hides", () => {
  const box = new Elem("div"); box.classList.add("hidden");
  let cancelled = 0;
  R.bar(doc, box, { id: 3, from: "bot", text: "第一行\n\n第二行   很多空白" + "長".repeat(200) }, () => { cancelled += 1; });
  assert.ok(!box.classList.contains("hidden"));
  assert.strictEqual(byClass(box, "rb-who")[0].textContent, "回覆 SYNOX");
  const t = byClass(box, "rb-text")[0].textContent;
  assert.ok(t.startsWith("第一行 第二行 很多空白") && t.length <= 80 && t.endsWith("…"), t);
  const x = byClass(box, "rb-x")[0];
  assert.strictEqual(x.attrs["aria-label"], R.TEXT.cancel);
  x.click();
  assert.strictEqual(cancelled, 1);
  R.bar(doc, box, null, () => {});
  assert.ok(box.classList.contains("hidden"));
  assert.strictEqual(box.children.length, 0);
});

test("jump scrolls + flashes when the original is loaded, false when it is gone", () => {
  const node = new Elem("div");
  let scrolled = null, timer = null;
  node.scrollIntoView = (o) => { scrolled = o; };
  assert.strictEqual(R.jump(node, (fn) => { timer = fn; }), true);
  assert.ok(scrolled && node.classList.contains("flash"));
  timer();
  assert.ok(!node.classList.contains("flash"));
  assert.strictEqual(R.jump(undefined), false);
});

test("excerpt handles empty and odd input", () => {
  assert.strictEqual(R.excerpt(""), R.TEXT.empty);
  assert.strictEqual(R.excerpt(null), R.TEXT.empty);
  assert.strictEqual(R.excerpt(42), "42");
  assert.strictEqual(R.excerpt("abcdef", 4), "abc…");
  assert.strictEqual(R.excerpt("**Am7** 的按法：\n- 食指\n```text\ne|---0---|\n```\n> 引用 `x00232`"),
                     "Am7 的按法： 食指 e|---0---| 引用 x00232");           // Markdown 記號不進摘要
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
