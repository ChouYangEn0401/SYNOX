; SYNOX installer texts, Traditional Chinese (zh-TW). Model-written translation: NEEDS NATIVE-SPEAKER REVIEW.
; Loaded after lang\en.isl, so a missing key falls back to English. Keys must match en.isl (tests/test_installer_script.py).

[LangOptions]
LanguageName=繁體中文 (Traditional Chinese)
LanguageID=$0404

[Messages]
SelectLanguageTitle=語言 · Language
SelectLanguageLabel=請選擇語言。安裝程式、設定精靈和 SYNOX 都會用它。
WelcomeLabel1=歡迎使用 SYNOX，用得開心。
WelcomeLabel2=•  住在你自己電腦上的小助手，用 Telegram、Discord 或網頁跟它說話。%n•  自帶專用的 Python，不動這台電腦原本的程式。%n•  不用系統管理員密碼，全部放在你自己的一個資料夾。%n•  先做一次簡短的教學，再挑你需要的工具。
WizardSelectTasks=要幫你準備哪些東西？
SelectTasksDesc=都已經照建議勾好了。
SelectTasksLabel2=每一項之後都能改：再執行一次安裝程式，或到 SYNOX 的設定。
FinishedHeadingLabel=SYNOX 裝好了
FinishedLabel=還差最後一步：打開設定精靈，接上你的 Telegram（或 Discord）、選要用的 AI，大約 3 分鐘。接著做一次教學。
ClickFinish=按「完成」關閉安裝程式。
ConfirmUninstall=確定要現在移除 %1 嗎？
UninstalledAll=%1 已經移除了。
UninstalledMost=%1 已經移除了。%n%n你的設定和資料還留在 SYNOX 資料夾裡，之後重裝就接著用。
FinishedLabelNoIcons=還差最後一步：打開設定精靈，接上你的 Telegram（或 Discord）、選要用的 AI，大約 3 分鐘。接著做一次教學。

[CustomMessages]
DirNotWritable=SYNOX 要在這個資料夾裡存你的資料，這裡不能寫入。請選別的位置。
FinishedClaudeSkipped=Claude Code 先跳過了（可能沒連上網路）。之後在設定精靈的 AI 那一頁按「一鍵安裝（PowerShell）」就能補。
IconOpen=開啟 SYNOX
IconUninstall=解除安裝 SYNOX
IconWizard=SYNOX 設定精靈
LicenseFile=LICENSING.md
LicenseLine=個人使用免費。要拿去做商業用途，請看 <a id="license">AGPL-3.0 授權條款</a>。
RunSetupNow=現在打開設定精靈（建議）
StatusClaude=正在安裝 Claude Code（需要上網，可能要幾分鐘）…
SynoxLangCode=zh-TW
TaskAllTools=全部官方工具都裝（不建議：建議做完教學後再挑自己需要的）
TaskAutostart=開機後自動啟動 SYNOX（看得到的小視窗，隨時可以關）
TaskClaude=安裝 Claude Code（這台還沒有才裝；需要上網，裝在你的使用者資料夾）
TaskClaudePresent=Claude Code 已經裝好了
TaskDesktop=在桌面放一個「SYNOX」捷徑
TaskFileType=讓 .synoxpack 檔案點兩下就安裝（裝之前一樣會先檢查、給你按確認）
TaskStartMenu=在開始功能表放「SYNOX」
TypeCustom=自訂（自己決定資料夾和每一項）
TypeDesc=大多數人選「建議」就好。
TypeLabel=「建議」會幫你：用 SYNOX 自己的 Python、在桌面和開始功能表放捷徑、讓 .synoxpack 檔點兩下就安裝、開機後自動啟動，並備好教學。這台還沒有 Claude Code 的話也一起裝（需要上網，裝在你的使用者資料夾）。之後想改，再執行一次安裝程式就好，資料不會不見。
TypeRecommended=建議（全部幫我弄好）
TypeTitle=要怎麼裝？
UninstallConfirmData=真的要連你的資料一起刪除嗎？%n%n你的設定、筆記、記帳、存好的金鑰和裝過的工具都會刪掉，刪了救不回來。
UninstallDeleteData=連我的資料也一起刪除
UninstallDeleteDataNote=刪了救不回來。勾了之後會再問你一次。
UninstallHeading=要移除 SYNOX 嗎？
UninstallKeeps=會留著：你的設定、筆記、記帳、存好的金鑰和裝過的工具。它們還在 SYNOX 資料夾裡，之後重裝就接著用。
UninstallRemoves=會移除：SYNOX 的程式、它自己的 Python、捷徑、開機自動啟動、.synoxpack 的點兩下安裝。
UninstallTitle=解除安裝 SYNOX
UninstallUntouched=這台電腦原本的 Python、Conda 和 Claude Code 都不會動。
