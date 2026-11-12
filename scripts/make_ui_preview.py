"""產生網頁介面的靜態預覽（給人雙擊看設計，不用開 SYNOX、不開任何網路埠）。

    .venv\\Scripts\\python.exe scripts\\make_ui_preview.py

寫出：
- docs/ui/preview.html        真的 src/synox/web/static/app.html（含 tools.css／tools.js，跟 server.render_app 同一個函式），
                              前面插一段「假的 fetch」（假資料、不送出任何東西）。
                              網址參數：?login=1 看登入畫面、?theme=dark|light 強制深淺色、?bar=0 拿掉上方的預覽列、
                              ?tooledit=1 工具頁直接打開「編輯群組」；?ctl=error 主控頁讀不到時的樣子、?member=1 用成員身分看
                              （沒有「主控」）；#chat／#tools／#settings／#control 切頁。
                              開場動畫（static/splash.js）：同一個分頁只播第一次；?splash=1 重播（預覽列的「重播開場」）、
                              ?splash=0 不播；?splashat=600 讓開場停在第 600 毫秒（拍關鍵影格用）。
                              工具頁的群組編輯可以真的操作（存在這一頁的記憶體裡，重新整理就回到預設）。
- docs/ui/preview-phone.html、preview-phone-dark.html
                              六個 390px 寬的框（登入、對話、工具、工具的編輯群組、設定、主控），看手機寬度用。
                              「登入」那一格每次打開都重播開場，其他格不播。
- docs/ui/preview-login.html  伺服器產生的「登入確認頁」（server.py 的 login_page，用假的帳號資料）。
- docs/ui/preview-error.html  伺服器產生的小頁（server.py 的 _page，例如登入連結不能用）。

樣式只寫在 app.html／server.py 一處；這個腳本只是把它們包成可以離線打開的檔案，改了樣式就重跑。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from synox.web import server, toolpage  # noqa: E402

OUT = os.path.join(ROOT, "docs", "ui")

# ── 假資料（形狀照 server.py 各 API 的回應；名字、id 都是佔位） ─────────────────
ME = {"id": 100001, "username": "小明", "role": "admin", "owner": True, "csrf": "preview"}

CHATS = [
    {"id": "c1", "title": "今天要做的事", "last": "好，兩件都記下來了。"},
    {"id": "c2", "title": "記帳", "last": "記了：午餐 120 元"},
    {"id": "c3", "title": "週末行程", "last": "（還沒有訊息）"},
    {"id": "tools", "title": "🧰 工具頁", "last": "/note_list"},
]

EVENTS = {
    "c1": [
        {"id": 1, "from": "me", "text": "幫我記：買牛奶、繳電費"},
        {"id": 2, "from": "bot", "text": "好，兩件都記下來了。\n📝 買牛奶\n📝 繳電費"},
        {"id": 3, "from": "me", "text": "把筆記全部刪掉"},
        {"id": 4, "from": "note", "text": "AI 想用一個會刪東西的工具，先問你"},
        {"id": 5, "from": "bot", "text": "⚠️ 要刪掉全部 2 則筆記嗎？這個沒辦法復原。",
         "buttons": [[{"text": "✅ 刪掉", "data": "ok"}, {"text": "取消", "data": "no"}]]},
    ],
    "c2": [
        {"id": 1, "from": "me", "text": "/money 120 午餐"},
        {"id": 2, "from": "bot", "text": "記了：午餐 120 元\n這個月：3,420／預算 12,000"},
    ],
    "c3": [],
    "tools": [{"id": 1, "from": "me", "text": "/note_list"}, {"id": 2, "from": "bot", "text": "1. 買牛奶\n2. 繳電費"}],
}

def _cmd(command, summary, effect="read", fields=(), usage="", default=False, confirm=False):
    """假的指令卡（形狀照 web/toolpage.py 的 command_info）。"""
    return {"command": command, "usage": usage, "summary": summary, "effect": effect, "path": command.strip("/"),
            "default": default, "ai": True, "confirm": confirm, "fields": list(fields), "asks_code": False}


def _f(name, label, kind="text", required=False, default="", help_="", choices=None):
    out = {"name": name, "label": label, "kind": kind, "required": required, "default": default}
    if help_:
        out["help"] = help_
    if choices:
        out["choices"] = choices
    return out


TOOLS = {
    "packs": [
        {"id": "note", "name": "notes", "title": "📝 筆記", "version": "0.2.0", "kind": "python", "category": "生活",
         "summary": "隨手記下想到的事", "description": "使用者想記下一件事、看記過的事、或清掉筆記時使用。",
         "status": "已連接", "commands": [
             _cmd("/note", "記一則筆記", "write", [_f("text", "內容", required=True)], default=True),
             _cmd("/note_list", "列出全部筆記"),
             _cmd("/note_clear", "全部刪掉（不能復原）", "danger")]},
        {"id": "money", "name": "money", "title": "💰 記帳", "version": "0.2.0", "kind": "python", "category": "生活",
         "summary": "記一筆、看這個月花了多少", "description": "使用者提到花了多少錢、想記帳、問這個月花多少時使用。",
         "status": "已連接", "commands": [
             _cmd("/money", "記一筆支出", "write", [
                 _f("amount", "金額", "number", required=True, help_="只放數字，例如 120"),
                 _f("category", "類別", default="其他", help_="例如 餐飲、交通"),
                 _f("memo", "備註")], default=True),
             _cmd("/money_month", "這個月的合計與預算"),
             _cmd("/money_budget", "設每月預算", "write", [_f("amount", "每月預算", "int", required=True)])]},
        {"id": "todoist", "name": "todoist", "title": "✅ Todoist", "version": "0.2.0", "kind": "python",
         "category": "待辦與行程", "summary": "把待辦送進 Todoist", "description": "",
         "status": "要先設定", "connect": True, "missing": ["API token"], "commands": [
             _cmd("/todo", "新增一個待辦", "write", [
                 _f("content", "要做什麼", required=True),
                 _f("due", "什麼時候", help_="例如 明天、週五 15:00；不填＝沒有期限")], default=True),
             _cmd("/todo_list", "今天的待辦")]},
        {"id": "gcal", "name": "google-calendar", "title": "📅 Google 日曆", "version": "0.2.0", "kind": "python",
         "category": "待辦與行程", "summary": "看行程、加行程", "description": "", "status": "已連接", "commands": [
             _cmd("/gcal_list", "接下來的行程", fields=[_f("days", "看幾天", "int", default="7")], default=True),
             _cmd("/gcal_add", "加一個行程", "write", [
                 _f("title", "標題", required=True), _f("when", "時間", required=True, help_="例如 11/20 14:00")],
                  confirm=True),
             _cmd("/gcal_rm", "刪掉一個行程", "danger", [_f("number", "編號（/gcal_list 的）", "int", required=True)])]},
        {"id": "hello", "name": "hello", "title": "👋 範例", "version": "0.1.0", "kind": "cli", "category": "",
         "summary": "算小費、打招呼（synox_sdk 的最小範例）", "description": "", "status": "已連接", "commands": [
             _cmd("/hello", "算含小費的總額", fields=[
                 _f("amount", "帳單金額", "number", required=True), _f("percent", "小費幾 %", "int", default="10"),
                 _f("round_up", "要不要進位到整數", "bool", default="false")], default=True),
             _cmd("/hello_greet", "跟某人打招呼", fields=[
                 _f("name", "要打招呼的人", required=True),
                 _f("style", "語氣", "choice", default="casual", choices=["casual", "formal"])])]},
    ],
    "groups": [
        {"id": "_basics", "title": "🧭 基本", "summary": "開始、說明、結束問答", "category": toolpage.BUILTIN,
         "commands": [_cmd("/start", "開始"), _cmd("/help", "看全部指令")]},
        {"id": "remind", "title": "⏰ 提醒（系統）",
         "summary": "SYNOX 內建的提醒：每天幾點、或指定哪一天提醒你一件事（不是 Apple 提醒事項）", "category": toolpage.BUILTIN,
         "commands": [_cmd("/remind_add", "加一個提醒（系統；每天，或 date= 指定那天一次）", "write",
                           usage="<HH:MM> <內容> [date=…]"),
                      _cmd("/remind_list", "列出提醒（系統）")]},
        {"id": "schedule", "title": "🗓 排程指令", "summary": "每天幾點自動替你執行一個指令", "category": toolpage.BUILTIN,
         "commands": [_cmd("/schedule_list", "列出排程")]},
        {"id": "agent", "title": "🤖 AI", "summary": "", "category": toolpage.BUILTIN,
         "commands": [_cmd("/ai_usage", "這個月用了多少")]},
    ],
}
TOOLS["layout"] = toolpage.effective(None, [(t["id"], t["category"]) for t in TOOLS["packs"] + TOOLS["groups"]])

SECRETS = {"fields": [{"name": "token", "label": "API token", "required": True, "secret": True, "set": False,
                       "help": "Todoist 網頁 → 設定 → 整合 → 開發者"}]}

SETTINGS = {
    "owner": True, "accounts": True, "ai_budget": None,
    "llm": {"kind": "claude_code", "model": "", "base_url": "", "has_key": False},
    "llm_choices": [
        {"label": "Claude Code（用你自己的 Claude 訂閱）", "choice": "claude_code",
         "models": [{"value": "", "label": "預設（讓 Claude Code 自己選）"}, {"value": "sonnet", "label": "Sonnet（平衡）"},
                    {"value": "opus", "label": "Opus（最強、較慢）"}, {"value": "haiku", "label": "Haiku（最快、最省）"}]},
        {"label": "API 金鑰：OpenAI", "choice": "keys", "provider": "openai", "model": "（照預設）"},
        {"label": "API 金鑰：本機或相容的服務", "choice": "keys", "provider": "openai_compat", "needs_url": True},
        {"label": "先不用 AI", "choice": "none"},
    ],
    "packs": [
        {"name": "notes", "status": "loaded", "version": "0.2.0", "lock": "locked", "removable": False},
        {"name": "money", "status": "loaded", "version": "0.2.0", "lock": "locked", "removable": False},
        {"name": "todoist", "status": "connector", "version": "0.2.0", "lock": "locked", "removable": False},
        {"name": "example-tool", "status": "rejected", "detail": "掃描沒過：用了動態執行程式碼", "version": "1.0.0",
         "lock": "unlocked", "removable": True},
    ],
}

# 主控頁（/api/runtime/*）：時間寫成「離現在幾分鐘」，假 fetch 打開時才換成 ISO 時間，預覽檔才不會每跑一次就變。
RUNTIME = {
    "heartbeat": {"enabled": True, "interval_min": 45, "last_run_min": -12, "next_run_min": 33,
                  "last_result": {"ok": True, "message": "看過一輪：任務都正常，沒有要提醒你的事。"}},
    "mother": {"state": "idle", "last_active_min": -3, "soul_updated_min": -26 * 60},
    "tasks": [
        {"id": "morning-digest", "name": "早上的摘要", "owner": "SYNOX", "schedule": "每天 08:00", "state": "ok",
         "last_run_min": -5 * 60, "last_message": "送出了：今天 2 個行程、1 個待辦"},
        {"id": "budget-watch", "name": "預算檢查", "owner": "example-budget", "schedule": "每 6 小時", "state": "failed",
         "last_run_min": -40, "last_message": "讀不到這個月的資料，下一輪會再試"},
        {"id": "calendar-sync", "name": "行事曆同步", "owner": "example-calendar", "schedule": "每 30 分鐘",
         "state": "running", "last_run_min": -1, "last_message": "同步中…"},
        {"id": "weekly-review", "name": "每週回顧", "owner": "example-notes", "schedule": "每週日 21:00", "state": "idle",
         "last_run_min": None, "last_message": ""},
    ],
}

TASK_LOGS = {
    "morning-digest": ["08:00:01 開始", "08:00:02 讀了 2 個行程、1 個待辦", "08:00:03 送出摘要", "08:00:03 完成"],
    "budget-watch": ["10:20:00 開始", "10:20:01 讀這個月的資料", "10:20:31 等太久沒有回應（30 秒）", "10:20:31 沒有完成，下一輪再試"],
    "calendar-sync": ["10:59:00 開始", "10:59:01 比對 14 筆"],
    "weekly-review": [],
}

SOUL = ("# 關於我\n- 叫我小明\n- 早上 9 點前不要傳訊息給我\n\n# 要你注意的事\n- 記帳超過預算八成就提醒我\n"
        "- 週末不要排工作的事\n")

CHANNELS = {"telegram": {"saved": True, "bot": "my_synox_bot", "active": True, "owner_paired": True},
            "discord": {"saved": False, "multi": False, "invite": ""}}

ACCOUNTS = {"roles": ["guest", "member", "admin"], "users": [
    {"id": 100001, "username": "小明", "role": "admin", "owner": True, "messages_today": 12, "messages_limit": 200,
     "ai_month_usd": 1.2, "ai_limit_usd": 20},
    {"id": 100002, "username": "阿華", "role": "member", "messages_today": 3, "messages_limit": 100,
     "ai_month_usd": 0.4, "ai_limit_usd": 2},
    {"id": 100003, "username": "新朋友", "role": "guest", "pending": True}]}

MOCK = r"""
(function () {
  "use strict";
  // 預覽專用：把 fetch 換成假的，全部回假資料；不送出任何東西。
  var q = new URLSearchParams(location.search);
  if (q.get("theme")) { document.documentElement.setAttribute("data-theme", q.get("theme")); }
  var D = __DATA__;
  var loggedOut = q.get("login") === "1";
  if (q.get("member") === "1") { D.me.owner = false; D.me.role = "member"; D.me.username = "阿華"; }
  var seq = 100;
  function reply(body, status) {
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: status || 200, headers: { "Content-Type": "application/json" } }));
  }
  // 主控頁：「離現在幾分鐘」換成 ISO 時間
  function at(min) { return min === null || min === undefined ? null : new Date(Date.now() + min * 60000).toISOString(); }
  var R = D.runtime, soul = { text: D.soul, updated_at: at(R.mother.soul_updated_min) };
  var hb = { enabled: R.heartbeat.enabled, interval_min: R.heartbeat.interval_min, last_run_at: at(R.heartbeat.last_run_min),
             next_run_at: at(R.heartbeat.next_run_min), last_result: R.heartbeat.last_result };
  var mother = { state: R.mother.state, last_active_at: at(R.mother.last_active_min), soul_updated_at: soul.updated_at };
  var tasks = R.tasks.map(function (t) {
    return { id: t.id, name: t.name, owner: t.owner, schedule: t.schedule, state: t.state,
             last_run_at: at(t.last_run_min), last_message: t.last_message };
  });
  function runtime(p, method, opts) {
    if (q.get("ctl") === "error") { return reply({ error: "出錯了：KeyError" }, 500); }   // 示範「讀不到」的樣子
    var body = opts && opts.body ? JSON.parse(opts.body) : {};
    if (p === "/api/runtime/status") { return reply({ heartbeat: hb, mother: mother, tasks: tasks }); }
    if (p === "/api/runtime/heartbeat") {
      if (body.enabled !== undefined) { hb.enabled = body.enabled; }
      if (body.interval_min !== undefined) { hb.interval_min = body.interval_min; }
      hb.next_run_at = hb.enabled ? at(hb.interval_min) : null;
      return reply(hb);
    }
    if (p === "/api/runtime/heartbeat/run-now") {
      hb.last_run_at = at(0); hb.next_run_at = hb.enabled ? at(hb.interval_min) : null; mother.last_active_at = at(0);
      hb.last_result = { ok: true, message: "（預覽）剛剛看過一輪，沒有新的事。" };
      return reply({ ok: true, message: "開始了（預覽：沒有真的跑）。結果會出現在「上次結果」。" });
    }
    if (p === "/api/runtime/mother/reset-memory") { mother.last_active_at = at(0); return reply({ ok: true }); }
    if (p === "/api/runtime/soul") {
      if (method === "PUT") { soul = { text: body.text, updated_at: at(0) }; mother.soul_updated_at = soul.updated_at; }
      return reply(soul);
    }
    var m = /^\/api\/runtime\/tasks\/([^/]+)\/log$/.exec(p);
    if (m) { return reply({ lines: D.logs[decodeURIComponent(m[1])] || [] }); }
    return reply({ error: "沒有這個 API。" }, 404);
  }
  window.fetch = function (path, opts) {
    var method = (opts && opts.method) || "GET";
    var p = String(path).split("?")[0];
    if (p.indexOf("/api/runtime/") === 0) { return runtime(p, method, opts); }
    if (p === "/api/me") { return loggedOut ? reply({ error: "請先登入" }, 401) : reply(D.me); }
    if (p === "/api/chats" && method === "GET") { return reply({ chats: D.chats }); }
    if (p === "/api/chats") {
      var id = "c" + (++seq);
      D.chats.unshift({ id: id, title: "新對話", last: "" }); D.events[id] = [];
      return reply({ id: id });
    }
    var m = /^\/api\/chat\/([^/]+)\/(events|send|press)$/.exec(p);
    if (m) {
      var list = D.events[m[1]] || (D.events[m[1]] = []);
      if (m[2] === "events") { return reply({ messages: list.slice(), rev: list.length }); }
      if (m[2] === "send") {
        var text = JSON.parse(opts.body).text;
        list.push({ id: ++seq, from: "me", text: text });
        list.push({ id: ++seq, from: "bot", text: "（預覽：這裡不會真的送出，SYNOX 的回覆會出現在這裡）" });
        return reply({ ok: true });
      }
      list.push({ id: ++seq, from: "note", text: "（預覽：按了按鈕）" });
      return reply({ ok: true });
    }
    if (p === "/api/tools") { return reply(D.tools); }
    if (p === "/api/tools/layout") {       // 群組編輯：只存在這一頁的記憶體
      var b = JSON.parse(opts.body);
      if (b.reset) { D.tools.layout = JSON.parse(D.defaultLayout); }
      else {
        D.tools.layout = { custom: true, groups: b.groups.map(function (g) {
          return { id: g.id, title: g.title, tools: g.tools, auto: false }; }) };
      }
      return reply({ ok: true, layout: D.tools.layout });
    }
    if (p.indexOf("/api/pack-secrets/") === 0) {
      return method === "GET" ? reply(D.secrets) : reply({ message: "（預覽：沒有真的存）", status: "還沒連接",
        connected: false, fields: D.secrets.fields });
    }
    if (p === "/api/settings") { return reply(D.settings); }
    if (p === "/api/settings/channels") { return reply(D.channels); }
    if (p === "/api/accounts") { return reply(D.accounts); }
    if (p === "/api/usage") {                     // 假的用量：讓設定頁的「AI 用量與花費」有東西看
      var per = (String(path).split("period=")[1] || "day").split("&")[0];
      var n = { hour: 24, day: 14, week: 12, month: 12 }[per] || 14, pts = [], total = { calls: 0, input: 0, output: 0, usd: 0 };
      for (var i = 0; i < n; i++) {
        var calls = (i * 7 + 3) % 9 === 0 ? 0 : (i * 5 + 2) % 11 + 1;
        var usd = calls * (per === "hour" ? 0.004 : per === "day" ? 0.02 : per === "week" ? 0.11 : 0.46);
        var tin = calls * 1800, tout = calls * 240;
        pts.push({ key: String(i), label: per === "hour" ? (i < 10 ? "0" : "") + i + ":00" : per === "month" ? "2026-" + (i < 9 ? "0" : "") + (i + 1)
          : (i + 1 < 10 ? "0" : "") + (i + 1) + "-" + (per === "week" ? "09起" : "01"), calls: calls, input: tin, output: tout,
          usd: Math.round(usd * 10000) / 10000, est: false });
        total.calls += calls; total.input += tin; total.output += tout; total.usd += usd;
      }
      total.usd = Math.round(total.usd * 10000) / 10000;
      return reply({ period: per, points: pts, total: total, estimated: false, kind: "claude_code", subscription: true });
    }
    return reply({ message: "（預覽：沒有真的做）", ok: true });
  };
  // 主控頁的示範（截圖用）：?open=log 打開失敗那個任務的日誌、?open=reset 打開清空記憶的確認，可以用逗號一起
  var demo = (q.get("open") || "").split(",");
  if (demo[0]) {
    window.addEventListener("load", function () {
      setTimeout(function () {
        if (demo.indexOf("log") >= 0) {
          var heads = document.querySelectorAll(".ctl-task-head");
          if (heads[1]) { heads[1].click(); }
        }
        if (demo.indexOf("reset") >= 0) {
          var b = document.querySelectorAll(".ctl button.danger")[0];
          if (b) { b.click(); }
        }
      }, 200);
    });
  }
  D.defaultLayout = JSON.stringify(D.tools.layout);
  if (q.get("tooledit") === "1") {        // 工具頁直接打開「編輯群組」（截圖用）
    var tries = 0;
    var wait = setInterval(function () {
      tries += 1;
      if (document.querySelector(".tp") && window.SynoxTools) { clearInterval(wait); window.SynoxTools.edit(); }
      else if (tries > 50) { clearInterval(wait); }
    }, 100);
  }
  // 拍開場的關鍵影格：?splash=1&splashat=600 → 全部動畫停在第 600 毫秒（開場以外的進場從 1250 毫秒、淡出那一刻才開始算）
  if (q.get("splashat") !== null && Number(q.get("splashat")) >= 0) {
    var freezeAt = Number(q.get("splashat"));
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(function () {
        if (!document.getAnimations) { return; }
        document.getAnimations().forEach(function (a) {
          var t = a.effect && a.effect.target;
          var inSplash = !!(t && t.closest && t.closest(".sx-splash"));
          a.pause();
          a.currentTime = inSplash ? freezeAt : Math.max(0, freezeAt - 1250);
        });
      }, 120);
    });
  }
  // 上方的預覽列（?bar=0 拿掉）
  if (q.get("bar") === "0") { return; }
  document.addEventListener("DOMContentLoaded", function () {
    var bar = document.createElement("div");
    bar.className = "preview-bar";
    var theme = q.get("theme") ? "theme=" + q.get("theme") : "";
    var items = [["登入畫面", function () { return "?login=1"; }],
                 ["對話", function () { return "?" + theme + "#chat"; }],
                 ["工具", function () { return "?" + theme + "#tools"; }],
                 ["工具：編輯群組", function () { return "?" + (theme ? theme + "&" : "") + "tooledit=1#tools"; }],
                 ["設定", function () { return "?" + theme + "#settings"; }],
                 ["主控", function () { return "?" + theme + "#control"; }],
                 ["主控讀不到", function () { return "?ctl=error" + (theme ? "&" + theme : "") + "#control"; }],
                 ["成員看到的", function () { return "?member=1" + (theme ? "&" + theme : "") + "#control"; }],
                 ["淺色", function () { return "?theme=light" + location.hash; }],
                 ["深色", function () { return "?theme=dark" + location.hash; }],
                 ["跟隨系統", function () { return "?" + location.hash; }],
                 ["重播開場", function () { return "?splash=1" + (theme ? "&" + theme : "") + location.hash; }]];
    var label = document.createElement("b"); label.textContent = "設計預覽（假資料）";
    bar.appendChild(label);
    items.forEach(function (it) {
      var a = document.createElement("a"); a.textContent = it[0]; a.href = it[1]();
      a.addEventListener("mouseenter", function () { a.href = it[1](); });
      a.addEventListener("focus", function () { a.href = it[1](); });
      bar.appendChild(a);
    });
    document.body.appendChild(bar);
  });
})();
"""

BAR_CSS = """
  .preview-bar { position: fixed; top: 8px; right: 8px; z-index: 60; display: flex; flex-wrap: wrap; gap: 4px;
    align-items: center; max-width: calc(100% - 16px); padding: 5px 8px; font-size: 12px; border-radius: 10px;
    background: var(--text); color: var(--bg); box-shadow: var(--shadow-md); opacity: .92; }
  .preview-bar b { margin-right: 4px; }
  .preview-bar a { color: inherit; padding: 2px 7px; border-radius: 6px; text-decoration: none;
    border: 1px solid color-mix(in srgb, var(--bg) 30%, transparent); }
"""


def app_preview() -> str:
    html = server.render_app("preview")          # 跟伺服器送出的頁面同一個函式（含 tools／control 的 css／js）
    data = {"me": ME, "chats": CHATS, "events": EVENTS, "tools": TOOLS, "secrets": SECRETS,
            "settings": SETTINGS, "channels": CHANNELS, "accounts": ACCOUNTS,
            "runtime": RUNTIME, "logs": TASK_LOGS, "soul": SOUL}
    mock = MOCK.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    note = ("<!-- 自動產生：scripts/make_ui_preview.py（不要手改；改 src/synox/web/static/app.html、tools.css、"
            "tools.js、splash.css、splash.js 再重跑） -->\n")
    html = html.replace("</style>", BAR_CSS + "</style>", 1)
    head_script = f'<script nonce="preview">{mock}</script>\n<script nonce="preview">'
    return note + html.replace('<script nonce="preview">', head_script, 1)


class _Users:
    def get(self, tg_id):
        return type("U", (), {"username": "小明"})()


class _Tokens:
    def peek(self, token):
        return 100001


def login_preview() -> str:
    ui = server.WebUI.__new__(server.WebUI)          # 只要畫登入確認頁：不建 app、不開埠
    ui.app = type("App", (), {"users": _Users()})()
    ui.config = type("Cfg", (), {"web": {}})()
    ui.tokens = _Tokens()
    ui._login_forms = {}
    ui._login_lock = threading.Lock()
    ui._clock = lambda: 0.0
    _, _, body = ui.login_page("preview", {}, None)
    # 表單 token 每次隨機：換成固定字，預覽檔才不會每跑一次就變
    return re.sub(r'name="f" value="[^"]*"', 'name="f" value="preview"', body.decode("utf-8"))


PHONE = """<!doctype html>
<!-- 自動產生：scripts/make_ui_preview.py -->
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SYNOX 手機寬度預覽</title>
<style>
  body { margin: 0; padding: 20px; background: #dfe4ea; font: 14px/1.5 "Segoe UI", "Microsoft JhengHei UI", sans-serif;
         color: #131b26; }
  h1 { font-size: 18px; margin: 0 0 4px; } p { margin: 0 0 16px; color: #4a5567; }
  .row { display: flex; gap: 20px; flex-wrap: wrap; align-items: flex-start; }
  figure { margin: 0; } figcaption { font-weight: 600; margin-bottom: 6px; }
  iframe { width: 390px; height: 780px; border: 0; border-radius: 28px; background: #fff;
           box-shadow: 0 0 0 10px #131b26, 0 24px 50px -12px rgba(0,0,0,.45); margin: 10px; }
</style></head><body>
<h1>手機寬度（390px）預覽</h1>
<p>每一格都是 preview.html（假資料）。深淺色：__THEME_LINKS__</p>
<div class="row">__FRAMES__</div>
</body></html>
"""


def phone_preview() -> str:
    frames = [("登入", "login=1"), ("對話", "#chat"), ("工具", "#tools"), ("工具：編輯群組", "tooledit=1#tools"),
              ("設定", "#settings"), ("主控", "#control")]
    out = []
    for title, q in frames:
        query, _, hash_ = q.partition("#")
        splash = "splash=1" if title == "登入" else "splash=0"      # 登入那格重播開場，其他格不播（六格一起播太吵）
        src = (f"preview.html?bar=0&amp;{splash}&amp;theme=__T__" + (("&amp;" + query) if query else "")
               + (("#" + hash_) if hash_ else ""))
        out.append(f'<figure><figcaption>{title}</figcaption><iframe title="{title}" src="{src}"></iframe></figure>')
    links = '<a href="preview-phone.html">淺色</a>、<a href="preview-phone-dark.html">深色</a>'
    return PHONE.replace("__FRAMES__", "".join(out)).replace("__THEME_LINKS__", links)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    phone = phone_preview()
    pages = {
        "preview-phone.html": phone.replace("__T__", "light"),
        "preview-phone-dark.html": phone.replace("__T__", "dark"),
        "preview.html": app_preview(),
        "preview-login.html": login_preview(),
        "preview-error.html": server._page(403, "登入連結不能用", server.LOGIN_BAD)[2].decode("utf-8"),
    }
    for name, text in pages.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("wrote", os.path.relpath(os.path.join(OUT, name), ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
