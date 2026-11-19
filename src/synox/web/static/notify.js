/* 🔔 通知與 ⏰ 鬧鐘（synox/notify、docs/notifications.md）。樣式在 static/notify.css。
 *
 * - 側欄（手機是上方列）多一顆 🔔（沒看的數字）和「⏰ 下一個：明天 08:00 吃藥」。
 * - 每 10 秒問一次 GET /api/notifications?since=<rev>（分頁在背景時 30 秒）。新來的跳出一張小卡：
 *   鬧鐘的小卡一直留著，直到按「知道了」或「5 分鐘後再提醒」；其他的幾秒後收起來（清單裡還在）。
 * - 打開頁面時還沒看的鬧鐘（你不在的時候響過、錯過的）也會跳出來。
 * - 提示音、桌面通知都要自己按才打開（不會自己跳出瀏覽器的詢問）；只記在這個瀏覽器（localStorage）。
 * - 工具畫面的「現在關掉」「再給我 N 分鐘」直接叫 /api/apps/<名>/stop、/keep（擁有者、手機驗證照舊）。
 * - 設定 → 電腦與備份 →「🔔 通知要送到哪裡」：每一類 × 網頁／Telegram／Discord。
 * 字一律 textContent；字串集中在 TEXT。app.html 拿到 /api/me 之後叫 window.SynoxNotify.init({ api, toast, me })。
 */
(function (root) {
  "use strict";
  var TEXT = {
    bell: "通知",
    bellN: "通知（{n} 則還沒看）",
    title: "通知",
    tabList: "通知",
    tabAlarms: "鬧鐘",
    allRead: "全部已讀",
    empty: "目前沒有通知。",
    ok: "知道了",
    close: "收起來",
    next: "⏰ 下一個：{when} {text}",
    nextShort: "⏰ {when}",
    missed: "你錯過了 {n} 個鬧鐘：",
    whileAway: "你不在的時候響過：",
    alarmsEmpty: "還沒有鬧鐘。跟我說「明天早上 8 點提醒我吃藥」，或打 /remind_add 08:00 吃藥。",
    where: "時間到會在：{where} 叫你。",
    whereNone: "現在沒有任何地方會叫你。",
    test: "試響一下",
    del: "刪除",
    delAsk: "刪掉「{text}」這個鬧鐘？",
    deleted: "刪掉了。",
    daily: "每天",
    once: "一次",
    sound: "開啟提示音",
    soundOff: "關掉提示音",
    soundOn: "提示音開了：鬧鐘響的時候這個分頁會嗶一聲。",
    desktop: "開啟桌面通知",
    desktopOn: "桌面通知開了。",
    desktopNo: "瀏覽器沒有允許，桌面通知沒打開（可以在網址列左邊的設定改）。",
    awakeOn: "好了，電腦不會自己睡著了。",
    prefsTitle: "🔔 通知要送到哪裡",
    prefsSub: "每一類通知要送到哪裡。沒接上的地方不能選；接上之後預設全部都送。",
    prefsSave: "存起來",
    prefsSaved: "存好了。",
    notLinked: "（沒接上）",
    done: "完成",
    deskTitle: "🖥️ 電腦提醒視窗",
    deskWindow: "提醒時間到，在這台電腦右下角跳出提醒視窗（不按不會自己關）",
    deskSentinel: "登入 Windows 時啟動提醒哨兵（SYNOX 沒開也會跳提醒、送 Telegram；SYNOX 開著時它會讓位）",
    deskLocked: "config.json 裡關掉了電腦視窗（notify.desktop = false）。",
    deskSaved: "存好了。",
    locked: "安全警告一定會在網頁上出現。",
    failed: "沒做成：{e}"
  };
  var POLL_MS = 10000, POLL_HIDDEN_MS = 30000, SOFT_HIDE_MS = 9000, MAX_POPS = 4;
  var ALARM_GRACE_MS = 1500, POLL_MIN_MS = 1000;   // 下一個鬧鐘響的那一刻＋1.5 秒多看一次（不用等滿 10 秒）
  var opts = null, me = null, rev = 0, primed = false, timer = null;
  var items = {};                 // id → item
  var pops = {};                  // id → 小卡 DOM
  var nextAlarm = null, unread = 0, panelTab = "list";
  var audio = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }
  function fmt(s, v) { return s.replace(/\{(\w+)\}/g, function (_m, k) { return v[k] === undefined ? "" : String(v[k]); }); }
  function clear(n) { while (n.firstChild) { n.removeChild(n.firstChild); } }
  function store(k, v) { try { if (v === undefined) { return localStorage.getItem(k); } if (v === null) { localStorage.removeItem(k); } else { localStorage.setItem(k, v); } } catch (e) { return null; } return null; }
  function btn(label, cls, fn) {
    var b = el("button", cls || "sm", label);
    b.type = "button";
    b.addEventListener("click", fn);
    return b;
  }
  function when(at) {
    var d = new Date(at * 1000);
    var hh = ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
    var today = new Date();
    if (d.toDateString() === today.toDateString()) { return hh; }
    return (d.getMonth() + 1) + "/" + d.getDate() + " " + hh;
  }
  function fail(e) { opts.toast(fmt(TEXT.failed, { e: e && e.message ? e.message : e })); }

  // ── 上方的 🔔 與 ⏰ ───────────────────────────────────────────────
  function build() {
    var row = document.querySelector(".brand-row");
    if (!row || $("ntf-bell")) { return; }
    var chip = el("button", "ntf-chip hidden");
    chip.id = "ntf-chip"; chip.type = "button";
    chip.addEventListener("click", function () { openPanel("alarms"); });
    var bell = el("button", "ntf-bell ghost sm");
    bell.id = "ntf-bell"; bell.type = "button";
    bell.setAttribute("aria-haspopup", "dialog");
    bell.setAttribute("aria-expanded", "false");
    bell.setAttribute("aria-label", TEXT.bell);
    var icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("class", "i"); icon.setAttribute("viewBox", "0 0 24 24"); icon.setAttribute("aria-hidden", "true");
    var p1 = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p1.setAttribute("d", "M6 16V11a6 6 0 0 1 12 0v5l2 2H4z");
    var p2 = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p2.setAttribute("d", "M10 20a2 2 0 0 0 4 0");
    icon.appendChild(p1); icon.appendChild(p2);
    bell.appendChild(icon);
    var n = el("span", "ntf-n hidden"); n.id = "ntf-n";
    bell.appendChild(n);
    bell.addEventListener("click", function () { if ($("ntf-panel").classList.contains("hidden")) { openPanel("list"); } else { closePanel(); } });
    var logout = $("logout");
    row.insertBefore(bell, logout);
    row.insertBefore(chip, bell);

    var panel = el("div", "ntf-panel hidden");
    panel.id = "ntf-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", TEXT.title);
    document.body.appendChild(panel);
    var stack = el("div", "ntf-stack");
    stack.id = "ntf-stack";
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { closePanel(); } });
    document.addEventListener("click", function (e) {
      var p = $("ntf-panel");
      if (!e.target.isConnected) { return; }            // 按了面板裡的分頁：那顆按鈕已經重畫掉了，不算點到外面
      if (!p.classList.contains("hidden") && !p.contains(e.target) && !$("ntf-bell").contains(e.target) &&
          !$("ntf-chip").contains(e.target)) { closePanel(); }
    });
  }

  function paintBell() {
    var n = $("ntf-n"), bell = $("ntf-bell");
    if (!n) { return; }
    n.textContent = unread > 99 ? "99+" : String(unread);
    n.classList.toggle("hidden", !unread);
    bell.setAttribute("aria-label", unread ? fmt(TEXT.bellN, { n: unread }) : TEXT.bell);
    var chip = $("ntf-chip");
    chip.classList.toggle("hidden", !nextAlarm);
    if (nextAlarm) {
      clear(chip);
      chip.appendChild(el("span", "long", fmt(TEXT.next, nextAlarm)));
      chip.appendChild(el("span", "short", fmt(TEXT.nextShort, nextAlarm)));
      chip.title = fmt(TEXT.next, nextAlarm);
    }
  }

  // ── 輪詢 ─────────────────────────────────────────────────────────
  function poll() {
    return opts.api("GET", "/api/notifications?since=" + rev).then(function (d) {
      var fresh = [];
      (d.items || []).forEach(function (it) {
        var old = items[it.id];
        items[it.id] = it;
        if (!old && !it.read) { fresh.push(it); }
        if (it.read && pops[it.id]) { dropPop(it.id); }
        if (old && pops[it.id] && !it.read) { fillPop(pops[it.id], it); }
      });
      rev = d.rev || rev;
      unread = d.unread || 0;
      nextAlarm = d.next || null;
      paintBell();
      if (!primed) {
        primed = true;
        fresh.filter(function (it) { return it.kind === "alarm"; }).slice(-MAX_POPS).forEach(function (it) { pop(it, true); });
      } else {
        fresh.slice(-MAX_POPS).forEach(function (it) { pop(it, false); ring(it); });
      }
      if (!$("ntf-panel").classList.contains("hidden") && panelTab === "list") { paintList(); }
    }).catch(function () { /* 下一輪再試 */ });
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(function () { poll().then(schedule, schedule); }, nextWait(Date.now()));
  }
  function nextWait(nowMs) {
    // 平常 10 秒（看不到分頁 30 秒）；下一個鬧鐘比那更早響＝在它響之後 1.5 秒就看（提醒引擎準時送出，網頁也準時跳）
    var wait = document.hidden ? POLL_HIDDEN_MS : POLL_MS;
    if (!document.hidden && nextAlarm && nextAlarm.ts) {
      var until = nextAlarm.ts * 1000 - nowMs + ALARM_GRACE_MS;
      if (until > 0 && until < wait) { wait = Math.max(POLL_MIN_MS, until); }
    }
    return wait;
  }

  // ── 跳出來的小卡 ─────────────────────────────────────────────────
  function sticky(it) { return it.kind === "alarm" || it.level === "alarm" || it.level === "warn"; }
  function pop(it, away) {
    if (pops[it.id]) { return; }
    var card = el("div", "ntf-pop" + (sticky(it) ? " alarm" : ""));
    card.setAttribute("role", it.kind === "alarm" ? "alert" : "status");
    card.dataset.away = away ? "1" : "";
    fillPop(card, it);
    pops[it.id] = card;
    $("ntf-stack").appendChild(card);
    if (!sticky(it)) { card.timer = setTimeout(function () { dropPop(it.id); }, SOFT_HIDE_MS); }
  }
  function fillPop(card, it) {
    clear(card);
    if (card.dataset.away && !(it.data && it.data.missed)) { card.appendChild(el("div", "ntf-away", TEXT.whileAway)); }
    card.appendChild(el("div", "ntf-text", it.text));
    card.appendChild(el("div", "ntf-time", when(it.at)));
    card.appendChild(actions(it, true));
  }
  function dropPop(id) {
    var c = pops[id];
    if (!c) { return; }
    clearTimeout(c.timer);
    if (c.parentNode) { c.parentNode.removeChild(c); }
    delete pops[id];
  }

  function actions(it, inPop) {
    var row = el("div", "ntf-acts");
    var acts = it.read ? [] : (it.actions || []);
    var hasOk = false;
    acts.forEach(function (a) {
      if (a.id === "ok") { hasOk = true; row.appendChild(btn(a.label || TEXT.ok, "sm", function () { read(it.id); })); }
      else if (a.id === "snooze") { row.appendChild(btn(a.label, "sm primary", function () { snooze(it.id); })); }
      else if (a.id === "done") { row.appendChild(btn(a.label || TEXT.done, "sm primary", function () { done(it.id); })); }
      else if ((a.id === "app_stop" || a.id === "app_keep") && a.app && me && me.owner) {
        row.appendChild(btn(a.label, a.id === "app_stop" ? "sm primary" : "sm", function () {
          opts.api("POST", "/api/apps/" + encodeURIComponent(a.app) + (a.id === "app_stop" ? "/stop" : "/keep"), {})
            .then(function () { return read(it.id); }, fail);
        }));
      }
    });
    if (!it.read && !hasOk) { row.appendChild(btn(TEXT.ok, "sm", function () { read(it.id); })); }
    if (inPop && !sticky(it)) { row.appendChild(btn(TEXT.close, "sm ghost", function () { dropPop(it.id); })); }
    return row;
  }

  function read(id) {
    dropPop(id);
    return opts.api("POST", "/api/notifications/read", id === undefined ? {} : { id: id }).then(poll, fail);
  }
  function done(id) {
    dropPop(id);
    return opts.api("POST", "/api/notifications/" + id + "/done", {}).then(function (d) {
      opts.toast(d.message || "");
      return poll();
    }, fail);
  }
  function snooze(id) {
    dropPop(id);
    return opts.api("POST", "/api/notifications/" + id + "/snooze", {}).then(function (d) {
      opts.toast(d.message || "");
      return poll();
    }, fail);
  }

  // ── 提示音、桌面通知（都要自己按才打開）─────────────────────────────
  function ring(it) {
    if (it.kind !== "alarm") { return; }
    if (store("synox.ntf.sound") === "1") { beep(); }
    if (store("synox.ntf.desktop") === "1" && root.Notification && Notification.permission === "granted") {
      try { new Notification("SYNOX", { body: it.text, tag: "synox-" + it.id }); } catch (e) { /* 有些瀏覽器只准 service worker */ }
    }
  }
  function beep() {
    try {
      var Ctx = root.AudioContext || root.webkitAudioContext;
      if (!Ctx) { return; }
      audio = audio || new Ctx();
      if (audio.state === "suspended") { audio.resume(); }
      [0, 0.35].forEach(function (t0) {
        var o = audio.createOscillator(), g = audio.createGain();
        o.frequency.value = 880;
        g.gain.setValueAtTime(0.0001, audio.currentTime + t0);
        g.gain.exponentialRampToValueAtTime(0.2, audio.currentTime + t0 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + t0 + 0.25);
        o.connect(g); g.connect(audio.destination);
        o.start(audio.currentTime + t0); o.stop(audio.currentTime + t0 + 0.3);
      });
    } catch (e) { /* 沒聲音就算了 */ }
  }
  function optIns(box) {
    var row = el("div", "ntf-acts ntf-optin");
    var on = store("synox.ntf.sound") === "1";
    row.appendChild(btn(on ? TEXT.soundOff : TEXT.sound, "sm", function () {
      if (store("synox.ntf.sound") === "1") { store("synox.ntf.sound", null); }
      else { store("synox.ntf.sound", "1"); beep(); opts.toast(TEXT.soundOn); }
      paintPanel();
    }));
    if (root.Notification && Notification.permission !== "denied" && store("synox.ntf.desktop") !== "1") {
      row.appendChild(btn(TEXT.desktop, "sm", function () {
        Notification.requestPermission().then(function (p) {
          if (p === "granted") { store("synox.ntf.desktop", "1"); opts.toast(TEXT.desktopOn); }
          else { opts.toast(TEXT.desktopNo); }
          paintPanel();
        });
      }));
    }
    box.appendChild(row);
  }

  // ── 清單 ─────────────────────────────────────────────────────────
  function openPanel(tab) {
    panelTab = tab || "list";
    $("ntf-panel").classList.remove("hidden");
    document.body.classList.add("ntf-open");
    $("ntf-bell").setAttribute("aria-expanded", "true");
    paintPanel();
  }
  function closePanel() {
    var p = $("ntf-panel");
    if (!p || p.classList.contains("hidden")) { return; }
    p.classList.add("hidden");
    document.body.classList.remove("ntf-open");
    $("ntf-bell").setAttribute("aria-expanded", "false");
  }
  function paintPanel() {
    var p = $("ntf-panel");
    clear(p);
    var head = el("div", "ntf-head");
    var tabs = el("div", "ntf-tabs");
    tabs.setAttribute("role", "tablist");
    [["list", TEXT.tabList], ["alarms", TEXT.tabAlarms]].forEach(function (t) {
      var b = btn(t[1], "sm" + (panelTab === t[0] ? " on" : " ghost"), function () { panelTab = t[0]; paintPanel(); });
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", panelTab === t[0] ? "true" : "false");
      tabs.appendChild(b);
    });
    head.appendChild(tabs);
    if (panelTab === "list") { head.appendChild(btn(TEXT.allRead, "sm ghost", function () { read(); })); }
    p.appendChild(head);
    var body = el("div", "ntf-body");
    body.id = "ntf-body";
    p.appendChild(body);
    if (panelTab === "list") { paintList(); } else { paintAlarms(); }
  }
  function paintList() {
    var body = $("ntf-body");
    if (!body) { return; }
    clear(body);
    var list = Object.keys(items).map(function (k) { return items[k]; }).sort(function (a, b) { return b.id - a.id; });
    var missed = list.filter(function (it) { return it.kind === "alarm" && !it.read && it.data && it.data.missed; });
    if (missed.length) {
      body.appendChild(el("div", "ntf-missed", fmt(TEXT.missed, { n: missed.length }) +
        missed.map(function (it) { return (it.data.text || ""); }).join("、")));
    }
    if (!list.length) { body.appendChild(el("p", "muted", TEXT.empty)); return; }
    var ul = el("ul", "ntf-list");
    list.forEach(function (it) {
      var li = el("li", it.read ? "read" : "unread");
      li.appendChild(el("div", "ntf-text", it.text));
      li.appendChild(el("div", "ntf-time", when(it.at)));
      if (!it.read) { li.appendChild(actions(it, false)); }
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }
  function paintAlarms() {
    var body = $("ntf-body");
    clear(body);
    opts.api("GET", "/api/alarms").then(function (d) {
      if (!$("ntf-body") || panelTab !== "alarms") { return; }
      clear(body);
      body.appendChild(el("p", "ntf-where", d.where && d.where.length ? fmt(TEXT.where, { where: d.where.join("、") }) : TEXT.whereNone));
      (d.warnings || []).forEach(function (w) {
        var box = el("div", "ntf-warn");
        box.appendChild(el("span", "", "⚠️ " + w.text));
        if (w.fix && w.fix.href) {
          var a = el("a", "btn ghost", w.fix.label); a.href = w.fix.href;
          a.addEventListener("click", closePanel);
          box.appendChild(a);
        } else if (w.fix && w.fix.action === "keep_awake") {
          box.appendChild(btn(w.fix.label, "sm primary", function () {
            opts.api("POST", "/api/runtime/keep-awake", { enabled: true }).then(function () {
              opts.toast(TEXT.awakeOn); paintAlarms();
            }, fail);
          }));
        }
        body.appendChild(box);
      });
      if (!(d.items || []).length) { body.appendChild(el("p", "muted", TEXT.alarmsEmpty)); }
      var ul = el("ul", "ntf-list");
      (d.items || []).forEach(function (a) {
        var li = el("li", "alarm");
        li.appendChild(el("div", "ntf-text", "⏰ " + a.when + "　" + a.text));
        li.appendChild(el("div", "ntf-time", a.daily ? TEXT.daily : TEXT.once));
        var row = el("div", "ntf-acts");
        row.appendChild(btn(TEXT.del, "sm ghost", function () {
          if (!root.confirm(fmt(TEXT.delAsk, a))) { return; }
          opts.api("POST", "/api/alarms/" + a.id + "/delete", {}).then(function () {
            opts.toast(TEXT.deleted); paintAlarms(); poll();
          }, fail);
        }));
        li.appendChild(row);
        ul.appendChild(li);
      });
      body.appendChild(ul);
      var row = el("div", "ntf-acts");
      row.appendChild(btn(TEXT.test, "sm primary", function () {
        opts.api("POST", "/api/alarms/test", {}).then(function (r) { opts.toast(r.message || ""); poll(); }, fail);
      }));
      body.appendChild(row);
      optIns(body);
      body.appendChild(el("p", "muted ntf-note", d.note || ""));
    }, function (e) { clear(body); body.appendChild(el("p", "muted", e.message)); optIns(body); });
  }

  // ── 設定 → 電腦與備份 → 通知要送到哪裡 ────────────────────────────
  function paintPrefs() {
    var box = $("set-notify");
    if (!box) { return; }
    opts.api("GET", "/api/notifications/prefs").then(function (d) {
      var body = $("set-notify-body");
      clear(body);
      var table = el("table", "ntf-prefs");
      var thead = el("thead"), tr = el("tr");
      tr.appendChild(el("th", "", ""));
      d.channels.forEach(function (c) { tr.appendChild(el("th", "", c.label + (c.active ? "" : TEXT.notLinked))); });
      thead.appendChild(tr); table.appendChild(thead);
      var tbody = el("tbody");
      d.kinds.forEach(function (k) {
        var row = el("tr");
        row.appendChild(el("th", "", k.label));
        d.channels.forEach(function (c) {
          var td = el("td"), cb = el("input");
          cb.type = "checkbox";
          cb.dataset.kind = k.kind; cb.dataset.ch = c.id;
          cb.checked = c.active && k.off.indexOf(c.id) < 0;          // 沒接上的不打勾（不會送）
          cb.disabled = !c.active || k.locked.indexOf(c.id) >= 0;
          cb.setAttribute("aria-label", k.label + "：" + c.label);
          if (k.locked.indexOf(c.id) >= 0) { cb.title = TEXT.locked; }
          td.appendChild(cb); row.appendChild(td);
        });
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      var wrap = el("div", "tablewrap");
      wrap.appendChild(table);
      body.appendChild(wrap);
      var r = el("div", "row");
      var msg = el("span", "muted");
      r.appendChild(btn(TEXT.prefsSave, "primary", function () {
        var off = {};
        Array.prototype.forEach.call(table.querySelectorAll("input[type=checkbox]"), function (cb) {
          if (!cb.checked && !cb.disabled) { (off[cb.dataset.kind] = off[cb.dataset.kind] || []).push(cb.dataset.ch); }
        });
        opts.api("POST", "/api/notifications/prefs", { off: off }).then(function () { msg.textContent = TEXT.prefsSaved; }, fail);
      }));
      r.appendChild(msg);
      body.appendChild(r);
      if (d.desk && d.desk.supported) { body.appendChild(deskPrefs(d.desk)); }
      box.classList.remove("hidden");
    }).catch(function () { /* 沒有就不顯示 */ });
  }
  // 電腦提醒視窗（Windows 個人版的擁有者才有）：開關視窗、登入時啟動提醒哨兵
  function deskPrefs(desk) {
    var wrap = el("div", "ntf-desk");
    wrap.appendChild(el("h3", "", TEXT.deskTitle));
    function check(key, label, disabled) {
      var lab = el("label", "row"), cb = el("input");
      cb.type = "checkbox";
      cb.checked = !!desk[key];
      cb.disabled = !!disabled;
      cb.dataset.key = key;
      lab.appendChild(cb);
      lab.appendChild(el("span", "", label));
      wrap.appendChild(lab);
      return cb;
    }
    var win = check("window", TEXT.deskWindow, desk.locked_off);
    var sen = check("sentinel", TEXT.deskSentinel, false);
    if (desk.locked_off) { wrap.appendChild(el("p", "muted", TEXT.deskLocked)); }
    var r = el("div", "row"), msg = el("span", "muted");
    r.appendChild(btn(TEXT.prefsSave, "primary", function () {
      var body = { sentinel: sen.checked };
      if (!win.disabled) { body.window = win.checked; }
      opts.api("POST", "/api/notifications/desk", body).then(function () { msg.textContent = TEXT.deskSaved; }, fail);
    }));
    r.appendChild(msg);
    wrap.appendChild(r);
    return wrap;
  }
  function prefsCard() {
    var panel = document.querySelector('.tab-panel[data-tab="system"]');
    if (!panel || $("set-notify")) { return; }
    var card = el("div", "card hidden");
    card.id = "set-notify";
    var head = el("div", "card-head");
    head.appendChild(el("span", "tile", "🔔"));
    var txt = el("div", "txt");
    txt.appendChild(el("h2", "", TEXT.prefsTitle));
    txt.appendChild(el("p", "sub", TEXT.prefsSub));
    head.appendChild(txt);
    card.appendChild(head);
    var body = el("div");
    body.id = "set-notify-body";
    card.appendChild(body);
    panel.insertBefore(card, panel.firstChild);
  }
  function onHash() { if ((location.hash || "").indexOf("#settings") === 0) { paintPrefs(); } }

  root.SynoxNotify = {
    init: function (o) {
      opts = o; me = o.me || null;
      build(); prefsCard();
      root.addEventListener("hashchange", onHash);
      document.addEventListener("visibilitychange", function () { if (!document.hidden) { poll(); } });
      onHash();
      poll().then(schedule, schedule);
    },
    refresh: function () { return poll(); },
    open: openPanel,
    TEXT: TEXT
  };
})(window);
