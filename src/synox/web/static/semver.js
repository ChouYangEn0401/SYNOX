/* SYNOX 網頁的版本比較（工具庫、衣櫃的「有新版」）：跟伺服器的 packs/upgrade.semver_key 同一套 SemVer 2.0.0 規則
 * （docs/versioning.md §1）：
 *   - X.Y.Z 按數值比（1.0.10 > 1.0.9）；正式版 > 同號的預覽版（0.1.3 > 0.1.3-beta.1）
 *   - 預覽版逐段比：數字段按數值（alpha.10 > alpha.2）、數字段 < 文字段、文字段照 ASCII（alpha < beta < rc）、
 *     前面都一樣時段數少的較舊（alpha < alpha.1）
 *   - `+build` 不看；不是 SemVer（含預覽版數字段前面補 0）＝比不出來，一律回「不是比較新」
 * 伺服器把這個檔原地塞進 app.html 主程式那個 script 標籤（INCLUDE:semver.js，跟 reply.js 一樣，同一個 CSP nonce）。
 * tests/js/test_semver.js 用 node 測（tests/test_web_semver.py）。
 */
(function (root) {
  "use strict";

  var ID = "(?:0|[1-9]\\d*|\\d*[A-Za-z-][0-9A-Za-z-]*)";
  var RE = new RegExp("^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)" +
    "(?:-(" + ID + "(?:\\." + ID + ")*))?(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$");

  function parse(v) {                   // → {core: [X, Y, Z], pre: [段…]}；看不懂回 null
    var m = RE.exec(String(v == null ? "" : v).trim());
    if (!m) { return null; }
    return { core: [+m[1], +m[2], +m[3]], pre: m[4] ? m[4].split(".") : [] };
  }

  function cmpId(a, b) {
    var an = /^\d+$/.test(a), bn = /^\d+$/.test(b);
    if (an && bn) { return (+a) - (+b) < 0 ? -1 : (+a) === (+b) ? 0 : 1; }
    if (an !== bn) { return an ? -1 : 1; }                 // 數字段 < 文字段
    return a < b ? -1 : a > b ? 1 : 0;                     // ASCII
  }

  function compare(a, b) {              // -1｜0｜1；任一個看不懂回 null
    var x = parse(a), y = parse(b);
    if (!x || !y) { return null; }
    for (var i = 0; i < 3; i++) { if (x.core[i] !== y.core[i]) { return x.core[i] < y.core[i] ? -1 : 1; } }
    if (!x.pre.length || !y.pre.length) {                  // 正式版 > 同號的預覽版
      return x.pre.length === y.pre.length ? 0 : (x.pre.length ? -1 : 1);
    }
    for (var j = 0; j < Math.min(x.pre.length, y.pre.length); j++) {
      var c = cmpId(x.pre[j], y.pre[j]);
      if (c) { return c; }
    }
    return x.pre.length === y.pre.length ? 0 : (x.pre.length < y.pre.length ? -1 : 1);
  }

  function newer(a, b) {                // a 比 b 新？
    return compare(a, b) === 1;
  }

  var api = { parse: parse, compare: compare, newer: newer };
  if (typeof module === "object" && module && module.exports) { module.exports = api; }
  else { root.SynoxSemver = api; }
})(typeof window !== "undefined" ? window : this);
