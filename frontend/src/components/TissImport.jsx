import { useEffect, useState } from 'react'
import { api } from '../api.js'

function Ergebnis({ ergebnis }) {
  return (
    <div className="meldung ok">
      Import abgeschlossen: {ergebnis.neu} neu, {ergebnis.geaendert} geändert, {ergebnis.geloescht} gelöscht,{' '}
      {ergebnis.unveraendert} unverändert.
      {ergebnis.neue_lvas.length > 0 && <div>Neue LVAs: {ergebnis.neue_lvas.join(', ')}</div>}
      {ergebnis.neu_geplante_wochen.length > 0 && (
        <div>
          Arbeitszeit neu vorgeschlagen für die Wochen ab{' '}
          {ergebnis.neu_geplante_wochen.map((w) => new Date(w).toLocaleDateString('de-AT')).join(', ')}.
        </div>
      )}
    </div>
  )
}

export default function TissImport({ onImportiert }) {
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState({})
  const [ergebnis, setErgebnis] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [laeuft, setLaeuft] = useState(false)

  const ladeStatus = () =>
    api
      .tissEinstellungen()
      .then((s) => {
        setStatus(s)
        setUrl(s.ical_url || '')
      })
      .catch((e) => setFehler(e.message))

  useEffect(() => {
    ladeStatus()
  }, [])

  async function ausfuehren(aufruf) {
    setLaeuft(true)
    setFehler(null)
    setErgebnis(null)
    try {
      setErgebnis(await aufruf())
      onImportiert()
    } catch (e) {
      setFehler(e.message)
    } finally {
      setLaeuft(false)
      ladeStatus()
    }
  }

  const speichernUndImportieren = () =>
    ausfuehren(async () => {
      await api.tissEinstellungenSpeichern({ ical_url: url })
      return api.tissImport()
    })

  return (
    <div className="seite formular">
      <h2>TISS-Kalender importieren</h2>
      <p className="hinweis">
        In TISS unter <em>Favoriten → Kalender → iCal-Export / Abonnieren</em> den persönlichen Link kopieren. Der Link wird
        lokal gespeichert und jeden Morgen automatisch abgeglichen; nur Änderungen werden übernommen.
      </p>
      <label>
        iCal-Link
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://tiss.tuwien.ac.at/events/rest/calendar/personal?..." />
      </label>
      <button onClick={speichernUndImportieren} disabled={!url || laeuft}>
        {laeuft ? 'Importiere …' : 'Speichern und jetzt importieren'}
      </button>

      <h3>Oder: .ics-Datei hochladen</h3>
      <input
        type="file"
        accept=".ics,text/calendar"
        disabled={laeuft}
        onChange={(e) => e.target.files[0] && ausfuehren(() => api.tissImportDatei(e.target.files[0]))}
      />

      <p className="hinweis">
        Letzter Import: {status.letzter_import ? new Date(status.letzter_import).toLocaleString('de-AT') : 'noch nie'}
      </p>
      {status.letzter_fehler && <div className="meldung fehler">Letzter Sync-Fehler: {status.letzter_fehler}</div>}
      {fehler && <div className="meldung fehler">{fehler}</div>}
      {ergebnis && <Ergebnis ergebnis={ergebnis} />}
    </div>
  )
}
