# Legt ein lokales Testkonto „StudienHubTest“ (Standardbenutzer, ohne Adminrechte) an und stellt den Installationstest
# unter C:\StudienHubTest bereit. Das Anlegen des Kontos fragt einmal per UAC nach Adminrechten.
# Danach: abmelden bzw. Benutzer wechseln, als StudienHubTest anmelden, C:\StudienHubTest\TEST-STARTEN.cmd starten,
# nach „Teil 1 fertig“ ab- und wieder anmelden und NACH-ANMELDUNG.cmd starten. Aufräumen: testkonto-entfernen.ps1
$wurzel = Split-Path $PSScriptRoot -Parent
$konto = 'StudienHubTest'
$basis = 'C:\StudienHubTest'
$setup = Get-ChildItem (Join-Path $wurzel 'dist\StudienHub-Setup-*.exe') | Sort-Object Name | Select-Object -Last 1
if (-not $setup) { throw 'Keine Setup-Datei in dist – zuerst .\build.ps1 ausführen.' }

# Testordner: Setup, Testskript, Startdateien; das Ergebnis darf das Testkonto schreiben
Remove-Item $basis -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory "$basis\dist", "$basis\ergebnis" | Out-Null
Copy-Item $setup.FullName "$basis\dist"
Copy-Item (Join-Path $PSScriptRoot 'sandbox-test.ps1') $basis
foreach ($teil in @(@{ Datei = 'TEST-STARTEN.cmd'; Teil = 'installation' }, @{ Datei = 'NACH-ANMELDUNG.cmd'; Teil = 'nach-anmeldung' })) {
    "@echo off`r`npowershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$basis\sandbox-test.ps1`" -Basis `"$basis`" -Teil $($teil.Teil)`r`ntype `"$basis\ergebnis\ergebnis.txt`"`r`npause" |
        Set-Content "$basis\$($teil.Datei)" -Encoding ascii
}

# Konto anlegen (UAC). Kennwort zufällig, wird unten angezeigt.
$kennwort = 'Hub-' + (-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 10 | ForEach-Object { [char]$_ })) + '!'
$befehl = @"
`$k = ConvertTo-SecureString '$kennwort' -AsPlainText -Force
if (Get-LocalUser -Name '$konto' -ErrorAction SilentlyContinue) { Set-LocalUser -Name '$konto' -Password `$k }
else { New-LocalUser -Name '$konto' -Password `$k -FullName 'Studien-Hub Test' -Description 'Installationstest Studien-Hub' -PasswordNeverExpires | Out-Null }
Add-LocalGroupMember -SID 'S-1-5-32-545' -Member '$konto' -ErrorAction SilentlyContinue
icacls '$basis\ergebnis' /grant '${konto}:(OI)(CI)M' | Out-Null
"@
$p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile', '-Command', $befehl
if ($p.ExitCode -ne 0) { throw "Konto anlegen fehlgeschlagen (Exitcode $($p.ExitCode))" }

# Lesezugriff auf die Entwicklungsdaten, damit der Assistent die Datenübernahme testen kann (nicht auf die .env)
icacls (Join-Path $wurzel 'daten') /grant "${konto}:(OI)(CI)RX" | Out-Null

Write-Host "Testkonto bereit: $konto / Kennwort: $kennwort" -ForegroundColor Green
Write-Host "Als $konto anmelden und $basis\TEST-STARTEN.cmd starten. Ergebnis: $basis\ergebnis\ergebnis.txt"
