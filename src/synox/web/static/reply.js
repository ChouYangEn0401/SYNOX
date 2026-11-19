/* SYNOX 網頁對話頁：「回覆某一則」（像 Telegram／LINE）。
 *
 * 每則訊息泡泡上有一顆「↩ 回覆」（滑鼠移上去或鍵盤 Tab 到才明顯；手機一直看得到）；按了 → 輸入框上方出現引用列
 * （誰說的＋一行摘要＋✕ 取消）；送出時帶 reply_to（訊息 id，伺服器檢查是同一段對話的）。
 * 送出的那則上面有一小塊引用，點了捲到原訊息、閃一下（原訊息已經不在畫面上就說一聲）。
 * 伺服器把這個檔原地塞進 app.html 主程式那個 script 標籤（INCLUDE:reply.js，跟 blocks.js 一樣，同一個 CSP nonce）。
 * 一律 createElement＋textContent，訊息的字不經 HTML。tests/js/test_reply.js 用 node＋假的 document 測。
 */
(function (root) {
  "use strict";

  var TEXT = {
    reply: "↩ 回覆",
    reply_label: "回覆這則訊息",
    who_me: "你",
    who_bot: "SYNOX",
    who_note: "系統",
    replying: "回覆 {who}",
    cancel: "取消回覆",
    jump: "跳到被回覆的訊息：{who}",
    gone: "原本那則訊息已經不在畫面上了（可能太舊了）。",
    empty: "（沒有文字）",
  };
  var BAR_MAX = 80;

  function make(doc, tag, cls, text) {
    var e = doc.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = String(text); }
    return e;
  }

  function fill(s, vars) {
    return String(s).replace(/\{(\w+)\}/g, function (_, k) { return vars[k] === undefined ? "" : String(vars[k]); });
  }

  function who(from) {
    return from === "me" ? TEXT.who_me : (from === "note" ? TEXT.who_note : TEXT.who_bot);
  }

  function excerpt(text, max) {
    var flat = String(text === undefined || text === null ? "" : text)
      .replace(/`{3,}[^\n]*/g, " ")             // Markdown 的記號只是排版：摘要裡拿掉（字本身留著）
      .replace(/\*\*|`/g, "")
      .replace(/^[ \t]*(?:#{1,6}|>|[-*+])[ \t]+/gm, "")
      .replace(/\s+/g, " ").trim();
    var n = max || BAR_MAX;
    if (!flat) { return TEXT.empty; }
    return flat.length <= n ? flat : flat.slice(0, n - 1) + "…";
  }

  // 泡泡上的「↩ 回覆」按鈕
  function button(doc, onReply) {
    var b = make(doc, "button", "reply-btn", TEXT.reply);
    b.type = "button";
    b.title = TEXT.reply_label;
    b.setAttribute("aria-label", TEXT.reply_label);
    b.addEventListener("click", function (ev) { if (ev && ev.stopPropagation) { ev.stopPropagation(); } onReply(); });
    return b;
  }

  // 送出的那則上面的引用塊（reply = 訊息的 reply_to：{id, from, excerpt}）；點了 onJump(id)
  function quote(doc, reply, onJump) {
    if (!reply || typeof reply !== "object") { return null; }
    var name = who(reply.from);
    var q = make(doc, "button", "reply-quote");
    q.type = "button";
    q.setAttribute("aria-label", fill(TEXT.jump, { who: name }));
    q.appendChild(make(doc, "span", "rq-who", name));
    q.appendChild(make(doc, "span", "rq-text", excerpt(reply.excerpt)));
    q.addEventListener("click", function () { onJump(reply.id); });
    return q;
  }

  // 輸入框上方的引用列：target = 要回覆的那則訊息 {id, from, text}；✕ → onCancel()
  function bar(doc, box, target, onCancel) {
    while (box.firstChild) { box.removeChild(box.firstChild); }
    if (!target) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    var body = make(doc, "div", "rb-body");
    body.appendChild(make(doc, "span", "rb-who", fill(TEXT.replying, { who: who(target.from) })));
    body.appendChild(make(doc, "span", "rb-text", excerpt(target.text)));
    var x = make(doc, "button", "rb-x", "✕");
    x.type = "button";
    x.title = TEXT.cancel;
    x.setAttribute("aria-label", TEXT.cancel);
    x.addEventListener("click", function () { onCancel(); });
    box.appendChild(body);
    box.appendChild(x);
  }

  // 捲到原訊息、閃一下；不在畫面上 → 回 false（呼叫的一方 toast TEXT.gone）
  function jump(node, setTimer) {
    if (!node) { return false; }
    if (node.scrollIntoView) { node.scrollIntoView({ behavior: "smooth", block: "center" }); }
    node.classList.remove("flash");
    node.classList.add("flash");
    (setTimer || setTimeout)(function () { node.classList.remove("flash"); }, 1600);
    return true;
  }

  var api = { TEXT: TEXT, who: who, excerpt: excerpt, button: button, quote: quote, bar: bar, jump: jump };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxReply = api; }
})(typeof window !== "undefined" ? window : this);
