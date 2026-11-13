# bootstrap.ps1 — Setup.bat 叫的安裝步驟（UTF-8 有 BOM：PowerShell 5.1 沒 BOM 會當成 cp950）。
# 1. Python（docs/adr/0003 附記「預設用 SYNOX 自己的 Python」）：
#    預設＝SYNOX 自己的 Python，全部放在 SYNOX 資料夾的 runtime\ 裡，不改 PATH、不寫登錄檔、不要管理員、不碰 Conda／其他 Python：
#      runtime\python（安裝程式附的；pip、virtualenv 從 wheelhouse 離線裝）→ 用釘死版本＋SHA256 的 uv 裝 CPython 到
#      runtime\python-uv（--python-preference only-managed：絕不挑這台電腦的 Python）→ uv 失敗才退到 python.org 的
#      embeddable zip 解到 runtime\python（沒有 tkinter，設定改文字版；會明說）
#    進階＝Setup.bat -UseSystemPython：照舊的順序找這台電腦的 Python（runtime\python → py 啟動器 → PATH 上的 python →
#      %LOCALAPPDATA%\Programs\Python → winget → embeddable zip），但絕不挑 Microsoft Store 的 WindowsApps 捷徑
# 2. 建 .venv → 裝相依：有 wheelhouse\ 就離線裝（--no-index）；有 requirements.lock 就照鎖定的版本裝；都沒有才照
#    pyproject 的範圍裝（docs/adr/0003；lock 與 wheelhouse 由 scripts/lock_deps.py 在發佈機產生）→ pip install -e .
# 3. 打開安裝精靈（pythonw，沒有黑色視窗）；這個 Python 沒有 tkinter（可攜版）就在這個視窗跑文字版 `synox init`
# 重跑是安全的：已經有 .venv 就直接更新套件、打開精靈（要換 Python：Uninstall.bat env，再跑 Setup.bat）。
# 0. 先選語言（lang.ps1）：-Lang／SYNOX_LANG → lang.txt → 問；存進 lang.txt，再用 --lang 交給精靈。
# 這個程序（和它開的精靈）先清掉 Conda／PYTHONHOME／PYTHONPATH 這類變數（Clear-PythonEnv），只影響這一次，不改 Windows 的設定。
param([string]$Lang = '', [switch]$UseSystemPython)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
. (Join-Path $PSScriptRoot 'lang.ps1')
$LangCode = Resolve-SynoxLang $Root $Lang -SaveOverride
Import-SynoxText $LangCode
Write-Host "[SYNOX] $(Tr 'prep')"
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$Venv = Join-Path $Root '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$VenvPyw = Join-Path $Venv 'Scripts\pythonw.exe'
$Runtime = Join-Path $Root 'runtime'
$EmbedVersion = '3.12.10'
# uv（https://github.com/astral-sh/uv）：版本與 zip 的 SHA256 都釘死。SHA256 抄自同一個 release 的
# uv-x86_64-pc-windows-msvc.zip.sha256（和 sha256.sum 那一行一樣）；換版本時兩個一起換，並更新 tests/test_private_python.py。
$UvVersion = '0.13.6'
$UvSha256 = 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f'
$UvUrl = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
$UvPython = '3.12.16'                                   # 這版 uv 內建的下載清單裡的 CPython；換 uv 版本時一起看
$UvHome = Join-Path $Runtime 'uv'
$UvDir = Join-Path $UvHome $UvVersion
$UvExe = Join-Path $UvDir 'uv.exe'
$UvPythonDir = Join-Path $Runtime 'python-uv'
$UvCache = Join-Path $Runtime 'uv-cache'

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
               '__PYVENV_LAUNCHER__', '_CE_CONDA', '_CE_M', 'PIP_USER', 'PIP_TARGET', 'PIP_PREFIX',
               'UV_PYTHON', 'UV_SYSTEM_PYTHON', 'UV_NO_MANAGED_PYTHON', 'UV_CONFIG_FILE', 'UV_OFFLINE')
    foreach ($n in $names) { Remove-Item -LiteralPath "Env:$n" -ErrorAction SilentlyContinue }
    Get-ChildItem Env: | Where-Object { $_.Name -like 'CONDA_*' } |
        ForEach-Object { Remove-Item -LiteralPath "Env:$($_.Name)" -ErrorAction SilentlyContinue }
    $env:PYTHONNOUSERSITE = '1'
}

function Find-SystemPython {
    # -UseSystemPython：舊的找法（SYNOX 資料夾自己帶的可攜版 Python 還是第一個），但絕不挑 Store 的捷徑
    $rt = Join-Path $Root 'runtime\python\python.exe'
    if ((Test-Path -LiteralPath $rt) -and (Test-Python $rt @())) { return @{ Exe = $rt; Pre = @(); Embedded = $true } }
    if (Get-Command py -CommandType Application -ErrorAction SilentlyContinue) {
        foreach ($v in @('-3.13', '-3.12', '-3.11')) {
            if ((Test-Python 'py' @($v)) -and -not (Test-StoreAlias (Get-PythonPath 'py' @($v)))) {
                return @{ Exe = 'py'; Pre = @($v); Embedded = $false }
            }
        }
    }
    foreach ($cmd in @(Get-Command python -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if (Test-StoreAlias $cmd.Source) { continue }               # 先擋掉再執行：那個捷徑一跑就開商店
        if (Test-Python $cmd.Source @()) { return @{ Exe = $cmd.Source; Pre = @(); Embedded = $false } }
    }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")) {
        if ((Test-Path -LiteralPath $p) -and (Test-Python $p @())) { return @{ Exe = $p; Pre = @(); Embedded = $false } }
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
        try { Install-Embedded } catch { Say $_.Exception.Message }
        $py = Find-SystemPython
    }
    return $py
}

function Set-UvEnv {
    # uv 的所有東西都在 runtime\ 裡；不讀使用者的 uv.toml；只用 uv 自己裝的 Python（不挑 PATH／Conda／Store 的）
    $env:UV_PYTHON_INSTALL_DIR = $UvPythonDir
    $env:UV_CACHE_DIR = $UvCache
    $env:UV_PYTHON_BIN_DIR = Join-Path $UvHome 'bin'          # 另外有 --no-bin；萬一還是寫了，也寫在 SYNOX 資料夾裡
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:UV_PYTHON_DOWNLOADS = 'automatic'
    $env:UV_NO_CONFIG = '1'
}

function Install-Uv {
    if (Test-Path -LiteralPath $UvExe) { return $UvExe }
    Say (Tr 'uv_download' $UvVersion)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'                  # PowerShell 5.1 的進度條會讓下載慢很多
    New-Item -ItemType Directory -Force -Path $UvHome | Out-Null
    $zip = Join-Path $UvHome "uv-$UvVersion.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $UvUrl -OutFile $zip
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
    if ($hash -ne $UvSha256) {                                # -ne 不分大小寫
        Remove-Item -LiteralPath $zip -Force
        throw (Tr 'uv_hash_bad' $hash)
    }
    $tmp = "$UvDir.tmp"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    Remove-Item -LiteralPath $zip -Force
    if (Test-Path -LiteralPath $UvDir) { Remove-Item -LiteralPath $UvDir -Recurse -Force }
    Move-Item -LiteralPath $tmp -Destination $UvDir
    if (-not (Test-Path -LiteralPath $UvExe)) { throw "uv.exe not found in $UvUrl" }
    return $UvExe
}

function Install-UvPython {
    $uv = Install-Uv
    Set-UvEnv
    Say (Tr 'uv_python' $UvPython)
    $ErrorActionPreference = 'Continue'                       # uv 把進度寫在 stderr；只看結束碼
    & $uv python install $UvPython --python-preference only-managed --no-bin --no-registry | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "uv python install $UvPython (exit $LASTEXITCODE)" }
    # uv 的資料夾名字是固定的（cpython-<版本>-windows-x86_64-none\python.exe）；只收 runtime\python-uv 底下的
    $exe = Get-ChildItem -LiteralPath $UvPythonDir -Directory -Filter "cpython-$UvPython-windows-*" -ErrorAction SilentlyContinue |
           ForEach-Object { Join-Path $_.FullName 'python.exe' } |
           Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $exe) { throw "python.exe not found in $UvPythonDir" }
    return $exe
}

function Get-PrivatePython {
    # 預設：只用 SYNOX 資料夾裡的 Python。1. 安裝程式附的
    $rt = Join-Path $Root 'runtime\python\python.exe'
    if ((Test-Path -LiteralPath $rt) -and (Test-Python $rt @())) { return @{ Exe = $rt; Pre = @(); Embedded = $true } }
    # 2. uv 裝的 CPython（有 tkinter，可以開視窗精靈）
    Say (Tr 'private_python')
    try {
        $exe = Install-UvPython
        if (Test-Python $exe @()) { return @{ Exe = $exe; Pre = @(); Embedded = $false } }
        throw "$exe does not run"
    } catch { Say (Tr 'uv_failed' $_.Exception.Message) }
    # 3. 最後退路：python.org 的可攜版（沒有 tkinter → 文字版設定）
    try { Install-Embedded } catch { Say $_.Exception.Message }
    if ((Test-Path -LiteralPath $rt) -and (Test-Python $rt @())) { return @{ Exe = $rt; Pre = @(); Embedded = $true } }
    return $null
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
    # 可攜版（embeddable）Python 沒有 tkinter：精靈開不了視窗，改用文字版
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

function Ensure-Virtualenv([string]$Exe) {
    # 安裝程式附的可攜版 Python（runtime\python）：pip、virtualenv 從 wheelhouse 離線裝，不跑 get-pip.py、不連網
    try {
        & $Exe -c "import virtualenv" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return }
    } catch {}
    $wheels = Join-Path $Root 'wheelhouse'
    if (-not (Test-Path -LiteralPath $wheels)) { return }
    $pipWheel = Get-ChildItem -LiteralPath $wheels -Filter 'pip-*.whl' | Select-Object -First 1
    if (-not $pipWheel) { return }
    Say (Tr 'offline_wheels')
    & $Exe (Join-Path $pipWheel.FullName 'pip') install --disable-pip-version-check --no-warn-script-location -q --no-index --find-links $wheels pip virtualenv | Out-Host
}

function Install-WithWinget {
    # 只有 -UseSystemPython 會走到這裡（會改這台電腦的 Python 與 PATH）
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return }
    Say (Tr 'no_python_winget')
    try {
        & winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements | Out-Host
    } catch { Say (Tr 'winget_failed' $_.Exception.Message) }
}

function Install-Embedded {
    Say (Tr 'embedded' $EmbedVersion)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $dir = Join-Path $Root 'runtime\python'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $zip = Join-Path $Root 'runtime\python-embed.zip'
    Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$EmbedVersion/python-$EmbedVersion-embed-amd64.zip" -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $dir -Force
    Remove-Item -LiteralPath $zip
    # 可攜版預設不載 site-packages：把 ._pth 裡的 "#import site" 打開
    Get-ChildItem -LiteralPath $dir -Filter 'python*._pth' | ForEach-Object {
        $text = (Get-Content -LiteralPath $_.FullName) -replace '^#\s*import site', 'import site'
        Set-Content -LiteralPath $_.FullName -Value $text -Encoding ascii
    }
    $getpip = Join-Path $Root 'runtime\get-pip.py'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getpip
    & (Join-Path $dir 'python.exe') $getpip --no-warn-script-location | Out-Host
    & (Join-Path $dir 'python.exe') -m pip install --no-warn-script-location -q virtualenv | Out-Host
}

try {
    $others = @(Find-OtherPythons)
    Clear-PythonEnv
    if (-not (Test-Path -LiteralPath $VenvPy)) {
        if ($UseSystemPython) {
            Say (Tr 'system_python')
            Say (Tr 'system_python_warning')
            $py = Get-SystemPython
        } else {
            if ($others.Count) { Say (Tr 'env_note' ($others -join ', ')) }
            $py = Get-PrivatePython
        }
        if (-not $py) { throw (Tr 'cannot_install_python') }
        Say (Tr 'creating_venv' "$($py.Exe) $($py.Pre -join ' ')".Trim())
        if ($py.Embedded) { Ensure-Virtualenv $py.Exe; & $py.Exe @($py.Pre) -m virtualenv $Venv | Out-Host }
        else { & $py.Exe @($py.Pre) -m venv $Venv | Out-Host }
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
    if (-not (Test-Window)) {
        Say (Tr 'no_window_text')
        & $VenvPy -m synox init
        exit $LASTEXITCODE
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
