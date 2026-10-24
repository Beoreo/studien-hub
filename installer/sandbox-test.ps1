# Installationstest auf einem frischen Windows-Benutzer: in der Windows Sandbox (alles in einem Lauf) oder auf einem
# zweiten lokalen Konto (zwei Teile, dazwischen ab- und wieder anmelden – prüft den echten Autostart).
#   Sandbox:      .\installer\sandbox-starten.ps1  (ruft dieses Skript mit -Basis C:\Test auf)
#   Testkonto:    .\installer\testkonto-einrichten.ps1, dann im Testkonto TEST-STARTEN.cmd und NACH-ANMELDUNG.cmd
# Ergebnis in <Basis>\ergebnis\ergebnis.txt.
param(
    [string]$Basis = 'C:\Test',
    [ValidateSet('alles', 'installation', 'nach-anmeldung')][string]$Teil = 'alles'
)
$ErrorActionPreference = 'Continue'
$ergebnis = Join-Path $Basis 'ergebnis'
$protokoll = Join-Path $ergebnis 'ergebnis.txt'
$programm = "$env:LOCALAPPDATA\Programs\StudienHub"
$exe = Join-Path $programm 'StudienHub.exe'
$daten = "$env:LOCALAPPDATA\StudienHub"
$hub = 'http://127.0.0.1:8000'
$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$setup = Get-ChildItem (Join-Path $Basis 'dist\StudienHub-Setup-*.exe') | Sort-Object Name | Select-Object -Last 1
$claude = "$env:APPDATA\Claude\claude_desktop_config.json"
Remove-Item (Join-Path $ergebnis 'fertig.txt') -ErrorAction SilentlyContinue
if ($Teil -ne 'nach-anmeldung') { Remove-Item $protokoll -ErrorAction SilentlyContinue }

function Notiz($text) {
    $zeile = "$(Get-Date -Format HH:mm:ss) $text"
    $zeile | Add-Content $protokoll -Encoding utf8
    Write-Host $zeile  # auch im Fenster, damit man sieht, dass es läuft
}

# Schutz: Der Test installiert, trägt Autostart und Claude Desktop ein – nie im eigenen Konto ausführen
if ($Basis -eq 'C:\StudienHubTest' -and $env:USERNAME -ne 'StudienHubTest') {
    Write-Host "Abbruch: Dieser Test läuft nur im Konto StudienHubTest (angemeldet ist $env:USERNAME)." -ForegroundColor Red
    Write-Host 'Startmenü → Profilbild → Benutzer wechseln → StudienHubTest.'
    exit 1
}
function Pruefe($name, $ok, $detail = '') {
    $zeichen = if ($ok) { 'OK  ' } else { 'FEHL' }
    Notiz "$zeichen $name$(if ($detail) { " – $detail" })"
}
function Api($pfad, $methode = 'GET', $daten = $null) {
    $optionen = @{ Uri = "$hub$pfad"; Method = $methode; TimeoutSec = 60 }
    if ($null -ne $daten) { $optionen.Body = ($daten | ConvertTo-Json -Compress); $optionen.ContentType = 'application/json' }
    Invoke-RestMethod @optionen
}
# Windows PowerShell 5.1 gibt ein JSON-Array als *ein* Objekt aus – @(…) ergäbe immer 1; Measure-Object zählt richtig
function AnzahlLvas { (Api '/api/lvas' | ForEach-Object { $_ } | Measure-Object).Count }
function WarteAufHub($sekunden = 90) {
    $start = Get-Date
    while (((Get-Date) - $start).TotalSeconds -lt $sekunden) {
        try { Api '/api/status' | Out-Null; return ((Get-Date) - $start).TotalSeconds } catch { Start-Sleep -Milliseconds 500 }
    }
    return $null
}
function Installieren($aufgaben) {
    $p = Start-Process $setup.FullName -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/TASKS=$aufgaben", "/LOG=$ergebnis\setup-$(Get-Date -Format HHmmss).log" -Wait -PassThru
    return $p.ExitCode
}

Notiz "== Test $($setup.Name), Teil $Teil, Benutzer $env:USERNAME (Fenster offen lassen, dauert einige Minuten)"

if ($Teil -ne 'nach-anmeldung') {
# Wiederholter Lauf im Testkonto: Daten des letzten Laufs (bleiben bei der Deinstallation absichtlich) entfernen,
# damit der Assistent wieder wie beim ersten Start beginnt
if (Test-Path $daten) {
    Remove-Item $daten -Recurse -Force
    Notiz 'Daten eines früheren Testlaufs entfernt'
}

# --- 1. Installation ------------------------------------------------------------------------------
$code = Installieren 'autostart,claude'
Pruefe 'Installation ohne Adminrechte' ($code -eq 0) "Exitcode $code"
Pruefe 'StudienHub.exe installiert' (Test-Path $exe) $programm
$manifest = Get-Content (Join-Path $programm 'browser-erweiterung\manifest.json') -Raw | ConvertFrom-Json
Pruefe 'Erweiterung mit festem key und Version' ($manifest.key -and $manifest.version -eq ($setup.BaseName -replace '.*-', '')) "Version $($manifest.version)"
$autostart = (Get-ItemProperty $run -ErrorAction SilentlyContinue).StudienHub
Pruefe 'Autostart eingetragen' ($autostart -like '*StudienHub.exe*--hintergrund') $autostart
Pruefe 'Startmenü-Eintrag' (Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Studien-Hub.lnk")
$eintrag = if (Test-Path $claude) { (Get-Content $claude -Raw | ConvertFrom-Json).mcpServers.'studien-hub' } else { $null }
Pruefe 'Claude Desktop: MCP-Server eingetragen' ($eintrag -and $eintrag.command -eq $exe -and $eintrag.args -contains '--mcp') "$($eintrag.command) $($eintrag.args)"

# --- 2. Start, zweites Exemplar ----------------------------------------------------------------------
Start-Process $exe -ArgumentList '--hintergrund'
$dauer = WarteAufHub
Pruefe 'Hub startet' ($null -ne $dauer) ("nach {0:N1} s" -f $dauer)
$status = Api '/api/system/status'
Pruefe 'Produktionsmodus, Datenordner unter LOCALAPPDATA' ($status.modus -eq 'produktion' -and $status.daten_ordner -eq $daten) $status.daten_ordner
$t = Get-Date
$zweiter = Start-Process $exe -ArgumentList '--hintergrund' -Wait -PassThru
Pruefe 'Zweiter Start beendet sich sofort' (((Get-Date) - $t).TotalSeconds -lt 10 -and (Get-Process StudienHub).Count -eq 1) ("{0:N1} s, {1} Prozess(e)" -f ((Get-Date) - $t).TotalSeconds, (Get-Process StudienHub).Count)
$nurLokal = Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -ExpandProperty LocalAddress -Unique
Pruefe 'Nur an 127.0.0.1 gebunden' (($nurLokal -join ',') -eq '127.0.0.1') ($nurLokal -join ',')

# --- 3. Einrichtungsassistent ---------------------------------------------------------------------------
$einrichtung = Api '/api/einrichtung'
Pruefe 'Assistent: erster Start erkannt' (-not $einrichtung.abgeschlossen)
Pruefe 'Assistent: Entwicklungsdaten gefunden' ([bool]$einrichtung.daten.quelle) $einrichtung.daten.quelle
$lvas = AnzahlLvas
if ($einrichtung.daten.quelle) {
    Api '/api/einrichtung/daten' 'POST' | Out-Null
    $start = Get-Date
    do { Start-Sleep 3; $stand = (Api '/api/einrichtung').daten.stand } while ($stand.laeuft -and ((Get-Date) - $start).TotalMinutes -lt 20)
    Pruefe 'Daten übernommen' ($stand.fertig -and -not $stand.fehler) ("{0:N0} MB in {1:N0} s {2}" -f ($stand.kopiert / 1MB), ((Get-Date) - $start).TotalSeconds, $stand.fehler)
    $lvas = AnzahlLvas
    Pruefe 'LVAs nach der Übernahme da' ($lvas -gt 0) "$($lvas) LVAs"
}
Api '/api/einrichtung/tuwel-token' 'PUT' @{ eingabe = ('a' * 32) } | Out-Null
$anmeldedaten = cmdkey /list | Select-String 'StudienHub'
Pruefe 'TUWEL-Token in der Anmeldeinformationsverwaltung' ([bool]$anmeldedaten) (($anmeldedaten | Select-Object -First 1) -as [string]).Trim()
Api '/api/einrichtung/abschliessen' 'POST' | Out-Null
Pruefe 'Assistent abgeschlossen' ((Api '/api/einrichtung').abgeschlossen)

# --- 4. Sync, Modell, Sicherung --------------------------------------------------------------------------
Api '/api/system/sync' 'POST' | Out-Null
$start = Get-Date
do { Start-Sleep 3; $tiss = (Api '/api/system/status').jobs | Where-Object id -eq 'tiss-sync' } while ($tiss.laeuft -and ((Get-Date) - $start).TotalSeconds -lt 180)
$quelle = (Api '/api/system/status').quellen | Where-Object id -eq 'tiss'
Pruefe 'Jetzt synchronisieren: TISS-Import' (-not $tiss.fehler -and $quelle.letzter_sync -and -not $quelle.fehler) "letzter Sync $($quelle.letzter_sync) $($quelle.fehler.meldung)"
Pruefe 'TUWEL-Sync angefordert (für die Erweiterung)' ([bool](Api '/api/tuwel/sync/anforderung').angefordert)

Api '/api/einrichtung/modelle/whisper' 'POST' | Out-Null
Start-Sleep 25
$whisper = (Api '/api/einrichtung').modelle | Where-Object id -eq 'whisper'
Pruefe 'Modell-Download mit Fortschritt' ($whisper.laeuft -and $whisper.prozent -gt 0 -or $whisper.vorhanden) "$($whisper.prozent) %, Fehler: $($whisper.fehler)"
$embedding = (Api '/api/einrichtung').modelle | Where-Object id -eq 'embedding'
Pruefe 'Embedding-Modell vorhanden (übernommen)' ($embedding.vorhanden)

$sicherung = Api '/api/system/sicherungen' 'POST'
$wieder = Api "/api/system/sicherungen/$($sicherung.name)/wiederherstellen" 'POST'
Pruefe 'Sicherung anlegen und wiederherstellen' ($wieder.vorheriger_stand -and (AnzahlLvas) -eq $lvas) "vorher gesichert: $($wieder.vorheriger_stand)"

# --- 5. MCP für Claude Desktop ------------------------------------------------------------------------
$info = New-Object System.Diagnostics.ProcessStartInfo $exe, '--mcp'
$info.UseShellExecute = $false; $info.RedirectStandardInput = $true; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
$info.EnvironmentVariables['STUDIENHUB_OFFLINE'] = '1'; $info.EnvironmentVariables['HF_HUB_OFFLINE'] = '1'
$mcp = [System.Diagnostics.Process]::Start($info)
$mcp.StandardInput.WriteLine('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"sandbox","version":"1"}}}')
$mcp.StandardInput.Flush()
$aufgabe = $mcp.StandardOutput.ReadLineAsync()
$antwort = if ($aufgabe.Wait(60000)) { $aufgabe.Result } else { '' }
$mcp.StandardInput.WriteLine('{"jsonrpc":"2.0","method":"notifications/initialized"}')
$mcp.StandardInput.WriteLine('{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"liste_lvas","arguments":{}}}')
$mcp.StandardInput.Flush()
$aufgabe = $mcp.StandardOutput.ReadLineAsync()
$aufruf = if ($aufgabe.Wait(60000)) { $aufgabe.Result } else { '' }
$mcp.StandardInput.Close(); $mcp.WaitForExit(10000) | Out-Null
Pruefe 'MCP-Server über stdio (StudienHub.exe --mcp)' ($antwort -like '*studien-hub*' -and $aufruf -like '*"id":2*' -and $aufruf -notlike '*"isError":true*') ($antwort.Substring(0, [Math]::Min(90, $antwort.Length)))

# --- 6. Autostart: Neustart nachstellen und im Hub schalten --------------------------------------------
Stop-Process -Name StudienHub -Force; Start-Sleep 2
$befehl = (Get-ItemProperty $run).StudienHub
$teile = [regex]::Match($befehl, '^"([^"]+)"\s*(.*)$')
Start-Process $teile.Groups[1].Value -ArgumentList $teile.Groups[2].Value
$dauer = WarteAufHub
Pruefe 'Start wie bei der Anmeldung (Run-Eintrag)' ($null -ne $dauer) ("nach {0:N1} s" -f $dauer)
$jobs = (Api '/api/system/status').jobs | Where-Object { $_.id -in 'tiss-sync', 'sicherung' }
Pruefe 'Geplante Läufe nach Neustart eingeplant' (($jobs | Where-Object naechster_lauf).Count -eq 2) (($jobs | ForEach-Object { "$($_.id) $($_.naechster_lauf)" }) -join ', ')
Api '/api/system/autostart' 'PUT' @{ aktiv = $false } | Out-Null
$aus = -not (Get-ItemProperty $run -ErrorAction SilentlyContinue).StudienHub
Api '/api/system/autostart' 'PUT' @{ aktiv = $true } | Out-Null
$an = [bool](Get-ItemProperty $run).StudienHub
Pruefe 'Autostart im Hub aus- und einschalten' ($aus -and $an)

# --- 7. Update: neue Setup-Datei über die laufende Installation ----------------------------------------
$code = Installieren 'autostart,claude'
Start-Process $exe -ArgumentList '--hintergrund'
$dauer = WarteAufHub
Pruefe 'Update über laufende Installation' ($code -eq 0 -and $null -ne $dauer -and (AnzahlLvas) -eq $lvas) "Exitcode $code, Daten erhalten"
}

if ($Teil -eq 'installation') {
    Notiz '== Teil 1 fertig – jetzt abmelden, wieder anmelden und NACH-ANMELDUNG.cmd starten'
    'fertig' | Set-Content (Join-Path $ergebnis 'fertig.txt')
    return
}

if ($Teil -eq 'nach-anmeldung') {
# --- Echter Autostart: nach dem Anmelden muss der Hub von selbst laufen ---------------------------------
# Windows startet Autostart-Einträge einige Sekunden nach der Anmeldung: erst warten, dann prüfen
$dauer = WarteAufHub 90
$prozess = Get-Process StudienHub -ErrorAction SilentlyContinue
Pruefe 'Autostart bei der Windows-Anmeldung' ($prozess -and $null -ne $dauer) ("{0} Prozess(e), Startzeit {1}" -f @($prozess).Count, (@($prozess)[0].StartTime))
$status = Api '/api/system/status'
$geplant = $status.jobs | Where-Object { $_.id -in 'tiss-sync', 'mbcloud', 'sicherung' }
Pruefe 'Geplante Läufe nach der Anmeldung eingeplant' ((@($geplant | Where-Object naechster_lauf)).Count -eq 3) (($geplant | ForEach-Object { "$($_.id) $($_.naechster_lauf)" }) -join ', ')
Pruefe 'Keine Fehler im Status' ($status.fehler.Count -eq 0) (($status.fehler) -join ' | ')
}

# --- 8. Deinstallation (Daten behalten = Standard) -----------------------------------------------------
$p = Start-Process (Join-Path $programm 'unins000.exe') -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Start-Sleep 5  # das Deinstallationsprogramm löscht sich verzögert selbst
Pruefe 'Deinstallation' ($p.ExitCode -eq 0 -and -not (Test-Path $exe) -and -not (Get-Process StudienHub -ErrorAction SilentlyContinue)) "Exitcode $($p.ExitCode)"
Pruefe 'Daten bleiben erhalten' (Test-Path (Join-Path $daten 'studienhub.db'))
Pruefe 'Autostart entfernt' (-not (Get-ItemProperty $run -ErrorAction SilentlyContinue).StudienHub)
$rest = if (Test-Path $claude) { (Get-Content $claude -Raw | ConvertFrom-Json).mcpServers.'studien-hub' } else { $null }
Pruefe 'Claude-Desktop-Eintrag entfernt (mit Sicherung)' (-not $rest -and (Get-ChildItem "$env:APPDATA\Claude" -Filter '*vor-studienhub*').Count -gt 0)

Copy-Item "$daten\logs\studienhub.log" $ergebnis -ErrorAction SilentlyContinue
Notiz '== fertig'
'fertig' | Set-Content (Join-Path $ergebnis 'fertig.txt')
