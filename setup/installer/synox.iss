; synox.iss -- SYNOX per-user Windows installer (Inno Setup 6). Design: docs/adr/0003.
; Build on the release machine, never on a user's machine:
;   1. scripts\stage_installer.py --fetch-python --wheelhouse ... --tools ...
;      (runtime\python = the same pinned python-build-standalone CPython that Setup.bat downloads for the ZIP:
;      URL + SHA256 come from setup\bootstrap.ps1, so the .exe and the ZIP run an identical Python with tkinter)
;   2. ISCC.exe /DAppVersion=0.2.0 /DStageDir=<stage>\SYNOX setup\installer\synox.iss
; Per-user (no admin): installs to %LOCALAPPDATA%\Programs\SYNOX. After copying it runs Setup.bat, which builds
; .venv from the bundled Python ("python -m venv") and wheelhouse (offline) and opens the setup wizard.
; Uninstall removes shortcuts/startup/.synoxpack association (setup\uninstall.ps1 -Mode shortcuts) and the
; installed files + .venv; config.json, data\ (notes, vault, keys) and installed tools in packs\ are KEPT.
; ASCII only on purpose.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\..\dist\installer-stage\SYNOX"
#endif

[Setup]
AppId={{319CD614-2BF6-4552-8D5E-218B43046503}
AppName=SYNOX
AppVersion={#AppVersion}
AppVerName=SYNOX {#AppVersion}
AppPublisher=ChouYangEn and the SYNOX Team
DefaultDirName={localappdata}\Programs\SYNOX
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=SYNOX-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile={#StageDir}\LICENSE
SetupIconFile={#StageDir}\src\synox\assets\synox.ico
UninstallDisplayIcon={app}\src\synox\assets\synox.ico
; Code signing (owner decides, QuestionToUser.md QD1). With a certificate configured in the IDE / ISCC /S:
; SignTool=synoxsign $f
; SignedUninstaller=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[InstallDelete]
; An update replaces the Python wholesale: an older installer shipped python.org's embeddable package there, whose
; leftover python3XX._pth would put the new python.exe into isolated mode. .venv was built on the old interpreter,
; so it goes too; Setup.bat (run below) rebuilds it offline. config.json, data\ and packs\ are not touched.
Type: filesandordirs; Name: "{app}\runtime\python"
Type: filesandordirs; Name: "{app}\.venv"

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "STAGE-MANIFEST.txt"

[Run]
Filename: "{app}\Setup.bat"; Description: "Set up SYNOX now (installs packages offline, then opens the setup wizard)"; Flags: postinstall shellexec

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\uninstall.ps1"" -Mode shortcuts -Yes -Lang en"; Flags: runhidden waituntilterminated; RunOnceId: "SynoxShortcuts"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\runtime"
Type: files; Name: "{app}\lang.txt"
