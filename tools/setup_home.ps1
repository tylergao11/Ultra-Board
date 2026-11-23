[CmdletBinding()]
param(
    [string]$Repository = "tylergao11/Ultra-Board",
    [string]$Tag = "research-store-current",
    [switch]$Force,
    [ValidateRange(0, 10)]
    [int]$KeepLocalBackups = 1
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
$python = Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1
$temporary = & $python.Source -B (Join-Path $root "tools/research_cli.py") temp-new --purpose setup --owner-pid $PID --file database_release_manifest.json --file research.sqlite.download | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "创建启用临时目录失败。" }
$tempDir = $temporary.path

try {
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $manifestPath = Join-Path $tempDir "database_release_manifest.json"
    if ($curl) {
        & $curl.Source -fsSL --connect-timeout 20 --retry 3 --retry-all-errors -o $manifestPath "$baseUrl/database_release_manifest.json"
        if ($LASTEXITCODE -ne 0) {
            throw "下载数据库清单失败（curl exit $LASTEXITCODE）。"
        }
    }
    else {
        Invoke-WebRequest -Uri "$baseUrl/database_release_manifest.json" -OutFile $manifestPath -UseBasicParsing
    }
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
            throw "本地数据库与 GitHub 快照不同。请先处理本地研究；确认覆盖时使用 -Force，需要保留副本时另传 -KeepLocalBackups。"
        }
    }

    if ($needsDownload) {
        $downloadPath = Join-Path $tempDir "research.sqlite.download"
        Write-Host "正在从 GitHub 下载研究库（$expectedSize 字节）..."
        if ($curl) {
            $maxAttempts = 6
            for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
                $existingBytes = if (Test-Path -LiteralPath $downloadPath) { (Get-Item -LiteralPath $downloadPath).Length } else { 0 }
                if ($existingBytes -gt $expectedSize) {
                    [System.IO.File]::Delete($downloadPath)
                    $existingBytes = 0
                }
                if ($existingBytes -eq $expectedSize) {
                    break
                }
                if ($attempt -gt 1) {
                    Write-Host "断点续传第 $attempt/$maxAttempts 次（已下载 $existingBytes / $expectedSize 字节）..."
                    Start-Sleep -Seconds 2
                }
                $ErrorActionPreference = "Continue"
                if ($existingBytes -gt 0) {
                    & $curl.Source -fsSL --connect-timeout 20 --speed-time 30 --speed-limit 10240 -C - -o $downloadPath "$baseUrl/research.sqlite"
                }
                else {
                    & $curl.Source -fsSL --connect-timeout 20 --speed-time 30 --speed-limit 10240 -o $downloadPath "$baseUrl/research.sqlite"
                }
                $curlExit = $LASTEXITCODE
                $ErrorActionPreference = "Stop"
                if ($curlExit -eq 0 -and (Test-Path -LiteralPath $downloadPath) -and (Get-Item -LiteralPath $downloadPath).Length -eq $expectedSize) {
                    break
                }
                if ($attempt -eq $maxAttempts) {
                    throw "研究库下载在 $maxAttempts 次尝试后仍未完成（curl exit $curlExit）。"
                }
            }
        }
        else {
            Invoke-WebRequest -Uri "$baseUrl/research.sqlite" -OutFile $downloadPath -UseBasicParsing
        }
        $actualSize = (Get-Item -LiteralPath $downloadPath).Length
        $actualHash = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSize -ne $expectedSize -or $actualHash -ne $expectedHash) {
            throw "下载校验失败：size=$actualSize sha256=$actualHash"
        }
        [System.IO.Directory]::CreateDirectory($storeDir) | Out-Null
        if ((Test-Path -LiteralPath $databasePath) -and $KeepLocalBackups -gt 0) {
            $backupDir = Join-Path $storeDir "local-backups"
            [System.IO.Directory]::CreateDirectory($backupDir) | Out-Null
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupPath = Join-Path $backupDir "research-before-setup-$stamp.sqlite"
            [System.IO.File]::Move($databasePath, $backupPath)
            Write-Host "原数据库已移动到：$backupPath"
            $oldBackups = @(Get-ChildItem -LiteralPath $backupDir -File -Filter "research-before-setup-*.sqlite" |
                Sort-Object LastWriteTime -Descending |
                Select-Object -Skip $KeepLocalBackups)
            foreach ($oldBackup in $oldBackups) {
                if ($oldBackup.DirectoryName -ne $backupDir) {
                    throw "本机备份路径异常：$($oldBackup.FullName)"
                }
                [System.IO.File]::Delete($oldBackup.FullName)
            }
        }
        if (Test-Path -LiteralPath $databasePath) {
            [System.IO.File]::Replace($downloadPath, $databasePath, [System.Management.Automation.Language.NullString]::Value)
        }
        else {
            [System.IO.File]::Move($downloadPath, $databasePath)
        }
        Write-Host "研究库已安装：$databasePath"
    }

    & $python.Source -B (Join-Path $root "tools/research_cli.py") summary
    if ($LASTEXITCODE -ne 0) {
        throw "研究库摘要检查失败。"
    }
}
finally {
    & $python.Source -B (Join-Path $root "tools/research_cli.py") temp-clean --id $temporary.id --owner-pid $PID
}
