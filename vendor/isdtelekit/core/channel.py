"""
Channel 無關的訊息介面：dispatcher、指令只認得這裡的東西，不認識 Telegram。

    Telegram ───┐                                  ┌─ 指令（快速路徑）
    本機畫面 ───┼─► Inbound ─► Dispatcher.handle ─┼─ 進行中的多輪對話
    排程 ───────┘      ▲                           └─ 自由文字的出口（fallback）
                       │            handler(api, chat_id, user, args)
                各 channel 轉換          └─ api：回覆用的管子（Channel），從哪個 channel 進來就從哪個回去

進來：每個 channel 把自己平台的訊息轉成 Inbound（誰、在哪個對話、說了什麼或按了哪個按鈕）。
出去：handler 拿到的 api 實作同一組方法（下面的 Channel）。Telegram 的 BotAPI、本機的 ConsoleChannel、
     測試的 FakeChannel 都是它。

按鈕是純資料，沿用 Telegram 的形狀：
    reply_markup = {"inline_keyboard": [[{"text": "✅ 執行", "callback_data": "job_ok:1"}]]}
其他 channel 照這個畫按鈕，按下時把 callback_data 送回來（Inbound.button）。

使用者 id：內部的使用者 id 就是 Telegram user id（users.json 的 tg_id）。其他 channel 要把自己的身分對應到這個 id。
chat_id 是「回覆送到哪」，私訊時等於使用者 id——private_only 靠這一點判斷是不是私訊。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

# Inbound.channel 的值：訊息從哪條管子來（log、事件日誌、要不要算速率限制都看它）
TELEGRAM, CONSOLE, HTTP, ROUTINE_CHANNEL = "telegram", "console", "http", "routine"


@dataclass
class CallbackInfo:
    """按下按鈕：callback_data 由客戶端送來、可以偽造，dispatcher 會先以點擊者身分 authorize。"""
    chat_id: int
    message_id: int
    cq_id: str
    clicker_id: int
    data: str
    text: str = ""
    message_date: Optional[float] = None    # 按鈕所在那則訊息的時間（epoch 秒）；危險按鈕看它判斷過期了沒


@dataclass
class Inbound:
    """一則進來的訊息（或一次按鈕），已經跟平台無關。"""
    channel: str                            # TELEGRAM / CONSOLE / ROUTINE_CHANNEL …
    user_id: int                            # 內部使用者 id（= Telegram id）
    chat_id: int                            # 回覆送到哪；私訊時 == user_id
    text: str = ""                          # 附件編成 __MEDIA__:photo:<file_id>: 這類標記
    username: str = ""
    button: Optional[CallbackInfo] = None   # 有值就是按了按鈕，text 不用
    sent_at: Optional[float] = None         # 使用者送出的時間（epoch 秒）；bot 離線時累積的舊訊息靠它認出來
    edited: bool = False                    # 編輯過的舊訊息：不重新執行


class Channel(Protocol):
    """回覆用的管子。回傳值沿用 Telegram 的 dict：{"ok": bool, "result": {"message_id": …}}，
    handler 靠 message_id 之後再 edit_message_text / remove_buttons。

    chat_id 不是這個 channel 的對話時（例如管理員指令通知另一個使用者），channel 自己決定怎麼送
    （本機畫面印出來、測試記下來）。

    text 可以是 core/richtext.py 的 Html（有格式的訊息）：Telegram 用 parse_mode=HTML 送，
    不支援格式的 channel 用 plain(text) 印純文字。

    pin_message / unpin_message 是選配的：沒有釘選的 channel 可以什麼都不做、回 {"ok": True}；
    呼叫的一方用 getattr 取，沒有這兩個方法也不能壞。"""

    def send_message(self, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None,
                     quiet: bool = False, link_preview: bool = True) -> Dict[str, Any]: ...

    def send_photo(self, chat_id: int, photo: str, caption: str = "") -> Dict[str, Any]: ...

    def send_document(self, chat_id: int, document: str, caption: str = "") -> Dict[str, Any]: ...

    def send_media_group(self, chat_id: int, photo_paths: List[str], caption: str = "",
                         kind: str = "photo") -> Dict[str, Any]: ...

    def edit_message_text(self, chat_id: int, message_id: int, text: str,
                          reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...

    def remove_buttons(self, chat_id: int, message_id: int) -> Dict[str, Any]: ...

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> Dict[str, Any]: ...

    def download_file(self, file_id: str, dest_path: str) -> bool: ...

    def typing(self, chat_id: int) -> None: ...

    def delete_message(self, chat_id: int, message_id: int) -> Dict[str, Any]: ...


def buttons(*rows) -> Dict[str, Any]:
    """reply_markup 的小工具：buttons([("✅ 接受", "ok:1"), ("❌ 拒絕", "no:1")], [("略過", "skip:1")])。
    每個參數是一排；每一排是 (文字, callback_data) 的序列。"""
    return {"inline_keyboard": [[{"text": text, "callback_data": data} for text, data in row] for row in rows]}
