param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..\.." )).Path,
    [string]$Version = "20260814-intranet-v1",
    [string]$Repository = "docker.io/library/due-diligence-assistant",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$image = "${Repository}:${Version}"
$artifactDir = Join-Path $ProjectDir "deploy\docker\artifacts"
$archiveName = "due-diligence-assistant-${Version}.image.tar"
$archive = Join-Path $artifactDir $archiveName

if (-not (Test-Path (Join-Path $ProjectDir "frontend\dist\index.html"))) {
    throw "Missing frontend/dist/index.html. Build the frontend first."
}
if (-not (Test-Path (Join-Path $ProjectDir "deploy\docker\wheelhouse") -PathType Container)) {
    throw "Missing deploy/docker/wheelhouse."
}
$wheelhouseDir = Join-Path $ProjectDir "deploy\docker\wheelhouse"
$wheelChecksumFile = Join-Path $ProjectDir "deploy\docker\WHEELHOUSE-SHA256SUMS"
if (-not (Test-Path $wheelChecksumFile -PathType Leaf)) { throw "Missing wheelhouse checksum file." }
Push-Location $wheelhouseDir
try {
    Get-Content $wheelChecksumFile | ForEach-Object {
        if ($_ -match '^([0-9a-f]{64})  (.+)$') {
            $actual = (Get-FileHash -Algorithm SHA256 $Matches[2]).Hash.ToLower()
            if ($actual -ne $Matches[1]) { throw "Wheel checksum failed: $($Matches[2])" }
        }
    }
} finally {
    Pop-Location
}
if ($ValidateOnly) {
    Write-Host "Pre-build validation passed."
    return
}

New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
docker build `
    --file (Join-Path $ProjectDir "deploy\docker\Dockerfile.intranet") `
    --build-arg "APP_VERSION=$Version" `
    --tag $image `
    $ProjectDir
if ($LASTEXITCODE -ne 0) { throw "docker build failed." }

docker save --output $archive $image
if ($LASTEXITCODE -ne 0) { throw "docker save failed." }

$hash = Get-FileHash -Algorithm SHA256 $archive
"$($hash.Hash.ToLower())  $archiveName" |
    Set-Content -Encoding ascii (Join-Path $artifactDir "SHA256SUMS")
Write-Host "Image: $image"
Write-Host "Archive: $archive"
