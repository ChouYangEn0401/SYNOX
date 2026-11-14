/* 外觀的 slot（名字與規則：synox/theme/contract.py、docs/themes.md）。
 *
 * 伺服器送網頁時，在 <head> 放：
 *   <template data-slot-src="<名字>">     外觀包或「自己貼」的內容（伺服器已經消毒過、白名單重建）
 *   <template data-slot-default="<名字>"> 原本的 SYNOX 的 SVG（等回覆的方塊、開心／擔心的 S 寶寶）
 * 這支只做一件事：把 template 的內容複製到網頁上的 [data-slot="<名字>"] 裡。不讀資料、不打 API、不執行任何外觀給的東西
 * （template 的內容本來就不會跑；CSP 也只放行有 nonce 的 script）。
 *
 *   SynoxSlots.has(名字)          有沒有被換掉（外觀包或自己貼）
 *   SynoxSlots.make(名字, class)  做一個 <span class="slot …" data-slot="名字">，裡面放換掉的或預設的；都沒有＝空的
 *   SynoxSlots.fill(根)           把根底下所有 [data-slot] 換成換掉的內容（沒換的不動：保留網頁本來寫的「S」「SYNOX」）
 */
(function (root) {
  "use strict";
  var NAMES = ["mascot.idle", "mascot.think", "mascot.happy", "mascot.warn", "opening", "wordmark", "appicon"];

  function doc() { return root.document || null; }
  function find(attr, name) {
    var d = doc();
    if (!d || !d.querySelectorAll) { return null; }
    var list = d.querySelectorAll("template[" + attr + "]");
    for (var i = 0; i < list.length; i++) {
      if (list[i].getAttribute(attr) === name) { return list[i]; }
    }
    return null;
  }
  function has(name) { return !!find("data-slot-src", name); }
  function get(name) {
    var t = find("data-slot-src", name) || find("data-slot-default", name);
    return t && t.content ? t.content.cloneNode(true) : null;
  }
  function key(name) { return String(name).replace(/\./g, "-"); }
  function make(name, cls) {
    var d = doc();
    var s = d.createElement("span");
    s.className = "slot theme-slot-" + key(name) + (cls ? " " + cls : "");
    s.setAttribute("data-slot", name);
    s.setAttribute("aria-hidden", "true");
    var f = get(name);
    if (f) { s.appendChild(f); }
    if (has(name)) { s.classList.add("slotted"); }
    return s;
  }
  function fill(rootNode) {
    var d = doc();
    var base = rootNode || d;
    if (!base || !base.querySelectorAll) { return; }
    var list = base.querySelectorAll("[data-slot]");
    for (var i = 0; i < list.length; i++) {
      var node = list[i];
      var name = node.getAttribute("data-slot");
      if (!has(name) || node.classList.contains("slotted")) { continue; }
      while (node.firstChild) { node.removeChild(node.firstChild); }
      node.appendChild(get(name));
      node.classList.add("slotted");
      if (node.parentNode && node.parentNode.classList) { node.parentNode.classList.add("slot-host"); }
    }
  }

  var api = { NAMES: NAMES, has: has, get: get, make: make, fill: fill, key: key };
  if (typeof module === "object" && module && module.exports) { module.exports = api; return; }
  root.SynoxSlots = api;
  var d = doc();
  if (d && d.readyState === "loading") { d.addEventListener("DOMContentLoaded", function () { fill(d); }); }
  else if (d) { fill(d); }
})(typeof window !== "undefined" ? window : this);
