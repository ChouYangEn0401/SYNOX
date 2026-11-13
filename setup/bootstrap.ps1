# bootstrap.ps1 — Setup.bat 叫的安裝步驟（UTF-8 有 BOM：PowerShell 5.1 沒 BOM 會當成 cp950）。
# 0. 先選語言（lang.ps1）：-Lang／SYNOX_LANG → lang.txt → 問（按 Enter＝Windows 的顯示語言）；存進 lang.txt，再用 --lang 交給精靈。
#    接著印「先說清楚」，再問一題：按 Enter 照建議（推薦），輸入 C 自訂（Setup.bat -Custom＝直接進自訂）。
#    建議＝只準備好 SYNOX 本身＋入門教學，開機自動啟動；工具等看完教學再自己挑。自訂可以改：開機自動啟動、
#    裝 Claude Code（這台沒有才裝）、全部工具都裝（不建議）。輸入被導向（沒有人在看）時照建議、不問。
# 1. Python（docs/adr/0003 附記「預設用 SYNOX 自己的 Python」）：
#    預設＝SYNOX 自己的 Python，全部放在 SYNOX 資料夾的 runtime\python 裡，不改 PATH、不寫登錄檔、不要管理員、
#      不碰 Conda／Microsoft Store／其他 Python。runtime\python 已經有（安裝程式附的，或上次下載的）就直接用；
#      沒有就下載 python-build-standalone 的 CPython（網址與 SHA256 都釘死，跟安裝程式附的是同一個檔案），
#      用 Windows 內建的 tar.exe 解到 runtime\python。檢查碼不對＝刪掉下載的檔案、停下來，不會改用別的來源。
#      不用 uv，也不用 python.org 的可攜版（沒有視窗元件）。
#    進階＝Setup.bat -UseSystemPython：照舊的順序找這台電腦的 Python（runtime\python → py 啟動器 → PATH 上的 python →
#      %LOCALAPPDATA%\Programs\Python → winget → 都沒有才用 SYNOX 自己的），但絕不挑 Microsoft Store 的 WindowsApps 捷徑
# 2. python -m venv 建 .venv → 裝相依：有 wheelhouse\ 就離線裝（--no-index）；有 requirements.lock 就照鎖定的版本裝；
#    都沒有才照 pyproject 的範圍裝（docs/adr/0003；lock 與 wheelhouse 由 scripts/lock_deps.py 在發佈機產生）→ pip install -e .
# 3. 照第 0 步的選擇做（Invoke-SetupPlan），再打開安裝精靈（pythonw，沒有黑色視窗）；這個 Python 沒有 tkinter
#    就在這個視窗跑文字版 `synox init`
# 重跑是安全的：已經有 .venv 就直接更新套件、打開精靈（要換 Python：Uninstall.bat env，再跑 Setup.bat）。
# 這個程序（和它開的精靈）先清掉 Conda／PYTHONHOME／PYTHONPATH 這類變數（Clear-PythonEnv），只影響這一次，不改 Windows 的設定。
param([string]$Lang = '', [switch]$UseSystemPython, [switch]$Custom)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
. (Join-Path $PSScriptRoot 'lang.ps1')
$LangCode = Resolve-SynoxLang $Root $Lang -SaveOverride
Import-SynoxText $LangCode
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$Venv = Join-Path $Root '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$VenvPyw = Join-Path $Venv 'Scripts\pythonw.exe'
$Runtime = Join-Path $Root 'runtime'
$PythonDir = Join-Path $Runtime 'python'
# SYNOX 自己的 Python：python-build-standalone（https://github.com/astral-sh/python-build-standalone）的
# install_only_stripped（Windows x64：python.exe、pip、venv、tkinter＋Tcl/Tk 8.6 都在裡面；去掉除錯符號，約 22 MB）。
# 網址與 SHA256 都釘死；SHA256 跟那個 release 的 SHA256SUMS 那一行一樣，也實際下載算過。換版本時這四行一起換，
# 並更新 tests/test_private_python.py。安裝程式（scripts/stage_installer.py）讀的也是這四行，所以兩邊是同一個 Python。
$PythonVersion = '3.12.16'
$PythonBuild = '20261026'
$PythonSha256 = '1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149'
$PythonUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$PythonBuild/cpython-$PythonVersion%2B$PythonBuild-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
# 只有 .tar.gz（這個專案的 Windows 版沒有 .zip）：PowerShell 5.1 的 Expand-Archive 只會解 zip，所以用 Windows 10 1803
# 以後內建的 tar.exe。寫完整路徑，不用 PATH 上的 tar（Git 附的 GNU tar 會把 C: 當成遠端主機）。
$WindowsTar = Join-Path $env:SystemRoot 'System32\tar.exe'
# Claude Code 的官方安裝指令：跟精靈「一鍵安裝」同一行（src/synox/wizard/logic.py 的 CLAUDE_INSTALL_PS）
$ClaudeInstallPs = 'irm https://claude.ai/install.ps1 | iex'

function Say([string]$Text) { Write-Host "[SYNOX] $Text" }

function Test-Python([string]$Exe, [string[]]$Pre) {
    try {
        & $Exe @Pre -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Test-StoreAlias([string]$Path) {
    # Microsoft Store 的 python 捷徑（沒裝時一執行就打開商店）與商店版 Python 都在 ...\WindowsApps\ 底下
    return ("$Path" -like '*\WindowsApps\*')
}

function Test-OldEmbedded([string]$Dir) {
    # python.org 的可攜版（embeddable）有 python3XX._pth：沒有 tkinter、沒有 venv。舊版的 Setup.bat 和安裝程式裝過這種
    return [bool](Get-ChildItem -LiteralPath $Dir -Filter 'python*._pth' -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Find-OtherPythons {
    # 這台電腦已經有的 Python（只看、不動）：要在 Clear-PythonEnv 之前叫，CONDA_PREFIX／CONDA_EXE 是線索
    $found = @()
    if ($env:CONDA_PREFIX -or $env:CONDA_EXE -or (Get-Command conda -ErrorAction SilentlyContinue)) {
        $found += (Tr 'found_conda')
    }
    if ($env:LOCALAPPDATA -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\python.exe'))) {
        $found += (Tr 'found_store_alias')
    }
    $other = @(Get-Command -Name py, python, python3 -CommandType Application -All -ErrorAction SilentlyContinue |
               Where-Object { -not (Test-StoreAlias $_.Source) })
    if ($other.Count -or ($env:LOCALAPPDATA -and (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'Programs\Python')))) {
        $found += (Tr 'found_other_python')
    }
    return $found
}

function Clear-PythonEnv {
    # 只清這個程序的：別人的 Python 設定不能漏進 SYNOX 的 Python（Start.bat 等用 setup\clean-python-env.bat 做同一件事）
    $names = @('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'PYTHONEXECUTABLE', 'VIRTUAL_ENV',
               '__PYVENV_LAUNCHER__', '_CE_CONDA', '_CE_M', 'PIP_USER', 'PIP_TARGET', 'PIP_PREFIX')
    foreach ($n in $names) { Remove-Item -LiteralPath "Env:$n" -ErrorAction SilentlyContinue }
    Get-ChildItem Env: | Where-Object { $_.Name -like 'CONDA_*' } |
        ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" -ErrorAction SilentlyContinue }
    $env:PYTHONNOUSERSITE = '1'
}

# ── 先說清楚、建議／自訂 ───────────────────────────────────────────

function Test-Interactive {
    # 輸入被導向（自動測試、沒有人在看）就不問，照建議
    try { return (-not [Console]::IsInputRedirected) } catch { return $true }
}

function Show-SetupIntro {
    Write-Host ''
    Say (Tr 'intro_title')
    foreach ($key in @('intro_1', 'intro_2', 'intro_3')) { Write-Host "        - $(Tr $key)" }
}

function Read-SetupPlan([bool]$GoCustom) {
    # 建議（按 Enter）＝只準備好 SYNOX＋入門教學、開機自動啟動；Claude Code 和全部工具都不裝（工具看完教學自己挑）。
    # 自訂的預設值跟建議一樣：一路按 Enter 結果相同。
    $plan = @{ Custom = $false; Autostart = $true; ClaudeCode = $false; AllTools = $false }
    if (-not (Test-Interactive)) { return $plan }
    if (-not $GoCustom) {
        Write-Host ''
        Write-Host "  Enter = $(Tr 'plan_recommended')"
        Write-Host "  C     = $(Tr 'plan_custom')"
        $answer = "$(Read-Host (Tr 'plan_question'))".Trim()
        if ($answer -notmatch '^[cC]') { return $plan }
    }
    $plan.Custom = $true
    $items = @(@{ Key = 'Autostart'; Text = (Tr 'custom_autostart') },
               @{ Key = 'ClaudeCode'; Text = (Tr 'custom_claude') },
               @{ Key = 'AllTools'; Text = (Tr 'custom_all_tools') })
    while ($true) {
        Write-Host ''
        Say (Tr 'custom_title')
        for ($i = 0; $i -lt $items.Count; $i++) {
            $mark = if ($plan[$items[$i].Key]) { '[x]' } else { '[ ]' }
            Write-Host ('  {0}) {1} {2}' -f ($i + 1), $mark, $items[$i].Text)
        }
        $answer = "$(Read-Host (Tr 'custom_prompt'))".Trim()
        if (-not $answer) { return $plan }
        $n = 0
        if ([int]::TryParse($answer, [ref]$n) -and $n -ge 1 -and $n -le $items.Count) {
            $key = $items[$n - 1].Key
            $plan[$key] = -not $plan[$key]
        }
    }
}

function Install-ClaudeCode {
    # 只有自訂裡勾了才會走到這裡。這台已經有 claude 就不裝；沒有就另開一個視窗跑官方安裝指令（裝在使用者自己的資料夾，
    # 不在 SYNOX 資料夾裡、不要管理員），跟精靈的「一鍵安裝」一樣。
    $found = ''
    try { $found = "$(& $VenvPy -c "from synox.llm.claude_code import find_claude; print(find_claude() or '')" 2>$null)".Trim() } catch { }
    if ($found) { Say (Tr 'claude_found' $found); return }
    Say (Tr 'claude_opening')
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList "-NoExit -NoProfile -ExecutionPolicy Bypass -Command `"$ClaudeInstallPs`""
    } catch { Say (Tr 'claude_failed' $_.Exception.Message) }
}

function Enable-Autostart {
    # 文字版設定（沒有精靈的完成頁可以勾）才用：跟精靈一樣，在啟動資料夾放 SYNOX.cmd（src/synox/wizard/shortcuts.py）
    try {
        $out = & $VenvPy -c "import sys; from synox.wizard import shortcuts; print(shortcuts.enable_autostart(sys.argv[1]))" $Root 2>$null
        if ($LASTEXITCODE -eq 0) { Say (Tr 'autostart_on' ("$out".Trim())); return }
    } catch { }
    Say (Tr 'autostart_failed')
}

function Invoke-SetupPlan($Plan) {
    # 精靈完成頁「開機自動啟動」那一格的預設勾選（src/synox/wizard/pages.py 讀這個變數；使用者在那裡還能改）
    $env:SYNOX_SETUP_AUTOSTART = if ($Plan.Autostart) { '1' } else { '0' }
    if ($Plan.ClaudeCode) { Install-ClaudeCode }
    if ($Plan.AllTools) {
        # TODO(工具庫／教學包)：「全部工具都裝」還沒有做。一次裝完整個工具庫（每個工具一樣先看安全報告、核准）的流程
        # 做好之後接在這裡，例如 & $VenvPy -m synox tools install <全部> 。現在只說一聲、不裝。
        Say (Tr 'all_tools_later')
    }
    # TODO(教學包)：建議和自訂都要在設定完之後打開入門教學（另一個工作正在做教學包）。做好之後在這裡，或在精靈的
    # 完成頁打開它（src/synox/tutorials.py：tutorials.open_local(<名字>)）。現在還沒有，所以什麼都不做、也不說。
}

# ── Python ─────────────────────────────────────────────────────────

function Find-SystemPython {
    # -UseSystemPython：舊的找法（SYNOX 資料夾自己的 Python 還是第一個），但絕不挑 Store 的捷徑
    $rt = Join-Path $PythonDir 'python.exe'
    if ((Test-Path -LiteralPath $rt) -and -not (Test-OldEmbedded $PythonDir) -and (Test-Python $rt @())) {
        return @{ Exe = $rt; Pre = @() }
    }
    if (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
        foreach ($v in @('-3.13', '-3.12', '-3.11')) {
            if ((Test-Python 'py' @($v)) -and -not (Test-StoreAlias (Get-PythonPath 'py' @($v)))) {
                return @{ Exe = 'py'; Pre = @($v) }
            }
        }
    }
    foreach ($cmd in @(Get-Command python -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if (Test-StoreAlias $cmd.Source) { continue }               # 先擋掉再執行：那個捷徑一跑就開商店
        if (Test-Python $cmd.Source @()) { return @{ Exe = $cmd.Source; Pre = @() } }
    }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")) {
        if ((Test-Path -LiteralPath $p) -and (Test-Python $p @())) { return @{ Exe = $p; Pre = @() } }
    }
    return $null
}

function Get-PythonPath([string]$Exe, [string[]]$Pre) {
    try {
        $out = & $Exe @Pre -c "import sys; print(sys.executable)" 2>$null
        return "$out".Trim()
    } catch { return '' }
}

function Get-SystemPython {
    $py = Find-SystemPython
    if (-not $py) { Install-WithWinget; $py = Find-SystemPython }
    if (-not $py) {
        # 還是沒有：改用 SYNOX 自己的（跟預設同一個：釘死網址＋SHA256，放在 runtime\python）
        try { Install-StandalonePython | Out-Null } catch { Say $_.Exception.Message }
        $py = Find-SystemPython
    }
    return $py
}

function Remove-Folder([string]$Path) {
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue }
}

function Install-StandalonePython {
    # 下載 → 核對 SHA256（不對就刪掉、停下來）→ 用 Windows 的 tar.exe 解開 → 搬到 runtime\python。全部在 runtime\ 裡。
    if (-not (Test-Path -LiteralPath $WindowsTar)) { throw (Tr 'py_no_tar') }
    Say (Tr 'py_download' $PythonVersion)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'                  # PowerShell 5.1 的進度條會讓下載慢很多
    $work = Join-Path $Runtime 'python.download'
    Remove-Folder $work
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    $archive = Join-Path $work 'python.tar.gz'
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $PythonUrl -OutFile $archive
    } catch {
        Remove-Folder $work
        throw (Tr 'py_download_failed' $_.Exception.Message)
    }
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    if ($hash -ne $PythonSha256) {                            # -ne 不分大小寫
        Remove-Folder $work                                   # 刪掉下載的檔案，絕不解開、不執行
        throw (Tr 'py_hash_bad' $hash)
    }
    Say (Tr 'py_extract')
    # 先切到下載資料夾、只給 tar 相對路徑：SYNOX 資料夾的路徑可能有中文，不交給 tar 處理
    Push-Location -LiteralPath $work
    try {
        & $WindowsTar -xzf 'python.tar.gz' | Out-Host
        $rc = $LASTEXITCODE
    } finally { Pop-Location }
    $extracted = Join-Path $work 'python'
    if ($rc -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $extracted 'python.exe'))) {
        Remove-Folder $work
        throw (Tr 'py_extract_failed' $rc)
    }
    Remove-Folder $PythonDir                                  # 舊的（可攜版或壞掉的）換掉；只在 runtime\ 裡
    if (Test-Path -LiteralPath $PythonDir) {                  # 刪不掉（有程式正在用）：不能搬進去，不然會變成 python\python
        Remove-Folder $work
        throw (Tr 'py_in_use')
    }
    Move-Item -LiteralPath $extracted -Destination $PythonDir
    Remove-Folder $work
    return (Join-Path $PythonDir 'python.exe')
}

function Get-PrivatePython {
    # 預設：只用 SYNOX 資料夾裡的 Python（runtime\python：安裝程式附的，或上次下載的）
    $exe = Join-Path $PythonDir 'python.exe'
    if (Test-Path -LiteralPath $exe) {
        if (Test-OldEmbedded $PythonDir) { Say (Tr 'py_old_embedded') }
        elseif (Test-Python $exe @()) { return @{ Exe = $exe; Pre = @() } }
    }
    Say (Tr 'private_python')
    $exe = Install-StandalonePython
    if (-not (Test-Python $exe @())) { throw (Tr 'py_does_not_run' $exe) }
    return @{ Exe = $exe; Pre = @() }
}

function Test-VenvHome {
    # 舊版 Setup.bat 用這台電腦的 Python 建的 .venv：照樣用，但說一聲怎麼換成 SYNOX 自己的
    $cfg = Join-Path $Venv 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $cfg)) { return }
    $line = Get-Content -LiteralPath $cfg -Encoding UTF8 | Where-Object { $_ -match '^\s*home\s*=' } | Select-Object -First 1
    if (-not $line) { return }
    $home_ = ($line -split '=', 2)[1].Trim()
    $inside = $Runtime.TrimEnd('\') + '\'
    if (-not $home_.StartsWith($inside, [StringComparison]::OrdinalIgnoreCase)) { Say (Tr 'venv_outside' $home_) }
}

function Test-Window {
    # 沒有 tkinter（-UseSystemPython 挑到的 Python 沒裝 tcl/tk，或舊的可攜版建的 .venv）：精靈開不了視窗，改用文字版
    try {
        & $VenvPy -c "import tkinter, _tkinter" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Install-Packages {
    $wheels = Join-Path $Root 'wheelhouse'
    $lock = Join-Path $Root 'requirements.lock'
    $pip = @('-m', 'pip', 'install', '--disable-pip-version-check', '-q')
    if (Test-Path -LiteralPath $wheels) {
        Say (Tr 'offline_wheels')
        $offline = $pip + @('--no-index', '--find-links', $wheels)
        if (Test-Path -LiteralPath $lock) {
            & $VenvPy @offline -r $lock | Out-Host
            if ($LASTEXITCODE -ne 0) { throw (Tr 'pip_failed') }
            & $VenvPy @offline --no-deps -e $Root | Out-Host
        } else {
            & $VenvPy @offline -e $Root | Out-Host
        }
    } elseif (Test-Path -LiteralPath $lock) {
        & $VenvPy @pip --upgrade pip | Out-Host
        & $VenvPy @pip -r $lock | Out-Host
        if ($LASTEXITCODE -ne 0) { throw (Tr 'pip_failed') }
        & $VenvPy @pip --no-deps -e $Root | Out-Host
    } else {
        # 連網、照 pyproject 的範圍裝：連 llm 組（ntu_easy_llm 的官方 release wheel 網址）一起裝，用金鑰的 AI 裝完就能用。
        # 上面兩條（wheelhouse 離線、requirements.lock）不變：鎖與 wheelhouse 不含 llm 組（scripts/lock_deps.py）。
        & $VenvPy @pip --upgrade pip | Out-Host
        & $VenvPy @pip -e "$Root[llm]" | Out-Host
    }
    if ($LASTEXITCODE -ne 0) { throw (Tr 'pip_failed') }
}

function Install-WithWinget {
    # 只有 -UseSystemPython 會走到這裡（會改這台電腦的 Python 與 PATH）
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return }
    Say (Tr 'no_python_winget')
    try {
        & winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements | Out-Host
    } catch { Say (Tr 'winget_failed' $_.Exception.Message) }
}

try {
    $others = @(Find-OtherPythons)
    Clear-PythonEnv
    if (-not $UseSystemPython) {
        Show-SetupIntro
        if ($others.Count) { Say (Tr 'env_note' ($others -join ', ')) }
    }
    $plan = Read-SetupPlan $Custom.IsPresent
    Write-Host ''
    Say (Tr 'prep')
    if (-not (Test-Path -LiteralPath $VenvPy)) {
        if ($UseSystemPython) {
            Say (Tr 'system_python')
            Say (Tr 'system_python_warning')
            $py = Get-SystemPython
        } else {
            $py = Get-PrivatePython
        }
        if (-not $py) { throw (Tr 'cannot_install_python') }
        Say (Tr 'creating_venv' ("$($py.Exe) $($py.Pre -join ' ')".Trim()))   # 括號：參數模式不會叫 .Trim()
        & $py.Exe @($py.Pre) -m venv $Venv | Out-Host
        if (-not (Test-Path -LiteralPath $VenvPy)) { throw (Tr 'venv_failed') }
    } elseif (-not $UseSystemPython) {
        Test-VenvHome
    }
    Say (Tr 'installing')
    Install-Packages
    # .synoxpack 檔案關聯（圖示＋點兩下＝Install-Pack.bat）：只寫 HKCU，重跑一樣；每一行印動了哪個機碼。失敗不擋安裝
    Say (Tr 'assoc_register')
    & $VenvPy -m synox filetype register | Out-Host
    if ($LASTEXITCODE -ne 0) { Say (Tr 'assoc_failed') }
    Invoke-SetupPlan $plan
    if (-not (Test-Window)) {
        Say (Tr 'no_window_text')
        & $VenvPy -m synox init
        $rc = $LASTEXITCODE
        if ($rc -eq 0 -and $plan.Autostart) { Enable-Autostart }
        exit $rc
    }
    Say (Tr 'opening_wizard')
    $exe = if (Test-Path -LiteralPath $VenvPyw) { $VenvPyw } else { $VenvPy }
    Start-Process -FilePath $exe -ArgumentList @('-m', 'synox', 'wizard', '--lang', $LangCode) -WorkingDirectory $Root
    exit 0
} catch {
    Write-Host "[SYNOX] ❌ $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "[SYNOX] $(Tr 'failed')"
    exit 1
}
