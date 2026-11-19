/* 左下角的使用者選單（點使用者卡片打開；手機是上方列的頭像）＋「🔄 重新啟動 SYNOX」。樣式在 static/usermenu.css。
 *
 * - 選單（role=menu）：上面是狀態（● SYNOX 運作中 · 已開 N 小時、版本、名字與角色），下面一列一列的 menuitem：
 *   🔄 重新啟動 SYNOX（只有擁有者；要重開才生效的設定改了就有小點）、🔔 通知、⚙️ 設定、🎨 換外觀、❓ 遇到問題？、↪ 登出。
 *   Esc／點外面關；上下鍵、Home／End 移動；Tab 在選單裡繞（不會跑出去）；關掉時焦點回到卡片。
 * - 重新啟動：先問（自己的確認框）→ POST /api/settings/restart → 蓋一層「重新啟動中…」→ 每 1.5 秒問 GET /alive，
 *   開機代號（boot）換了＝新的那支起來了 → 重新整理。等太久就說明下一步。伺服器那一半在 web/restart.py。
 * - 側欄上方的 ⟳、聊天通道黃色提示的「立即重新啟動」都走同一個 restart()。
 * 字一律 textContent；字串集中在 TEXT。app.html 拿到 /api/me 之後叫 window.SynoxUserMenu.init({ api, toast, me, logout })。
 */
(function (root) {
  "use strict";
  var TEXT = {
    running: "SYNOX 運作中",
    justNow: "剛開好",
    minutes: "已開 {n} 分鐘",
    hours: "已開 {n} 小時",
    days: "已開 {d} 天",
    daysHours: "已開 {d} 天 {h} 小時",
    version: "v{v}",
    owner: "擁有者",
    roles: { admin: "管理員", member: "成員", guest: "訪客", owner: "擁有者" },
    restart: "重新啟動 SYNOX",
    restartPending: "重新啟動 SYNOX（有設定要重開才生效）",
    askTitle: "重新啟動 SYNOX？",
    askBecause: "重開之後會生效：",
    askOk: "重新啟動",
    cancel: "取消",
    cantTitle: "沒辦法從網頁重新啟動",
    gotIt: "知道了",
    waitTitle: "等一下再重開",
    waitText: "剛剛才重新啟動過，為了避免一直重開，請 {s} 秒後再試。",
    working: "重新啟動中…",
    workingSub: "SYNOX 正在關掉、再自己開起來（大約 10～30 秒）。好了這一頁會自己重新整理，不用動。",
    waited: "已經等了 {s} 秒…",
    back: "好了！重新整理中…",
    slowTitle: "SYNOX 還沒回來",
    slow: "等了 {s} 秒還沒好。電腦比較忙時會久一點；也可能沒開成功：雙擊桌面的 SYNOX 捷徑就會開起來。還是不行的話，到「遇到問題？」告訴我們。",
    waitMore: "再等一下",
    reload: "重新整理",
    failed: "沒有重新啟動：{e}"
  };
  var POLL_MS = 1500;
  var TIMEOUT_MS = 90000;

  function fmt(s, o) { return String(s).replace(/\{(\w+)\}/g, function (_, k) { return o[k] === undefined ? "" : o[k]; }); }

  /* ── 純函式（tests/js/test_usermenu.js）──────────────────────────── */
  function uptimeText(seconds) {
    var s = Math.max(0, Math.floor(Number(seconds) || 0));
    if (s < 60) { return TEXT.justNow; }
    if (s < 3600) { return fmt(TEXT.minutes, { n: Math.floor(s / 60) }); }
    if (s < 86400) { return fmt(TEXT.hours, { n: Math.floor(s / 3600) }); }
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
    return h ? fmt(TEXT.daysHours, { d: d, h: h }) : fmt(TEXT.days, { d: d });
  }
  function statusLine(seconds) { return TEXT.running + " · " + uptimeText(seconds); }
  function whoLines(me) {
    me = me || {};
    var name = me.username ? String(me.username) : "id " + me.id;
    var role = me.owner ? TEXT.owner : (TEXT.roles[me.role] || String(me.role || ""));
    return { name: name, role: role, id: me.username ? "id " + me.id : "", initial: (me.username || "#").charAt(0).toUpperCase() };
  }
  /* 鍵盤：回下一個要停的位置；-1＝這個鍵不歸選單管 */
  function moveIndex(current, key, count, shift) {
    if (count <= 0) { return -1; }
    if (key === "ArrowDown" || (key === "Tab" && !shift)) { return current < 0 ? 0 : (current + 1) % count; }
    if (key === "ArrowUp" || (key === "Tab" && shift)) { return current < 0 ? count - 1 : (current - 1 + count) % count; }
    if (key === "Home" || key === "PageUp") { return 0; }
    if (key === "End" || key === "PageDown") { return count - 1; }
    return -1;
  }
  /* 等 SYNOX 回來：問 /alive，boot 跟原本的不一樣才算（舊的那支在關掉前還會回一下） */
  function watchRestart(o) {
    var start = o.now(), stopped = false;
    function tick() {
      if (stopped) { return; }
      var waited = o.now() - start;
      if (waited >= (o.timeoutMs || TIMEOUT_MS)) { stopped = true; o.onTimeout(Math.round(waited / 1000)); return; }
      if (o.onTick) { o.onTick(Math.round(waited / 1000)); }
      o.fetch("/alive", { cache: "no-store", credentials: "same-origin" }).then(function (r) {
        return r && r.ok ? r.json() : null;
      }).then(function (d) {
        if (stopped) { return; }
        if (d && d.ok && d.boot && d.boot !== o.oldBoot) { stopped = true; o.onBack(); return; }
        o.schedule(tick, o.interval || POLL_MS);
      }, function () {
        if (!stopped) { o.schedule(tick, o.interval || POLL_MS); }   // 關機中連不上是正常的
      });
    }
    o.schedule(tick, o.interval || POLL_MS);
    return { stop: function () { stopped = true; } };
  }

  /* ── 選單本身（只用一小撮 DOM：classList、setAttribute、focus、contains、addEventListener）────── */
  function createMenu(doc, menu, triggers, opts) {
    opts = opts || {};
    var openedBy = null;
    function list() {
      return Array.prototype.filter.call(menu.querySelectorAll('[role="menuitem"]'), function (n) {
        return !n.classList.contains("hidden") && !n.disabled;
      });
    }
    function isOpen() { return !menu.classList.contains("hidden"); }
    function focusAt(i) { var l = list(); if (l[i]) { l[i].focus(); } }
    function place(trigger) {
      if (!trigger || !trigger.getBoundingClientRect || !menu.style) { return; }
      var r = trigger.getBoundingClientRect(), w = root.innerWidth || 0, h = root.innerHeight || 0;
      var down = r.top < h / 2;                        // 手機的頭像在上面：往下開；側欄的卡片在下面：往上開
      menu.classList.toggle("um-down", down);
      menu.style.left = down ? "auto" : Math.max(8, Math.round(r.left)) + "px";
      menu.style.right = down ? Math.max(8, Math.round(w - r.right)) + "px" : "auto";
      menu.style.top = down ? Math.round(r.bottom + 8) + "px" : "auto";
      menu.style.bottom = down ? "auto" : Math.round(h - r.top + 8) + "px";
    }
    function open(trigger, where) {
      openedBy = trigger || triggers[0];
      if (opts.beforeOpen) { opts.beforeOpen(); }
      place(openedBy);
      menu.classList.remove("hidden");
      triggers.forEach(function (t) { t.setAttribute("aria-expanded", t === openedBy ? "true" : "false"); });
      focusAt(where === "last" ? list().length - 1 : 0);
    }
    function close(refocus) {
      if (!isOpen()) { return; }
      menu.classList.add("hidden");
      triggers.forEach(function (t) { t.setAttribute("aria-expanded", "false"); });
      if (refocus !== false && openedBy) { openedBy.focus(); }
    }
    triggers.forEach(function (t) {
      t.addEventListener("click", function () { if (isOpen()) { close(); } else { open(t, "first"); } });
      t.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(t, e.key === "ArrowUp" ? "last" : "first"); }
      });
    });
    menu.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      var l = list(), i = l.indexOf(doc.activeElement);
      var next = moveIndex(i, e.key, l.length, e.shiftKey);
      if (next >= 0) { e.preventDefault(); focusAt(next); return; }
      if (e.key === " " && doc.activeElement && doc.activeElement.click) { e.preventDefault(); doc.activeElement.click(); }
    });
    menu.addEventListener("click", function (e) {      // 按了任何一項：選單收起來（那一項自己的動作照做）
      var t = e.target;
      while (t && t !== menu && !(t.getAttribute && t.getAttribute("role") === "menuitem")) { t = t.parentNode; }
      if (t && t !== menu) { close(); }               // 焦點回卡片：接著跳出的確認框關掉後也回得來
    });
    doc.addEventListener("keydown", function (e) { if (e.key === "Escape" && isOpen()) { close(); } });
    doc.addEventListener("mousedown", function (e) {
      if (!isOpen()) { return; }
      if (menu.contains(e.target) || triggers.some(function (t) { return t.contains(e.target); })) { return; }
      close(false);
    });
    return { open: open, close: close, isOpen: isOpen, items: list };
  }

  /* ── 對話框（自己畫，跟主題一起換色；role=alertdialog、焦點留在裡面）──────────── */
  function dialog(doc, o) {
    var scrim = doc.createElement("div");
    scrim.className = "um-scrim";
    var box = doc.createElement("div");
    box.className = "um-dialog" + (o.busy ? " busy" : "");
    box.setAttribute("role", "alertdialog");
    box.setAttribute("aria-modal", "true");
    var icon = doc.createElement("div");
    icon.className = "um-dialog-icon" + (o.spin ? " spin" : "");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = o.icon || "⟳";
    var h = doc.createElement("h2");
    h.id = "um-dialog-title";
    h.textContent = o.title;
    box.setAttribute("aria-labelledby", h.id);
    var p = doc.createElement("p");
    p.className = "um-dialog-text";
    p.id = "um-dialog-text";
    p.textContent = o.text || "";
    box.setAttribute("aria-describedby", p.id);
    box.appendChild(icon); box.appendChild(h); box.appendChild(p);
    if (o.list && o.list.length) {
      var ul = doc.createElement("ul");
      ul.className = "um-dialog-list";
      o.list.forEach(function (t) { var li = doc.createElement("li"); li.textContent = t; ul.appendChild(li); });
      box.appendChild(ul);
    }
    var row = doc.createElement("div");
    row.className = "um-dialog-actions";
    var buttons = [];
    (o.buttons || []).forEach(function (b) {
      var btn = doc.createElement("button");
      btn.type = "button";
      btn.className = b.primary ? "primary" : "";
      btn.textContent = b.label;
      btn.addEventListener("click", function () { b.run(ctl); });
      row.appendChild(btn);
      buttons.push(btn);
    });
    box.appendChild(row);
    scrim.appendChild(box);
    var before = doc.activeElement;
    function onKey(e) {
      if (e.key === "Escape" && o.onEscape) { e.preventDefault(); o.onEscape(ctl); return; }
      if (e.key === "Tab" && buttons.length) {        // 焦點不跑出對話框
        var i = buttons.indexOf(doc.activeElement);
        var n = moveIndex(i, "Tab", buttons.length, e.shiftKey);
        e.preventDefault(); buttons[n].focus();
      }
    }
    box.addEventListener("keydown", onKey);
    doc.body.appendChild(scrim);
    var ctl = {
      box: box, text: p, title: h, buttons: buttons,
      close: function () { if (scrim.parentNode) { scrim.parentNode.removeChild(scrim); } if (before && before.focus) { before.focus(); } },
      set: function (title, text) { if (title) { h.textContent = title; } if (text !== undefined) { p.textContent = text; } }
    };
    var first = buttons[o.focus === undefined ? 0 : o.focus];
    if (first) { first.focus(); } else { box.setAttribute("tabindex", "-1"); if (box.focus) { box.focus(); } }
    return ctl;
  }

  /* ── 接到畫面 ───────────────────────────────────────────────────── */
  var opts = null, me = null, fetchedAt = 0, menuCtl = null, restarting = false;
  function $(id) { return document.getElementById(id); }
  function uptimeNow() { return (me && me.uptime_s || 0) + Math.max(0, (Date.now() - fetchedAt) / 1000); }

  function paintHead() {
    var w = whoLines(me);
    $("um-status").textContent = statusLine(uptimeNow());
    $("um-ver").textContent = me && me.version ? fmt(TEXT.version, { v: me.version }) : "";
    $("um-name").textContent = w.name;
    $("um-role").textContent = w.role + (w.id ? " · " + w.id : "");
    $("um-avatar").textContent = w.initial;
    var m = $("avatar-m");
    if (m) { m.textContent = w.initial; }
  }
  function setPending(on) {
    on = !!(on && me && me.owner);
    if (me) { me.restart = me.restart || {}; me.restart.pending = on; }
    Array.prototype.forEach.call(document.querySelectorAll("[data-um-dot]"), function (d) { d.classList.toggle("hidden", !on); });
    var item = $("um-restart");
    if (item) { item.setAttribute("aria-label", on ? TEXT.restartPending : TEXT.restart); }
    var btn = $("restart-btn");
    if (btn) { btn.title = on ? TEXT.restartPending : TEXT.restart; btn.setAttribute("aria-label", btn.title); }
  }
  function fail(e) { opts.toast(fmt(TEXT.failed, { e: e && e.message ? e.message : e })); }

  function restart() {
    if (!me || !me.owner || restarting) { return Promise.resolve(false); }
    return opts.api("GET", "/api/settings/restart").then(function (st) {
      if (!st.can) {
        dialog(document, { icon: "ℹ️", title: TEXT.cantTitle, text: st.how,
                           buttons: [{ label: TEXT.gotIt, primary: true, run: function (d) { d.close(); } }],
                           onEscape: function (d) { d.close(); } });
        return false;
      }
      if (st.wait_s > 0) {
        dialog(document, { icon: "⏳", title: TEXT.waitTitle, text: fmt(TEXT.waitText, { s: st.wait_s }),
                           buttons: [{ label: TEXT.gotIt, primary: true, run: function (d) { d.close(); } }],
                           onEscape: function (d) { d.close(); } });
        return false;
      }
      setPending(st.pending);
      return new Promise(function (resolve) {
        dialog(document, {
          icon: "⟳", title: TEXT.askTitle, text: st.how,
          list: st.reasons && st.reasons.length ? st.reasons.map(function (r) { return TEXT.askBecause + r; }) : null,
          focus: 0,
          buttons: [{ label: TEXT.cancel, run: function (d) { d.close(); resolve(false); } },
                    { label: TEXT.askOk, primary: true, run: function (d) { d.close(); resolve(true); } }],
          onEscape: function (d) { d.close(); resolve(false); }
        });
      }).then(function (yes) { return yes ? go() : false; });
    }).catch(function (e) { fail(e); return false; });
  }
  function working() {                                 // 「重新啟動中…」那一層
    var box = dialog(document, { icon: "⟳", spin: true, busy: true, title: TEXT.working, text: TEXT.workingSub });
    box.box.setAttribute("aria-busy", "true");
    var hint = document.createElement("p");
    hint.className = "um-dialog-wait";
    hint.setAttribute("aria-live", "polite");
    box.box.insertBefore(hint, box.box.lastChild);
    box.hint = hint;
    return box;
  }
  function watch(oldBoot) {
    var box = working();
    watchRestart({
      oldBoot: oldBoot, now: Date.now, schedule: function (fn, ms) { return root.setTimeout(fn, ms); },
      fetch: function (u, o) { return root.fetch(u, o); },
      onTick: function (s) { if (s >= 5) { box.hint.textContent = fmt(TEXT.waited, { s: s }); } },
      onBack: function () { box.set(TEXT.back, ""); box.hint.textContent = ""; root.location.reload(); },
      onTimeout: function (s) {
        box.close();
        dialog(document, { icon: "🤔", title: TEXT.slowTitle, text: fmt(TEXT.slow, { s: s }), focus: 0,
                           buttons: [{ label: TEXT.waitMore, primary: true, run: function (d) { d.close(); watch(oldBoot); } },
                                     { label: TEXT.reload, run: function () { root.location.reload(); } }] });
      }
    });
  }
  function go() {
    restarting = true;
    return opts.api("POST", "/api/settings/restart", { confirm: true }).then(function (r) {
      watch(r.boot);
      return true;
    }).catch(function (e) { restarting = false; fail(e); return false; });
  }

  function init(o) {
    opts = o; me = o.me; fetchedAt = Date.now();
    var menu = $("user-menu");
    if (!menu) { return; }
    var triggers = [$("um-card"), $("um-phone")].filter(Boolean);
    triggers.forEach(function (t) { t.classList.remove("hidden"); });
    $("um-restart").classList.toggle("hidden", !me.owner);
    var notifyItem = $("um-notify");
    notifyItem.classList.toggle("hidden", !root.SynoxNotify);
    var btn = $("restart-btn");
    if (btn) { btn.classList.toggle("hidden", !me.owner); }
    paintHead();
    setPending(me.restart && me.restart.pending);
    if (menuCtl) { return; }                           // 再登入一次：事件已經掛過了
    // 搬到 <body> 底下：側欄有 backdrop-filter，留在裡面的話 position: fixed 會被側欄框住、超出側欄的部分被切掉
    if (menu.parentNode !== document.body) { document.body.appendChild(menu); }
    menuCtl = createMenu(document, menu, triggers, {
      beforeOpen: function () {
        paintHead();
        if (me && me.owner) {                          // 打開時順便問一下：剛改了設定的話小點要亮
          opts.api("GET", "/api/settings/restart").then(function (st) { setPending(st.pending); }, function () { /* 沒關係 */ });
        }
      }
    });
    $("um-restart").addEventListener("click", function () { restart(); });
    notifyItem.addEventListener("click", function () { if (root.SynoxNotify) { root.SynoxNotify.open("list"); } });
    $("um-logout").addEventListener("click", function () { opts.logout(); });
    if (btn) { btn.addEventListener("click", function () { restart(); }); }
    Array.prototype.forEach.call(document.querySelectorAll("[data-restart-now]"), function (b) {
      b.addEventListener("click", function () { restart(); });
    });
  }
  function reset() {                                   // 登出、被登出：收起來、藏起來
    if (menuCtl) { menuCtl.close(false); }
    me = null;
    ["um-card", "um-phone", "restart-btn"].forEach(function (id) { var n = $(id); if (n) { n.classList.add("hidden"); } });
  }

  var api = { init: init, reset: reset, restart: restart, setPending: setPending,
              uptimeText: uptimeText, statusLine: statusLine, whoLines: whoLines, moveIndex: moveIndex,
              watchRestart: watchRestart, createMenu: createMenu, dialog: dialog, TEXT: TEXT, POLL_MS: POLL_MS,
              TIMEOUT_MS: TIMEOUT_MS };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxUserMenu = api; }
})(typeof window !== "undefined" ? window : this);
