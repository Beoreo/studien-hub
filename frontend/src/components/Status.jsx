import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Badge, Button, Hinweis, Karte, Kontrolle, Rueckfrage, SeitenKopf, Tabelle } from '../ui.jsx'

const zeit = (iso) =>
  iso ? new Date(iso).toLocaleString('de-AT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '–'
const mb = (bytes) => `${(bytes / 1e6).toLocaleString('de-AT', { maximumFractionDigits: 1 })} MB`

// Betrieb auf einen Blick: letzter Sync je Quelle, laufende Jobs, Fehler, Sicherungen, Version, Autostart
export default function Status({ onEinrichtung }) {
  const [status, setStatus] = useState(null)
  const [hinweis, setHinweis] = useState(null)
  const [rueckfrage, setRueckfrage] = useState(null)

  const laden = useCallback(() => api.systemStatus().then(setStatus).catch((e) => setHinweis({ ton: 'fehler', titel: e.message })), [])

  useEffect(() => {
    laden()
    const zeitgeber = setInterval(laden, 10000)
    return () => clearInterval(zeitgeber)
  }, [laden])

  const ausfuehren = (aufruf, erfolg) =>
    aufruf
      .then((ergebnis) => {
        if (erfolg) setHinweis({ ton: 'erfolg', titel: erfolg(ergebnis) })
        laden()
      })
      .catch((e) => setHinweis({ ton: 'fehler', titel: e.message }))

  if (!status) {
    return (
      <div className="seite">
        <SeitenKopf titel="Status" />
        {hinweis && <Hinweis {...hinweis} />}
      </div>
    )
  }

  const laufend = status.jobs.filter((j) => j.laeuft)
  // Ein Hinweis: Aktion > Fehler > alles in Ordnung
  const anzeige =
    hinweis ||
    (status.fehler.length
      ? { ton: 'warnung', titel: `${status.fehler.length} ${status.fehler.length === 1 ? 'Problem' : 'Probleme'}: ${status.fehler[0]}`, details: status.fehler }
      : { ton: 'erfolg', titel: `Alles in Ordnung${laufend.length ? ` · läuft gerade: ${laufend.map((j) => j.name).join(', ')}` : ''}` })

  return (
    <div className="seite">
      <SeitenKopf
        titel="Status"
        aktion={
          <Button
            variante="primaer"
            icon="aktualisieren"
            onClick={() => ausfuehren(api.jetztSynchronisieren(), () => 'TISS und MB Cloud laufen; TUWEL holt die Browser-Erweiterung in den nächsten Minuten.')}
          >
            Jetzt synchronisieren
          </Button>
        }
      >
        Studien-Hub {status.version} · {status.modus === 'produktion' ? 'installiert' : 'Entwicklungsmodus'}
      </SeitenKopf>

      <Hinweis key={anzeige.titel} ton={anzeige.ton} titel={anzeige.titel} onSchliessen={hinweis ? () => setHinweis(null) : undefined}>
        {anzeige.details?.length > 1 && (
          <ul>
            {anzeige.details.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        )}
      </Hinweis>

      <div className="raster">
        <Karte titel="Quellen">
          <Tabelle>
            <thead>
              <tr>
                <th>Quelle</th>
                <th>Letzter Sync</th>
                <th>Zustand</th>
              </tr>
            </thead>
            <tbody>
              {status.quellen.map((q) => (
                <tr key={q.id}>
                  <td>{q.name}</td>
                  <td>{zeit(q.letzter_sync)}</td>
                  <td>
                    {!q.eingerichtet ? (
                      <Badge>nicht eingerichtet</Badge>
                    ) : q.fehler ? (
                      <Badge ton="verwerfen" icon="warnung" title={q.fehler.meldung}>
                        Fehler
                      </Badge>
                    ) : (
                      <Badge ton="bestaetigen" icon="erledigt">
                        ok
                      </Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Tabelle>
        </Karte>

        <Karte titel="Geplante Läufe">
          <Tabelle>
            <thead>
              <tr>
                <th>Lauf</th>
                <th>Zuletzt</th>
                <th>Nächster</th>
              </tr>
            </thead>
            <tbody>
              {status.jobs.map((j) => (
                <tr key={j.id}>
                  <td>
                    {j.name}{' '}
                    {j.laeuft && <Badge ton="primaer">läuft</Badge>}
                    {j.fehler && (
                      <Badge ton="verwerfen" icon="warnung" title={j.fehler.meldung}>
                        Fehler
                      </Badge>
                    )}
                  </td>
                  <td>{zeit(j.letztes_ende || j.letzter_start)}</td>
                  <td>{zeit(j.naechster_lauf)}</td>
                </tr>
              ))}
            </tbody>
          </Tabelle>
        </Karte>

        <Karte
          titel="Sicherungen"
          aktionen={
            <Button klein onClick={() => ausfuehren(api.sichern(), (e) => `Sicherung ${e.name} angelegt.`)}>
              Jetzt sichern
            </Button>
          }
        >
          <p className="leise klein">Täglich eine Sicherung der Datenbank; die 14 neuesten bleiben.</p>
          {status.sicherungen.length === 0 ? (
            <p className="leise">Noch keine Sicherung.</p>
          ) : (
            <Tabelle>
              <tbody>
                {status.sicherungen.map((s) => (
                  <tr key={s.name}>
                    <td>
                      {zeit(s.zeit)} {s.anlass && <Badge>{s.anlass.replace(/-/g, ' ')}</Badge>}
                    </td>
                    <td className="zahl">{mb(s.groesse)}</td>
                    <td className="zahl">
                      <Button klein onClick={() => setRueckfrage(s)}>
                        Wiederherstellen
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Tabelle>
          )}
        </Karte>

        <Karte titel="System">
          <dl className="angaben">
            <div>
              <dt>Version</dt>
              <dd>{status.version}</dd>
            </div>
            <div>
              <dt>Daten</dt>
              <dd>{status.daten_ordner}</dd>
            </div>
            <div>
              <dt>Programm</dt>
              <dd>{status.programm_ordner}</dd>
            </div>
          </dl>
          <div className="stapel">
            <Kontrolle
              label="Beim Anmelden an Windows starten"
              checked={status.autostart.aktiv}
              disabled={!status.autostart.verfuegbar}
              title={status.autostart.verfuegbar ? undefined : 'Nur für den installierten Hub'}
              onChange={(e) => ausfuehren(api.autostartSetzen(e.target.checked))}
            />
            <div className="knopf-gruppe">
              <Button klein icon="extern" onClick={() => ausfuehren(api.ordnerOeffnen('daten'))}>
                Datenordner
              </Button>
              <Button klein icon="extern" onClick={() => ausfuehren(api.ordnerOeffnen('logs'))}>
                Logs
              </Button>
              <Button klein onClick={onEinrichtung}>
                Einrichtung öffnen
              </Button>
            </div>
          </div>
        </Karte>
      </div>

      {status.meldungen.length > 0 && (
        <Karte titel={`Letzte Warnungen und Fehler (${status.meldungen.length})`} icon="warnung" aufklappbar>
          <Tabelle>
            <tbody>
              {status.meldungen.map((m, i) => (
                <tr key={`${m.zeit}-${i}`}>
                  <td className="leise">{zeit(m.zeit)}</td>
                  <td>
                    <Badge ton={m.stufe === 'WARNING' ? 'neutral' : 'verwerfen'}>{m.stufe === 'WARNING' ? 'Warnung' : 'Fehler'}</Badge>
                  </td>
                  <td className="meldung-text">{m.meldung}</td>
                </tr>
              ))}
            </tbody>
          </Tabelle>
        </Karte>
      )}

      {rueckfrage && (
        <Rueckfrage
          titel="Sicherung wiederherstellen?"
          text={`Der Hub springt auf den Stand vom ${zeit(rueckfrage.zeit)} zurück. Der aktuelle Stand wird vorher selbst gesichert und lässt sich genauso zurückholen.`}
          bestaetigen="Wiederherstellen"
          ton="bestaetigen"
          onNein={() => setRueckfrage(null)}
          onJa={() => {
            const name = rueckfrage.name
            setRueckfrage(null)
            ausfuehren(api.wiederherstellen(name), (e) => `Stand von ${zeit(rueckfrage.zeit)} wiederhergestellt; vorheriger Stand gesichert (${e.vorheriger_stand}).`)
          }}
        />
      )}
    </div>
  )
}
