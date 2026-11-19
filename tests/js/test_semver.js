// 網頁的版本比較（src/synox/web/static/semver.js）＋ app.html 實際用的 verNewer（工具庫、衣櫃的「有新版」）。
// 規則跟伺服器的 packs/upgrade.semver_key 一樣（docs/versioning.md §1；tests/test_version_rules.py 是 Python 那份）。
// tests/test_web_semver.py 用 node 跑，退出碼 0＝全過。不開瀏覽器、不開埠。
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const STATIC = path.join(__dirname, "..", "..", "src", "synox", "web", "static");
const S = require(path.join(STATIC, "semver.js"));

// app.html 裡的 verNewer（連同它用到的 verKey，舊版才有）原樣拿出來跑：網頁實際用的就是這一份
function shippedVerNewer() {
  const html = fs.readFileSync(path.join(STATIC, "app.html"), "utf8");
  const start = html.search(/function verKey\(|function verNewer\(/);
  const end = html.indexOf("function libFail(", start);
  assert.ok(start >= 0 && end > start, "app.html 找不到 verNewer");
  // eslint-disable-next-line no-new-func
  return new Function("SynoxSemver", html.slice(start, end) + "\nreturn verNewer;")(S);
}

const SYNOX_PATH = ["0.2.0", "0.2.1-alpha.1", "0.2.1-beta.1", "0.2.1-beta.2", "0.2.2-alpha.1", "0.2.2-alpha.2",
  "0.2.2-beta.1", "0.2.2-rc.1", "0.2.2", "0.2.3-alpha.1", "0.3.0"];
const TOOL_PATH = ["0.1.2", "0.1.3-alpha.1", "0.1.3-alpha.2", "0.1.3-alpha.10", "0.1.3-beta.1", "0.1.3", "0.1.4",
  "0.1.10", "1.0.9", "1.0.10"];
const SPEC_ORDER = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
  "1.0.0-rc.1", "1.0.0"];

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function checkOrder(newer, order) {
  for (let i = 0; i < order.length; i++) {
    for (let j = i + 1; j < order.length; j++) {
      assert.ok(newer(order[j], order[i]), order[j] + " 應該比 " + order[i] + " 新");
      assert.ok(!newer(order[i], order[j]), order[i] + " 不應該比 " + order[j] + " 新");
    }
  }
}

for (const [label, newer] of [["semver.js", () => S.newer], ["app.html verNewer", shippedVerNewer]]) {
  test(label + ": SYNOX alpha → beta → 下一版 alpha → 正式版", () => checkOrder(newer(), SYNOX_PATH));
  test(label + ": 工具 0.1.2 → 0.1.3-alpha.1 → 0.1.3 → 1.0.10（數字按數值比）", () => checkOrder(newer(), TOOL_PATH));
  test(label + ": SemVer 規格的例子", () => checkOrder(newer(), SPEC_ORDER));
  test(label + ": +build 不看、一樣的不算新", () => {
    const n = newer();
    assert.ok(!n("1.0.0+build.2", "1.0.0+build.1") && !n("1.0.0", "1.0.0+x") && !n("0.2.2-alpha.1", "0.2.2-alpha.1"));
  });
  test(label + ": 看不懂的不算新", () => {
    const n = newer();
    for (const bad of ["", "1.0", "v1.0.0", "1.0.0-alpha.01", "01.0.0", "1.0.0-", null, undefined]) {
      assert.ok(!n(bad, "1.0.0") && !n("1.0.0", bad), String(bad));
    }
  });
}

test("compare 回 -1／0／1／null", () => {
  assert.strictEqual(S.compare("0.2.1-beta.2", "0.2.2-alpha.1"), -1);
  assert.strictEqual(S.compare("0.2.2", "0.2.2+meta"), 0);
  assert.strictEqual(S.compare("1.0.10", "1.0.9"), 1);
  assert.strictEqual(S.compare("x", "1.0.0"), null);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
