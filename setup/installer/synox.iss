; synox.iss -- SYNOX per-user Windows installer (Inno Setup 6). Design: docs/adr/0003, screens: docs/installer/spec.html.
; Build on the release machine, never on a user's machine:
;   1. scripts\stage_installer.py --fetch-python --wheelhouse ... --tools ...
;      (runtime\python = the same pinned python-build-standalone CPython that Setup.bat downloads for the ZIP:
;      URL + SHA256 come from setup\bootstrap.ps1, so the .exe and the ZIP run an identical Python with tkinter)
;   2. ISCC.exe /DAppVersion=0.2.0 /DStageDir=<stage>\SYNOX setup\installer\synox.iss
; Pages (owner's decisions 2026-11-13, spec section 8): Language -> Welcome -> Recommended | Custom -> Installing -> Done.
;   - Language: Inno's own language dialog, always shown, preselects the Windows display language (English when there
;     is no match). 12 languages, same order and codes as synox.wizard.i18n.LANGS. The choice is written to lang.txt and
;     handed to Setup.bat (-Lang), so the setup wizard and SYNOX use it too.
;   - No license page (Q4): the welcome page has one line linking to LICENSING.md / LICENSE (both still installed).
;   - Recommended = environment + tutorial, no tools; Custom adds the folder page and the task list (Q1, Q3).
;   - Claude Code (Q2): optional last step, only when missing, never blocks (setup\installer\claude-code.ps1).
;   - Uninstall (Q9): "also delete my data" is offered unchecked, with a second confirmation.
; Per-user (no admin): installs to %LOCALAPPDATA%\Programs\SYNOX. On the last page it runs Setup.bat, which builds
; .venv from the bundled Python ("python -m venv") and wheelhouse (offline) and opens the setup wizard (or the text
; synox init). Setup.bat sees installer-choices.json and does not ask Recommended/Custom again.
; Uninstall removes shortcuts/startup/.synoxpack association (setup\uninstall.ps1 -Mode shortcuts) and the
; installed files + .venv; config.json, data\ (notes, vault, keys) and installed tools in packs\ are KEPT
; unless the user ticks "also delete my data" (Q9).
; installer-choices.json (written after copying) tells the setup wizard what was already decided here.
; Texts live in lang\<code>.isl (UTF-8); this file stays ASCII on purpose. Static checks: scripts/installer_ci.py check-iss.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\..\dist\installer-stage\SYNOX"
#endif

; Inno Setup 6 ships official translations of its built-in texts (buttons, "Browse...") for es, fr, de, pt-BR, ru, ar,
; ja, ko. For Traditional Chinese, Simplified Chinese and Hindi, SYNOX has its own translations in lang\inno\ (same keys
; as Inno's Default.isl, kept complete by check-iss; docs/release-build.md "Installer languages").

[Setup]
AppId={{319CD614-2BF6-4552-8D5E-218B43046503}
AppName=SYNOX
AppVersion={#AppVersion}
AppVerName=SYNOX {#AppVersion}
AppPublisher=ChouYangEn and the SYNOX Team
DefaultDirName={localappdata}\Programs\SYNOX
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=SYNOX-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
; Minimal look: modern wizard without the stock side and corner pictures.
WizardStyle=modern
WizardImageFile=
WizardSmallImageFile=
SetupIconFile={#StageDir}\src\synox\assets\synox.ico
UninstallDisplayIcon={app}\src\synox\assets\synox.ico
UninstallDisplayName=SYNOX
; Language first: always show the language list, preselect the Windows display language.
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage
UsePreviousLanguage=yes
; Welcome page on; no license page (no LicenseFile), no program-group page, no "ready to install" page.
DisableWelcomePage=no
DisableProgramGroupPage=yes
DisableReadyPage=yes
; Custom always starts from the recommended values, never from an earlier custom run.
UsePreviousTasks=no
; Unsigned for the alpha (owner, Q6). With a certificate configured in the IDE / ISCC /S:
; SignTool=synoxsign $f
; SignedUninstaller=yes

[Languages]
; English first: it is used when the Windows display language matches none of the twelve.
; lang\en.isl comes before each language's own file, so any SYNOX text a translation lacks falls back to English.
Name: "en"; MessagesFile: "compiler:Default.isl,lang\en.isl"
Name: "zhTW"; MessagesFile: "lang\inno\ChineseTraditional.isl,lang\en.isl,lang\zh-TW.isl"
Name: "zhCN"; MessagesFile: "lang\inno\ChineseSimplified.isl,lang\en.isl,lang\zh-CN.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl,lang\en.isl,lang\es.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl,lang\en.isl,lang\fr.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl,lang\en.isl,lang\de.isl"
Name: "ptBR"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl,lang\en.isl,lang\pt-BR.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl,lang\en.isl,lang\ru.isl"
Name: "ar"; MessagesFile: "compiler:Languages\Arabic.isl,lang\en.isl,lang\ar.isl"
Name: "hi"; MessagesFile: "lang\inno\Hindi.isl,lang\en.isl,lang\hi.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl,lang\en.isl,lang\ja.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl,lang\en.isl,lang\ko.isl"

[Tasks]
; Shown only for Custom; Recommended uses these defaults as they are. Same order as spec page B.
Name: "desktopicon"; Description: "{cm:TaskDesktop}"
Name: "startmenu"; Description: "{cm:TaskStartMenu}"
Name: "fileassoc"; Description: "{cm:TaskFileType}"
Name: "autostart"; Description: "{cm:TaskAutostart}"
Name: "claudecode"; Description: "{cm:TaskClaude}"
Name: "alltools"; Description: "{cm:TaskAllTools}"; Flags: unchecked

[InstallDelete]
; An update replaces the Python wholesale: an older installer shipped python.org's embeddable package there, whose
; leftover python3XX._pth would put the new python.exe into isolated mode. .venv was built on the old interpreter,
; so it goes too; Setup.bat (run below) rebuilds it offline. config.json, data\ and packs\ are not touched.
Type: filesandordirs; Name: "{app}\runtime\python"
Type: filesandordirs; Name: "{app}\.venv"
; Files an older SYNOX shipped that this one does not: what only people working on SYNOX use (scripts/make_zip.py
; INTERNAL, kept equal by tests/test_release_layout.py) and files that moved or went away (Connect-Apple.bat: use
; "python -m synox connect apple-reminders"; GOVERNANCE / MAINTAINERS / TRADEMARK now in .github\).
Type: filesandordirs; Name: "{app}\tests"
Type: filesandordirs; Name: "{app}\evals"
Type: filesandordirs; Name: "{app}\docs\lab"
Type: filesandordirs; Name: "{app}\docs\artifacts"
Type: files; Name: "{app}\docs\artifacts.json"
Type: files; Name: "{app}\docs\QuestionToUser.md"
Type: filesandordirs; Name: "{app}\docs\ui"
Type: filesandordirs; Name: "{app}\docs\installer"
Type: filesandordirs; Name: "{app}\docs\community"
Type: filesandordirs; Name: "{app}\.github\workflows"
Type: filesandordirs; Name: "{app}\.github\ISSUE_TEMPLATE"
Type: filesandordirs; Name: "{app}\.github\DISCUSSION_TEMPLATE"
Type: files; Name: "{app}\.github\pull_request_template.md"
Type: filesandordirs; Name: "{app}\.devcontainer"
Type: files; Name: "{app}\Connect-Apple.bat"
Type: files; Name: "{app}\GOVERNANCE.md"
Type: files; Name: "{app}\MAINTAINERS.md"
Type: files; Name: "{app}\TRADEMARK.md"

[Files]
; The two license files again, extract-only, so the welcome page can open them before anything is installed.
Source: "{#StageDir}\LICENSING.md"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#StageDir}\LICENSE"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "STAGE-MANIFEST.txt"

[Icons]
; Same targets as the setup wizard's own shortcuts (synox.wizard.shortcuts): Open-SYNOX.bat on the desktop, and
; Start.bat --no-browser in the Startup folder. Uninstall removes them.
Name: "{userdesktop}\SYNOX"; Filename: "{app}\Open-SYNOX.bat"; WorkingDir: "{app}"; IconFilename: "{app}\src\synox\assets\synox.ico"; Comment: "{cm:IconOpen}"; Flags: runminimized; Tasks: desktopicon
Name: "{userprograms}\SYNOX\SYNOX"; Filename: "{app}\Open-SYNOX.bat"; WorkingDir: "{app}"; IconFilename: "{app}\src\synox\assets\synox.ico"; Comment: "{cm:IconOpen}"; Flags: runminimized; Tasks: startmenu
Name: "{userprograms}\SYNOX\{cm:IconWizard}"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-m synox wizard"; WorkingDir: "{app}"; IconFilename: "{app}\src\synox\assets\synox.ico"; Tasks: startmenu
Name: "{userprograms}\SYNOX\{cm:IconUninstall}"; Filename: "{uninstallexe}"; Tasks: startmenu
Name: "{userstartup}\SYNOX"; Filename: "{app}\Start.bat"; Parameters: "--no-browser"; WorkingDir: "{app}"; IconFilename: "{app}\src\synox\assets\synox.ico"; Flags: runminimized; Tasks: autostart

[Run]
; Setup.bat builds .venv offline, keeps the language (-Lang, no question asked) and opens the setup wizard.
; HOOK(python agent): once bootstrap can run without a console (-NoWizard / -Step ...), move this to the Installing
; page and open the wizard here with pythonw. A Custom "which Python" choice would add -UseSystemPython here.
Filename: "{app}\Setup.bat"; Parameters: "-Lang {cm:SynoxLangCode}"; Description: "{cm:RunSetupNow}"; Flags: postinstall shellexec nowait

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\uninstall.ps1"" -Mode shortcuts -Yes -Lang en"; Flags: runhidden waituntilterminated; RunOnceId: "SynoxShortcuts"

[Code]
var
  TypePage: TInputOptionWizardPage;
  ClaudeResult: String;     { off | present | installed | skipped }
  DeleteUserData: Boolean;

const
  RecommendedTasks = 'desktopicon,startmenu,fileassoc,autostart,claudecode,!alltools';

{ ---------- helpers ---------- }

function IsRecommended: Boolean;
begin
  Result := (TypePage = nil) or (TypePage.SelectedValueIndex = 0);
end;

function JsonBool(const Value: Boolean): String;
begin
  if Value then Result := 'true' else Result := 'false';
end;

{ Where Claude Code is, or '' (the official installer puts claude.exe in %USERPROFILE%\.local\bin). }
function ClaudePath: String;
begin
  Result := ExpandConstant('{%USERPROFILE}\.local\bin\claude.exe');
  if not FileExists(Result) then
    Result := FileSearch('claude.exe', GetEnv('PATH'));
  if Result = '' then
    Result := FileSearch('claude.cmd', GetEnv('PATH'));
end;

{ ---------- welcome page: one line about the license ---------- }

procedure LicenseLinkClick(Sender: TObject; const Link: String; LinkType: TSysLinkType);
var
  Name, Path: String;
  ErrorCode: Integer;
begin
  Name := CustomMessage('LicenseFile');
  Path := ExpandConstant('{tmp}\') + Name;
  try
    if not FileExists(Path) then
      ExtractTemporaryFile(Name);
    ShellExec('', ExpandConstant('{win}\notepad.exe'), '"' + Path + '"', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
  except
    Log('Could not open ' + Name + ': ' + GetExceptionMessage);
  end;
end;

procedure AddLicenseLine;
var
  Link: TNewLinkLabel;
begin
  WizardForm.AdjustLabelHeight(WizardForm.WelcomeLabel2);
  Link := TNewLinkLabel.Create(WizardForm);
  Link.AutoSize := False;
  Link.Left := WizardForm.WelcomeLabel2.Left;
  Link.Top := WizardForm.WelcomeLabel2.Top + WizardForm.WelcomeLabel2.Height + ScaleY(20);
  Link.Width := WizardForm.WelcomeLabel2.Width;
  Link.Caption := CustomMessage('LicenseLine');
  Link.OnLinkClick := @LicenseLinkClick;
  Link.Parent := WizardForm.WelcomePage;
  Link.AdjustHeight;
end;

{ ---------- install type: Recommended | Custom ---------- }

procedure UpdateTypeButton;
begin
  if IsRecommended then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall)
  else
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
end;

procedure TypeChanged(Sender: TObject);
begin
  if WizardForm.CurPageID = TypePage.ID then
    UpdateTypeButton;
end;

procedure InitializeWizard;
begin
  AddLicenseLine;
  TypePage := CreateInputOptionPage(wpWelcome, CustomMessage('TypeTitle'), CustomMessage('TypeDesc'),
    CustomMessage('TypeLabel'), True, False);
  TypePage.Add(CustomMessage('TypeRecommended'));
  TypePage.Add(CustomMessage('TypeCustom'));
  TypePage.SelectedValueIndex := 0;
  TypePage.CheckListBox.OnClickCheck := @TypeChanged;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := IsRecommended and ((PageID = wpSelectDir) or (PageID = wpSelectTasks));
end;

{ Custom: SYNOX keeps config.json and data\ in its own folder, so the folder must be writable without admin. }
function DirIsWritable(const Dir: String): Boolean;
var
  Probe: String;
begin
  Result := False;
  if not ForceDirectories(Dir) then
    Exit;
  Probe := AddBackslash(Dir) + 'synox-write-test.tmp';
  if SaveStringToFile(Probe, 'ok', False) then begin
    DeleteFile(Probe);
    Result := True;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = TypePage.ID) and IsRecommended and (WizardForm.TasksList.Items.Count > 0) then
    WizardSelectTasks(RecommendedTasks);   { back from Custom: Recommended means the defaults again }
  if (CurPageID = wpSelectDir) and not DirIsWritable(WizardDirValue) then begin
    MsgBox(CustomMessage('DirNotWritable'), mbError, MB_OK);
    Result := False;
  end;
end;

{ Custom task list: Claude Code already there -> say so and grey it out. }
procedure MarkClaudePresent;
var
  I: Integer;
begin
  if ClaudePath = '' then
    Exit;
  for I := 0 to WizardForm.TasksList.Items.Count - 1 do
    if WizardForm.TasksList.ItemCaption[I] = CustomMessage('TaskClaude') then begin
      WizardForm.TasksList.ItemCaption[I] := CustomMessage('TaskClaudePresent');
      WizardForm.TasksList.ItemEnabled[I] := False;
    end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = TypePage.ID then
    UpdateTypeButton
  else if CurPageID = wpSelectTasks then begin
    MarkClaudePresent;
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall);
  end else if CurPageID = wpInstalling then
    WizardForm.FilenameLabel.Visible := False    { plain words only, no file names }
  else if (CurPageID = wpFinished) and (ClaudeResult = 'skipped') then begin
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 + CustomMessage('FinishedClaudeSkipped');
    WizardForm.AdjustLabelHeight(WizardForm.FinishedLabel);
  end;
end;

{ ---------- after the files are copied ---------- }

procedure InstallClaudeCode;
var
  Script: String;
  ResultCode: Integer;
begin
  if not WizardIsTaskSelected('claudecode') then begin
    ClaudeResult := 'off';
    Exit;
  end;
  if ClaudePath <> '' then begin
    ClaudeResult := 'present';
    Exit;
  end;
  ClaudeResult := 'skipped';
  Script := ExpandConstant('{app}\setup\installer\claude-code.ps1');
  if not FileExists(Script) then
    Exit;
  WizardForm.StatusLabel.Caption := CustomMessage('StatusClaude');
  WizardForm.ProgressGauge.Style := npbstMarquee;
  try
    if Exec('powershell.exe', '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script + '"',
            ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0)
       and (ClaudePath <> '') then
      ClaudeResult := 'installed';
    Log('Claude Code step: exit code ' + IntToStr(ResultCode) + ', result ' + ClaudeResult);
  finally
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
end;

{ lang.txt: the language for Setup.bat, the setup wizard, Uninstall.bat (synox.wizard.i18n.LANG_FILE). }
procedure SaveLanguage;
begin
  SaveStringToFile(ExpandConstant('{app}\lang.txt'), CustomMessage('SynoxLangCode') + #10, False);
end;

{ installer-choices.json: read by the setup wizard (synox.wizard.logic.installer_choices). }
procedure SaveChoices;
var
  Kind, S: String;
begin
  if IsRecommended then Kind := 'recommended' else Kind := 'custom';
  S := '{' + #10 +
       '  "source": "exe-installer",' + #10 +
       '  "version": "{#AppVersion}",' + #10 +
       '  "language": "' + CustomMessage('SynoxLangCode') + '",' + #10 +
       '  "install_type": "' + Kind + '",' + #10 +
       '  "desktop": ' + JsonBool(WizardIsTaskSelected('desktopicon')) + ',' + #10 +
       '  "start_menu": ' + JsonBool(WizardIsTaskSelected('startmenu')) + ',' + #10 +
       '  "file_type": ' + JsonBool(WizardIsTaskSelected('fileassoc')) + ',' + #10 +
       '  "autostart": ' + JsonBool(WizardIsTaskSelected('autostart')) + ',' + #10 +
       '  "claude_code": "' + ClaudeResult + '",' + #10 +
       '  "all_tools": ' + JsonBool(WizardIsTaskSelected('alltools')) + #10 +
       '}' + #10;
  SaveStringToFile(ExpandConstant('{app}\installer-choices.json'), S, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    SaveLanguage;
    InstallClaudeCode;   { last, optional, never blocks }
    SaveChoices;
  end;
end;

{ ---------- uninstall: keep the user's things unless they ask twice ---------- }

function AddText(Form: TSetupForm; const Text: String; Top: Integer; Bold: Boolean): TNewStaticText;
begin
  Result := TNewStaticText.Create(Form);
  Result.AutoSize := False;
  Result.WordWrap := True;
  Result.Left := ScaleX(16);
  Result.Top := Top;
  Result.Width := Form.ClientWidth - ScaleX(32);
  Result.Caption := Text;
  if Bold then
    Result.Font.Style := [fsBold];
  Result.Parent := Form;
  Result.AdjustHeight;
end;

{ True = go on (DeleteUserData says whether to delete the data too); False = cancel. }
function AskUninstallChoices: Boolean;
var
  Form: TSetupForm;
  Lbl: TNewStaticText;
  DataCheck: TNewCheckBox;
  OKButton, CancelButton: TNewButton;
  Y, W: Integer;
begin
  Result := False;
  DeleteUserData := False;
  repeat
    Form := CreateCustomForm(ScaleX(460), ScaleY(300), False, False);
    try
      Form.Caption := CustomMessage('UninstallTitle');
      Lbl := AddText(Form, CustomMessage('UninstallHeading'), ScaleY(14), True);
      Y := Lbl.Top + Lbl.Height + ScaleY(10);
      Lbl := AddText(Form, CustomMessage('UninstallRemoves'), Y, False);
      Y := Lbl.Top + Lbl.Height + ScaleY(8);
      Lbl := AddText(Form, CustomMessage('UninstallKeeps'), Y, False);
      Y := Lbl.Top + Lbl.Height + ScaleY(12);
      DataCheck := TNewCheckBox.Create(Form);
      DataCheck.Left := ScaleX(16);
      DataCheck.Top := Y;
      DataCheck.Width := Form.ClientWidth - ScaleX(32);
      DataCheck.Height := ScaleY(20);
      DataCheck.Caption := CustomMessage('UninstallDeleteData');
      DataCheck.Checked := False;
      DataCheck.Parent := Form;
      Y := DataCheck.Top + DataCheck.Height + ScaleY(2);
      Lbl := AddText(Form, CustomMessage('UninstallDeleteDataNote'), Y, False);
      Lbl.Left := ScaleX(34);
      Lbl.Width := Form.ClientWidth - ScaleX(50);
      Lbl.AdjustHeight;
      Y := Lbl.Top + Lbl.Height + ScaleY(12);
      Lbl := AddText(Form, CustomMessage('UninstallUntouched'), Y, False);
      Y := Lbl.Top + Lbl.Height + ScaleY(16);

      OKButton := TNewButton.Create(Form);
      OKButton.Caption := SetupMessage(msgButtonNext);
      OKButton.ModalResult := mrOk;
      OKButton.Default := True;
      OKButton.Parent := Form;
      CancelButton := TNewButton.Create(Form);
      CancelButton.Caption := SetupMessage(msgButtonCancel);
      CancelButton.ModalResult := mrCancel;
      CancelButton.Cancel := True;
      CancelButton.Parent := Form;
      W := Form.CalculateButtonWidth([OKButton.Caption, CancelButton.Caption]);
      OKButton.Width := W;
      CancelButton.Width := W;
      OKButton.Height := ScaleY(23);
      CancelButton.Height := ScaleY(23);
      Form.ClientHeight := Y + ScaleY(23 + 14);
      OKButton.Top := Y;
      CancelButton.Top := Y;
      CancelButton.Left := Form.ClientWidth - ScaleX(16) - W;
      OKButton.Left := CancelButton.Left - ScaleX(8) - W;
      Form.ActiveControl := OKButton;
      Form.FlipAndCenterIfNeeded(False, nil, False);

      if Form.ShowModal() <> mrOk then
        Exit;
      DeleteUserData := DataCheck.Checked;
    finally
      Form.Free();
    end;
    if not DeleteUserData then begin
      Result := True;
      Exit;
    end;
    { second confirmation; "No" goes back to the first screen with the box unticked }
    if MsgBox(CustomMessage('UninstallConfirmData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then begin
      Result := True;
      Exit;
    end;
    DeleteUserData := False;
  until False;
end;

function InitializeUninstall(): Boolean;
begin
  DeleteUserData := False;
  if UninstallSilent then
    Result := True          { silent uninstall keeps the data, like the default }
  else
    Result := AskUninstallChoices;
end;

{ Only things SYNOX itself creates in its folder. The whole folder goes only when it is a folder named SYNOX. }
procedure DeleteUserDataNow;
var
  App: String;
begin
  App := ExpandConstant('{app}');
  DelTree(App + '\data', True, True, True);
  DelTree(App + '\packs', True, True, True);
  DelTree(App + '\tools', True, True, True);
  DelTree(App + '\.venv', True, True, True);
  DelTree(App + '\runtime', True, True, True);
  DeleteFile(App + '\config.json');
  DeleteFile(App + '\lang.txt');
  DeleteFile(App + '\installer-choices.json');
  if CompareText(ExtractFileName(App), 'SYNOX') = 0 then
    DelTree(App, True, True, True)
  else
    RemoveDir(App);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DeleteUserData then
    DeleteUserDataNow;
end;

[UninstallDelete]
; What SYNOX makes at run time next to the installed files (.venv, its own Python, Python caches in the code
; folders, the language file, the installer's choices). The user's own files (settings, notes, keys, installed
; tools) are KEPT unless they tick the box on the first uninstall screen and confirm (see DeleteUserDataNow).
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\vendor"
; Old program files Update.bat keeps for "Update.bat -Rollback" (docs/adr/0023; never the user's own files).
Type: filesandordirs; Name: "{app}\_previous"
Type: files; Name: "{app}\lang.txt"
Type: files; Name: "{app}\installer-choices.json"
