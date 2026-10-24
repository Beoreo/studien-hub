import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { Hinweis, Icon, IconButton } from './ui.jsx'
import Kalender from './components/Kalender.jsx'
import LvaListe from './components/LvaListe.jsx'
import Pruefungen from './components/Pruefungen.jsx'
import ArbeitEinstellungen from './components/ArbeitEinstellungen.jsx'
import TissImport from './components/TissImport.jsx'
import TuwelSync from './components/TuwelSync.jsx'
import MbCloud from './components/MbCloud.jsx'
import Wissensstand from './components/Wissensstand.jsx'
import KiVerbinden from './components/KiVerbinden.jsx'
import Wochenbericht from './components/Wochenbericht.jsx'
import Legende from './components/Legende.jsx'
import Status from './components/Status.jsx'
import Einrichtung from './components/Einrichtung.jsx'

const BEREICHE = [
  { id: 'kalender', name: 'Kalender' },
  { id: 'lvas', name: 'LVAs' },
  { id: 'pruefungen', name: 'Prüfungen' },
  { id: 'wissen', name: 'Wissensstand' },
  { id: 'bericht', name: 'Wochenbericht' },
  { id: 'arbeit', name: 'Arbeitszeiten' },
  { id: 'import', name: 'TISS-Import' },
  { id: 'tuwel', name: 'TUWEL' },
  { id: 'mbcloud', name: 'MB Cloud' },
  { id: 'ki', name: 'KI verbinden' },
  { id: 'status', name: 'Status' },
]
const GUELTIG = new Set([...BEREICHE.map((b) => b.id), 'einrichtung'])

// Bereich steht in der Adresse (#status), damit das Symbol im Infobereich direkt dorthin springen kann
const ausAdresse = () => {
  const id = window.location.hash.slice(1)
  return GUELTIG.has(id) ? id : 'kalender'
}

export default function App() {
  const [bereich, setBereichRoh] = useState(ausAdresse)
  const [lvas, setLvas] = useState([])
  const [fehler, setFehler] = useState(null)
  const [tuwelStatus, setTuwelStatus] = useState(null)
  const [menueOffen, setMenueOffen] = useState(false)
  const [legende, setLegende] = useState(false)

  const ladeLvas = useCallback(() => {
    api
      .lvas()
      .then((l) => {
        setLvas(l)
        setFehler(null)
      })
      .catch((e) => setFehler(e.message))
  }, [])

  useEffect(ladeLvas, [ladeLvas])

  const setBereich = useCallback((id) => {
    setBereichRoh(id)
    if (window.location.hash.slice(1) !== id) window.history.replaceState(null, '', `#${id}`)
  }, [])

  useEffect(() => {
    const wechsel = () => setBereichRoh(ausAdresse())
    window.addEventListener('hashchange', wechsel)
    return () => window.removeEventListener('hashchange', wechsel)
  }, [])

  // Beim ersten Start (Einrichtung nie abgeschlossen) zuerst der Assistent
  useEffect(() => {
    api
      .einrichtung()
      .then((e) => !e.abgeschlossen && !window.location.hash && setBereich('einrichtung'))
      .catch(() => {})
  }, [setBereich])

  // Sync-Probleme sollen auch außerhalb des TUWEL-Reiters auffallen
  useEffect(() => {
    const laden = () => api.tuwelStatus().then(setTuwelStatus).catch(() => {})
    laden()
    const zeitgeber = setInterval(laden, 5 * 60 * 1000)
    return () => clearInterval(zeitgeber)
  }, [])
  const tuwelProblem = tuwelStatus && (tuwelStatus.warnung || tuwelStatus.letzter_fehler?.meldung)

  const waehlen = (id) => {
    setBereich(id)
    setMenueOffen(false)
  }

  return (
    <div className="app">
      <header className="kopf">
        <span className="marke-name">Studien-Hub</span>
        <IconButton
          icon="menue"
          label="Bereiche"
          className="nur-schmal"
          data-menue
          aria-expanded={menueOffen}
          onClick={() => setMenueOffen(!menueOffen)}
        />
        <nav className={`navigation${menueOffen ? ' offen' : ''}`} aria-label="Bereiche">
          {BEREICHE.map((b) => (
            <button
              key={b.id}
              type="button"
              data-bereich={b.id}
              className={bereich === b.id ? 'reiter aktiv' : 'reiter'}
              aria-current={bereich === b.id ? 'page' : undefined}
              onClick={() => waehlen(b.id)}
            >
              {b.name}
              {b.id === 'tuwel' && tuwelProblem && <Icon name="warnung" label={`TUWEL: ${tuwelProblem}`} className="ton-warnung" />}
            </button>
          ))}
        </nav>
        <IconButton icon="hilfe" label="Legende der Symbole" onClick={() => setLegende(true)} />
      </header>
      {fehler && (
        <div className="app-meldung">
          <Hinweis ton="fehler" titel={`Backend nicht erreichbar: ${fehler}`} onSchliessen={() => setFehler(null)} />
        </div>
      )}
      <main>
        {bereich === 'kalender' && <Kalender lvas={lvas} />}
        {bereich === 'lvas' && <LvaListe lvas={lvas} onGeaendert={ladeLvas} />}
        {bereich === 'pruefungen' && <Pruefungen onGeaendert={ladeLvas} />}
        {bereich === 'arbeit' && <ArbeitEinstellungen />}
        {bereich === 'import' && <TissImport onImportiert={ladeLvas} />}
        {bereich === 'tuwel' && <TuwelSync lvas={lvas} onStatus={setTuwelStatus} />}
        {bereich === 'mbcloud' && <MbCloud lvas={lvas} />}
        {bereich === 'wissen' && <Wissensstand />}
        {bereich === 'ki' && <KiVerbinden />}
        {bereich === 'bericht' && <Wochenbericht />}
        {bereich === 'status' && <Status onEinrichtung={() => setBereich('einrichtung')} />}
        {bereich === 'einrichtung' && <Einrichtung onFertig={() => setBereich('kalender')} onDatenGeaendert={ladeLvas} />}
      </main>
      {legende && <Legende onSchliessen={() => setLegende(false)} />}
    </div>
  )
}
