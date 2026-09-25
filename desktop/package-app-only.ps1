param(
  [string]$Version = '0.1.4'
)

$ErrorActionPreference = 'Stop'
$desktop = $PSScriptRoot
$installer = Join-Path $desktop "dist\OmniStage Setup $Version.exe"
$release = Join-Path $desktop "release\OmniStage-$Version-sin-modelos"
$archive = "$release.7z"
$sevenZip = Join-Path $desktop 'node_modules\electron-winstaller\vendor\7z.exe'
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw "Falta el instalador: $installer" }
if (-not (Test-Path -LiteralPath $sevenZip -PathType Leaf)) { throw 'Falta 7-Zip en node_modules; ejecutá npm install en desktop.' }
if (Test-Path -LiteralPath $release) { throw "La carpeta de entrega ya existe: $release" }
if (Test-Path -LiteralPath $archive) { throw "El archivo de entrega ya existe: $archive" }

New-Item -ItemType Directory -Path $release -Force | Out-Null
Copy-Item -LiteralPath $installer -Destination $release
Copy-Item -LiteralPath (Join-Path $desktop 'verify-offline.ps1') -Destination (Join-Path $release 'VERIFICAR.ps1')
$readme = @"
OmniStage $Version - instalador comprimido SIN MODELOS

1. Extraer este .7z en la PC final (con 7-Zip u otro extractor compatible).
2. Abrir PowerShell en la carpeta extraída y verificar el instalador:
   powershell -ExecutionPolicy Bypass -File .\VERIFICAR.ps1
3. Ejecutar "OmniStage Setup $Version.exe" como administrador.
4. Abrir OmniStage, crear el operador y entrar en Modelos locales.
5. Descargar los modelos desde la app o importarlos desde una carpeta aparte.
6. Esperar a que Gemma aparezca activo y ejecutar una prueba de traducción.

Este paquete contiene la aplicación y sus motores, pero NO los pesos de
Gemma ni faster-whisper. No contiene claves API ni grabaciones privadas.
El instalador no está firmado. Requiere Windows x64; la ruta local necesita
una GPU NVIDIA compatible. Gemini es opcional y requiere su propia clave.
"@
Set-Content -LiteralPath (Join-Path $release 'LEEME.txt') -Value $readme -Encoding utf8
$hash = (Get-FileHash -LiteralPath (Join-Path $release "OmniStage Setup $Version.exe") -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $release 'CHECKSUMS.sha256') -Value "$hash  OmniStage Setup $Version.exe" -Encoding ascii
& (Join-Path $release 'VERIFICAR.ps1')

Push-Location $release
try {
  & $sevenZip a -t7z -m0=lzma2:d=64m -mx=7 -mmt=4 -ms=on -y $archive '.\*'
  if ($LASTEXITCODE -ne 0) { throw 'Fallo la compresión.' }
} finally { Pop-Location }
& $sevenZip t $archive
if ($LASTEXITCODE -ne 0) { throw 'Fallo la prueba de integridad del archivo 7z.' }
Write-Output "Entrega sin modelos: $archive"
Write-Output "Bytes comprimidos: $((Get-Item -LiteralPath $archive).Length)"
