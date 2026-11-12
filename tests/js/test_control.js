// 主控頁（src/synox/web/static/control.js）的純函式與 API 呼叫，用假 fetch 測。
// tests/test_control_panel.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const C = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "control.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

// 假 fetch：記下每一次呼叫，回事先排好的回應
function fakeFetch(responses) {
  const calls = [];
  const fn = (url, opts) => {
    calls.push({ url, method: opts.method, headers: opts.headers, body: opts.body ? JSON.parse(opts.body) : undefined });
    const r = responses.shift();
    if (r === "network") { return Promise.reject(new TypeError("Failed to fetch")); }
    const status = r && r.status ? r.status : 200;
    const json = r && r.json !== undefined ? r.json : r;
    return Promise.resolve({
      ok: status >= 200 && status < 300, status,
      headers: { get: () => "application/json; charset=utf-8" },
      json: () => Promise.resolve(json)
    });
  };
  fn.calls = calls;
  return fn;
}

const NOW = new Date(2026, 10, 12, 14, 5, 0);          // 本機時間 2026-11-12 14:05
const minutes = (m) => new Date(NOW.getTime() + m * 60000).toISOString();

test("relative time in plain words", () => {
  assert.strictEqual(C.relative(minutes(-3), NOW), "3 分鐘前");
  assert.strictEqual(C.relative(minutes(45), NOW), "45 分鐘後");
  assert.strictEqual(C.relative(minutes(0), NOW), "剛剛");
  assert.strictEqual(C.relative(minutes(-180), NOW), "3 小時前");
  assert.strictEqual(C.relative(minutes(-2 * 1440), NOW), "2 天前");
  assert.strictEqual(C.relative(null, NOW), "");
});

test("when(): clock time plus relative, date when not today, fallback for null/garbage", () => {
  assert.strictEqual(C.when(minutes(-3), NOW), "14:02（3 分鐘前）");
  assert.strictEqual(C.when(new Date(2026, 10, 10, 9, 7).toISOString(), NOW), "11/10 09:07（2 天前）");
  assert.strictEqual(C.when(null, NOW), "還沒有");
  assert.strictEqual(C.when(null, NOW, "還沒跑過"), "還沒跑過");
  assert.strictEqual(C.when("not a date", NOW, "—"), "—");
});

test("task states: colour + text + shape class for every contract state", () => {
  assert.deepStrictEqual(C.taskState("ok"), { tone: "ok", label: "正常" });
  assert.deepStrictEqual(C.taskState("running"), { tone: "run", label: "執行中" });
  assert.deepStrictEqual(C.taskState("failed"), { tone: "bad", label: "失敗" });
  assert.deepStrictEqual(C.taskState("idle"), { tone: "idle", label: "閒置" });
  assert.strictEqual(C.taskState("weird").label, "不明");
  ["idle", "running", "off"].forEach((s) => assert.ok(C.motherState(s).label && C.motherState(s).hint));
});

test("interval validation: integers 5..1440 only", () => {
  assert.deepStrictEqual(C.validateInterval("45"), { ok: true, value: 45 });
  assert.deepStrictEqual(C.validateInterval(" 5 "), { ok: true, value: 5 });
  assert.strictEqual(C.validateInterval("1440").ok, true);
  ["4", "1441", "0", "-5", "4.5", "abc", "", null].forEach((v) => {
    const r = C.validateInterval(v);
    assert.strictEqual(r.ok, false, String(v));
    assert.ok(/分鐘/.test(r.error));
  });
});

test("normalizeStatus survives missing / broken fields", () => {
  const s = C.normalizeStatus(null);
  assert.strictEqual(s.heartbeat.enabled, false);
  assert.strictEqual(s.heartbeat.interval_min, 45);
  assert.strictEqual(s.mother.state, "off");
  assert.deepStrictEqual(s.tasks, []);
  const t = C.normalizeStatus({ tasks: [null, { name: "沒有 id" }, { id: 7 }] }).tasks;
  assert.strictEqual(t.length, 1);
  assert.deepStrictEqual(t[0], { id: "7", name: "7", owner: "", schedule: "", state: "idle", last_run_at: null,
                                 last_message: "" });
});

test("viewModel turns the contract shape into the words on screen", () => {
  const v = C.viewModel({
    heartbeat: { enabled: true, interval_min: 45, last_run_at: minutes(-12), next_run_at: minutes(33),
                 last_result: { ok: false, message: "讀不到資料" } },
    mother: { state: "idle", last_active_at: minutes(-3), soul_updated_at: null },
    tasks: [
      { id: "a", name: "早上的摘要", owner: "SYNOX", schedule: "每天 08:00", state: "ok", last_run_at: minutes(-300),
        last_message: "送出了" },
      { id: "b", name: "預算檢查", owner: "example", schedule: "每 6 小時", state: "failed", last_run_at: null,
        last_message: "" }
    ]
  }, NOW);
  assert.strictEqual(v.mother.label, "待命中");
  assert.strictEqual(v.mother.lastActive, "14:02（3 分鐘前）");
  assert.strictEqual(v.mother.soulUpdated, "還沒寫過");
  assert.strictEqual(v.heartbeat.next, "14:38（33 分鐘後）");
  assert.strictEqual(v.heartbeat.every, "每 45 分鐘");
  assert.strictEqual(v.heartbeat.lastResult, "沒有成功：讀不到資料");
  assert.strictEqual(v.heartbeat.lastFailed, true);
  assert.strictEqual(v.summary, "2 個任務：1 個失敗、1 個正常");
  assert.strictEqual(v.taskBrief, "1 個失敗，共 2 個");
  assert.strictEqual(v.anyFailed, true);
  assert.strictEqual(v.tasks[1].label, "失敗");
  assert.strictEqual(v.tasks[1].last, "還沒跑過");
  const off = C.viewModel({ heartbeat: { enabled: false, interval_min: 45, next_run_at: minutes(10) } }, NOW);
  assert.strictEqual(off.heartbeat.next, "關著，不會自己跑");
  assert.strictEqual(off.summary, "還沒有排定的任務。");
  assert.strictEqual(off.taskBrief, "沒有");
  assert.strictEqual(C.resultText("看過一輪"), "看過一輪");
  assert.strictEqual(C.resultText(null), "還沒跑過");
});

test("humanError never shows status codes, exception names or CSRF", () => {
  const cases = [
    [{ status: 0 }, /連不到 SYNOX/],
    [{ status: 401, serverMessage: "請先登入：…" }, /登入過期/],
    [{ status: 403, serverMessage: "缺少或不對的 CSRF token（重新整理頁面再試）。" }, /重新整理/],
    [{ status: 403, serverMessage: "只有擁有者能做這件事。" }, /只有擁有者/],
    [{ status: 404, serverMessage: "沒有這個 API。" }, /還沒有主控功能/],
    [{ status: 500, serverMessage: "出錯了：KeyError" }, /SYNOX 那邊出了問題/],
    [{ status: 400, serverMessage: "間隔要在 5～1440 分鐘之間。" }, /間隔要在/],
    [{ status: 400, serverMessage: "ValueError: bad" }, /沒有成功/],
    [undefined, /連不到 SYNOX/]
  ];
  cases.forEach(([err, want]) => {
    const text = C.humanError(err);
    assert.ok(want.test(text), JSON.stringify(err) + " → " + text);
    assert.ok(!/CSRF|Error|HTTP|\b[45]\d\d\b|null|undefined/.test(text), text);
  });
});

test("canSee: only the owner", () => {
  assert.strictEqual(C.canSee({ owner: true }), true);
  assert.strictEqual(C.canSee({ owner: false, role: "admin" }), false);
  assert.strictEqual(C.canSee(null), false);
});

test("reset-memory confirmation says what goes and what stays", () => {
  assert.ok(C.RESET_CLEARS.some((t) => /記得的對話/.test(t)));
  ["soul.md", "對話", "工具", "heartbeat"].forEach((w) => assert.ok(C.RESET_KEEPS.some((t) => t.indexOf(w) >= 0), w));
});

test("client follows the API contract exactly (paths, methods, bodies, CSRF on writes only)", async () => {
  const f = fakeFetch([
    { heartbeat: {}, mother: {}, tasks: [] },
    { enabled: false, interval_min: 45 },
    { enabled: true, interval_min: 30 },
    { ok: true, message: "開始了" },
    { ok: true },
    { text: "叫我小明", updated_at: null },
    { text: "新的", updated_at: "2026-11-12T06:00:00Z" },
    { lines: ["a", "b"] }
  ]);
  const c = C.makeClient(f, () => "tok123");
  await c.status();
  await c.setHeartbeat({ enabled: false });
  await c.setHeartbeat({ interval_min: 30 });
  assert.deepStrictEqual(await c.runNow(), { ok: true, message: "開始了" });
  await c.resetMemory();
  assert.strictEqual((await c.soul()).text, "叫我小明");
  await c.saveSoul("新的");
  assert.deepStrictEqual((await c.taskLog("daily/../x y")).lines, ["a", "b"]);
  const got = f.calls.map((x) => [x.method, x.url, x.body]);
  assert.deepStrictEqual(got, [
    ["GET", "/api/runtime/status", undefined],
    ["POST", "/api/runtime/heartbeat", { enabled: false }],
    ["POST", "/api/runtime/heartbeat", { interval_min: 30 }],
    ["POST", "/api/runtime/heartbeat/run-now", {}],
    ["POST", "/api/runtime/mother/reset-memory", {}],
    ["GET", "/api/runtime/soul", undefined],
    ["PUT", "/api/runtime/soul", { text: "新的" }],
    ["GET", "/api/runtime/tasks/daily%2F..%2Fx%20y/log", undefined]
  ]);
  f.calls.forEach((x) => {
    if (x.method === "GET") { assert.strictEqual(x.headers["X-SYNOX-CSRF"], undefined); }
    else {
      assert.strictEqual(x.headers["X-SYNOX-CSRF"], "tok123");
      assert.strictEqual(x.headers["Content-Type"], "application/json");
    }
  });
});

test("client errors carry the status and the server's own words; network failures are status 0", async () => {
  const f = fakeFetch([{ status: 403, json: { error: "只有擁有者能做這件事。" } }, "network", { status: 500, json: {} }]);
  const c = C.makeClient(f, () => "t");
  await assert.rejects(c.status(), (e) => e.status === 403 && e.serverMessage === "只有擁有者能做這件事。");
  await assert.rejects(c.runNow(), (e) => e.status === 0);
  await assert.rejects(c.resetMemory(), (e) => e.status === 500 && C.humanError(e).indexOf("500") < 0);
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok   " + name); }
    catch (e) { failed += 1; console.log("FAIL " + name + "\n     " + (e && e.message)); }
  }
  console.log(failed ? failed + " failed" : "all " + tests.length + " passed");
  process.exit(failed ? 1 : 0);
})();
