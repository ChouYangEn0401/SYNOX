// 拖 .synoxpack 進網頁（src/synox/web/static/packdrop.js）：拖進來的檔要不要交給上傳。
// tests/test_pack_install_paths.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const P = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "packdrop.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

test("one .synoxpack or .zip under 5 MB is accepted", () => {
  assert.strictEqual(P.check([{ name: "notes-1.0.0.synoxpack", size: 1200 }]).ok, true);
  assert.strictEqual(P.check([{ name: "NOTES.SYNOXPACK", size: 1 }]).ok, true);
  assert.strictEqual(P.check([{ name: "notes.zip", size: P.MAX_BYTES }]).ok, true);
});

test("wrong count, type, size are refused with a message", () => {
  assert.strictEqual(P.check([]).ok, false);
  assert.strictEqual(P.check(null).ok, false);
  assert.strictEqual(P.check([{ name: "a.synoxpack", size: 1 }, { name: "b.synoxpack", size: 1 }]).ok, false);
  const exe = P.check([{ name: "setup.exe", size: 10 }]);
  assert.strictEqual(exe.ok, false);
  assert.ok(exe.message.indexOf("setup.exe") >= 0);
  assert.strictEqual(P.check([{ name: ".synoxpack", size: 10 }]).ok, false);
  assert.strictEqual(P.check([{ name: "x.synoxpack.exe", size: 10 }]).ok, false);
  assert.strictEqual(P.check([{ name: "x.synoxpack", size: 0 }]).ok, false);
  assert.strictEqual(P.check([{ name: "x.synoxpack", size: P.MAX_BYTES + 1 }]).ok, false);
});

test("only file drags are handled (text drags in chat are left alone)", () => {
  assert.strictEqual(P.hasFiles({ dataTransfer: { types: ["Files"] } }), true);
  assert.strictEqual(P.hasFiles({ dataTransfer: { types: ["text/plain"] } }), false);
  assert.strictEqual(P.hasFiles({}), false);
});

test("a drop always lands on the install tab (#packs), not whatever settings tab was open last", () => {
  assert.strictEqual(P.installHash(""), "#packs");
  assert.strictEqual(P.installHash("#chat"), "#packs");
  assert.strictEqual(P.installHash("#settings"), "#packs");         // 以前停在這裡：會沿用上次的分頁（例如 AI）
  assert.strictEqual(P.installHash("#settings:ai"), "#packs");
  assert.strictEqual(P.installHash("#packs"), "#packs");
  assert.strictEqual(P.installHash("#settings:packs"), "#settings:packs");   // 已經在安裝頁：不動網址
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); }
  catch (e) { failed += 1; console.log("FAIL " + name + "\n" + e.stack); }
}
process.exit(failed ? 1 : 0);
