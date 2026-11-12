/* 網頁「工具」頁（docs/tools.md「網頁工具頁」；後端 src/synox/web/toolpage.py）。
   server.py 的 render_app 把這個檔放進 app.html 的 include 標記那裡（同一個 nonce 的 script）。
   版面：左邊「群組」→ 群組裡的工具用分頁（tab）→ 每個工具：說明、指令（參數說明）、輸入、執行。
   群組可以自己編輯（新增／改名／刪除／排序、把工具移到別的群組），存在每個人自己的偏好（POST /api/tools/layout）。
   文字一律 textContent；沒有 inline 事件；執行一律經 /api/chat/tools/send（dispatcher、同一個 authorize）。 */
(function () {
  "use strict";

  var S = {
    ctx: null, data: null, tools: {}, layout: { groups: [] }, group: null, tab: {},
    editing: false, draft: null, rev: 0, seq: 0
  };
  var SEL_KEY = "synox.tools.selected";
  var EFFECT = { read: "唯讀", write: "會寫入", danger: "危險：會先問你" };
  var KIND = { text: "文字", int: "整數", number: "數字", bool: "是／否", path: "檔名", choice: "選一個" };

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }
  function clear(node) { while (node.firstChild) { node.removeChild(node.firstChild); } }
  function button(text, cls, onClick, title) {
    var b = el("button", cls || "", text);
    b.type = "button";
    if (title) { b.title = title; b.setAttribute("aria-label", title); }
    if (onClick) { b.addEventListener("click", onClick); }
    return b;
  }
  function api(method, path, body) { return S.ctx.api(method, path, body); }
  function toast(text) { S.ctx.toast(text); }
  function remember() {
    try { localStorage.setItem(SEL_KEY, JSON.stringify({ group: S.group, tab: S.tab })); } catch (e) { /* 私密視窗 */ }
  }
  function recall() {
    try {
      var v = JSON.parse(localStorage.getItem(SEL_KEY) || "null");
      if (v && typeof v === "object") { S.group = v.group || null; S.tab = v.tab || {}; }
    } catch (e) { /* 沒有就算了 */ }
  }
  function copyGroups(groups) {
    return groups.map(function (g) { return { id: g.id, title: g.title, tools: g.tools.slice(), auto: !!g.auto }; });
  }
  function groupsNow() { return S.editing ? S.draft : S.layout.groups; }
  function currentGroup() {
    var groups = groupsNow();
    var g = null;
    groups.forEach(function (x) { if (x.id === S.group) { g = x; } });
    return g || groups[0] || null;
  }

  // ── 載入 ──────────────────────────────────────────────────────────
  function load(ctx) {
    S.ctx = ctx;
    S.editing = false; S.draft = null;          // 離開工具頁又回來：沒存的編輯不算
    if (!S.data) { recall(); }
    api("GET", "/api/chat/tools/events?since=0").then(function (d) { S.rev = d.rev; }).catch(function () {});
    return api("GET", "/api/tools").then(function (d) {
      S.data = d;
      S.tools = {};
      d.packs.concat(d.groups).forEach(function (t) { S.tools[t.id] = t; });
      S.layout = d.layout || { groups: [] };
      if (d.layout_error) { toast(d.layout_error); }
      render();
    }).catch(function (e) { toast(e.message); });
  }

  function render() {
    var root = S.ctx.root;
    clear(root);
    var groups = groupsNow();
    if (!Object.keys(S.tools).length && !S.editing) {
      root.appendChild(el("p", "tp-empty", "你現在沒有可以用的功能；請管理員替你開。"));
      return;
    }
    var g = currentGroup();
    if (g) { S.group = g.id; }
    var wrap = el("div", "tp" + (S.editing ? " tp-editing" : ""));
    wrap.appendChild(renderSide(groups, g));
    var main = el("section", "tp-main");
    if (S.editing) { main.appendChild(renderArrange(g)); }
    else { renderGroup(main, g); }
    wrap.appendChild(main);
    root.appendChild(wrap);
  }

  // ── 左邊：群組 ────────────────────────────────────────────────────
  function renderSide(groups, current) {
    var side = el("nav", "tp-side");
    side.setAttribute("aria-label", "工具群組");
    var head = el("div", "tp-side-head");
    head.appendChild(el("span", "tp-side-title", S.editing ? "編輯群組" : "群組"));
    if (!S.editing) { head.appendChild(button("編輯", "ghost sm", startEdit, "編輯群組：新增、改名、刪除、排序、移動工具")); }
    side.appendChild(head);
    var list = el("ul", "tp-groups");
    groups.forEach(function (g, i) {
      var li = el("li");
      if (S.editing) { li.appendChild(groupEditor(g, i, groups.length)); }
      else {
        var b = button("", "tp-group" + (current && g.id === current.id ? " active" : ""), function () {
          S.group = g.id; remember(); render();
        });
        b.appendChild(el("span", "tp-gname", g.title));
        b.appendChild(el("span", "tp-count", g.tools.length));
        if (current && g.id === current.id) { b.setAttribute("aria-current", "true"); }
        li.appendChild(b);
      }
      list.appendChild(li);
    });
    side.appendChild(list);
    if (S.editing) {
      side.appendChild(button("＋ 新增群組", "tp-add", addGroup));
      var bar = el("div", "tp-editbar");
      bar.appendChild(button("儲存排版", "primary", saveEdit));
      bar.appendChild(button("取消", "", cancelEdit));
      bar.appendChild(button("回到建議的排法", "ghost", resetLayout, "丟掉自己的排法，照每個工具建議的群組重排"));
      side.appendChild(bar);
      var msg = el("p", "msgline tp-editmsg");
      msg.id = "tp-editmsg";
      side.appendChild(msg);
    }
    return side;
  }

  function groupEditor(g, i, n) {
    var row = el("div", "tp-gedit" + (g.id === S.group ? " active" : ""));
    var input = el("input");
    input.type = "text"; input.value = g.title; input.maxLength = 24;
    input.setAttribute("aria-label", "群組名稱");
    input.addEventListener("input", function () { g.title = input.value; });
    input.addEventListener("focus", function () {
      if (S.group !== g.id) { S.group = g.id; refreshArrange(); markEditing(); }
    });
    row.appendChild(input);
    var tools = el("div", "tp-gtools");
    tools.appendChild(el("span", "tp-count", g.tools.length));
    var up = button("↑", "ghost sm", function () { moveGroup(i, -1); }, "往上移");
    var down = button("↓", "ghost sm", function () { moveGroup(i, 1); }, "往下移");
    up.disabled = i === 0; down.disabled = i === n - 1;
    tools.appendChild(up); tools.appendChild(down);
    tools.appendChild(button("刪除", "danger sm", function () { deleteGroup(g); }, "刪除群組（裡面的工具回到建議的群組）"));
    row.appendChild(tools);
    return row;
  }
  function markEditing() {
    Array.prototype.forEach.call(S.ctx.root.querySelectorAll(".tp-gedit"), function (r, i) {
      r.classList.toggle("active", S.draft[i] && S.draft[i].id === S.group);
    });
  }

  // ── 編輯 ──────────────────────────────────────────────────────────
  function startEdit() {
    S.editing = true;
    S.draft = copyGroups(S.layout.groups);
    render();
  }
  function cancelEdit() { S.editing = false; S.draft = null; render(); }
  function editMsg(text) { var m = document.getElementById("tp-editmsg"); if (m) { m.textContent = text; } }
  function moveGroup(i, step) {
    var j = i + step;
    if (j < 0 || j >= S.draft.length) { return; }
    var g = S.draft.splice(i, 1)[0];
    S.draft.splice(j, 0, g);
    render();
  }
  function newId() {
    S.seq += 1;
    return ("g" + Date.now().toString(36) + S.seq.toString(36)).slice(0, 32);
  }
  function uniqueTitle(base) {
    var titles = S.draft.map(function (g) { return g.title.trim(); });
    var t = base, n = 2;
    while (titles.indexOf(t) >= 0) { t = base + " " + n; n += 1; }
    return t;
  }
  function addGroup() {
    if (S.draft.length >= 30) { editMsg("群組最多 30 個。"); return; }
    var g = { id: newId(), title: uniqueTitle("新群組"), tools: [] };
    S.draft.push(g);
    S.group = g.id;
    render();
    var inputs = S.ctx.root.querySelectorAll(".tp-gedit input");
    if (inputs.length) { inputs[inputs.length - 1].focus(); inputs[inputs.length - 1].select(); }
  }
  function suggestedGroup(toolId, except) {
    var t = S.tools[toolId] || {};
    var title = (t.category || "").trim() || "未分類";
    var found = null;
    S.draft.forEach(function (g) { if (g !== except && g.title.trim() === title) { found = g; } });
    if (!found) {
      found = { id: newId(), title: uniqueTitle(title), tools: [] };
      S.draft.push(found);
    }
    return found;
  }
  function deleteGroup(g) {
    var i = S.draft.indexOf(g);
    if (i < 0) { return; }
    S.draft.splice(i, 1);
    g.tools.forEach(function (tid) { suggestedGroup(tid, g).tools.push(tid); });
    if (S.group === g.id) { S.group = S.draft.length ? S.draft[Math.max(0, i - 1)].id : null; }
    editMsg(g.tools.length ? "「" + g.title + "」刪掉了，裡面的工具回到建議的群組（按「儲存排版」才算數）。" :
      "「" + g.title + "」刪掉了（按「儲存排版」才算數）。");
    render();
  }
  function moveTool(g, i, step) {
    var j = i + step;
    if (j < 0 || j >= g.tools.length) { return; }
    var t = g.tools.splice(i, 1)[0];
    g.tools.splice(j, 0, t);
    refreshArrange();
  }
  function moveToGroup(g, tid, targetId) {
    var target = null;
    S.draft.forEach(function (x) { if (x.id === targetId) { target = x; } });
    if (!target || target === g) { return; }
    g.tools.splice(g.tools.indexOf(tid), 1);
    target.tools.push(tid);
    render();
  }
  function saveEdit() {
    var titles = {};
    for (var i = 0; i < S.draft.length; i += 1) {
      var t = S.draft[i].title.trim();
      if (!t) { editMsg("❌ 群組名稱不能空白。"); return; }
      if (titles[t]) { editMsg("❌ 群組名稱「" + t + "」重複了。"); return; }
      titles[t] = true;
    }
    var body = { groups: S.draft.map(function (g) { return { id: g.id, title: g.title.trim(), tools: g.tools }; }) };
    api("POST", "/api/tools/layout", body).then(function (d) {
      S.layout = d.layout; S.editing = false; S.draft = null;
      render();
      toast("排版存好了（只改你自己的畫面）");
    }).catch(function (e) { editMsg("❌ " + e.message); });
  }
  function resetLayout() {
    api("POST", "/api/tools/layout", { reset: true }).then(function (d) {
      S.layout = d.layout; S.editing = false; S.draft = null; S.group = null;
      render();
      toast("回到建議的排法了");
    }).catch(function (e) { editMsg("❌ " + e.message); });
  }

  // 編輯時的主畫面：這個群組裡的工具（排序、移到別的群組）
  function renderArrange(g) {
    var card = el("div", "card tp-arrange");
    card.id = "tp-arrange";
    fillArrange(card, g);
    return card;
  }
  function refreshArrange() {
    var card = document.getElementById("tp-arrange");
    if (card) { clear(card); fillArrange(card, currentGroup()); }
  }
  function fillArrange(card, g) {
    card.appendChild(el("h2", "", g ? "排列「" + (g.title.trim() || "（沒有名字）") + "」裡的工具" : "還沒有群組"));
    card.appendChild(el("p", "sub", "點一下群組的名稱，就能在這裡排它裡面的工具。只改你自己的畫面，不會動到工具本身；別人的排法是分開的。"));
    if (!g) { return; }
    if (!g.tools.length) {
      card.appendChild(el("p", "tp-empty", "這個群組還沒有工具：到別的群組，用「移到」把工具放進來。"));
      return;
    }
    var list = el("ul", "tp-arrange-list");
    g.tools.forEach(function (tid, i) {
      var t = S.tools[tid] || { title: tid };
      var li = el("li");
      li.appendChild(el("span", "tp-aname", t.title));
      var acts = el("div", "tp-aacts");
      var up = button("↑", "ghost sm", function () { moveTool(g, i, -1); }, "往前移");
      var down = button("↓", "ghost sm", function () { moveTool(g, i, 1); }, "往後移");
      up.disabled = i === 0; down.disabled = i === g.tools.length - 1;
      acts.appendChild(up); acts.appendChild(down);
      var sel = el("select");
      sel.setAttribute("aria-label", "把「" + t.title + "」移到別的群組");
      var first = el("option", "", "移到…");
      first.value = "";
      sel.appendChild(first);
      S.draft.forEach(function (x) {
        if (x === g) { return; }
        var o = el("option", "", x.title.trim() || "（沒有名字）");
        o.value = x.id;
        sel.appendChild(o);
      });
      sel.addEventListener("change", function () { if (sel.value) { moveToGroup(g, tid, sel.value); } });
      acts.appendChild(sel);
      li.appendChild(acts);
      list.appendChild(li);
    });
    card.appendChild(list);
  }

  // ── 主畫面：群組裡的工具分頁 ──────────────────────────────────────
  function renderGroup(main, g) {
    if (!g) { main.appendChild(el("p", "tp-empty", "還沒有群組。按左邊的「編輯」新增一個。")); return; }
    var head = el("div", "tp-group-head");
    head.appendChild(el("h2", "", g.title));
    head.appendChild(el("span", "muted", g.tools.length + " 個工具" + (g.auto ? "・照工具建議的群組" : "")));
    main.appendChild(head);
    if (!g.tools.length) {
      main.appendChild(el("p", "tp-empty", "這個群組還沒有工具。按左邊的「編輯」把工具移進來。"));
      return;
    }
    var active = S.tab[g.id];
    if (g.tools.indexOf(active) < 0) { active = g.tools[0]; }
    var tabs = el("div", "tp-tabs");
    tabs.setAttribute("role", "tablist");
    tabs.setAttribute("aria-label", g.title + " 的工具");
    var buttons = [];
    g.tools.forEach(function (tid) {
      var t = S.tools[tid] || { title: tid };
      var b = button(t.title, "tp-tab", function () { S.tab[g.id] = tid; remember(); render(); focusTab(); });
      b.setAttribute("role", "tab");
      b.id = "tp-tab-" + tid;
      b.setAttribute("aria-controls", "tp-panel");
      b.setAttribute("aria-selected", tid === active ? "true" : "false");
      b.tabIndex = tid === active ? 0 : -1;
      if (t.status && t.status !== "已連接") { b.appendChild(el("span", "tp-dot", "")); }
      buttons.push(b);
      tabs.appendChild(b);
    });
    tabs.addEventListener("keydown", function (ev) {
      var i = buttons.indexOf(document.activeElement);
      if (i < 0) { return; }
      var j = ev.key === "ArrowRight" ? i + 1 : ev.key === "ArrowLeft" ? i - 1 : ev.key === "Home" ? 0 :
        ev.key === "End" ? buttons.length - 1 : -2;
      if (j === -2) { return; }
      ev.preventDefault();
      j = (j + buttons.length) % buttons.length;
      buttons[j].click();
    });
    main.appendChild(tabs);
    var panel = el("div", "card tp-panel");
    panel.id = "tp-panel";
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", "tp-tab-" + active);
    renderTool(panel, S.tools[active]);
    main.appendChild(panel);
  }
  function focusTab() {
    var b = S.ctx.root.querySelector('.tp-tab[aria-selected="true"]');
    if (b) { b.focus(); }
  }

  function renderTool(panel, t) {
    if (!t) { return; }
    var head = el("div", "tp-head");
    var h = el("h2", "", t.title);
    var badge = null;
    if (t.status) {
      badge = el("span", "badge " + (t.status === "已連接" ? "ok" : "warn"), t.status);
      h.appendChild(badge);
    }
    if (t.stage_label) {                  // 穩定度（pack.json 的 stage；符號＋字，不只靠顏色）
      var stage = el("span", "badge stage", t.stage_label);
      if (t.stage_text) { stage.title = t.stage_text; }
      h.appendChild(stage);
    }
    head.appendChild(h);
    if (t.name) { head.appendChild(el("span", "tp-meta", t.name + " " + (t.version || "") + "・" + (t.kind || ""))); }
    panel.appendChild(head);

    var about = el("section", "tp-about");
    about.appendChild(el("div", "section-label", "說明"));
    if (t.summary) { about.appendChild(el("p", "", t.summary)); }
    if (t.description && t.description !== t.summary) { about.appendChild(el("p", "sub", "什麼時候用：" + t.description)); }
    panel.appendChild(about);

    if (t.connect) { panel.appendChild(connectBlock(t, badge)); }
    else if (t.missing && t.missing.length) {
      panel.appendChild(el("p", "note-line", "還沒連接（缺 " + t.missing.join("、") + "）；請擁有者到工具頁按「連接」。"));
    }
    if (t.panel) {
      var frame = el("iframe", "panel");
      frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
      frame.setAttribute("title", t.title + " 面板");
      frame.src = t.panel;
      panel.appendChild(frame);
    }
    var cmds = t.commands || [];
    panel.appendChild(el("div", "section-label", "指令（" + cmds.length + "）"));
    var list = el("div", "tp-cmds");
    var openOne = cmds.filter(function (c) { return c.default; })[0] || cmds[0];
    cmds.forEach(function (c) { list.appendChild(commandCard(c, c === openOne, t)); });
    panel.appendChild(list);
  }

  // ── 工具健康（docs/tool-health.md）：狀態徽章、原因、擁有者的「重新檢查」「解除隔離」 ─────
  var HEALTH_MARK = { broken: "⏸", needs_action: "🛠", quarantined: "⛔" };
  function healthBlock(c, t) {
    var box = el("div", "tp-health");
    c.health.forEach(function (h) {
      var line = el("p", "note-line");
      line.appendChild(el("strong", "", (HEALTH_MARK[h.state] || "⚠️") + " " + h.label + (h.personal ? "（只對你）" : "")));
      line.appendChild(el("span", "", "：" + (h.code_label || h.code) + (h.reason ? "——" + h.reason : "")));
      if (h.trial) { line.appendChild(el("span", "muted", "（試用中：AI 這次會再用一次）")); }
      else if (h.next_check) { line.appendChild(el("span", "muted", "（下次自動檢查 " + h.next_check.replace("T", " ").slice(0, 16) + "）")); }
      box.appendChild(line);
      if (!t || !t.health_admin) { return; }
      var row = el("div", "tp-actions");
      var msg = el("span", "msgline");
      function act(action) {
        api("POST", "/api/tools/health", { key: h.key, action: action }).then(function () {
          msg.textContent = action === "release" ? "已解除，重新整理看最新狀態。" : "已經開始檢查，稍後重新整理看結果。";
        }).catch(function (e) { msg.textContent = "❌ " + e.message; });
      }
      if (h.state !== "quarantined") { row.appendChild(button("重新檢查", "sm", function () { act("recheck"); })); }
      row.appendChild(button(h.state === "quarantined" ? "解除隔離" : "標成正常", "sm", function () { act("release"); }));
      row.appendChild(msg);
      box.appendChild(row);
    });
    return box;
  }

  // ── 一個指令：說明、參數、輸入、執行 ────────────────────────────────
  function commandCard(c, open, t) {
    var box = el("details", "tp-cmd" + (c.effect === "danger" ? " is-danger" : ""));
    box.open = !!open;
    var sum = el("summary");
    sum.appendChild(el("code", "", c.command));
    var badge = el("span", "badge" + (c.effect === "danger" ? " danger" : c.effect === "write" ? " write" : ""),
                   EFFECT[c.effect] || c.effect);
    sum.appendChild(badge);
    if (c.health && c.health.length) {
      sum.appendChild(el("span", "badge warn", (HEALTH_MARK[c.health[0].state] || "⚠️") + " " + c.health[0].label));
    }
    sum.appendChild(el("span", "tp-csum", c.summary || ""));
    box.appendChild(sum);

    var body = el("div", "tp-cbody");
    if (c.health && c.health.length) { body.appendChild(healthBlock(c, t)); }
    var notes = [];
    if (c.confirm) { notes.push("AI 要用它之前會先問你"); }
    if (c.ai === false) { notes.push("不給 AI 用，只有你自己按"); }
    if (c.asks_code) { notes.push("執行後會再問你驗證碼"); }
    if (notes.length) { body.appendChild(el("p", "muted", notes.join("・"))); }

    var form = el("form", "tp-form");
    form.setAttribute("novalidate", "");
    var inputs = [];
    var fields = c.fields || [];
    if (fields.length) {
      fields.forEach(function (f) { inputs.push(fieldInput(form, f, c)); });
    } else if (c.usage) {
      inputs.push(rawInput(form, c));
    } else {
      form.appendChild(el("p", "muted", "這個指令不用參數，直接按執行。"));
    }
    var preview = el("p", "tp-line");
    var line = el("code");
    preview.appendChild(el("span", "", "會送出："));
    preview.appendChild(line);
    var actions = el("div", "tp-actions");
    var run = el("button", c.effect === "danger" ? "danger" : "primary", "執行");
    run.type = "submit";
    actions.appendChild(run);
    actions.appendChild(preview);
    form.appendChild(actions);
    var confirmBox = el("div", "tp-confirm hidden");
    form.appendChild(confirmBox);
    var msg = el("p", "msgline");
    form.appendChild(msg);
    var out = el("div", "result hidden");
    function update() { line.textContent = commandText(c, inputs); }
    inputs.forEach(function (it) { it.node.addEventListener("input", update); it.node.addEventListener("change", update); });
    update();
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var missing = inputs.filter(function (it) { return it.field && it.field.required && !it.value(); })
        .map(function (it) { return it.field.label; });
      if (missing.length) { msg.textContent = "要先填：" + missing.join("、"); return; }
      msg.textContent = "";
      var text = commandText(c, inputs);
      if (c.effect === "danger") { askDanger(confirmBox, text, function () { send(text, run, out); }); return; }
      send(text, run, out);
    });
    body.appendChild(form);
    body.appendChild(out);
    box.appendChild(body);
    return box;
  }

  function fieldInput(form, f, c) {
    var id = "tp-f-" + c.path.replace(/[^a-z0-9_]/gi, "_") + "-" + f.name;
    var wrap = el("div", "tp-field");
    var lab = el("label", "tp-flabel");
    lab.htmlFor = id;
    lab.appendChild(el("span", "", f.label));
    lab.appendChild(el("span", "tp-req" + (f.required ? " on" : ""), f.required ? "必填" : "選填"));
    wrap.appendChild(lab);
    var node;
    if (f.kind === "bool" || (f.choices && f.choices.length)) {
      node = el("select");
      var opts = f.kind === "bool" ? [["true", "是"], ["false", "否"]] :
        f.choices.map(function (x) { return [x, x]; });
      if (!f.required) { opts.unshift(["", "（不填）"]); }
      opts.forEach(function (o) { var op = el("option", "", o[1]); op.value = o[0]; node.appendChild(op); });
      var d = String(f.default || "").toLowerCase();
      if (f.kind === "bool" && d) { node.value = ["true", "yes", "1", "是", "y", "on"].indexOf(d) >= 0 ? "true" : "false"; }
      else if (f.default) {
        f.choices.forEach(function (x) { if (x.toLowerCase() === d) { node.value = x; } });
      }
    } else {
      node = el("input");
      node.type = "text";
      if (f.kind === "int") { node.inputMode = "numeric"; }
      if (f.kind === "number") { node.inputMode = "decimal"; }
      if (f.default) { node.value = f.default; }
      node.placeholder = f.kind === "path" ? "你自己資料夾裡的檔名" : (KIND[f.kind] || "");
      node.autocomplete = "off";
    }
    node.id = id;
    node.name = f.name;
    wrap.appendChild(node);
    var hint = [];
    if (f.help) { hint.push(f.help); }
    hint.push("參數 " + f.name + "・" + (KIND[f.kind] || f.kind) + (f.default ? "・預設 " + f.default : ""));
    wrap.appendChild(el("span", "tp-fhint", hint.join("　")));
    form.appendChild(wrap);
    return {
      field: f, node: node,
      value: function () { return String(node.value || "").replace(/\s+/g, " ").trim(); }
    };
  }
  function rawInput(form, c) {
    var wrap = el("div", "tp-field");
    var id = "tp-raw-" + c.path.replace(/[^a-z0-9_]/gi, "_");
    var lab = el("label", "tp-flabel", "參數");
    lab.htmlFor = id;
    wrap.appendChild(lab);
    var node = el("input");
    node.type = "text"; node.id = id; node.placeholder = c.usage; node.autocomplete = "off";
    wrap.appendChild(node);
    wrap.appendChild(el("span", "tp-fhint", "照這個順序填：" + c.usage));
    form.appendChild(wrap);
    return { field: null, node: node, value: function () { return String(node.value || "").replace(/\s+/g, " ").trim(); } };
  }
  // 表單 → 指令文字：有宣告欄位的一律 key=value（kit.parse_args／SDK Forms 都收）；跟預設值一樣的不送（SYNOX 會自己補）
  function commandText(c, inputs) {
    var parts = [c.command];
    inputs.forEach(function (it) {
      var v = it.value();
      if (!v) { return; }
      if (!it.field) { parts.push(v); return; }
      if (it.field.default && v.toLowerCase() === String(it.field.default).toLowerCase()) { return; }
      parts.push(it.field.name + "=" + v);
    });
    return parts.join(" ");
  }
  function askDanger(box, text, go) {
    clear(box);
    box.classList.remove("hidden");
    box.appendChild(el("p", "", "這是危險的指令（可能刪掉或改掉資料、不能復原）。確定要執行嗎？"));
    var line = el("p", "");
    line.appendChild(el("code", "", text));
    box.appendChild(line);
    var row = el("div", "row");
    var yes = button("確定執行", "danger", function () { box.classList.add("hidden"); go(); });
    row.appendChild(yes);
    row.appendChild(button("取消", "", function () { box.classList.add("hidden"); }));
    box.appendChild(row);
    yes.focus();
  }
  function send(text, btn, out) {
    btn.disabled = true;
    var since = S.rev;
    api("POST", "/api/chat/tools/send", { text: text }).then(function () {
      return new Promise(function (ok) { setTimeout(ok, 500); }).then(function () {
        return api("GET", "/api/chat/tools/events?since=" + since);
      });
    }).then(function (d) {
      S.rev = d.rev;
      clear(out);
      out.classList.remove("hidden");
      var replies = d.messages.filter(function (m) { return m.from !== "me"; });
      if (!replies.length) { out.textContent = "（送出了；回覆可能要等一下，到對話頁的「🧰 工具頁」看）"; }
      replies.forEach(function (m) {
        out.appendChild(S.ctx.renderMessage(m, "tools", function () { toast("按了；結果在對話頁的「🧰 工具頁」"); }));
      });
    }).catch(function (e) { toast(e.message); }).then(function () { btn.disabled = false; });
  }

  // 「連接」：auth.fields 的表單。secret 用 password 輸入、伺服器永遠不回值（只回有填、最後 4 碼）；留空＝沿用原值。
  function connectBlock(p, badge) {
    var box = el("div", "connect");
    var need = p.missing && p.missing.length;
    var open = button(need ? "🔌 連接" : "🔌 連接設定", need ? "primary sm" : "sm");
    var form = el("form", "hidden");
    var msg = el("div", "muted");
    box.appendChild(open); box.appendChild(form); box.appendChild(msg);
    function build(view) {
      clear(form);
      var inputs = {};
      view.fields.forEach(function (f) {
        var lab = el("label");
        var title = f.label + (f.required ? "" : "（選填）");
        if (f.set) { title += f.kind === "file" ? "　✅ 已上傳（" + f.size + " 字）" : (f.secret ? "　✅ 有填" + (f.last4 ? "（…" + f.last4 + "）" : "") : ""); }
        lab.appendChild(el("span", "", title));
        var input = el("input");
        if (f.kind === "file") { input.type = "file"; }
        else {
          input.type = f.secret ? "password" : "text";
          input.autocomplete = f.secret ? "new-password" : "off";
          if (!f.secret && f.value) { input.value = f.value; }
          if (f.set && f.secret) { input.placeholder = "留空＝沿用原本的"; }
        }
        lab.appendChild(input);
        if (f.help) { lab.appendChild(el("span", "muted", f.help)); }
        form.appendChild(lab);
        inputs[f.name] = { field: f, input: input };
      });
      var save = el("button", "primary", "存起來"); save.type = "submit";
      form.appendChild(save);
      form.onsubmit = function (ev) {
        ev.preventDefault();
        var values = {}, reads = [];
        Object.keys(inputs).forEach(function (name) {
          var it = inputs[name];
          if (it.field.kind === "file") {
            var file = it.input.files && it.input.files[0];
            if (file) { reads.push(file.text().then(function (t) { values[name] = t; })); }
          } else { values[name] = it.input.value; }
        });
        save.disabled = true;
        Promise.all(reads).then(function () {
          return api("POST", "/api/pack-secrets/" + encodeURIComponent(p.name), { values: values });
        }).then(function (d) {
          msg.textContent = d.message;
          if (badge) { badge.textContent = d.status; badge.className = "badge " + (d.connected ? "ok" : "warn"); }
          p.status = d.status;
          build(d);
        }).catch(function (e) { msg.textContent = "❌ " + e.message; })
          .then(function () { save.disabled = false; });
      };
    }
    open.addEventListener("click", function () {
      if (!form.classList.contains("hidden")) { form.classList.add("hidden"); return; }
      api("GET", "/api/pack-secrets/" + encodeURIComponent(p.name)).then(function (d) {
        build(d); form.classList.remove("hidden");
        msg.textContent = "存在這台電腦的保管箱（密文）；為了安全，Telegram 不收這些。";
      }).catch(function (e) { msg.textContent = "❌ " + e.message; });
    });
    return box;
  }

  window.SynoxTools = { load: load, edit: function () { if (S.data && !S.editing) { startEdit(); } } };
})();
