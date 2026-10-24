import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import deLocale from '@fullcalendar/core/locales/de'
import { api, filterParameter, lokalDatum, lokalIso } from '../api.js'
import { Button, Hinweis, Icon, IconButton, Menue, Rueckfrage, Seitenleiste, komma, lvaName } from '../ui.jsx'
import FilterLeiste from './FilterLeiste.jsx'
import EreignisDetails from './EreignisDialog.jsx'
import Wochenuebersicht from './Wochenuebersicht.jsx'

const STANDARD_FILTER = { lvas: [], typen: [], markierungen: [], arbeit: 'mit', vorschlaege: true }
const SPEICHER_SCHLUESSEL = 'studienhub.filter'
const SCHMAL = '(max-width: 900px)'
const ANSICHTEN = [
  { id: 'timeGridDay', name: 'Tag' },
  { id: 'timeGridWeek', name: 'Woche' },
  { id: 'dayGridMonth', name: 'Monat' },
]
const TYP_NAMEN = { PRUEFUNG: 'Prüfung', ABGABE: 'Abgabe', SONSTIGE: '' }

function gespeicherterFilter() {
  try {
    const roh = localStorage.getItem(SPEICHER_SCHLUESSEL)
    return roh ? { ...STANDARD_FILTER, ...JSON.parse(roh) } : STANDARD_FILTER
  } catch {
    return STANDARD_FILTER
  }
}

const istSchmal = () => window.matchMedia(SCHMAL).matches

/** Kurzer Titel eines Eintrags: „Mathe 1 (VO)“, „Lernen Mathe 1“, „Arbeit“. */
function eintragTitel(event, lvaNachId) {
  const p = event.extendedProps
  const lva = lvaNachId.get(p.lvaId)
  const kurz = lva ? lvaName(lva) : null
  if (p.art === 'termin') {
    const typ = p.pruefung ? 'Prüfung' : p.abgabe ? 'Abgabe' : TYP_NAMEN[p.typ] ?? p.typ
    const name = kurz || event.title.replace(/ \(nicht besucht\)$/, '')
    return typ && kurz ? `${name} (${typ})` : name
  }
  if (p.art === 'pruefung') return `${kurz || event.title.replace(/^Prüfung /, '')} (Prüfung)`
  if (p.art === 'anmeldung') return `Anmeldung ${kurz || event.title.replace(/^Anmeldung /, '')}`
  if (p.art === 'lernen') return kurz || event.title.replace(/^Vorschlag( von Claude)?: Lernen /, '')
  return event.title.replace(/^Vorschlag: /, '')
}

// Symbole eines Eintrags; jedes mit Tooltip und aria-label
function Symbole({ p }) {
  const namen = []
  if (p.art === 'arbeit') namen.push(['arbeit', 'Arbeit'])
  if (p.art === 'persoenlich') namen.push(['persoenlich', 'Persönlicher Termin'])
  if (p.art === 'lernen') namen.push(p.erledigt ? ['erledigt', 'Lernblock erledigt'] : ['lernen', 'Lernen'])
  if (p.art === 'feiertag' || p.art === 'frei') namen.push(['frei', 'Feiertag / frei'])
  if (p.pruefung) namen.push(['pruefung', 'Prüfung'])
  if (p.art === 'anmeldung') {
    const termine = (p.pruefungen || []).map((t) => new Date(t.start).toLocaleDateString('de-AT')).join(', ')
    namen.push(['anmeldung', `Prüfungsanmeldung ab diesem Tag${termine ? ` – Termine: ${termine}` : ''}`])
  }
  if (p.abgabe) namen.push(['abgabe', 'Abgabe'])
  if (p.steop) namen.push(['steop', 'STEOP'])
  if (p.anwesenheitspflicht) namen.push(['anwesenheit', 'Anwesenheitspflicht'])
  if (p.aufzeichnung) namen.push(['aufzeichnung', 'Aufzeichnung'])
  if (p.ausgeblendet) namen.push(['ausgeblendet', 'nicht besucht'])
  if (!namen.length) return null
  return (
    <span className="eintrag-symbole">
      {namen.map(([name, label]) => (
        <Icon key={name} name={name} label={label} />
      ))}
    </span>
  )
}

function EintragInhalt({ info, lvaNachId }) {
  const { event, timeText } = info
  const p = event.extendedProps
  return (
    <div className="eintrag-inhalt">
      <div className="eintrag-zeile">
        <Symbole p={p} />
        <span className="eintrag-titel">{eintragTitel(event, lvaNachId)}</span>
      </div>
      {timeText && !event.allDay && <div className="eintrag-zeit">{timeText}</div>}
    </div>
  )
}

export default function Kalender({ lvas }) {
  const kalender = useRef(null)
  const [filter, setFilter] = useState(gespeicherterFilter)
  const [zeitraum, setZeitraum] = useState(null)
  const [auswahl, setAuswahl] = useState(null)
  const [hinweis, setHinweis] = useState(null) // höchstens ein Hinweis gleichzeitig
  const [woche, setWoche] = useState(null)
  const [titel, setTitel] = useState('')
  const [ansicht, setAnsicht] = useState(() => (istSchmal() ? 'timeGridDay' : 'timeGridWeek'))
  const [filterOffen, setFilterOffen] = useState(false)
  const [rueckfrage, setRueckfrage] = useState(false)
  const [stand, setStand] = useState(0) // zählt hoch, wenn sich Blöcke ändern: Wochenübersicht neu laden

  const lvaNachId = useMemo(() => new Map(lvas.map((l) => [l.id, l])), [lvas])
  const besuchte = useMemo(() => lvas.filter((l) => l.besucht), [lvas])

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
          setHinweis({ ton: 'fehler', titel: e.message })
          misserfolg(e)
        })
    },
    [filter],
  )

  const fc = () => kalender.current?.getApi()
  const neuLaden = () => {
    fc()?.refetchEvents()
    setStand((n) => n + 1)
  }
  const aktuelleWoche = () => lokalDatum(fc().getDate())
  const fehler = (e) => setHinweis({ ton: 'fehler', titel: e.message })

  async function vorschlagen() {
    try {
      const v = await api.vorschlag(aktuelleWoche())
      setHinweis(vorschlagHinweis(v))
      neuLaden()
    } catch (e) {
      fehler(e)
    }
  }

  async function alleBestaetigen() {
    try {
      const { bestaetigt } = await api.bestaetigen(aktuelleWoche())
      setHinweis({ ton: 'erfolg', titel: `${bestaetigt} Vorschläge fixiert.` })
      neuLaden()
    } catch (e) {
      fehler(e)
    }
  }

  // Abbrechen vor der Bestätigung: offene Vorschläge der Woche löschen, bestätigte Blöcke bleiben
  async function verwerfen() {
    try {
      const { verworfen } = await api.verwerfen(aktuelleWoche())
      setHinweis({ ton: 'erfolg', titel: `${verworfen} Vorschläge verworfen.` })
      neuLaden()
    } catch (e) {
      fehler(e)
    }
  }

  // Alle Wochen: nur unbestätigte Arbeitszeit-Vorschläge, fixe und bestätigte Blöcke bleiben
  async function alleArbeitsvorschlaegeLoeschen() {
    setRueckfrage(false)
    try {
      const { geloescht } = await api.alleArbeitsvorschlaegeLoeschen()
      setHinweis({ ton: 'erfolg', titel: `${geloescht} Arbeitszeit-Vorschläge gelöscht.` })
      neuLaden()
    } catch (e) {
      fehler(e)
    }
  }

  // Ergebnis von „Woche planen“: eine Zeile mit den wichtigsten Zahlen, Rest aufklappbar
  function vorschlagHinweis(v) {
    const konflikte = (v.konflikte?.length || 0) + (v.hinweise?.length || 0)
    const teile = [`Arbeit ${komma(v.verplant_stunden)} von ${komma(v.soll_stunden)} h`]
    if (v.lern_stunden > 0) teile.push(`Lernen ${komma(v.lern_stunden)} h`)
    if (v.fehlende_stunden > 0) teile.push(`${komma(v.fehlende_stunden)} h fehlen`)
    if (konflikte) teile.push(`${konflikte} ${konflikte === 1 ? 'Konflikt' : 'Konflikte'}`)
    const offen = v.bloecke.length > 0 || v.lernbloecke.length > 0
    return {
      ton: v.fehlende_stunden > 0 || konflikte ? 'warnung' : 'info',
      titel: `Woche geplant: ${teile.join(' · ')}`,
      aktionen: offen && (
        <>
          <Button klein variante="bestaetigen" icon="ok" onClick={alleBestaetigen}>
            Übernehmen
          </Button>
          <Button klein onClick={verwerfen}>
            Verwerfen
          </Button>
        </>
      ),
      details:
        konflikte || v.begruendungen.length || v.geopferte_termine.length ? (
          <div className="stapel">
            {v.konflikte?.length > 0 && (
              <div>
                <strong>Zu wenig Zeit – gekürzt wurde Lernzeit (zuerst ohne nahe Prüfung), nie die Arbeit:</strong>
                <ul>
                  {v.konflikte.map((k) => (
                    <li key={k}>{k}</li>
                  ))}
                </ul>
              </div>
            )}
            {v.hinweise?.length > 0 && (
              <ul>
                {v.hinweise.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            {v.begruendungen.length > 0 && (
              <div>
                <strong>Warum so:</strong>
                <ul>
                  {v.begruendungen.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              </div>
            )}
            {v.geopferte_termine.length > 0 && (
              <div>
                <strong>Dafür müssten diese Termine ohne Aufzeichnung entfallen:</strong>
                <ul>
                  {v.geopferte_termine.map((t) => (
                    <li key={`${t.id}-${t.start}`}>
                      {t.titel},{' '}
                      {new Date(t.start).toLocaleString('de-AT', { weekday: 'short', hour: '2-digit', minute: '2-digit' })}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null,
    }
  }

  async function verschieben(info) {
    const props = info.event.extendedProps
    const zeit = { start: lokalIso(info.event.start), ende: lokalIso(info.event.end) }
    try {
      if (props.art === 'lernen') await api.lernBlockAendern(props.lernblockId, zeit)
      else if (props.art === 'termin') await api.terminAendern(props.terminId, zeit) // nur selbst angelegte sind verschiebbar
      else if (props.art === 'persoenlich') await api.persoenlichAendern(props.persoenlichId, zeit)
      else await api.blockAendern(props.blockId, zeit)
      neuLaden() // gilt danach als fix; der Hub plant den Rest der Woche neu
    } catch (e) {
      info.revert()
      fehler(e)
    }
  }

  const ansichtWaehlen = (id) => {
    setAnsicht(id)
    fc()?.changeView(id)
  }

  const filterLeiste = <FilterLeiste lvas={besuchte} filter={filter} setFilter={setFilter} zeitraum={zeitraum} />

  return (
    <div className="kalender-layout">
      <div className="kalender-filter">{filterLeiste}</div>
      <section className="kalender-bereich" aria-label="Kalender">
        <div className="kalender-werkzeuge">
          <div className="knopf-gruppe">
            <IconButton icon="zurueck" label="Zurück" onClick={() => fc()?.prev()} />
            <IconButton icon="weiter" label="Weiter" onClick={() => fc()?.next()} />
            <Button onClick={() => fc()?.today()}>Heute</Button>
            <h1 className="kalender-titel">{titel}</h1>
          </div>
          <div className="knopf-gruppe">
            <div className="segmente" role="group" aria-label="Ansicht">
              {ANSICHTEN.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={ansicht === a.id ? 'segment aktiv' : 'segment'}
                  aria-pressed={ansicht === a.id}
                  onClick={() => ansichtWaehlen(a.id)}
                >
                  {a.name}
                </button>
              ))}
            </div>
            <IconButton icon="filter" label="Filter und Export" className="nur-schmal" onClick={() => setFilterOffen(true)} />
            <Button
              variante="primaer"
              onClick={vorschlagen}
              title="Erst die Arbeitsstunden, dann die Lernzeit aus den ECTS in die freien Lücken dieser Woche legen"
            >
              Woche planen
            </Button>
            <Menue
              eintraege={[
                { name: 'Vorschläge der Woche fixieren', icon: 'ok', onClick: alleBestaetigen },
                { name: 'Vorschläge der Woche verwerfen', icon: 'schliessen', onClick: verwerfen },
                {
                  name: 'Alle Arbeitsvorschläge löschen',
                  icon: 'loeschen',
                  ton: 'verwerfen',
                  title: 'Unbestätigte Arbeitszeit-Vorschläge in allen Wochen löschen',
                  onClick: () => setRueckfrage(true),
                },
              ]}
            />
          </div>
        </div>

        <Wochenuebersicht woche={woche} stand={stand} />

        {hinweis && (
          <Hinweis key={hinweis.titel} ton={hinweis.ton} titel={hinweis.titel} aktionen={hinweis.aktionen} onSchliessen={() => setHinweis(null)}>
            {hinweis.details}
          </Hinweis>
        )}

        <div className="kalender-flaeche">
          <FullCalendar
            ref={kalender}
            plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
            locale={deLocale}
            initialView={ansicht}
            headerToolbar={false}
            firstDay={1}
            height="auto"
            slotMinTime="07:00:00"
            slotMaxTime="22:00:00"
            allDayText=""
            dayHeaderFormat={{ weekday: 'short', day: 'numeric', month: 'numeric', omitCommas: true }}
            slotLabelFormat={{ hour: '2-digit', minute: '2-digit' }}
            eventTimeFormat={{ hour: '2-digit', minute: '2-digit' }}
            nowIndicator
            slotEventOverlap={false}
            editable
            selectable
            selectMirror
            snapDuration="00:15:00"
            events={ereignisse}
            eventDataTransform={(e) => ({
              ...e,
              backgroundColor: undefined,
              borderColor: undefined,
              textColor: undefined,
              extendedProps: { ...e.extendedProps, farbe: e.backgroundColor },
            })}
            eventClassNames={(info) => ['eintrag', info.event.extendedProps.art]}
            eventDidMount={(info) => {
              const farbe = info.event.extendedProps.farbe
              if (farbe) info.el.style.setProperty('--lva', farbe)
            }}
            eventContent={(info) => <EintragInhalt info={info} lvaNachId={lvaNachId} />}
            eventDrop={verschieben}
            eventResize={verschieben}
            eventClick={(info) => {
              const art = info.event.extendedProps.art
              if (['termin', 'arbeit', 'lernen', 'persoenlich'].includes(art)) setAuswahl({ art, event: info.event })
              // Prüfungstermine und Anmeldestarts bearbeitet man im Reiter „Prüfungen“
              if (art === 'pruefung' || art === 'anmeldung') window.location.hash = 'pruefungen'
            }}
            select={(info) => setAuswahl({ art: 'neu', start: info.start, ende: info.end })}
            datesSet={(info) => {
              setZeitraum({ von: lokalIso(info.start), bis: lokalIso(info.end) })
              setWoche(lokalDatum(info.view.currentStart))
              setTitel(info.view.title)
            }}
          />
        </div>
      </section>

      {filterOffen && (
        <Seitenleiste titel="Filter und Export" icon="filter" onSchliessen={() => setFilterOffen(false)}>
          {filterLeiste}
        </Seitenleiste>
      )}

      {auswahl && (
        <EreignisDetails
          auswahl={auswahl}
          lvaNachId={lvaNachId}
          lvas={besuchte}
          onSchliessen={() => {
            setAuswahl(null)
            fc()?.unselect()
          }}
          onGeaendert={() => {
            setAuswahl(null)
            neuLaden()
          }}
        />
      )}

      {rueckfrage && (
        <Rueckfrage
          titel="Alle Arbeitsvorschläge löschen?"
          text="Unbestätigte Arbeitszeit-Vorschläge aller Wochen werden gelöscht. Bestätigte und fixe Blöcke bleiben."
          onJa={alleArbeitsvorschlaegeLoeschen}
          onNein={() => setRueckfrage(false)}
        />
      )}
    </div>
  )
}
