; SYNOX installer texts, English: the base for every language (loaded before the language's own file, so a
; key missing there falls back to this text). No [LangOptions] here: this file is part of every language.

[Messages]
SelectLanguageTitle=Language
SelectLanguageLabel=Choose a language. Setup, the setup wizard and SYNOX will all use it.
WelcomeLabel1=Welcome to SYNOX. Enjoy!
WelcomeLabel2=•  A small assistant that lives on your own computer. Talk to it from Telegram, Discord or a web page.%n•  Brings its own Python and leaves the rest of this computer alone.%n•  No administrator password: everything goes into one folder in your user account.%n•  Start with a short tutorial, then pick the tools you want.
WizardSelectTasks=What should Setup prepare?
SelectTasksDesc=Everything is already set to the recommended choice.
SelectTasksLabel2=You can change any of these later: run Setup again, or use SYNOX's settings.
FinishedHeadingLabel=SYNOX is installed
FinishedLabel=One last step: open the setup wizard to connect Telegram (or Discord) and choose an AI. It takes about 3 minutes. Then do the short tutorial.
ClickFinish=Click Finish to close Setup.
ConfirmUninstall=Remove %1 now?
UninstalledAll=%1 has been removed.
UninstalledMost=%1 has been removed.%n%nYour settings and data are still in the SYNOX folder, so a new install picks up where you left off.
FinishedLabelNoIcons=One last step: open the setup wizard to connect Telegram (or Discord) and choose an AI. It takes about 3 minutes. Then do the short tutorial.

[CustomMessages]
DirNotWritable=SYNOX keeps your data in this folder, but it can't write here. Please choose another location.
FinishedClaudeSkipped=Claude Code was skipped for now (maybe no internet). You can add it later on the AI page of the setup wizard: “One-click install (PowerShell)”.
IconOpen=Open SYNOX
IconUninstall=Uninstall SYNOX
IconWizard=SYNOX setup wizard
LicenseFile=LICENSE
LicenseLine=Free for personal use. For commercial use, please read the <a id="license">AGPL-3.0 license</a>.
RunSetupNow=Open the setup wizard now (recommended)
StatusClaude=Installing Claude Code (needs internet, may take a few minutes)…
SynoxLangCode=en
TaskAllTools=Install all official tools (not recommended: do the tutorial first, then pick what you need)
TaskAutostart=Start SYNOX when I sign in (a small visible window you can close any time)
TaskClaude=Install Claude Code (only if it is missing; needs internet; goes into your user folder)
TaskClaudePresent=Claude Code is already installed
TaskDesktop=Put a "SYNOX" shortcut on the desktop
TaskFileType=Double-click .synoxpack files to install them (still checked and confirmed first)
TaskStartMenu=Add "SYNOX" to the Start menu
TypeCustom=Custom (choose the folder and each item)
TypeDesc=Most people just keep the recommended choice.
TypeLabel=Recommended sets up SYNOX with its own Python, a desktop and Start menu shortcut, double-click install for .synoxpack files, start at sign-in and the tutorial. If this computer has no Claude Code yet, it is installed too (needs internet; goes into your user folder). Want something else later? Run Setup again; your data stays.
TypeRecommended=Recommended (set it all up for me)
TypeTitle=How should SYNOX be installed?
UninstallConfirmData=Really delete your data too?%n%nYour settings, notes, expense records, saved keys and installed tools will be deleted. This can't be undone.
UninstallDeleteData=Also delete my data
UninstallDeleteDataNote=This can't be undone. You'll be asked once more.
UninstallHeading=Remove SYNOX?
UninstallKeeps=Kept: your settings, notes, expense records, saved keys and installed tools. They stay in the SYNOX folder, so a new install picks up where you left off.
UninstallRemoves=Removed: the SYNOX program, its own Python, the shortcuts, start at sign-in and double-click install for .synoxpack files.
UninstallTitle=Uninstall SYNOX
UninstallUntouched=Other Python installs, Conda and Claude Code on this computer are not touched.
