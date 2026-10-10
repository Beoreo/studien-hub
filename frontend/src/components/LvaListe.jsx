import { useState } from 'react'
import { api, videoZusammenfassung } from '../api.js'

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
                  <th title="Aufzeichnungen aus TUWEL (Anzahl und Gesamtdauer)">Videos</th>
                  <th title="Für den Abgleich des Lernbedarfs: 1 ECTS = 25 Stunden">ECTS</th>
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
                      <td className="rechts">
                        {videoZusammenfassung(lva.anzahl_videos, lva.video_dauer_sekunden, lva.videos_ohne_dauer)}
                      </td>
                      <td>
                        <ZahlFeld wert={lva.ects} schritt="0.5" onSpeichern={(ects) => aendern(lva, { ects })} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <Lernaufwand lvas={lvas.filter((l) => l.semester === s)} aendern={aendern} />
        </section>
      ))}
    </div>
  )
}

// Zahl, die beim Verlassen des Feldes gespeichert wird (leer = nicht gesetzt)
function ZahlFeld({ wert, schritt = '1', onSpeichern, leerErlaubt = true }) {
  return (
    <input
      className="kurz"
      type="number"
      min="0"
      step={schritt}
      key={wert ?? 'leer'}
      defaultValue={wert ?? ''}
      onBlur={(e) => {
        const neu = e.target.value === '' ? null : Number(e.target.value)
        if (neu === null && !leerErlaubt) return
        if (neu !== (wert ?? null)) onSpeichern(neu)
      }}
    />
  )
}

const LERNWERTE = [
  { feld: 'minuten_pro_folie', name: 'Min./Folie', schritt: '0.5' },
  { feld: 'minuten_pro_skriptseite', name: 'Min./Skriptseite', schritt: '0.5' },
  { feld: 'minuten_pro_uebungsblatt', name: 'Min./Übungsblatt', schritt: '15' },
  { feld: 'video_faktor', name: 'Videofaktor', schritt: '0.1' },
  { feld: 'minuten_sonstiges', name: 'Min./sonstige Datei', schritt: '5' },
]

// Schätzwerte für den Lernaufwand je LVA und der aus eigenen Zeiten gelernte Korrekturfaktor
function Lernaufwand({ lvas, aendern }) {
  return (
    <details className="lernaufwand">
      <summary>Lernaufwand schätzen – Werte je LVA</summary>
      <p className="hinweis">
        Folien und Skripte zählen nach Seiten (PDF im Querformat = Folien), Videos nach Dauer × Faktor, Übungsblätter mit
        festem Wert. Der Korrekturfaktor ergibt sich aus den Zeiten, die du nach Lernblöcken einträgst.
      </p>
      <div className="tabelle-huelle">
        <table className="tabelle">
          <thead>
            <tr>
              <th>LVA</th>
              {LERNWERTE.map((w) => (
                <th key={w.feld}>{w.name}</th>
              ))}
              <th title="Tatsächlich gebrauchte ÷ geplante Lernzeit, geglättet">Korrektur</th>
            </tr>
          </thead>
          <tbody>
            {lvas.map((lva) => (
              <tr key={lva.id}>
                <td>{lva.kurzname || lva.titel}</td>
                {LERNWERTE.map((w) => (
                  <td key={w.feld}>
                    <ZahlFeld
                      wert={lva.lernparameter?.[w.feld]}
                      schritt={w.schritt}
                      leerErlaubt={false}
                      onSpeichern={(wert) => aendern(lva, { lernparameter: { [w.feld]: wert } })}
                    />
                  </td>
                ))}
                <td title={`${lva.korrektur_rueckmeldungen} Rückmeldungen`}>
                  × {String(lva.korrektur_faktor).replace('.', ',')}
                  {lva.korrektur_rueckmeldungen === 0 && <span className="hinweis"> (noch keine)</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
