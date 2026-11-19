# 如何貢獻

歡迎提 issue 與 pull request。送出前請先讀下面兩段：授權與貢獻者同意書。

## 授權

你的貢獻會以專案目前的授權釋出：核心是 AGPL-3.0-or-later，SDK 與範例是 Apache-2.0（範圍見 [LICENSING.md](LICENSING.md)）。你改的是哪個目錄，就適用哪個授權。

## 貢獻者同意書（CLA，簡版）

為了讓專案能同時提供開源授權與商業授權，也能在未來調整授權，每位貢獻者需要同意以下幾點。**在 pull request 描述寫下這句話即視為同意**：

> I have read CONTRIBUTING.md and agree to the Contributor Agreement.

內容：

1. 你保有你貢獻內容的著作權。
2. 你授予專案維護者（含創始維護者，見 [.github/GOVERNANCE.md](.github/GOVERNANCE.md)）一個永久、全球、免費、不可撤銷的授權，可以使用、修改、散布你的貢獻，並可以**以任何授權（包含商業授權與閉源授權）再授權**。
3. 你聲明這份貢獻是你自己寫的，或你有權提交；沒有夾帶別人不允許公開的程式碼、密鑰或個人資料。
4. 你的貢獻是「照現狀」提供，沒有任何擔保。

> 這份同意書是簡版草稿，不是經過律師審閱的法律文件。正式開放外部貢獻之前，請維護者找懂開源授權的人檢查。

## 從哪裡開始

- 全貌與目錄地圖：[docs/HANDOFF.md](docs/HANDOFF.md)；建環境、跑測試、不用金鑰的開發設定、開發工具（pack）、改核心的規則：[docs/development.md](docs/development.md)（兩份都只在 git clone／GitHub 上有，發佈 ZIP 與安裝程式不帶）。
- 從最新的 `dev` 開分支（`feat/…`、`fix/…`、`docs/…`），pull request 開到 `dev`。`main` 只放正式版。
- 新的工具（pack）請送到工具庫 SYNOX_Libs，不送到這個 repo；SYNOX 本體出廠不帶工具。
- 改權限、核准卡、驗證碼、pack 安裝、對外合約（pack.json、SDK）或資料格式之前，先寫一份 ADR（[docs/adr/README.md](docs/adr/README.md)）。

## 送出前請確認

- 跑過全部測試：`python -m pytest -q`（在不同平台已知會略過或失敗的，見 [docs/development.md](docs/development.md)「跑測試」；PR 裡寫出基準線之外有沒有新的失敗）。
- 新功能要有測試，測試不能連真的網路或開埠。
- 不要提交密鑰、token、個人資料或本機路徑（`python scripts/prepublish_check.py --worktree-only` 會找）。
- 使用者看得到的改變寫進 `CHANGELOG.md` 最上面的「未發佈」一節；版本號、tag、發佈由維護者決定。
- 安全相關的修改（權限、沙盒、保管箱、pack 掃描）請在 pull request 說明你考慮過的攻擊情境。
- 回報安全問題請不要開公開 issue，見 [SECURITY.md](SECURITY.md)。

## 參與討論 / Discussions

想法、問題、實測結果，歡迎到 [GitHub Discussions](https://github.com/ChouYangEn0401/SYNOX/discussions)（中文或英文都可以）。
正在徵求意見的：從其他生態（OpenClaw、Hermes Agent 等 Agent Skills 格式）匯入技能、以及沙盒——
見 [docs/sandbox-roadmap.md](docs/sandbox-roadmap.md)（現況、Windows 的候選路線、探測腳本、徵求協助的任務）。
Ideas, questions and test results are welcome in GitHub Discussions (Chinese or English). **安全漏洞不要貼在討論區**，見 [SECURITY.md](SECURITY.md).

## 聯絡

商業授權、貢獻者同意書：`mi.anthony.chou@gmail.com`。安全通報：見 [SECURITY.md](SECURITY.md)。維護者名單見 [.github/MAINTAINERS.md](.github/MAINTAINERS.md)。
