/* 🔐 安全（設定 → 🔐 安全；ADR 0025）：手機驗證器的設定、備用碼、開關、解鎖。樣式在 static/security.css。
 *
 * - SynoxStepUp.ask()：任何 API 回 403 {code: "stepup"} 時，app.html 的 api() 叫它跳出輸入框；
 *   打對 → POST /api/stepup/unlock → 回 Promise 成功，app.html 把原本的請求重送一次；按取消 → Promise 失敗，不重送。
 * - 設定頁的卡：狀態 → 設定三步（QR＋金鑰文字＋打碼）→ 備用碼（只這一次；勾「我抄好了」才關得掉）→
 *   之後：開關、剩幾組備用碼、產生新的備用碼、關掉驗證器（紅色、要碼）、這個瀏覽器解鎖了沒＋「馬上鎖回去」。
 * - 字一律 textContent；字串集中在 TEXT。app.html 在拿到 /api/me 之後叫 window.SynoxStepUp.init({ api, toast })。
 */
(function (root) {
  "use strict";
  var TEXT = {
    title: "手機驗證器",
    what: "手機上一個會每 30 秒換一組 6 位數的 App（Google Authenticator、Microsoft Authenticator 都可以）。設定好之後，重要的動作要多打這 6 個數字。",
    why: "現在只要有人拿到你的 Telegram 帳號或這台電腦的瀏覽器登入，就能叫 SYNOX 做任何事。加了驗證器，他還得拿到你的手機。",
    skip: "不設也照樣能用，跟現在一樣。只有「從手機打開工具畫面」這類一定要驗證器的功能不能用。",
    ai: "AI 永遠不會、也不能跟你要驗證碼。有東西跟你要 6 位數，而你不是正在自己做危險的動作，就不要給。",
    notSet: "還沒設定",
    setOn: "已設定，危險的動作要先解鎖",
    setOff: "已設定，但危險的動作沒有開保護",
    start: "設定手機驗證器",
    notHere: "請在跑 SYNOX 的那台電腦上設定（打開 SYNOX 網頁 → 設定 → 🔐 安全）。",
    step1: "① 打開手機的驗證器 App → 新增 → 掃描下面的方塊。",
    step2: "② 掃不到的話，選「手動輸入」，打這串字：",
    step3: "③ 打 App 上現在顯示的 6 位數：",
    confirm: "確定",
    protect: "危險的動作也要先解鎖（建議）",
    recoveryTitle: "備用碼（只顯示這一次）",
    recoveryHow: "手機不見時用的 10 組一次性密碼。請抄在紙上，只能在這台電腦的 SYNOX 網頁上用。",
    copied: "我抄好了",
    copy: "複製",
    close: "關閉",
    recoveryLeft: "備用碼還剩 {n} 組",
    newRecovery: "產生新的備用碼",
    disable: "關掉手機驗證器",
    disableAsk: "要關掉的話，打一組 App 上的 6 位數（或一組備用碼）：",
    unlocked: "這個瀏覽器已解鎖，還剩 {m} 分鐘",
    lockedHere: "這個瀏覽器還沒解鎖",
    lockNow: "馬上鎖回去",
    unlockNow: "解鎖",
    askTitle: "🔐 這個動作要先解鎖",
    askHow: "打手機驗證器上現在的 6 位數。解鎖之後 {m} 分鐘內不用再打。",
    askOk: "解鎖並繼續",
    askCancel: "取消",
    codeLabel: "6 位數",
    wrong: "不對：",
    done: "好了",
    failed: "沒有成功：",
    // 手機入口（ADR 0026）：總開關與通道程式的核准（都要先解鎖）
    remoteTitle: "📱 手機入口",
    remoteSwitch: "允許開手機入口（每次開還是要你本人＋一組新的驗證碼）",
    remoteNeedStepup: "要先設定手機驗證器，才能用手機入口。",
    binaryTitle: "通道程式（cloudflared）",
    binaryNone: "還沒核准。請自己安裝 cloudflared（SYNOX 不替你下載），再按下面的按鈕。",
    binaryCheck: "請跟官方發佈頁上的雜湊對一下，一樣才按核准。檔案一改（例如自己更新了）就要重新核准。",
    binaryApprove: "我核對過了，核准這個檔",
    binaryPath: "路徑：",
    binarySize: "大小：",
    binarySha: "SHA-256：",
    binarySigner: "簽署者：讀不到，請自己對雜湊。"
  };

  /* 純邏輯（tests/js/test_security.js）：deps = { api(method, path, body) → Promise, prompt() → Promise<碼或 null> } */
  function makeAsker(deps) {
    var waiting = null;
    function ask() {
      if (waiting) { return waiting; }                 // 同時好幾個請求被擋：只問一次
      waiting = new Promise(function (resolve, reject) {
        function round(hint) {
          deps.prompt(hint || "").then(function (code) {
            if (code === null || code === undefined) { waiting = null; reject(new Error("cancel")); return; }
            deps.api("POST", "/api/stepup/unlock", { code: String(code) }).then(function () {
              waiting = null;
              resolve();
            }, function (err) { round(TEXT.wrong + (err && err.message ? err.message : "")); });
          });
        }
        round("");
      });
      return waiting;
    }
    return { ask: ask };
  }

  function isStepUp(status, data) {
    return status === 403 && !!data && data.code === "stepup";
  }

  function statusLine(s) {
    if (!s.enrolled) { return TEXT.notSet; }
    return s.protect_danger ? TEXT.setOn : TEXT.setOff;
  }

  function fill(text, vars) {
    return String(text).replace(/\{(\w+)\}/g, function (_m, k) { return vars[k] === undefined ? "" : String(vars[k]); });
  }

  /* 畫面 ─────────────────────────────────────────────────────────── */
  var deps = null;
  var asker = null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }

  function drawQr(canvas, grid) {
    var n = grid.length, pad = 4, scale = 5;
    canvas.width = canvas.height = (n + pad * 2) * scale;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#000";
    for (var y = 0; y < n; y++) {
      for (var x = 0; x < n; x++) {
        if (grid[y].charAt(x) === "1") { ctx.fillRect((x + pad) * scale, (y + pad) * scale, scale, scale); }
      }
    }
  }

  function codeBox() {
    var i = el("input", "stepup-code");
    i.type = "text";
    i.inputMode = "numeric";
    i.autocomplete = "one-time-code";
    i.maxLength = 12;
    i.setAttribute("aria-label", TEXT.codeLabel);
    return i;
  }

  function prompt(hint) {
    return new Promise(function (resolve) {
      var back = el("div", "stepup-modal");
      var box = el("div", "stepup-box");
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      box.appendChild(el("h3", "", TEXT.askTitle));
      box.appendChild(el("p", "", fill(TEXT.askHow, { m: (deps && deps.minutes) || 15 })));
      if (hint) { box.appendChild(el("p", "stepup-err", hint)); }
      var input = codeBox();
      box.appendChild(input);
      var row = el("div", "row");
      var ok = el("button", "", TEXT.askOk);
      var no = el("button", "ghost", TEXT.askCancel);
      row.appendChild(ok);
      row.appendChild(no);
      box.appendChild(row);
      back.appendChild(box);
      document.body.appendChild(back);
      input.focus();
      function done(v) { back.parentNode.removeChild(back); resolve(v); }
      ok.addEventListener("click", function () { done(input.value.trim()); });
      no.addEventListener("click", function () { done(null); });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { done(input.value.trim()); }
        if (e.key === "Escape") { done(null); }
      });
    });
  }

  function showRecovery(card, codes, after) {
    var box = el("div", "stepup-recovery");
    box.appendChild(el("h3", "", TEXT.recoveryTitle));
    box.appendChild(el("p", "sub", TEXT.recoveryHow));
    var list = el("pre", "stepup-codes", codes.join("\n"));
    box.appendChild(list);
    var row = el("div", "row");
    var copy = el("button", "ghost", TEXT.copy);
    copy.addEventListener("click", function () {
      if (navigator.clipboard) { navigator.clipboard.writeText(codes.join("\n")); }
    });
    var label = el("label", "");
    var check = el("input", "");
    check.type = "checkbox";
    label.appendChild(check);
    label.appendChild(document.createTextNode(" " + TEXT.copied));
    var close = el("button", "", TEXT.close);
    close.disabled = true;
    check.addEventListener("change", function () { close.disabled = !check.checked; });
    close.addEventListener("click", function () { after(); });
    row.appendChild(copy);
    row.appendChild(label);
    row.appendChild(close);
    box.appendChild(row);
    card.textContent = "";
    card.appendChild(box);
  }

  function render(s) {
    var card = document.getElementById("set-security-body");
    if (!card) { return; }
    card.textContent = "";
    card.appendChild(el("p", "stepup-state", statusLine(s)));
    var msg = el("p", "msgline");
    if (!s.enrolled) {
      [TEXT.what, TEXT.why, TEXT.skip].forEach(function (t) { card.appendChild(el("p", "sub", t)); });
      if (!s.can_enroll_here) {
        card.appendChild(el("p", "stepup-err", s.why_not || TEXT.notHere));
        return;
      }
      var go = el("button", "", TEXT.start);
      go.addEventListener("click", function () { begin(card); });
      card.appendChild(go);
      card.appendChild(el("p", "sub", TEXT.ai));
      return;
    }
    var here = el("p", "", s.unlocked ? fill(TEXT.unlocked, { m: Math.ceil(s.unlock_left_s / 60) }) : TEXT.lockedHere);
    card.appendChild(here);
    var row = el("div", "row");
    if (s.unlocked) {
      var lock = el("button", "ghost", TEXT.lockNow);
      lock.addEventListener("click", function () { deps.api("POST", "/api/stepup/lock", {}).then(load); });
      row.appendChild(lock);
    } else {
      var un = el("button", "ghost", TEXT.unlockNow);
      un.addEventListener("click", function () { asker.ask().then(load, function () {}); });
      row.appendChild(un);
    }
    card.appendChild(row);
    var label = el("label", "stepup-toggle");
    var box = el("input", "");
    box.type = "checkbox";
    box.checked = !!s.protect_danger;
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + TEXT.protect));
    box.addEventListener("change", function () {
      deps.api("POST", "/api/stepup/protect", { on: box.checked }).then(load, function (e) {
        msg.textContent = TEXT.failed + e.message;
        load();
      });
    });
    card.appendChild(label);
    card.appendChild(el("p", "sub", fill(TEXT.recoveryLeft, { n: s.recovery_left })));
    var more = el("div", "row");
    var fresh = el("button", "ghost", TEXT.newRecovery);
    fresh.addEventListener("click", function () {
      prompt("").then(function (code) {
        if (code === null) { return; }
        deps.api("POST", "/api/stepup/recovery", { code: code }).then(function (d) {
          showRecovery(card, d.recovery, load);
        }, function (e) { msg.textContent = TEXT.failed + e.message; });
      });
    });
    var off = el("button", "danger", TEXT.disable);
    off.addEventListener("click", function () {
      prompt(TEXT.disableAsk).then(function (code) {
        if (code === null) { return; }
        deps.api("POST", "/api/stepup/disable", { code: code }).then(load, function (e) {
          msg.textContent = TEXT.failed + e.message;
        });
      });
    });
    more.appendChild(fresh);
    more.appendChild(off);
    card.appendChild(more);
    card.appendChild(msg);
  }

  function begin(card) {
    deps.api("POST", "/api/stepup/begin", {}).then(function (d) {
      card.textContent = "";
      card.appendChild(el("p", "", TEXT.step1));
      if (d.qr) {
        var canvas = el("canvas", "stepup-qr");
        drawQr(canvas, d.qr);
        card.appendChild(canvas);
      }
      card.appendChild(el("p", "", TEXT.step2));
      card.appendChild(el("pre", "stepup-secret", d.secret));
      card.appendChild(el("p", "", TEXT.step3));
      var input = codeBox();
      card.appendChild(input);
      var label = el("label", "stepup-toggle");
      var protect = el("input", "");
      protect.type = "checkbox";
      protect.checked = true;                          // 擁有者決定：預設勾著（ADR 0025 第 3 題）
      label.appendChild(protect);
      label.appendChild(document.createTextNode(" " + TEXT.protect));
      card.appendChild(label);
      var ok = el("button", "", TEXT.confirm);
      var msg = el("p", "msgline");
      ok.addEventListener("click", function () {
        deps.api("POST", "/api/stepup/confirm", { code: input.value.trim(), protect: protect.checked }).then(function (r) {
          showRecovery(card, r.recovery, load);
        }, function (e) { msg.textContent = TEXT.wrong + e.message; });
      });
      card.appendChild(ok);
      card.appendChild(msg);
    }, function (e) { if (deps.toast) { deps.toast(TEXT.failed + e.message); } });
  }

  function load() {
    return deps.api("GET", "/api/stepup").then(function (s) {
      deps.minutes = s.minutes;
      render(s);
      loadRemote(s);
      return s;
    });
  }

  function loadRemote(s) {
    var card = document.getElementById("set-security-body");
    if (!card || !deps) { return; }
    deps.api("GET", "/api/remote").then(function (r) { card.appendChild(renderRemote(r, s)); }, function () {});
  }

  function renderRemote(r, s) {
    var box = el("div", "stepup-remote");
    box.appendChild(el("h3", "", TEXT.remoteTitle));
    if (!s.enrolled) { box.appendChild(el("p", "sub", TEXT.remoteNeedStepup)); return box; }
    var label = el("label", "stepup-toggle");
    var on = el("input", "");
    on.type = "checkbox";
    on.checked = !!r.enabled;
    label.appendChild(on);
    label.appendChild(document.createTextNode(" " + TEXT.remoteSwitch));
    on.addEventListener("change", function () { deps.api("POST", "/api/remote/enabled", { on: on.checked }).then(load, load); });
    box.appendChild(label);
    box.appendChild(el("h3", "", TEXT.binaryTitle));
    if (r.binary) {
      box.appendChild(el("p", "", TEXT.binaryPath + r.binary.path));
      box.appendChild(el("p", "", TEXT.binarySize + r.binary.size));
      box.appendChild(el("pre", "stepup-secret", TEXT.binarySha + r.binary.sha256));
    } else {
      box.appendChild(el("p", "sub", TEXT.binaryNone));
    }
    box.appendChild(el("p", "sub", TEXT.binaryCheck));
    box.appendChild(el("p", "sub", TEXT.binarySigner));
    var approve = el("button", "ghost", TEXT.binaryApprove);
    approve.addEventListener("click", function () { deps.api("POST", "/api/remote/binary/approve", {}).then(load, load); });
    box.appendChild(approve);
    return box;
  }

  function init(d) {
    deps = d;
    asker = makeAsker({ api: d.api, prompt: prompt });
    load();
  }

  var exported = {
    TEXT: TEXT, makeAsker: makeAsker, isStepUp: isStepUp, statusLine: statusLine, fill: fill, init: init,
    ask: function () { return asker ? asker.ask() : Promise.reject(new Error("not ready")); },
    reload: function () { return deps ? load() : null; }
  };
  if (typeof module === "object" && module && module.exports) { module.exports = exported; }
  else { root.SynoxStepUp = exported; }
})(typeof window !== "undefined" ? window : this);
