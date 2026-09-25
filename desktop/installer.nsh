; Regla de firewall para la audiencia LAN: solo TCP 8088 y solo en redes Privadas.
; La API de operación, RTMP y RTSP siguen escuchando en loopback.
!macro customInstall
  nsExec::ExecToLog 'netsh advfirewall firewall delete rule name="OmniStage publico LAN"'
  nsExec::ExecToLog 'netsh advfirewall firewall add rule name="OmniStage publico LAN" dir=in action=allow protocol=TCP localport=8088 profile=private'
!macroend

!macro customUnInstall
  nsExec::ExecToLog 'netsh advfirewall firewall delete rule name="OmniStage publico LAN"'
!macroend
