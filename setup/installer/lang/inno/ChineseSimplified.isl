; *** Inno Setup 6 built-in messages, Simplified Chinese ***
;
; SYNOX's own translation, written for the SYNOX installer (not a copy of any third-party translation file).
; Same keys as Default.isl of Inno Setup 6.7.4; scripts/installer_ci.py check-iss keeps them complete.
; Inno Setup adds a period to some messages by itself: do not add one where English has none.
; Loaded first for zh-CN; lang\en.isl and lang\zh-CN.isl (SYNOX's own texts) come after it.

[LangOptions]
LanguageName=简体中文 (Simplified Chinese)
LanguageID=$0804
LanguageCodePage=936

[Messages]

; *** Application titles
SetupAppTitle=安装程序
SetupWindowTitle=安装程序 - %1
UninstallAppTitle=卸载
UninstallAppFullTitle=卸载 %1

; *** Misc. common
InformationTitle=信息
ConfirmTitle=确认
ErrorTitle=错误

; *** SetupLdr messages
SetupLdrStartupMessage=即将安装 %1。要继续吗？
LdrCannotCreateTemp=无法创建临时文件，安装程序已停止
LdrCannotExecTemp=无法运行临时文件夹中的文件，安装程序已停止
HelpTextNote=

; *** Startup error messages
LastErrorMessage=%1。%n%n错误 %2：%3
SetupFileMissing=安装文件夹中缺少文件 %1。请解决这个问题，或重新获取一份程序。
SetupFileCorrupt=安装文件已损坏。请重新获取一份程序。
SetupFileCorruptOrWrongVer=安装文件已损坏，或与这个版本的安装程序不兼容。请解决这个问题，或重新获取一份程序。
InvalidParameter=命令行中有无效的参数：%n%n%1
SetupAlreadyRunning=安装程序已经在运行。
WindowsVersionNotSupported=这个程序不支持你电脑上的 Windows 版本。
WindowsServicePackRequired=这个程序需要 %1 Service Pack %2 或更高版本。
NotOnThisPlatform=这个程序无法在 %1 上运行。
OnlyOnThisPlatform=这个程序只能在 %1 上运行。
OnlyOnTheseArchitectures=这个程序只能安装在为以下处理器架构设计的 Windows 上：%n%n%1
WinVersionTooLowError=这个程序需要 %1 %2 或更高版本。
WinVersionTooHighError=这个程序无法安装在 %1 %2 或更高版本上。
AdminPrivilegesRequired=安装这个程序需要以管理员身份登录。
PowerUserPrivilegesRequired=安装这个程序需要以管理员或 Power Users 组成员的身份登录。
SetupAppRunningError=安装程序检测到 %1 正在运行。%n%n请先将它全部关闭，然后单击“确定”继续；或单击“取消”退出。
UninstallAppRunningError=卸载程序检测到 %1 正在运行。%n%n请先将它全部关闭，然后单击“确定”继续；或单击“取消”退出。

; *** Startup questions
PrivilegesRequiredOverrideTitle=选择安装方式
PrivilegesRequiredOverrideInstruction=选择安装方式
PrivilegesRequiredOverrideText1=%1 可以为所有用户安装（需要管理员权限），也可以只为你安装。
PrivilegesRequiredOverrideText2=%1 可以只为你安装，也可以为所有用户安装（需要管理员权限）。
PrivilegesRequiredOverrideAllUsers=为所有用户安装(&A)
PrivilegesRequiredOverrideAllUsersRecommended=为所有用户安装（推荐）(&A)
PrivilegesRequiredOverrideCurrentUser=只为我安装(&M)
PrivilegesRequiredOverrideCurrentUserRecommended=只为我安装（推荐）(&M)

; *** Misc. errors
ErrorCreatingDir=安装程序无法创建文件夹“%1”
ErrorTooManyFilesInDir=文件夹“%1”中的文件太多，无法再创建文件

; *** Setup common messages
ExitSetupTitle=退出安装程序
ExitSetupMessage=安装尚未完成。如果现在退出，程序将不会被安装。%n%n你可以以后再运行安装程序来完成安装。%n%n要退出安装程序吗？
AboutSetupMenuItem=关于安装程序(&A)...
AboutSetupTitle=关于安装程序
AboutSetupMessage=%1 版本 %2%n%3%n%n%1 主页：%n%4
AboutSetupNote=
TranslatorNote=

; *** Buttons
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonOK=确定
ButtonCancel=取消
ButtonYes=是(&Y)
ButtonYesToAll=全部是(&A)
ButtonNo=否(&N)
ButtonNoToAll=全部否(&O)
ButtonFinish=完成(&F)
ButtonBrowse=浏览(&B)...
ButtonWizardBrowse=浏览(&R)...
ButtonNewFolder=新建文件夹(&M)

; *** "Select Language" dialog messages
SelectLanguageTitle=选择安装语言
SelectLanguageLabel=请选择安装时使用的语言。

; *** Common wizard text
ClickNext=单击“下一步”继续，或单击“取消”退出安装程序。
BeveledLabel=
BrowseDialogTitle=浏览文件夹
BrowseDialogLabel=请在下面的列表中选择一个文件夹，然后单击“确定”。
NewFolderName=新建文件夹

; *** "Welcome" wizard page
WelcomeLabel1=欢迎使用 [name] 安装向导
WelcomeLabel2=这将在你的电脑上安装 [name/ver]。%n%n建议先关闭其他所有应用程序再继续。

; *** "Password" wizard page
WizardPassword=密码
PasswordLabel1=这个安装需要密码。
PasswordLabel3=请输入密码，然后单击“下一步”继续。密码区分大小写。
PasswordEditLabel=密码(&P)：
IncorrectPassword=密码不正确，请再试一次。

; *** "License Agreement" wizard page
WizardLicense=许可协议
LicenseLabel=继续之前，请先阅读下面的重要信息。
LicenseLabel3=请阅读下面的许可协议。你必须接受协议条款才能继续安装。
LicenseAccepted=我接受协议(&A)
LicenseNotAccepted=我不接受协议(&D)

; *** "Information" wizard pages
WizardInfoBefore=信息
InfoBeforeLabel=继续之前，请先阅读下面的重要信息。
InfoBeforeClickLabel=准备好继续安装时，请单击“下一步”。
WizardInfoAfter=信息
InfoAfterLabel=继续之前，请先阅读下面的重要信息。
InfoAfterClickLabel=准备好继续安装时，请单击“下一步”。

; *** "User Information" wizard page
WizardUserInfo=用户信息
UserInfoDesc=请输入你的信息。
UserInfoName=用户名(&U)：
UserInfoOrg=组织(&O)：
UserInfoSerial=序列号(&S)：
UserInfoNameRequired=请输入名称。

; *** "Select Destination Location" wizard page
WizardSelectDir=选择安装位置
SelectDirDesc=要把 [name] 安装到哪里？
SelectDirLabel3=安装程序将把 [name] 安装到下面的文件夹。
SelectDirBrowseLabel=单击“下一步”继续。如果想选择其他文件夹，请单击“浏览”。
DiskSpaceGBLabel=至少需要 [gb] GB 的可用磁盘空间。
DiskSpaceMBLabel=至少需要 [mb] MB 的可用磁盘空间。
CannotInstallToNetworkDrive=安装程序无法安装到网络驱动器。
CannotInstallToUNCPath=安装程序无法安装到 UNC 路径。
InvalidPath=请输入带驱动器号的完整路径，例如：%n%nC:\APP%n%n或以下格式的 UNC 路径：%n%n\\server\share
InvalidDrive=你选择的驱动器或 UNC 共享不存在或无法访问，请选择其他位置。
DiskSpaceWarningTitle=磁盘空间不足
DiskSpaceWarning=安装程序至少需要 %1 KB 的可用空间，但你选择的驱动器只有 %2 KB 可用。%n%n仍然要继续吗？
DirNameTooLong=文件夹名称或路径太长。
InvalidDirName=文件夹名称无效。
BadDirName32=文件夹名称不能包含以下字符：%n%n%1
DirExistsTitle=文件夹已存在
DirExists=文件夹：%n%n%1%n%n已经存在。仍然要安装到这个文件夹吗？
DirDoesntExistTitle=文件夹不存在
DirDoesntExist=文件夹：%n%n%1%n%n不存在。要创建这个文件夹吗？

; *** "Select Components" wizard page
WizardSelectComponents=选择组件
SelectComponentsDesc=要安装哪些组件？
SelectComponentsLabel2=勾选要安装的组件，取消勾选不想安装的组件。准备好后单击“下一步”继续。
FullInstallation=完整安装
CompactInstallation=简洁安装
CustomInstallation=自定义安装
NoUninstallWarningTitle=组件已存在
NoUninstallWarning=安装程序检测到你的电脑上已经安装了以下组件：%n%n%1%n%n取消勾选这些组件并不会卸载它们。%n%n仍然要继续吗？
ComponentSize1=%1 KB
ComponentSize2=%1 MB
ComponentsDiskSpaceGBLabel=当前选择至少需要 [gb] GB 的磁盘空间。
ComponentsDiskSpaceMBLabel=当前选择至少需要 [mb] MB 的磁盘空间。

; *** "Select Additional Tasks" wizard page
WizardSelectTasks=选择附加任务
SelectTasksDesc=还要执行哪些附加任务？
SelectTasksLabel2=勾选安装 [name] 时要一并执行的附加任务，然后单击“下一步”。

; *** "Select Start Menu Folder" wizard page
WizardSelectProgramGroup=选择“开始”菜单文件夹
SelectStartMenuFolderDesc=要把程序的快捷方式放在哪里？
SelectStartMenuFolderLabel3=安装程序将在下面的“开始”菜单文件夹中创建程序的快捷方式。
SelectStartMenuFolderBrowseLabel=单击“下一步”继续。如果想选择其他文件夹，请单击“浏览”。
MustEnterGroupName=请输入文件夹名称。
GroupNameTooLong=文件夹名称或路径太长。
InvalidGroupName=文件夹名称无效。
BadGroupName=文件夹名称不能包含以下字符：%n%n%1
NoProgramGroupCheck2=不创建“开始”菜单文件夹(&D)

; *** "Ready to Install" wizard page
WizardReady=准备安装
ReadyLabel1=安装程序已准备好在你的电脑上安装 [name]。
ReadyLabel2a=单击“安装”开始安装；如果想检查或更改设置，请单击“上一步”。
ReadyLabel2b=单击“安装”开始安装。
ReadyMemoUserInfo=用户信息：
ReadyMemoDir=安装位置：
ReadyMemoType=安装类型：
ReadyMemoComponents=已选组件：
ReadyMemoGroup=“开始”菜单文件夹：
ReadyMemoTasks=附加任务：

; *** TDownloadWizardPage wizard page and DownloadTemporaryFile
DownloadingLabel2=正在下载文件...
ButtonStopDownload=停止下载(&S)
StopDownload=确定要停止下载吗？
ErrorDownloadAborted=下载已停止
ErrorDownloadFailed=下载失败：%1 %2
ErrorDownloadSizeFailed=无法获取文件大小：%1 %2
ErrorProgress=进度无效：%1 / %2
ErrorFileSize=文件大小无效：应为 %1，实际为 %2

; *** TExtractionWizardPage wizard page and ExtractArchive
ExtractingLabel=正在解压文件...
ButtonStopExtraction=停止解压(&S)
StopExtraction=确定要停止解压吗？
ErrorExtractionAborted=解压已停止
ErrorExtractionFailed=解压失败：%1

; *** Archive extraction failure details
ArchiveIncorrectPassword=密码不正确
ArchiveIsCorrupted=压缩包已损坏
ArchiveUnsupportedFormat=不支持这种压缩包格式

; *** "Preparing to Install" wizard page
WizardPreparing=准备安装
PreparingDesc=安装程序正在准备在你的电脑上安装 [name]。
PreviousInstallNotCompleted=之前某个程序的安装或卸载尚未完成，需要重启电脑才能完成。%n%n重启电脑后，请再次运行安装程序来完成 [name] 的安装。
CannotContinue=安装程序无法继续，请单击“取消”退出。
ApplicationsFound=以下应用程序正在使用安装程序需要更新的文件。建议让安装程序自动关闭这些应用程序。
ApplicationsFound2=以下应用程序正在使用安装程序需要更新的文件。建议让安装程序自动关闭这些应用程序。安装完成后，安装程序会尝试重新启动它们。
CloseApplications=自动关闭这些应用程序(&A)
DontCloseApplications=不关闭这些应用程序(&D)
ErrorCloseApplications=安装程序无法自动关闭所有应用程序。建议先关闭所有正在使用需更新文件的应用程序，再继续。
PrepareToInstallNeedsRestart=安装程序需要重启你的电脑。重启后，请再次运行安装程序来完成 [name] 的安装。%n%n要现在重启吗？

; *** "Installing" wizard page
WizardInstalling=正在安装
InstallingLabel=安装程序正在你的电脑上安装 [name]，请稍候。

; *** "Setup Completed" wizard page
FinishedHeadingLabel=[name] 安装向导即将完成
FinishedLabelNoIcons=安装程序已在你的电脑上安装好 [name]。
FinishedLabel=安装程序已在你的电脑上安装好 [name]。你可以通过已创建的快捷方式打开它。
ClickFinish=单击“完成”退出安装程序。
FinishedRestartLabel=要完成 [name] 的安装，安装程序必须重启你的电脑。要现在重启吗？
FinishedRestartMessage=要完成 [name] 的安装，安装程序必须重启你的电脑。%n%n要现在重启吗？
ShowReadmeCheck=是，我想查看 README 文件
YesRadio=是，现在重启电脑(&Y)
NoRadio=否，我稍后再重启电脑(&N)
RunEntryExec=运行 %1
RunEntryShellExec=查看 %1

; *** "Setup Needs the Next Disk" stuff
ChangeDiskTitle=安装程序需要下一张磁盘
SelectDiskLabel2=请插入第 %1 张磁盘，然后单击“确定”。%n%n如果这张磁盘上的文件位于下面以外的文件夹，请输入正确的路径或单击“浏览”。
PathLabel=路径(&P)：
FileNotInDir2=在“%2”中找不到文件“%1”。请插入正确的磁盘，或选择其他文件夹。
SelectDirectoryLabel=请指定下一张磁盘的位置。

; *** Installation phase messages
SetupAborted=安装未完成。%n%n请解决问题后再次运行安装程序。
AbortRetryIgnoreSelectAction=选择操作
AbortRetryIgnoreRetry=重试(&T)
AbortRetryIgnoreIgnore=忽略错误并继续(&I)
AbortRetryIgnoreCancel=取消安装
RetryCancelSelectAction=选择操作
RetryCancelRetry=重试(&T)
RetryCancelCancel=取消

; *** Installation status messages
StatusClosingApplications=正在关闭应用程序...
StatusCreateDirs=正在创建文件夹...
StatusExtractFiles=正在解压文件...
StatusDownloadFiles=正在下载文件...
StatusCreateIcons=正在创建快捷方式...
StatusCreateIniEntries=正在创建 INI 条目...
StatusCreateRegistryEntries=正在创建注册表项...
StatusRegisterFiles=正在注册文件...
StatusSavingUninstall=正在保存卸载信息...
StatusRunProgram=正在完成安装...
StatusRestartingApplications=正在重新启动应用程序...
StatusRollback=正在撤销更改...

; *** Misc. errors
ErrorInternal2=内部错误：%1
ErrorFunctionFailedNoCode=%1 失败
ErrorFunctionFailed=%1 失败，代码 %2
ErrorFunctionFailedWithMessage=%1 失败，代码 %2。%n%3
ErrorExecutingProgram=无法运行文件：%n%1

; *** Registry errors
ErrorRegOpenKey=打开注册表项时出错：%n%1\%2
ErrorRegCreateKey=创建注册表项时出错：%n%1\%2
ErrorRegWriteKey=写入注册表项时出错：%n%1\%2

; *** INI errors
ErrorIniEntry=在文件“%1”中创建 INI 条目时出错。

; *** File copying errors
FileAbortRetryIgnoreSkipNotRecommended=跳过这个文件（不推荐）(&S)
FileAbortRetryIgnoreIgnoreNotRecommended=忽略错误并继续（不推荐）(&I)
SourceIsCorrupted=源文件已损坏
SourceDoesntExist=源文件“%1”不存在
SourceVerificationFailed=源文件校验失败：%1
VerificationSignatureDoesntExist=签名文件“%1”不存在
VerificationSignatureInvalid=签名文件“%1”无效
VerificationKeyNotFound=签名文件“%1”使用了未知的密钥
VerificationFileNameIncorrect=文件名不正确
VerificationFileTagIncorrect=文件标记不正确
VerificationFileSizeIncorrect=文件大小不正确
VerificationFileHashIncorrect=文件哈希值不正确
ExistingFileReadOnly2=现有文件被设为只读，无法替换。
ExistingFileReadOnlyRetry=移除只读属性后重试(&R)
ExistingFileReadOnlyKeepExisting=保留现有文件(&K)
ErrorReadingExistingDest=读取现有文件时出错：
FileExistsSelectAction=选择操作
FileExists2=文件已经存在。
FileExistsOverwriteExisting=覆盖现有文件(&O)
FileExistsKeepExisting=保留现有文件(&K)
FileExistsOverwriteOrKeepAll=之后遇到同样的情况都这样处理(&D)
ExistingFileNewerSelectAction=选择操作
ExistingFileNewer2=现有文件比安装程序要安装的文件更新。
ExistingFileNewerOverwriteExisting=覆盖现有文件(&O)
ExistingFileNewerKeepExisting=保留现有文件（推荐）(&K)
ExistingFileNewerOverwriteOrKeepAll=之后遇到同样的情况都这样处理(&D)
ErrorChangingAttr=更改现有文件的属性时出错：
ErrorCreatingTemp=在安装文件夹中创建文件时出错：
ErrorReadingSource=读取源文件时出错：
ErrorCopying=复制文件时出错：
ErrorDownloading=下载文件时出错：
ErrorExtracting=解压文件时出错：
ErrorReplacingExistingFile=替换现有文件时出错：
ErrorRestartReplace=RestartReplace 失败：
ErrorRenamingTemp=在安装文件夹中重命名文件时出错：
ErrorRegisterServer=无法注册 DLL/OCX：%1
ErrorRegSvr32Failed=RegSvr32 失败，退出代码 %1
ErrorRegisterTypeLib=无法注册类型库：%1

; *** Uninstall display name markings
UninstallDisplayNameMark=%1 (%2)
UninstallDisplayNameMarks=%1 (%2, %3)
UninstallDisplayNameMark32Bit=32 位
UninstallDisplayNameMark64Bit=64 位
UninstallDisplayNameMarkAllUsers=所有用户
UninstallDisplayNameMarkCurrentUser=当前用户

; *** Post-installation errors
ErrorOpeningReadme=打开 README 文件时出错。
ErrorRestartingComputer=安装程序无法重启电脑，请手动重启。

; *** Uninstaller messages
UninstallNotFound=文件“%1”不存在，无法卸载。
UninstallOpenError=无法打开文件“%1”，无法卸载
UninstallUnsupportedVer=这个版本的卸载程序无法识别卸载日志文件“%1”的格式，无法卸载
UninstallUnknownEntry=卸载日志中有未知的条目（%1）
ConfirmUninstall=确定要完全删除 %1 及其所有组件吗？
UninstallOnlyOnWin64=这个程序只能在 64 位 Windows 上卸载。
OnlyAdminCanUninstall=这个程序只有拥有管理员权限的用户才能卸载。
UninstallStatusLabel=正在从你的电脑上删除 %1，请稍候。
UninstalledAll=已从你的电脑上删除 %1。
UninstalledMost=%1 卸载完成。%n%n有些项目无法删除，你可以手动删除它们。
UninstalledAndNeedsRestart=要完成 %1 的卸载，必须重启电脑。%n%n要现在重启吗？
UninstallDataCorrupted=文件“%1”已损坏，无法卸载

; *** Uninstallation phase messages
ConfirmDeleteSharedFileTitle=要删除共享文件吗？
ConfirmDeleteSharedFile2=系统显示以下共享文件已不再被任何程序使用。要让卸载程序删除这个共享文件吗？%n%n如果仍有程序在使用这个文件，删除后这些程序可能无法正常工作。如果不确定，请选择“否”，把文件留在系统中不会有任何影响。
SharedFileNameLabel=文件名：
SharedFileLocationLabel=位置：
WizardUninstalling=卸载状态
StatusUninstalling=正在卸载 %1...

; *** Shutdown block reasons
ShutdownBlockReasonInstallingApp=正在安装 %1。
ShutdownBlockReasonUninstallingApp=正在卸载 %1。

[CustomMessages]

NameAndVersion=%1 版本 %2
AdditionalIcons=其他快捷方式：
CreateDesktopIcon=创建桌面快捷方式(&D)
CreateQuickLaunchIcon=创建快速启动快捷方式(&Q)
ProgramOnTheWeb=%1 网站
UninstallProgram=卸载 %1
LaunchProgram=运行 %1
AssocFileExtension=将 %2 文件扩展名与 %1 关联(&A)
AssocingFileExtension=正在将 %2 文件扩展名与 %1 关联...
AutoStartProgramGroupDescription=启动：
AutoStartProgram=自动启动 %1
AddonHostProgramNotFound=在你选择的文件夹中找不到 %1。%n%n仍然要继续吗？
