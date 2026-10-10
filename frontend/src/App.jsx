import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import Kalender from './components/Kalender.jsx'
import LvaListe from './components/LvaListe.jsx'
import ArbeitEinstellungen from './components/ArbeitEinstellungen.jsx'
import TissImport from './components/TissImport.jsx'
import TuwelSync from './components/TuwelSync.jsx'

const BEREICHE = [
  { id: 'kalender', name: 'Kalender' },
  { id: 'lvas', name: 'LVAs' },
  { id: 'arbeit', name: 'Arbeitszeiten' },
  { id: 'import', name: 'TISS-Import' },
  { id: 'tuwel', name: 'TUWEL' },
]

export default function App() {
  const [bereich, setBereich] = useState('kalender')
  const [lvas, setLvas] = useState([])
  const [fehler, setFehler] = useState(null)
  const [tuwelStatus, setTuwelStatus] = useState(null)

  const ladeLvas = useCallback(() => {
    api.lvas().then(setLvas).catch((e) => setFehler(e.message))
  }, [])

  useEffect(ladeLvas, [ladeLvas])

  // Sync-Probleme sollen auch außerhalb des TUWEL-Reiters auffallen
  useEffect(() => {
    const laden = () => api.tuwelStatus().then(setTuwelStatus).catch(() => {})
    laden()
    const zeitgeber = setInterval(laden, 5 * 60 * 1000)
    return () => clearInterval(zeitgeber)
  }, [])
  const tuwelProblem = tuwelStatus && (tuwelStatus.warnung || tuwelStatus.letzter_fehler)

  return (
    <div className="app">
      <header className="kopf">
        <h1>Studien-Hub</h1>
        <nav>
          {BEREICHE.map((b) => (
            <button
              key={b.id}
              className={bereich === b.id ? 'reiter aktiv' : 'reiter'}
              onClick={() => setBereich(b.id)}
              title={b.id === 'tuwel' && tuwelProblem ? tuwelStatus.warnung || tuwelStatus.letzter_fehler.meldung : undefined}
            >
              {b.name}
              {b.id === 'tuwel' && tuwelProblem && <span className="warnpunkt" />}
            </button>
          ))}
        </nav>
      </header>
      {fehler && (
        <div className="meldung fehler" onClick={() => setFehler(null)}>
          Backend nicht erreichbar: {fehler}
        </div>
      )}
      <main>
        {bereich === 'kalender' && <Kalender lvas={lvas} />}
        {bereich === 'lvas' && <LvaListe lvas={lvas} onGeaendert={ladeLvas} />}
        {bereich === 'arbeit' && <ArbeitEinstellungen />}
        {bereich === 'import' && <TissImport onImportiert={ladeLvas} />}
        {bereich === 'tuwel' && <TuwelSync lvas={lvas} onStatus={setTuwelStatus} />}
      </main>
    </div>
  )
}
