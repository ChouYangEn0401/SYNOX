# 圖文教學（docs/tutorials/）

給電腦新手看的一步一圖設定教學。每一份都是**自足的一頁 HTML**（雙擊就能離線打開）＋同名資料夾裡的 `README.md` 純文字版。

| 教學 | 本機檔 | 線上版（Artifact） |
|---|---|---|
| Discord：觀念（私訊／伺服器／各頻道）、開發者後台建 bot、邀請、複製 ID、貼進 SYNOX、疑難排解 | [discord/index.html](discord/index.html)（純文字 [discord/README.md](discord/README.md)；觀念 [../discord-concepts.md](../discord-concepts.md)） | <https://claude.ai/artifact/21KFtvB7EVKsV4bjCE5h1h> |
| Telegram：跟 @BotFather 拿 token、貼進 SYNOX、配對、第一則訊息、常見問題 | [telegram/index.html](telegram/index.html)（純文字 [telegram/README.md](telegram/README.md)） | <https://claude.ai/artifact/SjWBzQkdDpUNymrQEZRKHe> |

## 怎麼打開

- **安裝精靈**「Bot 的 token」那一頁的「看圖文教學」按鈕：用預設瀏覽器開本機那份（`docs/tutorials/<平台>/index.html`）。
- **網頁介面**：`http://127.0.0.1:8830/tutorials/<名字>/`（設定 → 聊天通道裡有連結）。不用登入：是公開的說明文件，不碰任何資料。
- **文字版 `synox init`**：Telegram 那一題會印出本機檔的路徑。
- 發佈的 zip 與安裝程式都會帶到（`scripts/make_zip.py` 取 git 追蹤的檔，`docs/` 整個在裡面）。

## 加一份新教學（例如 Discord）：不用改程式

1. 放 `docs/tutorials/<名字>/index.html`。名字只用小寫英數、`-`、`_`（跟 pack 名同一個規則：`synox/tutorials.py` 的 `NAME_RE`）。
   `<名字>` 跟精靈「用哪一個」的平台代號一樣（`telegram`、`discord`）時，精靈那一頁的「看圖文教學」按鈕會自動出現。
2. 旁邊放 `README.md` 純文字版（同樣的步驟＋「怎麼更新這份教學」）。
3. 規則：**自足**（沒有外部字型、圖片、程式；本機離線要能看）、**沒有 JavaScript**（網頁路由 `GET /tutorials/<名字>/` 的 CSP 是
   `default-src 'none'; style-src 'unsafe-inline'; img-src data:`，`<script>` 不會執行）、亮色與深色都要能看
   （`prefers-color-scheme` ＋ `[data-theme]`）、手機寬度不橫向捲動、畫面是示意圖就標「示意圖」、範例 token 要看得出是假的
   （`scripts/prepublish_check.py` 會抓像真的）。
4. 網頁設定頁要放連結的話，在 `src/synox/web/static/app.html` 對應的通道那一格加一行
   `<a href="/tutorials/<名字>/" target="_blank" rel="noopener noreferrer">看圖文教學</a>`。
5. 發佈成 Artifact 後，把網址加進上面的表格（一列一份，表格照字母排）。

程式：`src/synox/tutorials.py`（`path_of`／`names`／`read`／`open_local`）、`src/synox/web/server.py` 的 `tutorial()`、
`src/synox/wizard/pages.py` 的 `page_token`；測試 `tests/test_tutorials.py`。
