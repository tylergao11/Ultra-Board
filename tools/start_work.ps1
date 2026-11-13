[CmdletBinding()]
param(
    [switch]$Sync,
    [ValidateRange(0, 10)]
    [int]$KeepLocalBackups = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $root
try {
    if (-not $Sync) {
        if (-not (Test-Path -LiteralPath (Join-Path $root "data/store/research.sqlite") -PathType Leaf)) {
            throw "本机研究库缺失。新电脑启用请运行 tools/setup_home.ps1。"
        }
        Write-Host "使用本机研究库，可以继续研究。GitHub 同步需显式指定 -Sync。"
        return
    }
    $status = @(git -c core.quotepath=false status --porcelain=v1)
    if ($LASTEXITCODE -ne 0) {
        throw "读取 Git 工作区状态失败。"
    }
    if ($status.Count -gt 0) {
        throw "工作区已有本地改动。请先保留并处理这些改动，再同步另一台电脑的内容。"
    }

    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub 拉取失败或分支需要人工处理。"
    }

    & (Join-Path $PSScriptRoot "setup_home.ps1") -Force -KeepLocalBackups $KeepLocalBackups
    if ($LASTEXITCODE -ne 0) {
        throw "安装 GitHub 当前数据库失败。"
    }

    Write-Host "Ultra-Board 已同步，可以开始本次工作。"
}
finally {
    Pop-Location
}
