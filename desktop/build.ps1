param(
  [switch]$SkipNpmInstall,
  # Reutiliza runtime/omnistage-api y runtime/omnistage-worker ya congelados.
  [switch]$SkipBackend
)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
$runtime = Join-Path $PSScriptRoot 'runtime'
$vendor = Join-Path $PSScriptRoot 'vendor'
$required = @('ffmpeg.exe', 'mediamtx.exe', 'llama-server.exe', 'cudnn64_9.dll')
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Falta .venv de Python.' }
foreach ($name in $required) {
  $source = Join-Path $vendor $name
  if (-not (Test-Path -LiteralPath $source)) { throw "Falta $source. Consulta desktop/README.md." }
}
$manifestPath = Join-Path $vendor 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Falta $manifestPath con version, origen y SHA256." }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$entries = @($manifest.PSObject.Properties.Name)
foreach ($name in $entries) {
  if ($name -notmatch '^[A-Za-z0-9_.-]+$') { throw "Nombre inseguro en manifiesto: $name" }
  $entry = $manifest.PSObject.Properties[$name].Value
  $source = Join-Path $vendor $name
  if (-not (Test-Path -LiteralPath $source)) { throw "Falta $source" }
  if (-not $entry.version -or -not $entry.source -or -not $entry.sha256 -or
      -not ($entry.archive_sha256 -or $entry.package_record_sha256) -or
      -not $entry.license -or -not $entry.size) {
    throw "Manifiesto incompleto para $name"
  }
  if ((Get-Item -LiteralPath $source).Length -ne [long]$entry.size) {
    throw "Tamaño no coincide para $name"
  }
  $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  if ($actual -ne $entry.sha256) { throw "SHA256 no coincide para $name" }
}
$unexpected = @(Get-ChildItem -LiteralPath $vendor -File | Where-Object {
  $_.Name -ne 'manifest.json' -and $_.Name -notin $entries
})
if ($unexpected.Count -gt 0) { throw "Archivos no registrados en vendor: $($unexpected.Name -join ', ')" }
foreach ($name in $required) {
  $entry = $manifest.PSObject.Properties[$name].Value
  if (-not $entry) {
    throw "Manifiesto incompleto para $name"
  }
}
$modelDir = Join-Path $env:APPDATA 'OmniStage\models'
Write-Host "Los modelos locales se cargaran desde $modelDir"
Push-Location $project
try {
  npm --prefix web run build
  if ($LASTEXITCODE -ne 0) { throw 'Fallo el build web.' }
  if ($SkipBackend) {
    foreach ($name in @('omnistage-api', 'omnistage-worker')) {
      if (-not (Test-Path -LiteralPath (Join-Path $runtime "$name\$name.exe"))) { throw "Falta $name congelado; compilar sin -SkipBackend." }
    }
  } else {
  & $venvPython -m PyInstaller --noconfirm --clean --onedir --name omnistage-api --distpath $runtime --workpath (Join-Path $project 'build\pyinstaller') --specpath (Join-Path $project 'build') --collect-data silero_vad --collect-data faster_whisper --exclude-module pytest --exclude-module IPython --exclude-module matplotlib --exclude-module pandas app/serve.py
  if ($LASTEXITCODE -ne 0) { throw 'Fallo el build del backend.' }
  & $venvPython -m PyInstaller --noconfirm --clean --onedir --name omnistage-worker --distpath $runtime --workpath (Join-Path $project 'build\pyinstaller') --specpath (Join-Path $project 'build') --collect-data silero_vad --exclude-module pytest --exclude-module IPython --exclude-module matplotlib --exclude-module pandas app/room_worker.py
  if ($LASTEXITCODE -ne 0) { throw 'Fallo el build del worker.' }
  }
  New-Item -ItemType Directory -Force -Path $runtime | Out-Null
  Get-ChildItem -LiteralPath $vendor -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $runtime $_.Name) -Force
  }
  if (-not $SkipNpmInstall) { npm --prefix desktop install; if ($LASTEXITCODE -ne 0) { throw 'Fallo npm install.' } }
  npm --prefix desktop run dist
  if ($LASTEXITCODE -ne 0) { throw 'Fallo electron-builder.' }
} finally { Pop-Location }
