# bootstrap.ps1 — Setup.bat 叫的安裝步驟（UTF-8 有 BOM：PowerShell 5.1 沒 BOM 會當成 cp950）。
# 1. 找 Python ≥ 3.11：py 啟動器 → PATH 上的 python → winget 裝 Python.Python.3.12 → 最後退路：python.org 的
#    embeddable zip 解到 runtime\python（加 get-pip、virtualenv）
# 2. 建 .venv → pip install -e .
# 3. 打開安裝精靈（pythonw，沒有黑色視窗）
# 重跑是安全的：已經有 .venv 就直接更新套件、打開精靈。
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
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
    $rt = Join-Path $Root 'runtime\python\python.exe'
    if ((Test-Path -LiteralPath $rt) -and (Test-Python $rt @())) { return @{ Exe = $rt; Pre = @(); Embedded = $true } }
    return $null
}

function Install-WithWinget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return }
    Say '找不到 Python 3.11 以上，用 winget 安裝 Python 3.12（要幾分鐘）…'
    try {
        & winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements | Out-Host
    } catch { Say "winget 安裝失敗：$($_.Exception.Message)" }
}

function Install-Embedded {
    Say "改下載 python.org 的可攜版 Python $EmbedVersion 到 runtime\python …"
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
        if (-not $py) { throw '裝不起 Python。請到 https://www.python.org/downloads/ 安裝 Python 3.12，再雙擊 Setup.bat。' }
        Say "用 $($py.Exe) $($py.Pre -join ' ') 建立 .venv …"
        if ($py.Embedded) { & $py.Exe @($py.Pre) -m virtualenv $Venv | Out-Host }
        else { & $py.Exe @($py.Pre) -m venv $Venv | Out-Host }
        if (-not (Test-Path -LiteralPath $VenvPy)) { throw '建立 .venv 失敗。' }
    }
    Say '安裝 SYNOX 需要的套件（第一次要幾分鐘）…'
    & $VenvPy -m pip install --disable-pip-version-check -q --upgrade pip | Out-Host
    & $VenvPy -m pip install --disable-pip-version-check -q -e $Root | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'pip install 失敗（網路？）。' }
    Say '打開安裝精靈…'
    $exe = if (Test-Path -LiteralPath $VenvPyw) { $VenvPyw } else { $VenvPy }
    Start-Process -FilePath $exe -ArgumentList @('-m', 'synox', 'wizard') -WorkingDirectory $Root
    exit 0
} catch {
    Write-Host "[SYNOX] ❌ $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
