/* 開場動畫（樣式在 static/splash.css；說明與時間表：docs/ui/motion-notes.md）。
 *
 * 這是一個可拆卸的零件（照 ISDPCS fireworks.js 的做法）：只碰畫面，不讀資料、不打 API、不知道誰登入了。
 * 要拿掉 → 刪 app.html 裡 splash.js、splash.css 那兩行 include。壞掉也不會擋住登入或對話：
 * 整段包在 try 裡、最晚 SAFETY 毫秒一定收掉；沒有 JS 時 .sx-splash 自己的 CSS 淡出也會讓它消失。
 *
 * 什麼時候播（decide）：
 *   - 系統開了「減少動態效果」→ 永遠不播
 *   - 網址有 ?splash=0 → 不播；?splash=1 → 重播（預覽的「重播開場」）
 *   - localStorage 的 synox.splash 是 "off" → 不播（使用者自己關掉）
 *   - 其他：同一個分頁的工作階段（sessionStorage）只播第一次；登入前後、重新整理都不會再播
 */
(function (root) {
  "use strict";
  var SEEN = "synox.splash.seen";      // sessionStorage：這個分頁播過了
  var OFF = "synox.splash";            // localStorage："off"＝不要開場
  var OUT_AT = 1250;                   // 開始淡出（跟 splash.css 的 1.25s 對齊）
  var TOTAL = 1700;                    // 淡出結束、拿掉
  var SAFETY = 2600;                   // 不管發生什麼，這時候一定收掉

  function decide(search, seen, off, calm) {
    var m = /[?&]splash=([01])(?:&|#|$)/.exec(search || "");
    if (calm) { return false; }
    if (m) { return m[1] === "1"; }
    if (off === "off") { return false; }
    return seen !== "1";
  }

  function read(kind, key) {
    try { var s = root[kind]; return s ? s.getItem(key) : null; } catch (e) { return null; }
  }
  function write(kind, key, value) {
    try { var s = root[kind]; if (s) { s.setItem(key, value); } } catch (e) { /* 私密視窗、file:// 之類：播就好，不記 */ }
  }
  function calm() {
    try { return !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches); }
    catch (e) { return false; }
  }

  function el(doc, tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) { e.className = cls; }
    if (text) { e.textContent = text; }
    return e;
  }

  // 畫面：全部用 createElement＋textContent（不拼 HTML 字串、不寫 inline 樣式）
  function build(doc) {
    var splash = el(doc, "div", "sx-splash");
    splash.setAttribute("aria-hidden", "true");          // 純裝飾；按任何鍵或點一下就略過
    var stage = el(doc, "div", "sx-stage");
    stage.appendChild(el(doc, "div", "sx-halo"));
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
    stage.appendChild(mascot);
    var word = el(doc, "div", "sx-word");
    "SYNOX".split("").forEach(function (ch) { word.appendChild(el(doc, "span", "", ch)); });
    stage.appendChild(word);
    var dots = el(doc, "div", "sx-dots");
    for (var j = 0; j < 3; j++) { dots.appendChild(el(doc, "i")); }
    stage.appendChild(dots);
    splash.appendChild(stage);
    splash.appendChild(el(doc, "p", "sx-hint", "點一下或按任意鍵略過"));
    return splash;
  }

  function play(doc) {
    var html = doc.documentElement;
    var splash = null, released = false, done = false;
    function release() {                     // 後面的內容開始進場
      if (released) { return; }
      released = true;
      html.classList.remove("sx-hold");
    }
    function finish() {
      if (done) { return; }
      done = true;
      release();
      doc.removeEventListener("keydown", skip, true);
      if (splash && splash.parentNode) { splash.parentNode.removeChild(splash); }
      setTimeout(function () { html.classList.remove("sx-intro"); }, 800);
    }
    function skip() {
      if (done || !splash) { return; }
      splash.classList.add("sx-skip");
      release();
      setTimeout(finish, 220);
    }
    setTimeout(finish, SAFETY);       // 先排好保險，下面就算出錯也收得掉
    try {
      html.classList.add("sx-intro", "sx-hold");
      splash = build(doc);
      splash.addEventListener("click", skip);
      doc.addEventListener("keydown", skip, true);
      (doc.body || html).appendChild(splash);
      setTimeout(release, OUT_AT);
      setTimeout(finish, TOTAL);
    } catch (e) {
      finish();
    }
  }

  function start() {
    var search = root.location ? root.location.search : "";
    if (!decide(search, read("sessionStorage", SEEN), read("localStorage", OFF), calm())) { return; }
    write("sessionStorage", SEEN, "1");
    play(root.document);
  }

  var api = { decide: decide, build: build, play: play, SEEN: SEEN, OFF: OFF, OUT_AT: OUT_AT, TOTAL: TOTAL, SAFETY: SAFETY };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxSplash = api; start(); }
})(typeof window !== "undefined" ? window : this);
