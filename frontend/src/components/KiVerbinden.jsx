import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Auswahl, Badge, Button, Eingabe, Feld, Hinweis, Karte, Kontrolle, SeitenKopf, Tabelle } from '../ui.jsx'
import './KiVerbinden.css'

const WERKZEUGE = [
  ['suche_unterlagen', 'Semantische Suche in Skripten, Folien, Transkripten und MB Cloud – mit Fundstelle'],
  ['lies_abschnitt', 'Vollständiger Text eines Abschnitts samt Nachbarn'],
  ['liste_lvas, termine, wochenplan, pruefungen', 'LVAs, Termine, Wochenplan mit Stunden, Prüfungen'],
  ['wissensstand, faellige_wiederholungen', 'Themen mit Stufe und Wiederholungen'],
  ['altpruefungen', 'Altprüfungen aus der MB Cloud (inoffiziell) mit Lösung und Bearbeitungsstand'],
  ['lernereignis_eintragen, wissensstand_setzen', 'Quiz- und Prüfungsergebnisse speichern, Stufe setzen'],
  ['notiz_speichern', 'Notiz zu LVA oder Thema'],
  ['lernblock_vorschlagen, wochenplan_vorschlagen', 'Lernblöcke bzw. die ganze Woche vorschlagen – du bestätigst im Kalender'],
  ['rueckblick, neue_unterlagen', 'Rückblick auf die letzte Woche, neuer Stoff'],
  ['lies_dokument, aufzeichnung_zu_termin', 'Ganze Unterlage (z. B. Altprüfung) bzw. Aufzeichnung samt Transkript zu einem Termin'],
  ['altpruefung_bearbeitet', 'Altprüfung mit Zeit und Punkten als erledigt markieren'],
]

const VORLAGEN = [
  ['thema_lernen', 'LVA, Thema', 'Erklärung in kleinen Schritten mit Verständnisfragen, 3 Kontrollfragen, Wissensstand aktualisieren'],
  ['wochenstart', '–', 'Rückblick, neuer Stoff, Prüfungen, fällige Wiederholungen; daraus 3 Prioritäten und Lernblock-Vorschläge'],
  ['wiederholung', 'LVA (optional)', 'Quiz zu allen fälligen Themen, Abstände nach Spaced Repetition'],
  ['pruefung_simulieren', 'LVA, Minuten (optional, 90)', 'Noch nicht gerechnete Altprüfung mit Zeitlimit, Bewertung, Fehleranalyse'],
  ['vorlesung_nachholen', 'Termin, z. B. „Mechanik 14.10.“', 'Zusammenfassung der Aufzeichnung mit Skript-Verweisen, 3 Kontrollfragen'],
  ['plan_anpassen', 'Grund, Woche (optional)', 'Neuer Wochenplan als Vorschläge nach den Planungsregeln'],
]

const BEISPIELE = [
  'Erkläre mir das Schnittprinzip aus Mechanik 1 mit Fundstellen.',
  'Stell mir 5 Quizfragen zu Reibung und trag das Ergebnis ein.',
  'Welche Themen sind diese Woche fällig, und wann ist die nächste Prüfung?',
  'Plane mir für morgen Nachmittag einen Lernblock für die neueste Altprüfung in Mathe.',
]

// Werkzeugnamen auf schmalen Bildschirmen nur nach Unterstrichen umbrechen
const umbrechbar = (name) =>
  name.split('_').flatMap((teil, i, alle) => (i < alle.length - 1 ? [`${teil}_`, <wbr key={i} />] : [teil]))

export default function KiVerbinden() {
  const [status, setStatus] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [ergebnis, setErgebnis] = useState(null)
  const [frage, setFrage] = useState('')
  const [treffer, setTreffer] = useState(null)

  const laden = useCallback(() => {
    api.kiStatus().then(setStatus).catch((e) => setFehler(e.message))
  }, [])
  useEffect(laden, [laden])
  useEffect(() => {
    if (!status?.verarbeitung.laeuft_text && !status?.verarbeitung.laeuft_video) return
    const zeitgeber = setInterval(laden, 5000)
    return () => clearInterval(zeitgeber)
  }, [status, laden])

  const ausfuehren = (aufruf) =>
    aufruf
      .then((antwort) => {
        setErgebnis(antwort)
        laden()
      })
      .catch((e) => setFehler(e.message))

  async function suchen(e) {
    e.preventDefault()
    try {
      setTreffer(await api.kiSuche(frage))
    } catch (f) {
      setFehler(f.message)
    }
  }

  if (!status) return <p className="seite leise">Lade …</p>
  const { einrichtung: e, verarbeitung: v } = status
  const fertig = e.eingetragen && e.aktuell // dann ist „Suchen“ der Hauptbutton

  // Höchstens ein Hinweis: Fehler vor Fehler der Einrichtung vor Sicherung
  let hinweis = null
  if (fehler) hinweis = <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} />
  else if (e.fehler) hinweis = <Hinweis ton="fehler" titel={e.fehler} />
  else if (ergebnis?.sicherung)
    hinweis = (
      <Hinweis ton="erfolg" titel="Konfiguration geändert – Claude Desktop jetzt ganz beenden und neu starten." onSchliessen={() => setErgebnis(null)}>
        <p className="ki-umbruch">Sicherung der bisherigen Datei: {ergebnis.sicherung}</p>
      </Hinweis>
    )

  return (
    <div className="seite ki-seite">
      <SeitenKopf titel="KI verbinden">
        Claude Desktop greift über einen lokalen MCP-Server auf deine Unterlagen, Termine und deinen Wissensstand zu.
      </SeitenKopf>
      {hinweis}

      <Karte titel="1. Unterlagen für die Suche aufbereiten">
        <div className="stapel">
          <div className="reihe ki-eng">
            <span>
              {v.abschnitte} Abschnitte aus {v.dokumente_fertig} Unterlagen
              {v.dokumente_offen > 0 && <> · {v.dokumente_offen} warten</>} · Videos: {v.videos_fertig} transkribiert,{' '}
              {v.videos_offen} offen
            </span>
            {v.dokumente_fehler > 0 && (
              <Badge ton="verwerfen" icon="warnung">
                {v.dokumente_fehler} nicht lesbar
              </Badge>
            )}
            {v.videos_fehler > 0 && (
              <Badge ton="verwerfen" icon="warnung">
                {v.videos_fehler} Videos mit Fehler
              </Badge>
            )}
            {!v.vektorsuche && (
              <Badge ton="verwerfen" icon="warnung" title="sqlite-vec fehlt">
                nur Volltextsuche
              </Badge>
            )}
          </div>
          <div>
            <Kontrolle
              checked={v.verarbeitung_aktiv}
              onChange={(x) => ausfuehren(api.kiVerarbeitung({ text: x.target.checked }))}
              label={
                <>
                  Skripte, Folien und MB-Cloud-Dateien für die Suche aufbereiten{' '}
                  {v.laeuft_text && (
                    <Badge ton="primaer" icon="aktualisieren">
                      läuft
                    </Badge>
                  )}
                </>
              }
            />
            <p className="leise klein ki-einzug">Lädt beim ersten Mal das Sprachmodell (etwa 220 MB), danach offline alle 15 min.</p>
          </div>
          <div>
            <Kontrolle
              checked={v.transkription_aktiv}
              onChange={(x) => ausfuehren(api.kiVerarbeitung({ video: x.target.checked }))}
              label={
                <>
                  Vorlesungsaufzeichnungen transkribieren (faster-whisper){' '}
                  {v.laeuft_video && (
                    <Badge ton="primaer" icon="aktualisieren">
                      läuft
                    </Badge>
                  )}
                </>
              }
            />
            <p className="leise klein ki-einzug">Lädt einmal etwa 460 MB; rechenintensiv, ein Video nach dem anderen im Hintergrund.</p>
          </div>
        </div>
      </Karte>

      <Karte
        titel="2. In Claude Desktop eintragen"
        aktionen={
          e.eingetragen ? (
            e.aktuell ? (
              <Badge ton="bestaetigen" icon="erledigt">
                eingetragen
              </Badge>
            ) : (
              <Badge ton="verwerfen" icon="warnung">
                veraltet – neu eintragen
              </Badge>
            )
          ) : (
            <Badge>noch nicht eingetragen</Badge>
          )
        }
      >
        <div className="stapel">
          <div className="ki-angabe">
            <span className="feld-beschriftung">Konfigurationsdatei</span>
            <code className="code-block ki-pfad">{e.config_pfad}</code>
            {!e.config_vorhanden && <span className="leise klein">Wird neu angelegt – ist Claude Desktop installiert?</span>}
          </div>
          {!e.python_vorhanden && (
            <div className="ki-angabe">
              <Badge ton="verwerfen" icon="warnung">
                Python der venv fehlt
              </Badge>
              <code className="code-block ki-pfad">{e.python}</code>
            </div>
          )}
          <div className="knopf-gruppe">
            <Button variante={fertig ? 'umriss' : 'primaer'} onClick={() => ausfuehren(api.kiEinrichten())}>
              {e.eingetragen ? 'Neu eintragen' : 'In Claude Desktop eintragen'}
            </Button>
            {e.eingetragen && (
              <Button variante="verwerfen" onClick={() => ausfuehren(api.kiAustragen())}>
                Austragen
              </Button>
            )}
          </div>
        </div>
      </Karte>

      <div className="stapel">
        <Karte aufklappbar titel="Danach: Claude Desktop neu starten und prüfen">
          <ol className="ki-liste">
            <li>
              Claude Desktop ganz beenden: Rechtsklick auf das Claude-Symbol im Infobereich (unten rechts), dann „Beenden“. Nur das
              Fenster zu schließen genügt nicht.
            </li>
            <li>Claude Desktop neu starten.</li>
            <li>
              Prüfen, ob der Server läuft: in Claude Desktop Einstellungen (Strg + ,), dann „Entwickler“ (Developer). Dort steht
              „studien-hub“ mit dem Status „running“. Bei „failed“ zeigt „Logs öffnen“ den Grund.
            </li>
            <li>
              In einem neuen Chat: Das Menü „Suche und Tools“ im Eingabefeld (Schieberegler-Symbol, in älteren Versionen ein Hammer)
              listet „studien-hub“ mit 19 Werkzeugen. Schreib zum Test „Welche LVAs besuche ich?“.
            </li>
            <li>Beim ersten Aufruf eines Werkzeugs fragt Claude nach der Erlaubnis – „Immer erlauben“ für die lesenden Werkzeuge ist bequem.</li>
          </ol>
        </Karte>
        <Karte aufklappbar titel="Eintrag in der Konfiguration">
          <pre className="code-block ki-block">{JSON.stringify({ mcpServers: { 'studien-hub': e.eintrag } }, null, 2)}</pre>
        </Karte>
      </div>

      <Karte titel="3. Ausprobieren">
        <div className="stapel">
          <form className="formular-zeile" onSubmit={suchen}>
            <Feld label="Frage an die Unterlagen" className="ki-frage">
              <Eingabe type="search" placeholder="z. B. „Was ist ein Freikörperbild?“" value={frage} onChange={(x) => setFrage(x.target.value)} />
            </Feld>
            <Button type="submit" variante={fertig ? 'primaer' : 'umriss'} icon="suche" disabled={!frage.trim()}>
              Suchen
            </Button>
          </form>
          {treffer && treffer.length === 0 && <p className="leise">Keine Treffer – sind die Unterlagen schon aufbereitet?</p>}
          {treffer && treffer.length > 0 && (
            <ul className="ki-treffer">
              {treffer.map((t) => (
                <li key={t.abschnitt_id}>
                  <div className="reihe ki-eng">
                    {!t.offiziell && (
                      <Badge ton="umriss" icon="mbcloud" title="MB Cloud: inoffizielle Unterlage">
                        inoffiziell {t.jahr || ''}
                      </Badge>
                    )}
                    <strong>{t.lva}</strong>
                    <a href={api.dokumentUrl(t.dokument_id)} target="_blank" rel="noreferrer" className="ki-umbruch">
                      {t.dokument}
                    </a>
                    <span className="leise klein">
                      {t.fundstelle}
                      {t.kapitel && ` · ${t.kapitel}`}
                    </span>
                  </div>
                  <p className="leise klein ki-umbruch">{t.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Karte>

      <div className="stapel">
        <Karte aufklappbar icon="ki" titel="Was Claude damit kann">
          <p className="leise">
            Der Server läuft auf diesem Rechner, liest keine Dateien außerhalb der Datenbank und greift nicht ins Netz. An Claude gehen
            nur die Abschnitte, die zur Frage passen.
          </p>
          <Tabelle>
            <thead>
              <tr>
                <th>Werkzeug</th>
                <th>Zweck</th>
              </tr>
            </thead>
            <tbody>
              {WERKZEUGE.map(([name, text]) => (
                <tr key={name}>
                  <td>
                    <code>{umbrechbar(name)}</code>
                  </td>
                  <td>{text}</td>
                </tr>
              ))}
            </tbody>
          </Tabelle>
        </Karte>

        <Karte aufklappbar titel="Vorlagen und Beispiele">
          <div className="stapel">
            <p className="leise">
              Im Chat in eigenen Worten nennen, z. B. „Starte thema_lernen für Mechanik 1, Thema Reibung“ oder „Mach den Wochenstart“ –
              Claude holt sich den Ablauf über das Werkzeug <code>vorlage</code>. Manche Versionen zeigen die Vorlagen auch unter „+“ /
              „Slash-Befehle“ bzw. beim Tippen von „/“. Die Server-Regeln (Quellen nennen, offiziell vor MB Cloud, Wissensstand abfragen,
              Lernereignisse eintragen, bei benoteten Abgaben nur Hinweise) gelten immer.
            </p>
            <Tabelle>
              <thead>
                <tr>
                  <th>Vorlage</th>
                  <th>Felder</th>
                  <th>Was passiert</th>
                </tr>
              </thead>
              <tbody>
                {VORLAGEN.map(([name, felder, text]) => (
                  <tr key={name}>
                    <td>
                      <code>{umbrechbar(name)}</code>
                    </td>
                    <td>{felder}</td>
                    <td>{text}</td>
                  </tr>
                ))}
              </tbody>
            </Tabelle>
            <VorlageKopieren setFehler={setFehler} />
            <div>
              <h3>Beispiele für Claude Desktop</h3>
              <ul className="ki-liste">
                {BEISPIELE.map((b) => (
                  <li key={b}>„{b}“</li>
                ))}
              </ul>
            </div>
          </div>
        </Karte>
      </div>
    </div>
  )
}

const FELDNAMEN = { lva: 'LVA', thema: 'Thema', termin: 'Termin (z. B. „Mechanik 14.10.“)', grund: 'Grund', woche: 'Woche (Datum)', minuten: 'Minuten' }

// Vorlagentext zum Kopieren – falls Claude Desktop die Vorlagen nicht im Menü anzeigt
function VorlageKopieren({ setFehler }) {
  const [vorlagen, setVorlagen] = useState([])
  const [name, setName] = useState('thema_lernen')
  const [werte, setWerte] = useState({})
  const [text, setText] = useState('')
  const [kopiert, setKopiert] = useState(false)

  useEffect(() => {
    api.kiVorlagen().then(setVorlagen).catch((e) => setFehler(e.message))
  }, [setFehler])

  const vorlage = vorlagen.find((v) => v.name === name)
  async function erzeugen() {
    try {
      const gefuellt = Object.fromEntries(Object.entries(werte).filter(([, w]) => w))
      setText((await api.kiVorlage(name, gefuellt)).text)
      setKopiert(false)
    } catch (e) {
      setFehler(e.message)
    }
  }
  async function kopieren() {
    try {
      await navigator.clipboard.writeText(text)
      setKopiert(true)
    } catch {
      setFehler('Kopieren nicht erlaubt – Text markieren und mit Strg + C kopieren.')
    }
  }

  if (!vorlage) return null
  return (
    <div className="stapel">
      <h3>Vorlagentext erzeugen und kopieren</h3>
      <div className="formular-zeile">
        <Feld label="Vorlage">
          <Auswahl breite="mittel" value={name} onChange={(e) => { setName(e.target.value); setText('') }}>
            {vorlagen.map((v) => (
              <option key={v.name} value={v.name}>{v.titel}</option>
            ))}
          </Auswahl>
        </Feld>
        {[...vorlage.pflicht, ...vorlage.optional].map((f) => (
          <Feld key={f} label={FELDNAMEN[f] + (vorlage.optional.includes(f) ? ' (optional)' : '')}>
            <Eingabe breite="mittel" value={werte[f] || ''} onChange={(e) => setWerte({ ...werte, [f]: e.target.value })} />
          </Feld>
        ))}
        <Button onClick={erzeugen}>Erzeugen</Button>
      </div>
      {text && (
        <>
          <Eingabe mehrzeilig className="ki-code" readOnly value={text} rows={12} aria-label="Vorlagentext" />
          <div className="knopf-gruppe">
            <Button variante={kopiert ? 'bestaetigen' : 'umriss'} icon={kopiert ? 'erledigt' : undefined} onClick={kopieren}>
              {kopiert ? 'Kopiert – jetzt in Claude Desktop einfügen' : 'In die Zwischenablage kopieren'}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
