// AI 回的 Markdown（沒有 blocks 的 bot 訊息）→ 區塊（src/synox/web/static/blocks.js 的 markdown），再用同一個 render 畫。
// 假的 document，不開瀏覽器、不開埠；tests/test_web_reply.py 用 node 跑，退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const B = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "blocks.js"));

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
function walk(n, out = []) { out.push(n); (n.children || []).forEach((c) => walk(c, out)); return out; }
const tags = (n) => walk(n).filter((x) => x.nodeType === 1).map((x) => x.tagName);
const find = (n, tag) => walk(n).filter((x) => x.tagName === tag);
const draw = (md) => B.render(doc, B.markdown(md));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("plain text is not markdown: stays on linkText (null)", () => {
  for (const s of ["好的，已經記下 80 元咖啡。", "/money_month 看這個月\n第二行", "2*3=6 不是斜體？", "a_b_c 底線不算", ""]) {
    assert.strictEqual(B.markdown(s), null, s);
  }
});

test("bold, italic and inline code", () => {
  const box = draw("和弦 **D/F#** 和 *Am7*，指法 `x00232`");
  assert.strictEqual(find(box, "b")[0].textContent, "D/F#");
  assert.strictEqual(find(box, "i")[0].textContent, "Am7");
  assert.strictEqual(find(box, "code")[0].textContent, "x00232");
  assert.strictEqual(box.textContent, "和弦 D/F# 和 Am7，指法 x00232");
});

test("fenced code keeps spacing and tabs inside <pre><code>", () => {
  const tab = "e|---0---|\nB|---1---|\n\tG|--2--|";
  const box = draw("看這個 TAB：\n```text\n" + tab + "\n```\n下一段");
  const pre = find(box, "pre");
  assert.strictEqual(pre.length, 1);
  assert.strictEqual(pre[0].children[0].tagName, "code");
  assert.strictEqual(pre[0].textContent, tab);
  assert.ok(!pre[0].textContent.includes("```"));
  assert.deepStrictEqual(find(box, "p").map((p) => p.textContent), ["看這個 TAB：", "下一段"]);
});

test("unclosed fence runs to the end; ~~~ works; markdown inside code stays literal", () => {
  assert.strictEqual(find(draw("```\n**not bold**\n# not heading"), "pre")[0].textContent, "**not bold**\n# not heading");
  assert.strictEqual(find(draw("~~~\na\n~~~"), "pre")[0].textContent, "a");
  assert.strictEqual(find(draw("```\na\n```\n**b**"), "b")[0].textContent, "b");
});

test("lists (two levels), ordered start, headings, quote, line breaks", () => {
  const box = draw("# 標題\n1. 一\n2. 二\n   - 子項\n\n- a\n- b\n\n> 引用\n> 第二行\n\n第一行\n第二行");
  assert.deepStrictEqual(tags(box).filter((t) => ["h3", "ol", "ul", "li", "blockquote"].includes(t)),
                         ["h3", "ol", "li", "li", "ul", "li", "ul", "li", "li", "blockquote"]);
  assert.strictEqual(find(box, "blockquote")[0].textContent, "引用\n第二行");
  const ps = find(box, "p");
  assert.strictEqual(ps[ps.length - 1].textContent, "第一行\n第二行");             // 段落裡的換行照留（CSS pre-wrap）
  assert.strictEqual(B.markdown("3. x\n4. y")[0].start, 3);
});

test("tables", () => {
  const box = draw("| 和弦 | 指法 |\n|---|---|\n| Am7 | x02010 |\n| **D** | xx0232 |");
  assert.deepStrictEqual(find(box, "th").map((x) => x.textContent), ["和弦", "指法"]);
  assert.deepStrictEqual(find(box, "td").map((x) => x.textContent), ["Am7", "x02010", "D", "xx0232"]);
});

test("injection: html, javascript: links and fake markup stay text", () => {
  const evil = "**<img src=x onerror=alert(1)>** [點我](javascript:alert(1)) [ok](https://example.com/a) " +
    "<script>alert(2)</script> [d](data:text/html,x)";
  const box = draw(evil);
  const t = tags(box);
  assert.ok(!t.includes("script") && !t.includes("img"), t.join(","));
  const as = find(box, "a");
  assert.deepStrictEqual(as.map((a) => a.href), ["https://example.com/a"]);
  assert.strictEqual(as[0].rel, "noopener noreferrer");
  assert.ok(box.textContent.includes("<img src=x onerror=alert(1)>"));
  assert.ok(box.textContent.includes("[點我](javascript:alert(1))"));
  assert.ok(box.textContent.includes("<script>alert(2)</script>"));
  const code = draw("```\n<script>alert(3)</script>\n```");
  assert.strictEqual(find(code, "pre")[0].textContent, "<script>alert(3)</script>");
});

test("bare urls inside markdown still become safe links", () => {
  const box = draw("**看** https://example.com/x，然後 http://a.example/b。");
  assert.deepStrictEqual(find(box, "a").map((a) => a.href), ["https://example.com/x", "http://a.example/b"]);
});

test("long hostile input stays linear (no hang)", () => {
  const big = "*".repeat(20000) + "`".repeat(20000) + "[".repeat(20000) + "\n- ".repeat(5000);
  const t0 = Date.now();
  B.markdown(big);
  assert.ok(Date.now() - t0 < 3000, "took " + (Date.now() - t0) + "ms");
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
