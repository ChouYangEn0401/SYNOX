"""
原本的 SYNOX 在各個 slot 放的東西（沒有套外觀包、也沒有自己貼的時候）。

- mascot.idle：「S」方塊（app.html 裡的 .mark 本身，不在這裡）
- wordmark：文字 SYNOX（app.html 裡，不在這裡）
- opening：S 寶寶掉下來的開場（static/splash.js 自己畫）
- appicon：沒有（瀏覽器的預設圖示）
- 下面這三個：網頁送出時放進 <template data-slot-default="…">，static/slots.js 拿來用。
  顏色一律是 class（.cb-*、.sb-*，app.html 用 token 上色），所以換外觀時跟著換色。
"""

from __future__ import annotations

from typing import Dict

# 等回覆的小方塊（以前寫在 app.html 的 CUBY）
THINK = ('<svg class="cuby" viewBox="0 0 32 32" aria-hidden="true">'
         '<path class="cb-side" d="M16 3 28 9.5v13L16 29 4 22.5v-13z"/>'
         '<path class="cb-top" d="M16 3 28 9.5 16 16 4 9.5z"/><path class="cb-right" d="M16 16 28 9.5v13L16 29z"/>'
         '<circle class="cb-eye" cx="12" cy="20" r="1.6"/><circle class="cb-eye" cx="20" cy="20" r="1.6"/></svg>')

# S 寶寶（開場那一隻）笑起來
HAPPY = ('<svg class="sbaby" viewBox="0 0 40 40" aria-hidden="true">'
         '<rect class="sb-face" x="2" y="2" width="36" height="36" rx="11"/>'
         '<path class="sb-line" d="M11 17q2.5-3.5 5 0M24 17q2.5-3.5 5 0"/>'
         '<ellipse class="sb-blush" cx="9.5" cy="23" rx="3" ry="1.7"/><ellipse class="sb-blush" cx="30.5" cy="23" rx="3" ry="1.7"/>'
         '<path class="sb-ink" d="M14 23.5h12q-1 6-6 6t-6-6z"/></svg>')

# S 寶寶有點擔心
WARN = ('<svg class="sbaby" viewBox="0 0 40 40" aria-hidden="true">'
        '<rect class="sb-face" x="2" y="2" width="36" height="36" rx="11"/>'
        '<path class="sb-line" d="M10.5 13.5l5 1.8M29.5 13.5l-5 1.8"/>'
        '<ellipse class="sb-ink" cx="14" cy="19.5" rx="2" ry="2.4"/><ellipse class="sb-ink" cx="26" cy="19.5" rx="2" ry="2.4"/>'
        '<path class="sb-line" d="M14.5 28.5q2.75-2.5 5.5 0t5.5 0"/>'
        '<path class="sb-drop" d="M33 7q2.6 3.4 0 5.2-2.6-1.8 0-5.2z"/></svg>')

MARKUP: Dict[str, str] = {"mascot.think": THINK, "mascot.happy": HAPPY, "mascot.warn": WARN}
