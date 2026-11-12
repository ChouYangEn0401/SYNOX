/* SYNOX 網頁「主控」頁（只有擁有者看得到）。
 *
 * 伺服器把這個檔原地塞進 app.html 裡 INCLUDE:control.js 那一格（server.app_html），送出去仍是一頁、
 * 同一個 CSP nonce。分成檔是為了好維護、好測：上半部是純函式（不碰 DOM，tests/js/test_control.js 用 node 跑），
 * 下半部 mount() 才畫畫面。文字一律 textContent。
 *
 * API（全部擁有者才能叫；非 GET 帶 X-SYNOX-CSRF，跟 app.html 的 api() 一樣）：
 *   GET  /api/runtime/status              {heartbeat, mother, tasks}
 *   POST /api/runtime/heartbeat           {enabled?, interval_min?} → 新的 heartbeat
 *   POST /api/runtime/heartbeat/run-now   → {ok, message}
 *   POST /api/runtime/mother/reset-memory → {ok}
 *   GET  /api/runtime/soul                {text, updated_at}；PUT 同一個網址 {text}
 *   GET  /api/runtime/tasks/<id>/log      {lines: [...]}
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

  function taskState(state) {
    return TASK_STATES[state] || { tone: "idle", label: "不明" };
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
      })
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
      })
    };
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
      taskLog: function (id) { return call("GET", "/api/runtime/tasks/" + encodeURIComponent(id) + "/log"); }
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
    mother.appendChild(mLine); mother.appendChild(mHint);
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
      soulText: soulText, soulWhen: soulWhen, soulDirty: soulDirty, soulSave: soulSave, soulUndo: soulUndo,
      soulMsg: soulMsg,
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

  function wire() {
    var d = ui.dom, client = ui.client;
    d.retry.addEventListener("click", function () {
      d.banner.classList.add("hidden");
      if (!ui.status) { d.loading.classList.remove("hidden"); }
      refresh(); loadSoul();
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
        refresh();
      }, function (e) {
        d.soulSave.disabled = false;
        d.soulMsg.textContent = "沒有存成（你打的字還在）：" + humanError(e);
      });
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
             soulSaved: "", soulUpdated: null, soulDirty: false, intervalDirty: false };
      ui.client = makeClient(ctx.fetch || function (p, o) { return root.fetch(p, o); },
        function () { return ui.ctx.me ? ui.ctx.me.csrf : ""; });
      ui.dom = build(container);
      wire();
    }
    ui.ctx = ctx;
    if (!canSee(ctx.me)) { leave(); return; }
    refresh();
    loadSoul();
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
    taskState: taskState, motherState: motherState, relative: relative, when: when,
    validateInterval: validateInterval, resultText: resultText, normalizeStatus: normalizeStatus,
    viewModel: viewModel, humanError: humanError, makeClient: makeClient, canSee: canSee,
    RESET_CLEARS: RESET_CLEARS, RESET_KEEPS: RESET_KEEPS,
    INTERVAL_MIN: INTERVAL_MIN, INTERVAL_MAX: INTERVAL_MAX, INTERVAL_DEFAULT: INTERVAL_DEFAULT,
    // 畫面
    open: open, leave: leave
  };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxControl = api; }
})(typeof window !== "undefined" ? window : this);
