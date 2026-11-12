// 對話頁的區塊畫法（src/synox/web/static/blocks.js），用假的 document 測。
// tests/test_present_wiring.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const B = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "blocks.js"));

// 假的 DOM：只有 createElement／createTextNode／appendChild／textContent；設 innerHTML 一律丟例外
class Text { constructor(t) { this.nodeType = 3; this.data = t; } get textContent() { return this.data; } }
class Elem {
  constructor(tag) { this.nodeType = 1; this.tagName = tag; this.children = []; this.className = ""; }
  appendChild(c) { this.children.push(c); return c; }
  set textContent(t) { this.children = [new Text(String(t))]; }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  set innerHTML(_v) { throw new Error("innerHTML must not be used"); }
  set outerHTML(_v) { throw new Error("outerHTML must not be used"); }
}
const doc = { createElement: (t) => new Elem(t), createTextNode: (t) => new Text(t) };

function tags(node, out = []) {
  if (node.nodeType === 1) { out.push(node.tagName); node.children.forEach((c) => tags(c, out)); }
  return out;
}
function find(node, tag) { return tags(node).includes(tag) ? walk(node).find((n) => n.tagName === tag) : null; }
function walk(node, out = []) { out.push(node); (node.children || []).forEach((c) => walk(c, out)); return out; }

const ALLOWED = new Set(["div", "p", "h3", "h4", "h5", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
                         "pre", "code", "b", "i", "a", "blockquote", "span"]);
const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("paragraph spans become b/i/code/a with textContent", () => {
  const box = B.render(doc, [{ type: "paragraph", spans: [
    { text: "粗", bold: true }, { text: " 斜", italic: true }, { text: "x()", code: true },
    { text: "連結", href: "https://example.com/" }] }]);
  assert.strictEqual(box.className, "text blocks");
  assert.strictEqual(box.textContent, "粗 斜x()連結");
  const a = find(box, "a");
  assert.strictEqual(a.href, "https://example.com/");
  assert.strictEqual(a.rel, "noopener noreferrer");
  assert.deepStrictEqual(tags(box), ["div", "p", "b", "i", "code", "a"]);
});

test("markup-looking text stays text", () => {
  const evil = "<script>alert(1)</script><b onclick=x>hi</b>&lt;";
  const box = B.render(doc, [{ type: "paragraph", spans: [{ text: evil }] }, { type: "code", code: evil }]);
  assert.strictEqual(box.textContent, evil + evil);
  assert.ok(!tags(box).includes("script"));
});

test("only http/https links become anchors", () => {
  for (const href of ["javascript:alert(1)", "JAVASCRIPT:x", "data:text/html,x", "file:///etc/passwd", "/admin", "", 5]) {
    const box = B.render(doc, [{ type: "paragraph", spans: [{ text: "點我", href }] }]);
    assert.ok(!tags(box).includes("a"), String(href));
    assert.strictEqual(box.textContent, "點我");
  }
  assert.strictEqual(B.safeHref("http://x.example"), "http://x.example");
});

test("every block type renders with allowed tags only; unknown types are skipped", () => {
  const box = B.render(doc, [
    { type: "heading", level: 1, spans: [{ text: "H" }] },
    { type: "heading", level: 9, spans: [{ text: "H5" }] },
    { type: "list", ordered: true, start: 3, items: [{ spans: [{ text: "a" }],
      children: { type: "list", ordered: false, items: [{ spans: [{ text: "a1" }] }] } }] },
    { type: "quote", paragraphs: [[{ text: "q" }]] },
    { type: "table", header: [[{ text: "h" }]], rows: [[[{ text: "v" }]]] },
    { type: "status", tone: "ok", icon: "✅", label: "完成" },
    { type: "status", tone: "<evil>", label: "x" },
    { type: "confirm", title: "確定？", lines: ["會刪掉 3 筆"] },
    { type: "buttons", rows: [[{ text: "✅", data: "agent_ok:go:1" }]] },
    { type: "script", code: "alert(1)" },
    null, "x"
  ]);
  walk(box).filter((n) => n.nodeType === 1).forEach((n) => assert.ok(ALLOWED.has(n.tagName), n.tagName));
  assert.ok(!tags(box).includes("button"));
  assert.strictEqual(find(box, "ol").start, 3);
  const spans = walk(box).filter((n) => n.tagName === "span");
  assert.deepStrictEqual(spans.map((s) => s.className), ["status status-ok", "status status-info"]);
  assert.ok(box.textContent.includes("✅ 完成") && box.textContent.includes("會刪掉 3 筆"));
  assert.ok(!box.textContent.includes("alert(1)"));
});

test("garbage input does not throw", () => {
  B.render(doc, null);
  B.render(doc, [{ type: "paragraph", spans: null }, { type: "list", items: [null] }, { type: "table" }]);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
