# bootstrap.ps1 — Setup.bat 叫的安裝步驟（UTF-8 有 BOM：PowerShell 5.1 沒 BOM 會當成 cp950）。
# 1. 找 Python ≥ 3.11：SYNOX 資料夾裡的 runtime\python（安裝程式附的；pip、virtualenv 從 wheelhouse 離線裝）→
#    py 啟動器 → PATH 上的 python → winget 裝 Python.Python.3.12 → 最後退路：python.org 的
#    embeddable zip 解到 runtime\python（加 get-pip、virtualenv；要網路）
# 2. 建 .venv → 裝相依：有 wheelhouse\ 就離線裝（--no-index）；有 requirements.lock 就照鎖定的版本裝；都沒有才照
#    pyproject 的範圍裝（docs/adr/0002；lock 與 wheelhouse 由 scripts/lock_deps.py 在發佈機產生）→ pip install -e .
# 3. 打開安裝精靈（pythonw，沒有黑色視窗）；這個 Python 沒有 tkinter（可攜版）就在這個視窗跑文字版 `synox init`
# 重跑是安全的：已經有 .venv 就直接更新套件、打開精靈。
# 0. 先選語言（lang.ps1）：-Lang／SYNOX_LANG → lang.txt → 問；存進 lang.txt，再用 --lang 交給精靈。
param([string]$Lang = '')
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
$EmbedVersion = '3.12.10'

function Say([string]$Text) { Write-Host "[SYNOX] $Text" }

function Test-Python([string]$Exe, [string[]]$Pre) {
    try {
        & $Exe @Pre -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Python {
    # SYNOX 資料夾自己帶的可攜版 Python 優先（安裝程式附的；wheelhouse 的 wheel 是照它的版本挑的）
    $rt = Join-Path $Root 'runtime\python\python.exe'
    if ((Test-Path -LiteralPath $rt) -and (Test-Python $rt @())) { return @{ Exe = $rt; Pre = @(); Embedded = $true } }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @('-3.13', '-3.12', '-3.11')) {
            if (Test-Python 'py' @($v)) { return @{ Exe = 'py'; Pre = @($v); Embedded = $false } }
        }
    }
    if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Python 'python' @())) {
        return @{ Exe = 'python'; Pre = @(); Embedded = $false }
    }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
                     "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")) {
        if ((Test-Path -LiteralPath $p) -and (Test-Python $p @())) { return @{ Exe = $p; Pre = @(); Embedded = $false } }
    }
    return $null
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
        & $VenvPy @pip --upgrade pip | Out-Host
        & $VenvPy @pip -e $Root | Out-Host
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
    if (-not (Test-Path -LiteralPath $VenvPy)) {
        $py = Find-Python
        if (-not $py) { Install-WithWinget; $py = Find-Python }
        if (-not $py) { Install-Embedded; $py = Find-Python }
        if (-not $py) { throw (Tr 'cannot_install_python') }
        Say (Tr 'creating_venv' "$($py.Exe) $($py.Pre -join ' ')".Trim())
        if ($py.Embedded) { Ensure-Virtualenv $py.Exe; & $py.Exe @($py.Pre) -m virtualenv $Venv | Out-Host }
        else { & $py.Exe @($py.Pre) -m venv $Venv | Out-Host }
        if (-not (Test-Path -LiteralPath $VenvPy)) { throw (Tr 'venv_failed') }
    }
    Say (Tr 'installing')
    Install-Packages
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
