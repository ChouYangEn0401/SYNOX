// 純文字訊息裡的網址變成連結（src/synox/web/static/blocks.js 的 linkText），用假的 document 測。
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
const links = (box) => box.children.filter((n) => n.tagName === "a");

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("plain text without a url stays one text node in div.text", () => {
  const box = B.linkText(doc, "沒有網址\n第二行");
  assert.strictEqual(box.tagName, "div");
  assert.strictEqual(box.className, "text");
  assert.strictEqual(box.children.length, 1);
  assert.strictEqual(box.children[0].nodeType, 3);
  assert.strictEqual(box.textContent, "沒有網址\n第二行");
});

test("http and https urls become links; the text around them is kept as text", () => {
  const msg = "mvp 網頁開著：2 個專案\n網頁：http://127.0.0.1:8790/ 或 https://example.com/a?b=1&c=2#x 看看";
  const box = B.linkText(doc, msg);
  assert.strictEqual(box.textContent, msg);
  const a = links(box);
  assert.deepStrictEqual(a.map((x) => x.href), ["http://127.0.0.1:8790/", "https://example.com/a?b=1&c=2#x"]);
  a.forEach((x) => {
    assert.strictEqual(x.target, "_blank");
    assert.strictEqual(x.rel, "noopener noreferrer");
    assert.strictEqual(x.textContent, x.href);
  });
});

test("full-width text and sentence punctuation are not part of the url", () => {
  const box = B.linkText(doc, "看這裡https://example.com/x，然後（http://a.example/b）。最後 https://example.com/end.");
  assert.deepStrictEqual(links(box).map((x) => x.href),
                         ["https://example.com/x", "http://a.example/b", "https://example.com/end"]);
  assert.ok(box.textContent.endsWith("https://example.com/end."));
});

test("javascript:, data: and other schemes never become links", () => {
  const msg = "javascript:alert(1) data:text/html,<b>x</b> ftp://example.com/ file:///c/x mailto:a@example.com";
  const box = B.linkText(doc, msg);
  assert.strictEqual(links(box).length, 0);
  assert.strictEqual(box.textContent, msg);
});

test("a url hidden after javascript: only links the http part; the href is always http(s)", () => {
  const box = B.linkText(doc, "javascript:http://evil.example/");
  const a = links(box);
  assert.strictEqual(a.length, 1);
  assert.ok(/^https?:\/\//.test(a[0].href));
  assert.strictEqual(box.textContent, "javascript:http://evil.example/");
});

test("quotes and angle brackets end the url (no attribute or tag injection)", () => {
  const box = B.linkText(doc, 'x https://example.com/"onmouseover="alert(1) <https://example.com/y>');
  assert.deepStrictEqual(links(box).map((x) => x.href), ["https://example.com/", "https://example.com/y"]);
});

test("a bare scheme is not a link", () => {
  const box = B.linkText(doc, "http:// 跟 https://. 都不是");
  assert.strictEqual(links(box).length, 0);
  assert.strictEqual(box.textContent, "http:// 跟 https://. 都不是");
});

test("null, undefined and numbers do not throw", () => {
  assert.strictEqual(B.linkText(doc, null).textContent, "");
  assert.strictEqual(B.linkText(doc, undefined).textContent, "");
  assert.strictEqual(B.linkText(doc, 42).textContent, "42");
});

test("calling it twice in a row gives the same result (no leftover regex state)", () => {
  const msg = "a https://example.com/1 b";
  assert.strictEqual(links(B.linkText(doc, msg)).length, 1);
  assert.strictEqual(links(B.linkText(doc, msg)).length, 1);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
