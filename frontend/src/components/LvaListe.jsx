import { useState } from 'react'
import { api } from '../api.js'

// Markierungen werden einmal pro Semester gesetzt und gelten für alle Termine der LVA.
export default function LvaListe({ lvas, onGeaendert }) {
  const [fehler, setFehler] = useState(null)

  const aendern = (lva, daten) =>
    api
      .lvaAendern(lva.id, daten)
      .then(onGeaendert)
      .catch((e) => setFehler(e.message))

  const semester = [...new Set(lvas.map((l) => l.semester))]

  if (lvas.length === 0) {
    return <p className="seite">Noch keine LVAs. Importiere zuerst deinen TISS-Kalender.</p>
  }

  return (
    <div className="seite">
      <p className="hinweis">
        STEOP, Anwesenheitspflicht und Aufzeichnung stehen nicht im TISS-Feed. Setze sie hier einmal pro Semester;
        einzelne Termine kannst du im Kalender per Klick abweichend markieren.
      </p>
      {fehler && (
        <div className="meldung fehler" onClick={() => setFehler(null)}>
          {fehler}
        </div>
      )}
      {semester.map((s) => (
        <section key={s}>
          <h2>Semester {s}</h2>
          <div className="tabelle-huelle">
            <table className="tabelle">
              <thead>
                <tr>
                  <th>Farbe</th>
                  <th>Nummer</th>
                  <th>Titel</th>
                  <th>Kurzname</th>
                  <th title="STEOP">★ STEOP</th>
                  <th title="Anwesenheitspflicht">✋ Anwesenheit</th>
                  <th title="Aufzeichnung">🎥 Aufzeichnung</th>
                  <th>TUWEL-Kurs-ID</th>
                  <th>Termine</th>
                </tr>
              </thead>
              <tbody>
                {lvas
                  .filter((l) => l.semester === s)
                  .map((lva) => (
                    <tr key={lva.id}>
                      <td>
                        <input type="color" value={lva.farbe} onChange={(e) => aendern(lva, { farbe: e.target.value })} />
                      </td>
                      <td>{lva.nummer || '–'}</td>
                      <td>{lva.titel}</td>
                      <td>
                        <input
                          className="kurz"
                          defaultValue={lva.kurzname || ''}
                          placeholder="z. B. EP1"
                          onBlur={(e) => e.target.value !== (lva.kurzname || '') && aendern(lva, { kurzname: e.target.value || null })}
                        />
                      </td>
                      {['steop', 'anwesenheitspflicht', 'aufzeichnung'].map((feld) => (
                        <td key={feld} className="mitte">
                          <input type="checkbox" checked={lva[feld]} onChange={(e) => aendern(lva, { [feld]: e.target.checked })} />
                        </td>
                      ))}
                      <td>
                        <input
                          className="kurz"
                          type="number"
                          defaultValue={lva.tuwel_kurs_id ?? ''}
                          onBlur={(e) => {
                            const wert = e.target.value ? Number(e.target.value) : null
                            if (wert !== lva.tuwel_kurs_id) aendern(lva, { tuwel_kurs_id: wert })
                          }}
                        />
                      </td>
                      <td className="mitte">{lva.anzahl_termine}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  )
}
