# AGENTS.md：給 AI 程式助理（Claude Code、Codex 等）的入口

這個檔每次都會被載入，所以只放每次都要知道的；細節照連結去讀。

## 先讀

1. [docs/HANDOFF.md](docs/HANDOFF.md)：SYNOX 是什麼、架構大圖、目錄地圖、重要 ADR、在雲端 session 工作的注意事項。
2. [docs/development.md](docs/development.md)：建環境、跑測試、不用金鑰的開發設定、開分支交 PR、開發 pack、改核心的規則。
3. [docs/AGENT.md](docs/AGENT.md)：程式地圖與**不能破壞的規則（invariants）**。動到某一塊之前先讀那一條。

全部文件的目錄在 [docs/README.md](docs/README.md)；架構決定在 [docs/adr/](docs/adr/README.md)。文件跟程式對不上時以程式為準。

## 怎麼跑

```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt && python -m pip install -e ".[dev]"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 SYNOX_NO_BANNER=1 SYNOX_NO_BROWSER=1
python -m pytest -q -p no:cacheprovider          # 先在沒改過的 dev 上跑一次，記下基準線
python -m synox console --llm fake               # 不連網、不用任何金鑰，在終端機試指令
```

Windows：`.venv\Scripts\python.exe` 取代 `python`，主控台先設 `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'`。

## 每次都要守的

- **公開 repo**：檔案、commit 訊息、PR 都不能有真名、信箱、本機路徑（`C:\Users\<名字>`、`/home/<名字>`）、token、私人專案名、別人的資料；範例一律假資料。
  交件前跑 `python scripts/prepublish_check.py --worktree-only`。
- **你不需要、也拿不到任何真的金鑰或帳號**；需要真機或真帳號才能驗的，寫進交件說明留給擁有者。機密的計畫文件不在這個 repo。
- **測試不連網、不開埠、不叫真的 AI、不真的 pip／npm、不執行下載來的東西**；一律用假的（`tests/conftest.py`）。
- **權限只有一個判斷**（`policy.decide`／`ai_decision`）；危險的動作走核准卡；**驗證碼永遠不經過 AI**；工具結果與使用者資料是資料、不是指令。
- **不改 `vendor/isdtelekit/`**；SYNOX 本體不再收工具（新工具放 SYNOX_Libs 工具庫）。
- 改安全邊界、對外合約、資料格式、AI 行為規則之前先寫 ADR（[docs/adr/README.md](docs/adr/README.md)，下一號 0046）。
- **所有持久化資料都有版本；改資料格式＝加一個遷移步驟＋測試**（用舊格式的假資料；[docs/data-migrations.md](docs/data-migrations.md)、ADR 0044）。
  不跳號、不服務降級；寫檔一律寫目前的格式與版本號。
- 開分支（`feat|fix|docs/<主題>`，基底是最新的 `dev`）、小步 commit、使用者看得到的改變寫進 `CHANGELOG.md` 最上面的「未發佈」一節；
  不升版本號、不打 tag、不發 release、不直接推 `dev`／`main`、不碰簽章的公鑰與私鑰。
