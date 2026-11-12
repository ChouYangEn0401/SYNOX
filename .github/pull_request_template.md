## 做了什麼、為什麼



## 貢獻者同意書（必填，見 CONTRIBUTING.md）

- [ ] I have read CONTRIBUTING.md and agree to the Contributor Agreement.

## 測試

- [ ] 跑過全部測試：`python -m pytest -q`，全過
- [ ] 新功能或修正有對應的測試
- [ ] 測試不連真的網路、不開埠、不執行下載來的程式

## 安全自檢

- [ ] 沒有提交密鑰、token、個人資料、本機絕對路徑（可以跑 `python scripts/prepublish_check.py --worktree-only`）
- [ ] 沒有提交 `config.json`、`.env`、`data/`、`*.enc`、`packs.lock`
- [ ] 動到權限、沙盒、保管箱、pack 掃描或安裝流程時，在上面寫了考慮過的攻擊情境
- [ ] 使用者看得到的行為有改時，更新了文件（README、docs/）與 CHANGELOG.md
