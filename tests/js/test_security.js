// 🔐 安全（src/synox/web/static/security.js）的純邏輯：403 stepup → 問碼 → 解鎖 → 原本的請求重送一次；取消 → 不重送。
// tests/test_stepup_web.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const S = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "security.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

function fakeApi(results) {
  const calls = [];
  const api = (method, p, body) => {
    calls.push([method, p, body]);
    const r = results.shift();
    return r instanceof Error ? Promise.reject(r) : Promise.resolve(r || {});
  };
  return { api, calls };
}

// app.html 的 api() 被擋下時做的事（同一個寫法）：問碼 → 成功就重送
function withRetry(asker, request) {
  return request().catch((err) => {
    if (S.isStepUp(err.status, err.data)) { return asker.ask().then(() => request()); }
    throw err;
  });
}

test("403 stepup → prompt → unlock → original request sent again once", async () => {
  const { api, calls } = fakeApi([{ ok: true, left_s: 900 }]);
  const prompts = [];
  const asker = S.makeAsker({ api, prompt: (hint) => { prompts.push(hint); return Promise.resolve("123456"); } });
  let sent = 0;
  const request = () => {
    sent += 1;
    if (sent === 1) { const e = new Error("x"); e.status = 403; e.data = { code: "stepup" }; return Promise.reject(e); }
    return Promise.resolve("done");
  };
  assert.strictEqual(await withRetry(asker, request), "done");
  assert.strictEqual(sent, 2);
  assert.deepStrictEqual(calls, [["POST", "/api/stepup/unlock", { code: "123456" }]]);
  assert.strictEqual(prompts.length, 1);
});

test("cancel → no unlock call, request not resent", async () => {
  const { api, calls } = fakeApi([]);
  const asker = S.makeAsker({ api, prompt: () => Promise.resolve(null) });
  let sent = 0;
  const request = () => { sent += 1; const e = new Error("x"); e.status = 403; e.data = { code: "stepup" }; return Promise.reject(e); };
  await assert.rejects(withRetry(asker, request));
  assert.strictEqual(sent, 1);
  assert.strictEqual(calls.length, 0);
});

test("wrong code asks again with the reason, then succeeds", async () => {
  const { api, calls } = fakeApi([new Error("驗證碼不對"), { ok: true }]);
  const hints = [];
  const codes = ["000000", "123456"];
  const asker = S.makeAsker({ api, prompt: (hint) => { hints.push(hint); return Promise.resolve(codes.shift()); } });
  await asker.ask();
  assert.strictEqual(calls.length, 2);
  assert.ok(hints[1].indexOf("驗證碼不對") >= 0);
});

test("two blocked requests share one prompt", async () => {
  const { api } = fakeApi([{ ok: true }]);
  let asked = 0;
  const asker = S.makeAsker({ api, prompt: () => { asked += 1; return Promise.resolve("123456"); } });
  await Promise.all([asker.ask(), asker.ask()]);
  assert.strictEqual(asked, 1);
});

test("other 403s are not step-up", () => {
  assert.ok(!S.isStepUp(403, { code: "csrf" }));
  assert.ok(!S.isStepUp(400, { code: "stepup" }));
  assert.ok(S.isStepUp(403, { code: "stepup" }));
});

test("status line and texts", () => {
  assert.strictEqual(S.statusLine({ enrolled: false }), S.TEXT.notSet);
  assert.strictEqual(S.statusLine({ enrolled: true, protect_danger: true }), S.TEXT.setOn);
  assert.strictEqual(S.fill("還剩 {n} 組", { n: 3 }), "還剩 3 組");
  const all = Object.values(S.TEXT).join("\n");
  for (const word of ["TOTP", "2FA", "token", "Token", "session", "step-up"]) {
    assert.ok(all.indexOf(word) < 0, word);
  }
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok - " + name); } catch (e) { failed += 1; console.log("FAIL - " + name + "\n" + e.stack); }
  }
  process.exit(failed ? 1 : 0);
})();
