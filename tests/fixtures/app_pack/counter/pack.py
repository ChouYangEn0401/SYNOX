"""🔢 計數器（工具服務的測試 fixture）：/counter_add <n>、/counter_reset、/counter_show、/counter_poke <how>。
指令與工具畫面共用同一組核心函式（一個動作＝一個指令，ADR 0023 §2）。"""

from isdtelekit.core.registry import DANGER, READ, WRITE, Field

from synox.packs import kit

CALLS = {"reset": 0, "export": 0, "poke": 0}        # 測試用的計數器：工具的函式到底有沒有被叫到


def install(app, pack):
    g = pack.group

    def state(user):
        return pack.store.of(user).load({"n": 0}) or {"n": 0}

    def add_core(user, n):
        def change(d):
            d["n"] = int(d.get("n", 0)) + n
            return d["n"]
        return pack.store.of(user).update(change, {"n": 0})

    def reset_core(user):
        CALLS["reset"] += 1
        pack.store.of(user).save({"n": 0})
        return 0

    def poke_core(how):
        CALLS["poke"] += 1
        if how == "refuse":
            raise kit.AppError("沒有這筆")
        if how == "boom":
            raise ValueError("秘密字串-poke")
        return {"poked": how}

    kit.command(g, "add", lambda api, chat_id, user, v: api.send_message(chat_id, f"現在是 {add_core(user, int(v['n']))}"),
                "加一個數", default=True, effect=WRITE, fields=[Field("n", "數字", required=True, check=kit.positive_int)])
    kit.command(g, "reset", lambda api, chat_id, user, v: api.send_message(chat_id, f"歸零了：{reset_core(user)}"),
                "歸零", effect=DANGER)
    kit.command(g, "show", lambda api, chat_id, user, v: api.send_message(chat_id, f"現在是 {state(user)['n']}"),
                "看現在是多少", effect=READ)
    kit.command(g, "poke", lambda api, chat_id, user, v: api.send_message(chat_id, str(poke_core(v["how"]))),
                "測試用", effect=WRITE, fields=[Field("how", "方式", required=True, choices=("ok", "refuse", "boom"))])

    if hasattr(pack, "app_read"):
        pack.app_read("state", lambda user, params: state(user))
        pack.app_action("add", lambda user, values: {"n": add_core(user, int(values["n"]))})
        pack.app_action("reset", lambda user, values: {"n": reset_core(user)},
                        describe=lambda user, values: "把數字歸零？")
        pack.app_action("poke", lambda user, values: poke_core(values["how"]))

        def export(user, params):
            CALLS["export"] += 1
            return kit.Download("counter.csv", "text/csv; charset=utf-8", kit.csv_bytes(["n"], [[state(user)["n"]]]))
        pack.app_export("state_csv", export)
