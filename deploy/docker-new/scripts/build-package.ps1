param(
    [string]$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..\.." )).Path,
    [string]$Version = "20260817-mysql-ops-v2"
)

$ErrorActionPreference = "Stop"
$root = Join-Path $ProjectDir "deploy\docker-new"
$images = Join-Path $root "images"
$artifacts = Join-Path $root "artifacts"
$appImage = "docker.io/library/due-diligence-assistant:$Version"
$appArchive = Join-Path $images "due-diligence-assistant-$Version.image.tar"
$mysqlArchive = Join-Path $images "mysql-8.4.image.tar"
$zipName = "due-diligence-assistant-$Version-full-release.zip"
$zipPath = Join-Path $artifacts $zipName
$stageRoot = Join-Path $ProjectDir "release"
$stage = Join-Path $stageRoot ".docker-new-$Version"

New-Item -ItemType Directory -Force -Path $images,$artifacts,$stageRoot | Out-Null
docker image inspect $appImage | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Missing application image: $appImage" }
docker image inspect "docker.io/library/mysql:8.4" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Missing MySQL image" }

docker save --output $appArchive $appImage
if ($LASTEXITCODE -ne 0) { throw "docker save application failed" }
docker save --output $mysqlArchive "docker.io/library/mysql:8.4"
if ($LASTEXITCODE -ne 0) { throw "docker save MySQL failed" }

$checksumTargets = @(
    $appArchive,
    $mysqlArchive,
    (Join-Path $root "database\001-due_diligence-full.sql"),
    (Join-Path $root "docker-compose.yml"),
    (Join-Path $root "release.sh"),
    (Join-Path $root "scripts\verify.sh"),
    (Join-Path $root "scripts\backup.sh"),
    (Join-Path $root "scripts\restore.sh")
)
$checksumTargets | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($root, $_).Replace('\','/')
    "$( (Get-FileHash -Algorithm SHA256 $_).Hash.ToLower() )  $relative"
} | Set-Content -Encoding ascii (Join-Path $root "SHA256SUMS")

if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$items = @("images","database","scripts","docker-compose.yml","release.sh",".env.release.example",".env.intranet.example","SHA256SUMS","README.md","OPERATIONS-GUIDE.md","MIGRATION-MANIFEST.md","Dockerfile.intranet")
foreach ($item in $items) { Copy-Item -LiteralPath (Join-Path $root $item) -Destination $stage -Recurse }

if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
$stageItems = Get-ChildItem -LiteralPath $stage -Force | Select-Object -ExpandProperty FullName
Compress-Archive -LiteralPath $stageItems -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -Algorithm SHA256 $zipPath).Hash.ToLower()
"$zipHash  $zipName" | Set-Content -Encoding ascii "$zipPath.sha256"
Remove-Item -LiteralPath $stage -Recurse -Force

Write-Host "Release archive: $zipPath"
Write-Host "Checksum: $zipPath.sha256"
