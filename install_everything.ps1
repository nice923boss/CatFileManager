# CatFileManager: install Everything and its command-line client es.exe (ES) so the
# "Everything 全電腦" search mode works. Opened by the search window's install button;
# safe to run again, steps that are already done are skipped.
# Saved as UTF-8 with BOM: Windows PowerShell 5.1 reads BOM-less scripts as ANSI.
# No $ErrorActionPreference = 'Stop': in 5.1 it turns native stderr into exceptions.

$DownloadPage = 'https://www.voidtools.com/zh-tw/downloads/'
$Host.UI.RawUI.WindowTitle = 'CatFileManager：安裝 Everything'

function Finish([bool]$ok, [string]$message) {
    Write-Host ''
    Write-Host $message -ForegroundColor $(if ($ok) { 'Green' } else { 'Yellow' })
    Read-Host '按 Enter 關閉視窗' | Out-Null
    exit $(if ($ok) { 0 } else { 1 })
}

function Find-Es {
    $local = $env:LOCALAPPDATA
    $paths = @(
        (Get-Command es.exe -ErrorAction SilentlyContinue).Source,
        "$env:ProgramFiles\Everything\es.exe",
        "${env:ProgramFiles(x86)}\Everything\es.exe",
        "$local\Programs\Everything\es.exe",
        "$local\Microsoft\WinGet\Links\es.exe"
    )
    $paths += Get-ChildItem "$local\Microsoft\WinGet\Packages\voidtools.Everything.Cli_*\es.exe" `
        -ErrorAction SilentlyContinue | ForEach-Object FullName
    $paths | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}

function Find-EverythingExe {
    @(
        "$env:ProgramFiles\Everything\Everything.exe",
        "$env:ProgramFiles\Everything 1.5a\Everything.exe",
        "${env:ProgramFiles(x86)}\Everything\Everything.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}

# Everything 1.4 / 1.5 beta answer as the default instance, 1.5 alpha as "1.5a".
function Test-EverythingRunning([string]$es) {
    foreach ($instance in @(@(), @('-instance', '1.5a'))) {
        & $es @instance -get-everything-version *> $null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

function Assert-Winget {
    if (Get-Command winget -ErrorAction SilentlyContinue) { return }
    Start-Process $DownloadPage
    Finish $false "找不到 winget（Windows 套件管理員），已開啟官網下載頁，請手動安裝 Everything 與 ES 命令列工具。"
}

Write-Host '=== CatFileManager：安裝 Everything 全電腦搜尋 ===' -ForegroundColor Cyan
Write-Host ''

$es = Find-Es
if (-not $es) {
    Assert-Winget
    Write-Host '安裝 ES 命令列工具 es.exe（winget：voidtools.Everything.Cli）…'
    # Its winget dependency is Everything 1.4; skip it so an existing 1.5 is not doubled.
    winget install -e --id voidtools.Everything.Cli --skip-dependencies `
        --accept-source-agreements --accept-package-agreements
    $es = Find-Es
    if (-not $es) { Finish $false "es.exe 安裝失敗，請看上方訊息，或到 $DownloadPage 手動下載。" }
}
Write-Host "es.exe：$es"

if (-not (Test-EverythingRunning $es)) {
    $exe = Find-EverythingExe
    if (-not $exe) {
        Assert-Winget
        Write-Host ''
        Write-Host '安裝 Everything（winget：voidtools.Everything），請在系統管理員確認視窗按「是」…'
        winget install -e --id voidtools.Everything --accept-source-agreements --accept-package-agreements
        $exe = Find-EverythingExe
        if (-not $exe) { Finish $false "Everything 安裝失敗，請看上方訊息，或到 $DownloadPage 手動下載。" }
    }
    Write-Host "啟動 Everything：$exe"
    Start-Process -FilePath $exe -ArgumentList '-startup'
    $ready = $false
    for ($i = 0; $i -lt 20 -and -not $ready; $i++) {
        Start-Sleep -Milliseconds 500
        $ready = Test-EverythingRunning $es
    }
    if (-not $ready) { Finish $false 'Everything 已啟動但還沒回應，稍候再回 CatFileManager 按「重新搜尋」。' }
}

Finish $true '完成！回到 CatFileManager 按「重新搜尋」即可。第一次安裝需要幾十秒建立索引，期間結果可能不完整。'
