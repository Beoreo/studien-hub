import { useEffect, useState } from 'react'
import { api, WOCHENTAGE } from '../api.js'

const STANDARD_REGEL = {
  stunden_pro_woche: 20,
  tage: [0, 1, 2, 3, 4],
  bevorzugte_tage: [],
  fruehester_beginn: '08:00',
  spaetestes_ende: '18:00',
  min_block_minuten: 120,
  max_block_minuten: 480,
  puffer_minuten: 30,
  arbeitgeber: '',
  freie_tage: [],
  max_tag_stunden: 9,
  lernfenster_minuten: 120,
  voller_unitag_stunden: 6,
  min_freie_tage: 1,
  gewichte: { gleichmaessig: 5, buendeln: 5, lernzeit: 5, erholung: 5, zerstueckelung: 5 },
}

// Kriterien der entspannten Woche, je 0 (egal) bis 10 (sehr wichtig)
const KRITERIEN = [
  { feld: 'gleichmaessig', name: 'Gleichmäßige Last', hilfe: 'Uni plus Arbeit pro Tag möglichst ähnlich' },
  { feld: 'buendeln', name: 'Ganze Tage bündeln', hilfe: 'Arbeit an Tagen ohne Uni, wenige Wechsel' },
  { feld: 'lernzeit', name: 'Lernzeit schützen', hilfe: 'Tag vor Prüfung oder Abgabe arbeitsfrei halten' },
  { feld: 'erholung', name: 'Erholung', hilfe: 'komplett freie Tage pro Woche' },
  { feld: 'zerstueckelung', name: 'Keine Zerstückelung', hilfe: 'lieber wenige lange Blöcke' },
]

function EntspannteWoche({ regel, setRegel }) {
  const zahl = (feld) => (e) => setRegel({ ...regel, [feld]: Number(e.target.value) })
  const gewicht = (feld) => (e) => setRegel({ ...regel, gewichte: { ...regel.gewichte, [feld]: Number(e.target.value) } })
  return (
    <fieldset className="kriterien">
      <legend>Entspannte Woche</legend>
      <p className="hinweis">
        Der Vorschlag bewertet jede mögliche Verteilung und wählt die beste. Diese Grenzen gelten immer:
      </p>
      <label>
        Höchstens Uni + Arbeit pro Tag (Stunden)
        <input type="number" min="1" max="24" step="0.5" value={regel.max_tag_stunden} onChange={zahl('max_tag_stunden')} />
      </label>
      <label>
        Lernfenster nach Vorlesungen und vor Prüfungen/Abgaben (Minuten)
        <input type="number" min="0" step="15" value={regel.lernfenster_minuten} onChange={zahl('lernfenster_minuten')} />
      </label>
      <label>
        Voller Unitag ab (Stunden) – danach kein Arbeitsblock am Abend
        <input type="number" min="0" max="24" step="0.5" value={regel.voller_unitag_stunden} onChange={zahl('voller_unitag_stunden')} />
      </label>
      <label>
        Komplett freie Tage pro Woche (mindestens)
        <input type="number" min="0" max="7" step="1" value={regel.min_freie_tage} onChange={zahl('min_freie_tage')} />
      </label>
      <p className="hinweis">Gewichtung – wie wichtig ist dir …</p>
      {KRITERIEN.map((k) => (
        <label key={k.feld} className="regler" title={k.hilfe}>
          <span>
            {k.name} <span className="hinweis">({k.hilfe})</span>
          </span>
          <span className="zeile">
            <input type="range" min="0" max="10" step="1" value={regel.gewichte[k.feld]} onChange={gewicht(k.feld)} />
            <output>{regel.gewichte[k.feld]}</output>
          </span>
        </label>
      ))}
    </fieldset>
  )
}

const formatiere = (iso) => new Date(iso).toLocaleDateString('de-AT')

// Zusätzliche freie Tage neben den gesetzlichen Feiertagen (die kommen automatisch dazu)
function FreieTage({ werte, onChange }) {
  const [neu, setNeu] = useState({ von: '', bis: '', bezeichnung: '', jaehrlich: false })
  const setze = (feld) => (e) => setNeu({ ...neu, [feld]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const hinzufuegen = () => {
    if (!neu.von) return
    onChange([...werte, { ...neu, bis: neu.bis || null, bezeichnung: neu.bezeichnung || null }])
    setNeu({ von: '', bis: '', bezeichnung: '', jaehrlich: false })
  }

  return (
    <div>
      {werte.length > 0 && (
        <table className="freie-tage">
          <tbody>
            {werte.map((f, i) => (
              <tr key={i}>
                <td>
                  {f.jaehrlich ? formatiere(f.von).replace(/\d{4}$/, '') : formatiere(f.von)}
                  {f.bis && f.bis !== f.von && <> – {f.jaehrlich ? formatiere(f.bis).replace(/\d{4}$/, '') : formatiere(f.bis)}</>}
                </td>
                <td>{f.bezeichnung || 'frei'}</td>
                <td>{f.jaehrlich && 'jährlich'}</td>
                <td>
                  <button type="button" className="klein" onClick={() => onChange(werte.filter((_, j) => j !== i))}>
                    entfernen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <span className="zeile">
        <input type="date" value={neu.von} onChange={setze('von')} title="von" />
        <input type="date" value={neu.bis} min={neu.von} onChange={setze('bis')} title="bis (optional)" />
        <input value={neu.bezeichnung} onChange={setze('bezeichnung')} placeholder="z. B. Urlaub" />
      </span>
      <span className="zeile">
        <label className="inline">
          <input type="checkbox" checked={neu.jaehrlich} onChange={setze('jaehrlich')} />
          jedes Jahr (z. B. 24.12.)
        </label>
        <button type="button" className="klein" onClick={hinzufuegen} disabled={!neu.von}>
          hinzufügen
        </button>
      </span>
    </div>
  )
}

function TagAuswahl({ werte, onChange }) {
  return (
    <span className="tage">
      {WOCHENTAGE.map((name, i) => (
        <label key={i}>
          <input
            type="checkbox"
            checked={werte.includes(i)}
            onChange={() => onChange(werte.includes(i) ? werte.filter((w) => w !== i) : [...werte, i].sort())}
          />
          {name}
        </label>
      ))}
    </span>
  )
}

const kurzeZeit = (t) => (t ? t.slice(0, 5) : t)
const datum = (d) => new Date(d).toLocaleDateString('de-AT')

function RegelFormular({ setMeldung }) {
  const [regel, setRegel] = useState(null)

  useEffect(() => {
    api
      .regel()
      .then((r) =>
        setRegel(
          r
            ? {
                ...STANDARD_REGEL,
                ...r,
                gewichte: { ...STANDARD_REGEL.gewichte, ...(r.gewichte || {}) },
                fruehester_beginn: kurzeZeit(r.fruehester_beginn),
                spaetestes_ende: kurzeZeit(r.spaetestes_ende),
                arbeitgeber: r.arbeitgeber || '',
                freie_tage: r.freie_tage || [],
              }
            : STANDARD_REGEL,
        ),
      )
      .catch((e) => setMeldung({ art: 'fehler', text: e.message }))
  }, [setMeldung])

  if (!regel) return <p>Lade …</p>
  const setze = (feld) => (e) => setRegel({ ...regel, [feld]: e.target.type === 'number' ? Number(e.target.value) : e.target.value })

  const speichern = (e) => {
    e.preventDefault()
    api
      .regelSpeichern({ ...regel, arbeitgeber: regel.arbeitgeber || null })
      .then(() => setMeldung({ art: 'ok', text: 'Arbeitsregel gespeichert. Im Kalender „Arbeitszeit vorschlagen“ klicken.' }))
      .catch((e) => setMeldung({ art: 'fehler', text: e.message }))
  }

  return (
    <form className="formular" onSubmit={speichern}>
      <h2>Arbeitsregel</h2>
      <p className="hinweis">
        Die Wochenstunden sind die Gesamtstunden. Bestätigte und fixe Blöcke werden abgezogen, der Rest wird automatisch in
        freie Lücken verteilt.
      </p>
      <label>
        Stunden pro Woche
        <input type="number" min="0" max="80" step="0.25" value={regel.stunden_pro_woche} onChange={setze('stunden_pro_woche')} />
      </label>
      <label>
        Mögliche Tage
        <TagAuswahl werte={regel.tage} onChange={(tage) => setRegel({ ...regel, tage })} />
      </label>
      <label>
        Bevorzugte Tage
        <TagAuswahl werte={regel.bevorzugte_tage} onChange={(t) => setRegel({ ...regel, bevorzugte_tage: t })} />
      </label>
      <label>
        Frühester Beginn
        <input type="time" step="900" value={regel.fruehester_beginn} onChange={setze('fruehester_beginn')} />
      </label>
      <label>
        Spätestes Ende
        <input type="time" step="900" value={regel.spaetestes_ende} onChange={setze('spaetestes_ende')} />
      </label>
      <label>
        Mindestlänge pro Block (Minuten)
        <input type="number" min="15" step="15" value={regel.min_block_minuten} onChange={setze('min_block_minuten')} />
      </label>
      <label>
        Maximallänge pro Block (Minuten)
        <input type="number" min="15" step="15" value={regel.max_block_minuten} onChange={setze('max_block_minuten')} />
      </label>
      <label>
        Puffer für den Weg (Minuten)
        <input type="number" min="0" step="5" value={regel.puffer_minuten} onChange={setze('puffer_minuten')} />
      </label>
      <label>
        Arbeitgeber
        <input value={regel.arbeitgeber} onChange={setze('arbeitgeber')} />
      </label>
      <EntspannteWoche regel={regel} setRegel={setRegel} />
      <div className="feld">
        <span>Zusätzliche freie Tage</span>
        <p className="hinweis">
          Gesetzliche Feiertage in Österreich sind automatisch gesperrt. Hier kommen weitere Tage dazu, an denen keine
          Arbeitszeit vorgeschlagen wird. Änderungen gelten nach „Speichern“.
        </p>
        <FreieTage werte={regel.freie_tage} onChange={(freie_tage) => setRegel({ ...regel, freie_tage })} />
      </div>
      <button type="submit">Speichern</button>
    </form>
  )
}

function SerienVerwaltung({ setMeldung }) {
  const heute = new Date().toISOString().slice(0, 10)
  const [serien, setSerien] = useState([])
  const [neu, setNeu] = useState({ wochentage: [], beginn: '08:00', ende: '12:00', von: heute, bis: heute, notiz: '' })

  const laden = () => api.serien().then(setSerien).catch((e) => setMeldung({ art: 'fehler', text: e.message }))
  useEffect(() => {
    laden()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const anlegen = (e) => {
    e.preventDefault()
    api
      .serieAnlegen({ ...neu, notiz: neu.notiz || null })
      .then((bloecke) => {
        setMeldung({ art: 'ok', text: `${bloecke.length} fixe Arbeitsblöcke angelegt.` })
        laden()
      })
      .catch((e) => setMeldung({ art: 'fehler', text: e.message }))
  }

  const loeschen = (serie, ab) =>
    api
      .serieLoeschen(serie.serie_id, ab)
      .then(laden)
      .catch((e) => setMeldung({ art: 'fehler', text: e.message }))

  const setze = (feld) => (e) => setNeu({ ...neu, [feld]: e.target.value })

  return (
    <div className="formular">
      <h2>Fixe Arbeitszeiten (Serie)</h2>
      <form onSubmit={anlegen}>
        <label>
          Wochentage
          <TagAuswahl werte={neu.wochentage} onChange={(w) => setNeu({ ...neu, wochentage: w })} />
        </label>
        <label>
          Von / bis (Uhrzeit)
          <span className="zeile">
            <input type="time" step="900" value={neu.beginn} onChange={setze('beginn')} />
            <input type="time" step="900" value={neu.ende} onChange={setze('ende')} />
          </span>
        </label>
        <label>
          Zeitraum
          <span className="zeile">
            <input type="date" value={neu.von} onChange={setze('von')} />
            <input type="date" value={neu.bis} onChange={setze('bis')} />
          </span>
        </label>
        <label>
          Notiz
          <input value={neu.notiz} onChange={setze('notiz')} />
        </label>
        <button type="submit" disabled={neu.wochentage.length === 0}>
          Serie anlegen
        </button>
      </form>

      {serien.length > 0 && (
        <table className="tabelle">
          <thead>
            <tr>
              <th>Zeitraum</th>
              <th>Blöcke</th>
              <th>Notiz</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {serien.map((s) => (
              <tr key={s.serie_id}>
                <td>
                  {datum(s.erster)} – {datum(s.letzter)}, {new Date(s.erster).toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })}
                </td>
                <td className="mitte">{s.anzahl}</td>
                <td>{s.notiz}</td>
                <td>
                  <button className="klein" onClick={() => loeschen(s, heute)}>
                    ab heute löschen
                  </button>{' '}
                  <button className="klein gefahr" onClick={() => loeschen(s)}>
                    ganz löschen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function ArbeitEinstellungen() {
  const [meldung, setMeldung] = useState(null)
  return (
    <div className="seite">
      {meldung && (
        <div className={`meldung ${meldung.art}`} onClick={() => setMeldung(null)}>
          {meldung.text}
        </div>
      )}
      <div className="zwei-spalten">
        <RegelFormular setMeldung={setMeldung} />
        <SerienVerwaltung setMeldung={setMeldung} />
      </div>
    </div>
  )
}
