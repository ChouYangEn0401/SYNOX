/* SYNOX 工具服務的共用元件（ADR 0024、計畫 C4–C6.1、C11、WP3）：工具畫面的入口頁第一個 <script> 一定是它（/_synox/kit.js）。
 *
 * - 進門：網址的 #t=<票> → 先把網址改乾淨（票不留在網址列與歷史）→ POST /api/enter → token 放在這個分頁的 sessionStorage。
 *   沒有票就用分頁裡存的 token → GET /api/me。都沒有 → 遮罩「請從 SYNOX 打開這個工具。」（一個請求都不送）
 * - 每個 /api/ 請求帶 X-SYNOX-App 標頭、credentials: "omit"（app 的位址不用瀏覽器自動帶的登入資料，也不帶過去）。
 * - 「人還在」：只有在使用者真的動了（滑鼠、鍵盤、點、捲、滑），分頁在眼前、而且距離上次超過 alive_every_s 秒，才送一次 /api/alive。
 *   沒有定時器、沒有輪詢：沒有輸入就什麼都不送。
 * - 對外只有 window.SynoxApp。字一律 textContent；字串集中在 TEXT。不碰瀏覽器自動帶的登入資料、不註冊背景程式、不連外面的網址。
 * - 手機入口（ADR 0026）：/api/me 的 remote 是 true 時不畫「回 SYNOX」、不能匯出（不送任何請求）、頁首多「幾點自動關」與「關閉手機入口」。
 * 這條頁首列是方便，不是保證：工具的畫面程式跟這個檔在同一頁，它可以不照做（ADR 0024 §3.5）。可信的狀態在 SYNOX 主機台。
 */
(function (root) {
  "use strict";
  var TEXT = {
    fromSynox: "請從 SYNOX 打開這個工具。",
    again: "請從 SYNOX 再打開一次。",
    closed: "這個服務已經關了。回 SYNOX 再開一次就好，資料都在。",
    back: "回 SYNOX",
    leave: "離開",
    closeService: "關閉服務",
    closeRemote: "關閉手機入口",
    closeAsk: "要關掉這個工具的服務嗎？資料都在，要用再從 SYNOX 開。",
    closeRemoteAsk: "要關掉手機入口嗎？資料都在。",
    closedNow: "關好了。",
    note: "這是 SYNOX 在這台電腦上開的工具畫面，不用的時候可以關掉。",
    remoteNote: "📱 手機入口",
    remoteUntil: "{t} 自動關閉",
    ok: "確定",
    cancel: "取消",
    submit: "送出",
    failed: "沒有成功：",
    required: "這一欄一定要填",
    noExport: "這裡不能匯出。"
  };
  var ACTIVITY = ["mousemove", "keydown", "pointerdown", "wheel", "scroll", "touchstart"];
  var TOKEN_KEY = "synox.app.token";
  var BUILT_IN_CONSOLE = [/*{{CONSOLE_URL}}*/][0] || "";

  function create(env) {
    var doc = env.document;
    var state = { token: "", me: null, readyFns: [], started: false, lastSent: 0, masked: null, bar: null };
    var consoleUrl = env.consoleUrl !== undefined ? env.consoleUrl : BUILT_IN_CONSOLE;

    function now() { return env.now ? env.now() : Date.now(); }

    function el(tag, cls, text) {
      var e = doc.createElement(tag);
      if (cls) { e.className = cls; }
      if (text !== undefined && text !== null) { e.textContent = String(text); }
      return e;
    }

    function clear(node) {
      while (node && node.firstChild) { node.removeChild(node.firstChild); }
      return node;
    }

    function fill(text, vars) {
      return String(text).replace(/\{(\w+)\}/g, function (_m, k) { return vars[k] === undefined ? "" : String(vars[k]); });
    }

    function storage(op, value) {
      try {
        if (op === "get") { return env.sessionStorage.getItem(TOKEN_KEY) || ""; }
        if (op === "set") { env.sessionStorage.setItem(TOKEN_KEY, value); }
        if (op === "del") { env.sessionStorage.removeItem(TOKEN_KEY); }
      } catch (_e) { /* 私密視窗等：沒有就算了 */ }
      return "";
    }

    function remote() { return !!(state.me && state.me.remote); }

    function mask(text) {
      if (state.masked) { state.masked.firstChild.textContent = text; return; }
      var m = el("div", "synox-mask");
      m.setAttribute("role", "alertdialog");
      m.appendChild(el("p", "", text));
      if (consoleUrl && !remote()) {
        var a = el("a", "btn primary", TEXT.back);
        a.href = consoleUrl;
        a.rel = "noopener noreferrer";
        m.appendChild(a);
      }
      doc.body.appendChild(m);
      state.masked = m;
    }

    function toast(text, tone) {
      var t = el("div", "synox-toast" + (tone ? " " + tone : ""), text);
      t.setAttribute("role", "status");
      doc.body.appendChild(t);
      if (env.later) { env.later(function () { if (t.parentNode) { t.parentNode.removeChild(t); } }, 4000); }
      return t;
    }

    function confirmBox(text, button) {
      return new Promise(function (resolve) {
        var back = el("div", "synox-modal");
        var box = el("div", "card");
        box.setAttribute("role", "dialog");
        box.setAttribute("aria-modal", "true");
        box.appendChild(el("p", "", text));
        var row = el("div", "row");
        var ok = el("button", "btn primary", button || TEXT.ok);
        var no = el("button", "btn ghost", TEXT.cancel);
        row.appendChild(ok);
        row.appendChild(no);
        box.appendChild(row);
        back.appendChild(box);
        doc.body.appendChild(back);
        function done(v) { if (back.parentNode) { back.parentNode.removeChild(back); } resolve(v); }
        ok.addEventListener("click", function () { done(true); });
        no.addEventListener("click", function () { done(false); });
      });
    }

    /* 網路 ─────────────────────────────────────────────────────────── */
    function request(method, path, body, opts) {
      opts = opts || {};
      var init = { method: method, credentials: "omit", headers: {} };
      if (state.token) { init.headers["X-SYNOX-App"] = state.token; }
      if (body !== undefined) {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(body);
      }
      return env.fetch(path, init).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (r.status === 401) {
            if (!opts.silent) { forget(); mask(TEXT.again); }
            throw { code: "login", error: TEXT.again };
          }
          if (!r.ok || !data || data.ok === false) {
            var err = data && data.code ? data : { code: "error", error: "HTTP " + r.status };
            err.status = r.status;
            throw err;
          }
          return data;
        });
      }, function () {
        if (!opts.silent) { mask(TEXT.closed); }
        throw { code: "network", error: TEXT.closed };
      });
    }

    function forget() {
      state.token = "";
      storage("del");
    }

    function used() { state.lastSent = now(); }

    /* 啟動 ─────────────────────────────────────────────────────────── */
    function start() {
      if (state.started) { return Promise.resolve(); }
      state.started = true;
      var hash = String((env.location && env.location.hash) || "");
      var m = /(?:^#|&)t=([A-Za-z0-9_-]{16,200})/.exec(hash);
      if (m) {
        env.history.replaceState(null, "", "/");           // 票不留在網址列與歷史（先做，再送請求）
        return request("POST", "/api/enter", { ticket: m[1] }).then(function (d) {
          state.token = d.token;
          storage("set", d.token);
          return entered(d.me);
        }, function () { forget(); mask(TEXT.fromSynox); });
      }
      state.token = storage("get");
      if (!state.token) { mask(TEXT.fromSynox); return Promise.resolve(); }
      return request("GET", "/api/me").then(entered, function (e) {
        forget();
        if (e && e.code !== "network") { mask(TEXT.fromSynox); }
      });
    }

    function entered(me) {
      state.me = me;
      used();
      drawBar();
      listen();
      var fns = state.readyFns.splice(0);
      fns.forEach(function (fn) { run(fn); });
    }

    function ctx() {
      var me = state.me;
      return { me: me, app: me.app, actions: me.actions || {}, reads: me.reads || [], exports: me.exports || {} };
    }

    function run(fn) {
      try { fn(ctx()); } catch (e) { toast(TEXT.failed + (e && e.message ? e.message : "")); }
    }

    function ready(fn) {
      if (state.me) { run(fn); } else { state.readyFns.push(fn); }
    }

    /* 頁首列 ───────────────────────────────────────────────────────── */
    function drawBar() {
      var me = state.me;
      var bar = el("div", "synox-bar");
      bar.appendChild(el("strong", "", (me.app && (me.app.app_title || me.app.title)) || ""));
      bar.appendChild(el("span", "muted", (me.user && me.user.name) || ""));
      if (remote()) {
        bar.appendChild(el("span", "badge write", TEXT.remoteNote));
        if (me.remote_until) { bar.appendChild(el("span", "muted", fill(TEXT.remoteUntil, { t: fmt.time(me.remote_until) }))); }
      } else if (me.console_url) {
        var a = el("a", "", TEXT.back);
        a.href = me.console_url;
        a.rel = "noopener noreferrer";
        bar.appendChild(a);
      }
      var leave = el("button", "btn ghost", TEXT.leave);
      leave.addEventListener("click", function () {
        request("POST", "/api/leave", {}, { silent: true }).catch(function () {});
        forget();
        mask(TEXT.again);
      });
      bar.appendChild(leave);
      if (me.user && me.user.owner) {
        var close = el("button", "btn danger", remote() ? TEXT.closeRemote : TEXT.closeService);
        close.addEventListener("click", function () {
          confirmBox(remote() ? TEXT.closeRemoteAsk : TEXT.closeAsk, remote() ? TEXT.closeRemote : TEXT.closeService)
            .then(function (yes) {
              if (!yes) { return; }
              request("POST", "/api/close-service", {}, { silent: true }).then(function () { mask(TEXT.closedNow); },
                function () { mask(TEXT.closed); });
            });
        });
        bar.appendChild(close);
      }
      bar.appendChild(el("small", "muted", TEXT.note));
      doc.body.insertBefore(bar, doc.body.firstChild);
      state.bar = bar;
    }

    /* 人還在（C11）：只在真的有輸入時送 ───────────────────────────────── */
    function listen() {
      ACTIVITY.forEach(function (type) { doc.addEventListener(type, onActivity, { passive: true }); });
    }

    function onActivity(e) {
      if (!e || e.isTrusted !== true || doc.visibilityState !== "visible" || !state.token) { return; }
      var every = ((state.me && state.me.alive_every_s) || 60) * 1000;
      if (now() - state.lastSent < every) { return; }
      used();
      try {
        env.fetch("/api/alive", { method: "POST", credentials: "omit",
                                  headers: { "X-SYNOX-App": state.token, "Content-Type": "application/json" },
                                  body: "{}" }).catch(function () {});
      } catch (_e) { /* 失敗不重試、不顯示 */ }
    }

    /* 讀、動作、表單、匯出 ─────────────────────────────────────────── */
    function query(params) {
      var keys = Object.keys(params || {});
      return keys.length ? "?" + keys.map(function (k) {
        return encodeURIComponent(k) + "=" + encodeURIComponent(String(params[k]));
      }).join("&") : "";
    }

    function read(name, params) {
      return request("GET", "/api/read/" + encodeURIComponent(name) + query(params)).then(function (d) {
        used();
        return d.data;
      }, function (e) {
        if (e.code !== "login" && e.code !== "network") { toast(e.error || TEXT.failed); }
        throw e;
      });
    }

    function cleanValues(values) {
      var out = {};
      Object.keys(values || {}).forEach(function (k) {
        var v = values[k];
        if (v === null || v === undefined || v === "") { return; }
        out[k] = String(v);
      });
      return out;
    }

    function act(name, values, opts) {
      opts = opts || {};
      var path = "/api/do/" + encodeURIComponent(name);
      var clean = cleanValues(values);
      function fail(e) {
        if (!opts.quiet && e.code !== "login" && e.code !== "network" && e.code !== "cancelled") {
          toast(e.error || TEXT.failed, "bad");
        }
        throw e;
      }
      return request("POST", path, { values: clean }).then(function (d) { used(); return d.data; }, function (e) {
        if (e.code !== "confirm" || !e.confirm) { return fail(e); }
        return confirmBox(e.confirm.text, e.confirm.button).then(function (yes) {
          if (!yes) { throw { code: "cancelled" }; }
          return request("POST", path, { values: clean, confirmed: true }).then(function (d) { used(); return d.data; }, fail);
        });
      });
    }

    function form(actionName, opts) {
      opts = opts || {};
      var spec = ((state.me && state.me.actions) || {})[actionName] || { fields: [] };
      var f = el("form", "card synox-form");
      var inputs = {}, notes = {};
      (spec.fields || []).forEach(function (field) {
        var wrap = el("label", "field");
        wrap.appendChild(el("span", "", field.label || field.name));
        var input;
        if (field.choices && field.choices.length) {
          input = el("select");
          field.choices.forEach(function (c) { var o = el("option", "", c); o.value = c; input.appendChild(o); });
        } else {
          input = el("input");
          input.type = (field.kind === "int" || field.kind === "number") ? "number" : "text";
        }
        input.name = field.name;
        if (field.required) { input.required = true; }
        var pre = opts.values && opts.values[field.name] !== undefined ? opts.values[field.name] : field.default;
        if (pre !== undefined && pre !== null && pre !== "") { input.value = String(pre); }
        wrap.appendChild(input);
        var note = el("small", "bad");
        wrap.appendChild(note);
        inputs[field.name] = input;
        notes[field.name] = note;
        f.appendChild(wrap);
      });
      var go = el("button", "btn primary", opts.submitText || spec.summary || TEXT.submit);
      go.type = "submit";
      f.appendChild(go);
      f.addEventListener("submit", function (e) {
        if (e && e.preventDefault) { e.preventDefault(); }
        var values = {}, missing = false;
        Object.keys(inputs).forEach(function (k) {
          notes[k].textContent = "";
          values[k] = inputs[k].value;
          if (inputs[k].required && !String(inputs[k].value || "").trim()) { notes[k].textContent = TEXT.required; missing = true; }
        });
        if (missing) { return; }
        act(actionName, values, { quiet: true }).then(function (data) {
          if (opts.onDone) { opts.onDone(data); }
        }, function (err) {
          if (err && err.fields) {
            Object.keys(err.fields).forEach(function (k) { if (notes[k]) { notes[k].textContent = err.fields[k]; } });
          } else if (err && err.code !== "cancelled" && err.code !== "login" && err.code !== "network") {
            toast(err.error || TEXT.failed, "bad");
          }
        });
      });
      return f;
    }

    function download(name, params) {
      var info = ((state.me && state.me.exports) || {})[name];
      if (remote() || !info || !info.available) {
        toast((info && info.reason) || TEXT.noExport);
        return Promise.resolve(false);
      }
      var path = "/api/export/" + encodeURIComponent(name);
      var pairs = [["t", state.token]];
      Object.keys(params || {}).forEach(function (k) { pairs.push([k, String(params[k])]); });
      var body = pairs.map(function (p) { return encodeURIComponent(p[0]) + "=" + encodeURIComponent(p[1]); }).join("&");
      return env.fetch(path, { method: "POST", credentials: "omit",
                               headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body })
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return [r, d]; }); })
        .then(function (pair) {
          var d = pair[1];
          if (pair[0].status === 401) { forget(); mask(TEXT.again); return false; }
          if (d.code !== "confirm" || !d.confirm) { toast(d.error || TEXT.failed, "bad"); return false; }
          return confirmBox(d.confirm.text, d.confirm.button).then(function (yes) {
            if (!yes) { return false; }
            var f = el("form");
            f.method = "post";
            f.action = path;
            pairs.concat([["confirmed", "1"]]).forEach(function (p) {
              var i = el("input");
              i.type = "hidden";
              i.name = p[0];
              i.value = p[1];
              f.appendChild(i);
            });
            doc.body.appendChild(f);
            f.submit();
            doc.body.removeChild(f);
            used();
            return true;
          });
        }, function () { mask(TEXT.closed); return false; });
    }

    function keep() { return request("POST", "/api/keep", {}).then(function () { used(); return true; }); }

    var fmt = {
      number: function (n) { var x = Number(n); return isFinite(x) ? x.toLocaleString("zh-Hant") : String(n); },
      date: function (iso) { return String(iso || "").replace("T", " ").slice(0, 16); },
      time: function (iso) { return String(iso || "").replace(/^.*T/, "").slice(0, 5); }
    };

    return { start: start, ready: ready, read: read, act: act, form: form, download: download, keep: keep,
             toast: toast, confirmBox: confirmBox, el: el, clear: clear, fmt: fmt, TEXT: TEXT,
             _state: state, _onActivity: onActivity };
  }

  var api = { create: create, TEXT: TEXT, ACTIVITY: ACTIVITY };
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    var kit = create({ document: root.document, fetch: root.fetch.bind(root), sessionStorage: root.sessionStorage,
                       history: root.history, location: root.location,
                       later: function (fn, ms) { root.setTimeout(fn, ms); } });
    root.SynoxApp = { ready: kit.ready, read: kit.read, act: kit.act, form: kit.form, download: kit.download,
                      keep: kit.keep, toast: kit.toast, confirmBox: kit.confirmBox, el: kit.el, clear: kit.clear,
                      fmt: kit.fmt };
    kit.start();
  }
})(typeof window !== "undefined" ? window : this);
