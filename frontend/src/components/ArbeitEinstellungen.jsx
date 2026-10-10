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
            ? { ...r, fruehester_beginn: kurzeZeit(r.fruehester_beginn), spaetestes_ende: kurzeZeit(r.spaetestes_ende), arbeitgeber: r.arbeitgeber || '' }
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
