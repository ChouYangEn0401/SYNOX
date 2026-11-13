# SYNOX research probe (stage 3, part B) -- READ-ONLY inventory of what this Windows PC can use as a sandbox.
# STATUS: written on Linux, never run on Windows. It changes nothing: no installs, no feature toggles, no network.
# Run in a normal (non-admin) PowerShell:   powershell -ExecutionPolicy Bypass -File .\win-env-probe.ps1
# Output: a table on screen + win-env-probe-result.json next to this script (review before sharing: it has no
# user names or paths except the install paths of node/python/docker).

$ErrorActionPreference = 'SilentlyContinue'
$r = [ordered]@{}

$cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
$build = [int]$cv.CurrentBuildNumber
$ubr = [int]$cv.UBR
$r.EditionID      = $cv.EditionID            # Core = Home, Professional, Enterprise, Education ...
$r.DisplayVersion = $cv.DisplayVersion       # 22H2, 24H2, 25H2 ...
$r.Build          = "$build.$ubr"
$r.IsWindows11    = ($build -ge 22000)
$r.Arch           = $env:PROCESSOR_ARCHITECTURE
$r.IsAdminShell   = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

$cs  = Get-CimInstance Win32_ComputerSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$r.RAM_GB                 = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$r.HypervisorPresent      = $cs.HypervisorPresent                 # True = a hypervisor (Hyper-V/WSL2 platform) is already running
$r.VirtualizationFirmware = $cpu.VirtualizationFirmwareEnabled    # reads False when HypervisorPresent is True (normal)
$r.SLAT                   = $cpu.SecondLevelAddressTranslationExtensions

# Tools on PATH (path + version; "docker --version" is the client only, it does not start or contact the engine)
foreach ($t in 'node', 'npm', 'npx', 'python', 'py', 'git', 'docker', 'podman', 'wsl', 'curl', 'winget') {
    $c = Get-Command $t -CommandType Application | Select-Object -First 1
    $r["path_$t"] = if ($c) { $c.Source } else { $null }
}
if ($r.path_node)   { $r.node_version   = (& node --version) 2>$null }
if ($r.path_npm)    { $r.npm_version    = (& npm --version) 2>$null }
if ($r.path_docker) { $r.docker_version = (& docker --version) 2>$null }
if ($r.path_podman) { $r.podman_version = (& podman --version) 2>$null }
if ($r.path_wsl)    { $r.wsl_version    = ((& wsl --version) 2>$null | Select-Object -First 1) -replace "`0", '' }

# Where node/python live decides whether an AppContainer or a separate sandbox user can read them
$r.node_under_program_files   = [bool]($r.path_node -and $r.path_node.StartsWith($env:ProgramFiles, 'OrdinalIgnoreCase'))
$r.python_under_program_files = [bool]($r.path_python -and $r.path_python.StartsWith($env:ProgramFiles, 'OrdinalIgnoreCase'))
$r.python_is_store_alias      = [bool]($r.path_python -and $r.path_python -like '*\WindowsApps\*')

# Windows Sandbox (Pro/Enterprise/Education only): present = the optional feature is already enabled
$r.WindowsSandbox_exe = Test-Path "$env:WINDIR\System32\WindowsSandbox.exe"
$r.wsb_cli            = [bool](Get-Command wsb -CommandType Application)

# Docker Desktop install markers (per-user and all-users locations from Docker's install page)
$r.DockerDesktop_per_user  = Test-Path "$env:LOCALAPPDATA\Programs\DockerDesktop"
$r.DockerDesktop_all_users = Test-Path "$env:ProgramFiles\Docker\Docker"

# MXC ProcessContainer baseline (microsoft/mxc docs/backends/process-container/os-version-support.md, read 2026-11-13)
$need = @{ 26100 = 9278; 26200 = 9278; 26300 = 9550; 28000 = 2804 }
$r.MXC_process_isolation_build_ok = [bool]($need.ContainsKey($build) -and $ubr -ge $need[$build])

# AppContainer APIs exist on every Windows 8+; CheckNetIsolation is the (admin) loopback-exemption tool
$r.CheckNetIsolation_exe = Test-Path "$env:WINDIR\System32\CheckNetIsolation.exe"

$r.GetEnumerator() | ForEach-Object { '{0,-32} {1}' -f $_.Key, $_.Value }
$outFile = Join-Path $PSScriptRoot 'win-env-probe-result.json'
$r | ConvertTo-Json | Set-Content -Encoding UTF8 $outFile
"`nresult file: $outFile"
