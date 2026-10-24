import { useState } from 'react'
import { api, filterParameter, MARKIERUNGEN, TYPEN } from '../api.js'
import { Auswahl, Button, Eingabe, Icon, Kontrolle, kurzTitel, lvaName } from '../ui.jsx'

// Leere Liste = alle sichtbar. „Keine“ braucht einen Wert, der nichts trifft.
const KEINE_LVA = 0
const KEIN_TYP = 'KEINE'

function sichtbar(liste, wert) {
  return liste.length === 0 || liste.includes(wert)
}

/** Ein Eintrag ein-/ausblenden; alle sichtbar wird wieder zur leeren Liste. */
function umschalten(liste, wert, alle, keine) {
  const aktuell = liste.length === 0 ? alle : liste.filter((x) => x !== keine)
  const neu = aktuell.includes(wert) ? aktuell.filter((x) => x !== wert) : [...aktuell, wert]
  if (neu.length === 0) return [keine]
  return alle.every((x) => neu.includes(x)) ? [] : neu
}

function monatsGrenzen(monat) {
  // monat im Format JJJJ-MM
  const [jahr, m] = monat.split('-').map(Number)
  const naechster = m === 12 ? `${jahr + 1}-01` : `${jahr}-${String(m + 1).padStart(2, '0')}`
  return { von: `${monat}-01T00:00:00`, bis: `${naechster}-01T00:00:00` }
}

function aktuellerMonat() {
  const heute = new Date()
  return `${heute.getFullYear()}-${String(heute.getMonth() + 1).padStart(2, '0')}`
}

// Aufklappbare Gruppe mit Anzahl der gewählten Einträge im Kopf
function Gruppe({ titel, zusatz, offen = true, children }) {
  return (
    <details className="filter-gruppe" open={offen}>
      <summary>
        <Icon name="auf" className="icon-auf" />
        <span>{titel}</span>
        {zusatz && <span className="leise klein">{zusatz}</span>}
      </summary>
      <div className="filter-gruppe-inhalt">{children}</div>
    </details>
  )
}

function AlleKeine({ onAlle, onKeine }) {
  return (
    <div className="knopf-gruppe">
      <Button klein onClick={onAlle}>
        alle
      </Button>
      <Button klein onClick={onKeine}>
        keine
      </Button>
    </div>
  )
}

export default function FilterLeiste({ lvas, filter, setFilter, zeitraum }) {
  const [suche, setSuche] = useState('')
  const [exportZeitraum, setExportZeitraum] = useState('ansicht')
  const [monat, setMonat] = useState(aktuellerMonat)

  const setze = (feld, wert) => setFilter({ ...filter, [feld]: wert })
  const lvaIds = lvas.map((l) => l.id)
  const typen = TYPEN.map((t) => t.wert)
  const gefunden = lvas.filter((l) => `${l.titel} ${l.kurzname || ''}`.toLowerCase().includes(suche.toLowerCase()))
  const anzahl = (liste, alle) => (liste.length === 0 ? 'alle' : `${liste.filter((x) => alle.includes(x)).length} von ${alle.length}`)

  const grenzen = exportZeitraum === 'monat' ? monatsGrenzen(monat) : exportZeitraum === 'ansicht' ? zeitraum : null
  const exportParameter = filterParameter(filter, grenzen?.von, grenzen?.bis)

  return (
    <div className="filter-leiste">
      <Gruppe titel="LVAs" zusatz={anzahl(filter.lvas, lvaIds)}>
        {lvas.length === 0 ? (
          <p className="leise klein">Noch keine LVAs – zuerst TISS importieren.</p>
        ) : (
          <>
            <div className="filter-suche">
              <Icon name="suche" />
              <Eingabe type="search" placeholder="LVA suchen" aria-label="LVA suchen" value={suche} onChange={(e) => setSuche(e.target.value)} />
            </div>
            <AlleKeine onAlle={() => setze('lvas', [])} onKeine={() => setze('lvas', [KEINE_LVA])} />
            <div className="filter-liste">
              {gefunden.map((lva) => (
                <Kontrolle
                  key={lva.id}
                  title={lva.titel}
                  checked={sichtbar(filter.lvas, lva.id)}
                  onChange={() => setze('lvas', umschalten(filter.lvas, lva.id, lvaIds, KEINE_LVA))}
                  label={
                    <span className="filter-lva">
                      <span className="farbpunkt" style={{ background: lva.farbe }} />
                      <span className="abgeschnitten">{lvaName(lva)}</span>
                    </span>
                  }
                />
              ))}
            </div>
          </>
        )}
      </Gruppe>

      <Gruppe titel="Typ" zusatz={anzahl(filter.typen, typen)}>
        <AlleKeine onAlle={() => setze('typen', [])} onKeine={() => setze('typen', [KEIN_TYP])} />
        <div className="filter-liste">
          {TYPEN.map((t) => (
            <Kontrolle
              key={t.wert}
              label={t.name}
              checked={sichtbar(filter.typen, t.wert)}
              onChange={() => setze('typen', umschalten(filter.typen, t.wert, typen, KEIN_TYP))}
            />
          ))}
        </div>
      </Gruppe>

      <Gruppe titel="Markierung" zusatz={filter.markierungen.length ? `nur ${filter.markierungen.length}` : 'alle Termine'} offen={false}>
        <p className="leise klein">Nur Termine mit einer dieser Markierungen zeigen:</p>
        <div className="filter-liste">
          {MARKIERUNGEN.map((m) => (
            <Kontrolle
              key={m.wert}
              checked={filter.markierungen.includes(m.wert)}
              onChange={() =>
                setze(
                  'markierungen',
                  filter.markierungen.includes(m.wert) ? filter.markierungen.filter((x) => x !== m.wert) : [...filter.markierungen, m.wert],
                )
              }
              label={
                <span className="filter-lva">
                  <Icon name={m.icon} />
                  {m.name}
                </span>
              }
            />
          ))}
        </div>
      </Gruppe>

      <Gruppe titel="Arbeit" offen={false}>
        <div className="filter-liste">
          {[
            ['mit', 'Termine und Arbeit'],
            ['ohne', 'nur Termine'],
            ['nur', 'nur Arbeit'],
          ].map(([wert, name]) => (
            <Kontrolle key={wert} typ="radio" name="arbeit" label={name} checked={filter.arbeit === wert} onChange={() => setze('arbeit', wert)} />
          ))}
          <Kontrolle label="Vorschläge zeigen" checked={filter.vorschlaege} onChange={() => setze('vorschlaege', !filter.vorschlaege)} />
        </div>
      </Gruppe>

      <Gruppe titel="Export" offen={false}>
        <Auswahl
          aria-label="Zeitraum des Exports"
          value={exportZeitraum}
          onChange={(e) => setExportZeitraum(e.target.value)}
          optionen={[
            { wert: 'ansicht', name: 'aktuelle Ansicht' },
            { wert: 'monat', name: 'Monat' },
            { wert: 'alles', name: 'alles' },
          ]}
        />
        {exportZeitraum === 'monat' && (
          <Eingabe type="month" aria-label="Monat" value={monat} onChange={(e) => setMonat(e.target.value)} />
        )}
        <p className="leise klein">Es gelten die Filter oben.</p>
        <div className="knopf-gruppe">
          {[
            ['ics', 'iCal'],
            ['csv', 'CSV'],
            ['pdf', 'PDF'],
          ].map(([format, name]) => (
            <Button key={format} klein icon="laden" href={api.exportUrl(format, exportParameter)} download>
              {name}
            </Button>
          ))}
        </div>
      </Gruppe>
    </div>
  )
}
