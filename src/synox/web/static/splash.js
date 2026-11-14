/* 開場動畫＋「點一下打開 SYNOX」的門（樣式在 static/splash.css；說明與時間表：docs/ui/motion-notes.md）。
 *
 * 這是一個可拆卸的零件（照 ISDPCS fireworks.js 的做法）：只碰畫面，不讀資料、不打 API、不知道誰登入了。
 * 要拿掉 → 刪 app.html 裡 splash.js、splash.css 那兩行 include（左上角 S 的 data-splash-replay 就只是一個沒反應的按鈕）。
 * 壞掉也不會擋住登入或對話：畫面做不出來（build 出錯）就直接放行；門一定有一顆看得到、按得到的按鈕，
 * 點畫面任何地方、按 Enter／空白鍵／Esc 都會進去。
 *
 * 流程（跟介紹頁 docs/landing/page.html 的 SynoxGate 同一個想法：開場播完不會自己消失，等你點）：
 *   1. 每次打開網頁：S 寶寶掉下來、眨眼、說「嗨！」、翻成 S、SYNOX 跳出來（約 1.3 秒，splash.css 的時間表）
 *   2. 停在最後一格：S 輕輕浮著、外面一圈光一直往外擴，下面寫「點一下打開 SYNOX」
 *   3. 點一下（或 Enter／空白鍵）：整片放大、淡掉，後面的 SYNOX 浮上來（LEAVE 毫秒）；動畫還沒播完就點也可以
 *   系統開了「減少動態效果」→ 不播動畫，直接顯示最後一格＋提示，一樣等你點，點了馬上進去。
 *   左上角的 S（[data-splash-replay]）→ 再開一次同樣的門。
 *   新手教學的邀請（static/tour.js）等門關了才出現：document 上的 "synox:splash-done" 事件、SynoxSplash.isOpen()。
 *
 * 外觀（docs/themes.md）：外觀包或「自己貼」換了 slot opening → S 寶寶跟 SYNOX 字換成那一段（static/slots.js 給的，
 * 伺服器消毒過），門的按鈕就是那一段；只換了 wordmark → SYNOX 那五個字換成字標。
 *
 * 什麼時候出現（decide）：
 *   - 網址有 ?splash=0 → 不出現；?splash=1 → 出現（就算下面兩條說不要）
 *   - localStorage 的 synox.splash 是 "off" → 不出現（使用者自己關掉；自動化測試也可以先寫好這個）
 *   - window.SYNOX_NO_SPLASH === true → 不出現（給自動化測試、設計預覽在頁面載入前先設好）
 *   - 其他：每次打開（含重新整理、登入後回到首頁）都出現
 */
(function (root) {
  "use strict";
  var OFF = "synox.splash";            // localStorage："off"＝不要開場
  var DONE = "synox:splash-done";      // 門關了：document 上的事件
  var READY_AT = 1300;                 // 開場播完、停在最後一格（跟 splash.css 的 1.3s 對齊；只給文件與測試用）
  var LEAVE = 480;                     // 點了之後：放大淡出到拿掉（跟 splash.css 的 .45s 對齊）
  var current = null;                  // 現在開著的門（同時只會有一個）

  function decide(search, off, skip) {
    var m = /[?&]splash=([01])(?:&|#|$)/.exec(search || "");
    if (m) { return m[1] === "1"; }
    if (skip === true) { return false; }
    return off !== "off";
  }

  function read(kind, key) {
    try { var s = root[kind]; return s ? s.getItem(key) : null; } catch (e) { return null; }
  }
  function calm() {
    try { return !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches); }
    catch (e) { return false; }
  }
  function coarse() {
    try { return !!(root.matchMedia && root.matchMedia("(pointer: coarse)").matches); }
    catch (e) { return false; }
  }

  function el(doc, tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) { e.className = cls; }
    if (text) { e.textContent = text; }
    return e;
  }

  // 外觀換掉的 slot（static/slots.js；沒有＝null）。外面包一層 SYNOX 的動畫（slot 本身的位置是釘死的，不能動）
  function themed(doc, name) {
    var slots = root.SynoxSlots;
    if (!(slots && slots.has && slots.has(name))) { return null; }
    var wrap = el(doc, "div", name === "opening" ? "sx-open" : "sx-word-slot");
    var slot = slots.make(name);
    wrap.appendChild(slot);
    if (name === "opening" && !squarish(slot)) { wrap.classList.add("sx-open-fit"); }
    return wrap;
  }

  // 開場的 SVG 是不是（差不多）正方形：是 → 照舊 220×220；不是（例如 480×250 的橫幅）→ 照 viewBox 的比例放大
  // （splash.css 的 .sx-open-fit；寬最多 min(560px, 92vw)、高最多 60vh）。讀不到比例（HTML、沒有 viewBox）→ 當正方形
  function ratio(svg) {
    var vb = String(svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/);
    var w = vb.length === 4 ? parseFloat(vb[2]) : parseFloat(svg.getAttribute("width"));
    var h = vb.length === 4 ? parseFloat(vb[3]) : parseFloat(svg.getAttribute("height"));
    return w > 0 && h > 0 ? w / h : 1;
  }
  function squarish(slot) {
    try {
      var svg = slot && slot.querySelector ? slot.querySelector("svg") : null;
      if (!svg || svg.parentNode !== slot) { return true; }
      var r = ratio(svg);
      return r > 0.9 && r < 1.1;
    } catch (e) { return true; }
  }

  // 畫面：全部用 createElement＋textContent（不拼 HTML 字串、不寫 inline 樣式）。
  // 門＝role="dialog" 的整片；中間的 S 寶寶（或外觀的開場）是一顆真的 <button>，Tab 不會跑到後面去。
  function build(doc, touch) {
    var splash = el(doc, "div", "sx-splash sx-gate");
    splash.setAttribute("role", "dialog");
    splash.setAttribute("aria-modal", "true");
    splash.setAttribute("aria-label", "SYNOX 開場");
    var stage = el(doc, "div", "sx-stage");
    stage.appendChild(el(doc, "div", "sx-halo"));
    var enter = el(doc, "button", "sx-enter");
    enter.setAttribute("type", "button");
    enter.setAttribute("aria-label", "點一下打開 SYNOX");
    stage.appendChild(enter);
    var opening = themed(doc, "opening");
    if (opening) {                                       // 外觀包的開場：整段換掉，只留光暈、門的按鈕、提示
      enter.classList.add("sx-enter-theme");
      enter.appendChild(opening);
      if (opening.classList.contains("sx-open-fit")) { stage.classList.add("sx-stage-fit"); }
      return finishBuild(doc, splash, stage, enter, touch);
    }
    var mascot = el(doc, "div", "sx-mascot");
    var flip = el(doc, "div", "sx-flip");
    var face = el(doc, "div", "sx-face");
    ["sx-eye l", "sx-eye r", "sx-blush l", "sx-blush r", "sx-smile"].forEach(function (c) {
      face.appendChild(el(doc, "i", c));
    });
    flip.appendChild(face);
    flip.appendChild(el(doc, "div", "sx-logo", "S"));
    mascot.appendChild(flip);
    var sparks = el(doc, "div", "sx-sparks");
    for (var i = 0; i < 6; i++) { sparks.appendChild(el(doc, "i", "sx-spark")); }
    sparks.appendChild(el(doc, "i", "sx-spark star", "✦"));
    sparks.appendChild(el(doc, "i", "sx-spark star", "✦"));
    mascot.appendChild(sparks);
    mascot.appendChild(el(doc, "div", "sx-hi", "嗨！"));
    enter.appendChild(mascot);
    var word = el(doc, "div", "sx-word");
    word.setAttribute("aria-hidden", "true");
    var mark = themed(doc, "wordmark");
    if (mark) { word.appendChild(mark); }
    else { "SYNOX".split("").forEach(function (ch) { word.appendChild(el(doc, "span", "", ch)); }); }
    stage.appendChild(word);
    return finishBuild(doc, splash, stage, enter, touch);
  }

  function finishBuild(doc, splash, stage, enter, touch) {
    var hint = el(doc, "p", "sx-hint", "點一下打開 SYNOX");
    if (!touch) { hint.appendChild(el(doc, "span", "sx-key", "或按 Enter")); }
    stage.appendChild(hint);
    splash.appendChild(stage);
    splash.sxEnter = enter;
    return splash;
  }

  function signal(doc) {
    try {
      var Ev = root.CustomEvent || (typeof CustomEvent === "function" ? CustomEvent : null);
      if (typeof Ev === "function" && doc.dispatchEvent) { doc.dispatchEvent(new Ev(DONE)); }
    } catch (e) { /* 舊瀏覽器：教學會自己再等一下 */ }
  }

  // 打開門。quiet＝減少動態效果（點了直接拿掉，不播放大淡出）；touch＝觸控螢幕（提示不寫「或按 Enter」、不搶焦點）
  function open(doc, quiet, touch) {
    if (current) { return current; }
    var html = doc.documentElement;
    var back = doc.activeElement || null;            // 門關了把焦點還回去（例如左上角的 S）
    var splash = null, leaving = false, done = false;
    var gate = { enter: enter, isOpen: function () { return !done; } };
    current = gate;
    function finish() {
      if (done) { return; }
      done = true;
      if (current === gate) { current = null; }
      html.classList.remove("sx-hold");
      doc.removeEventListener("keydown", onKey, true);
      if (splash && splash.parentNode) { splash.parentNode.removeChild(splash); }
      setTimeout(function () { html.classList.remove("sx-intro"); }, 800);
      try { if (back && back.focus && back !== doc.body) { back.focus({ preventScroll: true }); } } catch (e) { /* 不重要 */ }
      signal(doc);
    }
    function enter() {                               // 點了：後面的內容開始浮上來，門放大淡出
      if (leaving || done) { return; }
      leaving = true;
      html.classList.remove("sx-hold");
      if (quiet || !splash) { finish(); return; }
      splash.classList.add("sx-leave");
      setTimeout(finish, LEAVE);
    }
    function onKey(e) {
      var k = e && e.key;
      if (k === "Enter" || k === " " || k === "Spacebar" || k === "Escape" || k === "Esc") {
        if (e.preventDefault) { e.preventDefault(); }
        enter();
      } else if (k === "Tab") {                      // 門開著的時候焦點只停在門的按鈕上
        if (e.preventDefault) { e.preventDefault(); }
        try { splash.sxEnter.focus({ preventScroll: true }); } catch (err) { /* 不重要 */ }
      }
    }
    try {
      html.classList.add("sx-intro", "sx-hold");
      splash = build(doc, touch);
      if (quiet) { splash.classList.add("sx-still"); }
      splash.addEventListener("click", enter);
      doc.addEventListener("keydown", onKey, true);
      (doc.body || html).appendChild(splash);
      if (!touch) { try { splash.sxEnter.focus({ preventScroll: true }); } catch (e) { /* 不重要 */ } }
    } catch (e) {
      finish();                                      // 畫不出來：直接放行，不能讓人卡在門口
    }
    return gate;
  }

  function isOpen() { return !!(current && current.isOpen()); }

  function start() {
    var d = root.document;
    // 左上角的 S（app.html 的 [data-splash-replay]）：再看一次開場。用事件委派：這支跑的時候按鈕還沒長出來
    d.addEventListener("click", function (e) {
      var t = e.target;
      var btn = t && t.closest ? t.closest("[data-splash-replay]") : null;
      if (!btn || isOpen()) { return; }
      e.preventDefault();
      open(d, calm(), coarse());
    });
    var search = root.location ? root.location.search : "";
    if (!decide(search, read("localStorage", OFF), root.SYNOX_NO_SPLASH)) { return; }
    open(d, calm(), coarse());
  }

  var api = { decide: decide, build: build, open: open, isOpen: isOpen, ratio: ratio,
              OFF: OFF, DONE: DONE, READY_AT: READY_AT, LEAVE: LEAVE };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxSplash = api; start(); }
})(typeof window !== "undefined" ? window : this);
