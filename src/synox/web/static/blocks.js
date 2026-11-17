/* SYNOX 網頁對話頁：呈現層的區塊（synox/present/web.py 的 wire）→ DOM。
 *
 * config.json 的 presentation.enabled 開著時，AI 回覆的訊息多一個 blocks（JSON），app.html 的 renderMessage
 * 用這裡的 render(document, blocks) 畫；沒有 blocks 的訊息用 linkText(document, text)：照舊整段文字，只把網址變成連結。
 * 伺服器把這個檔原地塞進 app.html 主程式那個 script 標籤開頭的 INCLUDE:blocks.js（server.render_app，同一個 CSP nonce，
 * 不多一個 script 標籤）。
 *
 * 規則（docs/AGENT.md invariant 9、docs/presentation.md）：一律 createElement＋textContent，不塞 HTML 字串；
 * 連結只收 http／https；只產生白名單的標籤；不知道的區塊種類直接略過。
 * tests/js/test_blocks.js 用 node＋假的 document 測。
 */
(function (root) {
  "use strict";

  var TONES = { ok: 1, warn: 1, error: 1, info: 1, pending: 1 };
  var HEADINGS = ["h3", "h3", "h4", "h5"];

  function make(doc, tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }

  function safeHref(href) {
    return typeof href === "string" && /^https?:\/\//i.test(href) ? href : "";
  }

  function spans(doc, parent, list) {
    (Array.isArray(list) ? list : []).forEach(function (s) {
      if (!s) { return; }
      var node = doc.createTextNode(String(s.text === undefined || s.text === null ? "" : s.text));
      var wrap = function (tag) { var w = make(doc, tag); w.appendChild(node); node = w; };
      if (s.code) { wrap("code"); }
      if (s.italic) { wrap("i"); }
      if (s.bold) { wrap("b"); }
      var href = safeHref(s.href);
      if (href) {
        wrap("a");
        node.href = href; node.target = "_blank"; node.rel = "noopener noreferrer";
      }
      parent.appendChild(node);
    });
  }

  function list(doc, b) {
    var out = make(doc, b.ordered ? "ol" : "ul");
    if (b.ordered && (b.start | 0) > 1) { out.start = b.start | 0; }
    (Array.isArray(b.items) ? b.items : []).forEach(function (it) {
      var li = make(doc, "li");
      spans(doc, li, it && it.spans);
      if (it && it.children) { li.appendChild(list(doc, it.children)); }
      out.appendChild(li);
    });
    return out;
  }

  function table(doc, b) {
    var wrap = make(doc, "div", "tablewrap");
    var t = make(doc, "table"), thead = make(doc, "thead"), head = make(doc, "tr"), body = make(doc, "tbody");
    (Array.isArray(b.header) ? b.header : []).forEach(function (c) {
      var th = make(doc, "th"); spans(doc, th, c); head.appendChild(th);
    });
    thead.appendChild(head);
    (Array.isArray(b.rows) ? b.rows : []).forEach(function (row) {
      var tr = make(doc, "tr");
      (Array.isArray(row) ? row : []).forEach(function (c) { var td = make(doc, "td"); spans(doc, td, c); tr.appendChild(td); });
      body.appendChild(tr);
    });
    t.appendChild(thead); t.appendChild(body); wrap.appendChild(t);
    return wrap;
  }

  function block(doc, b) {
    var node = null;
    if (!b || typeof b !== "object") { return null; }
    if (b.type === "paragraph") {
      node = make(doc, "p"); spans(doc, node, b.spans);
    } else if (b.type === "heading") {
      node = make(doc, HEADINGS[Math.min(3, Math.max(1, b.level | 0))]); spans(doc, node, b.spans);
    } else if (b.type === "list") {
      node = list(doc, b);
    } else if (b.type === "quote") {
      node = make(doc, "blockquote");
      (Array.isArray(b.paragraphs) ? b.paragraphs : []).forEach(function (p) {
        var q = make(doc, "p"); spans(doc, q, p); node.appendChild(q);
      });
    } else if (b.type === "code") {
      node = make(doc, "pre");
      node.appendChild(make(doc, "code", "", b.code));
    } else if (b.type === "table") {
      node = table(doc, b);
    } else if (b.type === "status") {
      node = make(doc, "p");
      node.appendChild(make(doc, "span", "status status-" + (TONES[b.tone] ? b.tone : "info"),
                           (b.icon ? b.icon + " " : "") + String(b.label || "")));
    } else if (b.type === "confirm") {
      node = make(doc, "div");
      var title = make(doc, "p"); title.appendChild(make(doc, "b", "", b.title)); node.appendChild(title);
      (Array.isArray(b.lines) ? b.lines : []).forEach(function (line) { node.appendChild(make(doc, "p", "", line)); });
    }
    return node;
  }

  function render(doc, blocks) {
    var box = make(doc, "div", "text blocks");
    (Array.isArray(blocks) ? blocks : []).forEach(function (b) {
      var node = block(doc, b);
      if (node) { box.appendChild(node); }
    });
    return box;
  }

  // 純文字訊息（沒有 blocks）：整段照舊是文字，只有裡面的 http(s):// 網址變成可以點的連結。
  // 網址只認 ASCII 可見字元（碰到空白、全形字、引號、角括號就停），句尾的標點不算進網址；
  // 連結一樣過 safeHref、開新分頁、noopener；其他字一律 createTextNode。
  var URL_RE = /https?:\/\/[^\s<>"'`\u0080-￿]+/gi;
  var TRAILING = /[.,;:!?)\]}]+$/;

  function linkText(doc, text, cls) {
    var box = make(doc, "div", cls === undefined ? "text" : cls);
    var s = text === undefined || text === null ? "" : String(text);
    var last = 0, m;
    URL_RE.lastIndex = 0;
    while ((m = URL_RE.exec(s)) !== null) {
      var url = m[0].replace(TRAILING, "");
      var href = safeHref(url);
      if (!href || /^https?:\/\/$/i.test(url)) { continue; }
      if (m.index > last) { box.appendChild(doc.createTextNode(s.slice(last, m.index))); }
      var a = make(doc, "a", "", url);
      a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
      box.appendChild(a);
      last = m.index + url.length;
    }
    if (last < s.length) { box.appendChild(doc.createTextNode(s.slice(last))); }
    return box;
  }

  var api = { render: render, safeHref: safeHref, linkText: linkText };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxBlocks = api; }
})(typeof window !== "undefined" ? window : this);
