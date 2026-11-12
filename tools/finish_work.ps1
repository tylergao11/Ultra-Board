[CmdletBinding()]
param(
    [string]$Message = "同步 Ultra-Board 工作结果"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Get-Command python -ErrorAction Stop

Push-Location $root
try {
    $status = @(git -c core.quotepath=false status --porcelain=v1)
    if ($LASTEXITCODE -ne 0) {
        throw "读取 Git 工作区状态失败。"
    }
    $ruleChanges = @($status | Where-Object {
        $path = if ($_.Length -gt 3) { $_.Substring(3) } else { "" }
        $path -eq "AGENTS.md" -or $path.StartsWith("data/store/rules/")
    })
    $dataOrRuleChanges = @($status | Where-Object {
        $path = if ($_.Length -gt 3) { $_.Substring(3) } else { "" }
        $path -eq "AGENTS.md" -or
        $path -eq "一字首开研究总表.json" -or
        $path -eq "一字首开买卖研究表.json" -or
        $path -eq "tools/research_cli.py" -or
        $path.StartsWith("tools/research/") -or
        $path.StartsWith("data/")
    })

    if ($ruleChanges.Count -gt 0) {
        & $python.Source -B tools/research_cli.py sync-rules
        if ($LASTEXITCODE -ne 0) {
            throw "规则版本同步失败。"
        }
        & $python.Source -B tools/research_cli.py refresh-evidence
        if ($LASTEXITCODE -ne 0) {
            throw "规则证据登记失败。"
        }
    }

    if ($dataOrRuleChanges.Count -gt 0) {
        & $python.Source -B tools/research_cli.py maintain --keep-backups 3
        if ($LASTEXITCODE -ne 0) {
            throw "统一研究库维护或核验失败。"
        }
    }
    else {
        & $python.Source -B tools/research_cli.py summary *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "正式数据库摘要检查失败。"
        }
    }

    & (Join-Path $PSScriptRoot "sync_github.ps1") -Message $Message -PublishDatabase
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub 交接失败。"
    }
}
finally {
    Pop-Location
}
