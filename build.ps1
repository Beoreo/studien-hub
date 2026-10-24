# Erzeugt die Setup-Datei des Studien-Hubs: dist\StudienHub-Setup-<Version>.exe
#   .\build.ps1              Frontend bauen, Tests, PyInstaller, Inno Setup
#   .\build.ps1 -OhneTests   ohne pytest und Erweiterungs-Tests (schneller)
# Version steht nur in der Datei VERSION. Voraussetzungen: backend\.venv (start.ps1), Node, Inno Setup 6.
param([switch]$OhneTests)

# Nicht 'Stop': Windows PowerShell 5.1 bricht sonst ab, sobald ein Programm (npm, vite) nach stderr schreibt.
# Fehler erkennt Pruefen am Exitcode.
$ErrorActionPreference = 'Continue'
$wurzel = $PSScriptRoot
$python = Join-Path $wurzel 'backend\.venv\Scripts\python.exe'
$version = (Get-Content (Join-Path $wurzel 'VERSION') -Raw).Trim()
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

function Schritt($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Pruefen($was) { if ($LASTEXITCODE -ne 0) { throw "$was fehlgeschlagen (Exitcode $LASTEXITCODE)" } }

if (-not (Test-Path $python)) { throw 'Python-Umgebung fehlt: zuerst .\start.ps1 -NurBackend ausführen.' }
if (-not $iscc) { throw 'Inno Setup 6 fehlt: winget install JRSoftware.InnoSetup --scope user' }

Schritt "Studien-Hub $version"

Schritt 'Frontend bauen'
Push-Location (Join-Path $wurzel 'frontend')
try {
    if (-not (Test-Path 'node_modules')) { npm install; Pruefen 'npm install' }
    npm run build; Pruefen 'Frontend-Build'
} finally { Pop-Location }

if (-not $OhneTests) {
    Schritt 'Tests (Backend und Erweiterung)'
    Push-Location (Join-Path $wurzel 'backend')
    try { & $python -m pytest -q; Pruefen 'pytest' } finally { Pop-Location }
    Push-Location (Join-Path $wurzel 'browser-erweiterung')
    try { npm test; Pruefen 'Erweiterungs-Tests' } finally { Pop-Location }
}

Schritt 'Build vorbereiten (Symbol, Build-Info, Version)'
& $python -m pip install -q -r (Join-Path $wurzel 'backend\requirements-build.txt'); Pruefen 'pip install'
& $python (Join-Path $wurzel 'backend\scripts\build_vorbereiten.py'); Pruefen 'Build vorbereiten'

Schritt 'Browser-Erweiterung zusammenstellen'
$erweiterung = Join-Path $wurzel 'build\browser-erweiterung'
if (Test-Path $erweiterung) { Remove-Item $erweiterung -Recurse -Force }
New-Item -ItemType Directory $erweiterung | Out-Null
Get-ChildItem (Join-Path $wurzel 'browser-erweiterung') -File |
    Where-Object { $_.Extension -in '.js', '.json', '.html', '.css', '.png' -and $_.Name -notin 'package.json', 'package-lock.json' } |
    Copy-Item -Destination $erweiterung
Get-ChildItem (Join-Path $wurzel 'browser-erweiterung') -Directory |
    Where-Object { $_.Name -notin 'tests', 'node_modules' } |
    Copy-Item -Destination $erweiterung -Recurse
# Version der Erweiterung = Version des Hubs (nur in der Kopie; die Quelle bleibt unverändert)
$manifestPfad = Join-Path $erweiterung 'manifest.json'
$manifest = Get-Content $manifestPfad -Raw -Encoding utf8
$manifest = $manifest -replace '"version":\s*"[^"]*"', "`"version`": `"$version`""
[IO.File]::WriteAllText($manifestPfad, $manifest, [Text.UTF8Encoding]::new($false))

Schritt 'PyInstaller (StudienHub.exe, onedir)'
Push-Location (Join-Path $wurzel 'backend')
try {
    & $python -m PyInstaller --noconfirm --clean --log-level WARN `
        --distpath (Join-Path $wurzel 'build\pyinstaller') --workpath (Join-Path $wurzel 'build\pyinstaller-arbeit') `
        studienhub.spec
    Pruefen 'PyInstaller'
} finally { Pop-Location }

Schritt 'Paket prüfen (Importe in der exe)'
# Fehlende dynamische Importe fallen sonst erst beim Anwender auf (z. B. numpy, Whisper)
$exe = Join-Path $wurzel 'build\pyinstaller\StudienHub\StudienHub.exe'
$pruefung = Join-Path $wurzel 'build\import-pruefung.txt'
$module = 'numpy', 'faster_whisper', 'faster_whisper.utils', 'av', 'ctranslate2', 'fastembed', 'onnxruntime', 'sqlite_vec',
    'pymupdf', 'keyring.backends.Windows', 'pystray', 'holidays', 'apscheduler.triggers.cron', 'mcp.server.mcpserver', 'app.main'
$p = Start-Process $exe -ArgumentList (@('--import-pruefen') + $module) -RedirectStandardOutput $pruefung -Wait -PassThru -NoNewWindow
Get-Content $pruefung | Where-Object { $_ -match '^(ok|FEHLER)' } | ForEach-Object { Write-Host "  $_" }
if ($p.ExitCode -ne 0) { Get-Content $pruefung | Select-Object -Last 15 | Write-Host; throw 'Import-Prüfung der exe fehlgeschlagen (Details in build\import-pruefung.txt)' }

Schritt 'Inno Setup'
& $iscc /Q "/DVersion=$version" "/DWurzel=$wurzel" (Join-Path $wurzel 'installer\studienhub.iss'); Pruefen 'Inno Setup'

$setup = Join-Path $wurzel "dist\StudienHub-Setup-$version.exe"
$groesse = [math]::Round((Get-Item $setup).Length / 1MB, 1)
Write-Host "`nFertig: $setup ($groesse MB)" -ForegroundColor Green
