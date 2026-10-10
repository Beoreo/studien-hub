import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, laufzeit, videoZusammenfassung } from '../api.js'

const zeit = (iso) => (iso ? new Date(iso).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' }) : '–')
const tag = (iso) => (iso ? new Date(iso).toLocaleDateString('de-AT') : '')
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
      {e?.hinweise?.length > 0 && (
        <details>
          <summary className="hinweis">Was der letzte Lauf gefunden hat ({e.hinweise.length})</summary>
          <ul className="hinweis">
            {e.hinweise.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </details>
      )}
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

// Lernzeit einer Unterlage: leer = Schätzung, Zahl = eigene Minuten, 0 = nicht lernen
function LernzeitFeld({ dokument, onGeaendert }) {
  const speichern = (e) => {
    const wert = e.target.value === '' ? null : Math.max(0, Math.round(Number(e.target.value)))
    if (wert !== dokument.lern_minuten) api.dokumentLernzeit(dokument.id, wert).then(onGeaendert)
  }
  return (
    <span className="lernzeit" title={`Schätzung: ${dokument.lern_minuten_geschaetzt} min`}>
      <input
        type="number"
        min="0"
        step="5"
        key={dokument.lern_minuten ?? 'auto'}
        defaultValue={dokument.lern_minuten ?? ''}
        placeholder={String(dokument.lern_minuten_geschaetzt)}
        onBlur={speichern}
      />{' '}
      min{dokument.lern_minuten === 0 && <span className="hinweis"> · nicht lernen</span>}
    </span>
  )
}

function Unterlagen({ dokumente, lvas, onGeaendert }) {
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
      <p className="hinweis">
        Neueste zuerst nach Erscheinungsdatum. Hervorgehoben ist, was der letzte Sync neu gebracht oder geändert hat.
      </p>
      {[...nachLva.entries()].map(([lvaId, liste]) => {
        // Die API liefert bereits nach Erscheinungsdatum sortiert (neueste zuerst, ohne Datum am Ende)
        const dateien = liste.filter((d) => !d.ist_link)
        const videos = liste.filter((d) => d.ist_link)
        const dauer = videos.reduce((summe, v) => summe + (v.dauer_sekunden || 0), 0)
        const ohneDauer = videos.filter((v) => !v.dauer_sekunden).length
        const frisch = liste.filter((d) => d.neu_seit_sync).length
        return (
          <details key={lvaId} className="lva-unterlagen" open={frisch > 0}>
            <summary>
              {lvaName(lvaId)} – {dateien.length} Dateien, {videoZusammenfassung(videos.length, dauer, ohneDauer)}
              {frisch > 0 && <span className="marke">{frisch} neu/geändert</span>}
            </summary>
            {dateien.length > 0 && (
              <table className="tabelle">
                <thead>
                  <tr>
                    <th>Datei</th>
                    <th>Erschienen</th>
                    <th>Sync</th>
                    <th>Abschnitt</th>
                    <th>Typ</th>
                    <th title="Geschätzte Lernzeit; eigene Minuten eintragen, 0 = nicht lernen">Lernzeit</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {dateien.map((d) => (
                    <tr key={d.id} className={d.neu_seit_sync ? 'frisch' : ''}>
                      <td>
                        <Marke dokument={d} />
                        <a href={api.dokumentUrl(d.id)} target="_blank" rel="noreferrer">
                          {d.dateiname}
                        </a>
                      </td>
                      <td>
                        <Erschienen dokument={d} />
                      </td>
                      <td className="hinweis">{zeit(d.sync_am)}</td>
                      <td className="hinweis">{d.abschnitt}</td>
                      <td>
                        {TYP_NAME[d.typ] || d.typ}
                        {d.seiten ? <span className="hinweis"> · {d.seiten} S.</span> : null}
                      </td>
                      <td>
                        <LernzeitFeld dokument={d} onGeaendert={onGeaendert} />
                      </td>
                      <td className="hinweis rechts">{groesse(d.groesse)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {videos.length > 0 && (
              <>
                <h3 className="unterueberschrift">Aufzeichnungen</h3>
                <table className="tabelle">
                  <thead>
                    <tr>
                      <th>Titel</th>
                      <th>Erschienen</th>
                      <th>Sync</th>
                      <th>Dauer</th>
                      <th title="Geschätzte Lernzeit; eigene Minuten eintragen, 0 = nicht lernen">Lernzeit</th>
                      <th>Abschnitt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {videos.map((v) => (
                      <tr key={v.id} className={v.neu_seit_sync ? 'frisch' : ''}>
                        <td>
                          <Marke dokument={v} />
                          <a href={v.url} target="_blank" rel="noreferrer">
                            🎥 {v.dateiname}
                          </a>
                          {v.medien_url && (
                            <a className="hinweis klein-link" href={v.medien_url} target="_blank" rel="noreferrer" title="Videodatei direkt (Link kann ablaufen)">
                              Datei
                            </a>
                          )}
                        </td>
                        <td>
                          <Erschienen dokument={v} />
                        </td>
                        <td className="hinweis">{zeit(v.sync_am)}</td>
                        <td>{laufzeit(v.dauer_sekunden) || <span className="hinweis">unbekannt</span>}</td>
                        <td>
                          <LernzeitFeld dokument={v} onGeaendert={onGeaendert} />
                        </td>
                        <td className="hinweis">{v.abschnitt}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </details>
        )
      })}
    </section>
  )
}

// Woher das Erscheinungsdatum stammt
const QUELLEN = {
  tuwel: { kurz: 'TUWEL', lang: 'Datum, das TUWEL für die Aktivität meldet (hinzugefügt/geändert)' },
  'last-modified': { kurz: 'Datei', lang: 'Last-Modified-Angabe der Datei' },
  aufnahme: { kurz: 'Aufnahme', lang: 'Aufnahmedatum der Aufzeichnung' },
}

function Erschienen({ dokument }) {
  if (!dokument.erschienen_am) return <span className="hinweis" title="Noch kein Datum – kommt beim nächsten Sync">–</span>
  const quelle = QUELLEN[dokument.erschienen_quelle] || { kurz: dokument.erschienen_quelle, lang: '' }
  // Aufnahmedaten haben keine Uhrzeit
  const text = dokument.erschienen_quelle === 'aufnahme' ? tag(dokument.erschienen_am) : zeit(dokument.erschienen_am)
  return (
    <span title={`Quelle: ${quelle.lang}`}>
      {text} <span className="quelle">{quelle.kurz}</span>
    </span>
  )
}

function Marke({ dokument }) {
  if (!dokument.neu_seit_sync) return null
  return <span className="marke vorne">{dokument.status === 'geaendert' ? 'geändert' : 'neu'}</span>
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
      <Unterlagen dokumente={dokumente} lvas={lvas} onGeaendert={laden} />
    </div>
  )
}
