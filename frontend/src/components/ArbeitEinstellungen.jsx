import { useEffect, useState } from 'react'
import { api, WOCHENTAGE } from '../api.js'
import { Button, Dialog, Eingabe, Feld, Hinweis, IconButton, Karte, Kontrolle, SeitenKopf, Tabelle } from '../ui.jsx'
import './ArbeitEinstellungen.css'

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
  freie_tage: [],
  max_tag_stunden: 9,
  lernfenster_minuten: 120,
  voller_unitag_stunden: 6,
  min_freie_tage: 1,
  gewichte: { gleichmaessig: 5, buendeln: 5, lernzeit: 5, erholung: 5, zerstueckelung: 5 },
  lern_min_block_minuten: 45,
  lern_max_block_minuten: 120,
  lern_tage: [0, 1, 2, 3, 4, 5],
  ects_faktor: 0.7,
  lernphase_wochen: 2,
}

// Lernblöcke kommen nach der Arbeitszeit; der Bedarf je LVA aus den ECTS (Ziel und Regler im Reiter „LVAs“)
function LernEinstellungen({ regel, setRegel }) {
  const zahl = (feld) => (e) => setRegel({ ...regel, [feld]: Number(e.target.value) })
  return (
    <Karte titel="Lernblöcke" icon="lernen" aufklappbar>
      <div className="formular">
        <p className="leise klein">
          Reihenfolge: Pflichttermine, Arbeit, Lernen bis zum Wochenbedarf, der Rest ist Freizeit. Lernbedarf je LVA = (ECTS ×
          25 h − Präsenz) × ECTS-Faktor × Ziel; reicht die Zeit nicht, wird zuerst bei LVAs ohne nahe Prüfung gekürzt.
        </p>
        <TagAuswahl titel="Lerntage" werte={regel.lern_tage} onChange={(lern_tage) => setRegel({ ...regel, lern_tage })} />
        <div className="formular-zeile">
          <Feld label="Lernblock mindestens (min)">
            <Eingabe type="number" breite="schmal" min="15" step="15" value={regel.lern_min_block_minuten} onChange={zahl('lern_min_block_minuten')} />
          </Feld>
          <Feld label="höchstens (min)">
            <Eingabe type="number" breite="schmal" min="15" step="15" value={regel.lern_max_block_minuten} onChange={zahl('lern_max_block_minuten')} />
          </Feld>
        </div>
        <Feld label="ECTS-Faktor" hilfe="ECTS sind meist zu hoch angesetzt; 0,7 = 70 % der ECTS-Stunden.">
          <Eingabe type="number" breite="schmal" min="0.1" max="2" step="0.05" value={regel.ects_faktor} onChange={zahl('ects_faktor')} />
        </Feld>
        <Feld label="Lernen vor jeder Prüfung (Wochen)" hilfe="Standard; je LVA im Reiter „Prüfungen“ änderbar. Nur dann gibt es Lernblöcke.">
          <Eingabe type="number" breite="schmal" min="0" max="20" step="1" value={regel.lernphase_wochen} onChange={zahl('lernphase_wochen')} />
        </Feld>
      </div>
    </Karte>
  )
}

// Kriterien der entspannten Woche, je 0 (egal) bis 10 (sehr wichtig)
const KRITERIEN = [
  { feld: 'gleichmaessig', name: 'Gleichmäßige Last', hilfe: 'Uni plus Arbeit pro Tag möglichst ähnlich' },
  { feld: 'buendeln', name: 'Ganze Tage bündeln', hilfe: 'Arbeit an Tagen ohne Uni, wenige Wechsel' },
  { feld: 'lernzeit', name: 'Lernzeit schützen', hilfe: 'Tag vor Prüfung oder Abgabe arbeitsfrei halten' },
  { feld: 'erholung', name: 'Erholung', hilfe: 'komplett freie Tage pro Woche' },
  { feld: 'zerstueckelung', name: 'Keine Zerstückelung', hilfe: 'lieber wenige lange Blöcke' },
]

function EntspannteWoche({ regel, setRegel }) {
  const zahl = (feld) => (e) => setRegel({ ...regel, [feld]: Number(e.target.value) })
  const gewicht = (feld) => (e) => setRegel({ ...regel, gewichte: { ...regel.gewichte, [feld]: Number(e.target.value) } })
  return (
    <Karte titel="Verteilung und Gewichtung" aufklappbar>
      <div className="formular">
        <p className="leise klein">Der Vorschlag wählt die beste Verteilung; diese Grenzen gelten immer.</p>
        <div className="formular-zeile">
          <Feld label="Höchstens Uni + Arbeit pro Tag (h)">
            <Eingabe type="number" breite="schmal" min="1" max="24" step="0.5" value={regel.max_tag_stunden} onChange={zahl('max_tag_stunden')} />
          </Feld>
          <Feld label="Freie Tage pro Woche (mind.)">
            <Eingabe type="number" breite="schmal" min="0" max="7" step="1" value={regel.min_freie_tage} onChange={zahl('min_freie_tage')} />
          </Feld>
        </div>
        <Feld label="Lernfenster (Minuten)" hilfe="Nach Vorlesungen und vor Prüfungen/Abgaben frei gehalten.">
          <Eingabe type="number" breite="schmal" min="0" step="15" value={regel.lernfenster_minuten} onChange={zahl('lernfenster_minuten')} />
        </Feld>
        <Feld label="Voller Unitag ab (Stunden)" hilfe="Danach kein Arbeitsblock am Abend.">
          <Eingabe type="number" breite="schmal" min="0" max="24" step="0.5" value={regel.voller_unitag_stunden} onChange={zahl('voller_unitag_stunden')} />
        </Feld>
        <h3 className="arbeit-unter">Gewichtung: wie wichtig ist dir …</h3>
        {KRITERIEN.map((k) => (
          <Feld key={k.feld} label={k.name} hilfe={k.hilfe}>
            <span className="arbeit-regler">
              <input
                type="range"
                className="eingabe"
                min="0"
                max="10"
                step="1"
                value={regel.gewichte[k.feld]}
                onChange={gewicht(k.feld)}
              />
              <output>{regel.gewichte[k.feld]}</output>
            </span>
          </Feld>
        ))}
      </div>
    </Karte>
  )
}

const formatiere = (iso) => new Date(iso).toLocaleDateString('de-AT')

// Zusätzliche freie Tage neben den gesetzlichen Feiertagen (die kommen automatisch dazu)
function FreieTage({ werte, onChange }) {
  const [neu, setNeu] = useState({ von: '', bis: '', bezeichnung: '', jaehrlich: false })
  const setze = (feld) => (e) => setNeu({ ...neu, [feld]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const hinzufuegen = () => {
    if (!neu.von) return
    onChange([...werte, { ...neu, bis: neu.bis || null, bezeichnung: neu.bezeichnung || null }])
    setNeu({ von: '', bis: '', bezeichnung: '', jaehrlich: false })
  }

  return (
    <Karte titel={werte.length > 0 ? `Freie Tage (${werte.length})` : 'Freie Tage'} icon="frei" aufklappbar>
      <div className="formular">
        <p className="leise klein">Feiertage in Österreich sind automatisch gesperrt; hier kommen weitere Tage ohne Arbeitszeit dazu.</p>
        {werte.length > 0 && (
          <Tabelle>
            <tbody>
              {werte.map((f, i) => (
                <tr key={i}>
                  <td>
                    {f.jaehrlich ? formatiere(f.von).replace(/\d{4}$/, '') : formatiere(f.von)}
                    {f.bis && f.bis !== f.von && <> – {f.jaehrlich ? formatiere(f.bis).replace(/\d{4}$/, '') : formatiere(f.bis)}</>}
                  </td>
                  <td>{f.bezeichnung || 'frei'}</td>
                  <td className="leise">{f.jaehrlich && 'jährlich'}</td>
                  <td className="zahl">
                    <IconButton
                      icon="loeschen"
                      ton="verwerfen"
                      klein
                      label="Freien Tag entfernen"
                      onClick={() => onChange(werte.filter((_, j) => j !== i))}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </Tabelle>
        )}
        <div className="formular-zeile">
          <Feld label="Von">
            <Eingabe type="date" breite="mittel" value={neu.von} onChange={setze('von')} />
          </Feld>
          <Feld label="Bis (optional)">
            <Eingabe type="date" breite="mittel" value={neu.bis} min={neu.von} onChange={setze('bis')} />
          </Feld>
          <Feld label="Bezeichnung">
            <Eingabe breite="mittel" value={neu.bezeichnung} onChange={setze('bezeichnung')} placeholder="z. B. Urlaub" />
          </Feld>
        </div>
        <div className="reihe">
          <Kontrolle label="jedes Jahr (z. B. 24.12.)" checked={neu.jaehrlich} onChange={setze('jaehrlich')} />
          <Button klein icon="neu" onClick={hinzufuegen} disabled={!neu.von}>
            Hinzufügen
          </Button>
        </div>
      </div>
    </Karte>
  )
}

function TagAuswahl({ titel, werte, onChange }) {
  return (
    <fieldset className="arbeit-tage">
      <legend className="feld-beschriftung">{titel}</legend>
      <div className="reihe">
        {WOCHENTAGE.map((name, i) => (
          <Kontrolle
            key={i}
            label={name}
            checked={werte.includes(i)}
            onChange={() => onChange(werte.includes(i) ? werte.filter((w) => w !== i) : [...werte, i].sort())}
          />
        ))}
      </div>
    </fieldset>
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
            ? {
                ...STANDARD_REGEL,
                ...r,
                gewichte: { ...STANDARD_REGEL.gewichte, ...(r.gewichte || {}) },
                fruehester_beginn: kurzeZeit(r.fruehester_beginn),
                spaetestes_ende: kurzeZeit(r.spaetestes_ende),
                arbeitgeber: r.arbeitgeber || '',
                freie_tage: r.freie_tage || [],
              }
            : STANDARD_REGEL,
        ),
      )
      .catch((e) => setMeldung({ art: 'fehler', text: e.message }))
  }, [setMeldung])

  if (!regel) return <p className="leise">Lade …</p>
  const setze = (feld) => (e) => setRegel({ ...regel, [feld]: e.target.type === 'number' ? Number(e.target.value) : e.target.value })

  const speichern = (e) => {
    e.preventDefault()
    api
      .regelSpeichern({ ...regel, arbeitgeber: regel.arbeitgeber || null })
      .then(() => setMeldung({ art: 'ok', text: 'Arbeitsregel gespeichert. Im Kalender „Woche planen“ klicken.' }))
      .catch((e) => setMeldung({ art: 'fehler', text: e.message }))
  }

  return (
    <form className="stapel" onSubmit={speichern}>
      <Karte titel="Wochenstunden und Zeitfenster" icon="arbeit">
        <div className="formular">
          <div className="formular-zeile">
            <Feld label="Stunden pro Woche">
              <Eingabe type="number" breite="schmal" min="0" max="80" step="0.25" value={regel.stunden_pro_woche} onChange={setze('stunden_pro_woche')} />
            </Feld>
            <Feld label="Arbeitgeber">
              <Eingabe breite="mittel" value={regel.arbeitgeber} onChange={setze('arbeitgeber')} />
            </Feld>
          </div>
          <p className="leise klein">Bestätigte und fixe Blöcke werden abgezogen, der Rest wird automatisch in freie Lücken verteilt.</p>
          <TagAuswahl titel="Mögliche Tage" werte={regel.tage} onChange={(tage) => setRegel({ ...regel, tage })} />
          <TagAuswahl titel="Bevorzugte Tage" werte={regel.bevorzugte_tage} onChange={(t) => setRegel({ ...regel, bevorzugte_tage: t })} />
          <div className="formular-zeile">
            <Feld label="Frühester Beginn">
              <Eingabe type="time" breite="mittel" step="900" value={regel.fruehester_beginn} onChange={setze('fruehester_beginn')} />
            </Feld>
            <Feld label="Spätestes Ende">
              <Eingabe type="time" breite="mittel" step="900" value={regel.spaetestes_ende} onChange={setze('spaetestes_ende')} />
            </Feld>
          </div>
          <div className="formular-zeile">
            <Feld label="Block mind. (min)">
              <Eingabe type="number" breite="schmal" min="15" step="15" value={regel.min_block_minuten} onChange={setze('min_block_minuten')} />
            </Feld>
            <Feld label="Block höchstens (min)">
              <Eingabe type="number" breite="schmal" min="15" step="15" value={regel.max_block_minuten} onChange={setze('max_block_minuten')} />
            </Feld>
            <Feld label="Puffer für den Weg (min)">
              <Eingabe type="number" breite="schmal" min="0" step="5" value={regel.puffer_minuten} onChange={setze('puffer_minuten')} />
            </Feld>
          </div>
        </div>
      </Karte>
      <FreieTage werte={regel.freie_tage} onChange={(freie_tage) => setRegel({ ...regel, freie_tage })} />
      <EntspannteWoche regel={regel} setRegel={setRegel} />
      <LernEinstellungen regel={regel} setRegel={setRegel} />
      <div className="knopf-gruppe">
        <Button type="submit" variante="bestaetigen" icon="ok">
          Speichern
        </Button>
      </div>
    </form>
  )
}

const uhrzeit = (d) => new Date(d).toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })

function SerienVerwaltung({ setMeldung }) {
  const heute = new Date().toISOString().slice(0, 10)
  const [serien, setSerien] = useState([])
  const [neu, setNeu] = useState({ wochentage: [], beginn: '08:00', ende: '12:00', von: heute, bis: heute, notiz: '' })
  const [zuLoeschen, setZuLoeschen] = useState(null) // Serie, für die die Rückfrage offen ist

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
    <Karte titel="Feste Serien" icon="arbeit">
      <div className="stapel">
        {serien.length > 0 ? (
          <Tabelle>
            <thead>
              <tr>
                <th>Zeitraum</th>
                <th className="mitte">Blöcke</th>
                <th>Notiz</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {serien.map((s) => (
                <tr key={s.serie_id}>
                  <td>
                    {datum(s.erster)} – {datum(s.letzter)}
                    <div className="leise klein">ab {uhrzeit(s.erster)}</div>
                  </td>
                  <td className="mitte">{s.anzahl}</td>
                  <td>{s.notiz}</td>
                  <td className="zahl">
                    <IconButton icon="loeschen" ton="verwerfen" klein label="Serie löschen" onClick={() => setZuLoeschen(s)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </Tabelle>
        ) : (
          <p className="leise klein">Noch keine Serien. Feste Arbeitszeiten werden als fixe Blöcke angelegt.</p>
        )}

        <form className="formular" onSubmit={anlegen}>
          <h3>Neue Serie</h3>
          <TagAuswahl titel="Wochentage" werte={neu.wochentage} onChange={(w) => setNeu({ ...neu, wochentage: w })} />
          <div className="formular-zeile">
            <Feld label="Beginn">
              <Eingabe type="time" breite="mittel" step="900" value={neu.beginn} onChange={setze('beginn')} />
            </Feld>
            <Feld label="Ende">
              <Eingabe type="time" breite="mittel" step="900" value={neu.ende} onChange={setze('ende')} />
            </Feld>
          </div>
          <div className="formular-zeile">
            <Feld label="Von">
              <Eingabe type="date" breite="mittel" value={neu.von} onChange={setze('von')} />
            </Feld>
            <Feld label="Bis">
              <Eingabe type="date" breite="mittel" value={neu.bis} onChange={setze('bis')} />
            </Feld>
          </div>
          <Feld label="Notiz">
            <Eingabe value={neu.notiz} onChange={setze('notiz')} />
          </Feld>
          <div className="knopf-gruppe">
            <Button type="submit" icon="neu" disabled={neu.wochentage.length === 0}>
              Serie anlegen
            </Button>
          </div>
        </form>
      </div>

      {zuLoeschen && (
        <Dialog
          titel="Serie löschen"
          onSchliessen={() => setZuLoeschen(null)}
          aktionen={
            <>
              <Button onClick={() => setZuLoeschen(null)}>Abbrechen</Button>
              <Button
                onClick={() => {
                  loeschen(zuLoeschen, heute)
                  setZuLoeschen(null)
                }}
              >
                Ab heute löschen
              </Button>
              <Button
                variante="verwerfen"
                onClick={() => {
                  loeschen(zuLoeschen)
                  setZuLoeschen(null)
                }}
              >
                Ganz löschen
              </Button>
            </>
          }
        >
          <p>
            {zuLoeschen.anzahl} Blöcke von {datum(zuLoeschen.erster)} bis {datum(zuLoeschen.letzter)}
            {zuLoeschen.notiz && ` („${zuLoeschen.notiz}“)`}. Nur die künftigen oder alle Blöcke löschen?
          </p>
        </Dialog>
      )}
    </Karte>
  )
}

export default function ArbeitEinstellungen() {
  const [meldung, setMeldung] = useState(null)
  return (
    <div className="seite">
      <SeitenKopf titel="Arbeitszeiten">
        Wochenstunden und Zeitfenster festlegen; der Hub verteilt die Arbeit dann automatisch in die freien Lücken.
      </SeitenKopf>
      {meldung && (
        <Hinweis ton={meldung.art === 'ok' ? 'erfolg' : 'fehler'} titel={meldung.text} onSchliessen={() => setMeldung(null)} />
      )}
      <div className="arbeit-spalten">
        <RegelFormular setMeldung={setMeldung} />
        <SerienVerwaltung setMeldung={setMeldung} />
      </div>
    </div>
  )
}
