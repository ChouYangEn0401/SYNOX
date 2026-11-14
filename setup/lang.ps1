# lang.ps1 - shared by bootstrap.ps1 and uninstall.ps1 (dot-sourced). UTF-8 with BOM.
# Picks the installer language and loads setup\lang\<code>.psd1 (zh-TW is the source text; other languages fall
# back to en, then zh-TW, for a missing key). The choice is saved in <SYNOX>\lang.txt, the same file the wizard uses
# (src/synox/wizard/i18n.py; keep the code list and order in sync with i18n.LANGS).
# The language prompt shows the latin name of each language next to its own name, so it stays readable in a legacy
# console whose font has no CJK / Arabic / Devanagari glyphs. Pressing Enter keeps the language saved in lang.txt
# (labelled "last choice"), or, when nothing is saved yet, the Windows display language (Get-UICulture; English when
# it is none of the 12).
# Setup.bat (bootstrap.ps1, -EveryTime) asks on EVERY run, before anything else is printed; Uninstall.bat asks only
# when nothing is saved. -Lang / SYNOX_LANG (automation, the .exe installer's "Setup.bat -Lang <code>") always win
# silently, and nothing is asked when input is redirected (no one is watching) or with -NoAsk (Update.bat's
# bootstrap.ps1 -Update).

$SynoxLangs = @('zh-TW', 'zh-CN', 'en', 'es', 'fr', 'de', 'pt-BR', 'ru', 'ar', 'hi', 'ja', 'ko')
$SynoxLangLabels = @{
    'zh-TW' = 'Traditional Chinese / 繁體中文'
    'zh-CN' = 'Simplified Chinese / 简体中文'
    'en'    = 'English'
    'es'    = 'Spanish / Español'
    'fr'    = 'French / Français'
    'de'    = 'German / Deutsch'
    'pt-BR' = 'Portuguese (Brazil) / Português (Brasil)'
    'ru'    = 'Russian / Русский'
    'ar'    = 'Arabic / العربية'
    'hi'    = 'Hindi / हिन्दी'
    'ja'    = 'Japanese / 日本語'
    'ko'    = 'Korean / 한국어'
}
$SynoxText = @{}

try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }   # no console (redirected): nothing to do
$OutputEncoding = [Text.Encoding]::UTF8

function ConvertTo-SynoxLang([string]$Value) {
    $s = "$Value".Trim().ToLower().Replace('_', '-')
    if (-not $s) { return '' }
    foreach ($c in $SynoxLangs) { if ($s -eq $c.ToLower()) { return $c } }
    $alias = @{ 'zh' = 'zh-TW'; 'tw' = 'zh-TW'; 'zh-hant' = 'zh-TW'; 'cn' = 'zh-CN'; 'zh-hans' = 'zh-CN'; 'pt' = 'pt-BR' }
    if ($alias.ContainsKey($s)) { return $alias[$s] }
    $base = $s.Split('-')[0]
    if ($base -ne 'zh' -and $SynoxLangs -contains $base) { return $base }
    return ''
}

function Read-SynoxLangFile([string]$Root) {
    $f = Join-Path $Root 'lang.txt'
    if (-not (Test-Path -LiteralPath $f)) { return '' }
    try { return (ConvertTo-SynoxLang (Get-Content -LiteralPath $f -Raw -Encoding UTF8)) } catch { return '' }
}

function Save-SynoxLang([string]$Root, [string]$Code) {
    try { [IO.File]::WriteAllText((Join-Path $Root 'lang.txt'), "$Code`n", [Text.Encoding]::ASCII) } catch { }
}

# Windows display language -> one of the 12 codes (zh-HK / zh-MO / zh-Hant -> zh-TW, other zh -> zh-CN, pt-* -> pt-BR,
# en-US -> en ...); English when Windows uses a language SYNOX does not have.
function ConvertTo-SynoxUiLang([string]$Name) {
    $s = "$Name".Trim().ToLower().Replace('_', '-')
    if ($s -match '^zh-(tw|hk|mo|hant)') { return 'zh-TW' }
    if ($s -match '^zh') { return 'zh-CN' }
    if ($s -match '^pt') { return 'pt-BR' }
    $c = ConvertTo-SynoxLang $s
    if ($c) { return $c }
    return 'en'
}

function Get-SynoxDisplayLang {
    $name = ''
    try { $name = (Get-UICulture).Name } catch { }
    return (ConvertTo-SynoxUiLang $name)
}

function Test-SynoxLangInteractive {
    # 輸入被導向（自動測試、沒有人在看）就不問
    try { return (-not [Console]::IsInputRedirected) } catch { return $true }
}

# $Saved: the code in lang.txt ('' = none). Enter keeps it ("last choice"); else the Windows display language.
function Ask-SynoxLang([string]$Saved = '') {
    $default = Get-SynoxDisplayLang
    $mark = ''
    if ($Saved) { $default = $Saved; $mark = ' （上次選的 / last choice）' }
    $defaultNo = [Array]::IndexOf($SynoxLangs, $default) + 1
    Write-Host ''
    Write-Host 'Language / 語言 / 语言 / Idioma / Langue / Sprache / Язык / اللغة / भाषा / 言語 / 언어'
    $half = [Math]::Ceiling($SynoxLangs.Count / 2)
    for ($i = 0; $i -lt $half; $i++) {
        $left = '{0,3}) {1}' -f ($i + 1), $SynoxLangLabels[$SynoxLangs[$i]]
        $j = $i + $half
        $right = if ($j -lt $SynoxLangs.Count) { '{0,3}) {1}' -f ($j + 1), $SynoxLangLabels[$SynoxLangs[$j]] } else { '' }
        Write-Host ('  {0,-44} {1}' -f $left, $right)
    }
    while ($true) {
        $a = "$(Read-Host "Number or code, Enter = $defaultNo ($($SynoxLangLabels[$default]))$mark")".Trim()
        if (-not $a) { return $default }
        $n = 0
        if ([int]::TryParse($a, [ref]$n) -and $n -ge 1 -and $n -le $SynoxLangs.Count) { return $SynoxLangs[$n - 1] }
        $c = ConvertTo-SynoxLang $a
        if ($c) { return $c }
    }
}

# -Lang / SYNOX_LANG win silently. Otherwise:
#   -EveryTime (Setup.bat): always ask, Enter = lang.txt's language (if any), else the Windows display language;
#   default (Uninstall.bat): lang.txt if there is one, else ask.
# Never asks when input is redirected or with -NoAsk: lang.txt, else the Windows display language.
# The answer is saved in lang.txt. Returns the code.
function Resolve-SynoxLang([string]$Root, [string]$Override, [switch]$SaveOverride, [switch]$EveryTime, [switch]$NoAsk) {
    $code = ConvertTo-SynoxLang $Override
    if (-not $code) { $code = ConvertTo-SynoxLang $env:SYNOX_LANG }
    if ($code) {
        if ($SaveOverride) { Save-SynoxLang $Root $code }
        return $code
    }
    $saved = Read-SynoxLangFile $Root
    if ($saved -and -not $EveryTime) { return $saved }
    if ($NoAsk -or -not (Test-SynoxLangInteractive)) {
        if ($saved) { return $saved }
        return (Get-SynoxDisplayLang)
    }
    $code = Ask-SynoxLang $saved
    Save-SynoxLang $Root $code
    return $code
}

function Import-SynoxText([string]$Code) {
    $dir = Join-Path $PSScriptRoot 'lang'
    $chain = @('zh-TW')
    if ($Code -ne 'zh-TW') { $chain += @('en', $Code) }
    $script:SynoxText = @{}
    foreach ($c in $chain) {
        $f = Join-Path $dir "$c.psd1"
        if (-not (Test-Path -LiteralPath $f)) { continue }
        try {
            $d = Import-PowerShellDataFile -LiteralPath $f
            foreach ($k in $d.Keys) { $script:SynoxText[$k] = $d[$k] }
        } catch { }
    }
}

# Tr 'removed' $path  ->  the message in the chosen language, with {0}, {1} filled in.
function Tr([string]$Key) {
    $text = $script:SynoxText[$Key]
    if ($null -eq $text) { $text = $Key }
    if ($args.Count) { return ($text -f $args) }
    return $text
}
