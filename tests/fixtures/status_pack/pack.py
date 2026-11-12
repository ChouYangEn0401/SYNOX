"""測試用：/statusdemo_report <ok|failed|running|idle> [訊息] 回報狀態；/statusdemo_peers 列出別人的狀態（只有 state）。"""


def install(app, pack):
    g = pack.group

    def report(api, chat_id, user, args):
        state = args[0] if args else "ok"
        accepted = pack.report_status(state, " ".join(args[1:]))
        api.send_message(chat_id, f"reported={accepted}")

    def peers(api, chat_id, user, args):
        found = pack.peer_status()
        api.send_message(chat_id, "peers=" + ",".join(f"{k}:{v['state']}" for k, v in sorted(found.items())))

    g.leaf("report", report, "回報狀態")
    g.leaf("peers", peers, "看別人的狀態")
