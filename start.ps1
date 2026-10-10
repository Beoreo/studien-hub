# Startet den Studien-Hub im Entwicklungsmodus:
#   Backend  http://127.0.0.1:8000  (API-Doku unter /docs)
#   Frontend http://localhost:5173
# "npm run dev" startet das Backend automatisch mit und beendet es mit Strg+C wieder.
# Mit -NurBackend läuft nur das Backend; es liefert dann das gebaute Frontend
# (frontend/dist, erzeugt mit "npm run build") selbst unter http://127.0.0.1:8000 aus.
param([switch]$NurBackend)

$wurzel = $PSScriptRoot
$python = Join-Path $wurzel 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host 'Richte Python-Umgebung ein ...'
    py -3.12 -m venv (Join-Path $wurzel 'backend\.venv')
    & $python -m pip install -r (Join-Path $wurzel 'backend\requirements.txt')
}

if ($NurBackend) {
    Push-Location (Join-Path $wurzel 'backend')
    try { & $python -m uvicorn app.main:app --port 8000 } finally { Pop-Location }
    return
}

Push-Location (Join-Path $wurzel 'frontend')
try {
    if (-not (Test-Path 'node_modules')) { npm install }
    npm run dev
} finally { Pop-Location }
