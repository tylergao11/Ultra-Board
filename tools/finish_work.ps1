[CmdletBinding()]
param(
    [string]$Message = "同步 Ultra-Board 工作结果",
    [switch]$Sync
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$python = Get-Command python -ErrorAction Stop

Push-Location $root
try {
    & $python.Source -B tools/research_cli.py sync-rules
    if ($LASTEXITCODE -ne 0) {
        throw "当前规则同步失败。"
    }
    & $python.Source -B tools/research_cli.py temp-clean
    if ($LASTEXITCODE -ne 0) {
        throw "临时文件清理检查失败。"
    }

    & $python.Source -B tools/research_cli.py summary *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "正式数据库摘要检查失败。"
    }

    if ($Sync) {
        & (Join-Path $PSScriptRoot "sync_github.ps1") -Message $Message -PublishDatabase
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub 交接失败。"
        }
    }
    else {
        Write-Host "本地检查完成，研究结果已保存在本机。GitHub 同步需显式指定 -Sync。"
    }
}
finally {
    Pop-Location
}
