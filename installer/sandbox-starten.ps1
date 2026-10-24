# Startet den Installationstest in der Windows Sandbox (einmalig aktivieren: Windows-Feature „Windows-Sandbox“).
# Eingebunden: dist (Setup-Datei), installer (Testskript), daten (schreibgeschützt, für die Datenübernahme) und
# build\sandbox-ergebnis (Ergebnis). Die Sandbox läuft das Testskript bei der Anmeldung selbst ab.
$wurzel = Split-Path $PSScriptRoot -Parent
$ergebnis = Join-Path $wurzel 'build\sandbox-ergebnis'
New-Item -ItemType Directory -Force $ergebnis | Out-Null
Remove-Item (Join-Path $ergebnis '*') -Recurse -Force -ErrorAction SilentlyContinue

$wsb = @"
<Configuration>
  <Networking>Enable</Networking>
  <MappedFolders>
    <MappedFolder><HostFolder>$wurzel\dist</HostFolder><SandboxFolder>C:\Test\dist</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$wurzel\installer</HostFolder><SandboxFolder>C:\Test\skript</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$ergebnis</HostFolder><SandboxFolder>C:\Test\ergebnis</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$wurzel\daten</HostFolder><SandboxFolder>$wurzel\daten</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Test\skript\sandbox-test.ps1</Command>
  </LogonCommand>
</Configuration>
"@
$datei = Join-Path $wurzel 'build\sandbox.wsb'
Set-Content $datei $wsb -Encoding utf8
Start-Process 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList $datei
Write-Host "Sandbox gestartet. Ergebnis erscheint in $ergebnis\ergebnis.txt (fertig.txt markiert das Ende)."
