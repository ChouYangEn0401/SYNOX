# claude-code.ps1 -- the installer's optional last step (setup/installer/synox.iss, task "claudecode").
# Installs Claude Code with Anthropic's official one-liner, the same line the setup wizard's one-click button runs
# (synox.wizard.logic.CLAUDE_INSTALL_PS):  irm https://claude.ai/install.ps1 | iex
# It goes into the user's own profile (%USERPROFILE%\.local\bin), never into the SYNOX folder; no admin needed.
# Never blocks the install: the installer ignores failures and says on its last page how to add it later.
# Exit codes: 0 = Claude Code is there (it already was, or it was just installed), 2 = install failed,
#             3 = timed out (no or slow internet). ASCII only on purpose (PowerShell 5.1 reads BOM-less files as ANSI).
param([int]$TimeoutSeconds = 900)

$ErrorActionPreference = 'Stop'

function Find-Claude {
    $cmd = Get-Command claude -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $exe = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
    if (Test-Path -LiteralPath $exe) { return $exe }
    return $null
}

if (Find-Claude) { exit 0 }

$job = Start-Job -ScriptBlock {
    # Windows PowerShell 5.1 on older Windows 10 may not offer TLS 1.2 by default.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072
    irm https://claude.ai/install.ps1 | iex
}
try {
    if (-not (Wait-Job -Job $job -Timeout $TimeoutSeconds)) {
        Stop-Job -Job $job
        Write-Output "Claude Code: no answer after $TimeoutSeconds seconds, skipped."
        exit 3
    }
    Receive-Job -Job $job -ErrorAction SilentlyContinue | Out-String | Write-Output
} catch {
    Write-Output "Claude Code: $($_.Exception.Message)"
} finally {
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
}

if (Find-Claude) { exit 0 }
exit 2
