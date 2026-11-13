/* SYNOX 手機入口的進門頁：網址 # 後面的一次性鑰匙＋一組新的驗證碼 → POST /_synox/enter → 轉到工具的畫面。
 * 鑰匙一讀到就從網址拿掉（不留在網址列與歷史）。字一律 textContent。 */
(function () {
  "use strict";
  var TEXT = {
    noKey: "這個連結不完整。請回 Telegram 重新開一次手機入口。",
    wrong: "進不去：連結或驗證碼不對、過期了，或已經用過了。",
    offline: "連不上。入口可能已經關了；回 Telegram 重新開一次。",
    going: "對了，正在打開…"
  };
  var m = /(?:^#|&)k=([A-Za-z0-9_-]{16,200})/.exec(location.hash || "");
  var key = m ? m[1] : "";
  history.replaceState(null, "", "/");
  var msg = document.getElementById("enter-msg");
  if (!key) { msg.textContent = TEXT.noKey; }
  document.getElementById("enter-form").addEventListener("submit", function (e) {
    e.preventDefault();
    if (!key) { msg.textContent = TEXT.noKey; return; }
    var code = document.getElementById("enter-code").value.trim();
    fetch("/_synox/enter", { method: "POST", credentials: "same-origin",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ k: key, code: code }) })
      .then(function (r) { return r.json().then(function (d) { return [r.ok, d]; }); })
      .then(function (pair) {
        if (!pair[0] || !pair[1].ok) { msg.textContent = TEXT.wrong; return; }
        key = "";
        msg.textContent = TEXT.going;
        history.replaceState(null, "", pair[1].next);     // 「/#t=<票>」：只換 # 不會重新載入，所以接著 reload
        location.reload();
      }, function () { msg.textContent = TEXT.offline; });
  });
})();
