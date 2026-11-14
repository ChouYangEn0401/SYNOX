; SYNOX installer texts, Korean (ko). Model-written translation: NEEDS NATIVE-SPEAKER REVIEW.
; Loaded after lang\en.isl, so a missing key falls back to English. Keys must match en.isl (tests/test_installer_script.py).

[LangOptions]
LanguageName=한국어 (Korean)

[Messages]
SelectLanguageTitle=언어 · Language
SelectLanguageLabel=언어를 선택하세요. 설치 프로그램, 설정 마법사, SYNOX 모두 이 언어를 사용합니다.
WelcomeLabel1=SYNOX에 오신 것을 환영합니다. 즐겁게 사용하세요!
WelcomeLabel2=•  내 컴퓨터에 사는 작은 도우미. Telegram, Discord 또는 웹 페이지에서 말을 걸 수 있습니다.%n•  전용 Python을 함께 가져오고 이 컴퓨터의 다른 것은 건드리지 않습니다.%n•  관리자 암호가 필요 없습니다. 모든 것이 내 계정의 폴더 하나에 들어갑니다.%n•  짧은 튜토리얼로 시작한 뒤 필요한 도구를 고르세요.
WizardSelectTasks=무엇을 준비할까요?
SelectTasksDesc=모두 권장 설정으로 되어 있습니다.
SelectTasksLabel2=모든 항목은 나중에 바꿀 수 있습니다. 설치 프로그램을 다시 실행하거나 SYNOX 설정에서 바꾸세요.
FinishedHeadingLabel=SYNOX 설치가 끝났습니다
FinishedLabel=마지막 한 단계: 설정 마법사를 열어 Telegram(또는 Discord)을 연결하고 사용할 AI를 고르세요. 약 3분 걸립니다. 그다음 짧은 튜토리얼을 해 보세요.
ClickFinish=마침을 누르면 설치 프로그램이 닫힙니다.
ConfirmUninstall=지금 %1을(를) 제거할까요?
UninstalledAll=%1을(를) 제거했습니다.
UninstalledMost=%1을(를) 제거했습니다.%n%n설정과 데이터는 SYNOX 폴더에 남아 있어 다시 설치하면 이어서 쓸 수 있습니다.
FinishedLabelNoIcons=마지막 한 단계: 설정 마법사를 열어 Telegram(또는 Discord)을 연결하고 사용할 AI를 고르세요. 약 3분 걸립니다. 그다음 짧은 튜토리얼을 해 보세요.

[CustomMessages]
DirNotWritable=SYNOX는 이 폴더에 데이터를 저장하는데 여기에는 쓸 수 없습니다. 다른 위치를 고르세요.
FinishedClaudeSkipped=Claude Code는 일단 건너뛰었습니다(인터넷 연결이 없을 수 있음). 나중에 설정 마법사의 AI 페이지에서 "원클릭 설치 (PowerShell)"로 추가할 수 있습니다.
IconOpen=SYNOX 열기
IconUninstall=SYNOX 제거
IconWizard=SYNOX 설정 마법사
LicenseFile=LICENSE
LicenseLine=개인 사용은 무료입니다. 상업적으로 사용하려면 <a id="license">AGPL-3.0 라이선스</a>를 읽어 주세요.
RunSetupNow=지금 설정 마법사 열기(권장)
StatusClaude=Claude Code를 설치하는 중입니다(인터넷 필요, 몇 분 걸릴 수 있음)…
SynoxLangCode=ko
TaskAllTools=공식 도구 모두 설치(권장하지 않음: 튜토리얼을 먼저 하고 필요한 것만 고르세요)
TaskAutostart=로그인할 때 SYNOX 시작(작은 창이 보이며 언제든 닫을 수 있음)
TaskClaude=Claude Code 설치(없을 때만, 인터넷 필요, 사용자 폴더에 설치)
TaskClaudePresent=Claude Code가 이미 설치되어 있습니다
TaskDesktop=바탕 화면에 "SYNOX" 바로 가기 만들기
TaskFileType=.synoxpack 파일을 더블클릭해 설치(설치 전에 검사하고 확인을 받음)
TaskStartMenu=시작 메뉴에 "SYNOX" 추가
TypeCustom=사용자 지정(폴더와 각 항목 직접 선택)
TypeDesc=대부분은 권장 설정 그대로 두면 됩니다.
TypeLabel=권장 설정은 전용 Python, 바탕 화면과 시작 메뉴 바로 가기, .synoxpack 파일 더블클릭 설치, 로그인 시 시작, 튜토리얼까지 준비합니다. 이 컴퓨터에 아직 Claude Code가 없으면 함께 설치합니다(인터넷 필요, 사용자 폴더에 설치). 나중에 바꾸고 싶으면 설치 프로그램을 다시 실행하세요. 데이터는 그대로 남습니다.
TypeRecommended=권장(모두 알아서 준비)
TypeTitle=SYNOX를 어떻게 설치할까요?
UninstallConfirmData=정말 데이터도 삭제할까요?%n%n설정, 메모, 가계부, 저장한 키, 설치한 도구가 삭제되며 되돌릴 수 없습니다.
UninstallDeleteData=내 데이터도 함께 삭제
UninstallDeleteDataNote=되돌릴 수 없습니다. 체크하면 한 번 더 묻습니다.
UninstallHeading=SYNOX를 제거할까요?
UninstallKeeps=남는 것: 설정, 메모, 가계부, 저장한 키, 설치한 도구. SYNOX 폴더에 남아 있어 다시 설치하면 이어서 쓸 수 있습니다.
UninstallRemoves=제거되는 것: SYNOX 프로그램, 전용 Python, 바로 가기, 로그인 시 시작, .synoxpack 더블클릭 설치.
UninstallTitle=SYNOX 제거
UninstallUntouched=이 컴퓨터의 다른 Python, Conda, Claude Code는 건드리지 않습니다.
