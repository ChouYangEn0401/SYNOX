/* SYNOX 網頁對話頁：附件的三個入口（📎 選檔、Ctrl+V 貼上截圖、把檔案拖進對話區）共用的檢查。
 *
 *   var files = SynoxAttach.fromClipboard(ev.clipboardData);   // 貼上：只拿檔案（截圖）；剪貼簿有文字就不拿（照常貼字）
 *   var files = SynoxAttach.fromDrop(ev.dataTransfer);         // 拖進來：只拿檔案
 *   var p = SynoxAttach.plan(files, attached.length, input.getAttribute("accept"));
 *   // p.ok：要上傳的 File；p.problems：給人看的一句話（太大、空的、不支援的類型、超過數量）
 *
 * - 只收瀏覽器給的 File／Blob 物件（有 arrayBuffer 的），從來不收路徑字串（text/uri-list 的 file:// 一律不理）。
 * - 類型照 #attach-input 的 accept（同一份清單，📎 也是它）：image/png 這種 MIME、.xlsx 這種副檔名。
 * - 大小、數量跟伺服器一樣（web/uploads.py 的 MAX_FILE_BYTES、MAX_PENDING）；伺服器還會再看內容檢查一次，這裡只是早點說人話。
 * - 從 Excel／Word 複製一段字時，剪貼簿裡除了字還有一張「那段字的圖」：有文字就當貼字，不變成附件。
 * 伺服器把這個檔原地塞進 app.html 主程式那個 script 標籤（INCLUDE:attach.js，跟 blocks.js 一樣，同一個 CSP nonce）。
 * tests/js/test_attach.js 用 node 跑。
 */
(function (root) {
  "use strict";

  var MAX_BYTES = 10 * 1024 * 1024;          // web/uploads.py MAX_FILE_BYTES
  var MAX_COUNT = 10;                        // web/uploads.py MAX_PENDING（還沒送出的附件）
  var TEXT = {
    pasted: "貼上的圖片",
    big: "「{name}」太大（每個最多 10 MB）。",
    empty: "「{name}」是空的檔案。",
    type: "「{name}」不支援：可以附圖片（png／jpg／webp／gif）、表格（.xlsx／.csv）、文件（.docx）或文字檔。",
    count: "一次最多先放 {max} 個附件；多的沒有附上（先送出再傳）。",
    drop: "放開滑鼠，就附到這則訊息（圖片、表格、文字檔，可以一次好幾個）。"
  };
  var MIME_EXT = { "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif" };

  function fill(s, vars) {
    return String(s).replace(/\{(\w+)\}/g, function (_, k) { return vars[k] === undefined ? "" : String(vars[k]); });
  }

  function isFile(f) {
    return !!f && typeof f === "object" && typeof f.arrayBuffer === "function" && typeof f.size === "number";
  }

  function toArray(list) {
    var out = [];
    if (!list) { return out; }
    for (var i = 0; i < list.length; i++) { if (isFile(list[i])) { out.push(list[i]); } }
    return out;
  }

  // 貼上：剪貼簿有文字 → []（讓瀏覽器照常貼字）；不然拿 files，沒有再從 items（kind=file）拿
  function fromClipboard(cd) {
    if (!cd) { return []; }
    var text = "";
    try { text = typeof cd.getData === "function" ? String(cd.getData("text/plain") || "") : ""; } catch (e) { text = ""; }
    if (text.trim()) { return []; }
    var files = toArray(cd.files);
    if (files.length) { return files; }
    var items = cd.items, out = [];
    for (var i = 0; items && i < items.length; i++) {
      var it = items[i];
      if (it && it.kind === "file" && typeof it.getAsFile === "function") {
        var f = it.getAsFile();
        if (isFile(f)) { out.push(f); }
      }
    }
    return out;
  }

  // 拖進來：只拿檔案（拖一段字、一個網址進來 → []）
  function fromDrop(dt) {
    return dt ? toArray(dt.files) : [];
  }

  function hasFiles(dt) {
    var types = dt && dt.types;
    if (!types) { return false; }
    for (var i = 0; i < types.length; i++) { if (types[i] === "Files") { return true; } }
    return false;
  }

  function displayName(f) {
    var name = String((f && f.name) || "").trim();
    if (name) { return name; }
    return TEXT.pasted + (MIME_EXT[String(f && f.type || "").toLowerCase()] || "");
  }

  // accept 屬性的規則（<input type=file accept=…>）：".ext" 比副檔名、"type/*" 比大類、其他比完整 MIME；空的＝都收
  function accepts(f, accept) {
    var rules = String(accept || "").split(",").map(function (s) { return s.trim().toLowerCase(); })
      .filter(function (s) { return s; });
    if (!rules.length) { return true; }
    var name = displayName(f).toLowerCase(), mime = String(f.type || "").toLowerCase();
    return rules.some(function (r) {
      if (r.charAt(0) === ".") { return name.length > r.length && name.slice(-r.length) === r; }
      if (r.slice(-2) === "/*") { return mime.indexOf(r.slice(0, -1)) === 0; }
      return mime === r;
    });
  }

  // files → {ok: [{file, name}], problems: ["…"]}；already＝已經附上（還沒送出）的個數
  function plan(files, already, accept) {
    var ok = [], problems = [], room = Math.max(0, MAX_COUNT - (already | 0)), over = false;
    toArray(files).forEach(function (f) {
      var name = displayName(f);
      if (!accepts(f, accept)) { problems.push(fill(TEXT.type, { name: name })); return; }
      if (!(f.size > 0)) { problems.push(fill(TEXT.empty, { name: name })); return; }
      if (f.size > MAX_BYTES) { problems.push(fill(TEXT.big, { name: name })); return; }
      if (ok.length >= room) { over = true; return; }
      ok.push({ file: f, name: name });
    });
    if (over) { problems.push(fill(TEXT.count, { max: MAX_COUNT })); }
    return { ok: ok, problems: problems };
  }

  // 貼上的 listener（掛在 document）：只在對話頁；焦點在輸入框，或不在別的可以打字的地方；有檔案才攔下來交給 attach(files)
  function pasteListener(doc, input, attach) {
    return function (ev) {
      if (!doc.body || doc.body.getAttribute("data-view") !== "chat") { return; }
      var t = ev.target;
      if (t && t !== input && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(String(t.tagName || "")))) { return; }
      var files = fromClipboard(ev.clipboardData);
      if (!files.length) { return; }
      ev.preventDefault();
      attach(files);
    };
  }

  var api = { MAX_BYTES: MAX_BYTES, MAX_COUNT: MAX_COUNT, TEXT: TEXT, fromClipboard: fromClipboard, fromDrop: fromDrop,
              hasFiles: hasFiles, displayName: displayName, accepts: accepts, plan: plan,
              pasteListener: pasteListener };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxAttach = api; }
})(typeof window !== "undefined" ? window : this);
