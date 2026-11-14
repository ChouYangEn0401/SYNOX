# update.ps1 — Update.bat 叫的：把 SYNOX 更新到最新的正式版，或退回上一版（docs/adr/0023 決定 U4、U5、U8）。
# UTF-8 有 BOM、CRLF（PowerShell 5.1）。不要管理員；只動 SYNOX 資料夾裡的程式檔。
#
#   Update.bat                  查 → 給你看這版改了什麼 → 問一次 → 下載＋驗證 → 停 SYNOX → 換檔 → （相依變了才）重裝套件 → 開 SYNOX
#   Update.bat -Rollback        退回上一版（_previous\ 裡最新的那一份）
#   Update.bat -AllowUnsigned   這一版沒有簽章也換（只確認 HTTPS＋GitHub 發佈頁的 SHA256SUMS.txt；預設不換，照實說）
#   Update.bat -Yes             不再問（已經在別的地方確認過）
#
# 分工：下載、SHA256、Ed25519 簽章、安全解壓都在 Python（`synox update --prepare`，src/synox/update/prepare.py；
# PowerShell 5.1 沒有 Ed25519），用的是**現在裝著、已經信任的**那份程式碼；全部過了才寫 data\update\ready.json。
# 這支只做：停 SYNOX、搬檔、留舊版、重裝套件、檢查、開 SYNOX、出事自動退回。
# 永遠不動（$Keep，跟 prepare.py 的 KEEP 一樣）：config.json、data\、packs\、.venv\、runtime\、_previous\、lang.txt、
# installer-choices.json、.git。舊的程式檔整份搬到 _previous\<舊版本>-<時間>\，只留最近 2 份（決定 U8）。
# git clone 的不換檔：請 git pull；安裝程式（.exe）裝的：下載新的安裝程式。
param([switch]$Rollback, [switch]$AllowUnsigned, [switch]$Yes)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
$Previous = Join-Path $Root '_previous'
$UpdateDir = Join-Path $Root 'data\update'
$ReadyFile = Join-Path $UpdateDir 'ready.json'
$ResultFile = Join-Path $Root 'data\update_last.json'
$LogDir = Join-Path $Root 'data\logs'
$KeepCount = 2
$Keep = @('config.json', 'data', 'packs', '.venv', 'runtime', '_previous', 'lang.txt', 'installer-choices.json', '.git')

# 字：繁中＋英文（lang.txt 是 zh-* 用中文，其他語言用英文）。只有這支用，所以不放進 setup\lang\*.psd1。
$Messages = @{
    'zh' = @{
        title = 'SYNOX 更新'
        git = '你的 SYNOX 是用 git 裝的：自動更新不會蓋掉你的檔案。請：Stop.bat → git pull → Setup.bat。'
        exe = '你的 SYNOX 是用安裝程式裝的：請到發佈頁下載新的 SYNOX-Setup-<版本>.exe，裝在原本的位置。'
        no_venv = '找不到 .venv（SYNOX 還沒裝好）：先點兩下 Setup.bat。'
        checking = '問 GitHub 有沒有新版（只看）…'
        no_newer = '沒有要更新的。'
        ask = '要更新嗎？你的設定、資料、工具都不會動。輸入 Y 再按 Enter 開始（直接按 Enter＝先不要）'
        cancelled = '先不更新。'
        preparing = '下載並驗證新版（還不會動到現在的檔案）…'
        prepare_failed = '沒有更新（上面是原因）。現在的 SYNOX 沒有被動過。'
        stopping = '先關掉 SYNOX …'
        swapping = '換檔：舊版的程式檔搬到 {0}'
        swap_failed = '換檔失敗：{0}。已經把舊版搬回來。'
        packages = '這版的套件有變：重裝套件（要網路，可能要幾分鐘）…'
        packages_failed = '套件裝不起來。'
        verify_failed = '新版跑不起來（版本是 {0}，應該是 {1}）。'
        rolling_back = '自動退回 {0} …'
        updated = '✅ 已更新到 {0}。舊版留在 {1}（出問題可以 Update.bat -Rollback）。'
        starting = '重新打開 SYNOX …'
        rb_none = '沒有可以退回的舊版（_previous 是空的）。'
        rb_ask = '要退回 {0} 嗎？你的設定、資料、工具都不會動。輸入 Y 再按 Enter（直接按 Enter＝不要）'
        rb_done = '✅ 已經退回 {0}。'
        rb_failed = '退回失敗：{0}。請到 GitHub 開 issue，附上 data\logs\update.log。'
        failed = '更新失敗：{0}'
        log = '這次的紀錄在 {0}'
        press_enter = '按 Enter 關閉這個視窗'
    }
    'en' = @{
        title = 'SYNOX update'
        git = 'This SYNOX was installed with git: the updater will not overwrite your files. Run: Stop.bat, git pull, Setup.bat.'
        exe = 'This SYNOX was installed with the installer: download the new SYNOX-Setup-<version>.exe from the releases page and install it in the same place.'
        no_venv = '.venv not found (SYNOX is not set up yet): double-click Setup.bat first.'
        checking = 'Asking GitHub whether there is a new version (look only)...'
        no_newer = 'Nothing to update.'
        ask = 'Update now? Your settings, data and tools stay as they are. Type Y and press Enter (just Enter = not now)'
        cancelled = 'Not updating.'
        preparing = 'Downloading and checking the new version (your current files are not touched yet)...'
        prepare_failed = 'Not updated (reason above). Your current SYNOX was not changed.'
        stopping = 'Stopping SYNOX...'
        swapping = 'Swapping files: the old program files go to {0}'
        swap_failed = 'Swapping files failed: {0}. The old version was moved back.'
        packages = 'Packages changed in this version: reinstalling them (needs the internet, may take a few minutes)...'
        packages_failed = 'Could not install the packages.'
        verify_failed = 'The new version does not start (it says {0}, expected {1}).'
        rolling_back = 'Going back to {0} automatically...'
        updated = 'Updated to {0}. The old version is kept in {1} (Update.bat -Rollback if something is wrong).'
        starting = 'Starting SYNOX again...'
        rb_none = 'There is no older version to go back to (_previous is empty).'
        rb_ask = 'Go back to {0}? Your settings, data and tools stay as they are. Type Y and press Enter (just Enter = no)'
        rb_done = 'Back on {0}.'
        rb_failed = 'Going back failed: {0}. Please open a GitHub issue and attach data\logs\update.log.'
        failed = 'Update failed: {0}'
        log = 'Log of this run: {0}'
        press_enter = 'Press Enter to close this window'
    }
}
$LangFile = Join-Path $Root 'lang.txt'
$Lang = 'en'
try {
    if (Test-Path -LiteralPath $LangFile) {
        if ((Get-Content -LiteralPath $LangFile -Raw -Encoding UTF8).Trim() -like 'zh*') { $Lang = 'zh' }
    } elseif ((Get-UICulture).Name -like 'zh*') { $Lang = 'zh' }
} catch { }

function T([string]$Key) {
    $text = $Messages[$Lang][$Key]
    if (-not $text) { $text = $Messages['zh'][$Key] }
    if ($args.Count) { return ($text -f $args) }
    return $text
}

function Say([string]$Text) { Write-Host "[SYNOX] $Text" }

function Test-Interactive {
    try { return (-not [Console]::IsInputRedirected) } catch { return $true }
}

function Confirm-Step([string]$Question) {
    if ($Yes) { return $true }
    if (-not (Test-Interactive)) { return $false }          # 沒有人在看就不換
    $answer = "$(Read-Host $Question)".Trim()
    return ($answer -match '^[yY]')
}

function Get-Stamp { return (Get-Date -Format 'yyyyMMdd-HHmmss') }

function Get-InstalledVersion {
    try {
        $v = & $VenvPy -c "import synox; print(synox.__version__)" 2>$null
        return "$v".Trim()
    } catch { return '' }
}

function Stop-Synox {
    Say (T 'stopping')
    try { & $VenvPy -m synox -q stop | Out-Host } catch { }
    Start-Sleep -Seconds 3                                   # 讓 Windows 放開檔案
}

function Start-Synox {
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'config.json'))) { return }
    Say (T 'starting')
    try { Start-Process -FilePath (Join-Path $Root 'Start.bat') -WorkingDirectory $Root } catch { Say $_.Exception.Message }
}

function Move-ProgramFiles([string]$From, [string]$To) {
    # $From 底下除了 $Keep 以外的每一樣，搬到 $To（同一顆磁碟，只是改位置）。-contains 不分大小寫，跟 Windows 一樣。
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    foreach ($item in @(Get-ChildItem -LiteralPath $From -Force)) {
        if ($Keep -contains $item.Name) { continue }
        Move-Item -LiteralPath $item.FullName -Destination (Join-Path $To $item.Name)
    }
}

function Get-PreviousFolders {
    if (-not (Test-Path -LiteralPath $Previous)) { return @() }
    return @(Get-ChildItem -LiteralPath $Previous -Directory -Force | Where-Object { -not $_.Name.StartsWith('.') } |
             Sort-Object CreationTime -Descending)
}

function Limit-Previous {
    # 只留最近 $KeepCount 份（決定 U8）；.開頭的（退回時的暫存）不算
    foreach ($old in @(Get-PreviousFolders | Select-Object -Skip $KeepCount)) {
        Remove-Item -LiteralPath $old.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Install-Packages {
    # 跟 Setup.bat 同一套（bootstrap.ps1 -Update：只更新 .venv 的套件，不問問題、不開精靈）。用的是新版的 bootstrap.ps1
    Say (T 'packages')
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'setup\bootstrap.ps1') -Update | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Test-SameDeps([string]$Other) {
    # 現在的 SYNOX 資料夾跟 $Other 的套件需求一樣嗎？（prepare.py 的 deps_fingerprint；舊版沒有它＝當作不一樣）
    try {
        & $VenvPy -c "import sys; from synox.update.prepare import deps_fingerprint as f; sys.exit(0 if f(sys.argv[1]) == f(sys.argv[2]) else 1)" $Root $Other 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Save-Result([hashtable]$Data) {
    try {
        $Data['at'] = (Get-Date -Format 's')
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ResultFile) | Out-Null
        [IO.File]::WriteAllText($ResultFile, ($Data | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    } catch { }
}

function Restore-Previous {
    # _previous 裡最新的一份搬回來；現在的程式檔先放到 _previous\.replaced-<時間>（搬好才刪）。回傳退回到的資料夾名字（失敗丟例外）
    $latest = @(Get-PreviousFolders | Select-Object -First 1)
    if (-not $latest.Count) { throw (T 'rb_none') }
    $folder = $latest[0]
    $trash = Join-Path $Previous ('.replaced-' + (Get-Stamp))
    Move-ProgramFiles $Root $trash
    try {
        Move-ProgramFiles $folder.FullName $Root
    } catch {
        Move-ProgramFiles $Root (Join-Path $Previous ('.failed-' + (Get-Stamp)))
        Move-ProgramFiles $trash $Root
        throw
    }
    Remove-Item -LiteralPath $folder.FullName -Recurse -Force -ErrorAction SilentlyContinue
    if (-not (Test-SameDeps $trash)) {
        if (-not (Install-Packages)) { Say (T 'packages_failed') }
    }
    Remove-Item -LiteralPath $trash -Recurse -Force -ErrorAction SilentlyContinue
    return $folder.Name
}

function Invoke-Rollback {
    $latest = @(Get-PreviousFolders | Select-Object -First 1)
    if (-not $latest.Count) { Say (T 'rb_none'); return 1 }
    if (-not (Confirm-Step (T 'rb_ask' $latest[0].Name))) { Say (T 'cancelled'); return 0 }
    Stop-Synox
    try {
        $name = Restore-Previous
    } catch {
        Say (T 'rb_failed' $_.Exception.Message)
        return 1
    }
    $now = Get-InstalledVersion
    Save-Result @{ action = 'rollback'; to = $now; ok = $true }
    Say (T 'rb_done' "$now ($name)")
    Start-Synox
    return 0
}

function Invoke-Update {
    Say (T 'checking')
    & $VenvPy -m synox -q update --check | Out-Host
    if ($LASTEXITCODE -ne 10) { Say (T 'no_newer'); return 0 }     # 10＝有比較新的正式版（synox update --check 的結束碼）
    if (-not (Confirm-Step (T 'ask'))) { Say (T 'cancelled'); return 0 }

    Say (T 'preparing')
    $prep = @('-m', 'synox', '-q', 'update', '--prepare')
    if ($AllowUnsigned) { $prep += '--allow-unsigned' }
    & $VenvPy @prep | Out-Host
    $rc = $LASTEXITCODE
    if ($rc -eq 3) { Say (T 'no_newer'); return 0 }
    if ($rc -ne 0 -or -not (Test-Path -LiteralPath $ReadyFile)) { Say (T 'prepare_failed'); return 1 }
    $ready = Get-Content -LiteralPath $ReadyFile -Raw -Encoding UTF8 | ConvertFrom-Json
    Remove-Item -LiteralPath $ReadyFile -Force                # 用一次就丟：下次一定重新下載、重新驗
    $stage = "$($ready.stage)"
    $inside = $UpdateDir.TrimEnd('\') + '\'
    if (-not $stage.StartsWith($inside, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath (Join-Path $stage 'src\synox\__init__.py'))) {
        Say (T 'prepare_failed'); return 1                   # 暫存資料夾一定在 data\update\ 裡
    }

    Stop-Synox
    $prev = Join-Path $Previous ("$($ready.from)-" + (Get-Stamp))
    Say (T 'swapping' $prev)
    try {
        Move-ProgramFiles $Root $prev
    } catch {
        $why = $_.Exception.Message
        Move-ProgramFiles $prev $Root
        Remove-Item -LiteralPath $prev -Recurse -Force -ErrorAction SilentlyContinue
        Say (T 'swap_failed' $why)
        Start-Synox
        return 1
    }
    try {
        Move-ProgramFiles $stage $Root
    } catch {
        $why = $_.Exception.Message
        Move-ProgramFiles $Root (Join-Path $UpdateDir ('failed-' + (Get-Stamp)))
        Move-ProgramFiles $prev $Root
        Remove-Item -LiteralPath $prev -Recurse -Force -ErrorAction SilentlyContinue
        Say (T 'swap_failed' $why)
        Start-Synox
        return 1
    }
    Limit-Previous

    $ok = $true
    if ($ready.rebuild_venv) {
        if (-not (Install-Packages)) { Say (T 'packages_failed'); $ok = $false }
    }
    $now = Get-InstalledVersion
    if ($ok -and $now -ne "$($ready.version)") { Say (T 'verify_failed' $now $ready.version); $ok = $false }
    if (-not $ok) {
        Say (T 'rolling_back' $ready.from)
        try {
            Restore-Previous | Out-Null
            Save-Result @{ action = 'update'; from = "$($ready.from)"; to = "$($ready.version)"; ok = $false; rolled_back = $true }
        } catch {
            Say (T 'rb_failed' $_.Exception.Message)
            Save-Result @{ action = 'update'; from = "$($ready.from)"; to = "$($ready.version)"; ok = $false; rolled_back = $false }
        }
        Start-Synox
        return 1
    }
    Remove-Item -LiteralPath (Split-Path -Parent (Split-Path -Parent $stage)) -Recurse -Force -ErrorAction SilentlyContinue
    Save-Result @{ action = 'update'; from = "$($ready.from)"; to = "$($ready.version)"; ok = $true; signed = [bool]$ready.signed }
    Say (T 'updated' $ready.version $prev)
    Start-Synox
    return 0
}

$code = 1
$logging = $false
try {
    Write-Host ''
    Say (T 'title')
    if (Test-Path -LiteralPath (Join-Path $Root '.git')) { Say (T 'git'); exit 1 }
    try {
        $choices = Get-Content -LiteralPath (Join-Path $Root 'installer-choices.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($choices.source -eq 'exe-installer') { Say (T 'exe'); exit 1 }
    } catch { }
    if (-not (Test-Path -LiteralPath $VenvPy)) { Say (T 'no_venv'); exit 1 }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    try { Start-Transcript -LiteralPath (Join-Path $LogDir 'update.log') -Append | Out-Null; $logging = $true } catch { }
    if ($Rollback) { $code = Invoke-Rollback } else { $code = Invoke-Update }
} catch {
    Write-Host "[SYNOX] $(T 'failed' $_.Exception.Message)" -ForegroundColor Red
    $code = 1
} finally {
    if ($logging) {
        try { Stop-Transcript | Out-Null } catch { }
        Say (T 'log' (Join-Path $LogDir 'update.log'))
    }
}
# 失敗時 Update.bat 自己會 pause；成功時讓人看完再關
if ($code -eq 0 -and -not $Yes -and (Test-Interactive)) { Read-Host (T 'press_enter') | Out-Null }
exit $code
