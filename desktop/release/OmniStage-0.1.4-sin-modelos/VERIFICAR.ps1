$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$lines = Get-Content -LiteralPath (Join-Path $root 'CHECKSUMS.sha256')
if (-not $lines) { throw 'No hay checksums para verificar.' }
foreach ($line in $lines) {
  if ($line -notmatch '^([a-f0-9]{64})  (.+)$') { throw "Línea de checksum inválida: $line" }
  $expected = $Matches[1]
  $relative = $Matches[2]
  if ($relative.StartsWith('/') -or $relative -match '(^|/)\.\.(/|$)|:') {
    throw "Ruta insegura: $relative"
  }
  $file = [System.IO.Path]::GetFullPath((Join-Path $root ($relative -replace '/', '\')))
  if (-not $file.StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Ruta fuera del paquete: $relative"
  }
  if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Falta $relative" }
  $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $expected) { throw "SHA256 no coincide: $relative" }
  Write-Output "OK $relative"
}
Write-Output 'Paquete íntegro.'
