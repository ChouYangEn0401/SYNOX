/* 工具服務的主機台畫面（ADR 0024、計畫 C7、C10、WP4）：工具頁的「完整畫面」卡片、側欄的常駐標記、閒置設定。樣式在 static/apps.css。
 *
 * - 「打開」是一個表單：<form method="post" action="/apps/<名>/open" target="_blank" rel="noopener noreferrer">＋隱藏的 csrf 欄位。
 *   不用程式開新視窗、不用 fetch：真的導覽才不會被擋彈出視窗，交接票也不經過這個頁面的程式。開服務與打開畫面是兩個動作。
 * - 畫面上不顯示 app 的網址；埠只在「進階」的小字。字一律 textContent；字串集中在 TEXT。
 * - 頁面看得到時每 30 秒抓一次 GET /api/apps（document.hidden 時不抓）。
 * app.html 在拿到 /api/me 之後叫 window.SynoxApps.init({ api, toast, csrf })；tools.js 的 renderTool 叫 SynoxApps.card(panel, tool)。
 */
(function (root) {
  "use strict";
  var TEXT = {
    cardTitle: "完整畫面",
    open: "打開",
    start: "開啟",
    stop: "關掉",
    keep: "先留著",
    stopAll: "全部關掉",
    whatIs: "這是什麼？為什麼要關？",
    inUseTitle: "什麼叫有在用：",
    on: "開著 · {n} 分鐘沒用",
    onFresh: "開著",
    off: "關著",
    keepTag: "一直開著",
    ownerOnly: "服務由擁有者開關。",
    policyNow: "沒在用的時候：{text}",
    change: "改",
    save: "存起來",
    cancel: "取消",
    custom: "自己填：",
    customUnit: "分鐘沒用就關",
    keepWarn: "這個服務會一直開著，直到你自己關掉或 SYNOX 重開。開著的時候，這台電腦上的其他程式和其他帳號碰得到這扇門。",
    keepOk: "我知道，一直開著",
    blockAsk: "會先把它關掉，確定？",
    blocked: "不開放這個工具的畫面（要開先改上面的設定）。",
    firstTitle: "什麼是工具服務？",
    firstOk: "知道了，開啟",
    firstNo: "先不要",
    side: "● {n} 個工具服務開著",
    sideIdle: "● {title}的服務很久沒用了",
    log: "最近紀錄",
    advanced: "（進階）本機位址 127.0.0.x 的第 {n} 號埠",
    failed: "沒有成功：",
    problem: "這個工具的畫面現在不能開：",
    unavailable: "現在不能用：",
    events: { start: "開了", stop: "關了", auto_stop: "自動關了", suggest: "提醒很久沒用", keep: "按了先留著",
              policy: "改了閒置設定", handoff: "打開了畫面", enter: "進到畫面", leave: "離開畫面", action: "在畫面上做了一個動作",
              "export": "匯出了資料", denied: "擋下一個不對的請求", error: "出錯" },
    // 手機入口（ADR 0026；S14 填）
    remoteRow: "📱 手機入口"
  };
  var POLICY_CHOICES = [
    { key: "auto120", label: "120 分鐘沒用就關，30 分鐘先提醒（建議）", body: { mode: "auto", close_min: 120 } },
    { key: "auto30", label: "30 分鐘沒用就關", body: { mode: "auto", close_min: 30 } },
    { key: "custom", label: "自己填 N 分鐘", body: null },
    { key: "suggest", label: "只提醒，不自動關", body: { mode: "suggest" } },
    { key: "keep", label: "一直開著", body: { mode: "keep", understood: true } },
    { key: "blocked", label: "不開放這個工具的畫面", body: { mode: "blocked" } }
  ];

  function fill(text, vars) {
    return String(text).replace(/\{(\w+)\}/g, function (_m, k) { return vars[k] === undefined ? "" : String(vars[k]); });
  }

  /* 純函式（tests/js/test_apps.js） */
  function policyBody(key, minutes) {
    if (key === "custom") {
      var n = Number(minutes);
      if (!isFinite(n) || Math.floor(n) !== n || n < 5 || n > 1440) { return null; }
      return { mode: "auto", close_min: n };
    }
    var c = POLICY_CHOICES.filter(function (x) { return x.key === key; })[0];
    return c ? c.body : null;
  }

  function stateLine(view) {
    if (view.state !== "on") { return TEXT.off; }
    return view.idle_min > 0 ? fill(TEXT.on, { n: view.idle_min }) : TEXT.onFresh;
  }

  function sideText(data) {
    var on = (data.apps || []).filter(function (a) { return a.state === "on"; });
    var idle = on.filter(function (a) { return a.suggest_close; })[0];
    if (idle) { return { text: fill(TEXT.sideIdle, { title: idle.title }), warn: true, count: on.length }; }
    var keep = on.some(function (a) { return a.policy && a.policy.mode === "keep"; });
    return { text: fill(TEXT.side, { n: on.length }), warn: keep, count: on.length };
  }

  function make(doc) {
    function el(tag, cls, text) {
      var e = doc.createElement(tag);
      if (cls) { e.className = cls; }
      if (text !== undefined && text !== null) { e.textContent = String(text); }
      return e;
    }
    return el;
  }

  function openForm(doc, name, csrf) {
    var el = make(doc);
    var f = el("form", "app-open");
    f.method = "post";
    f.action = "/apps/" + encodeURIComponent(name) + "/open";
    f.target = "_blank";
    f.rel = "noopener noreferrer";
    f.setAttribute("rel", "noopener noreferrer");
    var hidden = el("input");
    hidden.type = "hidden";
    hidden.name = "csrf";
    hidden.value = csrf || "";
    f.appendChild(hidden);
    var b = el("button", "primary", TEXT.open);
    b.type = "submit";
    f.appendChild(b);
    return f;
  }

  /* ctx：{ canManage, csrf, explain, onStart(view), onStop(view), onKeep(view), onPolicy(view, body), confirm(text) → Promise } */
  function renderCard(doc, view, ctx) {
    var el = make(doc);
    var card = el("section", "app-card");
    card.appendChild(el("div", "section-label", TEXT.cardTitle));
    var policy = view.policy || {};
    var line = el("p", "app-policy", fill(TEXT.policyNow, { text: policy.text || "" }));
    if (policy.mode === "keep") { line.appendChild(el("span", "badge warn app-keep", TEXT.keepTag)); }
    card.appendChild(line);
    if (view.problem) {
      card.appendChild(el("p", "app-problem", TEXT.problem + view.problem));
    } else if (view.state === "error") {
      card.appendChild(el("p", "app-problem", view.error || TEXT.failed));
    }
    var row = el("div", "app-row");
    var state = el("span", "badge " + (view.state === "on" ? (view.suggest_close ? "warn" : "ok") : ""), stateLine(view));
    row.appendChild(state);
    if (view.state === "on" && view.open) { row.appendChild(openForm(doc, view.name, ctx.csrf)); }
    if (ctx.canManage) {
      if (view.state === "on") {
        var stop = el("button", "", TEXT.stop);
        stop.addEventListener("click", function () { ctx.onStop(view); });
        row.appendChild(stop);
        if (view.suggest_close) {
          var keep = el("button", "", TEXT.keep);
          keep.addEventListener("click", function () { ctx.onKeep(view); });
          row.appendChild(keep);
        }
      } else if (policy.mode !== "blocked" && !view.problem) {
        var start = el("button", "primary", TEXT.start);
        start.addEventListener("click", function () { ctx.onStart(view); });
        row.appendChild(start);
      }
    }
    card.appendChild(row);
    if (view.state !== "on" && ctx.explain && policy.mode !== "blocked") { card.appendChild(el("p", "sub", ctx.explain.what)); }
    if (policy.mode === "blocked") { card.appendChild(el("p", "sub", TEXT.blocked)); }
    if (!ctx.canManage) { card.appendChild(el("p", "sub", TEXT.ownerOnly)); }
    if (ctx.canManage) { card.appendChild(policyEditor(doc, view, ctx)); }
    if (ctx.explain) {
      var more = el("details", "app-more");
      more.appendChild(el("summary", "", TEXT.whatIs));
      ["what", "why_close", "restart"].forEach(function (k) { more.appendChild(el("p", "", ctx.explain[k])); });
      more.appendChild(el("p", "sub", TEXT.inUseTitle + (ctx.explain.in_use || "")));
      if (view.port) { more.appendChild(el("small", "muted", fill(TEXT.advanced, { n: view.port }))); }
      card.appendChild(more);
    }
    return card;
  }

  function policyEditor(doc, view, ctx) {
    var el = make(doc);
    var box = el("div", "app-policy-edit");
    var toggle = el("button", "ghost", TEXT.change);
    var form = el("div", "app-policy-form hidden");
    var picked = "auto120";
    var number = el("input");
    number.type = "number";
    number.min = "5";
    number.max = "1440";
    POLICY_CHOICES.forEach(function (c) {
      var label = el("label", "app-choice");
      var radio = el("input");
      radio.type = "radio";
      radio.name = "policy-" + view.name;
      radio.value = c.key;
      radio.addEventListener("change", function () { picked = c.key; });
      label.appendChild(radio);
      label.appendChild(el("span", "", c.key === "custom" ? TEXT.custom : c.label));
      if (c.key === "custom") {
        label.appendChild(number);
        label.appendChild(el("span", "", TEXT.customUnit));
      }
      form.appendChild(label);
    });
    var warn = el("p", "app-warn hidden", TEXT.keepWarn);
    form.appendChild(warn);
    var save = el("button", "primary", TEXT.save);
    var cancel = el("button", "ghost", TEXT.cancel);
    save.addEventListener("click", function () {
      var body = policyBody(picked, number.value);
      if (!body) { return; }
      if (picked === "keep") {
        return ctx.confirm(TEXT.keepWarn, TEXT.keepOk).then(function (yes) { if (yes) { ctx.onPolicy(view, body); } });
      }
      if (picked === "blocked" && view.state === "on") {
        return ctx.confirm(TEXT.blockAsk).then(function (yes) { if (yes) { ctx.onPolicy(view, body); } });
      }
      ctx.onPolicy(view, body);
    });
    cancel.addEventListener("click", function () { form.classList.add("hidden"); });
    form.appendChild(save);
    form.appendChild(cancel);
    toggle.addEventListener("click", function () { form.classList.toggle("hidden"); });
    box.appendChild(toggle);
    box.appendChild(form);
    return box;
  }

  /* 接上主機台 ───────────────────────────────────────────────────── */
  var deps = null, last = null, cards = {}, timer = null;

  function refresh() {
    if (!deps) { return Promise.resolve(null); }
    return deps.api("GET", "/api/apps").then(function (d) {
      last = d;
      drawSide(d);
      Object.keys(cards).forEach(function (name) { drawCard(name); });
      return d;
    }, function () { return null; });
  }

  function viewOf(name) {
    return ((last && last.apps) || []).filter(function (a) { return a.name === name; })[0];
  }

  function act(path, body) {
    return deps.api("POST", path, body || {}).then(refresh, function (e) {
      if (deps.toast) { deps.toast(TEXT.failed + (e && e.message ? e.message : "")); }
      return refresh();
    });
  }

  function confirmBox(text, okText) {
    var doc = root.document;
    var el = make(doc);
    return new Promise(function (resolve) {
      var back = el("div", "app-modal");
      var box = el("div", "app-modal-box");
      box.setAttribute("role", "dialog");
      String(text).split("\n").forEach(function (t) { box.appendChild(el("p", "", t)); });
      var ok = el("button", "primary", okText || TEXT.save);
      var no = el("button", "ghost", TEXT.cancel);
      box.appendChild(ok);
      box.appendChild(no);
      back.appendChild(box);
      doc.body.appendChild(back);
      function done(v) { back.parentNode.removeChild(back); resolve(v); }
      ok.addEventListener("click", function () { done(true); });
      no.addEventListener("click", function () { done(false); });
    });
  }

  function ctxFor() {
    return {
      canManage: !!(last && last.can_manage), csrf: deps.csrf ? deps.csrf() : "", explain: last && last.explain,
      confirm: confirmBox,
      onStart: function (view) {
        var first = last && !last.explained;
        var go = function () { return act("/api/apps/" + view.name + "/start", { explained: true }); };
        if (!first) { return act("/api/apps/" + view.name + "/start", {}); }
        var e = last.explain || {};
        return confirmBox([TEXT.firstTitle, e.what, e.why_close, e.restart].join("\n"), TEXT.firstOk).then(function (yes) {
          if (yes) { return go(); }
        });
      },
      onStop: function (view) { return act("/api/apps/" + view.name + "/stop"); },
      onKeep: function (view) { return act("/api/apps/" + view.name + "/keep"); },
      onPolicy: function (view, body) { return act("/api/apps/" + view.name + "/policy", body); }
    };
  }

  function drawCard(name) {
    var slot = cards[name];
    var view = viewOf(name);
    if (!slot || !view) { return; }
    while (slot.firstChild) { slot.removeChild(slot.firstChild); }
    slot.appendChild(renderCard(root.document, view, ctxFor()));
    if (last && last.can_manage) { drawLog(slot, name); }
  }

  function drawLog(slot, name) {
    deps.api("GET", "/api/apps/log?limit=50").then(function (d) {
      var mine = (d.events || []).filter(function (e) { return e.app === name; }).slice(0, 5);
      if (!mine.length) { return; }
      var el = make(root.document);
      var box = el("details", "app-log");
      box.appendChild(el("summary", "", TEXT.log));
      mine.forEach(function (e) {
        box.appendChild(el("p", "sub", String(e.at || "").slice(11, 16) + " " + (TEXT.events[e.event] || e.event)));
      });
      slot.appendChild(box);
    }, function () {});
  }

  function drawSide(d) {
    var doc = root.document;
    var badge = doc.getElementById("apps-side");
    if (!badge) { return; }
    var s = sideText(d);
    badge.textContent = s.text;
    badge.classList.toggle("hidden", s.count === 0);
    badge.classList.toggle("warn", !!s.warn);
  }

  function card(panel, tool) {
    if (!tool || !tool.app || !deps) { return; }
    var slot = make(root.document)("div", "app-slot");
    panel.appendChild(slot);
    cards[tool.name] = slot;
    if (last) { drawCard(tool.name); }
    refresh();
  }

  function init(d) {
    deps = d;
    refresh();
    if (timer === null && root.setInterval) {
      timer = root.setInterval(function () { if (!root.document.hidden) { refresh(); } }, 30000);
    }
  }

  var api = { TEXT: TEXT, POLICY_CHOICES: POLICY_CHOICES, policyBody: policyBody, stateLine: stateLine, sideText: sideText,
              openForm: openForm, renderCard: renderCard, init: init, card: card, refresh: refresh };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxApps = api; }
})(typeof window !== "undefined" ? window : this);
