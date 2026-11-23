// 不開瀏覽器檢查一步一步安裝教學（docs/guide/index.html）。只用 Node 內建的東西，不連網、不改任何檔。
//
//     node scripts/check_guide.js [docs/guide/index.html] [--steps]
//
// 做法：把頁面裡的程式放進一個假的瀏覽器（只有它用得到的那幾樣 DOM）跑起來，然後檢查：
//   1. 語法（等於 node --check）、兩段 JSON（tour-steps、release-info）讀得進來；
//   2. 每一步的示意畫面都有、要標出來的東西（targets）在示意畫面裡找得到、文字與示意畫面的 HTML 標籤成對；
//   3. 每一個 #step-… 都到得了那一步（主線的號碼、#step-<id>、改版前的網址、頁面裡寫死的連結）；
//   4. 岔路：每個分岔的每一條路都進得去，一路「下一步」會接回主線，從那裡一路「上一步」原路回到分岔；
//      還沒選路時分岔那一步的「下一步」不能按；選讀的「回去／接著做」都指得到。
// --steps：另外印出每一步的標題（主線號碼、岔路、選讀）。有問題＝結束碼 1。
// tests/test_build_guide.py 在有裝 Node 的電腦上會跑這支（沒裝就略過）；發版時照 docs/release-playbook.md 第 7 節跑一次。
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const args = process.argv.slice(2);
const listSteps = args.includes("--steps");
const file = args.find((a) => !a.startsWith("--")) || path.join(__dirname, "..", "docs", "guide", "index.html");
const html = fs.readFileSync(file, "utf8");

const jsonBlocks = {};
let main = "";
for (const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
  const tag = m[0].slice(0, m[0].indexOf(">") + 1);
  const id = /id="([^"]+)"/.exec(tag);
  if (/type="application\/json"/.test(tag)) { jsonBlocks[id ? id[1] : ""] = m[1]; JSON.parse(m[1]); } else { main = m[1]; }
}
if (!main) { throw new Error("找不到頁面的 <script>"); }
new vm.Script(main, { filename: "docs/guide/index.html <script>" });       // 語法不對會在這裡丟例外

// 假的瀏覽器：一個分頁（storage 可以沿用上一個分頁的，＝同一台電腦再開一次）
function boot(hash, storages) {
  const els = {};
  const warnings = [];
  function makeEl() {
    const first = { textContent: "" }, last = { textContent: "" }, attrs = {};
    return {
      innerHTML: "", textContent: "", hidden: false, disabled: false, open: false, style: {}, firstChild: first, lastChild: last,
      classList: { add() {}, remove() {} },
      setAttribute(k, v) { attrs[k] = v; }, getAttribute(k) { return attrs[k]; }, removeAttribute(k) { delete attrs[k]; },
      addEventListener() {}, appendChild() {}, focus() {},
      querySelector(sel) {
        if (sel === "svg") { return { style: {} }; }
        const m = /^\[data-hl="([^"]+)"\]$/.exec(sel);
        return m && this.innerHTML.indexOf('data-hl="' + m[1] + '"') >= 0 ? makeEl() : null;
      },
    };
  }
  const newStorage = () => { const d = {}; return { getItem: (k) => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); } }; };
  const store = storages || { local: newStorage(), session: newStorage() };
  const win = { localStorage: store.local, sessionStorage: store.session, console: { warn: (m) => warnings.push(m) }, scrollTo() {}, listeners: {} };
  win.window = win;
  win.addEventListener = (type, fn) => { win.listeners[type] = fn; };
  const location = {
    value: hash || "",
    get hash() { return this.value; },
    set hash(v) { this.value = v; if (win.listeners.hashchange) { win.listeners.hashchange(); } },
  };
  const document = {
    title: "",
    getElementById(id) { return id in jsonBlocks ? { textContent: jsonBlocks[id] } : (els[id] || (els[id] = makeEl())); },
    querySelectorAll() { return []; }, createElement: makeEl, addEventListener() {},
  };
  const ctx = { window: win, document, location, history: { replaceState(_a, _b, h) { location.value = h; } }, console: win.console };
  vm.createContext(ctx);
  vm.runInContext(main, ctx);
  return { guide: win.SynoxGuide, els, location, document, warnings, store };
}

const problems = [];
const plain = (t) => String(t).replace(/<[^>]+>/g, "");
function balanced(text, where) {                    // HTML 標籤有沒有成對（示意畫面是用字串接出來的）
  const stack = [];
  const VOID = new Set(["br", "path", "circle", "rect", "use", "img", "input"]);
  for (const m of String(text).matchAll(/<(\/?)([a-zA-Z0-9]+)([^>]*)>/g)) {
    const name = m[2].toLowerCase();
    if (VOID.has(name) || m[3].trim().endsWith("/")) { continue; }
    if (!m[1]) { stack.push(name); } else if (stack.pop() !== name) { problems.push(where + "：</" + name + "> 對不上"); return; }
  }
  if (stack.length) { problems.push(where + "：沒關的 <" + stack.join(">、<") + ">"); }
}

const tab = boot("");
const G = tab.guide;
if (!G || !G.check) { throw new Error("頁面沒有 window.SynoxGuide.check（格式改了？）"); }
const byId = (id) => G.STEPS.find((s) => s.id === id);
const ids = G.STEPS.map((s) => s.id);
const mainSteps = G.STEPS.filter((s) => !s.branch && !s.path);

// 2. 步驟資料
problems.push(...G.check());
if (new Set(ids).size !== ids.length) { problems.push("步驟 id 重複"); }
for (const s of G.STEPS) {
  tab.location.hash = G.hashFor(s);
  if (!tab.els.title.innerHTML) { problems.push(s.id + "：沒有標題"); }
  if (!tab.els.mock.innerHTML) { problems.push(s.id + "：示意畫面是空的"); }
  balanced(tab.els.mock.innerHTML, s.id + " 的示意畫面");
  s.body.forEach((p, i) => balanced(p, s.id + " 的第 " + (i + 1) + " 段"));
  (s.tips || []).forEach((t, i) => balanced(t.t, s.id + " 的第 " + (i + 1) + " 個小提示"));
}
problems.push(...tab.warnings);

// 3. 網址
for (const s of G.STEPS) {
  tab.location.hash = G.hashFor(s);
  if (tab.document.title.indexOf(plain(s.title)) < 0) { problems.push(G.hashFor(s) + " 沒有到 " + s.id); }
  tab.location.hash = "#step-" + s.id;
  if (tab.location.hash !== G.hashFor(s)) { problems.push("#step-" + s.id + " 沒有換成 " + G.hashFor(s)); }
}
tab.location.hash = "#step-ai-other";                                       // 改版前的網址
if (byId("ai") && tab.location.hash !== G.hashFor(byId("ai"))) { problems.push("舊網址 #step-ai-other 沒有到 ai"); }
for (const m of html.matchAll(/href="#step-([a-z0-9-]+)"/g)) {
  const ok = /^\d+$/.test(m[1]) ? +m[1] >= 1 && +m[1] <= mainSteps.length : ids.includes(m[1]);
  if (!ok) { problems.push("頁面裡的連結 #step-" + m[1] + " 指不到"); }
}

// 4. 岔路
const walks = [];
function walk(fork, trail) {
  for (const c of fork.choices) {
    tab.location.hash = G.hashFor(fork);
    G.choose(c.path);
    let s = byId(tab.location.hash.replace("#step-", ""));
    const seen = [fork.id];
    let guard = 0;
    while (s && s.path && !s.choices && guard++ < 50) { seen.push(s.id); s = G.nextOf(s); }
    if (s && s.choices && s.path) { walk(s, trail.concat(seen)); continue; }
    const full = trail.concat(seen), to = G.PATHS[c.path].to;
    if (!s || s.id !== to) { problems.push("岔路 " + c.path + " 沒有接回 " + to + "（停在 " + (s && s.id) + "）"); continue; }
    walks.push(full.join(" → ") + " → " + s.id);
    const back = [];
    for (let p = G.prevOf(s), n = 0; p && n++ < 50; p = G.prevOf(p)) { back.push(p.id); if (p.id === full[0]) { break; } }
    const want = full.slice().reverse();
    if (back.join(",") !== want.join(",")) { problems.push("岔路 " + c.path + " 往回走不對：" + back.join(" ← ") + "（應該是 " + want.join(" ← ") + "）"); }
  }
}
mainSteps.filter((s) => s.choices).forEach((s) => walk(s, []));
for (const fork of G.STEPS.filter((s) => s.choices)) {
  const fresh = boot(G.hashFor(fork));                                       // 全新的瀏覽器：還沒選過路
  if (!fresh.els.next.disabled) { problems.push(fork.id + "：還沒選路時「下一步」應該不能按"); }
  const again = boot(G.hashFor(fork), tab.store);                            // 選過路的瀏覽器再開一次：記得上次選的
  if (again.els.next.disabled) { problems.push(fork.id + "：選過路之後再打開，「下一步」應該能按"); }
}
const fresh = boot("");
for (const s of fresh.guide.STEPS.filter((x) => x.branch)) {
  if (!fresh.guide.prevOf(s) || !fresh.guide.nextOf(s)) { problems.push(s.id + "：選讀的「回去／接著做」指不到"); }
}

if (listSteps) {
  let n = 0;
  for (const s of G.STEPS) {
    console.log((s.branch ? "選讀（" + s.chapter.replace(/^選讀：/, "") + "）" : s.path ? "岔路（" + G.PATHS[s.path].label + "）" : "主線 " + (++n)) + "\t" + s.id + "\t" + plain(s.title));
  }
}
console.log("主線 " + mainSteps.length + " 步、岔路 " + G.STEPS.filter((s) => s.path).length + " 步、選讀 " + G.STEPS.filter((s) => s.branch).length + " 步；版本 " + (G.REL.version || "（沒有）"));
walks.forEach((w) => console.log("岔路走得通：" + w));
if (problems.length) {
  console.log("有問題：\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log("ok");
