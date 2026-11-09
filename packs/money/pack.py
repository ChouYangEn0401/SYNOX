"""💰 記帳：/money <金額> <類別> [備註]、/money_list [筆數]、/money_month、/money_budget <金額>。

資料經 pack.store.of(user)（保管箱，密文；個人版 data/money.json.enc，伺服器版每人一份 data/users/<id>/money.json.enc）：{"entries": [{amount, category, memo, at}], "budget": 數字或 null}。
記一筆讓這個月的總額超過預算時，回覆裡直接說。
"""

import time
from collections import defaultdict

from isdtelekit.core.registry import WRITE, Field

from synox.packs import kit

EMPTY = {"entries": [], "budget": None}


def fmt(x) -> str:
    x = float(x)
    return f"{int(x):,}" if x == int(x) else f"{x:,.2f}"


def month_key(ts=None) -> str:
    return time.strftime("%Y-%m", time.localtime(ts))


def month_total(data, key=None) -> float:
    key = key or month_key()
    return sum(float(e["amount"]) for e in data.get("entries", []) if month_key(e["at"]) == key)


def install(app, pack):
    g = pack.group

    def load(user):
        data = pack.store.of(user).load(None) or {}
        return {**EMPTY, **data}

    def add(api, chat_id, user, values):
        amount = float(values["amount"].replace(",", ""))
        if amount <= 0:
            api.send_message(chat_id, "❌ 金額要大於 0。")
            return
        entry = {"amount": amount, "category": values["category"].strip(), "memo": values.get("memo", "").strip(),
                 "at": int(time.time())}

        def append(d):
            d.setdefault("entries", []).append(entry)
            d.setdefault("budget", None)
            return month_total(d) - amount, month_total(d), d.get("budget")

        before, after, budget = pack.store.of(user).update(append, dict(EMPTY))
        memo = f"（{entry['memo']}）" if entry["memo"] else ""
        lines = [f"💰 記了：{entry['category']} {fmt(amount)} 元{memo}", f"這個月共 {fmt(after)} 元"]
        if budget:
            if before <= float(budget) < after:
                lines.append(f"⚠️ 這一筆讓這個月超過預算了（預算 {fmt(budget)} 元，超過 {fmt(after - float(budget))} 元）")
            elif after > float(budget):
                lines.append(f"⚠️ 這個月已經超過預算 {fmt(budget)} 元（超過 {fmt(after - float(budget))} 元）")
            else:
                lines.append(f"預算還剩 {fmt(float(budget) - after)} 元")
        api.send_message(chat_id, "\n".join(lines))

    def list_(api, chat_id, user, values):
        n = int(values.get("n") or 10)
        entries = load(user)["entries"][-n:]
        if not entries:
            api.send_message(chat_id, "💰 還沒有記帳。用 /money <金額> <類別> 記一筆。")
            return
        lines = [f"💰 最近 {len(entries)} 筆"]
        for e in reversed(entries):
            memo = f"（{e['memo']}）" if e.get("memo") else ""
            lines.append(f"{time.strftime('%m/%d', time.localtime(e['at']))}  {e['category']} {fmt(e['amount'])} 元{memo}")
        api.send_message(chat_id, "\n".join(lines))

    def month(api, chat_id, user, values):
        data = load(user)
        key = month_key()
        by_cat = defaultdict(float)
        for e in data["entries"]:
            if month_key(e["at"]) == key:
                by_cat[e["category"]] += float(e["amount"])
        total = sum(by_cat.values())
        lines = [f"💰 {key} 共 {fmt(total)} 元"]
        lines += [f"  {cat}：{fmt(v)} 元" for cat, v in sorted(by_cat.items(), key=lambda kv: -kv[1])]
        budget = data.get("budget")
        if budget:
            left = float(budget) - total
            lines.append(f"預算 {fmt(budget)} 元，" + (f"還剩 {fmt(left)} 元" if left >= 0 else f"⚠️ 超過 {fmt(-left)} 元"))
        else:
            lines.append("（還沒設預算：/money_budget <金額>）")
        api.send_message(chat_id, "\n".join(lines))

    def budget(api, chat_id, user, values):
        amount = float(values["amount"].replace(",", ""))
        if amount < 0:
            api.send_message(chat_id, "❌ 預算不能是負的。")
            return

        def set_budget(d):
            d["budget"] = amount or None
            d.setdefault("entries", [])
            return month_total(d)

        total = pack.store.of(user).update(set_budget, dict(EMPTY))
        if not amount:
            api.send_message(chat_id, "💰 預算拿掉了。")
            return
        api.send_message(chat_id, f"💰 每月預算設為 {fmt(amount)} 元（這個月目前 {fmt(total)} 元）。")

    kit.command(g, "add", add, "記一筆支出", default=True, effect=WRITE, fields=[
        Field("amount", "金額", required=True, check=kit.number),
        Field("category", "類別", required=True),
        Field("memo", "備註")])
    kit.command(g, "list", list_, "最近幾筆（預設 10）", fields=[Field("n", "筆數", check=kit.positive_int)])
    kit.command(g, "month", month, "這個月花了多少（分類別）")
    kit.command(g, "budget", budget, "設每月預算（0＝拿掉）", effect=WRITE,
                fields=[Field("amount", "金額", required=True, check=kit.number)])
