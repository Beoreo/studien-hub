// Startet Backend (FastAPI, Port 8000) und Frontend (Vite) gemeinsam.
// Läuft auf Port 8000 bereits ein Studien-Hub mit aktuellem Code, wird er weiterverwendet.
// Ein veraltetes Backend (älter als der Code) wird beendet und neu gestartet.
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readdirSync, statSync } from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backend = path.resolve(frontend, '..', 'backend')
const WINDOWS = process.platform === 'win32'
const python = WINDOWS
  ? path.join(backend, '.venv', 'Scripts', 'python.exe')
  : path.join(backend, '.venv', 'bin', 'python')
const PORT = 8000
const warte = (ms) => new Promise((r) => setTimeout(r, ms))

function portBelegt(port) {
  return new Promise((resolve) => {
    const socket = net.connect(port, '127.0.0.1')
    socket.once('connect', () => (socket.destroy(), resolve(true)))
    socket.once('error', () => resolve(false))
  })
}

async function backendStatus() {
  try {
    const antwort = await fetch(`http://127.0.0.1:${PORT}/api/status`, { signal: AbortSignal.timeout(2000) })
    return antwort.ok ? await antwort.json() : null
  } catch {
    return null
  }
}

// Neuester Änderungszeitpunkt der Backend-Quellen (Sekunden, wie Pythons st_mtime)
function codeStand(ordner = path.join(backend, 'app')) {
  let neuester = 0
  for (const eintrag of readdirSync(ordner, { withFileTypes: true })) {
    const pfad = path.join(ordner, eintrag.name)
    if (eintrag.isDirectory() && eintrag.name !== '__pycache__') neuester = Math.max(neuester, codeStand(pfad))
    else if (eintrag.name.endsWith('.py')) neuester = Math.max(neuester, statSync(pfad).mtimeMs / 1000)
  }
  return neuester
}

const istAktuell = (status) => status?.app === 'studien-hub' && status.code_stand >= codeStand() - 1

// Unter Windows startet die venv-python.exe den eigentlichen Interpreter als Kindprozess;
// deshalb immer den ganzen Prozessbaum beenden, sonst bleibt Port 8000 belegt.
function beendeBaum(pid) {
  if (!pid) return
  if (WINDOWS) spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' })
  else {
    try {
      process.kill(pid, 'SIGTERM')
    } catch {
      /* läuft schon nicht mehr */
    }
  }
}

async function warteAufBackend(prozess, sekunden = 30) {
  for (let i = 0; i < sekunden * 4; i++) {
    if (prozess.exitCode !== null) return false
    if (istAktuell(await backendStatus())) return true
    await warte(250)
  }
  return false
}

let backendProzess = null

if (await portBelegt(PORT)) {
  const status = await backendStatus()
  if (istAktuell(status)) {
    console.log(`[dev] Aktuelles Backend läuft bereits auf Port ${PORT} (PID ${status.pid}).`)
  } else if (status?.app === 'studien-hub') {
    console.log(`[dev] Backend auf Port ${PORT} ist veraltet (PID ${status.pid}) – wird beendet …`)
    beendeBaum(status.pid)
    // Mit --reload startet der Überwacher den Prozess sofort mit neuem Code neu; sonst wird der Port frei
    for (let i = 0; i < 40 && (await portBelegt(PORT)) && !istAktuell(await backendStatus()); i++) await warte(250)
  } else {
    console.error(`[dev] Port ${PORT} ist von einem anderen Programm belegt. Bitte beenden und neu starten.`)
    process.exit(1)
  }
}

if (!(await portBelegt(PORT))) {
  if (!existsSync(python)) {
    console.error(`[dev] Python-Umgebung fehlt (${python}).`)
    console.error('[dev] Einmalig ausführen:  cd backend; py -3.12 -m venv .venv; .\\.venv\\Scripts\\pip install -r requirements.txt')
    process.exit(1)
  }
  console.log('[dev] Starte Backend …')
  backendProzess = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--reload', '--port', String(PORT)], {
    cwd: backend,
    stdio: 'inherit',
  })
  if (!(await warteAufBackend(backendProzess))) {
    console.error('[dev] Backend ist nicht gestartet – siehe Fehlermeldung oben.')
    beendeBaum(backendProzess.pid)
    process.exit(1)
  }
  console.log(`[dev] Backend bereit: http://127.0.0.1:${PORT}/docs`)
} else if (!istAktuell(await backendStatus())) {
  console.error(`[dev] Das alte Backend auf Port ${PORT} ließ sich nicht beenden. Bitte Prozess manuell beenden.`)
  process.exit(1)
}

const vite = spawn(process.execPath, [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js')], {
  cwd: frontend,
  stdio: 'inherit',
})

let beendet = false
function beenden(code = 0) {
  if (beendet) return
  beendet = true
  beendeBaum(backendProzess?.pid)
  beendeBaum(vite.pid)
  process.exit(code)
}
process.on('SIGINT', () => beenden(0))
process.on('SIGTERM', () => beenden(0))
process.on('SIGHUP', () => beenden(0))
vite.on('exit', (code) => beenden(code ?? 0))
backendProzess?.on('exit', (code) => {
  if (code && !beendet) console.error(`[dev] Backend wurde beendet (Code ${code}).`)
})
