import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const zeit = (iso) => (iso ? new Date(iso).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' }) : '–')
const TYP_NAME = { pdf: 'PDF', folien: 'Folien', dokument: 'Dokument', sonstiges: 'Datei', video: 'Video' }

function groesse(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
}

function Status({ status }) {
  if (!status) return null
  const e = status.letztes_ergebnis
  return (
    <section className="formular">
      <h2>Status</h2>
      {status.warnung && <div className="meldung warnung">{status.warnung}</div>}
      {status.letzter_fehler && (
        <div className="meldung fehler">
          {status.letzter_fehler.art === 'login' ? 'TUWEL-Anmeldung fehlt: ' : 'Fehler beim letzten Lauf: '}
          {status.letzter_fehler.meldung} ({zeit(status.letzter_fehler.zeit)})
        </div>
      )}
      <p>
        Letzter erfolgreicher Lauf: <strong>{zeit(status.letzter_erfolg)}</strong>
        {e && (
          <>
            {' '}
            – {e.kurse} Kurse, {e.neu} neu, {e.geaendert} geändert, {e.unveraendert} unverändert, {e.videos} neue Videos
          </>
        )}
      </p>
      <p className="hinweis">
        Gesamt: {status.dateien} Dateien, {status.videos} Video-Links aus {status.kurse} Kursen
        {status.kurse_ohne_lva > 0 && <> · {status.kurse_ohne_lva} Kurse ohne LVA (siehe unten)</>}
      </p>
    </section>
  )
}

function Einrichtung({ offen }) {
  const [daten, setDaten] = useState(null)
  const [kopiert, setKopiert] = useState(false)

  useEffect(() => {
    api.tuwelEinrichtung().then(setDaten)
  }, [])
  if (!daten) return null

  const kopieren = async () => {
    try {
      await navigator.clipboard.writeText(daten.schluessel)
      setKopiert(true)
      setTimeout(() => setKopiert(false), 2000)
    } catch {
      /* Zwischenablage nicht verfügbar – Schlüssel ist markierbar */
    }
  }
  const neu = () => api.tuwelNeuerSchluessel().then((d) => setDaten({ ...daten, ...d }))

  return (
    <details className="formular einrichtung" open={offen}>
      <summary>
        <h2>Browser-Erweiterung einrichten</h2>
      </summary>
      <p className="hinweis">
        Die Erweiterung liest TUWEL mit deiner normalen Browser-Anmeldung und schickt neue oder geänderte Dateien an den Hub.
        Sie läuft täglich, beim Öffnen von TUWEL (höchstens alle 6 h) und auf Klick. Videos werden nur verlinkt.
      </p>
      <ol>
        <li>
          <strong>Chrome/Edge:</strong> <code>chrome://extensions</code> bzw. <code>edge://extensions</code> öffnen,
          „Entwicklermodus“ einschalten, „Entpackte Erweiterung laden“ und diesen Ordner wählen:
          <br />
          <code className="pfad">{daten.ordner}</code>
          <br />
          <strong>Firefox:</strong> <code>about:debugging#/runtime/this-firefox</code> → „Temporäres Add-on laden“ →{' '}
          <code>manifest.json</code> aus diesem Ordner (bleibt bis zum Neustart von Firefox aktiv).
        </li>
        <li>Auf das Symbol der Erweiterung klicken, unter „Einstellungen“ diesen Schlüssel eintragen und „Speichern und prüfen“:</li>
      </ol>
      <div className="zeile schluessel">
        <input readOnly value={daten.schluessel} onFocus={(e) => e.target.select()} />
        <button type="button" onClick={kopieren}>
          {kopiert ? 'kopiert ✓' : 'kopieren'}
        </button>
        <button type="button" className="zweitrangig" onClick={neu} title="Alten Schlüssel ungültig machen">
          neu erzeugen
        </button>
      </div>
      <p className="hinweis">
        Unterlagen landen in <code className="pfad">{daten.unterlagen}</code>, je Semester und LVA ein Ordner.
      </p>
    </details>
  )
}

function KursZuordnung({ kurse, lvas, onGeaendert, setFehler }) {
  if (kurse.length === 0) return null
  const wert = (k) => (k.zuordnung === 'aus' ? 'aus' : k.zuordnung === 'auto' ? 'auto' : String(k.lva_id ?? 'aus'))
  const aendern = (k, auswahl) => {
    const daten =
      auswahl === 'auto' ? { automatisch: true } : auswahl === 'aus' ? { aus: true } : { lva_id: Number(auswahl) }
    api.tuwelKursZuordnen(k.id, daten).then(onGeaendert).catch((e) => setFehler(e.message))
  }
  return (
    <section className="formular">
      <h2>Kurse und LVAs</h2>
      <p className="hinweis">
        Kurse werden über die LVA-Nummer (und das Semester) automatisch zugeordnet. Nur zugeordnete Kurse werden
        synchronisiert.
      </p>
      <div className="tabelle-huelle">
        <table className="tabelle">
          <thead>
            <tr>
              <th>TUWEL-Kurs</th>
              <th>LVA</th>
              <th>Zuordnung</th>
            </tr>
          </thead>
          <tbody>
            {kurse.map((k) => (
              <tr key={k.id} className={k.synchronisieren ? '' : 'leise'}>
                <td>
                  {k.name}
                  <div className="hinweis">{k.kurzname}</div>
                </td>
                <td>{k.lva_name ? `${k.lva_name} (${k.lva_semester})` : '–'}</td>
                <td>
                  <select value={wert(k)} onChange={(e) => aendern(k, e.target.value)}>
                    <option value="auto">automatisch{k.zuordnung === 'auto' && !k.lva_id ? ' (nichts gefunden)' : ''}</option>
                    <option value="aus">nicht synchronisieren</option>
                    {lvas.map((l) => (
                      <option key={l.id} value={String(l.id)}>
                        {l.kurzname || l.titel} ({l.semester})
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Unterlagen({ dokumente, lvas }) {
  const nachLva = useMemo(() => {
    const gruppen = new Map()
    for (const d of dokumente) {
      if (!gruppen.has(d.lva_id)) gruppen.set(d.lva_id, [])
      gruppen.get(d.lva_id).push(d)
    }
    return gruppen
  }, [dokumente])
  if (dokumente.length === 0) return null
  const lvaName = (id) => {
    const l = lvas.find((x) => x.id === id)
    return l ? `${l.kurzname || l.titel} (${l.semester})` : `LVA ${id}`
  }
  return (
    <section className="formular">
      <h2>Unterlagen</h2>
      {[...nachLva.entries()].map(([lvaId, liste]) => (
        <details key={lvaId} className="lva-unterlagen">
          <summary>
            {lvaName(lvaId)} – {liste.filter((d) => !d.ist_link).length} Dateien, {liste.filter((d) => d.ist_link).length}{' '}
            Videos
            {liste.some((d) => d.status !== 'unveraendert') && <span className="marke">neu/geändert</span>}
          </summary>
          <table className="tabelle">
            <tbody>
              {liste.map((d) => (
                <tr key={d.id}>
                  <td>{d.abschnitt}</td>
                  <td>
                    {d.ist_link ? (
                      <a href={d.url} target="_blank" rel="noreferrer">
                        🎥 {d.dateiname}
                      </a>
                    ) : (
                      <a href={api.dokumentUrl(d.id)} target="_blank" rel="noreferrer">
                        {d.dateiname}
                      </a>
                    )}
                  </td>
                  <td>{TYP_NAME[d.typ] || d.typ}</td>
                  <td className="hinweis">{groesse(d.groesse)}</td>
                  <td>{d.status !== 'unveraendert' && <span className="marke">{d.status === 'neu' ? 'neu' : 'geändert'}</span>}</td>
                  <td className="hinweis">{zeit(d.geaendert_am)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </section>
  )
}

export default function TuwelSync({ lvas, onStatus }) {
  const [status, setStatus] = useState(null)
  const [kurse, setKurse] = useState([])
  const [dokumente, setDokumente] = useState([])
  const [fehler, setFehler] = useState(null)

  const laden = useCallback(() => {
    Promise.all([api.tuwelStatus(), api.tuwelKurse(), api.tuwelDokumente()])
      .then(([s, k, d]) => {
        setStatus(s)
        setKurse(k)
        setDokumente(d)
        onStatus?.(s)
      })
      .catch((e) => setFehler(e.message))
  }, [onStatus])

  useEffect(() => {
    laden()
    const zeitgeber = setInterval(laden, 30000) // Läufe der Erweiterung erscheinen ohne Neuladen
    return () => clearInterval(zeitgeber)
  }, [laden])

  return (
    <div className="seite tuwel">
      {fehler && (
        <div className="meldung fehler" onClick={() => setFehler(null)}>
          {fehler}
        </div>
      )}
      <Status status={status} />
      <Einrichtung offen={status && !status.letzter_erfolg} />
      <KursZuordnung kurse={kurse} lvas={lvas} onGeaendert={laden} setFehler={setFehler} />
      <Unterlagen dokumente={dokumente} lvas={lvas} />
    </div>
  )
}
