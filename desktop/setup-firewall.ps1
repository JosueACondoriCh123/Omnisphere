$ErrorActionPreference = 'Stop'
if (-not (Get-NetFirewallRule -DisplayName 'OmniStage publico LAN' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName 'OmniStage publico LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8088 -Profile Private | Out-Null
}
Write-Host 'Puerto 8088 habilitado solo en redes privadas. RTMP y controles siguen en loopback.'
