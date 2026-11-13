// 「遇到問題？」（src/synox/web/static/report.js）：到 GitHub 開問題單的網址怎麼組、太長的時候怎麼辦。
// tests/test_web_report.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const R = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "report.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("the issue link always uses the plain-Chinese form", () => {
  const url = R.issueUrl("");
  assert.strictEqual(url, R.ISSUE_NEW + "?template=" + R.TEMPLATE);
  assert.ok(R.ISSUE_NEW.indexOf("https://github.com/ChouYangEn0401/SYNOX/issues/new") === 0);
});

test("a short summary is prefilled into the summary field, fully encoded", () => {
  const text = "SYNOX 版本：0.2.0\nAI：local & more #1 ?x=y";
  const plan = R.issuePlan(text);
  assert.strictEqual(plan.copy, false);
  assert.ok(plan.url.length <= R.MAX_URL);
  const q = new URL(plan.url).searchParams;
  assert.strictEqual(q.get("template"), R.TEMPLATE);
  assert.strictEqual(q.get(R.FIELD), text);                 // 原樣回得來（換行、&、#、? 都有編碼）
  assert.strictEqual(Array.from(q.keys()).length, 2);       // 沒有塞別的參數
});

test("blank or whitespace summary opens the empty form", () => {
  assert.deepStrictEqual(R.issuePlan("   \n "), { url: R.issueUrl(""), copy: false });
  assert.deepStrictEqual(R.issuePlan(null), { url: R.issueUrl(""), copy: false });
});

test("a summary too long for a link is copied instead, and the link stays short", () => {
  const long = "最近的錯誤：" + "長".repeat(3000);           // 中文編碼後一個字 9 個字元
  const plan = R.issuePlan(long);
  assert.strictEqual(plan.copy, true);
  assert.strictEqual(plan.url, R.issueUrl(""));
  assert.ok(plan.url.length <= R.MAX_URL);
});

test("the limit is on the whole encoded URL, right at the edge", () => {
  const base = R.issueUrl("").length + ("&" + R.FIELD + "=").length;
  const fits = "a".repeat(R.MAX_URL - base);
  assert.strictEqual(R.issuePlan(fits).copy, false);
  assert.strictEqual(R.issuePlan(fits + "a").copy, true);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok - " + name); }
  catch (err) { failed += 1; console.log("not ok - " + name + "\n" + (err && err.stack)); }
}
process.exit(failed ? 1 : 0);
