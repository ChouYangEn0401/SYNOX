/* SYNOX 新手教學的畫面：SYNOX 自己在真的畫面上指給人看（聚光圈＋小卡），內容來自核心（GET /api/tour，synox/tour）。
 *
 *   window.SynoxTour.init({ api, toast, fill, go })      app.html 拿到 /api/me 之後呼叫（第一次會問「要不要我帶你走一遍？」）
 *   window.SynoxTour.start(tourId, stepId)                開始／接著走（/tutorial 的回覆、對話裡的按鈕、邀請卡的「開始」）
 *   window.SynoxTour.signal(name, value)                  app.html 告訴教學「剛剛發生了什麼」（送出訊息、載入清單、移除…）
 *   window.SynoxTour.chatButton(block, live, id)          對話裡 tour 區塊的「在畫面上帶我走」按鈕（live＝剛收到的，自動開始）
 *
 * 安全（tests/test_tour.py 會掃這個檔）：
 * - 只畫東西、不按東西：不呼叫任何元素的 click()、不送出表單、不改設定。聚光圈與遮罩是 pointer-events: none。
 * - 只打三支 API：GET /api/tour、POST /api/tour/progress、POST /api/tour/offer（都只碰這個人自己的教學進度）。
 * - 「幫我填好」只把字放進輸入框（ctx.fill，不送出）；「帶我去」只換網址的 #（ctx.go）。
 * - 位置只用 data-tour 名字找（synox/tour/anchors.py 的清單），找不到就退成畫面中央的文字卡：教學永遠走得完。
 * - 字一律 textContent。
 */
(function (root) {
  "use strict";

  var ctx = null;            // { api, toast, fill(text), go(view, tab) }
  var data = null;           // GET /api/tour 的結果
  var cur = null;            // { tour, at, done: {}, shownAt, base, ok, minimized }
  var ui = { ring: null, card: null, pill: null, offer: null };
  var started = {};          // 對話裡已經自動開始過的訊息 id（同一則不會一直重開）
  var timer = null;
  var advanceTimer = null;
  var lastFocus = null;

  var TEXT = {
    count: "教學 {a}／{b}", prev: "上一步", next: "下一步", finish: "完成", leave: "先離開", fill: "幫我填好",
    go: "帶我去", minimize: "收起", expand: "🎓 教學 {a}／{b}", done: "✓ 做到了！", already: "✓ 你已經在這裡了。",
    missing: "（這個東西現在不在畫面上，可以按「帶我去」。）", missingNoGo: "（這個東西現在不在畫面上，看字就好。）",
    from: "這份教學是工具「{s}」附的", offerTitle: "要不要我帶你走一遍？（約 {m} 分鐘）",
    offerBody: "我會在畫面上指給你看每個地方：怎麼聊天、工具在哪、怎麼裝和移除工具。之後忘了，打 /tutorial 就能再看。",
    offerStart: "開始", offerLater: "之後再說", laterToast: "好，想看的時候打 /tutorial（或按 /help）。",
    paused: "先停在這裡。之後打 /tutorial 就會接著走。", finished: "🎉 走完了！忘了隨時打 /tutorial 再看一次。",
    startButton: "▶ 在畫面上帶我走", none: "現在沒有教學可以看。"
  };

  function fill(s, vars) { return String(s).replace(/\{(\w+)\}/g, function (_m, k) { return vars[k]; }); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }
  function button(cls, text, fn) {
    var b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", fn);
    return b;
  }
  function reduced() {
    return !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  function phone() { return !!(root.matchMedia && root.matchMedia("(max-width: 760px)").matches); }
  function remove(node) { if (node && node.parentNode) { node.parentNode.removeChild(node); } }

  // ── 資料 ───────────────────────────────────────────────────────────
  function refresh() {
    return ctx.api("GET", "/api/tour").then(function (d) { data = d; return d; });
  }
  function findTour(id) {
    var list = (data && data.tours) || [];
    for (var i = 0; i < list.length; i++) { if (list[i].id === id) { return list[i]; } }
    return list[0] || null;
  }
  function save(state) {
    if (!cur) { return; }
    var step = cur.tour.steps[cur.at];
    var done = Object.keys(cur.done);
    ctx.api("POST", "/api/tour/progress", { tour: cur.tour.id, step: step.id, state: state, done: done })
      .catch(function () { /* 進度沒存到：下次從上一個存到的地方接，教學照走 */ });
  }

  // ── 找位置、判斷做完了沒 ───────────────────────────────────────────
  function visible(node) {
    if (!node) { return false; }
    var r = node.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) { return false; }
    var st = root.getComputedStyle ? root.getComputedStyle(node) : null;
    return !st || (st.visibility !== "hidden" && st.display !== "none");
  }
  function target(step) {
    var names = step.anchors || [];
    for (var i = 0; i < names.length; i++) {
      var list = document.querySelectorAll('[data-tour="' + names[i].replace(/[^a-z0-9._-]/g, "") + '"]');
      for (var j = 0; j < list.length; j++) { if (visible(list[j])) { return list[j]; } }
    }
    return null;
  }
  function stateOk(step) {               // 看得出來的狀態（不用等事件）：在哪一頁、哪個分頁
    var d = step.done_when;
    if (!d) { return false; }
    if (d.event === "view") { return document.body.getAttribute("data-view") === d.value; }
    if (d.event === "tab") {
      if (document.body.getAttribute("data-view") !== "settings") { return false; }
      var a = document.querySelector('#set-tabs a[data-tab="' + String(d.value).replace(/[^a-z]/g, "") + '"]');
      return !!a && a.getAttribute("aria-selected") === "true";
    }
    return false;
  }
  function signal(name, value) {
    if (!cur) { return; }
    var step = cur.tour.steps[cur.at];
    var d = step.done_when;
    if (!d || d.event !== name) { return; }
    if (d.value && String(value || "") !== d.value) { return; }
    markDone(true);
  }
  function markDone(advance) {
    if (!cur || cur.ok) { return; }
    var step = cur.tour.steps[cur.at];
    cur.ok = true;
    cur.done[step.id] = 1;
    paint();
    if (advance && cur.at + 1 < cur.tour.steps.length) {
      clearTimeout(advanceTimer);
      var at = cur.at;
      advanceTimer = setTimeout(function () { if (cur && cur.at === at) { show(at + 1); } }, reduced() ? 1400 : 1100);
    }
  }

  // ── 畫 ─────────────────────────────────────────────────────────────
  function ensure() {
    if (!ui.ring) {
      ui.ring = el("div", "tour-ring hidden");
      ui.ring.setAttribute("aria-hidden", "true");
      document.body.appendChild(ui.ring);
    }
    if (!ui.card) {
      ui.card = el("div", "tour-card");
      ui.card.setAttribute("role", "dialog");
      ui.card.setAttribute("aria-modal", "false");
      ui.card.setAttribute("aria-labelledby", "tour-title");
      ui.card.setAttribute("aria-describedby", "tour-body");
      ui.card.tabIndex = -1;
      document.body.appendChild(ui.card);
    }
  }
  function paint() {
    if (!cur) { return; }
    ensure();
    var t = cur.tour, step = t.steps[cur.at], n = t.steps.length, last = cur.at + 1 >= n;
    var card = ui.card;
    while (card.firstChild) { card.removeChild(card.firstChild); }
    var top = el("div", "tour-top");
    top.appendChild(el("span", "count", fill(TEXT.count, { a: cur.at + 1, b: n })));
    top.appendChild(button("ghost sm", TEXT.minimize, minimize));
    top.appendChild(button("ghost sm", TEXT.leave, leave));
    card.appendChild(top);
    var bar = el("div", "tour-bar"), fillBar = el("span");
    fillBar.style.width = Math.round(((cur.at + 1) / n) * 100) + "%";
    bar.appendChild(fillBar);
    bar.setAttribute("aria-hidden", "true");
    card.appendChild(bar);
    if (t.source) { card.appendChild(el("p", "tour-src", fill(TEXT.from, { s: t.source }))); }
    var h = el("h2", "", step.title);
    h.id = "tour-title";
    h.tabIndex = -1;
    card.appendChild(h);
    var body = el("p", "", step.body);
    body.id = "tour-body";
    card.appendChild(body);
    var tgt = target(step);
    if (cur.ok) {
      card.appendChild(el("p", "tour-ok", cur.base ? TEXT.already : TEXT.done));
    } else if (!tgt && (step.anchors || []).length) {
      card.appendChild(el("p", "tour-note", step.go ? TEXT.missing : TEXT.missingNoGo));
    }
    var actions = el("div", "tour-actions");
    if (cur.at > 0) { actions.appendChild(button("ghost", TEXT.prev, function () { show(cur.at - 1); })); }
    actions.appendChild(el("span", "spacer"));
    if (step["try"]) {
      actions.appendChild(button("", TEXT.fill, function () { ctx.fill(step["try"]); }));
    }
    if (step.go && (!tgt || last)) {
      actions.appendChild(button(last ? "" : "primary", TEXT.go, function () { ctx.go(step.go.view, step.go.tab || ""); }));
    }
    actions.appendChild(button(step.go && (!tgt || last) && !last ? "" : "primary", last ? TEXT.finish : TEXT.next,
      function () { if (last) { finish(); } else { cur.done[step.id] = 1; show(cur.at + 1); } }));
    card.appendChild(actions);
    place();
  }
  function place() {
    if (!cur || !ui.card || cur.minimized) { return; }
    var step = cur.tour.steps[cur.at];
    var tgt = target(step), card = ui.card, ring = ui.ring;
    card.classList.remove("center", "dock-top", "dock-bottom");
    card.style.top = ""; card.style.left = ""; card.style.bottom = "";
    if (!tgt) {
      ring.classList.add("hidden");
      card.classList.add("center");
      return;
    }
    var r = tgt.getBoundingClientRect(), vh = root.innerHeight, vw = root.innerWidth;
    if (r.bottom < 0 || r.top > vh) {
      tgt.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" });
      r = tgt.getBoundingClientRect();
    }
    var pad = 6;
    ring.classList.remove("hidden");
    ring.style.top = Math.max(0, r.top - pad) + "px";
    ring.style.left = Math.max(0, r.left - pad) + "px";
    ring.style.width = Math.min(vw, r.width + pad * 2) + "px";
    ring.style.height = Math.min(vh, r.height + pad * 2) + "px";
    if (phone()) {                       // 手機：小卡貼在上或下，不蓋住要按的地方
      card.classList.add(r.top + r.height / 2 > vh / 2 ? "dock-top" : "dock-bottom");
      return;
    }
    var cw = card.offsetWidth, ch = card.offsetHeight, gap = 14, top, left;
    if (r.bottom + gap + ch <= vh - 8) { top = r.bottom + gap; left = r.left; }
    else if (r.top - gap - ch >= 8) { top = r.top - gap - ch; left = r.left; }
    else if (r.right + gap + cw <= vw - 8) { top = r.top; left = r.right + gap; }
    else if (r.left - gap - cw >= 8) { top = r.top; left = r.left - gap - cw; }
    else { top = vh - ch - 12; left = vw - cw - 12; }
    card.style.top = Math.max(8, Math.min(top, vh - ch - 8)) + "px";
    card.style.left = Math.max(8, Math.min(left, vw - cw - 8)) + "px";
  }
  function tick() {
    if (!cur) { return; }
    var step = cur.tour.steps[cur.at];
    if (!cur.ok && step.done_when && stateOk(step)) { markDone(!cur.base); }
    if (!cur.minimized) {
      var had = !ui.ring.classList.contains("hidden"), has = !!target(step);
      if (had !== has) { paint(); } else { place(); }
    }
  }

  // ── 走 ─────────────────────────────────────────────────────────────
  function show(at) {
    if (!cur) { return; }
    clearTimeout(advanceTimer);
    var n = cur.tour.steps.length;
    cur.at = Math.max(0, Math.min(n - 1, at));
    var step = cur.tour.steps[cur.at];
    cur.base = !!(step.done_when && stateOk(step));     // 一開始就已經做到了：打個勾，不自動跳
    cur.ok = cur.base;
    if (cur.minimized) { expand(); }
    paint();
    var h = document.getElementById("tour-title");
    if (h) { h.focus({ preventScroll: true }); }
    save("active");
  }
  function begin(tour, stepId) {
    stop(true);
    var at = 0;
    for (var i = 0; i < tour.steps.length; i++) { if (tour.steps[i].id === stepId) { at = i; } }
    var rec = (data.progress || {})[tour.id] || {};
    var done = {};
    (rec.done || []).forEach(function (id) { done[id] = 1; });
    lastFocus = document.activeElement;
    cur = { tour: tour, at: at, done: done, ok: false, base: false, minimized: false };
    removeOffer();
    show(at);
    timer = setInterval(tick, 400);
    root.addEventListener("resize", place);
    root.addEventListener("scroll", place, true);
  }
  function start(tourId, stepId) {
    if (!ctx) { return; }
    return refresh().then(function () {
      var tour = findTour(tourId || data["default"]);
      if (!tour || !tour.steps.length) { ctx.toast(TEXT.none); return; }
      var rec = (data.progress || {})[tour.id] || {};
      begin(tour, stepId || (rec.state === "finished" ? "" : rec.step) || "");
    }).catch(function (e) { ctx.toast(e.message); });
  }
  function stop(silent) {
    clearInterval(timer); timer = null;
    clearTimeout(advanceTimer);
    root.removeEventListener("resize", place);
    root.removeEventListener("scroll", place, true);
    remove(ui.ring); remove(ui.card); remove(ui.pill);
    ui.ring = ui.card = ui.pill = null;
    var was = cur;
    cur = null;
    if (!silent && lastFocus && lastFocus.focus && document.body.contains(lastFocus)) { lastFocus.focus(); }
    return was;
  }
  function leave() {
    save("paused");
    stop(false);
    ctx.toast(TEXT.paused);
  }
  function finish() {
    var step = cur.tour.steps[cur.at];
    cur.done[step.id] = 1;
    save("finished");
    stop(false);
    ctx.toast(TEXT.finished);
  }
  function minimize() {
    if (!cur) { return; }
    cur.minimized = true;
    ui.card.classList.add("hidden");
    ui.card.style.display = "none";
    ui.ring.classList.add("hidden");
    ui.pill = button("primary tour-pill", fill(TEXT.expand, { a: cur.at + 1, b: cur.tour.steps.length }), expand);
    document.body.appendChild(ui.pill);
    ui.pill.focus();
  }
  function expand() {
    if (!cur) { return; }
    cur.minimized = false;
    remove(ui.pill); ui.pill = null;
    ui.card.classList.remove("hidden");
    ui.card.style.display = "";
    paint();
    ui.card.focus();
  }

  // ── 第一次打開網頁的邀請 ────────────────────────────────────────────
  function removeOffer() { remove(ui.offer); ui.offer = null; }
  function offer(tries) {
    if (!data || !data.offer || cur || ui.offer) { return; }
    var gate = root.SynoxSplash;
    if (gate && gate.isOpen && gate.isOpen()) {         // 開場的門還開著（static/splash.js）：等使用者點進來再問（不要疊在一起）
      document.addEventListener(gate.DONE, function again() {
        document.removeEventListener(gate.DONE, again);
        offer(tries);
      });
      return;
    }
    if (document.querySelector(".sx-splash") && (tries || 0) < 12) {     // 門正在淡出：等它收掉
      setTimeout(function () { offer((tries || 0) + 1); }, 400);
      return;
    }
    var tour = findTour(data["default"]);
    if (!tour) { return; }
    var box = el("div", "tour-offer");
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "false");
    box.setAttribute("aria-labelledby", "tour-offer-title");
    var h = el("h2", "", fill(TEXT.offerTitle, { m: tour.minutes }));
    h.id = "tour-offer-title";
    box.appendChild(h);
    box.appendChild(el("p", "", TEXT.offerBody));
    var actions = el("div", "tour-actions");
    actions.appendChild(button("ghost", TEXT.offerLater, function () {
      removeOffer();
      ctx.api("POST", "/api/tour/offer", { answer: "later" }).catch(function () {});
      ctx.toast(TEXT.laterToast);
    }));
    actions.appendChild(button("primary", TEXT.offerStart, function () {
      removeOffer();
      ctx.api("POST", "/api/tour/offer", { answer: "start" }).catch(function () {});
      start(tour.id, "");
    }));
    box.appendChild(actions);
    ui.offer = box;
    document.body.appendChild(box);
  }

  // ── 對話裡的 tour 區塊（/tutorial 的回覆）─────────────────────────────
  function chatButton(block, live, messageId) {
    var b = button("primary tour-start", TEXT.startButton, function () { start(block.tour, ""); });
    if (live && messageId !== undefined && !started[messageId]) {
      started[messageId] = 1;
      setTimeout(function () { start(block.tour, block.step || ""); }, 50);
    }
    return b;
  }

  document.addEventListener("keydown", function (ev) {
    if (!cur || ev.key !== "Escape") { return; }
    if (cur.minimized) { return; }
    ev.preventDefault();
    minimize();
  });
  document.addEventListener("synox:install-step", function (ev) {
    var d = ev.detail || {};
    if (d.step === "review") { signal("pack_report"); }
    if (d.step === "done" && d.status !== "fail") { signal("pack_installed"); }
  });

  function init(c) {
    ctx = c;
    return refresh().then(function () { offer(0); }).catch(function () { /* 沒有教學也不影響其他畫面 */ });
  }

  root.SynoxTour = {
    init: init, start: start, signal: signal, chatButton: chatButton,
    active: function () { return !!cur; }, _text: TEXT
  };
})(window);
