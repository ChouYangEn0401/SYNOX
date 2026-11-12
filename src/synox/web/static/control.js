/* SYNOX 網頁「主控」頁（只有擁有者看得到）。
 *
 * 伺服器把這個檔原地塞進 app.html 裡 INCLUDE:control.js 那一格（server.app_html），送出去仍是一頁、
 * 同一個 CSP nonce。分成檔是為了好維護、好測：上半部是純函式（不碰 DOM，tests/js/test_control.js 用 node 跑），
 * 下半部 mount() 才畫畫面。文字一律 textContent。
 *
 * API（全部擁有者才能叫；非 GET 帶 X-SYNOX-CSRF，跟 app.html 的 api() 一樣）：
 *   GET  /api/runtime/status              {heartbeat, mother, tasks, activator}
 *   POST /api/runtime/heartbeat           {enabled?, interval_min?} → 新的 heartbeat
 *   POST /api/runtime/heartbeat/run-now   → {ok, message}
 *   POST /api/runtime/mother/reset-memory → {ok}
 *   GET  /api/runtime/soul                {text, updated_at}；PUT 同一個網址 {text}
 *   GET  /api/runtime/tasks/<id>/log      {lines: [...]}
 *   POST /api/runtime/activator/rules/<id>/reset      連動規則解除暫停 → {ok, message}
 *   POST /api/runtime/activator/resume                全部連動恢復 → {ok, message}
 *   POST /api/runtime/activator/pending/run           留給心跳的現在處理 → {ok, count, message}
 *   POST /api/runtime/activator/pending/<id>/dismiss  丟掉一件待處理 → {ok}
 *   GET  /api/runtime/soul/notes          助理筆記：{review, notes, pending, archive, budget}（docs/adr/0005）
 *   POST /api/runtime/soul/proposal       {id, action: approve|replace|reject} → 新的 notes 物件
 *   POST /api/runtime/soul/note           {id, action: retire|confirm|restore} → 新的 notes 物件
 *   POST /api/runtime/soul/forget         {text, confirm} → 會動到／動了幾筆
 *   POST /api/runtime/soul/tidy           → {ok, message, notes}
 *   GET  /api/runtime/soul/export         全部倒成一份 JSON
 */
(function (root) {
  "use strict";

  // ── 純函式 ──────────────────────────────────────────────────────────

  var INTERVAL_MIN = 15, INTERVAL_MAX = 1440, INTERVAL_DEFAULT = 45;
  var POLL_MS = 15000;

  // 任務狀態：顏色＋文字＋形狀（圓點／空心圈／方點／短線），不只靠顏色
  var TASK_STATES = {
    ok: { tone: "ok", label: "正常" },
    running: { tone: "run", label: "執行中" },
    failed: { tone: "bad", label: "失敗" },
    idle: { tone: "idle", label: "閒置" }
  };
  var MOTHER_STATES = {
    idle: { tone: "ok", label: "待命中", hint: "開著，沒事的時候在等；heartbeat 到了會起來看一輪。" },
    running: { tone: "run", label: "工作中", hint: "正在跑一輪檢查或任務。" },
    off: { tone: "idle", label: "關著", hint: "常駐助理沒有在跑：heartbeat 和排定的任務不會自己動。" }
  };

  // 連動規則的狀態（docs/adr/0004）
  var RULE_STATUS = {
    active: { tone: "ok", label: "啟用中" },
    tripped: { tone: "bad", label: "暫停了" },
    off: { tone: "idle", label: "關著" }
  };

  function taskState(state) {
    return TASK_STATES[state] || { tone: "idle", label: "不明" };
  }
  function ruleStatus(status) {
    return RULE_STATUS[status] || { tone: "idle", label: "不明" };
  }
  function motherState(state) {
    return MOTHER_STATES[state] || { tone: "idle", label: "不明", hint: "讀不到常駐助理的狀態。" };
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  function parseTime(iso) {
    if (iso === null || iso === undefined || iso === "") { return null; }
    var t = new Date(iso);
    return isNaN(t.getTime()) ? null : t;
  }

  // 「3 分鐘前」「45 分鐘後」「剛剛」
  function relative(iso, now) {
    var t = parseTime(iso);
    if (!t) { return ""; }
    var diff = Math.round((t.getTime() - now.getTime()) / 60000);   // 分鐘，正＝未來
    var abs = Math.abs(diff);
    if (abs < 1) { return "剛剛"; }
    var n, unit;
    if (abs < 60) { n = abs; unit = " 分鐘"; }
    else if (abs < 60 * 24) { n = Math.round(abs / 60); unit = " 小時"; }
    else { n = Math.round(abs / 1440); unit = " 天"; }
    return n + unit + (diff > 0 ? "後" : "前");
  }

  // 「14:05（3 分鐘前）」；不是今天的加日期「11/10 14:05（2 天前）」；沒有時間回 empty
  function when(iso, now, empty) {
    var t = parseTime(iso);
    if (!t) { return empty === undefined ? "還沒有" : empty; }
    var clock = pad2(t.getHours()) + ":" + pad2(t.getMinutes());
    var sameDay = t.getFullYear() === now.getFullYear() && t.getMonth() === now.getMonth() &&
      t.getDate() === now.getDate();
    var text = sameDay ? clock : (t.getMonth() + 1) + "/" + t.getDate() + " " + clock;
    return text + "（" + relative(iso, now) + "）";
  }

  function validateInterval(value) {
    var s = String(value === undefined || value === null ? "" : value).trim();
    if (!/^\d+$/.test(s)) {
      return { ok: false, error: "請填整數分鐘（" + INTERVAL_MIN + "～" + INTERVAL_MAX + "）。" };
    }
    var n = parseInt(s, 10);
    if (n < INTERVAL_MIN || n > INTERVAL_MAX) {
      return { ok: false, error: "間隔要在 " + INTERVAL_MIN + "～" + INTERVAL_MAX + " 分鐘之間（最長一天）。" };
    }
    return { ok: true, value: n };
  }

  // 上次結果可能是一句話，也可能是 {ok, message}
  function resultText(r) {
    if (r === null || r === undefined || r === "") { return "還沒跑過"; }
    if (typeof r === "string") { return r; }
    if (typeof r === "object") {
      var msg = r.message || r.text || "";
      if (r.ok === false) { return "沒有成功" + (msg ? "：" + msg : ""); }
      if (r.ok === true) { return msg || "正常"; }
      return msg || "—";
    }
    return String(r);
  }

  // 伺服器回什麼都不讓畫面壞掉：缺的欄位補預設
  function normalizeStatus(d) {
    d = d && typeof d === "object" ? d : {};
    var hb = d.heartbeat && typeof d.heartbeat === "object" ? d.heartbeat : {};
    var mo = d.mother && typeof d.mother === "object" ? d.mother : {};
    var interval = parseInt(hb.interval_min, 10);
    return {
      heartbeat: {
        enabled: !!hb.enabled,
        interval_min: isNaN(interval) ? INTERVAL_DEFAULT : interval,
        last_run_at: hb.last_run_at || null,
        next_run_at: hb.next_run_at || null,
        last_result: hb.last_result === undefined ? null : hb.last_result
      },
      mother: {
        state: mo.state || "off",
        ai: mo.ai !== false,                     // 沒有這個欄位（舊後端）＝當作有 AI
        last_active_at: mo.last_active_at || null,
        soul_updated_at: mo.soul_updated_at || null
      },
      tasks: (Array.isArray(d.tasks) ? d.tasks : []).filter(function (t) {
        return t && typeof t === "object" && t.id !== undefined && t.id !== null;
      }).map(function (t) {
        return { id: String(t.id), name: t.name || String(t.id), owner: t.owner || "", schedule: t.schedule || "",
                 state: t.state || "idle", last_run_at: t.last_run_at || null, last_message: t.last_message || "" };
      }),
      activator: normalizeActivator(d.activator)
    };
  }

  function objects(x) {
    return Array.isArray(x) ? x.filter(function (i) { return i && typeof i === "object"; }) : [];
  }
  function strings(x) {
    return Array.isArray(x) ? x.filter(function (i) { return typeof i === "string"; }) : [];
  }

  // 連動（舊後端沒有這塊＝null，畫面不顯示那張卡）
  function normalizeActivator(a) {
    if (!a || typeof a !== "object") { return null; }
    return {
      enabled: a.enabled !== false,
      paused: a.paused && typeof a.paused === "object" ? { reason: String(a.paused.reason || ""), at: a.paused.at || null } : null,
      rules: objects(a.rules).map(function (r) {
        return { id: String(r.id || ""), name: r.name || String(r.id || ""), owner: r.owner || "", on: r.on || "",
                 states: strings(r.states), tag: r.tag || "", action: r.action || "",
                 timing: r.timing === "heartbeat" ? "heartbeat" : "now", status: r.status || "active",
                 reason: r.reason || "", last_fired_at: r.last_fired_at || null, last_note: r.last_note || "" };
      }),
      pending: objects(a.pending).map(function (p) {
        return { id: String(p.id || ""), rule: String(p.rule || ""), task: String(p.task || ""), state: p.state || "",
                 at: p.at || null };
      }),
      events: objects(a.events).map(function (e) {
        return { task: String(e.task || ""), state: e.state || "", tag: e.tag || "", at: e.at || null,
                 fired: strings(e.fired), skipped: objects(e.skipped) };
      }),
      rejected: objects(a.rejected).map(function (r) { return { id: String(r.id || ""), reason: String(r.reason || "") }; })
    };
  }

  // 連動那張卡要顯示的字：任務、規則都用名字（不貼 id 與內部詞）
  function activatorView(a, tasks, now) {
    if (!a) { return null; }
    var taskNames = {}, ruleNames = {};
    (tasks || []).forEach(function (t) { taskNames[t.id] = t.name; });
    a.rules.forEach(function (r) { ruleNames[r.id] = r.name; });
    function tname(id) { return taskNames[id] || id; }
    function rname(id) { return ruleNames[id] || id; }
    function sw(s) { return taskState(s).label; }
    var tripped = a.rules.filter(function (r) { return r.status === "tripped"; }).length;
    return {
      paused: a.paused ? "全部連動暫停了：" + a.paused.reason + "。處理好之後按「恢復」。" : "",
      brief: !a.enabled ? "連動整個關著（在設定檔裡關掉的）。"
        : !a.rules.length ? "還沒有連動規則。"
        : a.rules.length + " 條規則" + (tripped ? "，" + tripped + " 條暫停了" : "，都正常") +
          (a.pending.length ? "；" + a.pending.length + " 件等心跳處理" : ""),
      alert: tripped > 0 || !!a.paused,
      rules: a.rules.map(function (r) {
        var st = ruleStatus(r.status);
        return { id: r.id, name: r.name, tone: st.tone, label: st.label, canReset: r.status === "tripped",
                 line: "當「" + tname(r.on) + "」" + (r.tag ? "的「" + r.tag + "」" : "") + "變成" +
                   (r.states.map(sw).join("或") || "—") + " → " + r.action + (r.timing === "heartbeat" ? "（等心跳）" : "（馬上）"),
                 reason: r.reason, last: when(r.last_fired_at, now, "還沒動過"), note: r.last_note };
      }),
      pending: a.pending.map(function (p) {
        return { id: p.id, text: rname(p.rule) + "：「" + tname(p.task) + "」變成" + sw(p.state), when: when(p.at, now, "") };
      }),
      events: a.events.slice(0, 10).map(function (e) {
        return when(e.at, now, "") + "　「" + tname(e.task) + "」" + (e.tag ? "（" + e.tag + "）" : "") + "→ " + sw(e.state) +
          (e.fired.length ? "；做了：" + e.fired.map(rname).join("、") : "") +
          (e.skipped.length ? "；略過：" + e.skipped.map(function (s) { return rname(String(s.rule || "")) + "（" + (s.reason || "") + "）"; }).join("、") : "");
      }),
      rejected: a.rejected.map(function (r) { return rname(r.id) + "：" + r.reason; })
    };
  }

  // 畫面要顯示的字（純資料，好測）
  function viewModel(status, now) {
    var s = normalizeStatus(status);
    var hb = s.heartbeat, mo = s.mother;
    var ms = motherState(mo.state);
    var counts = { ok: 0, running: 0, failed: 0, idle: 0 };
    s.tasks.forEach(function (t) { if (counts.hasOwnProperty(t.state)) { counts[t.state] += 1; } });
    return {
      mother: { tone: ms.tone, label: ms.label,
                hint: (mo.state === "off" && !mo.ai) ?
                  "還沒設定 AI 來源：到〔設定〕選好並存起來，這裡馬上就會開始跑（不用重開）。" : ms.hint,
                lastActive: when(mo.last_active_at, now, "還沒有活動"),
                soulUpdated: when(mo.soul_updated_at, now, "還沒寫過") },
      heartbeat: {
        enabled: hb.enabled,
        interval: hb.interval_min,
        stateLabel: hb.enabled ? "開著" : "關著",
        every: "每 " + hb.interval_min + " 分鐘",
        next: hb.enabled ? when(hb.next_run_at, now, "等常駐助理排上") : "關著，不會自己跑",
        last: when(hb.last_run_at, now, "還沒跑過"),
        lastResult: resultText(hb.last_result),
        lastFailed: !!(hb.last_result && typeof hb.last_result === "object" && hb.last_result.ok === false)
      },
      taskBrief: !s.tasks.length ? "沒有" : (counts.failed ? counts.failed + " 個失敗，共 " + s.tasks.length + " 個"
        : "共 " + s.tasks.length + " 個，沒有失敗的"),
      anyFailed: counts.failed > 0,
      summary: s.tasks.length ? (s.tasks.length + " 個任務：" + [
        counts.failed ? counts.failed + " 個失敗" : "",
        counts.running ? counts.running + " 個執行中" : "",
        counts.ok ? counts.ok + " 個正常" : "",
        counts.idle ? counts.idle + " 個閒置" : ""
      ].filter(Boolean).join("、")) : "還沒有排定的任務。",
      tasks: s.tasks.map(function (t) {
        var st = taskState(t.state);
        return { id: t.id, name: t.name, owner: t.owner || "SYNOX", schedule: t.schedule || "—",
                 tone: st.tone, label: st.label, last: when(t.last_run_at, now, "還沒跑過"),
                 message: t.last_message || "" };
      }),
      activator: activatorView(s.activator, s.tasks, now)
    };
  }

  // ── 助理筆記（soul 帳本，GET /api/runtime/soul/notes）─────────────────

  var NOTE_BY = { mother: "常駐助理加的", owner: "你寫的", tidy: "整理時提的" };

  // 伺服器回什麼都不讓畫面壞掉：缺的欄位補預設、不是物件的丟掉
  function normalizeNotes(d) {
    d = d && typeof d === "object" ? d : {};
    function list(v) { return (Array.isArray(v) ? v : []).filter(function (x) { return x && typeof x === "object" && x.id; }); }
    var b = d.budget && typeof d.budget === "object" ? d.budget : {};
    function num(v) { var n = parseInt(v, 10); return isNaN(n) ? 0 : n; }
    return {
      review: !!d.review,
      notes: list(d.notes).map(function (n) {
        return { id: String(n.id), text: String(n.text || ""), by: String(n.by || "owner"), tracked: !!n.tracked,
                 added_at: n.added_at || null, confirmed_at: n.confirmed_at || null, stale: !!n.stale,
                 grounded: n.grounded === false ? false : (n.grounded === true ? true : null) };
      }),
      pending: list(d.pending).map(function (p) {
        return { id: String(p.id), kind: p.kind === "retire" ? "retire" : "add", text: String(p.text || ""),
                 at: p.at || null, why: (Array.isArray(p.why) ? p.why : []).map(String),
                 related: String(p.related || ""), can_replace: !!p.can_replace,
                 grounded: p.grounded === false ? false : (p.grounded === true ? true : null) };
      }),
      archive: list(d.archive).map(function (a) {
        return { id: String(a.id), text: String(a.text || ""), retired_at: a.retired_at || null,
                 reason: String(a.reason || ""), replaced_by: String(a.replaced_by || "") };
      }),
      budget: { chars: num(b.chars), max_chars: num(b.max_chars), prompt_chars: num(b.prompt_chars),
                prompt_max: num(b.prompt_max), notes: num(b.notes), notes_max: num(b.notes_max),
                stale_days: num(b.stale_days) }
    };
  }

  // 畫面要顯示的字（純資料，好測）
  function notesModel(data, now) {
    var d = normalizeNotes(data), b = d.budget;
    var over = b.prompt_max > 0 && b.prompt_chars > b.prompt_max;
    return {
      usage: "soul.md " + b.chars + "／" + b.max_chars + " 字・助理筆記 " + b.notes + "／" + b.notes_max + " 條",
      over: over,
      overText: over ? "對話助理每一輪最多讀 " + b.prompt_max + " 字，現在有 " + b.prompt_chars +
        " 字：你寫的段落都會放，助理筆記只挑跟那句話相關、比較新的。想讓它每次都讀到，就收起幾條。" : "",
      mode: d.review ? "現在的設定：助理想記的每一條都先問你。" : "現在的設定：沒有疑慮的助理會直接記；有疑慮的先問你。",
      pendingTitle: d.pending.length ? "等你確認（" + d.pending.length + "）" : "",
      pending: d.pending.map(function (p) {
        var retire = p.kind === "retire";
        return { id: p.id, text: p.text, retire: retire,
                 head: retire ? "要不要收起這一條？" : "助理想記這一條",
                 why: p.why.length ? "為什麼先問你：" + p.why.join("；") : "",
                 related: p.related ? (retire ? "比較新的那一條：" : "很像的現有一條：") + p.related : "",
                 warn: p.grounded === false ? "看不出是從你自己說的話來的" : "",
                 when: when(p.at, now, ""),
                 actions: retire ? [["approve", "收起來"], ["reject", "留著"]]
                   : [["approve", "加進去"]].concat(p.can_replace ? [["replace", "取代舊的那條"]] : [], [["reject", "不要"]]) };
      }),
      notesTitle: "助理筆記（" + d.notes.length + "）",
      notes: d.notes.map(function (n) {
        var who = n.tracked ? (NOTE_BY[n.by] || n.by) : "你寫的或以前就有的";
        var bits = [who];
        if (n.added_at) { bits.push(when(n.added_at, now, "")); }
        if (n.tracked && n.confirmed_at && n.confirmed_at !== n.added_at) { bits.push("上次確認 " + relative(n.confirmed_at, now)); }
        return { id: n.id, text: n.text, meta: bits.join("・"),
                 badges: [n.stale ? "很久沒確認" : "", n.grounded === false ? "看不出是你說的" : ""].filter(Boolean),
                 stale: n.stale };
      }),
      empty: !d.notes.length && !d.pending.length ? "助理還沒有記任何事。" : "",
      archiveTitle: d.archive.length ? "收起來的（" + d.archive.length + "）" : "",
      archive: d.archive.map(function (a) {
        return { id: a.id, text: a.text,
                 meta: [when(a.retired_at, now, ""), a.reason, a.replaced_by ? "換成：" + a.replaced_by : ""]
                   .filter(Boolean).join("・") };
      })
    };
  }

  // 「忘掉」先看會動到什麼：給確認框的一句話
  function forgetSummary(r, word) {
    r = r && typeof r === "object" ? r : {};
    function n(k) { var v = parseInt(r[k], 10); return isNaN(v) ? 0 : v; }
    var parts = [];
    if (n("notes")) { parts.push("助理筆記 " + n("notes") + " 條"); }
    if (n("pending")) { parts.push("等你確認的 " + n("pending") + " 則"); }
    if (n("archive")) { parts.push("收起來的 " + n("archive") + " 條"); }
    if (n("audit")) { parts.push("修改紀錄 " + n("audit") + " 筆"); }
    if (n("patrol")) { parts.push("常駐助理的記憶 " + n("patrol") + " 筆"); }
    var mine = n("owner_lines") ? "你自己寫的段落裡有 " + n("owner_lines") + " 行提到，那是你寫的，不會動（要改請直接改上面的內容）。" : "";
    if (!parts.length) { return { any: false, text: "沒有找到提到「" + word + "」的東西。" + mine }; }
    return { any: true, text: "會拿掉提到「" + word + "」的：" + parts.join("、") + "。拿掉就回不來。" + mine };
  }

  // 錯誤 → 人話（不貼 HTTP 碼、例外名、CSRF 這類內部詞）
  function humanError(err) {
    var status = err && err.status;
    var msg = (err && err.serverMessage) || "";
    if (!status) { return "連不到 SYNOX：它可能沒在跑，或這台電腦剛剛斷線了。等一下會自動再試。"; }
    if (status === 401) { return "登入過期了，請重新登入。"; }
    if (status === 403) {
      if (/CSRF|Origin|來源/.test(msg)) { return "這一頁開太久了，重新整理一次再試。"; }
      return "只有擁有者能用主控。";
    }
    if (status === 404 || status === 405) { return "這個版本的 SYNOX 還沒有主控功能（要更新 SYNOX）。"; }
    if (status >= 500) { return "SYNOX 那邊出了問題，等一下再試；一直這樣的話，看一下 SYNOX 視窗裡的訊息。"; }
    if (msg && !/[A-Za-z]{2,}Error|Traceback|HTTP \d/.test(msg)) { return msg; }   // 400、409 這類是伺服器寫好的人話
    return "沒有成功，請再試一次。";
  }

  // fetch 的小包裝：回 JSON；失敗丟 {status, serverMessage}
  function makeClient(fetchImpl, getCsrf) {
    function call(method, path, body) {
      var opts = { method: method, credentials: "same-origin", headers: {} };
      if (method !== "GET") {
        opts.headers["X-SYNOX-CSRF"] = (getCsrf && getCsrf()) || "";
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body || {});
      }
      var network = function () { var e = new Error("network"); e.status = 0; e.serverMessage = ""; throw e; };
      var p;
      try { p = fetchImpl(path, opts); } catch (x) { return Promise.reject({ status: 0, serverMessage: "" }); }
      return Promise.resolve(p).then(function (r) {
        var type = (r.headers && r.headers.get && r.headers.get("Content-Type")) || "";
        var parse = type.indexOf("application/json") === 0 ? r.json().catch(function () { return {}; })
          : Promise.resolve({});
        return parse.then(function (d) {
          if (!r.ok) { throw { status: r.status || 500, serverMessage: (d && d.error) || "" }; }
          return d;
        });
      }, network);
    }
    return {
      status: function () { return call("GET", "/api/runtime/status"); },
      setHeartbeat: function (change) {
        var body = {};
        if (change && change.enabled !== undefined) { body.enabled = !!change.enabled; }
        if (change && change.interval_min !== undefined) { body.interval_min = change.interval_min; }
        return call("POST", "/api/runtime/heartbeat", body);
      },
      runNow: function () { return call("POST", "/api/runtime/heartbeat/run-now", {}); },
      resetMemory: function () { return call("POST", "/api/runtime/mother/reset-memory", {}); },
      soul: function () { return call("GET", "/api/runtime/soul"); },
      saveSoul: function (text) { return call("PUT", "/api/runtime/soul", { text: String(text) }); },
      taskLog: function (id) { return call("GET", "/api/runtime/tasks/" + encodeURIComponent(id) + "/log"); },
      resetRule: function (id) {
        return call("POST", "/api/runtime/activator/rules/" + encodeURIComponent(id) + "/reset", {});
      },
      resumeActivator: function () { return call("POST", "/api/runtime/activator/resume", {}); },
      runPending: function () { return call("POST", "/api/runtime/activator/pending/run", {}); },
      dismissPending: function (id) {
        return call("POST", "/api/runtime/activator/pending/" + encodeURIComponent(id) + "/dismiss", {});
      },
      notes: function () { return call("GET", "/api/runtime/soul/notes"); },
      proposal: function (id, action) { return call("POST", "/api/runtime/soul/proposal", { id: String(id), action: action }); },
      note: function (id, action) { return call("POST", "/api/runtime/soul/note", { id: String(id), action: action }); },
      forget: function (text, confirm) { return call("POST", "/api/runtime/soul/forget", { text: String(text), confirm: !!confirm }); },
      tidy: function () { return call("POST", "/api/runtime/soul/tidy", {}); },
      exportSoul: function () { return call("GET", "/api/runtime/soul/export"); }
    };
  }

  function canSee(me) { return !!(me && me.owner); }

  // ── 畫面 ────────────────────────────────────────────────────────────

  var RESET_CLEARS = ["常駐助理記得的對話與工作脈絡（清完它會像剛開機一樣，從頭開始）"];
  var RESET_KEEPS = ["soul.md（你的偏好，就是下面那一格）", "「對話」頁的對話紀錄，和對話助理的記憶",
    "筆記、記帳、提醒這些工具裡的資料", "設定、heartbeat 和排定的任務"];

  var ui = null;        // mount() 之後的畫面與狀態

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
  function card(icon, title, sub) {
    var c = el("div", "card");
    var head = el("div", "card-head");
    var tile = el("span", "tile", icon); tile.setAttribute("aria-hidden", "true");
    var txt = el("div", "txt");
    txt.appendChild(el("h2", "", title));
    if (sub) { txt.appendChild(el("p", "sub", sub)); }
    head.appendChild(tile); head.appendChild(txt);
    c.appendChild(head);
    return c;
  }
  function stat(label) {
    var row = el("div", "ctl-stat");
    row.appendChild(el("span", "k", label));
    var v = el("span", "v");
    row.appendChild(v);
    return { row: row, value: v };
  }
  function badge(tone, label) { return el("span", "badge ctl-" + tone, label); }

  function build(container) {
    clear(container);
    var page = el("div", "page wide ctl");
    var head = el("header", "page-head");
    head.appendChild(el("h1", "", "主控"));
    head.appendChild(el("p", "sub", "常駐助理一直開著，在背景顧著 SYNOX：定時看一輪（heartbeat）、跑排定的任務、記得你的偏好。" +
      "要聊天、交代事情，請到「對話」頁。"));
    page.appendChild(head);

    var roles = el("div", "ctl-roles");
    [["💬", "對話助理", "你平常聊天、交代事情的對象。在「對話」頁。"],
     ["🛰️", "常駐助理", "一直開著、在背景監督和回報，不用你跟它聊。在這一頁管。"]].forEach(function (r) {
      var b = el("div", "ctl-role");
      var t = el("span", "tile", r[0]); t.setAttribute("aria-hidden", "true");
      var tx = el("div", "txt");
      tx.appendChild(el("b", "", r[1]));
      tx.appendChild(el("span", "sub", r[2]));
      b.appendChild(t); b.appendChild(tx);
      roles.appendChild(b);
    });
    page.appendChild(roles);

    var banner = el("div", "ctl-banner hidden");
    banner.setAttribute("role", "alert");
    var bannerText = el("span", "", "");
    var retry = el("button", "sm", "再試一次"); retry.type = "button";
    banner.appendChild(bannerText); banner.appendChild(retry);
    page.appendChild(banner);

    var loading = el("p", "ctl-loading", "讀取中…");
    page.appendChild(loading);

    var body = el("div", "ctl-body hidden");
    page.appendChild(body);

    // 總覽：常駐助理＋heartbeat
    var grid = el("div", "ctl-grid");
    var mother = card("🛰️", "常駐助理", "");
    var mLine = el("div", "ctl-state");
    var mHint = el("p", "sub");
    var mActive = stat("上次活動");
    var mSoul = stat("偏好（soul.md）更新");
    var mTasks = stat("任務");
    var mChat = el("a", "ctl-chat", "💬 跟它聊天（對話頁最上面的「常駐助理」）");
    mChat.href = "#chat:mother";
    mother.appendChild(mLine); mother.appendChild(mHint); mother.appendChild(mChat);
    var mStats = el("div", "ctl-stats");
    mStats.appendChild(mActive.row); mStats.appendChild(mSoul.row); mStats.appendChild(mTasks.row);
    mother.appendChild(mStats);

    var hb = card("💓", "Heartbeat", "常駐助理每隔一段時間醒來看一輪：任務有沒有卡住、有沒有該提醒你的事。");
    var sw = el("label", "ctl-switch");
    var swInput = el("input"); swInput.type = "checkbox"; swInput.setAttribute("role", "switch");
    var swText = el("span", "", "");
    sw.appendChild(swInput); sw.appendChild(el("span", "track")); sw.appendChild(swText);
    hb.appendChild(sw);
    var lab = el("label", "f", "間隔（分鐘）");
    lab.setAttribute("for", "ctl-interval");
    hb.appendChild(lab);
    var row = el("div", "field-row ctl-interval-row");
    var interval = el("input"); interval.id = "ctl-interval"; interval.type = "number";
    interval.min = String(INTERVAL_MIN); interval.max = String(INTERVAL_MAX); interval.step = "1";
    interval.setAttribute("inputmode", "numeric");
    var saveInterval = el("button", "", "存起來"); saveInterval.type = "button";
    row.appendChild(interval); row.appendChild(saveInterval);
    hb.appendChild(row);
    var hbNext = stat("下一次"), hbLast = stat("上次"), hbResult = stat("上次結果");
    var hbStats = el("div", "ctl-stats");
    hbStats.appendChild(hbNext.row); hbStats.appendChild(hbLast.row); hbStats.appendChild(hbResult.row);
    hb.appendChild(hbStats);
    var hbActions = el("div", "row ctl-actions");
    var runNow = el("button", "primary", "現在執行一次"); runNow.type = "button";
    hbActions.appendChild(runNow);
    hb.appendChild(hbActions);
    var hbMsg = el("p", "msgline"); hbMsg.setAttribute("aria-live", "polite");
    hb.appendChild(hbMsg);

    grid.appendChild(mother); grid.appendChild(hb);
    body.appendChild(grid);

    // 任務
    var tasks = card("🗂️", "任務", "排定時間自動跑的工作（誰的、多久一次、上次怎麼樣）。點一列看日誌。");
    var tSummary = el("p", "ctl-summary");
    var tList = el("ul", "ctl-tasks");
    tasks.appendChild(tSummary); tasks.appendChild(tList);
    body.appendChild(tasks);

    // 連動（docs/adr/0004）：後端沒有這塊就整張藏起來
    var act = card("🔗", "連動", "一件事做完就馬上接著做下一件（例如：日記圖片做好了 → 問你要不要打卡）。" +
      "會繞回自己、太頻繁、一直失敗的規則會自己暫停，在這裡看原因、按「重設」。");
    act.classList.add("hidden");
    var aSummary = el("p", "ctl-summary");
    var aPaused = el("div", "row ctl-actions hidden");
    var aPausedText = el("p", "alert", "");
    var aResume = el("button", "primary sm", "恢復"); aResume.type = "button";
    aPaused.appendChild(aPausedText); aPaused.appendChild(aResume);
    var aRules = el("ul", "ctl-tasks");
    var aPendHead = el("p", "ctl-summary hidden", "");
    var aPending = el("ul", "ctl-tasks");
    var aPendRow = el("div", "row ctl-actions hidden");
    var aRunPending = el("button", "sm", "現在處理"); aRunPending.type = "button";
    aPendRow.appendChild(aRunPending);
    var aRejected = el("p", "alert hidden", "");
    var aEventsBox = el("details", "");
    aEventsBox.appendChild(el("summary", "", "最近的連動紀錄"));
    var aEvents = el("pre", "ctl-pre", "");
    aEventsBox.appendChild(aEvents);
    var aMsg = el("p", "msgline"); aMsg.setAttribute("aria-live", "polite");
    [aSummary, aPaused, aRules, aPendHead, aPending, aPendRow, aRejected, aEventsBox, aMsg].forEach(function (n) {
      act.appendChild(n);
    });
    body.appendChild(act);

    // 偏好（soul.md）
    var soul = card("📜", "你的偏好（soul.md）",
      "常駐助理記你的喜好、習慣、要它注意的事的地方，它每次醒來都會先讀。這個檔只存在這台電腦，不會上傳。");
    var soulLab = el("label", "f", "內容（純文字，可以用 Markdown）");
    soulLab.setAttribute("for", "ctl-soul");
    var soulText = el("textarea", "ctl-soul"); soulText.id = "ctl-soul"; soulText.rows = 10;
    soulText.setAttribute("spellcheck", "false");
    soulText.placeholder = "例如：\n- 叫我小明\n- 早上 9 點前不要傳訊息\n- 記帳超過預算八成要提醒我";
    var soulMeta = el("div", "ctl-soul-meta");
    var soulWhen = el("span", "muted", "");
    var soulDirty = el("span", "badge warn hidden", "還沒儲存");
    soulMeta.appendChild(soulWhen); soulMeta.appendChild(soulDirty);
    var soulRow = el("div", "row ctl-actions");
    var soulSave = el("button", "primary", "儲存"); soulSave.type = "button"; soulSave.disabled = true;
    var soulUndo = el("button", "ghost", "還原"); soulUndo.type = "button"; soulUndo.disabled = true;
    soulRow.appendChild(soulSave); soulRow.appendChild(soulUndo);
    var soulMsg = el("p", "msgline"); soulMsg.setAttribute("aria-live", "polite");
    soul.appendChild(soulLab); soul.appendChild(soulText); soul.appendChild(soulMeta);
    soul.appendChild(soulRow); soul.appendChild(soulMsg);
    body.appendChild(soul);

    // 助理筆記（soul 帳本）
    var notes = card("🗒️", "助理記下來的事",
      "常駐助理自己加進 soul.md「助理筆記」那一段的每一條：誰加的、什麼時候、還對不對。" +
      "看起來像在下指令、有網址、或跟現有的很像的，它不會自己寫進去，會先在這裡等你按。");
    var nUsage = el("p", "ctl-summary");
    var nOver = el("p", "ctl-note-over hidden");
    var nMode = el("p", "muted");
    var nPendingTitle = el("h3", "ctl-note-h hidden");
    var nPending = el("ul", "ctl-notes");
    var nTitle = el("h3", "ctl-note-h");
    var nList = el("ul", "ctl-notes");
    var nEmpty = el("p", "muted hidden");
    var nArchive = el("details", "ctl-note-archive hidden");
    var nArchiveTitle = el("summary", "");
    var nArchiveList = el("ul", "ctl-notes");
    nArchive.appendChild(nArchiveTitle); nArchive.appendChild(nArchiveList);
    var nRow = el("div", "row ctl-actions");
    var nTidy = el("button", "", "整理一次"); nTidy.type = "button";
    var nExport = el("button", "ghost", "匯出（下載）"); nExport.type = "button";
    nRow.appendChild(nTidy); nRow.appendChild(nExport);
    var fLab = el("label", "f", "要它忘掉的事（打一個詞，例如人名或主題）");
    fLab.setAttribute("for", "ctl-forget");
    var fRow = el("div", "row");
    var fText = el("input"); fText.id = "ctl-forget"; fText.type = "text"; fText.maxLength = 80;
    fText.setAttribute("autocomplete", "off");
    var fAsk = el("button", "danger", "忘掉…"); fAsk.type = "button";
    fRow.appendChild(fText); fRow.appendChild(fAsk);
    var fBox = el("div", "ctl-confirm hidden");
    fBox.setAttribute("role", "group");
    fBox.setAttribute("aria-label", "確認忘掉");
    var fQ = el("p", "ctl-confirm-q", "");
    var fPreview = el("ul", "ctl-forget-preview");
    var fBtns = el("div", "row");
    var fGo = el("button", "danger ctl-solid", "確定忘掉"); fGo.type = "button";
    var fNo = el("button", "", "取消"); fNo.type = "button";
    fBtns.appendChild(fGo); fBtns.appendChild(fNo);
    fBox.appendChild(fQ); fBox.appendChild(fPreview); fBox.appendChild(fBtns);
    var nMsg = el("p", "msgline"); nMsg.setAttribute("aria-live", "polite");
    [nUsage, nOver, nMode, nPendingTitle, nPending, nTitle, nList, nEmpty, nArchive, nRow, fLab, fRow, fBox, nMsg]
      .forEach(function (x) { notes.appendChild(x); });
    body.appendChild(notes);

    // 清空記憶
    var reset = card("🧹", "清空常駐助理的記憶",
      "它記得的東西太亂、或想讓它從頭開始時用。按了會先再問你一次。");
    var resetOpen = el("button", "danger", "清空記憶…"); resetOpen.type = "button";
    var confirmBox = el("div", "ctl-confirm hidden");
    confirmBox.setAttribute("role", "group");
    confirmBox.setAttribute("aria-label", "確認清空記憶");
    confirmBox.appendChild(el("p", "ctl-confirm-q", "確定要清空常駐助理的記憶嗎？清了就回不來。"));
    var lists = el("div", "ctl-confirm-lists");
    [["會清掉", RESET_CLEARS, "bad"], ["不會動", RESET_KEEPS, "ok"]].forEach(function (g) {
      var col = el("div", "ctl-confirm-col " + g[2]);
      col.appendChild(el("b", "", g[0]));
      var ul = el("ul");
      g[1].forEach(function (t) { ul.appendChild(el("li", "", t)); });
      col.appendChild(ul);
      lists.appendChild(col);
    });
    confirmBox.appendChild(lists);
    var cRow = el("div", "row");
    var resetGo = el("button", "danger ctl-solid", "確定清空"); resetGo.type = "button";
    var resetNo = el("button", "", "取消"); resetNo.type = "button";
    cRow.appendChild(resetGo); cRow.appendChild(resetNo);
    confirmBox.appendChild(cRow);
    var resetMsg = el("p", "msgline"); resetMsg.setAttribute("aria-live", "polite");
    reset.appendChild(resetOpen); reset.appendChild(confirmBox); reset.appendChild(resetMsg);
    body.appendChild(reset);

    container.appendChild(page);
    return {
      banner: banner, bannerText: bannerText, retry: retry, loading: loading, body: body,
      mLine: mLine, mHint: mHint, mActive: mActive.value, mSoul: mSoul.value, mTasks: mTasks.value,
      swInput: swInput, swText: swText, interval: interval, saveInterval: saveInterval,
      hbNext: hbNext.value, hbLast: hbLast.value, hbResult: hbResult.value, runNow: runNow, hbMsg: hbMsg,
      tSummary: tSummary, tList: tList,
      act: act, aSummary: aSummary, aPaused: aPaused, aPausedText: aPausedText, aResume: aResume, aRules: aRules,
      aPendHead: aPendHead, aPending: aPending, aPendRow: aPendRow, aRunPending: aRunPending, aRejected: aRejected,
      aEventsBox: aEventsBox, aEvents: aEvents, aMsg: aMsg,
      soulText: soulText, soulWhen: soulWhen, soulDirty: soulDirty, soulSave: soulSave, soulUndo: soulUndo,
      soulMsg: soulMsg,
      nUsage: nUsage, nOver: nOver, nMode: nMode, nPendingTitle: nPendingTitle, nPending: nPending, nTitle: nTitle,
      nList: nList, nEmpty: nEmpty, nArchive: nArchive, nArchiveTitle: nArchiveTitle, nArchiveList: nArchiveList,
      nTidy: nTidy, nExport: nExport, fText: fText, fAsk: fAsk, fBox: fBox, fQ: fQ, fPreview: fPreview,
      fGo: fGo, fNo: fNo, nMsg: nMsg,
      resetOpen: resetOpen, confirmBox: confirmBox, resetGo: resetGo, resetNo: resetNo, resetMsg: resetMsg
    };
  }

  function renderStatus(status) {
    var v = viewModel(status, new Date());
    var d = ui.dom;
    clear(d.mLine);
    d.mLine.appendChild(badge(v.mother.tone, v.mother.label));
    d.mHint.textContent = v.mother.hint;
    d.mActive.textContent = v.mother.lastActive;
    d.mSoul.textContent = v.mother.soulUpdated;
    d.mTasks.textContent = v.taskBrief;
    d.mTasks.classList.toggle("alert", v.anyFailed);

    d.swInput.checked = v.heartbeat.enabled;
    d.swInput.setAttribute("aria-checked", v.heartbeat.enabled ? "true" : "false");
    d.swText.textContent = v.heartbeat.enabled ? "開著（" + v.heartbeat.every + "）" : "關著";
    if (!ui.intervalDirty && document.activeElement !== d.interval) { d.interval.value = String(v.heartbeat.interval); }
    d.hbNext.textContent = v.heartbeat.next;
    d.hbLast.textContent = v.heartbeat.last;
    d.hbResult.textContent = v.heartbeat.lastResult;
    d.hbResult.classList.toggle("alert", v.heartbeat.lastFailed);

    d.tSummary.textContent = v.summary;
    clear(d.tList);
    v.tasks.forEach(function (t) { d.tList.appendChild(taskRow(t)); });
    renderActivator(v.activator);
  }

  function renderActivator(a) {
    var d = ui.dom;
    d.act.classList.toggle("hidden", !a);
    if (!a) { return; }
    d.aSummary.textContent = a.brief;
    d.aSummary.classList.toggle("alert", a.alert);
    d.aPaused.classList.toggle("hidden", !a.paused);
    d.aPausedText.textContent = a.paused;
    clear(d.aRules);
    a.rules.forEach(function (r) { d.aRules.appendChild(ruleRow(r)); });
    d.aPendHead.classList.toggle("hidden", !a.pending.length);
    d.aPendHead.textContent = a.pending.length ? "等心跳處理的（" + a.pending.length + " 件）：" : "";
    clear(d.aPending);
    a.pending.forEach(function (p) { d.aPending.appendChild(pendingRow(p)); });
    d.aPendRow.classList.toggle("hidden", !a.pending.length);
    d.aRejected.classList.toggle("hidden", !a.rejected.length);
    d.aRejected.textContent = a.rejected.length ? "沒有收的規則（會繞回自己）：" + a.rejected.join("；") : "";
    d.aEventsBox.classList.toggle("hidden", !a.events.length);
    d.aEvents.textContent = a.events.join("\n");
  }

  function ruleRow(r) {
    var li = el("li", "ctl-task");
    var head = el("div", "ctl-task-head");
    head.appendChild(badge(r.tone, r.label));
    var main = el("span", "ctl-task-main");
    main.appendChild(el("span", "ctl-task-name", r.name));
    main.appendChild(el("span", "ctl-task-meta", r.line + "・上次 " + r.last));
    if (r.reason) { main.appendChild(el("span", "ctl-task-msg alert", "暫停的原因：" + r.reason)); }
    else if (r.note) { main.appendChild(el("span", "ctl-task-msg", r.note)); }
    head.appendChild(main);
    if (r.canReset) {
      var btn = el("button", "sm", "重設"); btn.type = "button";
      btn.addEventListener("click", function () {
        btn.disabled = true;
        ui.client.resetRule(r.id).then(function (res) {
          ui.dom.aMsg.textContent = (res && res.message) || "重設了。";
          refresh();
        }, function (e) {
          ui.dom.aMsg.textContent = "沒有重設成：" + humanError(e);
          btn.disabled = false;
        });
      });
      head.appendChild(btn);
    }
    li.appendChild(head);
    return li;
  }

  function pendingRow(p) {
    var li = el("li", "ctl-task");
    var head = el("div", "ctl-task-head");
    var main = el("span", "ctl-task-main");
    main.appendChild(el("span", "ctl-task-name", p.text));
    if (p.when) { main.appendChild(el("span", "ctl-task-meta", p.when)); }
    head.appendChild(main);
    var btn = el("button", "ghost sm", "不用做了"); btn.type = "button";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      ui.client.dismissPending(p.id).then(function () { refresh(); }, function (e) {
        ui.dom.aMsg.textContent = "沒有丟掉：" + humanError(e);
        btn.disabled = false;
      });
    });
    head.appendChild(btn);
    li.appendChild(head);
    return li;
  }

  function taskRow(t) {
    var li = el("li", "ctl-task");
    var btn = el("button", "ctl-task-head"); btn.type = "button";
    var open = !!ui.openLogs[t.id];
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.appendChild(badge(t.tone, t.label));
    var main = el("span", "ctl-task-main");
    main.appendChild(el("span", "ctl-task-name", t.name));
    main.appendChild(el("span", "ctl-task-meta", t.owner + "・" + t.schedule + "・上次 " + t.last));
    if (t.message) { main.appendChild(el("span", "ctl-task-msg", t.message)); }
    btn.appendChild(main);
    btn.appendChild(el("span", "ctl-chev", open ? "收起" : "日誌"));
    li.appendChild(btn);
    var log = el("div", "ctl-log" + (open ? "" : " hidden"));
    li.appendChild(log);
    if (open) { fillLog(log, t.id); }
    btn.addEventListener("click", function () {
      ui.openLogs[t.id] = !ui.openLogs[t.id];
      var now = ui.openLogs[t.id];
      btn.setAttribute("aria-expanded", now ? "true" : "false");
      btn.querySelector(".ctl-chev").textContent = now ? "收起" : "日誌";
      log.classList.toggle("hidden", !now);
      if (now) { ui.logs[t.id] = null; fillLog(log, t.id); }
    });
    return li;
  }

  function fillLog(box, id) {
    clear(box);
    var cached = ui.logs[id];
    if (cached) { showLog(box, id, cached); return; }
    box.appendChild(el("p", "muted", "讀取日誌中…"));
    ui.client.taskLog(id).then(function (d) {
      var lines = Array.isArray(d && d.lines) ? d.lines.map(String) : [];
      ui.logs[id] = lines;
      showLog(box, id, lines);
    }, function (e) {
      clear(box);
      box.appendChild(el("p", "alert", "讀不到日誌：" + humanError(e)));
    });
  }
  function showLog(box, id, lines) {
    clear(box);
    if (!lines.length) { box.appendChild(el("p", "muted", "還沒有日誌。")); }
    else { box.appendChild(el("pre", "ctl-pre", lines.join("\n"))); }
    var again = el("button", "ghost sm", "重新讀取"); again.type = "button";
    again.addEventListener("click", function () { ui.logs[id] = null; fillLog(box, id); });
    box.appendChild(again);
  }

  function showError(e) {
    if (e && e.status === 401 && ui.ctx.onUnauthorized) { ui.ctx.onUnauthorized(); return; }
    ui.dom.bannerText.textContent = humanError(e);
    ui.dom.banner.classList.remove("hidden");
  }

  function refresh() {
    return ui.client.status().then(function (d) {
      ui.status = d;
      ui.dom.banner.classList.add("hidden");
      ui.dom.loading.classList.add("hidden");
      ui.dom.body.classList.remove("hidden");
      renderStatus(d);
    }, function (e) {
      ui.dom.loading.classList.add("hidden");
      if (!ui.status) { ui.dom.body.classList.add("hidden"); }     // 從沒讀到過：只留錯誤＋再試
      showError(e);
    });
  }

  function loadSoul(force) {
    if (ui.soulDirty && !force) { return Promise.resolve(); }   // 有沒存的字：不要蓋掉
    var d = ui.dom;
    d.soulWhen.textContent = "讀取中…";
    return ui.client.soul().then(function (s) {
      ui.soulSaved = String((s && s.text) || "");
      ui.soulUpdated = (s && s.updated_at) || null;
      d.soulText.value = ui.soulSaved;
      setSoulDirty(false);
      soulWhenText();
    }, function (e) {
      d.soulWhen.textContent = "";
      d.soulMsg.textContent = "讀不到偏好：" + humanError(e);
    });
  }
  function soulWhenText() {
    ui.dom.soulWhen.textContent = "上次更新：" + when(ui.soulUpdated, new Date(), "還沒寫過") +
      "・" + ui.dom.soulText.value.length + " 字";
  }
  function setSoulDirty(on) {
    ui.soulDirty = on;
    ui.dom.soulDirty.classList.toggle("hidden", !on);
    ui.dom.soulSave.disabled = !on;
    ui.dom.soulUndo.disabled = !on;
  }

  // ── 助理筆記 ────────────────────────────────────────────────────────

  function noteItem(text, meta, extra, badges, actions, onAct) {
    var li = el("li", "ctl-note");
    var main = el("div", "ctl-note-main");
    main.appendChild(el("span", "ctl-note-text", text));
    if (badges && badges.length) {
      var bs = el("span", "ctl-note-badges");
      badges.forEach(function (b) { bs.appendChild(el("span", "badge warn", b)); });
      main.appendChild(bs);
    }
    if (meta) { main.appendChild(el("span", "ctl-task-meta", meta)); }
    (extra || []).forEach(function (t) { if (t) { main.appendChild(el("span", "ctl-note-why", t)); } });
    li.appendChild(main);
    var row = el("div", "row ctl-note-acts");
    actions.forEach(function (a, i) {
      var b = el("button", (i === 0 ? "" : "ghost ") + "sm", a[1]); b.type = "button";
      b.addEventListener("click", function () { onAct(a[0], li); });
      row.appendChild(b);
    });
    li.appendChild(row);
    return li;
  }

  function renderNotes(data) {
    var v = notesModel(data, new Date()), d = ui.dom;
    d.nUsage.textContent = v.usage;
    d.nOver.textContent = v.overText;
    d.nOver.classList.toggle("hidden", !v.over);
    d.nMode.textContent = v.mode;
    d.nPendingTitle.textContent = v.pendingTitle;
    d.nPendingTitle.classList.toggle("hidden", !v.pendingTitle);
    clear(d.nPending);
    v.pending.forEach(function (p) {
      d.nPending.appendChild(noteItem(p.text, p.head + (p.when ? "・" + p.when : ""), [p.why, p.related],
        p.warn ? [p.warn] : [], p.actions, function (action, li) {
          noteAct(li, ui.client.proposal(p.id, action),
            action === "reject" ? (p.retire ? "留著了。" : "不記這一條；它之後再提同一句也不會記。")
              : (p.retire ? "收起來了（在「收起來的」裡，可以放回去）。" : "加進 soul.md 了。"));
        }));
    });
    d.nTitle.textContent = v.notesTitle;
    clear(d.nList);
    v.notes.forEach(function (n) {
      d.nList.appendChild(noteItem(n.text, n.meta, [], n.badges,
        (n.stale ? [["confirm", "還對"]] : []).concat([["retire", "收起來"]]), function (action, li) {
          noteAct(li, ui.client.note(n.id, action),
            action === "confirm" ? "記下了：這條還對。" : "收起來了：AI 讀不到了；在「收起來的」裡可以放回去。");
        }));
    });
    d.nEmpty.textContent = v.empty;
    d.nEmpty.classList.toggle("hidden", !v.empty);
    d.nArchive.classList.toggle("hidden", !v.archiveTitle);
    d.nArchiveTitle.textContent = v.archiveTitle;
    clear(d.nArchiveList);
    v.archive.forEach(function (a) {
      d.nArchiveList.appendChild(noteItem(a.text, a.meta, [], [], [["restore", "放回去"]], function (action, li) {
        noteAct(li, ui.client.note(a.id, "restore"), "放回 soul.md 了。");
      }));
    });
  }

  // 按了一顆筆記的按鈕：那一列的按鈕先鎖住，成功＝用伺服器回的新清單重畫，soul.md 那一格也重讀
  function noteAct(li, promise, done) {
    var buttons = li.querySelectorAll("button");
    Array.prototype.forEach.call(buttons, function (b) { b.disabled = true; });
    ui.dom.nMsg.textContent = "";
    promise.then(function (view) {
      renderNotes(view);
      ui.dom.nMsg.textContent = done;
      loadSoul(); refresh();
    }, function (e) {
      Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      ui.dom.nMsg.textContent = "沒有成功：" + humanError(e);
    });
  }

  function loadNotes() {
    return ui.client.notes().then(renderNotes, function (e) {
      ui.dom.nUsage.textContent = "";
      ui.dom.nMsg.textContent = "讀不到助理筆記：" + humanError(e);
    });
  }

  function saveFile(name, text) {
    var blob = new Blob([text], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function wire() {
    var d = ui.dom, client = ui.client;
    d.retry.addEventListener("click", function () {
      d.banner.classList.add("hidden");
      if (!ui.status) { d.loading.classList.remove("hidden"); }
      refresh(); loadSoul(); loadNotes();
    });
    d.swInput.addEventListener("change", function () {
      var want = d.swInput.checked;
      d.swInput.disabled = true;
      client.setHeartbeat({ enabled: want }).then(function (hb) {
        if (ui.status) { ui.status.heartbeat = hb; renderStatus(ui.status); }
        d.hbMsg.textContent = want ? "Heartbeat 開了。" : "Heartbeat 關了：常駐助理不會再自己定時看。";
      }, function (e) {
        d.swInput.checked = !want;
        d.hbMsg.textContent = "沒有改成：" + humanError(e);
        if (e && e.status === 401 && ui.ctx.onUnauthorized) { ui.ctx.onUnauthorized(); }
      }).then(function () { d.swInput.disabled = false; });
    });
    d.interval.addEventListener("input", function () { ui.intervalDirty = true; });
    function saveIntervalNow() {
      var check = validateInterval(d.interval.value);
      if (!check.ok) { d.hbMsg.textContent = check.error; d.interval.focus(); return; }
      d.saveInterval.disabled = true;
      client.setHeartbeat({ interval_min: check.value }).then(function (hb) {
        ui.intervalDirty = false;
        if (ui.status) { ui.status.heartbeat = hb; renderStatus(ui.status); }
        d.hbMsg.textContent = "存好了：每 " + check.value + " 分鐘看一輪。";
      }, function (e) {
        d.hbMsg.textContent = "沒有存成：" + humanError(e);
      }).then(function () { d.saveInterval.disabled = false; });
    }
    d.saveInterval.addEventListener("click", saveIntervalNow);
    d.interval.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); saveIntervalNow(); }
    });
    d.runNow.addEventListener("click", function () {
      d.runNow.disabled = true;
      d.hbMsg.textContent = "請常駐助理現在看一輪…";
      client.runNow().then(function (r) {
        d.hbMsg.textContent = (r && r.message) || (r && r.ok === false ? "沒有成功，請再試一次。" : "開始了，結果等一下會出現在「上次結果」。");
        setTimeout(refresh, 1500);
      }, function (e) {
        d.hbMsg.textContent = "沒有開始：" + humanError(e);
      }).then(function () { d.runNow.disabled = false; });
    });

    d.soulText.addEventListener("input", function () {
      setSoulDirty(d.soulText.value !== ui.soulSaved);
      soulWhenText();
      d.soulMsg.textContent = "";
    });
    d.soulUndo.addEventListener("click", function () {
      d.soulText.value = ui.soulSaved;
      setSoulDirty(false);
      soulWhenText();
    });
    d.soulSave.addEventListener("click", function () {
      var text = d.soulText.value;
      d.soulSave.disabled = true;
      d.soulMsg.textContent = "儲存中…";
      client.saveSoul(text).then(function (r) {
        ui.soulSaved = text;
        setSoulDirty(d.soulText.value !== text);
        d.soulMsg.textContent = "存好了。常駐助理下一次醒來就會照新的偏好。";
        if (r && r.updated_at) { ui.soulUpdated = r.updated_at; soulWhenText(); }
        else { ui.soulUpdated = new Date().toISOString(); soulWhenText(); }
        refresh(); loadNotes();
      }, function (e) {
        d.soulSave.disabled = false;
        d.soulMsg.textContent = "沒有存成（你打的字還在）：" + humanError(e);
      });
    });

    d.nTidy.addEventListener("click", function () {
      d.nTidy.disabled = true;
      d.nMsg.textContent = "整理中…";
      client.tidy().then(function (r) {
        if (r && r.notes) { renderNotes(r.notes); }
        d.nMsg.textContent = (r && r.message) || "整理過了。";
        loadSoul(); refresh();
      }, function (e) {
        d.nMsg.textContent = "沒有整理成：" + humanError(e);
      }).then(function () { d.nTidy.disabled = false; });
    });
    d.nExport.addEventListener("click", function () {
      d.nExport.disabled = true;
      client.exportSoul().then(function (data) {
        try {
          saveFile("synox-soul-export.json", JSON.stringify(data, null, 2));
          d.nMsg.textContent = "下載了一份（沒有加密的純文字：裡面是你的偏好與紀錄，放好）。";
        } catch (x) { d.nMsg.textContent = "這個瀏覽器存不了檔。"; }
      }, function (e) {
        d.nMsg.textContent = "沒有匯出成：" + humanError(e);
      }).then(function () { d.nExport.disabled = false; });
    });
    function closeForget() { d.fBox.classList.add("hidden"); d.fAsk.disabled = false; }
    function askForget() {
      var word = d.fText.value.trim();
      if (!word) { d.nMsg.textContent = "先打要它忘掉的詞。"; d.fText.focus(); return; }
      d.fAsk.disabled = true;
      d.nMsg.textContent = "";
      client.forget(word, false).then(function (r) {
        var s = forgetSummary(r, word);
        if (!s.any) { d.nMsg.textContent = s.text; d.fAsk.disabled = false; return; }
        ui.forgetWord = word;
        d.fQ.textContent = s.text;
        clear(d.fPreview);
        (Array.isArray(r.preview) ? r.preview : []).forEach(function (t) { d.fPreview.appendChild(el("li", "", String(t))); });
        d.fBox.classList.remove("hidden");
        d.fNo.focus();
      }, function (e) {
        d.nMsg.textContent = "沒有成功：" + humanError(e);
        d.fAsk.disabled = false;
      });
    }
    d.fAsk.addEventListener("click", askForget);
    d.fText.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); askForget(); } });
    d.fNo.addEventListener("click", function () { closeForget(); d.fText.focus(); });
    d.fGo.addEventListener("click", function () {
      d.fGo.disabled = true;
      client.forget(ui.forgetWord, true).then(function () {
        closeForget();
        d.fText.value = "";
        d.nMsg.textContent = "忘掉了。";
        loadNotes(); loadSoul(); refresh();
      }, function (e) {
        d.nMsg.textContent = "沒有忘掉：" + humanError(e);
      }).then(function () { d.fGo.disabled = false; });
    });
    d.aResume.addEventListener("click", function () {
      d.aResume.disabled = true;
      client.resumeActivator().then(function (r) {
        d.aMsg.textContent = (r && r.message) || "恢復了。";
        refresh();
      }, function (e) {
        d.aMsg.textContent = "沒有恢復成：" + humanError(e);
      }).then(function () { d.aResume.disabled = false; });
    });
    d.aRunPending.addEventListener("click", function () {
      d.aRunPending.disabled = true;
      client.runPending().then(function (r) {
        d.aMsg.textContent = (r && r.message) || "開始處理了。";
        refresh();
      }, function (e) {
        d.aMsg.textContent = "沒有處理成：" + humanError(e);
      }).then(function () { d.aRunPending.disabled = false; });
    });

    d.resetOpen.addEventListener("click", function () {
      d.confirmBox.classList.remove("hidden");
      d.resetOpen.classList.add("hidden");
      d.resetMsg.textContent = "";
      d.resetNo.focus();
    });
    function closeConfirm() {
      d.confirmBox.classList.add("hidden");
      d.resetOpen.classList.remove("hidden");
    }
    d.resetNo.addEventListener("click", function () { closeConfirm(); d.resetOpen.focus(); });
    d.resetGo.addEventListener("click", function () {
      d.resetGo.disabled = true;
      client.resetMemory().then(function (r) {
        closeConfirm();
        d.resetMsg.textContent = (r && r.ok === false) ? "沒有清成，請再試一次。" : "清空了。soul.md 和其他資料都還在。";
        if (!(r && r.ok === false) && ui.ctx.toast) { ui.ctx.toast("常駐助理的記憶清空了"); }
        refresh();
      }, function (e) {
        d.resetMsg.textContent = "沒有清成：" + humanError(e);
      }).then(function () { d.resetGo.disabled = false; });
    });
  }

  // app.html 的 show("control") 叫這個；container 是 #view-control
  function open(container, ctx) {
    ctx = ctx || {};
    if (!ui || ui.container !== container) {
      ui = { container: container, ctx: ctx, status: null, openLogs: {}, logs: {}, timer: null,
             soulSaved: "", soulUpdated: null, soulDirty: false, intervalDirty: false, forgetWord: "" };
      ui.client = makeClient(ctx.fetch || function (p, o) { return root.fetch(p, o); },
        function () { return ui.ctx.me ? ui.ctx.me.csrf : ""; });
      ui.dom = build(container);
      wire();
    }
    ui.ctx = ctx;
    if (!canSee(ctx.me)) { leave(); return; }
    refresh();
    loadSoul();
    loadNotes();
    if (ui.timer) { clearInterval(ui.timer); }
    ui.timer = setInterval(function () {
      if (!root.document || !root.document.hidden) { refresh(); }
    }, POLL_MS);
  }
  function leave() {
    if (ui && ui.timer) { clearInterval(ui.timer); ui.timer = null; }
  }

  var api = {
    // 純函式（tests/js/test_control.js）
    taskState: taskState, motherState: motherState, ruleStatus: ruleStatus, relative: relative, when: when,
    normalizeActivator: normalizeActivator, activatorView: activatorView,
    validateInterval: validateInterval, resultText: resultText, normalizeStatus: normalizeStatus,
    viewModel: viewModel, humanError: humanError, makeClient: makeClient, canSee: canSee,
    normalizeNotes: normalizeNotes, notesModel: notesModel, forgetSummary: forgetSummary,
    RESET_CLEARS: RESET_CLEARS, RESET_KEEPS: RESET_KEEPS,
    INTERVAL_MIN: INTERVAL_MIN, INTERVAL_MAX: INTERVAL_MAX, INTERVAL_DEFAULT: INTERVAL_DEFAULT,
    // 畫面
    open: open, leave: leave
  };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxControl = api; }
})(typeof window !== "undefined" ? window : this);
