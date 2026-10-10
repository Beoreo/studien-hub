import { useState } from 'react'
import { api, filterParameter, MARKIERUNGEN, TYPEN } from '../api.js'

function umschalten(liste, wert) {
  return liste.includes(wert) ? liste.filter((x) => x !== wert) : [...liste, wert]
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

export default function FilterLeiste({ lvas, filter, setFilter, zeitraum }) {
  const [exportZeitraum, setExportZeitraum] = useState('ansicht')
  const [monat, setMonat] = useState(aktuellerMonat)

  const setze = (feld, wert) => setFilter({ ...filter, [feld]: wert })

  const grenzen = exportZeitraum === 'monat' ? monatsGrenzen(monat) : exportZeitraum === 'ansicht' ? zeitraum : null
  const exportParameter = filterParameter(filter, grenzen?.von, grenzen?.bis)

  return (
    <aside className="filter">
      <h3>LVAs</h3>
      {lvas.length === 0 && <p className="hinweis">Noch keine LVAs – zuerst TISS importieren.</p>}
      {lvas.map((lva) => (
        <label key={lva.id} className="filter-lva">
          <input
            type="checkbox"
            checked={filter.lvas.includes(lva.id)}
            onChange={() => setze('lvas', umschalten(filter.lvas, lva.id))}
          />
          <span className="farbpunkt" style={{ background: lva.farbe }} />
          <span title={lva.titel}>{lva.kurzname || lva.titel}</span>
        </label>
      ))}
      {filter.lvas.length > 0 && (
        <button className="klein" onClick={() => setze('lvas', [])}>
          alle LVAs zeigen
        </button>
      )}

      <h3>Typ</h3>
      {TYPEN.map((t) => (
        <label key={t.wert}>
          <input
            type="checkbox"
            checked={filter.typen.includes(t.wert)}
            onChange={() => setze('typen', umschalten(filter.typen, t.wert))}
          />
          {t.name}
        </label>
      ))}

      <h3>Markierung</h3>
      {MARKIERUNGEN.map((m) => (
        <label key={m.wert}>
          <input
            type="checkbox"
            checked={filter.markierungen.includes(m.wert)}
            onChange={() => setze('markierungen', umschalten(filter.markierungen, m.wert))}
          />
          {m.symbol} {m.name}
        </label>
      ))}

      <h3>Arbeit</h3>
      {[
        ['mit', 'Termine und Arbeit'],
        ['ohne', 'nur Termine'],
        ['nur', 'nur Arbeit'],
      ].map(([wert, name]) => (
        <label key={wert}>
          <input type="radio" name="arbeit" checked={filter.arbeit === wert} onChange={() => setze('arbeit', wert)} />
          {name}
        </label>
      ))}
      <label>
        <input type="checkbox" checked={filter.vorschlaege} onChange={() => setze('vorschlaege', !filter.vorschlaege)} />
        Vorschläge zeigen
      </label>

      <h3>Export</h3>
      <select value={exportZeitraum} onChange={(e) => setExportZeitraum(e.target.value)}>
        <option value="ansicht">aktuelle Ansicht</option>
        <option value="monat">Monat</option>
        <option value="alles">alles</option>
      </select>
      {exportZeitraum === 'monat' && <input type="month" value={monat} onChange={(e) => setMonat(e.target.value)} />}
      <p className="hinweis">Es gelten die Filter oben.</p>
      <div className="export-knoepfe">
        {[
          ['ics', 'iCal'],
          ['csv', 'CSV'],
          ['pdf', 'PDF'],
        ].map(([format, name]) => (
          <a key={format} className="knopf" href={api.exportUrl(format, exportParameter)} download>
            {name}
          </a>
        ))}
      </div>
    </aside>
  )
}
