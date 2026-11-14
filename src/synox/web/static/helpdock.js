/* 對話頁的「💡 範例」與 /help 卡片上的範例小標籤（資料：GET /api/help，synox/helpui；已照這個人的叫法算好）。
 *
 *   window.SynoxHelp.init({ api, toast, fill })   app.html 拿到 /api/me 之後呼叫；fill(text)＝把字放進輸入框（不送出）
 *   window.SynoxHelp.toggle()                     打開／關上輸入框上面的範例面板（#examples-btn）
 *   window.SynoxHelp.chips(block)                 對話裡 /help 卡片的 examples 區塊 → 一排可以點的小標籤
 *
 * 安全（tests/test_help_cards.py 會掃這個檔）：只會**填**輸入框，不送出、不按任何東西、不呼叫會改東西的 API
 * （只有 GET /api/help）。字一律 textContent。
 */
(function (root) {
  "use strict";

  var ctx = null;
  var data = null;
  var loadedAt = 0;
  var panel = null;
  var pick = "";               // 面板左邊選到的工具 id

  var TEXT = {
    title: "💡 點一個範例，它會放進輸入框（不會自己送出）", close: "關上", loading: "讀取中…",
    none: "現在還沒有可以用的工具。打 /tutorial 看怎麼裝。", all: "看全部 → 工具頁", tour: "🎓 想要有人帶你走一遍？",
    write: "會寫入", danger: "危險：會先問你", nothing: "這個指令沒有範例，直接打：", tip: "改成你順手的打法：設定 →「⌨️ 我的指令」"
  };

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
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }

  function chip(text, note) {
    var b = button("hd-chip", text, function () { use(text); });
    if (note) { b.title = note; b.setAttribute("aria-label", text + "（" + note + "）"); }
    return b;
  }
  function use(text) {
    if (ctx && ctx.fill) { ctx.fill(text); }
    close();
  }

  function load() {
    if (data && Date.now() - loadedAt < 30000) { return Promise.resolve(data); }
    return ctx.api("GET", "/api/help").then(function (d) { data = d; loadedAt = Date.now(); return d; });
  }

  function badge(effect) {
    if (effect === "write") { return el("span", "hd-badge write", TEXT.write); }
    if (effect === "danger") { return el("span", "hd-badge danger", TEXT.danger); }
    return null;
  }

  function commandRow(c) {
    var row = el("div", "hd-cmd");
    var head = el("div", "hd-cmd-head");
    head.appendChild(el("span", "hd-cmd-title", c.title));
    var b = badge(c.effect);
    if (b) { head.appendChild(b); }
    row.appendChild(head);
    var chips = el("div", "hd-chips");
    (c.examples || []).forEach(function (ex) { chips.appendChild(chip(ex.text, ex.note)); });
    if (!(c.examples || []).length) {
      chips.appendChild(el("span", "hd-note", TEXT.nothing));
      chips.appendChild(chip(c.command, ""));
    }
    row.appendChild(chips);
    return row;
  }

  function render() {
    clear(panel);
    var top = el("div", "hd-top");
    top.appendChild(el("strong", "", TEXT.title));
    top.appendChild(button("ghost sm", TEXT.close, close));
    panel.appendChild(top);
    var tools = (data && data.tools) || [];
    if (!tools.length) {
      panel.appendChild(el("p", "hd-note", TEXT.none));
      panel.appendChild(chip("/tutorial", ""));
      return;
    }
    if (!tools.some(function (t) { return t.id === pick; })) { pick = tools[0].id; }
    var body = el("div", "hd-body");
    var list = el("div", "hd-tools");
    list.setAttribute("role", "tablist");
    tools.forEach(function (t) {
      var b = button("hd-tool" + (t.id === pick ? " on" : ""), t.title, function () { pick = t.id; render(); });
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", t.id === pick ? "true" : "false");
      list.appendChild(b);
    });
    body.appendChild(list);
    var right = el("div", "hd-cmds");
    var tool = tools.filter(function (t) { return t.id === pick; })[0];
    if (tool.summary) { right.appendChild(el("p", "hd-note", tool.summary)); }
    var featured = tool.featured || [];
    var cmds = (tool.commands || []).slice().sort(function (a, b) {
      var ia = featured.indexOf(a.path), ib = featured.indexOf(b.path);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    cmds.forEach(function (c) { right.appendChild(commandRow(c)); });
    body.appendChild(right);
    panel.appendChild(body);
    var foot = el("div", "hd-foot");
    var all = el("a", "", TEXT.all);
    all.href = "#tools";
    all.addEventListener("click", close);
    foot.appendChild(all);
    foot.appendChild(chip("/tutorial", TEXT.tour));
    foot.appendChild(el("span", "hd-note", TEXT.tip));
    panel.appendChild(foot);
  }

  function open() {
    panel = document.getElementById("helpdock");
    if (!panel || !ctx) { return; }
    panel.classList.remove("hidden");
    var btn = document.getElementById("examples-btn");
    if (btn) { btn.setAttribute("aria-expanded", "true"); }
    clear(panel);
    panel.appendChild(el("p", "hd-note", TEXT.loading));
    load().then(render).catch(function (e) { close(); if (ctx.toast) { ctx.toast(e.message); } });
  }
  function close() {
    var p = document.getElementById("helpdock");
    if (p) { p.classList.add("hidden"); }
    var btn = document.getElementById("examples-btn");
    if (btn) { btn.setAttribute("aria-expanded", "false"); }
  }
  function toggle() {
    var p = document.getElementById("helpdock");
    if (p && !p.classList.contains("hidden")) { close(); } else { open(); }
  }

  function chips(block) {
    var box = el("div", "hd-chips in-chat");
    (block.items || []).forEach(function (it) {
      if (it && typeof it.text === "string") { box.appendChild(chip(it.text, it.note || "")); }
    });
    return box;
  }

  function init(c) {
    ctx = c;
    var btn = document.getElementById("examples-btn");
    if (btn && !btn.getAttribute("data-bound")) {
      btn.setAttribute("data-bound", "1");
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("aria-controls", "helpdock");
      btn.addEventListener("click", toggle);
    }
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { close(); } });
  }

  root.SynoxHelp = { init: init, toggle: toggle, chips: chips, close: close, _use: use };
})(typeof window !== "undefined" ? window : this);
