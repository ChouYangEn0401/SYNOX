; SYNOX installer texts, Simplified Chinese (zh-CN). Model-written translation: NEEDS NATIVE-SPEAKER REVIEW.
; Loaded after lang\en.isl, so a missing key falls back to English. Keys must match en.isl (tests/test_installer_script.py).

[LangOptions]
LanguageName=简体中文 (Simplified Chinese)
LanguageID=$0804

[Messages]
SelectLanguageTitle=语言 · Language
SelectLanguageLabel=请选择语言。安装程序、设置向导和 SYNOX 都会使用它。
WelcomeLabel1=欢迎使用 SYNOX，用得开心。
WelcomeLabel2=•  住在你自己电脑上的小助手，用 Telegram、Discord 或网页跟它说话。%n•  自带专用的 Python，不动这台电脑原有的程序。%n•  不需要管理员密码，全部放在你自己的一个文件夹里。%n•  先做一次简短的教程，再挑你需要的工具。
WizardSelectTasks=要帮你准备哪些东西？
SelectTasksDesc=都已经按推荐勾好了。
SelectTasksLabel2=每一项以后都能改：再运行一次安装程序，或到 SYNOX 的设置里改。
FinishedHeadingLabel=SYNOX 装好了
FinishedLabel=还差最后一步：打开设置向导，接上你的 Telegram（或 Discord）、选择要用的 AI，大约 3 分钟。接着做一次教程。
ClickFinish=点击“完成”关闭安装程序。
ConfirmUninstall=确定要现在移除 %1 吗？
UninstalledAll=%1 已经移除了。
UninstalledMost=%1 已经移除了。%n%n你的设置和数据还留在 SYNOX 文件夹里，以后重装就能接着用。
FinishedLabelNoIcons=还差最后一步：打开设置向导，接上你的 Telegram（或 Discord）、选择要用的 AI，大约 3 分钟。接着做一次教程。

[CustomMessages]
DirNotWritable=SYNOX 要在这个文件夹里保存你的数据，但这里无法写入。请选择别的位置。
FinishedClaudeSkipped=Claude Code 暂时跳过了（可能没有联网）。以后在设置向导的 AI 那一页点“一键安装（PowerShell）”就能补上。
IconOpen=打开 SYNOX
IconUninstall=卸载 SYNOX
IconWizard=SYNOX 设置向导
LicenseFile=LICENSING.md
LicenseLine=个人使用免费。要用于商业用途，请看 <a id="license">AGPL-3.0 许可条款</a>。
RunSetupNow=现在打开设置向导（推荐）
StatusClaude=正在安装 Claude Code（需要联网，可能要几分钟）…
SynoxLangCode=zh-CN
TaskAllTools=安装全部官方工具（不推荐：建议做完教程后再挑自己需要的）
TaskAutostart=登录后自动启动 SYNOX（可见的小窗口，随时可以关闭）
TaskClaude=安装 Claude Code（这台电脑还没有才装；需要联网，装在你的用户文件夹）
TaskClaudePresent=Claude Code 已经装好了
TaskDesktop=在桌面放一个“SYNOX”快捷方式
TaskFileType=双击 .synoxpack 文件即可安装（安装前同样会先检查并请你确认）
TaskStartMenu=在开始菜单放“SYNOX”
TypeCustom=自定义（自己决定文件夹和每一项）
TypeDesc=大多数人选“推荐”就好。
TypeLabel=“推荐”会帮你：使用 SYNOX 自己的 Python、在桌面和开始菜单放快捷方式、双击 .synoxpack 文件即可安装、登录后自动启动，并准备好教程。这台电脑还没有 Claude Code 的话也一起装（需要联网，装在你的用户文件夹）。以后想改，再运行一次安装程序就行，数据不会丢。
TypeRecommended=推荐（全部帮我弄好）
TypeTitle=要怎么装？
UninstallConfirmData=真的要连你的数据一起删除吗？%n%n你的设置、笔记、记账、保存的密钥和装过的工具都会被删除，无法恢复。
UninstallDeleteData=连我的数据也一起删除
UninstallDeleteDataNote=删除后无法恢复。勾选后会再问你一次。
UninstallHeading=要移除 SYNOX 吗？
UninstallKeeps=会保留：你的设置、笔记、记账、保存的密钥和装过的工具。它们还在 SYNOX 文件夹里，以后重装就能接着用。
UninstallRemoves=会移除：SYNOX 程序、它自己的 Python、快捷方式、登录后自动启动、双击安装 .synoxpack。
UninstallTitle=卸载 SYNOX
UninstallUntouched=这台电脑原有的 Python、Conda 和 Claude Code 都不会动。
