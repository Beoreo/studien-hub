# Startet den Studien-Hub im Entwicklungsmodus:
#   Backend  http://127.0.0.1:8000  (API-Doku unter /docs)
#   Frontend http://localhost:5173
# Mit -NurBackend wird nur das Backend gestartet; es liefert dann das gebaute Frontend
# (frontend/dist, erzeugt mit "npm run build") selbst unter http://127.0.0.1:8000 aus.
param([switch]$NurBackend)

$wurzel = $PSScriptRoot
$python = Join-Path $wurzel 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host 'Richte Python-Umgebung ein ...'
    py -3.12 -m venv (Join-Path $wurzel 'backend\.venv')
    & $python -m pip install -r (Join-Path $wurzel 'backend\requirements.txt')
}
if (-not $NurBackend -and -not (Test-Path (Join-Path $wurzel 'frontend\node_modules'))) {
    Write-Host 'Installiere Frontend-Pakete ...'
    Push-Location (Join-Path $wurzel 'frontend'); npm install; Pop-Location
}

Start-Process -FilePath $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000' `
    -WorkingDirectory (Join-Path $wurzel 'backend')

if ($NurBackend) {
    Start-Process 'http://127.0.0.1:8000'
} else {
    Start-Process 'http://localhost:5173'
    Push-Location (Join-Path $wurzel 'frontend'); npm run dev; Pop-Location
}
