import { useEffect, useState } from 'react'
import { api, dauerText } from '../api.js'
import { Badge, Button, Tabelle, komma, kurzTitel } from '../ui.jsx'

const TEILE = [
  { feld: 'uni', name: 'Uni' },
  { feld: 'arbeit', name: 'Arbeit' },
  { feld: 'lernen', name: 'Lernen' },
  { feld: 'freizeit', name: 'Freizeit' },
]

function countdownText(tage) {
  if (tage === 0) return 'heute'
  if (tage === 1) return 'morgen'
  return `in ${tage} Tagen`
}

// Kompakt oben im Kalender: Stunden der Woche als Balken; Prüfungen und Lernstand aufklappbar
export default function Wochenuebersicht({ woche, stand }) {
  const [daten, setDaten] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [offen, setOffen] = useState(false)

  useEffect(() => {
    if (!woche) return
    api
      .planungWoche(woche)
      .then((d) => {
        setDaten(d)
        setFehler(null)
      })
      .catch((e) => setFehler(e.message))
  }, [woche, stand])

  if (fehler) {
    return (
      <div className="wochenbalken-zeile">
        <Badge ton="verwerfen" icon="warnung">
          Wochenübersicht: {fehler}
        </Badge>
      </div>
    )
  }
  if (!daten) return null
  const { stunden, pruefungen, lernstand } = daten
  const hinten = lernstand.filter((l) => l.rueckstand_minuten > 30)
  const naechste = pruefungen[0]
  const lernenGeplant = lernstand.reduce((s, l) => s + l.geplant_minuten, 0)
  const lernenSoll = lernstand.reduce((s, l) => s + l.soll_minuten, 0)

  return (
    <section className="wochenuebersicht" aria-label="Diese Woche">
      <div className="wochenbalken-zeile">
        <div className="wochenbalken" role="img" aria-label={TEILE.map((t) => `${t.name} ${komma(stunden[t.feld])} h`).join(', ')}>
          {TEILE.map((t) =>
            stunden[t.feld] > 0 ? (
              <span key={t.feld} className={`balken-teil ${t.feld}`} style={{ flexGrow: stunden[t.feld] }} title={`${t.name}: ${komma(stunden[t.feld])} h`} />
            ) : null,
          )}
        </div>
        <ul className="balken-legende">
          {TEILE.map((t) => (
            <li key={t.feld}>
              <span className={`punkt ${t.feld}`} />
              {t.name} <strong>{komma(stunden[t.feld])} h</strong>
            </li>
          ))}
        </ul>
        {stunden.arbeit < stunden.arbeit_soll && (
          <Badge ton="verwerfen" icon="warnung" title="Weniger Arbeit eingeplant als die Wochenstunden">
            Arbeit unter Soll ({komma(stunden.arbeit_soll)} h)
          </Badge>
        )}
        {naechste && (
          <Badge ton={naechste.in_dieser_woche ? 'verwerfen' : 'neutral'} icon="pruefung" title={`Nächste Prüfung: ${naechste.lva_name}`}>
            {kurzTitel(naechste.lva_name)} {countdownText(naechste.tage)}
          </Badge>
        )}
        {(pruefungen.length > 0 || lernstand.length > 0) && (
          <Button klein aria-expanded={offen} onClick={() => setOffen(!offen)}>
            {offen ? 'Weniger' : 'Details'}
          </Button>
        )}
      </div>

      {offen && (
        <div className="wochen-details">
          {pruefungen.length > 0 && (
            <div className="stapel">
              <h3>Nächste Prüfungen</h3>
              <ul className="countdown">
                {pruefungen.slice(0, 5).map((p) => (
                  <li key={p.lva_id}>
                    <span className="farbpunkt" style={{ background: p.farbe }} />
                    <strong>{p.lva_name}</strong> {countdownText(p.tage)}
                    <span className="leise">
                      {new Date(p.zeitpunkt).toLocaleDateString('de-AT', { weekday: 'short', day: '2-digit', month: '2-digit' })}
                      {p.quelle === 'manuell' && ', selbst eingetragen'}
                    {p.quelle === 'vorschlag' && ', voraussichtlich (noch kein Termin gewählt)'}
                    </span>
                    {p.in_dieser_woche && <Badge ton="verwerfen">diese Woche</Badge>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {lernstand.length > 0 && (
            <div className="stapel">
              <h3>
                Lernen diese Woche: {dauerText(lernenGeplant * 60) || '0 min'} von {dauerText(lernenSoll * 60) || '0 min'}
                {hinten.length > 0 && (
                  <>
                    {' '}
                    <Badge ton="verwerfen" icon="warnung">
                      {hinten.length} LVA hinter dem Plan
                    </Badge>
                  </>
                )}
              </h3>
              <Tabelle>
                <thead>
                  <tr>
                    <th>LVA</th>
                    <th className="zahl" title="Anteil dieser Woche inklusive Nachholen">
                      Soll
                    </th>
                    <th className="zahl">geplant</th>
                    <th className="zahl" title="Positiv: so viel fehlt aus früheren Wochen">
                      Rückstand
                    </th>
                    <th>Prüfung</th>
                  </tr>
                </thead>
                <tbody>
                  {lernstand.map((l) => (
                    <tr key={l.lva_id}>
                      <td>
                        {l.lva_name}
                      </td>
                      <td className="zahl">{l.ohne_ects ? <span className="leise">ECTS fehlen</span> : dauerText(l.soll_minuten * 60) || '–'}</td>
                      <td className="zahl">{dauerText(l.geplant_minuten * 60) || '–'}</td>
                      <td className="zahl">
                        {l.rueckstand_minuten > 30 ? (
                          <Badge ton="verwerfen">{dauerText(l.rueckstand_minuten * 60)}</Badge>
                        ) : l.rueckstand_minuten > 0 ? (
                          dauerText(l.rueckstand_minuten * 60)
                        ) : (
                          '–'
                        )}
                      </td>
                      <td>{l.pruefung ? new Date(l.pruefung).toLocaleDateString('de-AT') : <span className="leise">keine</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </Tabelle>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
