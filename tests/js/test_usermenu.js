// 左下角的使用者選單（src/synox/web/static/usermenu.js）：文字、鍵盤、開關、等重開回來。
// tests/test_web_restart.py 用 node 跑這個檔（不開瀏覽器、不開埠、不連網；DOM 是下面的小假貨）；退出碼 0＝全過。
"use strict";
const assert = require("assert");
const path = require("path");
const U = require(path.join(__dirname, "..", "..", "src", "synox", "web", "static", "usermenu.js"));

const tests = [];
function test(name, fn) { tests.push([name, fn]); }

// ── 小假 DOM：只有選單用到的那幾樣 ──────────────────────────────
function fakeDoc() {
  const doc = { activeElement: null, listeners: {}, body: null };
  doc.addEventListener = (t, fn) => { (doc.listeners[t] = doc.listeners[t] || []).push(fn); };
  doc.fire = (t, e) => (doc.listeners[t] || []).forEach((fn) => fn(e));
  doc.createElement = (tag) => node(doc, tag);
  doc.body = node(doc, "body");
  return doc;
}
function node(doc, tag, attrs) {
  const set = new Set();
  const n = {
    tagName: tag, attrs: Object.assign({}, attrs || {}), children: [], parentNode: null, listeners: {}, disabled: false,
    textContent: "",
    classList: {
      add: (...c) => c.forEach((x) => set.add(x)), remove: (...c) => c.forEach((x) => set.delete(x)),
      contains: (c) => set.has(c),
      toggle: (c, on) => { const v = on === undefined ? !set.has(c) : !!on; if (v) { set.add(c); } else { set.delete(c); } return v; }
    },
    setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    fire(t, e) { e = Object.assign({ target: this, preventDefault() { e.prevented = true; } }, e || {}); (this.listeners[t] || []).forEach((fn) => fn(e));
                 if (this.parentNode && !e.stop) { this.parentNode.fire(t, e); } return e; },
    appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
    insertBefore(c, ref) { c.parentNode = this; const i = this.children.indexOf(ref); this.children.splice(i < 0 ? this.children.length : i, 0, c); return c; },
    removeChild(c) { this.children = this.children.filter((x) => x !== c); c.parentNode = null; },
    contains(o) { for (let x = o; x; x = x.parentNode) { if (x === this) { return true; } } return false; },
    focus() { doc.activeElement = this; },
    click() { this.fire("click"); },
    querySelectorAll(sel) {
      const m = /^\[role="(\w+)"\]$/.exec(sel);
      const out = [];
      (function walk(p) { p.children.forEach((c) => { if (c.getAttribute("role") === m[1]) { out.push(c); } walk(c); }); })(this);
      return out;
    }
  };
  if (attrs && attrs.class) { attrs.class.split(" ").forEach((c) => set.add(c)); }
  return n;
}
function key(target, k, extra) { return target.fire("keydown", Object.assign({ key: k }, extra || {})); }

function setup(opts) {
  const doc = fakeDoc();
  const card = node(doc, "button", { "aria-expanded": "false" });
  const phone = node(doc, "button", { "aria-expanded": "false" });
  const menu = node(doc, "div", { role: "menu", class: "um hidden" });
  doc.body.appendChild(card); doc.body.appendChild(phone); doc.body.appendChild(menu);
  const head = menu.appendChild(node(doc, "div", { role: "none" }));
  head.appendChild(node(doc, "span"));
  const names = ["restart", "notify", "settings", "look", "help", "logout"];
  const items = {};
  names.forEach((nm) => {
    if (nm === "logout") { menu.appendChild(node(doc, "div", { role: "separator" })); }
    const it = menu.appendChild(node(doc, "button", { role: "menuitem" }));
    it.appendChild(node(doc, "span"));               // 圖示（點到它也算點到那一項）
    it.name = nm;
    items[nm] = it;
  });
  if (opts && opts.hide) { opts.hide.forEach((nm) => items[nm].classList.add("hidden")); }
  let opened = 0;
  const ctl = U.createMenu(doc, menu, [card, phone], { beforeOpen: () => { opened += 1; } });
  return { doc, card, phone, menu, items, ctl, opened: () => opened };
}

// ── 文字 ──────────────────────────────────────────────────────
test("uptime reads like a person would say it", () => {
  assert.strictEqual(U.uptimeText(5), "剛開好");
  assert.strictEqual(U.uptimeText(59 * 60), "已開 59 分鐘");
  assert.strictEqual(U.uptimeText(3 * 3600 + 1200), "已開 3 小時");
  assert.strictEqual(U.uptimeText(86400), "已開 1 天");
  assert.strictEqual(U.uptimeText(2 * 86400 + 5 * 3600), "已開 2 天 5 小時");
  assert.strictEqual(U.uptimeText(-3), "剛開好");
  assert.strictEqual(U.uptimeText("garbage"), "剛開好");
  assert.strictEqual(U.statusLine(7200), "SYNOX 運作中 · 已開 2 小時");
});

test("name, role and initial for owners, members and nameless accounts", () => {
  assert.deepStrictEqual(U.whoLines({ id: 100001, username: "", role: "admin", owner: true }),
                         { name: "id 100001", role: "擁有者", id: "", initial: "#" });
  assert.deepStrictEqual(U.whoLines({ id: 9, username: "alice", role: "member", owner: false }),
                         { name: "alice", role: "成員", id: "id 9", initial: "A" });
  assert.strictEqual(U.whoLines({ id: 1, role: "weird" }).role, "weird");
});

test("arrow keys wrap, Home/End jump, Tab cycles inside (focus trap)", () => {
  assert.strictEqual(U.moveIndex(-1, "ArrowDown", 5), 0);
  assert.strictEqual(U.moveIndex(-1, "ArrowUp", 5), 4);
  assert.strictEqual(U.moveIndex(4, "ArrowDown", 5), 0);
  assert.strictEqual(U.moveIndex(0, "ArrowUp", 5), 4);
  assert.strictEqual(U.moveIndex(2, "Home", 5), 0);
  assert.strictEqual(U.moveIndex(2, "End", 5), 4);
  assert.strictEqual(U.moveIndex(4, "Tab", 5, false), 0);
  assert.strictEqual(U.moveIndex(0, "Tab", 5, true), 4);
  assert.strictEqual(U.moveIndex(1, "a", 5), -1);
  assert.strictEqual(U.moveIndex(0, "ArrowDown", 0), -1);
});

// ── 開、關、鍵盤 ────────────────────────────────────────────────
test("clicking the card opens the menu and focuses the first item; clicking again closes", () => {
  const t = setup();
  t.card.click();
  assert.ok(t.ctl.isOpen() && !t.menu.classList.contains("hidden"));
  assert.strictEqual(t.card.getAttribute("aria-expanded"), "true");
  assert.strictEqual(t.phone.getAttribute("aria-expanded"), "false");
  assert.strictEqual(t.doc.activeElement, t.items.restart);
  assert.strictEqual(t.opened(), 1);
  t.card.click();
  assert.ok(!t.ctl.isOpen() && t.menu.classList.contains("hidden"));
  assert.strictEqual(t.card.getAttribute("aria-expanded"), "false");
  assert.strictEqual(t.doc.activeElement, t.card);              // 焦點回到卡片
});

test("arrow keys move through visible items only and wrap; hidden items are skipped", () => {
  const t = setup({ hide: ["restart", "notify"] });              // 成員：沒有重新啟動；沒有通知模組
  t.card.click();
  assert.strictEqual(t.doc.activeElement, t.items.settings);
  key(t.doc.activeElement, "ArrowDown");
  assert.strictEqual(t.doc.activeElement, t.items.look);
  key(t.doc.activeElement, "End");
  assert.strictEqual(t.doc.activeElement, t.items.logout);
  const e = key(t.doc.activeElement, "ArrowDown");
  assert.ok(e.prevented);
  assert.strictEqual(t.doc.activeElement, t.items.settings);    // 繞回第一個
  key(t.doc.activeElement, "ArrowUp");
  assert.strictEqual(t.doc.activeElement, t.items.logout);
  key(t.doc.activeElement, "Tab");
  assert.strictEqual(t.doc.activeElement, t.items.settings);    // Tab 不會跑出選單
  key(t.doc.activeElement, "Tab", { shiftKey: true });
  assert.strictEqual(t.doc.activeElement, t.items.logout);
});

test("ArrowUp on the card opens at the last item (the menu pops upward)", () => {
  const t = setup();
  const e = key(t.card, "ArrowUp");
  assert.ok(e.prevented && t.ctl.isOpen());
  assert.strictEqual(t.doc.activeElement, t.items.logout);
});

test("Escape closes and returns focus to whichever trigger opened it", () => {
  const t = setup();
  t.phone.click();
  assert.strictEqual(t.phone.getAttribute("aria-expanded"), "true");
  key(t.doc.activeElement, "Escape");
  assert.ok(!t.ctl.isOpen());
  assert.strictEqual(t.doc.activeElement, t.phone);
  t.card.click();
  t.doc.fire("keydown", { key: "Escape" });                     // 焦點不在選單裡也關得掉
  assert.ok(!t.ctl.isOpen());
});

test("clicking outside closes; clicking inside or on the trigger does not", () => {
  const t = setup();
  t.card.click();
  t.doc.fire("mousedown", { target: t.items.help });
  assert.ok(t.ctl.isOpen());
  t.doc.fire("mousedown", { target: t.card });
  assert.ok(t.ctl.isOpen());
  const outside = t.doc.body.appendChild(node(t.doc, "main"));
  t.doc.fire("mousedown", { target: outside });
  assert.ok(!t.ctl.isOpen());
});

test("choosing an item closes the menu (even when the icon inside it was clicked); Space activates", () => {
  const t = setup();
  let ran = 0;
  t.items.settings.addEventListener("click", () => { ran += 1; });
  t.card.click();
  t.items.settings.children[0].click();                          // 點到圖示：事件冒泡到那一項、再到選單
  assert.strictEqual(ran, 1);
  assert.ok(!t.ctl.isOpen());
  t.card.click();
  key(t.doc.activeElement, "End");
  key(t.doc.activeElement, "ArrowUp");
  assert.strictEqual(t.doc.activeElement, t.items.help);
  let help = 0;
  t.items.help.addEventListener("click", () => { help += 1; });
  key(t.doc.activeElement, " ");
  assert.strictEqual(help, 1);
  assert.ok(!t.ctl.isOpen());
});

// ── 確認框 ─────────────────────────────────────────────────────
test("the confirm dialog traps focus, cancels on Escape and puts focus back", () => {
  const doc = fakeDoc();
  const before = doc.body.appendChild(node(doc, "button"));
  before.focus();
  let result = null;
  const d = U.dialog(doc, {
    title: "重新啟動 SYNOX？", text: "說明", list: ["重開之後會生效：Telegram 的設定改了"], focus: 0,
    buttons: [{ label: "取消", run: (x) => { result = "no"; x.close(); } },
              { label: "重新啟動", primary: true, run: (x) => { result = "yes"; x.close(); } }],
    onEscape: (x) => { result = "esc"; x.close(); }
  });
  assert.strictEqual(d.box.getAttribute("role"), "alertdialog");
  assert.strictEqual(d.box.getAttribute("aria-modal"), "true");
  assert.strictEqual(doc.activeElement, d.buttons[0]);           // 預設停在「取消」
  key(d.buttons[0], "Tab");
  assert.strictEqual(doc.activeElement, d.buttons[1]);
  key(d.buttons[1], "Tab");
  assert.strictEqual(doc.activeElement, d.buttons[0]);           // 不會跑出去
  key(d.buttons[0], "Escape");
  assert.strictEqual(result, "esc");
  assert.strictEqual(doc.body.children.length, 1);               // 拿掉了
  assert.strictEqual(doc.activeElement, before);
});

// ── 等 SYNOX 回來 ───────────────────────────────────────────────
function fakeClock() {
  const c = { t: 0, queue: [] };
  c.now = () => c.t;
  c.schedule = (fn, ms) => { c.queue.push([c.t + ms, fn]); };
  c.run = async (n) => {
    for (let i = 0; i < n && c.queue.length; i++) {
      c.queue.sort((a, b) => a[0] - b[0]);
      const [at, fn] = c.queue.shift();
      c.t = at; fn();
      await new Promise((r) => setImmediate(r));
    }
  };
  return c;
}

test("restart watcher ignores the old process and connection errors, reloads when a new boot answers", async () => {
  const c = fakeClock();
  const answers = [{ boot: "old" }, "down", "down", { boot: "new" }];
  const calls = [];
  let back = 0, timeout = 0;
  U.watchRestart({
    oldBoot: "old", now: c.now, schedule: c.schedule, interval: 1000, timeoutMs: 60000,
    fetch: (u, o) => {
      calls.push([u, o.cache]);
      const a = answers.shift();
      return a === "down" ? Promise.reject(new TypeError("Failed to fetch"))
                          : Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, boot: a.boot }) });
    },
    onBack: () => { back += 1; }, onTimeout: () => { timeout += 1; }
  });
  await c.run(10);
  assert.strictEqual(back, 1);
  assert.strictEqual(timeout, 0);
  assert.strictEqual(calls.length, 4);
  assert.deepStrictEqual(calls[0], ["/alive", "no-store"]);
});

test("restart watcher gives up after the timeout with how long it waited", async () => {
  const c = fakeClock();
  let waited = null, back = 0;
  U.watchRestart({
    oldBoot: "old", now: c.now, schedule: c.schedule, interval: 1500, timeoutMs: 6000,
    fetch: () => Promise.reject(new TypeError("down")),
    onBack: () => { back += 1; }, onTimeout: (s) => { waited = s; }
  });
  await c.run(20);
  assert.strictEqual(back, 0);
  assert.strictEqual(waited, 6);
  assert.strictEqual(c.queue.length, 0);                          // 停了，不會一直問下去
});

(async () => {
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(); console.log("ok - " + name); }
    catch (e) { failed += 1; console.log("not ok - " + name + "\n  " + (e && e.stack || e)); }
  }
  console.log(failed ? failed + " failed" : "all " + tests.length + " passed");
  process.exit(failed ? 1 : 0);
})();
