[CmdletBinding()]
param(
    [string]$Repository = "tylergao11/Ultra-Board",
    [string]$Tag = "research-store-current",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -lt 6) {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
}

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$storeDir = Join-Path $root "data/store"
$databasePath = Join-Path $storeDir "research.sqlite"
$baseUrl = "https://github.com/$Repository/releases/download/$Tag"
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("ultra-board-setup-" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($tempDir) | Out-Null

try {
    $manifestPath = Join-Path $tempDir "database_release_manifest.json"
    Invoke-WebRequest -Uri "$baseUrl/database_release_manifest.json" -OutFile $manifestPath -UseBasicParsing
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expectedHash = ([string]$manifest.sha256).ToLowerInvariant()
    $expectedSize = [int64]$manifest.size_bytes
    $needsDownload = $true

    if (Test-Path -LiteralPath $databasePath) {
        $currentHash = (Get-FileHash -LiteralPath $databasePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($currentHash -eq $expectedHash) {
            Write-Host "数据库已是 GitHub 当前版本：$currentHash"
            $needsDownload = $false
        }
        elseif (-not $Force) {
            throw "本地数据库与 GitHub 快照不同。请先处理本地研究，或使用 -Force 覆盖并自动保留本机备份。"
        }
    }

    if ($needsDownload) {
        $downloadPath = Join-Path $tempDir "research.sqlite.download"
        Write-Host "正在从 GitHub 下载研究库（$expectedSize 字节）..."
        Invoke-WebRequest -Uri "$baseUrl/research.sqlite" -OutFile $downloadPath -UseBasicParsing
        $actualSize = (Get-Item -LiteralPath $downloadPath).Length
        $actualHash = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSize -ne $expectedSize -or $actualHash -ne $expectedHash) {
            throw "下载校验失败：size=$actualSize sha256=$actualHash"
        }
        [System.IO.Directory]::CreateDirectory($storeDir) | Out-Null
        if (Test-Path -LiteralPath $databasePath) {
            $backupDir = Join-Path $storeDir "local-backups"
            [System.IO.Directory]::CreateDirectory($backupDir) | Out-Null
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupPath = Join-Path $backupDir "research-before-setup-$stamp.sqlite"
            [System.IO.File]::Move($databasePath, $backupPath)
            Write-Host "原数据库已移动到：$backupPath"
        }
        [System.IO.File]::Move($downloadPath, $databasePath)
        Write-Host "研究库已安装：$databasePath"
    }

    $python = Get-Command python -ErrorAction Stop
    & $python.Source -B (Join-Path $root "tools/research_cli.py") summary
    if ($LASTEXITCODE -ne 0) {
        throw "研究库摘要检查失败。"
    }
}
finally {
    if (Test-Path -LiteralPath $tempDir) {
        [System.IO.Directory]::Delete($tempDir, $true)
    }
}
