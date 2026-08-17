param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..\.." )).Path,
    [string]$Version = "20260814-intranet-v1"
)

$ErrorActionPreference = "Stop"
$dockerDir = Join-Path $ProjectDir "deploy\docker"
$artifactDir = Join-Path $dockerDir "artifacts"
$archiveName = "due-diligence-assistant-${Version}.image.tar"
$imageArchive = Join-Path $artifactDir $archiveName
$releaseName = "due-diligence-assistant-${Version}-release.zip"
$releaseArchive = Join-Path $artifactDir $releaseName
$releaseChecksum = Join-Path $artifactDir "${releaseName}.sha256"
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $ProjectDir "release"))
$staging = [IO.Path]::GetFullPath((Join-Path $releaseRoot ".docker-release-${Version}"))

if (-not $staging.StartsWith($releaseRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Invalid staging path: $staging"
}
if (-not (Test-Path $imageArchive -PathType Leaf)) {
    throw "Missing image archive: $imageArchive"
}

if (Test-Path $staging) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$files = @(
    "docker-compose.yml",
    "release.sh",
    ".env.intranet.example",
    ".env.release.example",
    "README.md",
    "RELEASE-GUIDE.md"
)
foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $dockerDir $file) -Destination $staging
}
Copy-Item -LiteralPath (Join-Path $dockerDir "scripts\verify.sh") -Destination (Join-Path $staging "verify.sh")
Copy-Item -LiteralPath $imageArchive -Destination $staging

$imageHash = (Get-FileHash -Algorithm SHA256 $imageArchive).Hash.ToLower()
"${imageHash}  ${archiveName}" |
    Set-Content -Encoding ascii (Join-Path $staging "SHA256SUMS")

if (Test-Path $releaseArchive) {
    Remove-Item -LiteralPath $releaseArchive -Force
}
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $releaseArchive -CompressionLevel Optimal

$releaseHash = (Get-FileHash -Algorithm SHA256 $releaseArchive).Hash.ToLower()
"${releaseHash}  ${releaseName}" | Set-Content -Encoding ascii $releaseChecksum
Remove-Item -LiteralPath $staging -Recurse -Force

Write-Host "Release archive: $releaseArchive"
Write-Host "Checksum: $releaseChecksum"
