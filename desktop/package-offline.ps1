param(
  [string]$Version = '0.1.3'
)

$ErrorActionPreference = 'Stop'
$desktop = $PSScriptRoot
$installer = Join-Path $desktop "dist\OmniStage Setup $Version.exe"
$modelPack = Join-Path $desktop 'model-pack'
$release = Join-Path $desktop "release\OmniStage-$Version-offline"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw "Falta el instalador: $installer" }
if (Test-Path -LiteralPath $release) { throw "La carpeta de entrega ya existe: $release" }
$manifest = Get-Content -LiteralPath (Join-Path $modelPack 'manifest.json') -Raw | ConvertFrom-Json
if ($manifest.format -ne 1 -or @($manifest.files).Count -ne 5) { throw 'Manifiesto de modelos inesperado.' }

foreach ($entry in $manifest.files) {
  if ($entry.path -notmatch '^(gemma-4-e2b-q4\.gguf|faster-whisper/(model\.bin|config\.json|tokenizer\.json|vocabulary\.txt))$') {
    throw "Archivo de modelo inesperado: $($entry.path)"
  }
  $source = Join-Path $modelPack ($entry.path -replace '/', '\')
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Falta $source" }
  if ((Get-Item -LiteralPath $source).Length -ne [long]$entry.size -or
      (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
    throw "Hash o tamaño inválido: $($entry.path)"
  }
}

New-Item -ItemType Directory -Path $release -Force | Out-Null
Copy-Item -LiteralPath $installer -Destination $release
$destination = Join-Path $release 'model-pack'
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $modelPack 'manifest.json') -Destination $destination
foreach ($entry in $manifest.files) {
  $relative = $entry.path -replace '/', '\'
  $target = Join-Path $destination $relative
  New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $modelPack $relative) -Destination $target
  if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
    throw "La copia no coincide: $relative"
  }
}

$readme = @"
OmniStage $Version - paquete de instalación offline

1. Copiar esta carpeta completa a la PC final.
2. Verificar la copia con PowerShell:
   powershell -ExecutionPolicy Bypass -File .\VERIFICAR.ps1
3. Ejecutar "OmniStage Setup $Version.exe" como administrador.
4. Abrir OmniStage y crear el operador inicial.
5. En Primeros pasos, elegir "Importar desde una carpeta" y seleccionar
   la carpeta model-pack que está junto al instalador.
6. Confirmar que los servicios aparecen activos antes de conectar una sala.

Este paquete incluye el modelo base Gemma 4 E2B GGUF y faster-whisper.
No contiene un modelo ajustado, claves API ni grabaciones privadas.
El instalador no está firmado. Requiere Windows x64 y controlador NVIDIA
compatible para la ruta local; Gemini es opcional y necesita su propia clave.
"@
Set-Content -LiteralPath (Join-Path $release 'LEEME.txt') -Value $readme -Encoding utf8
Copy-Item -LiteralPath (Join-Path $desktop 'verify-offline.ps1') -Destination (Join-Path $release 'VERIFICAR.ps1')

$checksums = @()
foreach ($file in @(Get-Item -LiteralPath (Join-Path $release "OmniStage Setup $Version.exe")) +
    @(Get-Item -LiteralPath (Join-Path $destination 'manifest.json')) +
    @($manifest.files | ForEach-Object { Get-Item -LiteralPath (Join-Path $destination ($_.path -replace '/', '\')) })) {
  $relative = $file.FullName.Substring($release.Length + 1).Replace('\', '/')
  $checksums += "$((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant())  $relative"
}
Set-Content -LiteralPath (Join-Path $release 'CHECKSUMS.sha256') -Value $checksums -Encoding ascii
Write-Output "Paquete listo: $release"
