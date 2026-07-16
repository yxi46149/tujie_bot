[CmdletBinding()]
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content -LiteralPath (Join-Path $ProjectRoot "VERSION") -Raw).Trim()
}
if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]*$') {
    throw "版本号只能包含字母、数字、点、下划线和连字符。"
}

$DistDirectory = Join-Path $ProjectRoot "dist"
$ArchivePath = Join-Path $DistDirectory "tujie_bot-v$Version.zip"
$ResolvedProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$ResolvedDistDirectory = [IO.Path]::GetFullPath($DistDirectory)
$ResolvedArchivePath = [IO.Path]::GetFullPath($ArchivePath)

if (-not $ResolvedDistDirectory.StartsWith($ResolvedProjectRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "拒绝在项目目录外创建发布文件。"
}
if (-not $ResolvedArchivePath.StartsWith($ResolvedDistDirectory, [StringComparison]::OrdinalIgnoreCase)) {
    throw "发布文件路径不安全。"
}

New-Item -ItemType Directory -Path $ResolvedDistDirectory -Force | Out-Null
if (Test-Path -LiteralPath $ResolvedArchivePath) {
    Remove-Item -LiteralPath $ResolvedArchivePath -Force
}

$RelativeItems = @(
    "app",
    "deploy",
    "docs",
    "scripts",
    "tests",
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "compose.yaml",
    "Dockerfile",
    "README.md",
    "requirements.txt",
    "VERSION"
)
$Items = foreach ($RelativeItem in $RelativeItems) {
    $ItemPath = Join-Path $ProjectRoot $RelativeItem
    if (-not (Test-Path -LiteralPath $ItemPath)) {
        throw "缺少打包文件：$RelativeItem"
    }
    Get-Item -LiteralPath $ItemPath -Force
}

$Files = foreach ($Item in $Items) {
    if ($Item.PSIsContainer) {
        Get-ChildItem -LiteralPath $Item.FullName -Recurse -File -Force
    }
    else {
        $Item
    }
}
$Files = $Files | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
    $_.Extension -notin @('.pyc', '.pyo')
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$RootWithSeparator = $ResolvedProjectRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
$RootUri = [Uri]$RootWithSeparator
$Archive = [IO.Compression.ZipFile]::Open(
    $ResolvedArchivePath,
    [IO.Compression.ZipArchiveMode]::Create
)
try {
    foreach ($File in $Files) {
        $RelativePath = [Uri]::UnescapeDataString(
            $RootUri.MakeRelativeUri([Uri]$File.FullName).ToString()
        )
        $EntryName = "tujie_bot/" + $RelativePath.Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $Archive,
            $File.FullName,
            $EntryName,
            [IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $Archive.Dispose()
}
$Hash = Get-FileHash -LiteralPath $ResolvedArchivePath -Algorithm SHA256

Write-Output "打包完成：$ResolvedArchivePath"
Write-Output "SHA256：$($Hash.Hash)"
Write-Output "已排除 .env、数据库、日志、虚拟环境和 Git 历史。"
