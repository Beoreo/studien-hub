import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { Auswahl, Badge, Button, Eingabe, Feld, Hinweis, Karte, SeitenKopf, Tabelle } from '../ui.jsx'
import './MbCloud.css'

const KATEGORIEN = [
  { wert: 'altpruefung', name: 'Altprüfungen' },
  { wert: 'loesung', name: 'Lösungen' },
  { wert: 'formelsammlung', name: 'Formelsammlungen' },
  { wert: 'ausarbeitung', name: 'Ausarbeitungen' },
  { wert: 'mitschrift', name: 'Mitschriften' },
  { wert: 'sonstiges', name: 'Sonstiges' },
]

const zeit = (iso) => (iso ? new Date(iso).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' }) : '–')
const groesse = (b) => (b == null ? '' : b < 1e6 ? `${Math.max(1, Math.round(b / 1e3))} KB` : `${(b / 1e6).toFixed(1).replace('.', ',')} MB`)

// MB Cloud der Fachschaft: inoffizielle Quelle (Altprüfungen, Lösungen, Ausarbeitungen …), nur lokal gespeichert
export default function MbCloud({ lvas }) {
  const [status, setStatus] = useState(null)
  const [ordner, setOrdner] = useState([])
  const [fehler, setFehler] = useState(null)
  const [lvaId, setLvaId] = useState(null)

  const laden = useCallback(() => {
    Promise.all([api.mbcloudStatus(), api.mbcloudOrdner()])
      .then(([s, o]) => {
        setStatus(s)
        setOrdner(o)
      })
      .catch((e) => setFehler(e.message))
  }, [])
  useEffect(laden, [laden])

  // Während eines Laufs oder einer offenen Anmeldung regelmäßig nachsehen
  useEffect(() => {
    if (!status || !(status.laeuft || status.anmeldung_offen)) return
    const zeitgeber = setInterval(async () => {
      if (status.anmeldung_offen) await api.mbcloudVerbindenPruefen().catch(() => {})
      laden()
    }, 3000)
    return () => clearInterval(zeitgeber)
  }, [status, laden])

  const ausfuehren = (aufruf) => aufruf.then(laden).catch((e) => setFehler(e.message))

  async function verbinden() {
    try {
      const { login_url } = await api.mbcloudVerbinden()
      window.open(login_url, '_blank', 'noopener')
      laden()
    } catch (e) {
      setFehler(e.message)
    }
  }

  const besuchte = lvas.filter((l) => l.besucht)
  const zugeordnet = useMemo(() => {
    const ids = new Set(ordner.filter((o) => o.lva_id && ['auto', 'bestaetigt'].includes(o.zuordnung)).map((o) => o.lva_id))
    return lvas.filter((l) => ids.has(l.id))
  }, [ordner, lvas])
  const vorschlaege = ordner.filter((o) => o.zuordnung === 'vorschlag')

  if (!status) return <p className="seite leise">Lade …</p>

  // Ein Hauptbutton: verbunden → abgleichen, sonst verbinden
  const aktion = status.verbunden ? (
    <>
      <Button onClick={verbinden}>Neu verbinden</Button>
      <Button variante="primaer" icon="aktualisieren" onClick={() => ausfuehren(api.mbcloudLauf())} disabled={status.laeuft}>
        {status.laeuft ? 'Läuft …' : 'Jetzt abgleichen'}
      </Button>
    </>
  ) : (
    <Button variante="primaer" icon="mbcloud" onClick={verbinden}>
      Verbinden
    </Button>
  )

  // Höchstens ein Hinweis: Fehler vor Anmeldung vor Status
  const arbeitsweise = (
    <p>
      Der Hub liest regelmäßig nur das Verzeichnis und lädt automatisch Altprüfungen, Lösungen und Formelsammlungen der letzten 5
      Jahre für besuchte LVAs – schonend, eine Datei nach der anderen. Die Dateien bleiben nur auf diesem Rechner.
    </p>
  )
  let hinweis
  if (fehler) {
    hinweis = <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} />
  } else if (status.anmeldung_offen) {
    hinweis = <Hinweis titel="Warte auf die Bestätigung im Browser …" />
  } else if (!status.verbunden) {
    hinweis = (
      <Hinweis titel="Noch nicht verbunden: „Verbinden“ öffnet die MB Cloud zur Anmeldung mit dem TU Login.">
        <p>
          Nach der Anmeldung den Zugriff erlauben. Der Hub bekommt ein eigenes App-Passwort (in der MB Cloud unter Einstellungen /
          Sicherheit widerrufbar) und speichert es nur in der <code>.env</code>.
        </p>
        {arbeitsweise}
      </Hinweis>
    )
  } else {
    const b = status.bericht
    hinweis = (
      <Hinweis
        ton={status.letzter_fehler ? 'fehler' : 'info'}
        titel={
          status.letzter_fehler
            ? `Letzter Abgleich ${zeit(status.letzter_lauf)} fehlgeschlagen`
            : `${status.laeuft ? 'Abgleich läuft' : `Letzter Abgleich ${zeit(status.letzter_lauf)}`} · ${status.dateien} Dateien · ${status.heruntergeladen} heruntergeladen`
        }
      >
        {status.letzter_fehler && <p className="mbcloud-umbruch">{status.letzter_fehler}</p>}
        <ul>
          <li>
            Verbunden mit{' '}
            <a href={status.url} target="_blank" rel="noreferrer">
              {status.url}
            </a>{' '}
            als {status.benutzer}, Ordner <code>{status.wurzel}</code>
          </li>
          <li>
            {status.ordner} LVA-Ordner, {status.dateien} Dateien im Index, {status.heruntergeladen} heruntergeladen
          </li>
          {b && (
            <li>
              Zuletzt {b.neue_dateien} neu, {b.heruntergeladen} geladen, {b.duplikate} Duplikate, {b.anfragen} Anfragen
            </li>
          )}
        </ul>
        {arbeitsweise}
      </Hinweis>
    )
  }

  return (
    <div className="seite mbcloud">
      <SeitenKopf
        titel={
          <span className="mit-icon">
            MB Cloud
            <Badge ton="umriss" icon="mbcloud" title="Unterlagen von Studierenden, keine offizielle Quelle">
              inoffiziell
            </Badge>
          </span>
        }
        aktion={aktion}
      >
        Altprüfungen, Lösungen und Ausarbeitungen von Studierenden der Fachschaft Maschinenbau.
      </SeitenKopf>
      {hinweis}

      {vorschlaege.length > 0 && (
        <Karte titel={`Zuordnung bestätigen (${vorschlaege.length})`}>
          <p className="leise">Diese Ordner passen nur dem Titel nach. Deine Entscheidung gilt auch für künftige Dateien im Ordner.</p>
          <OrdnerTabelle ordner={vorschlaege} lvas={besuchte.length ? besuchte : lvas} ausfuehren={ausfuehren} />
        </Karte>
      )}

      <section className="stapel">
        <h2>Unterlagen je LVA</h2>
        {zugeordnet.length === 0 ? (
          <p className="leise">Noch keine Ordner zugeordnet – erst verbinden und abgleichen.</p>
        ) : (
          <Treffer
            lvaId={lvaId}
            onFehler={setFehler}
            auswahl={
              <Feld label="LVA">
                <Auswahl breite="mittel" className="mbcloud-lva" value={lvaId ?? ''} onChange={(e) => setLvaId(Number(e.target.value) || null)}>
                  <option value="">– LVA wählen –</option>
                  {zugeordnet.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.kurzname || l.titel}
                      {!l.besucht && ' (ausgeblendet)'}
                    </option>
                  ))}
                </Auswahl>
              </Feld>
            }
          />
        )}
      </section>

      <Karte aufklappbar titel={`Alle Ordner der MB Cloud (${ordner.length}) – von Hand zuordnen`}>
        <OrdnerTabelle ordner={ordner} lvas={lvas} ausfuehren={ausfuehren} alle />
      </Karte>
    </div>
  )
}

const ZUORDNUNG = {
  auto: { text: 'sicher (Nummer)', ton: 'neutral' },
  vorschlag: { text: 'Vorschlag', ton: 'umriss' },
  bestaetigt: { text: 'bestätigt', ton: 'bestaetigen' },
  abgelehnt: { text: 'abgelehnt', ton: 'neutral' },
}

function OrdnerTabelle({ ordner, lvas, ausfuehren, alle = false }) {
  const [wahl, setWahl] = useState({})
  return (
    <Tabelle>
      <thead>
        <tr>
          <th>Ordner in der MB Cloud</th>
          <th>LVA</th>
          {alle && <th>Status</th>}
          <th />
        </tr>
      </thead>
      <tbody>
        {ordner.map((o) => {
          const gewaehlt = wahl[o.id] ?? o.lva_id ?? ''
          const zuordnung = ZUORDNUNG[o.zuordnung]
          const zusatz = [
            o.dateien > 0 && `${o.dateien} Dateien`,
            o.aehnlichkeit != null && o.zuordnung === 'vorschlag' && `${Math.round(o.aehnlichkeit * 100)} % ähnlich`,
          ].filter(Boolean)
          return (
            <tr key={o.id} className={o.zuordnung === 'abgelehnt' ? 'gedimmt' : undefined}>
              <td>
                {o.name}
                {zusatz.length > 0 && <div className="leise klein">{zusatz.join(' · ')}</div>}
              </td>
              <td>
                <Auswahl
                  className="mbcloud-lva"
                  aria-label={`LVA für ${o.name}`}
                  value={gewaehlt}
                  onChange={(e) => setWahl({ ...wahl, [o.id]: Number(e.target.value) || '' })}
                >
                  <option value="">– keine –</option>
                  {lvas.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.kurzname || l.titel} ({l.semester})
                    </option>
                  ))}
                </Auswahl>
              </td>
              {alle && <td>{zuordnung ? <Badge ton={zuordnung.ton}>{zuordnung.text}</Badge> : '–'}</td>}
              <td>
                <div className="knopf-gruppe mbcloud-nowrap">
                  <Button
                    klein
                    variante={alle ? 'umriss' : 'bestaetigen'}
                    disabled={!gewaehlt}
                    onClick={() => ausfuehren(api.mbcloudOrdnerZuordnen(o.id, { lva_id: gewaehlt, zuordnung: 'bestaetigt' }))}
                  >
                    Bestätigen
                  </Button>
                  {o.zuordnung !== 'abgelehnt' && (
                    <Button klein onClick={() => ausfuehren(api.mbcloudOrdnerZuordnen(o.id, { zuordnung: 'abgelehnt' }))}>
                      Ablehnen
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          )
        })}
      </tbody>
    </Tabelle>
  )
}

function Treffer({ lvaId, onFehler, auswahl }) {
  const [dateien, setDateien] = useState(null)
  const [laedt, setLaedt] = useState(null)
  const [filter, setFilter] = useState('')

  const laden = useCallback(() => {
    if (!lvaId) return
    api.mbcloudDateien(lvaId).then(setDateien).catch((e) => onFehler(e.message))
  }, [lvaId, onFehler])
  useEffect(laden, [laden])

  const kopf = (
    <div className="formular-zeile">
      {auswahl}
      {lvaId && (
        <Feld label="Dateiname">
          <Eingabe breite="mittel" type="search" placeholder="filtern …" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </Feld>
      )}
    </div>
  )
  if (!lvaId) return kopf
  if (!dateien) {
    return (
      <>
        {kopf}
        <p className="leise">Lade …</p>
      </>
    )
  }
  const nachId = new Map(dateien.map((d) => [d.id, d]))
  const sichtbar = dateien.filter((d) => !filter || d.name.toLowerCase().includes(filter.toLowerCase()))

  async function herunterladen(d) {
    setLaedt(d.id)
    try {
      await api.mbcloudDateiLaden(d.id)
      laden()
    } catch (e) {
      onFehler(e.message)
    } finally {
      setLaedt(null)
    }
  }

  return (
    <>
      {kopf}
      <div>
        {KATEGORIEN.map((k) => {
          const liste = sichtbar.filter((d) => d.kategorie === k.wert)
          if (!liste.length) return null
          return (
            <Karte
              key={`${lvaId}-${k.wert}`}
              aufklappbar
              icon="mbcloud"
              offen={['altpruefung', 'loesung', 'formelsammlung'].includes(k.wert)}
              titel={`${k.name} (${liste.length}, ${liste.filter((d) => d.dokument_id).length} geladen)`}
            >
              <Tabelle>
                <thead>
                  <tr>
                    <th>Datei</th>
                    <th>Datum / Jahr</th>
                    <th>Ordner</th>
                    <th className="zahl">Größe</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {liste.map((d) => (
                    <tr key={d.id}>
                      <td className="mbcloud-datei">
                        <div className="reihe mbcloud-eng">
                          {d.dokument_id && !d.duplikat ? (
                            <a href={api.dokumentUrl(d.dokument_id)} target="_blank" rel="noreferrer">
                              {d.name}
                            </a>
                          ) : (
                            <span>{d.name}</span>
                          )}
                          {d.gedankenprotokoll && (
                            <Badge title="Aus dem Gedächtnis notiert, keine Originalangabe">Gedankenprotokoll</Badge>
                          )}
                          {dateien.some((x) => x.loesung_zu_id === d.id) && <Badge>mit Lösung</Badge>}
                        </div>
                        {d.loesung_zu_id && nachId.get(d.loesung_zu_id) && (
                          <div className="leise klein">Lösung zu {nachId.get(d.loesung_zu_id).name}</div>
                        )}
                      </td>
                      <td className="mbcloud-nowrap">
                        {d.datum ? new Date(d.datum).toLocaleDateString('de-AT') : d.jahr || '–'}
                        {d.jahr_geschaetzt && (
                          <span className="leise klein" title="Nur aus dem Änderungsdatum der Datei">
                            {' '}
                            (geschätzt)
                          </span>
                        )}
                      </td>
                      <td className="leise">{d.unterordner}</td>
                      <td className="zahl leise">{groesse(d.groesse)}</td>
                      <td>
                        {d.duplikat ? (
                          <span className="leise klein mbcloud-nowrap" title="Gleicher Inhalt (Prüfsumme) schon vorhanden">
                            schon da ({d.duplikat_von === 'tuwel' ? 'TUWEL' : 'MB Cloud'})
                          </span>
                        ) : d.dokument_id ? (
                          d.kategorie === 'altpruefung' ? (
                            <Bearbeitung datei={d} onGeaendert={laden} onFehler={onFehler} />
                          ) : (
                            <span className="leise klein">geladen</span>
                          )
                        ) : (
                          <Button
                            klein
                            icon="laden"
                            disabled={laedt === d.id}
                            title={d.automatisch ? 'Kommt beim nächsten Abgleich auch automatisch' : undefined}
                            onClick={() => herunterladen(d)}
                          >
                            {laedt === d.id ? 'lädt …' : 'Laden'}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Tabelle>
            </Karte>
          )
        })}
      </div>
    </>
  )
}

// Altprüfung erledigt: Zeitbedarf und erreichte Punkte
function Bearbeitung({ datei, onGeaendert, onFehler }) {
  const [offen, setOffen] = useState(false)
  const [werte, setWerte] = useState({ minuten: datei.bearbeitet_minuten ?? '', punkte: datei.punkte ?? '', punkte_max: datei.punkte_max ?? '' })
  const zahl = (v) => (v === '' ? null : Number(v))
  const speichern = (erledigt) =>
    api
      .altpruefungBearbeitet(datei.dokument_id, {
        erledigt,
        minuten: zahl(werte.minuten),
        punkte: zahl(werte.punkte),
        punkte_max: zahl(werte.punkte_max),
      })
      .then(() => {
        setOffen(false)
        onGeaendert()
      })
      .catch((e) => onFehler(e.message))

  if (datei.bearbeitet_am && !offen) {
    return (
      <div className="knopf-gruppe mbcloud-nowrap">
        <Badge ton="bestaetigen" icon="erledigt">
          erledigt
          {datei.punkte != null && ` · ${datei.punkte}${datei.punkte_max ? `/${datei.punkte_max}` : ''} P.`}
          {datei.bearbeitet_minuten != null && ` · ${datei.bearbeitet_minuten} min`}
        </Badge>
        <Button klein onClick={() => setOffen(true)}>
          Ändern
        </Button>
      </div>
    )
  }
  if (!offen) {
    return (
      <Button klein icon="erledigt" title="Als erledigt markieren (Zeit und Punkte)" onClick={() => setOffen(true)}>
        Erledigt …
      </Button>
    )
  }
  return (
    <div className="knopf-gruppe mbcloud-nowrap">
      <Eingabe
        className="mbcloud-zahl"
        type="number"
        min="0"
        placeholder="min"
        aria-label="Minuten"
        value={werte.minuten}
        onChange={(e) => setWerte({ ...werte, minuten: e.target.value })}
      />
      <Eingabe
        className="mbcloud-zahl"
        type="number"
        min="0"
        step="0.5"
        placeholder="Punkte"
        aria-label="Erreichte Punkte"
        value={werte.punkte}
        onChange={(e) => setWerte({ ...werte, punkte: e.target.value })}
      />
      <span className="leise">von</span>
      <Eingabe
        className="mbcloud-zahl"
        type="number"
        min="0"
        step="0.5"
        placeholder="max"
        aria-label="Höchstpunkte"
        value={werte.punkte_max}
        onChange={(e) => setWerte({ ...werte, punkte_max: e.target.value })}
      />
      <Button klein variante="bestaetigen" onClick={() => speichern(true)}>
        Speichern
      </Button>
      {datei.bearbeitet_am && (
        <Button klein onClick={() => speichern(false)}>
          Nicht erledigt
        </Button>
      )}
    </div>
  )
}
