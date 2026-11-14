/* 設定 →「⌨️ 我的指令」：每個人自己的指令符號與名字（synox/aliases.py；API 在 web/api_commands.py）。
 *
 *   window.SynoxAliases.init({ api, toast })
 *   window.SynoxAliases.open(rootElement)     設定頁打開時呼叫：讀 GET /api/aliases 畫出來
 *
 * 規則與檢查都在伺服器（存檔時 POST /api/aliases 才算數）；這裡只畫、送出、把錯誤放在那一格旁邊。
 * 試打（POST /api/aliases/preview）照還沒存的表算，不執行、不存。字一律 textContent。
 */
(function (root) {
  "use strict";

  var ctx = null;
  var box = null;
  var state = null;            // GET /api/aliases 的結果
  var rows = [];               // [{ path, name }]
  var previewTimer = null;

  var TEXT = {
    title: "⌨️ 我的指令",
    sub: "把指令換成你順手的打法，例如把 /money 打成 @記帳。原本的 / 和原本的指令名永遠可以用；只改你自己打的字，不影響別人。",
    prefix: "指令前面的符號", names: "幫指令取名字", add: "＋ 加一個名字", remove: "拿掉",
    name: "名字", target: "哪個指令", suggest: "工具建議的名字（點了才會加上）：", tryLabel: "試打看看",
    tryHint: "例如 @記帳 120 午餐", save: "存起來", reset: "全部還原", resetAgain: "再按一次：全部還原",
    saved: "存好了。", resetDone: "還原了：只用原本的 /。", becomes: "會變成：", plain: "會當成一般的話，交給 AI。",
    notes: [
      "名字只能用中文、英文字母、數字和底線，最多 {n} 個字；不能跟原本的指令同名。",
      "網頁、Telegram、Discord 都可以用；Telegram 輸入框旁的指令選單只會列原本的 /英文 指令。",
      "在 Discord 的頻道裡，要 @bot 才收得到不是 / 開頭的訊息；在頻道裡大家看到的說明一律是原本的 /。"
    ],
    conflict: "「{n}」現在跟一個新裝的指令同名，暫時沒有作用，請換一個名字。",
    empty: "還沒有取任何名字。"
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
  function fmt(s, vars) { return String(s).replace(/\{(\w+)\}/g, function (_m, k) { return vars[k]; }); }

  function draft() {
    var names = {};
    rows.forEach(function (r) {
      if (!r.path || !String(r.name || "").trim()) { return; }
      (names[r.path] = names[r.path] || []).push(String(r.name).trim());
    });
    var sel = box.querySelector("#alias-prefix");
    return { prefix: sel ? sel.value : "/", names: names };
  }

  function rowsFrom(names) {
    var out = [];
    Object.keys(names || {}).forEach(function (p) { (names[p] || []).forEach(function (n) { out.push({ path: p, name: n }); }); });
    return out;
  }

  function targetLabel(t) { return t.tool + "：" + t.title + "（" + t.command + "）"; }

  function renderRows(list, errors) {
    clear(list);
    if (!rows.length) { list.appendChild(el("p", "muted", TEXT.empty)); }
    rows.forEach(function (r, i) {
      var line = el("div", "alias-row");
      var sel = el("select", "alias-target");
      sel.setAttribute("aria-label", TEXT.target);
      (state.targets || []).forEach(function (t) {
        var o = el("option", "", targetLabel(t));
        o.value = t.path;
        sel.appendChild(o);
      });
      if (r.path) { sel.value = r.path; } else if (state.targets && state.targets[0]) { r.path = state.targets[0].path; }
      sel.addEventListener("change", function () { r.path = sel.value; schedulePreview(); });
      var input = el("input", "alias-name");
      input.type = "text";
      input.maxLength = (state.limits && state.limits.name) || 16;
      input.placeholder = TEXT.name;
      input.setAttribute("aria-label", TEXT.name);
      input.value = r.name || "";
      input.addEventListener("input", function () { r.name = input.value; schedulePreview(); });
      line.appendChild(input);
      line.appendChild(el("span", "alias-eq", "＝"));
      line.appendChild(sel);
      line.appendChild(button("ghost sm", TEXT.remove, function () { rows.splice(i, 1); renderRows(list); schedulePreview(); }));
      list.appendChild(line);
      (errors || []).filter(function (e) { return e.path === r.path && e.name === r.name; }).forEach(function (e) {
        list.appendChild(el("p", "alias-error", "⚠️ " + e.error));
      });
    });
  }

  function warningFor(prefix) {
    var w = (state.warnings || {})[prefix];
    return w || "";
  }

  function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(preview, 300);
  }
  function preview() {
    var input = box.querySelector("#alias-try");
    var out = box.querySelector("#alias-try-out");
    if (!input || !out) { return; }
    var text = input.value.trim();
    if (!text) { out.textContent = ""; return; }
    var body = draft();
    body.text = text;
    ctx.api("POST", "/api/aliases/preview", body).then(function (d) {
      out.textContent = d.command ? TEXT.becomes + d.result : TEXT.plain + (d.result !== text ? "（" + d.result + "）" : "");
      out.className = "alias-out " + (d.command ? "ok" : "");
    }).catch(function (e) { out.textContent = "⚠️ " + e.message; out.className = "alias-out bad"; });
  }

  function render(errors) {
    clear(box);
    var head = el("div", "card-head");
    head.appendChild(el("span", "tile", "⌨️"));
    var txt = el("div", "txt");
    txt.appendChild(el("h2", "", TEXT.title));
    txt.appendChild(el("p", "sub", TEXT.sub));
    head.appendChild(txt);
    box.appendChild(head);
    if (state.load_error) { box.appendChild(el("p", "note-line", "⚠️ " + state.load_error)); }

    var lab = el("label", "f", TEXT.prefix);
    lab.htmlFor = "alias-prefix";
    box.appendChild(lab);
    var sel = el("select", "");
    sel.id = "alias-prefix";
    (state.prefixes || []).forEach(function (p) {
      var o = el("option", "", p.label);
      o.value = p.value;
      sel.appendChild(o);
    });
    sel.value = state.prefix;
    box.appendChild(sel);
    var warn = el("p", "note-line alias-warn");
    function syncWarn() {
      var w = warningFor(sel.value);
      warn.textContent = w ? "⚠️ " + w : "";
      warn.classList.toggle("hidden", !w);
    }
    sel.addEventListener("change", function () { syncWarn(); schedulePreview(); });
    syncWarn();
    box.appendChild(warn);

    box.appendChild(el("label", "f", TEXT.names));
    var list = el("div", "alias-list");
    box.appendChild(list);
    renderRows(list, errors);
    box.appendChild(button("sm", TEXT.add, function () { rows.push({ path: "", name: "" }); renderRows(list); }));

    var sugg = state.suggestions || [];
    if (sugg.length) {
      var s = el("div", "alias-sugg");
      s.appendChild(el("span", "muted", TEXT.suggest));
      sugg.forEach(function (g) {
        s.appendChild(button("hd-chip", "「" + g.name + "」＝ " + g.command, function () {
          rows.push({ path: g.path, name: g.name });
          s.removeChild(this);
          renderRows(list);
          schedulePreview();
        }));
      });
      box.appendChild(s);
    }
    (state.conflicts || []).forEach(function (c) { box.appendChild(el("p", "note-line", "⚠️ " + fmt(TEXT.conflict, { n: c.name }))); });

    var tl = el("label", "f", TEXT.tryLabel);
    tl.htmlFor = "alias-try";
    box.appendChild(tl);
    var tryIn = el("input", "");
    tryIn.id = "alias-try";
    tryIn.type = "text";
    tryIn.placeholder = TEXT.tryHint;
    tryIn.addEventListener("input", schedulePreview);
    box.appendChild(tryIn);
    var out = el("p", "alias-out");
    out.id = "alias-try-out";
    out.setAttribute("aria-live", "polite");
    box.appendChild(out);

    var notes = el("ul", "muted alias-notes");
    TEXT.notes.forEach(function (n) { notes.appendChild(el("li", "", fmt(n, { n: (state.limits || {}).name || 16 }))); });
    box.appendChild(notes);

    box.appendChild(el("hr", "rule"));
    var actions = el("div", "row");
    var msg = el("span", "muted");
    actions.appendChild(button("primary", TEXT.save, function () {
      ctx.api("POST", "/api/aliases", draft()).then(function (d) {
        state.prefix = d.prefix;
        rows = rowsFrom(d.names);
        msg.textContent = TEXT.saved;
        if (ctx.toast) { ctx.toast(TEXT.saved); }
      }).catch(function (e) {
        var errs = (e.data && e.data.errors) || [];
        state.prefix = sel.value;
        render(errs);
        var m = box.querySelector(".alias-msg");
        if (m) { m.textContent = "⚠️ " + e.message; }
      });
    }));
    var armed = null;
    var resetBtn = button("", TEXT.reset, function () {
      if (!armed) {
        resetBtn.textContent = TEXT.resetAgain;
        armed = setTimeout(function () { armed = null; resetBtn.textContent = TEXT.reset; }, 4000);
        return;
      }
      clearTimeout(armed);
      armed = null;
      ctx.api("POST", "/api/aliases", { reset: true }).then(function () {
        if (ctx.toast) { ctx.toast(TEXT.resetDone); }
        open(box);
      }).catch(function (e) { msg.textContent = "⚠️ " + e.message; });
    });
    actions.appendChild(resetBtn);
    msg.className = "muted alias-msg";
    actions.appendChild(msg);
    box.appendChild(actions);
  }

  function open(node) {
    box = node || box;
    if (!box || !ctx) { return; }
    ctx.api("GET", "/api/aliases").then(function (d) {
      state = d;
      rows = rowsFrom(d.names);
      render([]);
    }).catch(function (e) { clear(box); box.appendChild(el("p", "note-line", "⚠️ " + e.message)); });
  }

  function init(c) { ctx = c; }

  root.SynoxAliases = { init: init, open: open };
})(typeof window !== "undefined" ? window : this);
