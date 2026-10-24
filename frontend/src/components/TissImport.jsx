import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Button, Eingabe, Feld, Hinweis, Icon, Karte, SeitenKopf, Tabelle } from '../ui.jsx'
import './TissImport.css'

const tag = (d) => new Date(d).toLocaleDateString('de-AT')

// Ergebnis des letzten Imports: eine Zeile mit den Zahlen, Rest aufklappbar
function Ergebnis({ ergebnis }) {
  const details = [
    ergebnis.freie_zeitraeume > 0 && `${ergebnis.freie_zeitraeume} vorlesungsfreie Zeiten übernommen`,
    ergebnis.neue_lvas.length > 0 && `Neue LVAs: ${ergebnis.neue_lvas.join(', ')}`,
    ergebnis.entfernte_lvas?.length > 0 && `Entfernt (keine Termine mehr im Feed): ${ergebnis.entfernte_lvas.join(', ')}`,
    ergebnis.neu_geplante_wochen.length > 0 &&
      `Arbeitszeit neu vorgeschlagen für die Wochen ab ${ergebnis.neu_geplante_wochen.map(tag).join(', ')}`,
  ].filter(Boolean)
  return (
    <Hinweis
      ton="erfolg"
      titel={`Import abgeschlossen: ${ergebnis.neu} neu, ${ergebnis.geaendert} geändert, ${ergebnis.geloescht} gelöscht, ${ergebnis.unveraendert} unverändert`}
    >
      {details.length > 0 && (
        <ul>
          {details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
    </Hinweis>
  )
}

// Vorlesungsfreie Zeiten aus TISS: sperren Arbeit und Lernen wie Feiertage
function FreieZeiten({ neuLaden }) {
  const [zeiten, setZeiten] = useState([])
  useEffect(() => {
    api.freieZeitraeume().then(setZeiten).catch(() => setZeiten([]))
  }, [neuLaden])
  if (zeiten.length === 0) return null
  return (
    <Karte aufklappbar icon="frei" titel={`Vorlesungsfreie Zeiten aus TISS (${zeiten.length})`}>
      <p className="leise">An diesen Tagen schlägt der Hub weder Arbeit noch Lernblöcke vor.</p>
      <Tabelle>
        <thead>
          <tr>
            <th>Bezeichnung</th>
            <th className="zahl">Von</th>
            <th className="zahl">Bis</th>
          </tr>
        </thead>
        <tbody>
          {zeiten.map((z) => (
            <tr key={z.id}>
              <td>
                <span className="mit-icon">
                  <Icon name="frei" />
                  {z.bezeichnung}
                </span>
              </td>
              <td className="zahl">{tag(z.von)}</td>
              <td className="zahl">{z.bis !== z.von ? tag(z.bis) : '–'}</td>
            </tr>
          ))}
        </tbody>
      </Tabelle>
    </Karte>
  )
}

function Bereinigung({ bericht }) {
  if (!bericht) return null
  const getrennt = bericht.getrennt || []
  return (
    <Karte aufklappbar titel={`Datenbank am ${new Date(bericht.zeit).toLocaleString('de-AT')} aufgeräumt`}>
      <p>
        {bericht.freie_zeitraeume.length} Ferien-/Feiertagseinträge zu freien Zeiten, {getrennt.length} LVAs in VO/UE getrennt.
      </p>
      {(getrennt.length > 0 || bericht.hinweise.length > 0) && (
        <ul className="tiss-liste">
          {getrennt.map((z) => (
            <li key={z}>{z}</li>
          ))}
          {bericht.hinweise.map((h) => (
            <li key={h}>{h}</li>
          ))}
        </ul>
      )}
      {bericht.sicherung && <p className="leise klein tiss-umbruch">Sicherungskopie davor: {bericht.sicherung}</p>}
    </Karte>
  )
}

export default function TissImport({ onImportiert }) {
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState({})
  const [ergebnis, setErgebnis] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [laeuft, setLaeuft] = useState(false)

  const ladeStatus = () =>
    api
      .tissEinstellungen()
      .then((s) => {
        setStatus(s)
        setUrl(s.ical_url || '')
      })
      .catch((e) => setFehler(e.message))

  useEffect(() => {
    ladeStatus()
  }, [])

  async function ausfuehren(aufruf) {
    setLaeuft(true)
    setFehler(null)
    setErgebnis(null)
    try {
      setErgebnis(await aufruf())
      onImportiert()
    } catch (e) {
      setFehler(e.message)
    } finally {
      setLaeuft(false)
      ladeStatus()
    }
  }

  const speichernUndImportieren = () =>
    ausfuehren(async () => {
      await api.tissEinstellungenSpeichern({ ical_url: url })
      return api.tissImport()
    })

  // Höchstens ein Hinweis: aktueller Fehler vor Ergebnis vor dem Fehler des automatischen Abgleichs
  let hinweis = null
  if (fehler) hinweis = <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} />
  else if (ergebnis) hinweis = <Ergebnis ergebnis={ergebnis} />
  else if (status.letzter_fehler)
    hinweis = (
      <Hinweis ton="warnung" titel="Der letzte automatische Abgleich ist fehlgeschlagen.">
        <p className="tiss-umbruch">{status.letzter_fehler}</p>
      </Hinweis>
    )

  return (
    <div className="seite tiss-import">
      <SeitenKopf titel="TISS-Import">
        Der Hub übernimmt deinen TISS-Kalender und gleicht ihn jeden Morgen automatisch ab.
      </SeitenKopf>
      {hinweis}

      <Karte>
        <div className="stapel">
          <Feld label="iCal-Link" hilfe="In TISS unter „Favoriten / Kalender / iCal-Export“ den persönlichen Link kopieren.">
            <Eingabe
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://tiss.tuwien.ac.at/events/rest/calendar/personal?..."
            />
          </Feld>
          <div className="reihe">
            <Button variante="primaer" icon="aktualisieren" onClick={speichernUndImportieren} disabled={!url || laeuft}>
              {laeuft ? 'Importiere …' : 'Jetzt importieren'}
            </Button>
            <label className={`knopf knopf-umriss klein${laeuft ? ' gesperrt' : ''}`} aria-disabled={laeuft}>
              <Icon name="hochladen" />
              Oder .ics-Datei hochladen
              <input
                type="file"
                className="nur-screenreader"
                accept=".ics,text/calendar"
                disabled={laeuft}
                onChange={(e) => e.target.files[0] && ausfuehren(() => api.tissImportDatei(e.target.files[0]))}
              />
            </label>
          </div>
          <p className="leise klein tiss-zeile">
            Letzter Import: {status.letzter_import ? new Date(status.letzter_import).toLocaleString('de-AT') : 'noch nie'}
          </p>
        </div>
      </Karte>

      <div className="stapel">
        <FreieZeiten neuLaden={status.letzter_import} />
        <Bereinigung bericht={status.bereinigung} />
      </div>
    </div>
  )
}
