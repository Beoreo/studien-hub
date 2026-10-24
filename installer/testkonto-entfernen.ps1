# Entfernt das Testkonto „StudienHubTest“ samt Profil, den Testordner und die Leserechte auf die Entwicklungsdaten.
# Das Testkonto vorher abmelden. Fragt einmal per UAC nach Adminrechten.
$wurzel = Split-Path $PSScriptRoot -Parent
$konto = 'StudienHubTest'
icacls (Join-Path $wurzel 'daten') /remove:g $konto /T /C /Q | Out-Null
$befehl = @"
# noch angemeldet (nur Benutzer gewechselt)? Sitzung abmelden, sonst ist das Profil gesperrt
foreach (`$zeile in (quser 2>`$null)) { if (`$zeile -match '^\s*>?$konto\s+(?:\S+\s+)?(\d+)\s') { logoff `$Matches[1]; Start-Sleep 5 } }
`$sid = (Get-LocalUser -Name '$konto' -ErrorAction SilentlyContinue).SID.Value
if (`$sid) {
  Get-CimInstance Win32_UserProfile | Where-Object SID -eq `$sid | Remove-CimInstance
  Remove-LocalUser -Name '$konto'
}
Remove-Item 'C:\StudienHubTest' -Recurse -Force -ErrorAction SilentlyContinue
"@
Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile', '-Command', $befehl
Write-Host "Testkonto $konto entfernt." -ForegroundColor Green
