/* 「遇到問題？」（設定 → 🙋 遇到問題？；畫面在 app.html 的 #set-help，樣式在 static/report.css；伺服器那一半是 web/report.py）。
 *
 * 三步：① 沒有 GitHub 帳號？（連結）② 幫我準備好回報內容（POST /api/report → 放進可以改的框）
 * ③ 到 GitHub 開一張問題單（一般的連結：表單 problem.yml，第 2 步的內容放在網址參數 summary；太長就改成複製到剪貼簿）。
 * SYNOX 自己不連到 GitHub：送出的只有使用者自己按的那個連結。字一律 textContent；字串集中在 TEXT。
 * app.html 在拿到 /api/me 之後叫 window.SynoxReport.init({ api: api, toast: toast })（api 會帶 CSRF）。
 */
(function (root) {
  "use strict";
  var ISSUE_NEW = "https://github.com/ChouYangEn0401/SYNOX/issues/new";   // 跟 web/report.py 一樣（tests/test_web_report.py 對）
  var TEMPLATE = "problem.yml";
  var FIELD = "summary";
  var MAX_URL = 6000;
  var TEXT = {
    preparing: "整理中…（只在這台電腦上整理，不會送出）",
    again: "重新整理一次",
    full: "已經拿掉 token、金鑰、對話內容和有你名字的路徑。送出前再看一眼，不想公開的地方直接刪掉就好。",
    member: "你不是這台 SYNOX 的擁有者，所以這裡只有版本；這台的設定和錯誤紀錄，要請擁有者幫忙回報。",
    failed: "沒有整理成功：",
    opened: "已經在新分頁打開 GitHub 的表單。用自己的話寫「發生了什麼」，再按最下面的綠色按鈕就送出了。",
    blank: "已經在新分頁打開 GitHub 的表單（還沒有第 2 步的內容也沒關係，可以只寫發生了什麼）。",
    long: "內容比較長，網址放不下，所以已經幫你複製好了：在 GitHub 表單的「SYNOX 幫你準備的回報內容」那一格按 Ctrl+V（手機長按 → 貼上）。",
    longFail: "內容比較長、網址放不下，也沒辦法自動複製：回到這裡按「複製」，再貼到 GitHub 表單的「SYNOX 幫你準備的回報內容」那一格。",
    copied: "已複製",
    copy: "複製",
    copyFail: "已經選起來了，按 Ctrl+C 複製"
  };

  /* 純函式（tests/js/test_report.js） */
  function issueUrl(summary) {
    var url = ISSUE_NEW + "?template=" + encodeURIComponent(TEMPLATE);
    return summary ? url + "&" + FIELD + "=" + encodeURIComponent(summary) : url;
  }
  function issuePlan(summary) {
    var text = String(summary || "");
    if (!text.trim()) { return { url: issueUrl(""), copy: false }; }
    var full = issueUrl(text);
    return full.length <= MAX_URL ? { url: full, copy: false } : { url: issueUrl(""), copy: true };
  }

  function copyText(doc, textarea, text) {
    /* 先用剪貼簿 API；不行就選起來用 execCommand（都要在按下去的那一刻叫） */
    function legacy() {
      try {
        textarea.focus(); textarea.select();
        return doc.execCommand && doc.execCommand("copy") ? Promise.resolve() : Promise.reject(new Error("copy"));
      } catch (err) { return Promise.reject(err); }
    }
    var clip = root.navigator && root.navigator.clipboard;
    if (clip && clip.writeText) { return clip.writeText(text).catch(legacy); }
    return legacy();
  }

  var deps = null;
  function init(options) {
    if (deps) { deps = options; return; }
    deps = options;
    var doc = root.document;
    function $(id) { return doc.getElementById(id); }
    var prepare = $("report-prepare"), review = $("report-review"), box = $("report-text"), scope = $("report-scope"),
        open = $("report-open"), msg = $("report-msg"), copy = $("report-copy");
    if (!prepare || !box || !open) { return; }

    function emphasize(ready) {           // 一頁只有一個主要動作：整理好之後換第 3 步當主要的
      prepare.classList.toggle("primary", !ready);
      open.classList.toggle("primary", ready);
    }
    prepare.addEventListener("click", function () {
      prepare.disabled = true;
      msg.textContent = TEXT.preparing;
      deps.api("POST", "/api/report", {}).then(function (d) {
        box.value = d.summary || "";
        scope.textContent = d.full ? TEXT.full : TEXT.member;
        review.classList.remove("hidden");
        prepare.textContent = TEXT.again;
        msg.textContent = "";
        emphasize(true);
      }).catch(function (err) {
        msg.textContent = TEXT.failed + (err && err.message ? err.message : "");
      }).then(function () { prepare.disabled = false; });
    });
    copy.addEventListener("click", function () {
      copyText(doc, box, box.value).then(function () {
        copy.textContent = TEXT.copied;
        setTimeout(function () { copy.textContent = TEXT.copy; }, 1500);
      }, function () { box.focus(); box.select(); copy.textContent = TEXT.copyFail; });
    });
    open.addEventListener("click", function () {   // 不 preventDefault：照一般連結在新分頁打開（href 在這裡換好）
      var text = review.classList.contains("hidden") ? "" : box.value;
      var plan = issuePlan(text);
      open.href = plan.url;
      if (!plan.copy) { msg.textContent = text.trim() ? TEXT.opened : TEXT.blank; return; }
      msg.textContent = TEXT.long;
      copyText(doc, box, text).catch(function () { msg.textContent = TEXT.longFail; });
    });
  }

  var api = { issueUrl: issueUrl, issuePlan: issuePlan, init: init, ISSUE_NEW: ISSUE_NEW, TEMPLATE: TEMPLATE,
              FIELD: FIELD, MAX_URL: MAX_URL, TEXT: TEXT };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxReport = api; }
})(typeof window !== "undefined" ? window : this);
