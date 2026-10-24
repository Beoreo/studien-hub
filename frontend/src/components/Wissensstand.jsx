import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Badge, Button, Dialog, Eingabe, Feld, Hinweis, Icon, IconButton, Karte, LeererZustand, Rueckfrage, SeitenKopf, Auswahl, kurzTitel } from '../ui.jsx'
import { zeitstrahl } from '../zeitstrahl.js'
import './Wissensstand.css'

export const STUFEN = [
  { wert: 0, name: 'neu' },
  { wert: 1, name: 'gesehen' },
  { wert: 2, name: 'mit Hilfe' },
  { wert: 3, name: 'sicher' },
  { wert: 4, name: 'prüfungsfest' },
]

const ARTEN = [
  { wert: 'quiz', name: 'Quiz' },
  { wert: 'altpruefung', name: 'Altprüfung' },
  { wert: 'lernblock', name: 'Lernblock' },
]

const tag = (iso) => (iso ? new Date(iso).toLocaleDateString('de-AT', { weekday: 'short', day: '2-digit', month: '2-digit' }) : '–')

// Wissensstand je LVA: Themen als farbige Kacheln, fällige Wiederholungen, Abstand zur Prüfung
export default function Wissensstand() {
  const [daten, setDaten] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [meldung, setMeldung] = useState(null)
  const [auswahl, setAuswahl] = useState(null) // Thema-ID

  const laden = useCallback(() => {
    api.wissenUebersicht().then(setDaten).catch((e) => setFehler(e.message))
  }, [])
  useEffect(laden, [laden])

  const ausfuehren = (aufruf) => aufruf.then(laden).catch((e) => setFehler(e.message))

  async function ableiten() {
    try {
      const { neue_themen } = await api.themenAbleiten()
      const summe = Object.values(neue_themen).reduce((a, b) => a + b, 0)
      setMeldung(summe ? `${summe} neue Themen aus den Skripten.` : 'Keine neuen Themen – vorhandene bleiben unverändert.')
      laden()
    } catch (e) {
      setFehler(e.message)
    }
  }

  const kopf = (
    <SeitenKopf
      titel="Wissensstand"
      aktion={
        <Button variante="primaer" icon="aktualisieren" onClick={ableiten} title="Fehlende Themen aus der Gliederung der Skripte anlegen; eigene bleiben">
          Themen aus Skripten ableiten
        </Button>
      }
    >
      Je Kurs ein Zeitstrahl bis zu den Prüfungen – ein Klick auf einen Abschnitt zeigt Fortschritt und Themen dieser Prüfung.
    </SeitenKopf>
  )

  // Höchstens ein Hinweis: Fehler vor Meldung vor Erklärung
  const hinweis = fehler ? (
    <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} />
  ) : meldung ? (
    <Hinweis ton="erfolg" titel={meldung} onSchliessen={() => setMeldung(null)} />
  ) : (
    <Hinweis titel="Prüfungsstoff hochladen bestimmt die Themen einer Prüfung; Quiz und Altprüfungen passen die Stufe an.">
      <p>
        Je Prüfung kannst du den Stoff hochladen (Stoffliste mit einem Thema je Zeile, Skript mit Kapiteln oder Folien) – die
        Themen dieser Prüfung entstehen daraus, der Lernstand bleibt. Ohne Stoff gelten die Themen aus den Skripten. Quiz und
        Altprüfungen (auch über Claude) passen die Stufe an; die nächste Wiederholung kommt nach 1, 2, 4, 9 oder 21 Tagen –
        spätestens am Tag vor der Prüfung.
      </p>
      <div className="stufen-reihe">
        {STUFEN.map((s) => (
          <span key={s.wert} className={`stufe-chip stufe-${s.wert}`}>
            {s.wert} {s.name}
          </span>
        ))}
      </div>
    </Hinweis>
  )

  if (!daten) {
    return (
      <div className="seite">
        {kopf}
        {fehler ? hinweis : <p className="leise">Lade …</p>}
      </div>
    )
  }
  const faellig = daten.flatMap((l) => l.faellig.map((t) => ({ ...t, lva: l.lva, farbe: l.farbe })))
  const gewaehlt = daten.flatMap((l) => l.themen).find((t) => t.id === auswahl)

  return (
    <div className="seite wissensstand">
      {kopf}
      {hinweis}

      {faellig.length > 0 && (
        <Karte titel={`Fällige Wiederholungen (${faellig.length})`} icon="aktualisieren">
          <ul className="faellig-liste">
            {faellig.map((t) => (
              <li key={t.id}>
                <span className="farbpunkt" style={{ background: t.farbe }} />
                <span className="faellig-text">
                  <strong>{t.lva}</strong> {t.titel}
                  <span className="leise klein"> · fällig seit {tag(t.naechste_wiederholung)}</span>
                </span>
                <span className={`stufe-chip stufe-${t.stufe}`}>{t.stufe_name}</span>
                <Button klein onClick={() => setAuswahl(t.id)}>
                  Üben eintragen
                </Button>
              </li>
            ))}
          </ul>
        </Karte>
      )}

      {daten.length === 0 && (
        <LeererZustand icon="lernen" titel="Keine besuchten LVAs">
          Sobald der TISS-Import LVAs kennt, erscheint hier je Kurs ein Zeitstrahl bis zu den Prüfungen.
        </LeererZustand>
      )}
      <div className="stapel">
        {daten.map((l) => (
          <LvaKarte key={l.lva_id} lva={l} auswahl={auswahl} setAuswahl={setAuswahl} ausfuehren={ausfuehren} setFehler={setFehler} />
        ))}
      </div>

      {gewaehlt && (
        <ThemaDialog thema={gewaehlt} onSchliessen={() => setAuswahl(null)} ausfuehren={ausfuehren} setFehler={setFehler} />
      )}
    </div>
  )
}

const datumKurz = (iso) => new Date(iso).toLocaleDateString('de-AT', { weekday: 'short', day: '2-digit', month: '2-digit' })
const prozent = (anteil) => `${Math.round(anteil * 100)} %`
// für CSS-Breiten ohne Leerzeichen ("50 %" wäre ungültig)
const breite = (anteil) => `${Math.round(anteil * 1000) / 10}%`

// Breiten der Abschnitte: gleicher angepasster Maßstab wie im Reiter „Prüfungen“ (nahe Prüfungen nicht zu schmal)
function abschnittsBreiten(zeitstrahlDaten) {
  const tage = [zeitstrahlDaten[0].von, ...zeitstrahlDaten.map((a) => a.datum)].map((d) => ({ datum: new Date(d) }))
  const { punkte } = zeitstrahl(tage)
  if (punkte.length < 2) return zeitstrahlDaten.map(() => 1 / zeitstrahlDaten.length)
  return zeitstrahlDaten.map((_, i) => (punkte[i + 1]?.pos ?? 1) - (punkte[i]?.pos ?? 0))
}

function Balken({ label, anteil, art }) {
  return (
    <div className="kurs-balken-zeile">
      <span className="klein kurs-balken-label">{label}</span>
      <div className={`kurs-balken ${art}`} role="progressbar" aria-valuenow={Math.round(anteil * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <span style={{ width: breite(anteil) }} />
      </div>
      <span className="klein kurs-balken-wert">{prozent(anteil)}</span>
    </div>
  )
}

// Zeitstrahl eines Kurses: Abschnitte bis zu jeder Prüfung; ein Klick zeigt Fortschritt, Themen und Prüfungsstoff
function KursZeitstrahl({ lva, auswahl, setAuswahl, ausfuehren, setFehler }) {
  const abschnitte = lva.zeitstrahl
  const standard = Math.max(abschnitte.findIndex((a) => !a.vorbei), 0)
  const [gewaehlt, setGewaehlt] = useState(standard)
  const [laedt, setLaedt] = useState(false)
  if (!abschnitte.length) {
    return (
      <p className="leise klein">
        Keine Prüfung eingetragen – im Reiter <a href="#pruefungen">„Prüfungen“</a> den Termin wählen, dann erscheint hier der Zeitstrahl.
      </p>
    )
  }
  const breiten = abschnittsBreiten(abschnitte)
  const a = abschnitte[Math.min(gewaehlt, abschnitte.length - 1)]
  const themen = a.themen.map((id) => lva.themen.find((t) => t.id === id)).filter(Boolean)
  const eigenerStoff = a.stoff[0]

  const hochladen = (datei) => {
    if (!datei) return
    setLaedt(true)
    ausfuehren(api.stoffHochladen(lva.lva_id, a.datum, datei)).finally(() => setLaedt(false))
  }

  return (
    <div className="stapel">
      <div className="kurs-zeitstrahl" role="tablist" aria-label={`Zeitstrahl ${lva.lva}`}>
        {abschnitte.map((s, i) => (
          <button
            key={s.datum}
            type="button"
            role="tab"
            aria-selected={i === gewaehlt}
            className={`kurs-abschnitt${i === gewaehlt ? ' gewaehlt' : ''}${s.vorbei ? ' vorbei' : ''}`}
            style={{ flexGrow: breiten[i], '--lva': lva.farbe }}
            onClick={() => setGewaehlt(i)}
            title={`${datumKurz(s.von)} bis Prüfung ${datumKurz(s.datum)} · Stoff ${prozent(s.fortschritt)}`}
          >
            <span className="kurs-abschnitt-fuellung" style={{ width: breite(s.fortschritt) }} />
            {!s.vorbei && s.zeit_anteil > 0 && s.zeit_anteil < 1 && (
              <span className="kurs-heute" style={{ left: breite(s.zeit_anteil) }} aria-hidden="true" />
            )}
            <span className="kurs-abschnitt-text">
              <Icon name="pruefung" />
              {datumKurz(s.datum)}
            </span>
          </button>
        ))}
      </div>

      <div className="kurs-detail">
        <div className="kurs-detail-kopf">
          <strong>
            {datumKurz(a.von)} – Prüfung am {datumKurz(a.datum)}
          </strong>
          {a.quelle === 'vorschlag' && <Badge>voraussichtlich</Badge>}
          {a.vorbei && <Badge ton="umriss">vorbei</Badge>}
        </div>
        <Balken label="Stoff gelernt" anteil={a.fortschritt} art="stoff" />
        <Balken label="Zeit vergangen" anteil={a.zeit_anteil} art="zeit" />

        {themen.length > 0 ? (
          <div className="themen-kacheln">
            {themen.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`thema-kachel stufe-${t.stufe}${auswahl === t.id ? ' gewaehlt' : ''}`}
                onClick={() => setAuswahl(t.id)}
                title={`${t.stufe_name}${t.naechste_wiederholung ? ` · nächste Wiederholung ${tag(t.naechste_wiederholung)}` : ''}`}
              >
                <span className="thema-titel">{t.titel}</span>
                <span className="thema-info">
                  {t.stufe} · {t.stufe_name}
                  {t.faellig && <Icon name="aktualisieren" label="Wiederholung fällig" />}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="leise klein">Noch keine Themen für diese Prüfung – Prüfungsstoff hochladen.</p>
        )}

        <div className="reihe">
          <label className={`knopf knopf-umriss klein${laedt ? ' gesperrt' : ''}`} aria-disabled={laedt}>
            <Icon name="hochladen" />
            {laedt ? 'Lese Stoff …' : eigenerStoff ? 'Neuen Prüfungsstoff hochladen' : 'Prüfungsstoff hochladen'}
            <input
              type="file"
              className="nur-screenreader"
              accept=".pdf,.docx,.pptx,.ppsx,.odp,.txt,.md"
              disabled={laedt}
              onChange={(e) => {
                hochladen(e.target.files[0])
                e.target.value = ''
              }}
            />
          </label>
          {eigenerStoff ? (
            <span className="klein kurs-stoff">
              <a href={api.stoffUrl(eigenerStoff.id)} target="_blank" rel="noreferrer">
                {eigenerStoff.dateiname}
              </a>{' '}
              <span className="leise">· {eigenerStoff.themen} Themen</span>
              <IconButton
                icon="loeschen"
                klein
                ton="verwerfen"
                label="Prüfungsstoff entfernen (es gelten wieder die allgemeinen Themen)"
                onClick={() => ausfuehren(api.stoffLoeschen(eigenerStoff.id)).catch((e) => setFehler(e.message))}
              />
            </span>
          ) : (
            <span className="leise klein">Stoffliste (eine Zeile je Thema), Skript oder Folien – die Themen dieser Prüfung entstehen daraus.</span>
          )}
        </div>
      </div>
    </div>
  )
}

function LvaKarte({ lva, auswahl, setAuswahl, ausfuehren, setFehler }) {
  const [neu, setNeu] = useState('')
  const gesamt = lva.themen.length || 1
  return (
    <Karte
      className="wissen-lva"
      titel={
        <>
          <span className="farbpunkt" style={{ background: lva.farbe }} />
          {kurzTitel(lva.lva)}
        </>
      }
      aktionen={
        <>
          {lva.faellig.length > 0 && (
            <Badge ton="primaer" icon="aktualisieren">
              {lva.faellig.length} fällig
            </Badge>
          )}
          {lva.pruefung && (
            <Badge ton={lva.tage_bis_pruefung <= 14 ? 'verwerfen' : 'neutral'} icon="pruefung" title={`Prüfung am ${tag(lva.pruefung)}`}>
              in {lva.tage_bis_pruefung} Tagen
            </Badge>
          )}
        </>
      }
    >
      <div className="stapel">
        <KursZeitstrahl lva={lva} auswahl={auswahl} setAuswahl={setAuswahl} ausfuehren={ausfuehren} setFehler={setFehler} />

        <details className="wissen-notizen">
          <summary>
            <Icon name="auf" className="icon-auf" />
            Alle Themen ({lva.themen.length}) · {Math.round(lva.fortschritt * 100)} %
          </summary>
          <div className="stapel">
            {lva.themen.length > 0 && (
              <div
                className="stufen-balken"
                role="img"
                aria-label={`Verteilung der Stufen: ${STUFEN.map((s) => `${s.name} ${lva.verteilung[s.wert] || 0}`).join(', ')}`}
              >
                {STUFEN.map((s) =>
                  lva.verteilung[s.wert] ? (
                    <span key={s.wert} className={`stufe-${s.wert}`} style={{ flexGrow: lva.verteilung[s.wert] / gesamt }} title={`${s.name}: ${lva.verteilung[s.wert]}`}>
                      {lva.verteilung[s.wert]}
                    </span>
                  ) : null,
                )}
              </div>
            )}
            {lva.themen.length > 0 && (
              <div className="themen-kacheln">
                {lva.themen.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={`thema-kachel stufe-${t.stufe}${auswahl === t.id ? ' gewaehlt' : ''}`}
                    onClick={() => setAuswahl(t.id)}
                  >
                    <span className="thema-titel">{t.titel}</span>
                    <span className="thema-info">
                      {t.stufe} · {t.stufe_name}
                    </span>
                  </button>
                ))}
              </div>
            )}
            <div className="wissen-neu">
              <Eingabe aria-label="Eigenes Thema" placeholder="Eigenes Thema …" value={neu} onChange={(e) => setNeu(e.target.value)} />
              <Button
                klein
                icon="neu"
                disabled={!neu.trim()}
                onClick={() => ausfuehren(api.themaAnlegen({ lva_id: lva.lva_id, titel: neu.trim() })).then(() => setNeu(''))}
              >
                Hinzufügen
              </Button>
            </div>
          </div>
        </details>

        {lva.notizen.length > 0 && (
          <details className="wissen-notizen">
            <summary>
              <Icon name="auf" className="icon-auf" />
              Notizen ({lva.notizen.length})
            </summary>
            <ul>
              {lva.notizen.map((n) => (
                <li key={n.id}>
                  {n.quelle === 'ki' && (
                    <Badge ton="primaer" icon="ki">
                      Claude
                    </Badge>
                  )}{' '}
                  {n.text} <span className="leise klein">{tag(n.erstellt_am)}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Karte>
  )
}
function ThemaDialog({ thema, onSchliessen, ausfuehren, setFehler }) {
  const [titel, setTitel] = useState(thema.titel)
  const [prozent, setProzent] = useState('')
  const [art, setArt] = useState('quiz')
  const [abschnitte, setAbschnitte] = useState(null)
  const [frage, setFrage] = useState(false)

  useEffect(() => {
    setTitel(thema.titel)
    api.themaAbschnitte(thema.id).then(setAbschnitte).catch((e) => setFehler(e.message))
  }, [thema.id, thema.titel, setFehler])

  const ereignis = (daten) => ausfuehren(api.themaEreignis(thema.id, daten))

  if (frage) {
    return (
      <Rueckfrage
        titel="Thema löschen?"
        text={`Thema „${thema.titel}“ samt Wissensstand löschen?`}
        onNein={() => setFrage(false)}
        onJa={() => ausfuehren(api.themaLoeschen(thema.id)).then(onSchliessen)}
      />
    )
  }

  return (
    <Dialog
      titel={thema.titel}
      icon="lernen"
      breit
      onSchliessen={onSchliessen}
      aktionen={
        <>
          <Button variante="verwerfen" icon="loeschen" onClick={() => setFrage(true)}>
            Löschen
          </Button>
          <Button onClick={onSchliessen}>Schließen</Button>
        </>
      }
    >
      <p className="leise klein">
        Stufe {thema.stufe} ({thema.stufe_name}) · zuletzt geübt {tag(thema.letzte_uebung)} · nächste Wiederholung{' '}
        {tag(thema.naechste_wiederholung)}
        {thema.kapitel && <> · aus Kapitel „{thema.kapitel}“</>}
      </p>

      <section className="stapel thema-abschnitt">
        <h3>Selbsteinschätzung</h3>
        <div className="stufen-reihe">
          {STUFEN.map((s) => (
            <button
              key={s.wert}
              type="button"
              aria-pressed={thema.stufe === s.wert}
              className={`stufe-chip stufe-${s.wert}${thema.stufe === s.wert ? ' gewaehlt' : ''}`}
              onClick={() => ereignis({ art: 'selbsteinschaetzung', stufe: s.wert })}
            >
              {thema.stufe === s.wert && <Icon name="ok" />}
              {s.wert} {s.name}
            </button>
          ))}
        </div>
      </section>

      <section className="stapel thema-abschnitt">
        <h3>Ergebnis eintragen</h3>
        <div className="formular-zeile">
          <Feld label="Art">
            <Auswahl breite="mittel" optionen={ARTEN} value={art} onChange={(e) => setArt(e.target.value)} />
          </Feld>
          <Feld label="% richtig">
            <Eingabe type="number" breite="schmal" min="0" max="100" step="5" placeholder="%" value={prozent} onChange={(e) => setProzent(e.target.value)} />
          </Feld>
          <Button
            variante="bestaetigen"
            disabled={prozent === ''}
            onClick={() => ereignis({ art, ergebnis: Number(prozent) / 100 }).then(() => setProzent(''))}
          >
            Speichern
          </Button>
        </div>
      </section>

      <section className="stapel thema-abschnitt">
        <h3>Bearbeiten</h3>
        <div className="formular-zeile thema-bearbeiten">
          <Feld label="Titel" className="thema-titel-feld">
            <Eingabe value={titel} onChange={(e) => setTitel(e.target.value)} />
          </Feld>
          <Button
            variante="bestaetigen"
            disabled={titel.trim() === thema.titel}
            onClick={() => ausfuehren(api.themaAendern(thema.id, { titel: titel.trim() }))}
          >
            Umbenennen
          </Button>
          <div className="knopf-gruppe">
            <IconButton
              icon="hoch"
              label="In der Reihenfolge nach vorne"
              disabled={thema.reihenfolge <= 1}
              onClick={() => ausfuehren(api.themaAendern(thema.id, { reihenfolge: thema.reihenfolge - 1 }))}
            />
            <IconButton
              icon="runter"
              label="In der Reihenfolge nach hinten"
              onClick={() => ausfuehren(api.themaAendern(thema.id, { reihenfolge: thema.reihenfolge + 1 }))}
            />
          </div>
        </div>
      </section>

      <Karte aufklappbar titel={`Passende Abschnitte (${abschnitte?.length ?? '…'})`} icon="suche">
        <ul className="wissen-abschnitte">
          {(abschnitte || []).slice(0, 12).map((a) => (
            <li key={a.id}>
              <div className="wissen-abschnitt-kopf">
                {!a.offiziell && (
                  <Badge ton="umriss" icon="mbcloud">
                    MB Cloud {a.jahr || ''}
                  </Badge>
                )}
                <a href={api.dokumentUrl(a.dokument_id)} target="_blank" rel="noreferrer">
                  {a.dokument}
                </a>
                <span className="leise klein">{a.fundstelle}</span>
              </div>
              <p className="leise klein wissen-abschnitt-text">{a.text}</p>
            </li>
          ))}
        </ul>
      </Karte>
    </Dialog>
  )
}
