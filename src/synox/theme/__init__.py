"""
外觀（換裝）：SYNOX 定「大方針」（顏色 token、吉祥物與動畫的 slot），外觀包與「自己貼」只把它們換掉。
說明：docs/themes.md。

    contract.py    token 與 slot 的名字（相容規則同教學的位置清單）、原本的 SYNOX 的值（整個 SYNOX 的顏色只在這裡，ADR 0042）
    sanitize.py    SVG／HTML／CSS 的消毒（白名單重建；危險的整份拒絕）
    tokens.py      token 的值怎麼檢查、怎麼組成 CSS
    pack.py        外觀包（pack.json kind=theme）：第 1、2 關、組成要送網頁的 Bundle、安裝報告那一段
    check.py       套用檢查：每個 token／slot 是有給、沿用預設、還是被忽略（提示，不擋）
    defaults.py    原本的 SYNOX 在 slot 裡放的 SVG（等回覆的方塊、開心／擔心的 S 寶寶）
    appearance.py  「設定 → 外觀」：誰選了什麼、存在哪、送網頁時塞進 <head> 的東西、預覽頁

外觀只碰網頁；Telegram、Discord 是純文字，不受影響。
"""
