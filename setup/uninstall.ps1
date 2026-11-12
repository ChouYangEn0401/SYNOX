# uninstall.ps1 - called by Uninstall.bat (UTF-8 with BOM: PowerShell 5.1 reads a BOM-less file as cp950).
#   check      only report what is installed (changes nothing)
#   shortcuts  stop SYNOX; remove desktop shortcut, startup entry, .synoxpack association
#   env        shortcuts + delete .venv and runtime\  (keeps config.json and data\; Setup.bat restores it)
#   all        env + delete config.json and data\    (everything starts over; data is lost)
# Never deletes the SYNOX folder itself or any source file.
param(
    [ValidateSet('', 'check', 'shortcuts', 'env', 'all')][string]$Mode = '',
    [switch]$Yes
)
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$Runtime = Join-Path $Root 'runtime'
$Config = Join-Path $Root 'config.json'
$Data = Join-Path $Root 'data'
$Desktop = [Environment]::GetFolderPath('Desktop')
$Startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
if ($env:SYNOX_UNINSTALL_SANDBOX) {   # tests only: never touch the real Desktop / Startup / registry
    $Desktop = Join-Path $env:SYNOX_UNINSTALL_SANDBOX 'Desktop'
    $Startup = Join-Path $env:SYNOX_UNINSTALL_SANDBOX 'Startup'
}
$Lnk = Join-Path $Desktop 'SYNOX.lnk'
$StartupFiles = @((Join-Path $Startup 'SYNOX.cmd'), (Join-Path $Startup 'SYNOX.lnk'))
$ClassKeys = @('HKCU:\Software\Classes\.synoxpack', 'HKCU:\Software\Classes\SYNOX.Pack')

function Say([string]$Text) { Write-Host "[SYNOX] $Text" }

function Running-Pid {
    $lock = Join-Path $Data 'host.lock'
    if (-not (Test-Path -LiteralPath $lock)) { return $null }
    try {
        $p = (Get-Content -LiteralPath $lock -Raw -Encoding UTF8 | ConvertFrom-Json).pid
        if ($p -and (Get-Process -Id $p -ErrorAction SilentlyContinue)) { return $p }
    } catch { }
    return $null
}

function Pack-Registered {
    if ($env:SYNOX_UNINSTALL_SANDBOX) { return $false }
    $k = 'HKCU:\Software\Classes\.synoxpack'
    if (-not (Test-Path -LiteralPath $k)) { return $false }
    return ((Get-ItemProperty -LiteralPath $k).'(default)' -eq 'SYNOX.Pack')
}

function Show-State {
    $rows = @(
        @('SYNOX running (pid)',            [string](Running-Pid)),
        @('Desktop shortcut',               $(if (Test-Path -LiteralPath $Lnk) { $Lnk } else { '' })),
        @('Startup entry',                  (($StartupFiles | Where-Object { Test-Path -LiteralPath $_ }) -join ', ')),
        @('.synoxpack association',         $(if (Pack-Registered) { 'registered' } else { '' })),
        @('.venv',                          $(if (Test-Path -LiteralPath $Venv) { $Venv } else { '' })),
        @('runtime\ (embedded Python)',     $(if (Test-Path -LiteralPath $Runtime) { $Runtime } else { '' })),
        @('config.json',                    $(if (Test-Path -LiteralPath $Config) { $Config } else { '' })),
        @('data\ (notes, vault, tokens)',   $(if (Test-Path -LiteralPath $Data) { $Data } else { '' }))
    )
    Write-Host ''
    foreach ($r in $rows) {
        $state = if ($r[1]) { "PRESENT   $($r[1])" } else { 'not found' }
        Write-Host ("  {0,-32} {1}" -f $r[0], $state)
    }
    Write-Host ''
}

function Remove-Path([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Say "removed $Path"
    } catch {
        Say "could not remove $Path ($($_.Exception.Message)) - close anything using it and run again"
        $script:Failed = $true
    }
}

function Stop-Synox {
    $p = Running-Pid
    if (-not $p) { return }
    Say "stopping SYNOX (pid $p) ..."
    if (Test-Path -LiteralPath $VenvPy) {
        $env:PYTHONIOENCODING = 'utf-8'
        & $VenvPy -m synox stop | Out-Null
        Start-Sleep -Seconds 3
    }
    if (Running-Pid) {
        Say 'SYNOX is still running: close its window (or run Stop.bat) and run this again.'
        $script:Failed = $true
    }
}

function Remove-Shortcuts {
    Remove-Path $Lnk
    foreach ($f in $StartupFiles) { Remove-Path $f }
    if (Pack-Registered) {
        foreach ($k in $ClassKeys) {
            if (Test-Path -LiteralPath $k) {
                Remove-Item -LiteralPath $k -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        Say 'removed .synoxpack association (Explorer may need a refresh/sign-out to update icons)'
    }
}

$Failed = $false
if (-not $Mode) {
    Show-State
    Write-Host '  0  Check only (change nothing)'
    Write-Host '  1  Remove shortcuts, startup entry and .synoxpack association. Keeps everything else.'
    Write-Host '  2  1 + delete .venv and runtime\. Keeps config.json and data\ (Setup.bat restores it).'
    Write-Host '  3  2 + delete config.json and data\. EVERYTHING starts over; notes and vault are lost.'
    Write-Host '  q  Quit'
    $choice = Read-Host 'Choose'
    $Mode = switch ($choice) { '0' { 'check' } '1' { 'shortcuts' } '2' { 'env' } '3' { 'all' } default { 'quit' } }
}
if ($Mode -eq 'quit') { exit 0 }
if ($Mode -eq 'check') { Show-State; exit 0 }

if ($Mode -eq 'all' -and -not $Yes) {
    $typed = Read-Host 'This deletes config.json and data\ (notes, vault, tokens). Type DELETE to continue'
    if ($typed -ne 'DELETE') { Say 'cancelled, nothing changed.'; exit 1 }
}

Stop-Synox
if ($Failed) { exit 1 }
Remove-Shortcuts
if ($Mode -in @('env', 'all')) {
    Remove-Path $Venv
    Remove-Path $Runtime
}
if ($Mode -eq 'all') {
    Remove-Path $Config
    Remove-Path $Data
}
Say 'state after uninstall:'
Show-State
if ($Failed) { exit 1 }
Say 'done. Double-click Setup.bat to install again.'
exit 0
