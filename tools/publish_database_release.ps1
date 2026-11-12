[CmdletBinding()]
param(
    [string]$Repository = "tylergao11/Ultra-Board",
    [string]$Tag = "research-store-current"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$databasePath = Join-Path $root "data/store/research.sqlite"
$currentPointerPath = Join-Path $root "data/store/exports/current.json"

if (-not (Test-Path -LiteralPath $databasePath)) {
    throw "正式数据库不存在：$databasePath"
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "需要安装 GitHub CLI：https://cli.github.com/"
}

$python = Get-Command python -ErrorAction Stop
$summaryText = & $python.Source -B (Join-Path $root "tools/research_cli.py") summary | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "正式数据库摘要检查失败。"
}
$summary = $summaryText | ConvertFrom-Json
$hash = (Get-FileHash -LiteralPath $databasePath -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item -LiteralPath $databasePath).Length
$logicalSnapshot = $null
$generationKey = $null
if (Test-Path -LiteralPath $currentPointerPath) {
    $pointer = Get-Content -LiteralPath $currentPointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $generationKey = $pointer.generation_key
    $manifestPath = Join-Path $root $pointer.manifest
    if (Test-Path -LiteralPath $manifestPath) {
        $exportManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $logicalSnapshot = $exportManifest.database_snapshot
    }
}

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("ultra-board-release-" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($tempDir) | Out-Null
$addedToken = $false

try {
    $checksumPath = Join-Path $tempDir "research.sqlite.sha256"
    [System.IO.File]::WriteAllText($checksumPath, "$hash  research.sqlite`n", [System.Text.UTF8Encoding]::new($false))
    $releaseManifestPath = Join-Path $tempDir "database_release_manifest.json"
    $releaseManifest = [ordered]@{
        schema_version = 1
        created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        repository = $Repository
        tag = $Tag
        asset = "research.sqlite"
        sha256 = $hash
        size_bytes = $size
        current_batch = $summary.current_batch
        generation_key = $generationKey
        logical_snapshot = $logicalSnapshot
        rules = $summary.rules
        tables = $summary.tables
    }
    [System.IO.File]::WriteAllText(
        $releaseManifestPath,
        (($releaseManifest | ConvertTo-Json -Depth 8) + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )

    if (-not $env:GH_TOKEN) {
        $credentialRequest = @("protocol=https", "host=github.com", "") -join "`n"
        $credentialResult = $credentialRequest | git credential fill 2>$null
        $passwordLine = $credentialResult | Where-Object { $_ -like "password=*" } | Select-Object -First 1
        if (-not $passwordLine) {
            throw "GitHub CLI 尚未登录，Git Credential Manager 中也没有可复用凭据。请先运行 gh auth login。"
        }
        $env:GH_TOKEN = $passwordLine.Substring(9)
        $addedToken = $true
    }

    $releaseExists = $true
    $savedErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & gh release view $Tag --repo $Repository 2>$null | Out-Null
    $releaseViewExitCode = $LASTEXITCODE
    $ErrorActionPreference = $savedErrorActionPreference
    if ($releaseViewExitCode -ne 0) {
        $releaseExists = $false
    }
    $databaseUploadRequired = $true
    if ($releaseExists) {
        $releaseInfo = (& gh release view $Tag --repo $Repository --json assets | Out-String) | ConvertFrom-Json
        $databaseAsset = $releaseInfo.assets | Where-Object { $_.name -eq "research.sqlite" } | Select-Object -First 1
        if ($databaseAsset -and $databaseAsset.size -eq $size -and $databaseAsset.digest -eq "sha256:$hash") {
            $databaseUploadRequired = $false
        }
    }
    $notes = @"
Ultra-Board 当前正式研究数据库。

- 生成时间：$($releaseManifest.created_at)
- 数据库 SHA-256：$hash
- 逻辑快照：$logicalSnapshot
- 当前生成批次：$generationKey

下载后运行 tools/setup_home.ps1 自动校验和安装。
"@
    if ($releaseExists) {
        $head = (git -C $root rev-parse HEAD).Trim()
        & gh api --method PATCH "repos/$Repository/git/refs/tags/$Tag" -f "sha=$head" -F "force=true" *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "更新滚动 Release 标签失败。"
        }
        & gh release edit $Tag --repo $Repository --title "研究数据库当前快照" --notes $notes --latest
    }
    else {
        $branch = (git -C $root branch --show-current).Trim()
        & gh release create $Tag --repo $Repository --target $branch --title "研究数据库当前快照" --notes $notes --latest
    }
    if ($LASTEXITCODE -ne 0) {
        throw "创建或更新 GitHub Release 失败。"
    }

    $uploadFiles = @($checksumPath, $releaseManifestPath)
    if ($databaseUploadRequired) {
        $uploadFiles = @($databasePath) + $uploadFiles
    }
    else {
        Write-Host "远端数据库 digest 已一致，跳过 403 MB 重复上传。"
    }
    $uploadArguments = @("release", "upload", $Tag) + $uploadFiles + @("--repo", $Repository, "--clobber")
    & gh @uploadArguments
    if ($LASTEXITCODE -ne 0) {
        throw "上传数据库 Release 资产失败。"
    }
    Write-Host "数据库快照已发布：https://github.com/$Repository/releases/tag/$Tag"
    Write-Host "SHA-256：$hash"
}
finally {
    if ($addedToken) {
        Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $tempDir) {
        [System.IO.Directory]::Delete($tempDir, $true)
    }
}
