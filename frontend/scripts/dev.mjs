// Startet Backend (FastAPI, Port 8000) und Frontend (Vite) gemeinsam.
// Läuft auf Port 8000 bereits ein Backend, wird nur Vite gestartet.
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backend = path.resolve(frontend, '..', 'backend')
const python =
  process.platform === 'win32'
    ? path.join(backend, '.venv', 'Scripts', 'python.exe')
    : path.join(backend, '.venv', 'bin', 'python')
const PORT = 8000

function portBelegt(port) {
  return new Promise((resolve) => {
    const socket = net.connect(port, '127.0.0.1')
    socket.once('connect', () => (socket.destroy(), resolve(true)))
    socket.once('error', () => resolve(false))
  })
}

async function warteAufBackend(prozess, sekunden = 30) {
  for (let i = 0; i < sekunden * 4; i++) {
    if (prozess.exitCode !== null) return false
    if (await portBelegt(PORT)) return true
    await new Promise((r) => setTimeout(r, 250))
  }
  return false
}

let backendProzess = null

if (await portBelegt(PORT)) {
  console.log(`[dev] Backend läuft bereits auf Port ${PORT}.`)
} else {
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
    backendProzess.kill()
    process.exit(1)
  }
  console.log(`[dev] Backend bereit: http://127.0.0.1:${PORT}/docs`)
}

const vite = spawn(process.execPath, [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js')], {
  cwd: frontend,
  stdio: 'inherit',
})

function beenden() {
  backendProzess?.kill()
  vite.kill()
}
process.on('SIGINT', beenden)
process.on('SIGTERM', beenden)
vite.on('exit', (code) => {
  backendProzess?.kill()
  process.exit(code ?? 0)
})
backendProzess?.on('exit', (code) => {
  if (code) console.error(`[dev] Backend wurde beendet (Code ${code}).`)
})
