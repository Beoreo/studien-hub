import { Fragment, useEffect, useState } from 'react'
import { api, dauerText, videoZusammenfassung } from '../api.js'
import {
  Auswahl,
  Badge,
  Button,
  Eingabe,
  Feld,
  Hinweis,
  Icon,
  IconButton,
  Karte,
  Kontrolle,
  LeererZustand,
  SeitenKopf,
  Tabelle,
  ZahlEingabe,
  komma,
  kurzTitel, lvaName,
} from '../ui.jsx'
import './LvaListe.css'

const MARKIERUNGEN = [
  { feld: 'steop', icon: 'steop', name: 'STEOP' },
  { feld: 'anwesenheitspflicht', icon: 'anwesenheit', name: 'Anwesenheitspflicht' },
  { feld: 'aufzeichnung', icon: 'aufzeichnung', name: 'Aufzeichnung' },
]

const AUSBLENDEN_TEXT = 'Ausgeblendete LVAs erscheinen nicht im Kalender und werden nicht geplant'

// Eine LVA fasst VO, UE und Gruppen zusammen: Farbe, ECTS und Lernwerte gemeinsam,
// Markierungen und TUWEL-Kurs je Teil (einmal pro Semester setzen).
export default function LvaListe({ lvas, onGeaendert }) {
  const [fehler, setFehler] = useState(null)
  const [steop, setSteop] = useState(null)
  const steopFertig = steop ? steop.abgeschlossen : null

  // nach jeder Änderung neu laden: eingeblendete Nicht-STEOP-ECTS ändern sich mit
  useEffect(() => {
    api.steopStatus().then(setSteop).catch((e) => setFehler(e.message))
  }, [lvas])

  const steopAusfuehren = (aufruf) =>
    aufruf
      .then((s) => {
        setSteop(s)
        onGeaendert()
      })
      .catch((e) => setFehler(e.message))
  const steopSetzen = (daten) => steopAusfuehren(api.steopSetzen(daten))
  const varianteNeu = () => steopAusfuehren(api.steopVarianteNeu())
  const varianteAendern = (lva, enthalten) => steopAusfuehren(api.steopVarianteAendern(lva.id, enthalten))

  const ausfuehren = (aufruf) => aufruf.then(onGeaendert).catch((e) => setFehler(e.message))
  const aendern = (lva, daten) => ausfuehren(api.lvaAendern(lva.id, daten))
  const teilAendern = (teil, daten) => ausfuehren(api.teilAendern(teil.id, daten))

  const semester = [...new Set(lvas.map((l) => l.semester))]

  if (lvas.length === 0) {
    return (
      <div className="seite">
        <LeererZustand titel="Noch keine LVAs">Importiere zuerst deinen TISS-Kalender.</LeererZustand>
      </div>
    )
  }

  // ein Hinweisbereich: Fehler vor den Warnungen der STEOP-Variante
  const warnungen = steop && !steop.abgeschlossen ? steop.warnungen : []

  return (
    <div className="seite lva-seite">
      <SeitenKopf titel="LVAs">
        VO, UE und Gruppen stehen gemeinsam unter einer LVA; STEOP, Anwesenheitspflicht und Aufzeichnung setzt du je Teil
        einmal pro Semester.
      </SeitenKopf>
      {fehler ? (
        <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} />
      ) : (
        warnungen.length > 0 && (
          <Hinweis ton="warnung" titel={warnungen.length === 1 ? warnungen[0] : `${warnungen.length} Warnungen zur STEOP-Variante`}>
            {warnungen.length > 1 && (
              <ul>
                {warnungen.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
          </Hinweis>
        )
      )}
      <SteopKasten
        steop={steop}
        steopSetzen={steopSetzen}
        varianteNeu={varianteNeu}
        varianteAendern={varianteAendern}
        ausgeblendet={lvas.filter((l) => !l.besucht).length}
      />
      {semester.map((s) => {
        const imSemester = lvas.filter((l) => l.semester === s)
        const besucht = imSemester.filter((l) => l.besucht)
        return (
          <Karte
            key={s}
            aufklappbar
            offen={besucht.length > 0}
            titel={`Semester ${s}`}
            className="lva-semester"
            aktionen={
              <span className="leise klein">
                {besucht.length} von {imSemester.length} LVAs besucht
              </span>
            }
          >
            <div className="stapel">
              <Tabelle className="lva-tabelle">
                <thead>
                  <tr>
                    <th>
                      <span className="nur-screenreader">Farbe</span>
                    </th>
                    <th>LVA / Teil</th>
                    <th>Nummer</th>
                    {MARKIERUNGEN.map((m) => (
                      <th key={m.feld} className="mitte">
                        <Icon name={m.icon} label={m.name} />
                      </th>
                    ))}
                    <th>TUWEL-Kurs</th>
                    <th className="zahl">Termine</th>
                    <th className="zahl" title="Aufzeichnungen aus TUWEL (Anzahl und Gesamtdauer)">
                      Videos
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {imSemester
                    .sort((a, b) => Number(b.besucht) - Number(a.besucht))
                    .map((lva) => (
                      <Fragment key={lva.id}>
                        <tr className={lva.besucht ? 'lva-zeile' : 'lva-zeile gedimmt'}>
                          <td>
                            <input
                              type="color"
                              className="lva-farbe"
                              value={lva.farbe}
                              aria-label={`Farbe von ${lva.titel}`}
                              title="Farbe im Kalender"
                              onChange={(e) => aendern(lva, { farbe: e.target.value })}
                            />
                          </td>
                          <td className="lva-name">
                            <strong>{lva.titel}</strong>
                            <div className="lva-einstellungen">
                              <label className="lva-kurzname">
                                <span className="leise klein">Im Kalender</span>
                                <Eingabe
                                  breite="mittel"
                                  defaultValue={lva.kurzname || ''}
                                  placeholder={kurzTitel(lva.titel)}
                                  title="Kurzname im Kalender – leer = gekürzter Titel"
                                  onBlur={(e) =>
                                    e.target.value !== (lva.kurzname || '') && aendern(lva, { kurzname: e.target.value || null })
                                  }
                                />
                              </label>
                              <Besuchen lva={lva} steopFertig={steopFertig} aendern={aendern} varianteAendern={varianteAendern} />
                            </div>
                          </td>
                          <td className="leise klein">{lva.teile.length > 1 ? `${lva.teile.length} Teile` : ''}</td>
                          {MARKIERUNGEN.map((m) => (
                            <td key={m.feld} />
                          ))}
                          <td />
                          <td className="zahl">{lva.anzahl_termine}</td>
                          <td className="zahl">
                            {videoZusammenfassung(lva.anzahl_videos, lva.video_dauer_sekunden, lva.videos_ohne_dauer)}
                          </td>
                        </tr>
                        {lva.teile.map((teil) => (
                          <tr key={`t${teil.id}`} className={lva.besucht ? 'teil-zeile' : 'teil-zeile gedimmt'}>
                            <td>
                              <span className="lva-streifen" style={{ background: lva.farbe }} />
                            </td>
                            <td className="teil-name">{teil.bezeichnung}</td>
                            <td>{teil.nummer || '–'}</td>
                            {MARKIERUNGEN.map((m) => (
                              <td key={m.feld} className="mitte">
                                <input
                                  type="checkbox"
                                  className="lva-haken"
                                  aria-label={`${m.name} für ${teil.bezeichnung}`}
                                  title={`${m.name} für ${teil.bezeichnung}`}
                                  checked={teil[m.feld]}
                                  onChange={(e) => teilAendern(teil, { [m.feld]: e.target.checked })}
                                />
                              </td>
                            ))}
                            <td>
                              <ZahlEingabe
                                wert={teil.tuwel_kurs_id}
                                aria-label={`TUWEL-Kurs-ID für ${teil.bezeichnung}`}
                                onSpeichern={(tuwel_kurs_id) => teilAendern(teil, { tuwel_kurs_id })}
                              />
                            </td>
                            <td className="zahl">{teil.anzahl_termine}</td>
                            <td />
                          </tr>
                        ))}
                      </Fragment>
                    ))}
                </tbody>
              </Tabelle>
              {besucht.length > 0 && (
                <>
                  <Lernbedarf lvas={besucht} aendern={aendern} />
                  <Lernaufwand lvas={besucht} aendern={aendern} />
                </>
              )}
            </div>
          </Karte>
        )
      })}
      <p className="leise klein">
        Einzelne Termine markierst du im Kalender per Klick abweichend. Ferien und Feiertage aus TISS sind keine LVAs – sie
        stehen im Reiter „TISS-Import“.
      </p>
    </div>
  )
}

const zeitText = (zeit) => new Date(zeit).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' })

// STEOP-Status: aus TISS (Browser-Erweiterung) oder von Hand. Solange sie offen ist, gilt eine Variante:
// STEOP-LVAs, die die TISS-Kriterien erfüllen, dazu Nicht-STEOP-LVAs bis zu den erlaubten ECTS.
function SteopKasten({ steop, steopSetzen, varianteNeu, varianteAendern, ausgeblendet }) {
  if (!steop) return null
  const tiss = steop.tiss
  const offen = !steop.abgeschlossen
  return (
    <Karte
      titel="STEOP"
      icon="steop"
      aktionen={
        offen && (
          <Button
            klein
            icon="aktualisieren"
            onClick={varianteNeu}
            disabled={!steop.variante_bearbeitet}
            title={steop.variante_bearbeitet ? 'Deine Änderungen verwerfen und neu berechnen' : 'Die Variante ist schon automatisch erzeugt'}
          >
            Neue Variante erzeugen
          </Button>
        )
      }
    >
      <div className="stapel">
        <div className="reihe">
          <Kontrolle
            label={<strong>STEOP noch offen</strong>}
            title="Angehakt: Die STEOP ist noch offen, besucht wird die Variante"
            checked={offen}
            onChange={(e) => steopSetzen({ abgeschlossen: !e.target.checked })}
          />
          <span className="leise klein">
            {steop.quelle === 'tiss' && tiss
              ? `aus TISS, Stand ${zeitText(tiss.zeit)}`
              : steop.quelle === 'manuell'
                ? 'von Hand gesetzt – der nächste Stand aus TISS überschreibt das'
                : 'noch nicht aus TISS gelesen: in TISS „LVA Cockpit → STEOP Status“ öffnen (Erweiterung muss installiert sein)'}
          </span>
        </div>
        {!offen ? (
          <p className="leise">Alle LVAs werden besucht, außer du blendest sie aus.</p>
        ) : (
          <>
            <div className="formular-zeile">
              <Feld
                label="Erlaubte Non-STEOP-ECTS"
                hilfe={steop.erlaubte_ects_quelle === 'tiss' ? `leer = Wert aus TISS (${komma(steop.erlaubte_ects)})` : 'leer = Wert aus TISS'}
              >
                <ZahlEingabe
                  wert={steop.erlaubte_ects_quelle === 'manuell' ? steop.erlaubte_ects : null}
                  schritt="0.5"
                  title="Nicht-STEOP-ECTS, die vor Abschluss der STEOP vorgezogen werden dürfen"
                  onSpeichern={(erlaubte_ects) => steopSetzen({ erlaubte_ects })}
                />
              </Feld>
              <div className="steop-variante">
                <span className="feld-beschriftung">Variante {steop.semester}</span>
                <div className="reihe">
                  <Badge icon="steop">{steop.steop_gewaehlt} STEOP-LVAs</Badge>
                  <Badge>
                    {komma(steop.vorgezogen_ects)} von {komma(steop.erlaubte_ects ?? 0)} Non-STEOP-ECTS
                  </Badge>
                  {ausgeblendet > 0 && (
                    <Badge icon="ausgeblendet" title={AUSBLENDEN_TEXT}>
                      {ausgeblendet} ausgegraut
                    </Badge>
                  )}
                  <span className="leise klein">
                    {steop.variante_bearbeitet ? 'von dir bearbeitet' : 'automatisch erzeugt – hake LVAs an oder ab, um sie zu bearbeiten'}
                  </span>
                </div>
              </div>
            </div>
            {steop.kriterien.length > 0 ? (
              <Karte
                aufklappbar
                className="steop-kriterien"
                titel={`STEOP-Kriterien aus TISS${steop.kriterien.length > 1 ? ` (${steop.verknuepfung === 'OR' ? 'eines' : 'alle'} davon)` : ''}`}
              >
                <p className="leise klein">Die Variante erfüllt sie mit möglichst wenig ECTS.</p>
                <KriterienBaum knoten={steop.kriterien} varianteAendern={varianteAendern} />
              </Karte>
            ) : (
              <p className="leise klein">
                Keine STEOP-Kriterien aus TISS – in TISS bei „STEOP Status“ die „Detailansicht offener STEOPs“ aufklappen. Bis
                dahin gehören alle STEOP-LVAs zur Variante.
              </p>
            )}
          </>
        )}
      </div>
    </Karte>
  )
}

const KRITERIUM_TEXT = { ects: (w) => `${komma(w)} ECTS aus`, anzahl: (w) => `${w} aus`, alle: () => 'Alle aus' }

// Kriterienbaum: je Knoten erfüllt/offen mit der Variante, je LVA anhakbar (wenn dieses Semester angeboten)
function KriterienBaum({ knoten, varianteAendern }) {
  return (
    <ul className="kriterien-baum">
      {knoten.map((k, i) =>
        k.art === 'lva' ? (
          <li key={`${k.nummer}-${i}`} className="kriterium-lva">
            {k.erledigt ? (
              <span className="kriterium-erledigt">
                <Icon name="erledigt" label="In TISS schon erledigt" />
                <span>
                  {k.nummer} {k.titel}
                </span>
              </span>
            ) : (
              <Kontrolle
                label={[k.nummer, k.titel].filter(Boolean).join(' ')}
                checked={k.in_variante}
                disabled={k.lva_id == null}
                title={k.lva_id == null ? 'Dieses Semester nicht im Kalender' : 'In der Variante'}
                onChange={(e) => varianteAendern({ id: k.lva_id }, e.target.checked)}
              />
            )}
            {k.ects != null && <span className="leise klein">{komma(k.ects)} ECTS</span>}
            {k.lva_id == null && !k.erledigt && <Badge ton="umriss">nicht angeboten</Badge>}
          </li>
        ) : (
          <li key={`${k.name}-${i}`}>
            <span className="kriterium">
              {k.erfuellt_variante ? (
                <Badge ton="bestaetigen" icon="erledigt">
                  erfüllt
                </Badge>
              ) : (
                <Badge>offen</Badge>
              )}
              <strong>
                {k.name && `${k.name}: `}
                {KRITERIUM_TEXT[k.art]?.(k.wert) ?? k.art}
              </strong>
            </span>
            <KriterienBaum knoten={k.kinder} varianteAendern={varianteAendern} />
          </li>
        ),
      )}
    </ul>
  )
}

const BESUCHEN = [
  { wert: 'auto', name: 'automatisch (besucht)' },
  { wert: 'ja', name: 'einblenden' },
  { wert: 'nein', name: 'ausblenden' },
]

// Besuchen dieses Semester: solange die STEOP offen ist über die Variante, danach automatisch oder manuell
function Besuchen({ lva, steopFertig, aendern, varianteAendern }) {
  const ausgeblendetBadge = !lva.besucht && (
    <Badge icon="ausgeblendet" title={AUSBLENDEN_TEXT}>
      ausgeblendet
    </Badge>
  )
  if (steopFertig === false) {
    return (
      <div className="lva-besuchen">
        <Kontrolle
          label="in der Variante"
          title={AUSBLENDEN_TEXT}
          checked={lva.besucht}
          onChange={(e) => varianteAendern(lva, e.target.checked)}
        />
        {lva.ist_steop && <Badge icon="steop">STEOP</Badge>}
        {ausgeblendetBadge}
      </div>
    )
  }
  const wert = lva.besuchen === null || lva.besuchen === undefined ? 'auto' : lva.besuchen ? 'ja' : 'nein'
  return (
    <div className="lva-besuchen">
      <Auswahl
        breite="mittel"
        optionen={BESUCHEN}
        value={wert}
        aria-label="Besuchen"
        title={AUSBLENDEN_TEXT}
        onChange={(e) => aendern(lva, { besuchen: e.target.value === 'auto' ? null : e.target.value === 'ja' })}
      />
      {ausgeblendetBadge}
    </div>
  )
}

const LERNWERTE = [
  { feld: 'minuten_pro_folie', name: 'Min./Folie', schritt: '0.5' },
  { feld: 'minuten_pro_skriptseite', name: 'Min./Skriptseite', schritt: '0.5' },
  { feld: 'minuten_pro_uebungsblatt', name: 'Min./Übungsblatt', schritt: '15' },
  { feld: 'video_faktor', name: 'Videofaktor', schritt: '0.1' },
  { feld: 'minuten_sonstiges', name: 'Min./sonstige Datei', schritt: '5' },
]

const ZIELE = [
  { wert: 'bestehen', name: 'bestehen (× 0,6)' },
  { wert: 'normal', name: 'normal (× 0,8)' },
  { wert: 'gut', name: 'gute Note (× 1,0)' },
]

const stunden = (minuten) => (minuten ? `${(minuten / 60).toFixed(1).replace('.', ',')} h` : '–')

// Name in den Detailtabellen: kurz, voller Titel als Tooltip
const LvaName = ({ lva }) => <span title={lva.titel}>{lvaName(lva)}</span>

// Lernbedarf je LVA: (ECTS × 25 h − Präsenz) × ECTS-Faktor × Ziel × Regler, verteilt bis zur Prüfung
function Lernbedarf({ lvas, aendern }) {
  return (
    <Karte aufklappbar titel="Prüfungen und Lernbedarf" icon="pruefung">
      <p className="leise klein">
        Lernzeit = (ECTS × 25 h − Präsenzstunden) × ECTS-Faktor (Reiter „Arbeitszeiten“) × Ziel × Anpassung. Lernblöcke gibt es
        nur in den Wochen vor den angemeldeten Prüfungen – wie viele, stellst du im Reiter „Prüfungen“ je LVA ein.
      </p>
      <Tabelle>
        <thead>
          <tr>
            <th>LVA</th>
            <th title="1 ECTS = 25 Stunden Gesamtaufwand">ECTS</th>
            <th>Prüfungen</th>
            <th>Ziel</th>
            <th title="Wochenbedarf anpassen: 100 % = wie berechnet">Anpassung</th>
            <th className="zahl" title="In einer Woche vor einer Prüfung">
              pro Lernwoche
            </th>
            <th className="zahl">Semester</th>
          </tr>
        </thead>
        <tbody>
          {lvas.map((lva) => (
            <tr key={lva.id}>
              <td>
                <LvaName lva={lva} />
              </td>
              <td>
                <ZahlEingabe wert={lva.ects} schritt="0.5" aria-label="ECTS" onSpeichern={(ects) => aendern(lva, { ects })} />
              </td>
              <td>
                <Pruefungen lva={lva} />
              </td>
              <td>
                <Auswahl
                  breite="mittel"
                  optionen={ZIELE}
                  aria-label="Ziel"
                  value={lva.ziel}
                  onChange={(e) => aendern(lva, { ziel: e.target.value })}
                />
              </td>
              <td>
                <Regler wert={lva.bedarf_faktor} onSpeichern={(bedarf_faktor) => aendern(lva, { bedarf_faktor })} />
              </td>
              <td className="zahl">{lva.ects ? stunden(lva.wochenbedarf_minuten) : <span className="leise">ECTS fehlen</span>}</td>
              <td className="zahl">{lva.ects ? dauerText(lva.gesamtbedarf_minuten * 60) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </Tabelle>
    </Karte>
  )
}

// Nächste Prüfung der LVA; Termine wählt und trägt man im Reiter „Prüfungen“ ein
function Pruefungen({ lva }) {
  if (!lva.pruefung) {
    return (
      <a href="#pruefungen" className="leise">
        keine – eintragen
      </a>
    )
  }
  const vorschlag = lva.pruefung_quelle === 'vorschlag'
  return (
    <a
      href="#pruefungen"
      className="lva-pruefung"
      title={vorschlag ? 'Noch kein Termin gewählt – der nächste angebotene zählt' : 'Im Reiter „Prüfungen“ ändern'}
    >
      <Icon name="pruefung" />
      {new Date(lva.pruefung).toLocaleDateString('de-AT')}
      {vorschlag && <Badge>voraussichtlich</Badge>}
    </a>
  )
}

// Schieberegler 0–200 %, gespeichert beim Loslassen
function Regler({ wert, onSpeichern }) {
  const [prozent, setProzent] = useState(Math.round((wert ?? 1) * 100))
  useEffect(() => setProzent(Math.round((wert ?? 1) * 100)), [wert])
  const speichern = () => prozent / 100 !== wert && onSpeichern(prozent / 100)
  return (
    <span className="lva-regler">
      <input
        type="range"
        className="eingabe"
        min="0"
        max="200"
        step="10"
        value={prozent}
        onChange={(e) => setProzent(Number(e.target.value))}
        onPointerUp={speichern}
        onKeyUp={speichern}
        aria-label="Wochenbedarf anpassen"
      />
      <span className="lva-regler-wert">{prozent} %</span>
    </span>
  )
}

// Gewichtung des Stoffs je LVA: bestimmt nur, welcher Stoff in einem Lernblock dran ist, nicht wie viel Zeit
function Lernaufwand({ lvas, aendern }) {
  return (
    <Karte aufklappbar titel="Stoffgewichtung" icon="lernen">
      <p className="leise klein">
        Bestimmt nur, welcher Stoff in einem Lernblock dran ist, nicht die Lernzeit: Folien und Skripte zählen nach Seiten (PDF
        im Querformat = Folien), Videos nach Dauer × Faktor, Übungsblätter mit festem Wert.
      </p>
      <Tabelle>
        <thead>
          <tr>
            <th>LVA</th>
            {LERNWERTE.map((w) => (
              <th key={w.feld}>{w.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lvas.map((lva) => (
            <tr key={lva.id}>
              <td>
                <LvaName lva={lva} />
              </td>
              {LERNWERTE.map((w) => (
                <td key={w.feld}>
                  <ZahlEingabe
                    wert={lva.lernparameter?.[w.feld]}
                    schritt={w.schritt}
                    leerErlaubt={false}
                    aria-label={w.name}
                    onSpeichern={(wert) => aendern(lva, { lernparameter: { [w.feld]: wert } })}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </Tabelle>
    </Karte>
  )
}
