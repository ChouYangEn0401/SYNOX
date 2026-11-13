/* 把 .synoxpack 拖進網頁就開始檢查（樣式在 static/packdrop.css；server.render_app 原地塞進 app.html，同一個 CSP nonce）。
 *
 * 可拆卸的零件：要拿掉 → 刪 app.html 裡 packdrop.js、packdrop.css 那兩行 include。
 * 不自己裝任何東西、不另外打上傳 API：檢查通過的檔交給設定頁原本的 #pack-file＋「上傳並檢查」（#pack-upload），
 * 所以報告、確認按鈕、T2 的 publisher 輸入全部是原本那一套（/api/packs/upload → 看報告 → /api/packs/install）。
 * 伺服器一樣驗大小、zip 檔頭、只有擁有者（web/server.py pack_upload、packs/admin.py stage）；這裡的檢查只是早點說人話。
 *
 * 也在設定頁的上傳框旁邊放一句「怎麼裝」的提示（點兩下、拖到 Install-Pack.bat、拖進這裡）。
 * 字一律 textContent。網頁介面目前只有繁體中文；字串集中在 TEXT，之後網頁有多語系時從這裡接。
 */
(function (root) {
  "use strict";
  var MAX_BYTES = 5 * 1024 * 1024;               // 跟 packs/admin.py 的 MAX_UPLOAD 一樣
  var EXTS = [".synoxpack", ".zip"];
  var TEXT = {
    overlay: "放開來檢查這個 .synoxpack（先看安全報告，按確認才會裝）",
    hint: "也可以直接把 .synoxpack 拖進這個網頁；在檔案總管點兩下 .synoxpack，或拖到 SYNOX 資料夾的 Install-Pack.bat 上也行。不管哪一種，都會先檢查、給你看報告，按確認才裝。",
    one: "一次拖一個 .synoxpack 就好。",
    ext: "這不是 .synoxpack 檔：",
    big: "檔案太大（最多 5 MB）：",
    empty: "檔案是空的：",
    login: "先登入 SYNOX，再把 .synoxpack 拖進來。",
    owner: "只有擁有者能裝功能。",
    checking: "檢查中：",
    missing: "設定頁的上傳框不見了（重新整理看看）。"
  };

  /* 純函式（tests/js/test_packdrop.js）：拖進來的檔案清單 → {ok, file} 或 {ok:false, message} */
  function check(files) {
    if (!files || files.length !== 1) { return { ok: false, message: TEXT.one }; }
    var f = files[0];
    var name = String(f.name || "");
    var lower = name.toLowerCase();
    if (!EXTS.some(function (e) { return lower.length > e.length && lower.slice(-e.length) === e; })) {
      return { ok: false, message: TEXT.ext + name };
    }
    if (!(f.size > 0)) { return { ok: false, message: TEXT.empty + name }; }
    if (f.size > MAX_BYTES) { return { ok: false, message: TEXT.big + name }; }
    return { ok: true, file: f };
  }

  /* 純函式：拖進來之後要去的網址。一律到安裝頁 #packs（＝#settings:packs）：只設 #settings 的話，設定頁會沿用上次的分頁
     （例如 AI），報告就出現在看不到的分頁裡。已經在安裝頁就不動網址。 */
  function installHash(current) {
    return current === "#packs" || current === "#settings:packs" ? current : "#packs";
  }

  function hasFiles(e) {
    var types = e && e.dataTransfer && e.dataTransfer.types;
    if (!types) { return false; }
    for (var i = 0; i < types.length; i++) { if (types[i] === "Files") { return true; } }
    return false;
  }

  function wire(doc) {
    var $ = function (id) { return doc.getElementById(id); };
    var overlay = doc.createElement("div");
    overlay.id = "packdrop";
    overlay.className = "hidden";
    overlay.setAttribute("aria-hidden", "true");
    var box = doc.createElement("div");
    box.className = "packdrop-box";
    box.textContent = TEXT.overlay;
    overlay.appendChild(box);
    doc.body.appendChild(overlay);

    var input = $("pack-file");
    if (input && input.parentNode && !$("packdrop-hint")) {
      var hint = doc.createElement("p");
      hint.id = "packdrop-hint";
      hint.className = "muted packdrop-hint";
      hint.textContent = TEXT.hint;
      var zone = input.parentNode;
      zone.parentNode.insertBefore(hint, zone.nextSibling);
    }

    function say(text) {
      var t = $("toast");
      if (!t) { return; }
      t.textContent = text;
      t.classList.remove("hidden");
      clearTimeout(say.timer);
      say.timer = setTimeout(function () { t.classList.add("hidden"); }, 4500);
    }
    var depth = 0;
    function showOverlay(on) { overlay.classList.toggle("hidden", !on); }

    doc.addEventListener("dragenter", function (e) {
      if (!hasFiles(e)) { return; }
      e.preventDefault();
      depth += 1;
      showOverlay(true);
    });
    doc.addEventListener("dragover", function (e) {
      if (!hasFiles(e)) { return; }
      e.preventDefault();                                   // 不然瀏覽器會直接打開這個檔、離開 SYNOX
      e.dataTransfer.dropEffect = "copy";
    });
    doc.addEventListener("dragleave", function (e) {
      if (!hasFiles(e)) { return; }
      depth = Math.max(0, depth - 1);
      if (!depth) { showOverlay(false); }
    });
    doc.addEventListener("drop", function (e) {
      if (!hasFiles(e)) { return; }
      e.preventDefault();
      depth = 0;
      showOverlay(false);
      var r = check(e.dataTransfer.files);
      if (!r.ok) { say(r.message); return; }
      if (doc.body.getAttribute("data-view") === "login") { say(TEXT.login); return; }
      root.fetch("/api/me", { credentials: "same-origin" }).then(function (resp) {
        if (!resp.ok) { throw new Error(TEXT.login); }
        return resp.json();
      }).then(function (me) {
        if (!me.owner) { say(TEXT.owner); return; }
        handOff(r.file);
      }).catch(function (err) { say(err && err.message ? err.message : TEXT.login); });
    });

    function handOff(file) {
      var fileInput = $("pack-file");
      var button = $("pack-upload");
      if (!fileInput || !button) { say(TEXT.missing); return; }
      var want = installHash(root.location.hash);
      if (root.location.hash !== want) { root.location.hash = want; }
      try {
        var dt = new root.DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
      } catch (err) { say(TEXT.missing); return; }
      say(TEXT.checking + file.name);
      button.click();                                       // 原本的上傳 → 報告 → 確認按鈕
      setTimeout(function () {                              // 設定頁剛打開時卡片還在載入：等一下再捲過去
        var review = $("pack-review");
        var card = review && !review.classList.contains("hidden") ? review : $("set-packs");
        if (card && card.scrollIntoView) { card.scrollIntoView({ behavior: "smooth", block: "start" }); }
      }, 700);
    }
  }

  var api = { check: check, hasFiles: hasFiles, installHash: installHash, MAX_BYTES: MAX_BYTES, TEXT: TEXT };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else {
    root.SynoxPackDrop = api;
    try { wire(root.document); } catch (err) { /* 壞掉也不能擋住網頁其他部分 */ }
  }
})(typeof window !== "undefined" ? window : this);
