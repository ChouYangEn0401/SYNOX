"""📒 隨手記：/note <文字>、/note_list [關鍵字]、/note_rm <編號>、/note_clear。

資料經 pack.store.of(user)（保管箱，密文）：個人版一份共用檔；伺服器版每人一份 data/users/<id>/notes.json.enc。
"""

import time

from isdtelekit.core.registry import DANGER, WRITE, Field

from synox.packs import kit


def install(app, pack):
    g = pack.group

    def items(user):
        return (pack.store.of(user).load({"items": []}) or {}).get("items", [])

    def add(api, chat_id, user, values):
        text = values["text"].strip()
        count = pack.store.of(user).update(lambda d: (d.setdefault("items", []).append({"text": text, "at": int(time.time())}),
                                        len(d["items"]))[1], {"items": []})
        api.send_message(chat_id, f"📒 記下了（第 {count} 筆）：{text}")

    def list_(api, chat_id, user, values):
        kw = values.get("keyword", "").strip()
        rows = [(i, it) for i, it in enumerate(items(user), 1) if not kw or kw.lower() in it["text"].lower()]
        if not rows:
            api.send_message(chat_id, "📒 " + (f"沒有含「{kw}」的筆記。" if kw else "還沒有筆記。用 /note <文字> 記一筆。"))
            return
        head = f"📒 含「{kw}」的筆記（{len(rows)} 筆）" if kw else f"📒 全部筆記（{len(rows)} 筆）"
        lines = [f"{i}. {it['text']}  （{time.strftime('%m/%d %H:%M', time.localtime(it['at']))}）" for i, it in rows]
        api.send_message(chat_id, "\n".join([head] + lines))

    def rm(api, chat_id, user, values):
        n = int(values["n"])

        def drop(d):
            lst = d.setdefault("items", [])
            return lst.pop(n - 1) if 0 < n <= len(lst) else None

        gone = pack.store.of(user).update(drop, {"items": []})
        if gone is None:
            api.send_message(chat_id, f"❌ 沒有第 {n} 筆（/note_list 看編號）。")
            return
        api.send_message(chat_id, f"🗑 刪掉第 {n} 筆：{gone['text']}")

    def clear(api, chat_id, user, values):
        count = pack.store.of(user).update(lambda d: (len(d.get("items", [])), d.update(items=[]))[0], {"items": []})
        api.send_message(chat_id, f"🗑 全部筆記都刪掉了（{count} 筆）。")

    kit.command(g, "add", add, "記一筆", default=True, effect=WRITE,
                fields=[Field("text", "要記的內容", required=True)])
    kit.command(g, "list", list_, "列出筆記（可以帶關鍵字找）",
                fields=[Field("keyword", "關鍵字")])
    kit.command(g, "rm", rm, "刪掉一筆（編號看 /note_list）", effect=WRITE,
                fields=[Field("n", "編號", required=True, check=kit.positive_int)])
    kit.command(g, "clear", clear, "全部筆記都刪掉", effect=DANGER)
