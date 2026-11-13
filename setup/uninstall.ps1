# uninstall.ps1 - called by Uninstall.bat (UTF-8 with BOM: PowerShell 5.1 reads a BOM-less file as cp950).
#   check      only report what is installed (changes nothing)
#   shortcuts  stop SYNOX; remove desktop shortcut, startup entry, .synoxpack association
#   env        shortcuts + delete .venv and runtime\  (keeps config.json and data\; Setup.bat restores it)
#              runtime\ = SYNOX's own private Python: the installer's runtime\python, uv (runtime\uv), the CPython
#              it installed (runtime\python-uv) and uv's cache (runtime\uv-cache). Nothing outside the SYNOX folder.
#   all        env + delete config.json and data\    (everything starts over; data is lost)
# Never deletes the SYNOX folder itself or any source file.
# Language: -Lang <code> (not saved) / SYNOX_LANG, else lang.txt, else ask first and save (lang.ps1).
# 'all' also deletes lang.txt (everything starts over, so the next Setup.bat asks again).
param(
    [ValidateSet('', 'check', 'shortcuts', 'env', 'all')][string]$Mode = '',
    [switch]$Yes,
    [string]$Lang = ''
)
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'lang.ps1')
Import-SynoxText (Resolve-SynoxLang $Root $Lang)
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
        @((Tr 'row_running'),   [string](Running-Pid)),
        @((Tr 'row_shortcut'),  $(if (Test-Path -LiteralPath $Lnk) { $Lnk } else { '' })),
        @((Tr 'row_startup'),   (($StartupFiles | Where-Object { Test-Path -LiteralPath $_ }) -join ', ')),
        @((Tr 'row_assoc'),     $(if (Pack-Registered) { Tr 'registered' } else { '' })),
        @((Tr 'row_venv'),      $(if (Test-Path -LiteralPath $Venv) { $Venv } else { '' })),
        @((Tr 'row_runtime'),   $(if (Test-Path -LiteralPath $Runtime) { $Runtime } else { '' })),
        @((Tr 'row_config'),    $(if (Test-Path -LiteralPath $Config) { $Config } else { '' })),
        @((Tr 'row_data'),      $(if (Test-Path -LiteralPath $Data) { $Data } else { '' }))
    )
    Write-Host ''
    foreach ($r in $rows) {
        $state = if ($r[1]) { "$(Tr 'present')   $($r[1])" } else { Tr 'not_found' }
        Write-Host ("  {0,-32} {1}" -f $r[0], $state)
    }
    Write-Host ''
}

function Remove-Path([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Say (Tr 'removed' $Path)
    } catch {
        Say (Tr 'could_not_remove' $Path $_.Exception.Message)
        $script:Failed = $true
    }
}

function Remove-Runtime {
    # runtime\python-uv has a directory junction per minor version (cpython-3.12-... -> cpython-3.12.x-...). Unlink
    # junctions/symlinks first (Directory.Delete on a reparse point removes only the link, never what it points to),
    # so the recursive delete below can never follow a link out of the SYNOX folder.
    if (-not (Test-Path -LiteralPath $Runtime)) { return }
    foreach ($dir in @($Runtime, (Join-Path $Runtime 'python-uv'))) {
        if (-not (Test-Path -LiteralPath $dir)) { continue }
        $links = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue |
                   Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
        foreach ($link in $links) {
            try { [IO.Directory]::Delete($link.FullName, $false) } catch { Say (Tr 'could_not_remove' $link.FullName $_.Exception.Message) }
        }
    }
    Remove-Path $Runtime
}

function Stop-Synox {
    $p = Running-Pid
    if (-not $p) { return }
    Say (Tr 'stopping' $p)
    if (Test-Path -LiteralPath $VenvPy) {
        $env:PYTHONIOENCODING = 'utf-8'
        & $VenvPy -m synox stop | Out-Null
        Start-Sleep -Seconds 3
    }
    if (Running-Pid) {
        Say (Tr 'still_running')
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
                Say (Tr 'removed' $k)
            }
        }
        Say (Tr 'removed_assoc')
    }
}

$Failed = $false
if (-not $Mode) {
    Show-State
    Write-Host "  0  $(Tr 'menu0')"
    Write-Host "  1  $(Tr 'menu1')"
    Write-Host "  2  $(Tr 'menu2')"
    Write-Host "  3  $(Tr 'menu3')"
    Write-Host "  q  $(Tr 'menuq')"
    $choice = Read-Host (Tr 'choose')
    $Mode = switch ($choice) { '0' { 'check' } '1' { 'shortcuts' } '2' { 'env' } '3' { 'all' } default { 'quit' } }
}
if ($Mode -eq 'quit') { exit 0 }
if ($Mode -eq 'check') { Show-State; exit 0 }

if ($Mode -eq 'all' -and -not $Yes) {
    $typed = Read-Host (Tr 'delete_prompt')
    if ($typed -ne 'DELETE') { Say (Tr 'cancelled'); exit 1 }
}

Stop-Synox
if ($Failed) { exit 1 }
Remove-Shortcuts
if ($Mode -in @('env', 'all')) {
    Remove-Path $Venv
    Remove-Runtime
}
if ($Mode -eq 'all') {
    Remove-Path $Config
    Remove-Path $Data
    Remove-Path (Join-Path $Root 'lang.txt')
}
Say (Tr 'state_after')
Show-State
if ($Failed) { exit 1 }
Say (Tr 'done')
exit 0
