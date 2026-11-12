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

test("interval validation: integers 15..1440 only", () => {
  assert.deepStrictEqual(C.validateInterval("45"), { ok: true, value: 45 });
  assert.deepStrictEqual(C.validateInterval(" 15 "), { ok: true, value: 15 });
  assert.strictEqual(C.validateInterval("1440").ok, true);
  ["14", "1441", "0", "-5", "4.5", "abc", "", null].forEach((v) => {
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

test("mother is off because no AI source is set: the hint points to settings", () => {
  const noAi = C.viewModel({ heartbeat: { enabled: true, interval_min: 45 }, mother: { state: "off", ai: false } }, NOW);
  assert.ok(noAi.mother.hint.includes("設定"));
  const disabled = C.viewModel({ heartbeat: { enabled: true, interval_min: 45 }, mother: { state: "off", ai: true } }, NOW);
  assert.ok(!disabled.mother.hint.includes("AI 來源"));
  const old = C.viewModel({ heartbeat: { enabled: true, interval_min: 45 }, mother: { state: "off" } }, NOW);   // 舊後端沒有 ai 欄位
  assert.ok(!old.mother.hint.includes("AI 來源"));
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

// ── 助理筆記（soul 帳本，docs/adr/0005）──────────────────────────────

test("notes client follows the API contract (paths, bodies, CSRF on writes only)", async () => {
  const f = fakeFetch([{ notes: [] }, { notes: [] }, { notes: [] }, { done: false }, { ok: true }, { format: "x" }]);
  const c = C.makeClient(f, () => "tok123");
  await c.notes();
  await c.proposal("p-1", "replace");
  await c.note("abc123", "retire");
  await c.forget("某個詞", false);
  await c.tidy();
  await c.exportSoul();
  assert.deepStrictEqual(f.calls.map((x) => [x.method, x.url, x.body]), [
    ["GET", "/api/runtime/soul/notes", undefined],
    ["POST", "/api/runtime/soul/proposal", { id: "p-1", action: "replace" }],
    ["POST", "/api/runtime/soul/note", { id: "abc123", action: "retire" }],
    ["POST", "/api/runtime/soul/forget", { text: "某個詞", confirm: false }],
    ["POST", "/api/runtime/soul/tidy", {}],
    ["GET", "/api/runtime/soul/export", undefined]
  ]);
  f.calls.forEach((x) => {
    assert.strictEqual(x.headers["X-SYNOX-CSRF"], x.method === "GET" ? undefined : "tok123");
  });
});

test("normalizeNotes survives missing / broken fields", () => {
  const n = C.normalizeNotes(null);
  assert.deepStrictEqual([n.review, n.notes, n.pending, n.archive], [false, [], [], []]);
  assert.strictEqual(n.budget.notes_max, 0);
  const m = C.normalizeNotes({ notes: [null, { text: "沒有 id" }, { id: 7, text: "- 好" }], pending: "壞的",
                               archive: [{ id: "a-1" }], budget: { chars: "12" } });
  assert.strictEqual(m.notes.length, 1);
  assert.deepStrictEqual(m.notes[0], { id: "7", text: "- 好", by: "owner", tracked: false, added_at: null,
                                       confirmed_at: null, stale: false, grounded: null });
  assert.strictEqual(m.archive[0].text, "");
  assert.strictEqual(m.budget.chars, 12);
});

test("notesModel: proposals say why and offer only the allowed buttons", () => {
  const v = C.notesModel({
    review: false,
    notes: [
      { id: "n1", text: "- 喜歡簡短", by: "mother", tracked: true, added_at: minutes(-2 * 1440),
        confirmed_at: minutes(-60), stale: false, grounded: true },
      { id: "n2", text: "- 很久以前記的", by: "mother", tracked: true, added_at: minutes(-200 * 1440),
        confirmed_at: minutes(-200 * 1440), stale: true, grounded: false },
      { id: "n3", text: "- 我自己加的", by: "owner", tracked: false }
    ],
    pending: [
      { id: "p1", kind: "add", text: "- 新的一條", why: ["有網址或網域", "跟現有的一條很像，可能是更新"],
        related: "- 喜歡簡短", can_replace: true, grounded: false, at: minutes(-5) },
      { id: "p2", kind: "add", text: "- 另一條", why: ["你設定了每一條都先問你"], related: "", can_replace: false },
      { id: "p3", kind: "retire", text: "- 很久以前記的", why: ["90 天沒有再確認過，還對嗎？"] }
    ],
    archive: [{ id: "a1", text: "- 舊的", retired_at: minutes(-30), reason: "被新的一條取代", replaced_by: "- 新的" }],
    budget: { chars: 2600, max_chars: 6000, prompt_chars: 2400, prompt_max: 2000, notes: 3, notes_max: 40 }
  }, NOW);
  assert.strictEqual(v.usage, "soul.md 2600／6000 字・助理筆記 3／40 條");
  assert.ok(v.over && /2000 字/.test(v.overText) && /2400/.test(v.overText));
  assert.strictEqual(v.pendingTitle, "等你確認（3）");
  assert.deepStrictEqual(v.pending[0].actions.map((a) => a[0]), ["approve", "replace", "reject"]);
  assert.deepStrictEqual(v.pending[1].actions.map((a) => a[0]), ["approve", "reject"]);     // 沒有可以取代的就不給那顆
  assert.deepStrictEqual(v.pending[2].actions, [["approve", "收起來"], ["reject", "留著"]]);
  assert.strictEqual(v.pending[0].why, "為什麼先問你：有網址或網域；跟現有的一條很像，可能是更新");
  assert.strictEqual(v.pending[0].related, "很像的現有一條：- 喜歡簡短");
  assert.ok(v.pending[0].warn && !v.pending[1].warn);
  assert.strictEqual(v.notes[0].meta, "常駐助理加的・11/10 14:05（2 天前）・上次確認 1 小時前");
  assert.deepStrictEqual(v.notes[0].badges, []);
  assert.deepStrictEqual(v.notes[1].badges, ["很久沒確認", "看不出是你說的"]);
  assert.strictEqual(v.notes[2].meta, "你寫的或以前就有的");
  assert.strictEqual(v.archiveTitle, "收起來的（1）");
  assert.ok(/被新的一條取代/.test(v.archive[0].meta) && /換成：- 新的/.test(v.archive[0].meta));
  const empty = C.notesModel({ review: true }, NOW);
  assert.strictEqual(empty.empty, "助理還沒有記任何事。");
  assert.ok(/每一條都先問你/.test(empty.mode) && !empty.over && empty.pendingTitle === "");
});

test("forgetSummary: says what goes, and that the owner's own lines stay", () => {
  const s = C.forgetSummary({ notes: 2, pending: 1, archive: 0, audit: 3, patrol: 1, owner_lines: 1 }, "日文");
  assert.ok(s.any && /助理筆記 2 條/.test(s.text) && /等你確認的 1 則/.test(s.text) && /回不來/.test(s.text));
  assert.ok(!/收起來的/.test(s.text) && /不會動/.test(s.text));
  const none = C.forgetSummary({ notes: 0, owner_lines: 2 }, "日文");
  assert.ok(!none.any && /沒有找到/.test(none.text) && /2 行/.test(none.text));
  assert.strictEqual(C.forgetSummary(null, "x").any, false);
});

test("activator card: old backend without it hides the card; broken fields do not break it", () => {
  assert.strictEqual(C.normalizeStatus({}).activator, null);
  assert.strictEqual(C.viewModel({}, NOW).activator, null);
  const a = C.normalizeActivator({ rules: [null, { id: "x" }], pending: "nope", events: [{ fired: [1, "x"] }] });
  assert.strictEqual(a.rules.length, 1);
  assert.deepStrictEqual(a.pending, []);
  assert.deepStrictEqual(a.events[0].fired, ["x"]);
});

test("activator card uses task and rule names, shows tripped reasons and pending in plain words", () => {
  const v = C.viewModel({
    tasks: [{ id: "pack.diary", name: "📔 日記", state: "ok" }],
    activator: {
      enabled: true, paused: null,
      rules: [
        { id: "pack.diary.ask", name: "圖片好了 → 問打卡", owner: "diary", on: "pack.diary", states: ["ok"],
          tag: "diary-image", action: "程式（工具 diary）", timing: "now", status: "active", reason: null,
          last_fired_at: minutes(-3) },
        { id: "loopy", name: "會繞圈的", on: "pack.diary", states: ["failed"], action: "通知你：壞了",
          timing: "heartbeat", status: "tripped", reason: "同一串連動又回到這條規則（循環）", last_fired_at: null }
      ],
      pending: [{ id: "abcd1234", rule: "loopy", task: "pack.diary", state: "failed", at: minutes(-1) }],
      events: [{ task: "pack.diary", state: "ok", tag: "diary-image", at: minutes(-3), fired: ["pack.diary.ask"],
                 skipped: [{ rule: "loopy", reason: "冷卻中" }] }],
      rejected: [{ id: "pack.x.y", reason: "會繞回自己（無限連動）：a → a" }]
    }
  }, NOW).activator;
  assert.strictEqual(v.brief, "2 條規則，1 條暫停了；1 件等心跳處理");
  assert.strictEqual(v.alert, true);
  assert.strictEqual(v.rules[0].line, "當「📔 日記」的「diary-image」變成正常 → 程式（工具 diary）（馬上）");
  assert.strictEqual(v.rules[0].last, "14:02（3 分鐘前）");
  assert.strictEqual(v.rules[1].label, "暫停了");
  assert.strictEqual(v.rules[1].canReset, true);
  assert.ok(v.rules[1].line.endsWith("（等心跳）"));
  assert.strictEqual(v.pending[0].text, "會繞圈的：「📔 日記」變成失敗");
  assert.ok(v.events[0].indexOf("做了：圖片好了 → 問打卡") > 0 && v.events[0].indexOf("略過：會繞圈的（冷卻中）") > 0);
  assert.strictEqual(v.rejected.length, 1);
  const paused = C.viewModel({ activator: { enabled: true, paused: { reason: "10 分鐘內太多" }, rules: [] } }, NOW).activator;
  assert.ok(paused.paused.indexOf("10 分鐘內太多") >= 0 && paused.alert);
  assert.strictEqual(paused.brief, "還沒有連動規則。");
});

test("activator client calls follow the contract (POST + CSRF, ids encoded)", async () => {
  const f = fakeFetch([{ ok: true }, { ok: true }, { ok: true, count: 0 }, { ok: true }]);
  const c = C.makeClient(f, () => "tok");
  await c.resetRule("pack.diary.ask");
  await c.resumeActivator();
  await c.runPending();
  await c.dismissPending("ab/cd");
  assert.deepStrictEqual(f.calls.map((x) => [x.method, x.url, x.body]), [
    ["POST", "/api/runtime/activator/rules/pack.diary.ask/reset", {}],
    ["POST", "/api/runtime/activator/resume", {}],
    ["POST", "/api/runtime/activator/pending/run", {}],
    ["POST", "/api/runtime/activator/pending/ab%2Fcd/dismiss", {}]
  ]);
  f.calls.forEach((x) => assert.strictEqual(x.headers["X-SYNOX-CSRF"], "tok"));
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
