import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, laufzeit, videoZusammenfassung } from '../api.js'
import { Auswahl, Badge, Button, Eingabe, Hinweis, Icon, Karte, Menue, SeitenKopf, Tabelle } from '../ui.jsx'
import './TuwelSync.css'

const zeit = (iso) => (iso ? new Date(iso).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' }) : '–')
const tag = (iso) => (iso ? new Date(iso).toLocaleDateString('de-AT') : '')
const TYP_NAME = { pdf: 'PDF', folien: 'Folien', dokument: 'Dokument', sonstiges: 'Datei', video: 'Video' }
const LERNZEIT_HILFE = 'Geschätzte Lernzeit; eigene Minuten eintragen, 0 = nicht lernen'

function groesse(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
}

function fehlerText(f) {
  return `${f.art === 'login' ? 'TUWEL-Anmeldung fehlt: ' : 'Fehler beim letzten Lauf: '}${f.meldung} (${zeit(f.zeit)})`
}

// Ein einziger Hinweis: Seitenfehler, Lauf-Fehler, Warnung oder Zusammenfassung; alles Weitere aufklappbar
function StatusHinweis({ status, fehler, onSchliessen }) {
  if (!status && !fehler) return null
  const e = status?.letztes_ergebnis
  const laufFehler = status?.letzter_fehler

  let ton = 'erfolg'
  let titel
  if (fehler) {
    ton = 'fehler'
    titel = fehler
  } else if (laufFehler) {
    ton = 'fehler'
    titel = fehlerText(laufFehler)
  } else if (status.warnung) {
    ton = 'warnung'
    titel = status.warnung
  } else if (!status.letzter_erfolg) {
    ton = 'info'
    titel = 'Noch kein erfolgreicher Lauf – zuerst die Browser-Erweiterung einrichten.'
  } else {
    titel = [
      `Letzter Lauf ${zeit(status.letzter_erfolg)}`,
      e && `${e.neu} neu, ${e.geaendert} geändert`,
      `${status.dateien} Dateien, ${status.videos} Videos`,
      status.kurse_ohne_lva > 0 && `${status.kurse_ohne_lva} Kurse ohne LVA`,
    ]
      .filter(Boolean)
      .join(' · ')
  }

  return (
    <Hinweis ton={ton} titel={titel} onSchliessen={fehler ? onSchliessen : undefined}>
      {status && (
        <ul>
          {status.warnung && ton !== 'warnung' && <li>{status.warnung}</li>}
          {laufFehler && (fehler || ton !== 'fehler') && <li>{fehlerText(laufFehler)}</li>}
          <li>
            Letzter erfolgreicher Lauf: <strong>{zeit(status.letzter_erfolg)}</strong>
            {e && (
              <>
                {' '}
                – {e.kurse} Kurse, {e.neu} neu, {e.geaendert} geändert, {e.unveraendert} unverändert, {e.videos} neue Videos
              </>
            )}
          </li>
          <li>
            Gesamt: {status.dateien} Dateien, {status.videos} Video-Links aus {status.kurse} Kursen
            {status.kurse_ohne_lva > 0 && <> · {status.kurse_ohne_lva} Kurse ohne LVA (siehe „Kurse und LVAs“)</>}
          </li>
          {e?.hinweise?.length > 0 && (
            <li>
              Was der letzte Lauf gefunden hat:
              <ul>
                {e.hinweise.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
            </li>
          )}
        </ul>
      )}
    </Hinweis>
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
    <Karte aufklappbar offen={offen} titel="Browser-Erweiterung einrichten" className="tuwel-einrichtung">
      <div className="stapel">
        <p className="leise">
          Die Erweiterung liest TUWEL mit deiner Browser-Anmeldung und schickt neue oder geänderte Dateien an den Hub –
          täglich, beim Öffnen von TUWEL (höchstens alle 6 h) und auf Klick; Videos werden nur verlinkt.
        </p>
        <ol className="tuwel-schritte">
          <li>
            <strong>Chrome/Edge:</strong> <code>chrome://extensions</code> bzw. <code>edge://extensions</code> öffnen,
            „Entwicklermodus“ einschalten, „Entpackte Erweiterung laden“ und diesen Ordner wählen:
            <code className="tuwel-pfad">{daten.ordner}</code>
            <span className="leise klein">
              Firefox: <code>about:debugging#/runtime/this-firefox</code> – „Temporäres Add-on laden“ –{' '}
              <code>manifest.json</code> aus diesem Ordner (bleibt bis zum Neustart von Firefox aktiv).
            </span>
          </li>
          <li>
            Auf das Symbol der Erweiterung klicken, unter „Einstellungen“ diesen Schlüssel eintragen und „Speichern und
            prüfen“:
            <div className="tuwel-schluessel">
              <Eingabe readOnly aria-label="Schlüssel" value={daten.schluessel} onFocus={(e) => e.target.select()} />
              <Button icon={kopiert ? 'ok' : undefined} onClick={kopieren}>
                {kopiert ? 'Kopiert' : 'Kopieren'}
              </Button>
              <Menue
                eintraege={[
                  { name: 'Neuen Schlüssel erzeugen', icon: 'aktualisieren', title: 'Alten Schlüssel ungültig machen', onClick: neu },
                ]}
              />
            </div>
          </li>
        </ol>
        <p className="leise klein">
          Unterlagen landen in <code className="tuwel-pfad">{daten.unterlagen}</code> je Semester und LVA ein Ordner.
        </p>
      </div>
    </Karte>
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
  const ohneLva = kurse.filter((k) => k.zuordnung === 'auto' && !k.lva_id).length
  const aktiv = kurse.filter((k) => k.synchronisieren).length
  return (
    <Karte
      aufklappbar
      offen={ohneLva > 0}
      icon="tuwel"
      titel="Kurse und LVAs"
      aktionen={
        <>
          <span className="leise klein">
            {aktiv} von {kurse.length} synchronisiert
          </span>
          {ohneLva > 0 && <Badge ton="verwerfen" icon="warnung">{ohneLva} ohne LVA</Badge>}
        </>
      }
    >
      <p className="leise">Kurse werden über LVA-Nummer und Semester zugeordnet; nur zugeordnete Kurse werden synchronisiert.</p>
      <Tabelle>
        <thead>
          <tr>
            <th>TUWEL-Kurs</th>
            <th>LVA</th>
            <th>Zuordnung</th>
          </tr>
        </thead>
        <tbody>
          {kurse.map((k) => (
            <tr key={k.id} className={k.synchronisieren ? '' : 'gedimmt'}>
              <td className="tuwel-umbruch">
                {k.name}
                <div className="leise klein">{k.kurzname}</div>
              </td>
              <td className="tuwel-umbruch">{k.lva_name ? `${k.lva_name} (${k.lva_semester})` : '–'}</td>
              <td>
                <Auswahl aria-label={`Zuordnung für ${k.name}`} className="tuwel-zuordnung" value={wert(k)} onChange={(e) => aendern(k, e.target.value)}>
                  <option value="auto">automatisch{k.zuordnung === 'auto' && !k.lva_id ? ' (nichts gefunden)' : ''}</option>
                  <option value="aus">nicht synchronisieren</option>
                  {lvas.map((l) => (
                    <option key={l.id} value={String(l.id)}>
                      {l.kurzname || l.titel} ({l.semester})
                    </option>
                  ))}
                </Auswahl>
              </td>
            </tr>
          ))}
        </tbody>
      </Tabelle>
    </Karte>
  )
}

// Lernzeit einer Unterlage: leer = Schätzung, Zahl = eigene Minuten, 0 = nicht lernen
function LernzeitFeld({ dokument, onGeaendert }) {
  const speichern = (e) => {
    const wert = e.target.value === '' ? null : Math.max(0, Math.round(Number(e.target.value)))
    if (wert !== dokument.lern_minuten) api.dokumentLernzeit(dokument.id, wert).then(onGeaendert)
  }
  return (
    <span className="tuwel-lernzeit" title={`Schätzung: ${dokument.lern_minuten_geschaetzt} min`}>
      <Eingabe
        type="number"
        breite="schmal"
        min="0"
        step="5"
        aria-label={`Lernzeit in Minuten für ${dokument.dateiname}`}
        key={dokument.lern_minuten ?? 'auto'}
        defaultValue={dokument.lern_minuten ?? ''}
        placeholder={String(dokument.lern_minuten_geschaetzt)}
        onBlur={speichern}
      />
      <span className="leise klein">min{dokument.lern_minuten === 0 && ' · nicht lernen'}</span>
    </span>
  )
}

function Unterlagen({ dokumente: alle, lvas, onGeaendert }) {
  // offizielle (TUWEL) und inoffizielle Unterlagen (MB Cloud der Fachschaft) getrennt filterbar
  const [quelle, setQuelle] = useState('alle')
  const dokumente = useMemo(() => alle.filter((d) => quelle === 'alle' || (d.quelle || 'tuwel') === quelle), [alle, quelle])
  const nachLva = useMemo(() => {
    const gruppen = new Map()
    for (const d of dokumente) {
      if (!gruppen.has(d.lva_id)) gruppen.set(d.lva_id, [])
      gruppen.get(d.lva_id).push(d)
    }
    return gruppen
  }, [dokumente])
  if (alle.length === 0) return null
  const lvaName = (id) => {
    const l = lvas.find((x) => x.id === id)
    return l ? `${l.kurzname || l.titel} (${l.semester})` : `LVA ${id}`
  }
  return (
    <section className="stapel">
      <div className="tuwel-kopf">
        <div>
          <h2>Unterlagen</h2>
          <p className="leise klein">Je LVA neueste zuerst; „neu“ und „geändert“ markieren, was der letzte Sync gebracht hat.</p>
        </div>
        <Auswahl
          aria-label="Quelle"
          breite="mittel"
          value={quelle}
          onChange={(e) => setQuelle(e.target.value)}
          optionen={[
            { wert: 'alle', name: 'alle Quellen' },
            { wert: 'tuwel', name: 'nur offiziell (TUWEL)' },
            { wert: 'mbcloud', name: 'nur MB Cloud (inoffiziell)' },
          ]}
        />
      </div>
      <div>
        {[...nachLva.entries()].map(([lvaId, liste]) => {
          // Die API liefert bereits nach Erscheinungsdatum sortiert (neueste zuerst, ohne Datum am Ende)
          const dateien = liste.filter((d) => !d.ist_link)
          const videos = liste.filter((d) => d.ist_link)
          const dauer = videos.reduce((summe, v) => summe + (v.dauer_sekunden || 0), 0)
          const ohneDauer = videos.filter((v) => !v.dauer_sekunden).length
          const frisch = liste.filter((d) => d.neu_seit_sync).length
          return (
            <Karte
              key={lvaId}
              aufklappbar
              className="tuwel-lva"
              titel={lvaName(lvaId)}
              aktionen={
                <>
                  <span className="leise klein">
                    {dateien.length} Dateien
                    {videos.length > 0 && ` · ${videoZusammenfassung(videos.length, dauer, ohneDauer)}`}
                  </span>
                  {frisch > 0 && <Badge ton="primaer">{frisch} neu/geändert</Badge>}
                </>
              }
            >
              <div className="stapel">
                {dateien.length > 0 && (
                  <Tabelle>
                    <thead>
                      <tr>
                        <th>Datei</th>
                        <th>Erschienen</th>
                        <th>Sync</th>
                        <th>Abschnitt</th>
                        <th>Typ</th>
                        <th title={LERNZEIT_HILFE}>Lernzeit</th>
                        <th className="zahl">Größe</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dateien.map((d) => (
                        <tr key={d.id} className={d.neu_seit_sync ? 'tuwel-frisch' : ''}>
                          <td className="tuwel-datei">
                            <Herkunft dokument={d} />
                            <Marke dokument={d} />
                            <a href={api.dokumentUrl(d.id)} target="_blank" rel="noreferrer">
                              {d.dateiname}
                            </a>
                          </td>
                          <td>
                            <Erschienen dokument={d} />
                          </td>
                          <td className="leise klein">{zeit(d.sync_am)}</td>
                          <td className="leise klein tuwel-umbruch">{d.abschnitt}</td>
                          <td>
                            {TYP_NAME[d.typ] || d.typ}
                            {d.seiten ? <span className="leise klein"> · {d.seiten} S.</span> : null}
                          </td>
                          <td>
                            <LernzeitFeld dokument={d} onGeaendert={onGeaendert} />
                          </td>
                          <td className="leise klein zahl">{groesse(d.groesse)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Tabelle>
                )}
                {videos.length > 0 && (
                  <>
                    <h3 className="tuwel-unterkopf">
                      <Icon name="aufzeichnung" />
                      Aufzeichnungen
                    </h3>
                    <Tabelle>
                      <thead>
                        <tr>
                          <th>Titel</th>
                          <th>Erschienen</th>
                          <th>Sync</th>
                          <th>Dauer</th>
                          <th title={LERNZEIT_HILFE}>Lernzeit</th>
                          <th>Abschnitt</th>
                        </tr>
                      </thead>
                      <tbody>
                        {videos.map((v) => (
                          <tr key={v.id} className={v.neu_seit_sync ? 'tuwel-frisch' : ''}>
                            <td className="tuwel-datei">
                              <Marke dokument={v} />
                              <a href={v.url} target="_blank" rel="noreferrer">
                                {v.dateiname}
                              </a>
                              {v.medien_url && (
                                <a className="klein tuwel-medien" href={v.medien_url} target="_blank" rel="noreferrer" title="Videodatei direkt (Link kann ablaufen)">
                                  <Icon name="laden" />
                                  Datei
                                </a>
                              )}
                            </td>
                            <td>
                              <Erschienen dokument={v} />
                            </td>
                            <td className="leise klein">{zeit(v.sync_am)}</td>
                            <td>{laufzeit(v.dauer_sekunden) || <span className="leise klein">unbekannt</span>}</td>
                            <td>
                              <LernzeitFeld dokument={v} onGeaendert={onGeaendert} />
                            </td>
                            <td className="leise klein tuwel-umbruch">{v.abschnitt}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Tabelle>
                  </>
                )}
              </div>
            </Karte>
          )
        })}
      </div>
    </section>
  )
}

// Woher das Erscheinungsdatum stammt
const QUELLEN = {
  tuwel: { kurz: 'TUWEL', lang: 'Datum, das TUWEL für die Aktivität meldet (hinzugefügt/geändert)' },
  'last-modified': { kurz: 'Datei', lang: 'Last-Modified-Angabe der Datei' },
  aufnahme: { kurz: 'Aufnahme', lang: 'Aufnahmedatum der Aufzeichnung' },
  mbcloud: { kurz: 'MB Cloud', lang: 'Prüfungsdatum aus dem Dateinamen, sonst Änderungsdatum in der MB Cloud' },
}

const KATEGORIE_KURZ = {
  altpruefung: 'Altprüfung', loesung: 'Lösung', ausarbeitung: 'Ausarbeitung', mitschrift: 'Mitschrift',
  formelsammlung: 'Formelsammlung', sonstiges: 'Sonstiges',
}

// Inoffizielle Unterlage aus der MB Cloud: Quelle, Kategorie und Jahr sichtbar
function Herkunft({ dokument }) {
  if (dokument.quelle !== 'mbcloud') return null
  return (
    <Badge ton="umriss" icon="mbcloud" title="Inoffiziell: MB Cloud der Fachschaft Maschinenbau">
      {KATEGORIE_KURZ[dokument.kategorie] || 'Sonstiges'}
      {dokument.jahr ? ` · ${dokument.jahr}` : ''}
    </Badge>
  )
}

function Erschienen({ dokument }) {
  if (!dokument.erschienen_am) return <span className="leise" title="Noch kein Datum – kommt beim nächsten Sync">–</span>
  const quelle = QUELLEN[dokument.erschienen_quelle] || { kurz: dokument.erschienen_quelle, lang: '' }
  // Aufnahmedaten haben keine Uhrzeit
  const text = dokument.erschienen_quelle === 'aufnahme' ? tag(dokument.erschienen_am) : zeit(dokument.erschienen_am)
  return (
    <span className="tuwel-erschienen" title={`Quelle: ${quelle.lang}`}>
      {text}
      <span className="leise klein">{quelle.kurz}</span>
    </span>
  )
}

function Marke({ dokument }) {
  if (!dokument.neu_seit_sync) return null
  return <Badge ton="primaer">{dokument.status === 'geaendert' ? 'geändert' : 'neu'}</Badge>
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
      <SeitenKopf titel="TUWEL">Unterlagen und Aufzeichnungen deiner TUWEL-Kurse, geholt von der Browser-Erweiterung.</SeitenKopf>
      <StatusHinweis status={status} fehler={fehler} onSchliessen={() => setFehler(null)} />
      <div>
        <Einrichtung offen={status && !status.letzter_erfolg} />
        <KursZuordnung kurse={kurse} lvas={lvas} onGeaendert={laden} setFehler={setFehler} />
      </div>
      <Unterlagen dokumente={dokumente} lvas={lvas} onGeaendert={laden} />
    </div>
  )
}
