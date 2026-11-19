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

  // ── 沒有 blocks 的 bot 訊息：瀏覽器這邊的小 Markdown（config presentation.enabled 關著時，AI 回的就是原樣的 Markdown）──
  // markdown(text) → 跟伺服器 wire 一樣形狀的區塊（交給上面的 render 畫，一樣只用 createElement＋textContent）；
  // 看起來不是 Markdown → null，照舊用 linkText（純文字的訊息畫出來跟以前一模一樣）。
  // 支援：``` / ~~~ 程式碼區塊（沒閉合＝到結尾）、# 標題、- * + 與 1. 清單（兩層）、> 引用、| 表格、段落（換行照留）；
  // 行內 **粗體**、*斜體*、`程式碼`、[字](http/https 網址)、裸網址。不認 _底線_（指令名字裡常有底線）。
  // HTML 標籤、[字](javascript:…) 一律是普通字。
  var FENCE = /^ {0,3}(`{3,}|~{3,})/;
  var HEAD = /^ {0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$/;
  var ITEM = /^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
  var QUOTE = /^ {0,3}> ?(.*)$/;
  var HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
  var SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
  var INLINE = /`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^\s*][^*\n]*\*|\[[^\]\n]+\]\(https?:[^)\s]+\)/;

  function looksLikeMarkdown(s) {
    return /^ {0,3}(```|~~~|#{1,6}[ \t]|[-*+][ \t]|\d{1,9}[.)][ \t]|>)/m.test(s) || INLINE.test(s) ||
      /^\s*\|.*\|\s*$/m.test(s);
  }

  function urlSpans(text, style, out) {          // 普通字裡的裸網址 → href（跟 linkText 同一套規則）
    var last = 0, m;
    var add = function (t, href) {
      var sp = { text: t };
      Object.keys(style).forEach(function (k) { sp[k] = style[k]; });
      if (href) { sp.href = href; }
      out.push(sp);
    };
    URL_RE.lastIndex = 0;
    while ((m = URL_RE.exec(text)) !== null) {
      var url = m[0].replace(TRAILING, "");
      if (!safeHref(url) || /^https?:\/\/$/i.test(url)) { continue; }
      if (m.index > last) { add(text.slice(last, m.index)); }
      add(url, url);
      last = m.index + url.length;
    }
    if (last < text.length) { add(text.slice(last)); }
  }

  var I_CODE = /`([^`\n]+)`/y, I_BOLD = /\*\*([^*\n]+)\*\*/y, I_ITAL = /\*([^\s*](?:[^*\n]*[^\s*])?)\*/y,
      I_LINK = /\[([^\]\n]+)\]\(([^)\s]+)\)/y;

  function at(re, s, i) { re.lastIndex = i; return re.exec(s); }

  function inline(text) {
    var out = [], s = String(text), start = 0, i = 0, m;
    var flush = function () { if (i > start) { urlSpans(s.slice(start, i), {}, out); } };
    while (i < s.length) {
      var c = s.charAt(i);
      if (c === "`" && (m = at(I_CODE, s, i))) {
        flush(); out.push({ text: m[1], code: true });
      } else if (c === "*" && (m = at(I_BOLD, s, i)) && m[1].trim()) {
        flush(); urlSpans(m[1], { bold: true }, out);
      } else if (c === "*" && (m = at(I_ITAL, s, i))) {
        flush(); urlSpans(m[1], { italic: true }, out);
      } else if (c === "[" && (m = at(I_LINK, s, i)) && safeHref(m[2])) {
        flush(); out.push({ text: m[1], href: m[2] });
      } else {
        i += 1; continue;
      }
      i += m[0].length; start = i;
    }
    flush();
    return out;
  }

  function cells(line) {
    var t = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return t.split("|").map(function (c) { return inline(c.trim()); });
  }

  function newList(marker) {
    var ordered = /\d/.test(marker);
    return { type: "list", ordered: ordered, start: ordered ? parseInt(marker, 10) : 1, items: [] };
  }

  function markdown(text) {
    var s = text === undefined || text === null ? "" : String(text).replace(/\r\n?/g, "\n");
    if (!looksLikeMarkdown(s)) { return null; }
    var lines = s.split("\n"), out = [], para = [], i = 0, m;
    var endPara = function () {
      if (para.length) { out.push({ type: "paragraph", spans: inline(para.join("\n")) }); para = []; }
    };
    while (i < lines.length) {
      var line = lines[i];
      if ((m = FENCE.exec(line))) {
        endPara();
        var mark = m[1], code = [];
        var close = new RegExp("^ {0,3}" + (mark.charAt(0) === "`" ? "`" : "~") + "{" + mark.length + ",}\\s*$");
        i += 1;
        while (i < lines.length && !close.test(lines[i])) { code.push(lines[i]); i += 1; }
        i += 1;                                                      // 收尾那行（沒有＝到結尾都是程式碼）
        out.push({ type: "code", code: code.join("\n") });
        continue;
      }
      if (!line.trim() || HR.test(line)) { endPara(); i += 1; continue; }
      if ((m = HEAD.exec(line))) {
        endPara();
        out.push({ type: "heading", level: Math.min(3, m[1].length), spans: inline(m[2]) });
        i += 1; continue;
      }
      if (QUOTE.test(line)) {
        endPara();
        var qs = [], cur = [];
        while (i < lines.length && (m = QUOTE.exec(lines[i]))) {
          if (m[1].trim()) { cur.push(m[1]); } else if (cur.length) { qs.push(inline(cur.join("\n"))); cur = []; }
          i += 1;
        }
        if (cur.length) { qs.push(inline(cur.join("\n"))); }
        out.push({ type: "quote", paragraphs: qs });
        continue;
      }
      if (line.indexOf("|") >= 0 && i + 1 < lines.length && lines[i + 1].indexOf("|") >= 0 && SEP.test(lines[i + 1])) {
        endPara();
        var tb = { type: "table", header: cells(line), rows: [] };
        i += 2;
        while (i < lines.length && lines[i].indexOf("|") >= 0 && lines[i].trim()) { tb.rows.push(cells(lines[i])); i += 1; }
        out.push(tb);
        continue;
      }
      if ((m = ITEM.exec(line))) {
        endPara();
        var top = newList(m[2]), base = m[1].replace(/\t/g, "    ").length;
        while (i < lines.length && (m = ITEM.exec(lines[i])) && !HR.test(lines[i])) {
          var item = { spans: inline(m[3]) }, prev = top.items[top.items.length - 1];
          if (m[1].replace(/\t/g, "    ").length >= base + 2 && prev) {     // 第二層（更深的也併到第二層）
            if (!prev.children) { prev.children = newList(m[2]); }
            prev.children.items.push(item);
          } else {
            top.items.push(item);
          }
          i += 1;
        }
        out.push(top);
        continue;
      }
      para.push(line);
      i += 1;
    }
    endPara();
    return out;
  }

  var api = { render: render, safeHref: safeHref, linkText: linkText, markdown: markdown };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxBlocks = api; }
})(typeof window !== "undefined" ? window : this);
