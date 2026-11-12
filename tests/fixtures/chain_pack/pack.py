"""測試用（docs/adr/0004 的例子）：「每日日記的圖片做好了 → 馬上再問一次要不要打卡」。

/diarydemo_image [ok|failed]   假裝圖片做完了：回報 pack.diarydemo 的狀態，標籤 diary-image
連動規則 ask-checkin：pack.diarydemo 變成 ok、標籤是 diary-image → 問擁有者要不要打卡；問完回報標籤 checkin-asked
（emits 宣告了 pack.diarydemo#checkin-asked：登記時就知道它不會繞回 diary-image 那條規則）。
"""

ASK = "📔 今天的日記圖片好了。要打卡今天的日記嗎？"


def install(app, pack):
    g = pack.group

    def image(api, chat_id, user, args):
        state = args[0] if args else "ok"
        pack.report_status(state, "日記圖片", tag="diary-image")
        api.send_message(chat_id, f"image={state}")

    def ask_checkin(event):
        app.notify_owner(f"{ASK}（{event.task}#{event.tag}，第 {event.depth} 層）")
        pack.report_status("ok", "問過打卡了", tag="checkin-asked")

    g.leaf("image", image, "假裝日記圖片做完了")
    pack.on_event("pack.diarydemo", "ask-checkin", ask_checkin, state="ok", tag="diary-image",
                  emits=["pack.diarydemo#checkin-asked"], cooldown_s=60, name="日記圖片好了 → 問要不要打卡")
