[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Message,
    [switch]$PublishDatabase
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1

Push-Location $root
try {
    & $python.Source -B tools/research_cli.py summary *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "正式数据库摘要检查失败。"
    }

    $upstream = (git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null)
    if ($LASTEXITCODE -eq 0 -and $upstream) {
        git fetch --quiet
        if ($LASTEXITCODE -ne 0) {
            throw "同步前检查远端分支失败（git fetch 异常），已中止推送。"
        }
        $behindCount = [int]((git rev-list --count "HEAD..$upstream").Trim())
        if ($behindCount -gt 0) {
            throw "远端分支 $upstream 已领先本机 $behindCount 个提交（疑似另一台电脑已更新但本机未先同步），已中止提交与数据库发布！请先处理本机改动并同步远端结果。"
        }
    }

    git add -A
    if ($LASTEXITCODE -ne 0) {
        throw "Git 暂存失败。"
    }

    $oversized = @()
    $stagedFiles = git -c core.quotepath=false diff --cached --name-only --diff-filter=ACMR
    foreach ($relative in $stagedFiles) {
        $candidate = Join-Path $root $relative
        if ((Test-Path -LiteralPath $candidate) -and (Get-Item -LiteralPath $candidate).Length -ge 100MB) {
            $oversized += $relative
        }
    }
    if ($oversized.Count -gt 0) {
        throw "暂存区含有超过 100 MiB 的普通 Git 文件：$($oversized -join ', ')"
    }

    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit -m $Message
        if ($LASTEXITCODE -ne 0) {
            throw "Git 提交失败。"
        }
    }
    else {
        Write-Host "没有需要提交的普通 Git 变更。"
    }

    git push
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub 推送失败。"
    }

    if ($PublishDatabase) {
        & (Join-Path $PSScriptRoot "publish_database_release.ps1")
    }
}
finally {
    Pop-Location
}
