import { useEffect, useState } from 'react'
import { api, lokalIso } from '../api.js'

const zeit = (d) =>
  new Date(d).toLocaleString('de-AT', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })

// Drei Zustände: LVA-Wert übernehmen, ja, nein
function Abweichung({ name, wert, lvaWert, onChange }) {
  const auswahl = wert === null ? 'lva' : wert ? 'ja' : 'nein'
  return (
    <label className="abweichung">
      <span>{name}</span>
      <select
        value={auswahl}
        onChange={(e) => onChange(e.target.value === 'lva' ? null : e.target.value === 'ja')}
      >
        <option value="lva">wie LVA ({lvaWert ? 'ja' : 'nein'})</option>
        <option value="ja">ja</option>
        <option value="nein">nein</option>
      </select>
    </label>
  )
}

function TerminInhalt({ id, onGeaendert, setFehler }) {
  const [termin, setTermin] = useState(null)

  useEffect(() => {
    api.termin(id).then(setTermin).catch((e) => setFehler(e.message))
  }, [id, setFehler])

  if (!termin) return <p>Lade …</p>

  const lvaWerte = {
    steop_abweichung: termin.lva_steop,
    anwesenheit_abweichung: termin.lva_anwesenheitspflicht,
    aufzeichnung_abweichung: termin.lva_aufzeichnung,
  }

  const speichern = () =>
    api
      .terminAendern(termin.id, {
        steop_abweichung: termin.steop_abweichung,
        anwesenheit_abweichung: termin.anwesenheit_abweichung,
        aufzeichnung_abweichung: termin.aufzeichnung_abweichung,
      })
      .then(onGeaendert)
      .catch((e) => setFehler(e.message))

  const setze = (feld) => (wert) => setTermin({ ...termin, [feld]: wert })

  return (
    <>
      <h2>
        <span className="farbpunkt" style={{ background: termin.lva_farbe }} /> {termin.lva_titel} {termin.typ}
      </h2>
      <p>
        {zeit(termin.start)} – {new Date(termin.ende).toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })}
        {termin.ort && <> · {termin.ort}</>}
      </p>
      <p className="hinweis">{termin.titel}</p>
      <h3>Abweichungen nur für diesen Termin</h3>
      <Abweichung name="STEOP" wert={termin.steop_abweichung} lvaWert={lvaWerte.steop_abweichung} onChange={setze('steop_abweichung')} />
      <Abweichung
        name="Anwesenheitspflicht"
        wert={termin.anwesenheit_abweichung}
        lvaWert={lvaWerte.anwesenheit_abweichung}
        onChange={setze('anwesenheit_abweichung')}
      />
      <Abweichung
        name="Aufzeichnung"
        wert={termin.aufzeichnung_abweichung}
        lvaWert={lvaWerte.aufzeichnung_abweichung}
        onChange={setze('aufzeichnung_abweichung')}
      />
      <div className="dialog-knoepfe">
        <button onClick={speichern}>Speichern</button>
      </div>
    </>
  )
}

function ArbeitInhalt({ event, onGeaendert, setFehler }) {
  const props = event.extendedProps
  const [notiz, setNotiz] = useState(props.notiz || '')
  const vorschlag = props.status === 'vorschlag'
  const ausfuehren = (aufruf) => aufruf.then(onGeaendert).catch((e) => setFehler(e.message))

  return (
    <>
      <h2>{event.title}</h2>
      <p>
        {zeit(event.start)} – {event.end.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })} ·{' '}
        {vorschlag ? 'Vorschlag' : 'bestätigt'} · {props.blockArt}
        {props.serieId && ' · Teil einer Serie'}
      </p>
      <label className="block">
        Notiz
        <textarea value={notiz} onChange={(e) => setNotiz(e.target.value)} rows={3} />
      </label>
      <div className="dialog-knoepfe">
        {vorschlag && (
          <button onClick={() => ausfuehren(api.blockAendern(props.blockId, { status: 'bestaetigt', notiz }))}>
            Bestätigen
          </button>
        )}
        <button onClick={() => ausfuehren(api.blockAendern(props.blockId, { notiz }))}>Notiz speichern</button>
        <button className="gefahr" onClick={() => ausfuehren(api.blockLoeschen(props.blockId))}>
          {vorschlag ? 'Vorschlag verwerfen' : 'Löschen'}
        </button>
      </div>
    </>
  )
}

function NeuInhalt({ start, ende, onGeaendert, setFehler }) {
  const [notiz, setNotiz] = useState('')
  const anlegen = () =>
    api
      .blockAnlegen({ start: lokalIso(start), ende: lokalIso(ende), notiz: notiz || null })
      .then(onGeaendert)
      .catch((e) => setFehler(e.message))
  return (
    <>
      <h2>Arbeitsblock anlegen</h2>
      <p>
        {zeit(start)} – {ende.toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })}
      </p>
      <label className="block">
        Notiz
        <input value={notiz} onChange={(e) => setNotiz(e.target.value)} />
      </label>
      <div className="dialog-knoepfe">
        <button onClick={anlegen}>Anlegen (fix)</button>
      </div>
    </>
  )
}

export default function EreignisDialog({ auswahl, onSchliessen, onGeaendert }) {
  const [fehler, setFehler] = useState(null)
  return (
    <div className="dialog-hintergrund" onClick={onSchliessen}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <button className="schliessen" onClick={onSchliessen}>
          ×
        </button>
        {auswahl.art === 'termin' && (
          <TerminInhalt id={auswahl.event.extendedProps.terminId} onGeaendert={onGeaendert} setFehler={setFehler} />
        )}
        {auswahl.art === 'arbeit' && <ArbeitInhalt event={auswahl.event} onGeaendert={onGeaendert} setFehler={setFehler} />}
        {auswahl.art === 'neu' && (
          <NeuInhalt start={auswahl.start} ende={auswahl.ende} onGeaendert={onGeaendert} setFehler={setFehler} />
        )}
        {fehler && <div className="meldung fehler">{fehler}</div>}
      </div>
    </div>
  )
}
