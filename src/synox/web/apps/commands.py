"""🧩 工具服務的 Telegram 指令（計畫 C9、WP5；ADR 0026 對接 g）。

| 指令 | 危險程度 | 誰 | AI／排程 |
|---|---|---|---|
| `/apps` | 唯讀 | 看得到工具的人 | 可 |
| `/app_open <名字>` | 會寫入 | 擁有者、只在私訊 | **都不行**：`ai=False`、`interactive=True`（排程建立與到點都擋）、只收人 |
| `/app_close <名字｜all>` | 會寫入 | 擁有者 | 可（關是安全的） |

回覆裡不放 app 的網址、不放任何票：打開一律從 SYNOX 網頁的工具頁按「打開」。
"""

from __future__ import annotations

from isdtelekit.core.registry import READ, WRITE

from synox.web.apps.site import AppsError

GROUP = "apps"
TEXT = {
    "none": "還沒有任何工具附完整畫面。",
    "line_on": "● {title}：開著（{since} 分鐘、{idle} 分鐘沒用）　沒在用的時候：{policy}",
    "line_off": "○ {title}：關著　沒在用的時候：{policy}",
    "line_error": "⚠️ {title}：{why}",
    "line_problem": "⚠️ {title}：畫面現在不能開（{why}）",
    "keep_tag": "（一直開著）",
    "recent": "最近：",
    "how": "開：/app_open 名字　關：/app_close 名字",
    "remote_on": "　📱 手機入口開著（{left} 分鐘後自動關）",
    "which": "要開哪一個？有完整畫面的工具：{names}",
    "unknown": "沒有叫「{text}」的工具畫面。有完整畫面的工具：{names}",
    "opened": "{title}的服務開好了。到 SYNOX 網頁的工具頁按「打開」：{url}（要在跑 SYNOX 的這台電腦上）。"
              "不用的時候 /app_close {name}。",
    "first": "（第一次用：{what}\n{why}\n{restart}）",
    "closed": "關好了。資料都在，Telegram 照樣可以用。",
    "was_closed": "{title}的服務本來就關著。",
    "closed_all": "全部關好了（{n} 個）。資料都在，Telegram 照樣可以用。",
    "closed_none": "沒有開著的工具服務。",
    "remote_hint": "從手機用請打 /app_remote {name}（要先設定手機驗證器）。",
    "unavailable": "工具服務現在不能用：{why}",
}
EVENT_WORDS = {"start": "開了", "stop": "關了", "auto_stop": "自動關了", "suggest": "提醒很久沒用", "keep": "先留著",
               "policy": "改了閒置設定", "handoff": "打開了畫面", "enter": "進到畫面", "action": "畫面上做了一個動作",
               "export": "匯出了資料"}


def install(app, manager) -> None:
    from synox import guard
    from synox.packs.loader import group_policy
    registry = app.registry
    server = getattr(manager.config, "mode", "personal") == "server"
    registry.ensure_group(GROUP, "🧩 工具服務", "開、關、看每個工具自己的網頁", bare=True,
                          **group_policy(app, "member", server))
    g = registry.group(GROUP)

    def names(user=None) -> str:
        specs = manager.specs()
        return "、".join(f"{s.title}（{n}）" for n, s in sorted(specs.items())) or "（沒有）"

    def cmd_apps(api, chat_id, user, args):
        data = manager.views(user)
        lines = []
        for a in data["apps"]:
            policy = a["policy"]["text"] + (TEXT["keep_tag"] if a["policy"]["mode"] == "keep" else "")
            if a["problem"]:
                lines.append(TEXT["line_problem"].format(title=a["title"], why=a["problem"]))
            elif a["state"] == "on":
                since = _minutes_since(manager, a["name"])
                line = TEXT["line_on"].format(title=a["title"], since=since, idle=a["idle_min"], policy=policy)
                remote = _remote_line(app, a["name"])
                lines.append(line + remote)
            elif a["state"] == "error":
                lines.append(TEXT["line_error"].format(title=a["title"], why=a["error"]))
            else:
                lines.append(TEXT["line_off"].format(title=a["title"], policy=policy))
        if not lines:
            api.send_message(chat_id, TEXT["none"])
            return
        if not data["available"]:
            lines.append(TEXT["unavailable"].format(why=data["reason"]))
        if registry.is_owner(user):
            recent = [r for r in manager.audit.tail(20) if r.get("event") in EVENT_WORDS][:3]
            if recent:
                lines.append(TEXT["recent"] + "；".join(
                    f"{str(r.get('at', ''))[11:16]} {r.get('app')} {EVENT_WORDS[r['event']]}" for r in recent))
            lines.append(TEXT["how"])
        api.send_message(chat_id, "\n".join(lines))

    def cmd_open(api, chat_id, user, args):
        if not args:
            api.send_message(chat_id, TEXT["which"].format(names=names()))
            return
        if len(args) >= 2 and args[-1].lower() == "remote":            # 對接 g：手機入口在 /app_remote
            name = manager.resolve(" ".join(args[:-1])) or " ".join(args[:-1])
            if app.extras.get("synox_remote_open_command") is not None:
                app.extras["synox_remote_open_command"](api, chat_id, user, [name])
            else:
                api.send_message(chat_id, TEXT["remote_hint"].format(name=name))
            return
        name = manager.resolve(" ".join(args))
        if name is None:
            api.send_message(chat_id, TEXT["unknown"].format(text=" ".join(args)[:40], names=names()))
            return
        first = not manager._data()["explained"]
        try:
            manager.start(name, by=user, via="telegram")
        except AppsError as e:
            api.send_message(chat_id, "❌ " + e.message)
            return
        title = manager.specs()[name].title
        text = TEXT["opened"].format(title=title, url=manager.console_url(), name=name)
        if first:
            manager.mark_explained()
            v = manager.views(user)["explain"]
            text += "\n" + TEXT["first"].format(what=v["what"], why=v["why_close"], restart=v["restart"])
        api.send_message(chat_id, text)

    def cmd_close(api, chat_id, user, args):
        target = " ".join(args).strip()
        if not target or target.lower() == "all":
            stopped = manager.stop_all(by=user.tg_id, via="telegram", reason="owner")
            api.send_message(chat_id, TEXT["closed_all"].format(n=len(stopped)) if stopped else TEXT["closed_none"])
            return
        name = manager.resolve(target)
        if name is None:
            api.send_message(chat_id, TEXT["unknown"].format(text=target[:40], names=names()))
            return
        try:
            done = manager.stop(name, by=user.tg_id, via="telegram", reason="owner")
        except AppsError as e:
            api.send_message(chat_id, "❌ " + e.message)
            return
        api.send_message(chat_id, TEXT["closed"] if done else TEXT["was_closed"].format(title=manager._title(name)))

    g.leaf("apps", cmd_apps, "看每個工具的完整畫面開著沒、多久沒用", effect=READ)
    open_node = g.leaf("app_open", cmd_open, "開一個工具的完整畫面（之後在 SYNOX 網頁按「打開」）", usage="<名字>",
                       effect=WRITE, owner_only=True, private_only=True, interactive=True, ai=False)
    g.leaf("app_close", cmd_close, "關掉工具的完整畫面（資料都在）", usage="<名字|all>", effect=WRITE, owner_only=True)
    gate = guard.of(app)
    if gate is not None and gate.scope is not None:
        gate.scope.restrict(open_node.path, callers=("human",))


def _minutes_since(manager, name: str) -> int:
    st = manager._states.get(name)
    return int((manager.clock() - st.since) // 60) if st is not None and st.since else 0


def _remote_line(app, name: str) -> str:
    """有手機入口開著（ADR 0026，S14 之後）就多一句剩幾分鐘。"""
    remote = (getattr(app, "extras", None) or {}).get("synox_remote")
    if remote is None:
        return ""
    try:
        left = remote.minutes_left(name)
    except Exception:
        return ""
    return TEXT["remote_on"].format(left=left) if left else ""
