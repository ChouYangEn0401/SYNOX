/* 計數器的畫面：只用 SynoxApp.*（共用元件），不自己連線。 */
SynoxApp.ready(function () {
  "use strict";
  var main = document.getElementById("app");
  var line = SynoxApp.el("p", "card", "…");
  main.appendChild(line);
  function load() {
    SynoxApp.read("state").then(function (d) { line.textContent = "現在是 " + d.n; });
  }
  main.appendChild(SynoxApp.form("add", { onDone: load }));
  load();
});
