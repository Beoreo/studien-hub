import { useEffect, useState } from 'react'
import { api, lokalIso } from '../api.js'
import { Auswahl, Badge, Button, Eingabe, Feld, Hinweis, Icon, Seitenleiste, lvaName } from '../ui.jsx'

// Details eines Kalender-Eintrags in der Seitenleiste: Ort, Markierungen, Notiz, erledigt …
const zeit = (d) =>
  new Date(d).toLocaleString('de-AT', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
const uhr = (d) => new Date(d).toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })

function Angaben({ zeilen }) {
  return (
    <dl className="angaben">
      {zeilen
        .filter(([, wert]) => wert)
        .map(([name, wert]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{wert}</dd>
          </div>
        ))}
    </dl>
  )
}

// Drei Zustände: Wert des Teils übernehmen, ja, nein
function Abweichung({ name, icon, wert, lvaWert, onChange }) {
  const auswahl = wert === null ? 'lva' : wert ? 'ja' : 'nein'
  return (
    <Feld
      label={
        <span className="mit-icon">
          <Icon name={icon} />
          {name}
        </span>
      }
    >
      <Auswahl
        value={auswahl}
        onChange={(e) => onChange(e.target.value === 'lva' ? null : e.target.value === 'ja')}
        optionen={[
          { wert: 'lva', name: `wie Teil (${lvaWert ? 'ja' : 'nein'})` },
          { wert: 'ja', name: 'ja' },
          { wert: 'nein', name: 'nein' },
        ]}
      />
    </Feld>
  )
}

function TerminDetails({ id, onGeaendert, onSchliessen }) {
  const [termin, setTermin] = useState(null)
  const [fehler, setFehler] = useState(null)

  useEffect(() => {
    api.termin(id).then(setTermin).catch((e) => setFehler(e.message))
  }, [id])

  if (!termin) {
    return (
      <Seitenleiste titel="Termin" onSchliessen={onSchliessen}>
        {fehler ? <Hinweis ton="fehler" titel={fehler} /> : <p className="leise">Lade …</p>}
      </Seitenleiste>
    )
  }

  const eigen = termin.quelle === 'manuell' // selbst angelegt: Titel, Ort, Typ änderbar, löschbar
  const speichern = () =>
    api
      .terminAendern(termin.id, {
        steop_abweichung: termin.steop_abweichung,
        anwesenheit_abweichung: termin.anwesenheit_abweichung,
        aufzeichnung_abweichung: termin.aufzeichnung_abweichung,
        ...(eigen ? { titel: termin.titel, ort: termin.ort || null, typ: termin.typ } : {}),
      })
      .then(onGeaendert)
      .catch((e) => setFehler(e.message))
  const loeschen = () => api.terminLoeschen(termin.id).then(onGeaendert).catch((e) => setFehler(e.message))
  const setze = (feld) => (wert) => setTermin({ ...termin, [feld]: wert })
  const teil = termin.teil_bezeichnung && termin.teil_bezeichnung !== 'Teil' ? termin.teil_bezeichnung : termin.typ

  return (
    <Seitenleiste
      titel={termin.lva_titel}
      farbe={termin.lva_farbe}
      onSchliessen={onSchliessen}
      aktionen={
        <>
          {eigen ? (
            <Button variante="verwerfen" icon="loeschen" onClick={loeschen}>
              Löschen
            </Button>
          ) : (
            <Button onClick={onSchliessen}>Abbrechen</Button>
          )}
          <Button variante="bestaetigen" onClick={speichern}>
            Speichern
          </Button>
        </>
      }
    >
      <Angaben
        zeilen={[
          ['Teil', eigen ? null : teil],
          ['Zeit', `${zeit(termin.start)} – ${uhr(termin.ende)}`],
          ['Ort', eigen ? null : termin.ort],
          ['Titel in TISS', eigen ? null : termin.titel],
        ]}
      />
      {eigen && (
        <div className="stapel">
          <Badge>selbst eingetragen</Badge>
          <Feld label="Titel">
            <Eingabe value={termin.titel} onChange={(e) => setze('titel')(e.target.value)} />
          </Feld>
          <Feld label="Ort">
            <Eingabe value={termin.ort || ''} onChange={(e) => setze('ort')(e.target.value)} />
          </Feld>
          <Feld label="Typ">
            <Auswahl optionen={TERMIN_TYPEN} value={termin.typ} onChange={(e) => setze('typ')(e.target.value)} />
          </Feld>
        </div>
      )}
      <div className="stapel">
        <h3>Abweichungen nur für diesen Termin</h3>
        <Abweichung name="STEOP" icon="steop" wert={termin.steop_abweichung} lvaWert={termin.lva_steop} onChange={setze('steop_abweichung')} />
        <Abweichung
          name="Anwesenheitspflicht"
          icon="anwesenheit"
          wert={termin.anwesenheit_abweichung}
          lvaWert={termin.lva_anwesenheitspflicht}
          onChange={setze('anwesenheit_abweichung')}
        />
        <Abweichung
          name="Aufzeichnung"
          icon="aufzeichnung"
          wert={termin.aufzeichnung_abweichung}
          lvaWert={termin.lva_aufzeichnung}
          onChange={setze('aufzeichnung_abweichung')}
        />
      </div>
      {fehler && <Hinweis ton="fehler" titel={fehler} />}
    </Seitenleiste>
  )
}

function ArbeitDetails({ event, onGeaendert, onSchliessen }) {
  const props = event.extendedProps
  const [notiz, setNotiz] = useState(props.notiz || '')
  const [fehler, setFehler] = useState(null)
  const vorschlag = props.status === 'vorschlag'
  const ausfuehren = (aufruf) => aufruf.then(onGeaendert).catch((e) => setFehler(e.message))

  return (
    <Seitenleiste
      titel={event.title.replace(/^Vorschlag: /, '')}
      icon="arbeit"
      onSchliessen={onSchliessen}
      aktionen={
        <>
          <Button variante="verwerfen" icon="loeschen" onClick={() => ausfuehren(api.blockLoeschen(props.blockId))}>
            {vorschlag ? 'Verwerfen' : 'Löschen'}
          </Button>
          <Button onClick={() => ausfuehren(api.blockAendern(props.blockId, { notiz }))}>Notiz speichern</Button>
          {vorschlag && (
            <Button
              variante="bestaetigen"
              onClick={() => ausfuehren(api.blockAendern(props.blockId, { status: 'bestaetigt', notiz }))}
              title="Bleibt beim Neuplanen, wo er ist"
            >
              Fixieren
            </Button>
          )}
        </>
      }
    >
      <div className="reihe">
        {vorschlag ? <Badge ton="umriss">Vorschlag</Badge> : <Badge ton="bestaetigen">bestätigt</Badge>}
        <Badge>{props.blockArt}</Badge>
        {props.serieId && <Badge>Teil einer Serie</Badge>}
      </div>
      <Angaben zeilen={[['Zeit', `${zeit(event.start)} – ${uhr(event.end)}`]]} />
      <Feld label="Notiz">
        <Eingabe mehrzeilig rows={3} value={notiz} onChange={(e) => setNotiz(e.target.value)} />
      </Feld>
      {vorschlag && <p className="leise klein">Verworfen: Der Hub legt die Stunden diese Woche an eine andere Stelle.</p>}
      {fehler && <Hinweis ton="fehler" titel={fehler} />}
    </Seitenleiste>
  )
}

// Lernblock: erledigt markieren und die tatsächlich gelernte Zeit eintragen – weniger als geplant wird nachgeholt
function LernDetails({ event, lvaNachId, onGeaendert, onSchliessen }) {
  const props = event.extendedProps
  const geplant = Math.round((event.end - event.start) / 60000)
  const [minuten, setMinuten] = useState(geplant)
  const [fehler, setFehler] = useState(null)
  const alt = props.altpruefung // Altprüfung aus der MB Cloud, falls der Block eine behandelt
  const [punkte, setPunkte] = useState({ punkte: alt?.punkte ?? '', punkte_max: alt?.punkte_max ?? '' })
  const vorschlag = props.status === 'vorschlag'
  const lva = lvaNachId.get(props.lvaId)
  const ausfuehren = (aufruf) => aufruf.then(onGeaendert).catch((e) => setFehler(e.message))
  const zahl = (v) => (v === '' ? null : Number(v))
  const erledigt = () =>
    api.lernBlockAendern(props.lernblockId, { tatsaechliche_minuten: minuten }).then(() =>
      alt
        ? api.altpruefungBearbeitet(alt.dokument_id, {
            erledigt: true,
            minuten,
            punkte: zahl(punkte.punkte),
            punkte_max: zahl(punkte.punkte_max),
          })
        : null,
    )

  return (
    <Seitenleiste
      titel={lva ? `Lernen: ${lva.titel}` : event.title.replace(/^Vorschlag( von Claude)?: /, '')}
      icon="lernen"
      farbe={props.farbe}
      onSchliessen={onSchliessen}
      aktionen={
        <>
          <Button variante="verwerfen" icon="loeschen" onClick={() => ausfuehren(api.lernBlockLoeschen(props.lernblockId))}>
            {vorschlag ? 'Verwerfen' : 'Löschen'}
          </Button>
          {vorschlag && (
            <Button
              onClick={() => ausfuehren(api.lernBlockAendern(props.lernblockId, { status: 'bestaetigt' }))}
              title="Bleibt beim Neuplanen, wo er ist"
            >
              Fixieren
            </Button>
          )}
          <Button variante="bestaetigen" icon="ok" onClick={() => ausfuehren(erledigt())}>
            Erledigt
          </Button>
        </>
      }
    >
      <div className="reihe">
        {vorschlag ? <Badge ton="umriss">Vorschlag</Badge> : <Badge ton="bestaetigen">bestätigt</Badge>}
        {props.erledigt && (
          <Badge ton="bestaetigen" icon="erledigt">
            erledigt
          </Badge>
        )}
      </div>
      <Angaben
        zeilen={[
          ['Zeit', `${zeit(event.start)} – ${uhr(event.end)}`],
          ['Geplant', `${geplant} min`],
          ['Stoff', props.thema],
        ]}
      />
      {alt && (
        <div className="stapel">
          <p className="mit-icon">
            <Icon name="mbcloud" />
            <span>
              Inoffizielle Altprüfung:{' '}
              <a href={api.dokumentUrl(alt.dokument_id)} target="_blank" rel="noreferrer">
                {alt.dateiname}
              </a>
            </span>
          </p>
          <div className="formular-zeile">
            <Feld label="Erreichte Punkte">
              <Eingabe type="number" breite="schmal" min="0" step="0.5" value={punkte.punkte} onChange={(e) => setPunkte({ ...punkte, punkte: e.target.value })} />
            </Feld>
            <Feld label="von">
              <Eingabe
                type="number"
                breite="schmal"
                min="0"
                step="0.5"
                value={punkte.punkte_max}
                onChange={(e) => setPunkte({ ...punkte, punkte_max: e.target.value })}
              />
            </Feld>
          </div>
        </div>
      )}
      <Feld label="Tatsächlich gelernt (Minuten)" hilfe="Was du weniger lernst als geplant, verteilt der Hub auf die Wochen bis zur Prüfung.">
        <Eingabe type="number" breite="schmal" min="0" step="5" value={minuten} onChange={(e) => setMinuten(Number(e.target.value))} />
      </Feld>
      {fehler && <Hinweis ton="fehler" titel={fehler} />}
    </Seitenleiste>
  )
}

const ARTEN = [
  { wert: 'arbeit', name: 'Arbeitsblock (fix)' },
  { wert: 'lva', name: 'Termin zu einer LVA' },
  { wert: 'persoenlich', name: 'Persönlicher Termin' },
]
const TERMIN_TYPEN = [
  { wert: 'SONSTIGE', name: 'Sonstiges (z. B. Tutorium)' },
  { wert: 'VO', name: 'Vorlesung' },
  { wert: 'UE', name: 'Übung' },
  { wert: 'PRUEFUNG', name: 'Prüfung' },
  { wert: 'ABGABE', name: 'Abgabe' },
]

// Im Kalender aufgezogener Zeitraum: Arbeitsblock, eigener LVA-Termin oder persönlicher Termin
function NeuDetails({ start, ende, lvas, onGeaendert, onSchliessen }) {
  const [art, setArt] = useState('arbeit')
  const [werte, setWerte] = useState({ titel: '', ort: '', notiz: '', lva_id: lvas[0]?.id ?? '', typ: 'SONSTIGE' })
  const [fehler, setFehler] = useState(null)
  const setze = (feld) => (e) => setWerte({ ...werte, [feld]: e.target.value })
  const zeitraum = { start: lokalIso(start), ende: lokalIso(ende) }
  const anlegen = () => {
    let aufruf
    if (art === 'arbeit') aufruf = api.blockAnlegen({ ...zeitraum, notiz: werte.notiz || null })
    else if (!werte.titel.trim()) return setFehler('Bitte einen Titel eingeben.')
    else if (art === 'lva') {
      aufruf = api.terminAnlegen({ ...zeitraum, lva_id: Number(werte.lva_id), titel: werte.titel.trim(), ort: werte.ort || null, typ: werte.typ })
    } else {
      aufruf = api.persoenlichAnlegen({ ...zeitraum, titel: werte.titel.trim(), ort: werte.ort || null, notiz: werte.notiz || null })
    }
    return aufruf.then(onGeaendert).catch((e) => setFehler(e.message))
  }
  return (
    <Seitenleiste
      titel="Eintrag anlegen"
      icon={art === 'arbeit' ? 'arbeit' : art === 'persoenlich' ? 'persoenlich' : undefined}
      onSchliessen={onSchliessen}
      aktionen={
        <>
          <Button onClick={onSchliessen}>Abbrechen</Button>
          <Button variante="bestaetigen" onClick={anlegen}>
            Anlegen
          </Button>
        </>
      }
    >
      <Angaben zeilen={[['Zeit', `${zeit(start)} – ${uhr(ende)}`]]} />
      <Feld label="Art">
        <Auswahl optionen={ARTEN} value={art} onChange={(e) => setArt(e.target.value)} />
      </Feld>
      {art === 'lva' && (
        <>
          <Feld label="LVA">
            <Auswahl value={werte.lva_id} onChange={setze('lva_id')}>
              {lvas.map((l) => (
                <option key={l.id} value={l.id}>
                  {lvaName(l)}
                </option>
              ))}
            </Auswahl>
          </Feld>
          <Feld label="Typ">
            <Auswahl optionen={TERMIN_TYPEN} value={werte.typ} onChange={setze('typ')} />
          </Feld>
        </>
      )}
      {art !== 'arbeit' && (
        <>
          <Feld label="Titel">
            <Eingabe value={werte.titel} onChange={setze('titel')} autoFocus />
          </Feld>
          <Feld label="Ort">
            <Eingabe value={werte.ort} onChange={setze('ort')} />
          </Feld>
        </>
      )}
      {art !== 'lva' && (
        <Feld label="Notiz">
          <Eingabe value={werte.notiz} onChange={setze('notiz')} />
        </Feld>
      )}
      <p className="leise klein">
        {art === 'arbeit'
          ? 'Bleibt beim Neuplanen, wo er ist, und zählt zu den Wochenstunden.'
          : 'Arbeit und Lernen werden um diesen Termin herum geplant. Verschieben per Ziehen im Kalender.'}
      </p>
      {fehler && <Hinweis ton="fehler" titel={fehler} />}
    </Seitenleiste>
  )
}

// Persönlicher Termin ohne LVA: Titel, Ort, Notiz ändern oder löschen (Zeit per Ziehen im Kalender)
function PersoenlichDetails({ event, onGeaendert, onSchliessen }) {
  const props = event.extendedProps
  const [werte, setWerte] = useState({ titel: event.title, ort: props.ort || '', notiz: props.notiz || '' })
  const [fehler, setFehler] = useState(null)
  const ausfuehren = (aufruf) => aufruf.then(onGeaendert).catch((e) => setFehler(e.message))
  const setze = (feld) => (e) => setWerte({ ...werte, [feld]: e.target.value })
  return (
    <Seitenleiste
      titel={event.title}
      icon="persoenlich"
      onSchliessen={onSchliessen}
      aktionen={
        <>
          <Button variante="verwerfen" icon="loeschen" onClick={() => ausfuehren(api.persoenlichLoeschen(props.persoenlichId))}>
            Löschen
          </Button>
          <Button
            variante="bestaetigen"
            onClick={() =>
              ausfuehren(api.persoenlichAendern(props.persoenlichId, { titel: werte.titel, ort: werte.ort || null, notiz: werte.notiz || null }))
            }
          >
            Speichern
          </Button>
        </>
      }
    >
      <Angaben zeilen={[['Zeit', `${zeit(event.start)} – ${uhr(event.end)}`]]} />
      <Feld label="Titel">
        <Eingabe value={werte.titel} onChange={setze('titel')} />
      </Feld>
      <Feld label="Ort">
        <Eingabe value={werte.ort} onChange={setze('ort')} />
      </Feld>
      <Feld label="Notiz">
        <Eingabe mehrzeilig rows={3} value={werte.notiz} onChange={setze('notiz')} />
      </Feld>
      {fehler && <Hinweis ton="fehler" titel={fehler} />}
    </Seitenleiste>
  )
}

export default function EreignisDetails({ auswahl, lvaNachId, lvas = [], onSchliessen, onGeaendert }) {
  const gemeinsam = { onSchliessen, onGeaendert }
  if (auswahl.art === 'termin') return <TerminDetails id={auswahl.event.extendedProps.terminId} {...gemeinsam} />
  if (auswahl.art === 'arbeit') return <ArbeitDetails event={auswahl.event} {...gemeinsam} />
  if (auswahl.art === 'lernen') return <LernDetails event={auswahl.event} lvaNachId={lvaNachId} {...gemeinsam} />
  if (auswahl.art === 'persoenlich') return <PersoenlichDetails event={auswahl.event} {...gemeinsam} />
  return <NeuDetails start={auswahl.start} ende={auswahl.ende} lvas={lvas} {...gemeinsam} />
}
