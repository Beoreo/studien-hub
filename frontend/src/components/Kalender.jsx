import { useCallback, useEffect, useRef, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import deLocale from '@fullcalendar/core/locales/de'
import { api, dauerText, filterParameter, lokalDatum, lokalIso, MARKIERUNGEN } from '../api.js'
import FilterLeiste from './FilterLeiste.jsx'
import EreignisDialog from './EreignisDialog.jsx'

const STANDARD_FILTER = { lvas: [], typen: [], markierungen: [], arbeit: 'mit', vorschlaege: true }
const SPEICHER_SCHLUESSEL = 'studienhub.filter'

function gespeicherterFilter() {
  try {
    const roh = localStorage.getItem(SPEICHER_SCHLUESSEL)
    return roh ? { ...STANDARD_FILTER, ...JSON.parse(roh) } : STANDARD_FILTER
  } catch {
    return STANDARD_FILTER
  }
}

function Symbole({ props }) {
  if (props.art !== 'termin') return null
  const aktiv = {
    steop: props.steop,
    anwesenheit: props.anwesenheitspflicht,
    aufzeichnung: props.aufzeichnung,
  }
  return (
    <span className="symbole">
      {MARKIERUNGEN.filter((m) => aktiv[m.wert]).map((m) => (
        <span key={m.wert} title={m.name}>
          {m.symbol}
        </span>
      ))}
    </span>
  )
}

function EreignisInhalt({ ereignis }) {
  const { event, timeText } = ereignis
  const props = event.extendedProps
  return (
    <div className="ereignis">
      <div className="ereignis-zeile">
        <Symbole props={props} />
        {props.pruefung && <strong>Prüfung · </strong>}
        {props.abgabe && <strong>Abgabe · </strong>}
        {props.art === 'lernen' && <span title="Lernblock">{props.erledigt ? '✅' : '📚'} </span>}
        <span className="ereignis-titel">{event.title}</span>
      </div>
      {timeText && <div className="ereignis-zeit">{timeText}</div>}
      {props.ort && <div className="ereignis-ort">{props.ort}</div>}
    </div>
  )
}

export default function Kalender({ lvas }) {
  const kalender = useRef(null)
  const [filter, setFilter] = useState(gespeicherterFilter)
  const [zeitraum, setZeitraum] = useState(null)
  const [auswahl, setAuswahl] = useState(null)
  const [meldung, setMeldung] = useState(null)
  const [vorschlag, setVorschlag] = useState(null)

  useEffect(() => {
    try {
      localStorage.setItem(SPEICHER_SCHLUESSEL, JSON.stringify(filter))
    } catch {
      /* Speicher nicht verfügbar */
    }
  }, [filter])

  const ereignisse = useCallback(
    (info, erfolg, misserfolg) => {
      api
        .kalender(filterParameter(filter, lokalIso(info.start), lokalIso(info.end)))
        .then(erfolg)
        .catch((e) => {
          setMeldung({ art: 'fehler', text: e.message })
          misserfolg(e)
        })
    },
    [filter],
  )

  const neuLaden = () => kalender.current?.getApi().refetchEvents()

  const aktuelleWoche = () => lokalDatum(kalender.current.getApi().getDate())

  async function vorschlagen() {
    try {
      const ergebnis = await api.vorschlag(aktuelleWoche())
      setVorschlag(ergebnis)
      neuLaden()
    } catch (e) {
      setMeldung({ art: 'fehler', text: e.message })
    }
  }

  async function alleBestaetigen() {
    try {
      const { bestaetigt } = await api.bestaetigen(aktuelleWoche())
      setMeldung({ art: 'ok', text: `${bestaetigt} Vorschläge bestätigt.` })
      setVorschlag(null)
      neuLaden()
    } catch (e) {
      setMeldung({ art: 'fehler', text: e.message })
    }
  }

  // Abbrechen vor der Bestätigung: offene Vorschläge der Woche löschen, bestätigte Blöcke bleiben
  async function verwerfen() {
    try {
      const { verworfen } = await api.verwerfen(aktuelleWoche())
      setMeldung({ art: 'ok', text: `${verworfen} Vorschläge verworfen.` })
      setVorschlag(null)
      neuLaden()
    } catch (e) {
      setMeldung({ art: 'fehler', text: e.message })
    }
  }

  async function verschieben(info) {
    const props = info.event.extendedProps
    const zeit = { start: lokalIso(info.event.start), ende: lokalIso(info.event.end) }
    try {
      if (props.art === 'lernen') await api.lernBlockAendern(props.lernblockId, zeit)
      else await api.blockAendern(props.blockId, zeit)
      neuLaden() // Vorschlag gilt nach dem Verschieben als bestätigt
    } catch (e) {
      info.revert()
      setMeldung({ art: 'fehler', text: e.message })
    }
  }

  return (
    <div className="kalender-layout">
      <FilterLeiste lvas={lvas} filter={filter} setFilter={setFilter} zeitraum={zeitraum} />
      <section className="kalender-bereich">
        <div className="werkzeuge">
          <button onClick={vorschlagen} title="Flexible Stunden in die freien Lücken dieser Woche legen">
            Arbeitszeit vorschlagen
          </button>
          <button onClick={alleBestaetigen}>Vorschläge der Woche bestätigen</button>
          <button className="zweitrangig" onClick={verwerfen} title="Offene Vorschläge dieser Woche löschen">
            Vorschläge verwerfen
          </button>
          <span className="legende">
            {MARKIERUNGEN.map((m) => (
              <span key={m.wert}>
                {m.symbol} {m.name}
              </span>
            ))}
            <span className="legende-vorschlag">Vorschlag</span>
            <span className="legende-feiertag">Feiertag / frei</span>
          </span>
        </div>

        {meldung && (
          <div className={`meldung ${meldung.art}`} onClick={() => setMeldung(null)}>
            {meldung.text}
          </div>
        )}
        {vorschlag && (
          <div className={`meldung ${vorschlag.fehlende_stunden > 0 ? 'warnung' : 'ok'}`}>
            <button className="schliessen" onClick={() => setVorschlag(null)}>
              ×
            </button>
            Woche ab {new Date(vorschlag.woche).toLocaleDateString('de-AT')}: {vorschlag.verplant_stunden} von{' '}
            {vorschlag.soll_stunden} offenen Stunden verplant.
            {vorschlag.fehlende_stunden > 0 && <> Es fehlen {vorschlag.fehlende_stunden} Stunden.</>}
            {vorschlag.lern_stunden > 0 && <> Dazu {String(vorschlag.lern_stunden).replace('.', ',')} h Lernen.</>}
            {vorschlag.konflikte?.length > 0 && (
              <div className="meldung fehler konflikt">
                <strong>Konflikt – Lernen und Arbeit passen nicht beide in diese Woche:</strong>
                <ul>
                  {vorschlag.konflikte.map((k) => (
                    <li key={k}>{k}</li>
                  ))}
                </ul>
              </div>
            )}
            {vorschlag.ects_warnungen?.length > 0 && (
              <div className="meldung warnung">
                <ul>
                  {vorschlag.ects_warnungen.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
            {vorschlag.lernbedarf?.length > 0 && (
              <details className="begruendung">
                <summary>Lernbedarf dieser Woche</summary>
                <table className="tabelle">
                  <thead>
                    <tr>
                      <th>LVA</th>
                      <th>neuer Stoff</th>
                      <th>Präsenz</th>
                      <th>ECTS-Soll</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vorschlag.lernbedarf.map((b) => (
                      <tr key={b.lva_id} className={b.warnung ? 'warnzeile' : ''}>
                        <td title={b.unterlagen.map((u) => `${u.titel}: ${u.minuten} min`).join('\n')}>{b.lva_name}</td>
                        <td>{dauerText(b.unterlagen_minuten * 60) || '–'}</td>
                        <td>{dauerText(b.praesenz_minuten * 60) || '–'}</td>
                        <td>{b.soll_minuten ? dauerText(b.soll_minuten * 60) : <span className="hinweis">ECTS fehlen</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
            {vorschlag.begruendungen.length > 0 && (
              <div className="begruendung">
                Warum so:
                <ul>
                  {vorschlag.begruendungen.map((text) => (
                    <li key={text}>{text}</li>
                  ))}
                </ul>
              </div>
            )}
            {vorschlag.geopferte_termine.length > 0 && (
              <div>
                Dafür müssten diese Termine ohne Aufzeichnung entfallen:
                <ul>
                  {vorschlag.geopferte_termine.map((t) => (
                    <li key={`${t.id}-${t.start}`}>
                      {t.titel},{' '}
                      {new Date(t.start).toLocaleString('de-AT', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {vorschlag.bloecke.length > 0 && (
              <div className="dialog-knoepfe">
                <button onClick={alleBestaetigen}>Übernehmen</button>
                <button className="zweitrangig" onClick={verwerfen}>
                  Verwerfen
                </button>
              </div>
            )}
          </div>
        )}

        <FullCalendar
          ref={kalender}
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          locale={deLocale}
          initialView="timeGridWeek"
          headerToolbar={{ left: 'prev,next today', center: 'title', right: 'timeGridWeek,dayGridMonth' }}
          firstDay={1}
          height="auto"
          slotMinTime="07:00:00"
          slotMaxTime="22:00:00"
          allDayText="ganztägig"
          nowIndicator
          editable
          selectable
          selectMirror
          snapDuration="00:15:00"
          events={ereignisse}
          eventContent={(e) => <EreignisInhalt ereignis={e} />}
          eventDrop={verschieben}
          eventResize={verschieben}
          eventClick={(info) => {
            const art = info.event.extendedProps.art
            if (art === 'termin' || art === 'arbeit' || art === 'lernen') setAuswahl({ art, event: info.event })
          }}
          select={(info) => setAuswahl({ art: 'neu', start: info.start, ende: info.end })}
          datesSet={(info) => setZeitraum({ von: lokalIso(info.start), bis: lokalIso(info.end) })}
        />
      </section>

      {auswahl && (
        <EreignisDialog
          auswahl={auswahl}
          onSchliessen={() => {
            setAuswahl(null)
            kalender.current?.getApi().unselect()
          }}
          onGeaendert={() => {
            setAuswahl(null)
            neuLaden()
          }}
        />
      )}
    </div>
  )
}
