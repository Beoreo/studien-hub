import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import {
  Auswahl,
  Badge,
  Button,
  Dialog,
  Eingabe,
  Feld,
  Hinweis,
  Icon,
  IconButton,
  Karte,
  Kontrolle,
  LeererZustand,
  Rueckfrage,
  SeitenKopf,
  Tabelle,
  ZahlEingabe,
  lvaName,
} from '../ui.jsx'
import { abstandText, zeitstrahl } from '../zeitstrahl.js'
import './Pruefungen.css'

const QUELLEN = { tiss: 'TISS', tuwel: 'TUWEL', manuell: 'eigener' }
const z2 = (n) => String(n).padStart(2, '0')

const tagText = (d, mitJahr = true) =>
  new Date(d).toLocaleDateString('de-AT', { weekday: 'short', day: '2-digit', month: '2-digit', ...(mitJahr ? { year: 'numeric' } : {}) })
const zeitText = (d) => new Date(d).toLocaleTimeString('de-AT', { hour: '2-digit', minute: '2-digit' })
const zeitpunktText = (d) => `${tagText(d, false)} ${zeitText(d)}`

/** Datum und Uhrzeit eines Termins: „Fr., 23.01.2027 09:00–11:00“; ohne Ende nur der Tag. */
function terminZeit(t) {
  if (!t.ende) return tagText(t.start)
  return `${tagText(t.start)} ${zeitText(t.start)}–${zeitText(t.ende)}`
}

const optionText = (t) => `${terminZeit(t)} · ${t.titel}${t.quelle === 'manuell' ? '' : ` (${QUELLEN[t.quelle]})`}`

// --- Zeitstrahl ------------------------------------------------------------------------------------

function zeitstrahlEintraege(lvas, alle, heute) {
  const eintraege = [{ datum: heute, art: 'heute', name: 'Heute', key: 'heute' }]
  for (const lva of lvas) {
    const name = lvaName(lva)
    for (const t of lva.termine) {
      const start = new Date(t.start)
      if (start >= heute && (t.angemeldet || alle)) {
        eintraege.push({ datum: start, art: t.angemeldet ? 'pruefung' : 'option', name, farbe: lva.farbe, key: `p${t.id}`,
          titel: `${name}: ${t.titel}, ${terminZeit(t)}${t.angemeldet ? ' (angemeldet)' : ''}` })
      }
      // für angemeldete Termine auch der Tag, ab dem man sich anmelden kann
      if (t.angemeldet && t.anmeldung_von && new Date(t.anmeldung_von) >= heute) {
        eintraege.push({ datum: new Date(t.anmeldung_von), art: 'anmeldung', name, farbe: lva.farbe, key: `a${t.id}`,
          titel: `${name}: Anmeldung ab ${zeitpunktText(t.anmeldung_von)}` })
      }
    }
    for (const z of lva.feed_pruefungen) {
      const start = new Date(z)
      if (start >= heute) {
        eintraege.push({ datum: start, art: 'pruefung', name, farbe: lva.farbe, key: `f${lva.lva_id}-${z}`,
          titel: `${name}: Prüfung ${zeitpunktText(z)} (TISS-Kalender)` })
      }
    }
  }
  return eintraege
}

const ZEITSTRAHL_ICON = { pruefung: 'pruefung', option: 'pruefung', anmeldung: 'anmeldung' }

function Zeitstrahl({ eintraege }) {
  const { punkte, abschnitte } = useMemo(() => zeitstrahl(eintraege), [eintraege])
  if (punkte.length < 2) return <p className="leise">Keine kommenden Prüfungen. Wähle unten je LVA den angemeldeten Termin.</p>
  return (
    <div className="zeitstrahl" style={{ '--anzahl': punkte.length }} role="list" aria-label="Prüfungen auf dem Zeitstrahl">
      <span className="zeitstrahl-linie" aria-hidden="true" />
      {abschnitte.map((a, i) => (
        <span key={i} className="zeitstrahl-abstand" style={{ '--pos': a.mitte }} title={`${a.tage} Tage`} aria-hidden="true">
          {abstandText(a.tage)}
        </span>
      ))}
      {punkte.map((p, i) => {
        const lage = [i % 2 ? 'unten' : 'oben', i === 0 && 'erster', i === punkte.length - 1 && 'letzter'].filter(Boolean)
        const heute = p.eintraege.some((e) => e.art === 'heute')
        return (
          <div key={p.tag.toISOString()} className={`zeitstrahl-punkt ${lage.join(' ')}`} style={{ '--pos': p.pos }} role="listitem">
            <span className={`zeitstrahl-marke${heute ? ' heute' : ''}`} style={{ '--lva': p.eintraege.find((e) => e.farbe)?.farbe }} />
            <div className="zeitstrahl-text">
              <span className="zeitstrahl-datum">{heute ? 'Heute' : tagText(p.tag, false)}</span>
              {p.eintraege
                .filter((e) => e.art !== 'heute')
                .map((e) => (
                  <span key={e.key} className={`zeitstrahl-eintrag ${e.art}`} style={{ '--lva': e.farbe }} title={e.titel}>
                    <Icon name={ZEITSTRAHL_ICON[e.art]} />
                    <span className="zeitstrahl-name">{e.art === 'anmeldung' ? `Anm. ${e.name}` : e.name}</span>
                  </span>
                ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// --- Anmeldung je Termin -------------------------------------------------------------------------

function AnmeldeFrist({ t }) {
  if (t.anmeldestatus === 'bald') {
    return (
      <Badge icon="anmeldung" title={t.anmeldung_bis ? `bis ${zeitpunktText(t.anmeldung_bis)}` : undefined}>
        ab {zeitpunktText(t.anmeldung_von)}
      </Badge>
    )
  }
  if (t.anmeldestatus === 'offen') {
    return (
      <Badge ton="primaer" icon="anmeldung">
        offen{t.anmeldung_bis ? ` bis ${zeitpunktText(t.anmeldung_bis)}` : ''}
      </Badge>
    )
  }
  if (t.anmeldestatus === 'vorbei') return <span className="leise klein">vorbei</span>
  return <span className="leise">–</span>
}

// Auswahl „Angemeldet“: automatisch (nach TISS), bei keinem oder genau einem Termin
function AngemeldetAuswahl({ lva, onWaehlen }) {
  const selbst = lva.termine.some((t) => !t.angemeldet_automatisch)
  const wert = selbst ? (lva.angemeldet_id ? String(lva.angemeldet_id) : 'keiner') : 'auto'
  const automatisch = lva.termine.find((t) => t.id === lva.angemeldet_id)
  const optionen = [
    { wert: 'auto', name: automatisch ? `automatisch: ${terminZeit(automatisch)}` : 'noch nicht gewählt' },
    { wert: 'keiner', name: 'bei keinem Termin' },
    ...lva.termine.map((t) => ({ wert: String(t.id), name: optionText(t) })),
  ]
  return (
    <Feld label="Angemeldet bei" className="pruefung-auswahl">
      <Auswahl
        optionen={optionen}
        value={wert}
        disabled={!lva.termine.length}
        onChange={(e) => {
          const v = e.target.value
          onWaehlen(lva, v === 'auto' || v === 'keiner' ? null : Number(v), v === 'auto')
        }}
      />
    </Feld>
  )
}

function LvaPruefungen({ lva, jetzt, onWaehlen, onLernwochen, onBearbeiten, onLoeschen, onNeu }) {
  const name = lvaName(lva)
  return (
    <Karte
      className="pruefung-lva"
      style={{ '--lva': lva.farbe }}
      titel={<span title={lva.titel}>{name}</span>}
      aktionen={<IconButton icon="neu" label={`Termin für ${name} eintragen`} onClick={() => onNeu(lva.lva_id)} />}
    >
      <div className="stapel">
        <div className="pruefung-kopf">
          <AngemeldetAuswahl lva={lva} onWaehlen={onWaehlen} />
          <Feld label="Lernen ab" hilfe={`Wochen vor der Prüfung (leer = ${lva.lernwochen_standard})`} className="pruefung-lernwochen">
            <ZahlEingabe
              wert={lva.lernwochen}
              max="20"
              placeholder={String(lva.lernwochen_standard)}
              aria-label="Lernblöcke so viele Wochen vor der Prüfung"
              onSpeichern={(n) => onLernwochen(lva, n)}
            />
          </Feld>
        </div>
        {lva.feed_pruefungen.length > 0 && (
          <p className="klein">
            <Icon name="pruefung" /> Im TISS-Kalender (angemeldet): {lva.feed_pruefungen.map(zeitpunktText).join(', ')}
          </p>
        )}
        {lva.termine.length ? (
          <Tabelle className="pruefung-tabelle">
            <thead>
              <tr>
                <th>Termin</th>
                <th>Anmeldung</th>
                <th>Quelle</th>
                <th>
                  <span className="nur-screenreader">Aktionen</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {lva.termine.map((t) => (
                <tr key={t.id} className={new Date(t.start) < jetzt ? 'gedimmt' : undefined}>
                  <td>
                    <div className="pruefung-termin">
                      <span className="pruefung-zeit">
                        {terminZeit(t)}
                        {t.angemeldet && (
                          <Badge ton="bestaetigen" icon="ok" title={t.angemeldet_automatisch ? 'laut TISS' : 'selbst gewählt'}>
                            angemeldet
                          </Badge>
                        )}
                      </span>
                      <span className="leise klein">{[t.titel, t.ort].filter(Boolean).join(' · ')}</span>
                    </div>
                  </td>
                  <td>
                    <AnmeldeFrist t={t} />
                  </td>
                  <td>
                    <Badge ton="umriss" title={t.bearbeitet ? 'Zeiten selbst geändert – der Import überschreibt sie nicht' : undefined}>
                      {QUELLEN[t.quelle]}
                      {t.bearbeitet ? ' (geändert)' : ''}
                    </Badge>
                  </td>
                  <td className="pruefung-aktionen">
                    <IconButton icon="bearbeiten" klein label="Bearbeiten" onClick={() => onBearbeiten(t)} />
                    <IconButton icon="loeschen" klein ton="verwerfen" label="Entfernen" onClick={() => onLoeschen(t)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </Tabelle>
        ) : (
          <p className="leise">
            Noch keine Termine bekannt – sie kommen mit dem nächsten Lauf der Erweiterung aus TISS und TUWEL, oder du trägst
            selbst einen ein.
          </p>
        )}
      </div>
    </Karte>
  )
}

// --- Eintragen und Bearbeiten ------------------------------------------------------------------------

const lokal = (iso) => (iso ? iso.slice(0, 16) : '') // „2027-01-23T09:00“ für datetime-local
const uhrzeit = (iso) => (iso ? iso.slice(11, 16) : '')

function formular(termin, lvaId) {
  if (!termin) {
    return { lva_id: lvaId ?? '', titel: 'Prüfung', datum: '', beginn: '', ende: '', ort: '', anmeldung_von: '', anmeldung_bis: '', angemeldet: true }
  }
  return {
    lva_id: termin.lva_id,
    titel: termin.titel,
    datum: termin.start.slice(0, 10),
    beginn: termin.ende ? uhrzeit(termin.start) : '',
    ende: termin.ende ? uhrzeit(termin.ende) : '',
    ort: termin.ort || '',
    anmeldung_von: lokal(termin.anmeldung_von),
    anmeldung_bis: lokal(termin.anmeldung_bis),
    angemeldet: termin.angemeldet,
  }
}

/** Formularwerte → API: ohne Uhrzeit ganztägig (9 Uhr, ohne Ende), ohne Ende zwei Stunden. */
function nutzdaten(f) {
  const start = `${f.datum}T${f.beginn || '09:00'}:00`
  let ende = null
  if (f.beginn) {
    if (f.ende) ende = `${f.datum}T${f.ende}:00`
    else {
      const [h, m] = f.beginn.split(':').map(Number)
      ende = `${f.datum}T${z2(Math.min(h + 2, 23))}:${z2(m)}:00`
    }
  }
  return {
    titel: f.titel.trim() || 'Prüfung',
    start,
    ende,
    ort: f.ort.trim() || null,
    anmeldung_von: f.anmeldung_von ? `${f.anmeldung_von}:00` : null,
    anmeldung_bis: f.anmeldung_bis ? `${f.anmeldung_bis}:00` : null,
    angemeldet: f.angemeldet,
  }
}

function PruefungDialog({ termin, lvaId, lvas, onSchliessen, onGespeichert }) {
  const [f, setF] = useState(() => formular(termin, lvaId))
  const [fehler, setFehler] = useState(null)
  const [speichert, setSpeichert] = useState(false)
  const setze = (feld) => (e) => setF({ ...f, [feld]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const importiert = termin && termin.quelle !== 'manuell'

  async function speichern() {
    if (!f.lva_id || !f.datum) {
      setFehler('LVA und Datum sind nötig.')
      return
    }
    setSpeichert(true)
    setFehler(null)
    try {
      if (termin) await api.pruefungAendern(termin.id, nutzdaten(f))
      else await api.pruefungAnlegen({ lva_id: Number(f.lva_id), ...nutzdaten(f) })
      onGespeichert()
    } catch (e) {
      setFehler(e.message)
      setSpeichert(false)
    }
  }

  return (
    <Dialog
      titel={termin ? 'Prüfungstermin bearbeiten' : 'Prüfung eintragen'}
      icon="pruefung"
      onSchliessen={onSchliessen}
      aktionen={
        <>
          <Button onClick={onSchliessen}>Abbrechen</Button>
          <Button variante="bestaetigen" icon="ok" onClick={speichern} disabled={speichert}>
            Speichern
          </Button>
        </>
      }
    >
      <div className="stapel pruefung-formular">
        {!termin && (
          <Feld label="LVA">
            <Auswahl value={f.lva_id} onChange={setze('lva_id')}>
              <option value="">bitte wählen</option>
              {lvas.map((l) => (
                <option key={l.lva_id} value={l.lva_id}>
                  {lvaName(l)}
                </option>
              ))}
            </Auswahl>
          </Feld>
        )}
        <Feld label="Bezeichnung">
          <Eingabe value={f.titel} onChange={setze('titel')} placeholder="z. B. Zwischentest, mündliche Prüfung" />
        </Feld>
        <div className="pruefung-felder">
          <Feld label="Datum">
            <Eingabe type="date" value={f.datum} onChange={setze('datum')} />
          </Feld>
          <Feld label="Beginn" hilfe="leer = ganztägig">
            <Eingabe type="time" value={f.beginn} onChange={setze('beginn')} />
          </Feld>
          <Feld label="Ende" hilfe="leer = 2 Stunden">
            <Eingabe type="time" value={f.ende} onChange={setze('ende')} disabled={!f.beginn} />
          </Feld>
        </div>
        <Feld label="Ort">
          <Eingabe value={f.ort} onChange={setze('ort')} />
        </Feld>
        <div className="pruefung-felder">
          <Feld label="Anmeldung ab" hilfe="erscheint im Kalender">
            <Eingabe type="datetime-local" value={f.anmeldung_von} onChange={setze('anmeldung_von')} />
          </Feld>
          <Feld label="Anmeldung bis">
            <Eingabe type="datetime-local" value={f.anmeldung_bis} onChange={setze('anmeldung_bis')} />
          </Feld>
        </div>
        <Kontrolle label="Ich bin angemeldet bzw. trete an (zählt für den Lernplan)" checked={f.angemeldet} onChange={setze('angemeldet')} />
        {importiert && <p className="leise klein">Geänderte Zeiten überschreibt der nächste Import aus {QUELLEN[termin.quelle]} nicht.</p>}
        {fehler && <p className="feld-fehler">{fehler}</p>}
      </div>
    </Dialog>
  )
}

// --- Seite ---------------------------------------------------------------------------------------------

function syncHinweis(sync) {
  const teile = []
  const fehler = []
  for (const [quelle, s] of Object.entries(sync)) {
    if (!s) continue
    teile.push(`${QUELLEN[quelle]} ${new Date(s.zeit).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' })}: ${s.termine} Termine`)
    fehler.push(...s.fehler.map((f) => `${QUELLEN[quelle]}: ${f}`))
  }
  if (!teile.length) {
    return {
      ton: 'info',
      titel: 'Noch kein Import – die Browser-Erweiterung holt die Termine beim nächsten Lauf (oder: Prüfungsliste in TISS öffnen).',
    }
  }
  return { ton: fehler.length ? 'warnung' : 'info', titel: `Zuletzt geholt: ${teile.join(' · ')}`, fehler }
}

export default function Pruefungen({ onGeaendert }) {
  const [daten, setDaten] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [dialog, setDialog] = useState(null) // { termin } oder { lvaId }
  const [loeschen, setLoeschen] = useState(null)
  const [alle, setAlle] = useState(false)

  const laden = useCallback(() => {
    api
      .pruefungen()
      .then((d) => {
        setDaten(d)
        setFehler(null)
      })
      .catch((e) => setFehler(e.message))
  }, [])
  useEffect(laden, [laden])

  const geaendert = () => {
    laden()
    onGeaendert?.() // Lernbedarf der LVAs hängt an den Prüfungen
  }
  const ausfuehren = (aufruf) => aufruf.then(geaendert).catch((e) => setFehler(e.message))

  const heute = useMemo(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), d.getDate())
  }, [])
  const eintraege = useMemo(() => (daten ? zeitstrahlEintraege(daten.lvas, alle, heute) : []), [daten, alle, heute])

  let hinweis = null
  if (fehler) hinweis = <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} />
  else if (daten) {
    const h = syncHinweis(daten.sync)
    hinweis = (
      <Hinweis ton={h.ton} titel={h.titel}>
        {h.fehler?.length > 0 && (
          <ul>
            {h.fehler.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        )}
      </Hinweis>
    )
  }

  return (
    <div className="seite pruefungen-seite">
      <SeitenKopf
        titel="Prüfungen"
        aktion={
          <Button variante="primaer" icon="neu" onClick={() => setDialog({})} disabled={!daten?.lvas.length}>
            Prüfung eintragen
          </Button>
        }
      >
        Termine kommen automatisch aus TISS und TUWEL; wähle je LVA, wo du angemeldet bist – das bestimmt den Lernplan.
      </SeitenKopf>
      {hinweis}

      {daten && daten.lvas.length === 0 && (
        <LeererZustand icon="pruefung" titel="Keine besuchten LVAs im laufenden Semester">
          Sobald der TISS-Import LVAs kennt, erscheinen hier ihre Prüfungstermine.
        </LeererZustand>
      )}

      {daten && daten.lvas.length > 0 && (
        <>
          <Karte
            titel="Zeitstrahl"
            icon="pruefung"
            aktionen={<Kontrolle label="auch nicht angemeldete Termine" checked={alle} onChange={(e) => setAlle(e.target.checked)} />}
          >
            <Zeitstrahl eintraege={eintraege} />
          </Karte>
          <div className="pruefungen-raster">
            {daten.lvas.map((lva) => (
              <LvaPruefungen
                key={lva.lva_id}
                lva={lva}
                jetzt={heute}
                onWaehlen={(l, id, automatisch) => ausfuehren(api.pruefungAngemeldet(l.lva_id, id, automatisch))}
                onLernwochen={(l, lernwochen) => ausfuehren(api.lvaAendern(l.lva_id, { lernwochen }))}
                onBearbeiten={(termin) => setDialog({ termin })}
                onLoeschen={setLoeschen}
                onNeu={(lvaId) => setDialog({ lvaId })}
              />
            ))}
          </div>
        </>
      )}

      {dialog && (
        <PruefungDialog
          termin={dialog.termin}
          lvaId={dialog.lvaId}
          lvas={daten.lvas}
          onSchliessen={() => setDialog(null)}
          onGespeichert={() => {
            setDialog(null)
            geaendert()
          }}
        />
      )}
      {loeschen && (
        <Rueckfrage
          titel="Termin entfernen?"
          text={
            loeschen.quelle === 'manuell'
              ? `„${loeschen.titel}“ am ${tagText(loeschen.start)} wird gelöscht.`
              : `„${loeschen.titel}“ am ${tagText(loeschen.start)} wird ausgeblendet; der nächste Import aus ${QUELLEN[loeschen.quelle]} holt ihn nicht zurück.`
          }
          bestaetigen="Entfernen"
          onJa={() => {
            const t = loeschen
            setLoeschen(null)
            ausfuehren(api.pruefungLoeschen(t.id))
          }}
          onNein={() => setLoeschen(null)}
        />
      )}
    </div>
  )
}
