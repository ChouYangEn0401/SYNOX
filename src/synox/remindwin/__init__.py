"""
電腦提醒視窗＋提醒哨兵（docs/adr/0028 §3.4–3.5、docs/notifications.md「電腦提醒視窗」）。

- logic.py：視窗的邏輯（讀 to_win、寫 shown／act、延後時間怎麼算、多張卡怎麼疊）。**不開視窗就能測**。
- window.py：tkinter 畫面（右下角、永遠在最上層、多張往上疊、響一聲；不處理不會自己關）。只負責畫，邏輯全在 logic.py。
- sentinel.py：提醒哨兵（`python -m synox sentinel`）：登入 Windows 時自動啟動；主程式沒開時跑提醒引擎，開著時讓位。
- launcher.py：開視窗程式、哨兵啟動檔的指令（pythonw，不跳黑窗）。

視窗程式：`python -m synox.remindwin --data <data 資料夾>`（主程式／哨兵要跳提醒時自己開；popup.lock 保證只有一個）。
不開任何網路埠：跟引擎之間只有 data/remind/desk/ 裡的小檔案。
"""
