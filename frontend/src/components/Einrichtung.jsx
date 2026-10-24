import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Badge, Button, Eingabe, Feld, Fortschritt, Hinweis, Karte, Rueckfrage, SeitenKopf } from '../ui.jsx'

// Einrichtungsassistent beim ersten Start; jeder Schritt lässt sich überspringen und später wiederholen
function Schritt({ nummer, titel, erledigt, children }) {
  return (
    <Karte
      className="einrichtung-schritt"
      titel={
        <span className="mit-icon">
          <span className="schritt-nummer">{nummer}</span>
          {titel}
        </span>
      }
      aktionen={erledigt ? <Badge ton="bestaetigen" icon="erledigt">erledigt</Badge> : <Badge>offen</Badge>}
    >
      <div className="stapel">{children}</div>
    </Karte>
  )
}

function KopierFeld({ wert, label }) {
  const [kopiert, setKopiert] = useState(false)
  return (
    <div className="formular-zeile">
      <Eingabe readOnly value={wert} aria-label={label} onFocus={(e) => e.target.select()} />
      <Button
        klein
        icon={kopiert ? 'ok' : 'kopieren'}
        onClick={() => navigator.clipboard?.writeText(wert).then(() => setKopiert(true))}
      >
        {kopiert ? 'Kopiert' : 'Kopieren'}
      </Button>
    </div>
  )
}

export default function Einrichtung({ onFertig, onDatenGeaendert }) {
  const [stand, setStand] = useState(null)
  const [hinweis, setHinweis] = useState(null)
  const [tissUrl, setTissUrl] = useState('')
  const [token, setToken] = useState('')
  const [rueckfrage, setRueckfrage] = useState(false)

  const laden = useCallback(() => api.einrichtung().then(setStand).catch((e) => setHinweis({ ton: 'fehler', titel: e.message })), [])
  useEffect(() => {
    laden()
    api.tissEinstellungen().then((t) => setTissUrl(t.ical_url || '')).catch(() => {})
  }, [laden])

  // während Übernahme, Download oder MB-Cloud-Anmeldung den Stand mitverfolgen
  const aktiv = stand && (stand.daten.stand.laeuft || stand.modelle.some((m) => m.laeuft) || stand.mbcloudWartet)
  useEffect(() => {
    if (!aktiv) return
    const zeitgeber = setInterval(async () => {
      if (stand.mbcloudWartet) await api.mbcloudVerbindenPruefen().catch(() => {})
      const neu = await api.einrichtung().catch(() => null)
      if (!neu) return
      if (stand.daten.stand.laeuft && neu.daten.stand.fertig) onDatenGeaendert?.()
      setStand({ ...neu, mbcloudWartet: stand.mbcloudWartet && !neu.mbcloud.eingerichtet })
    }, 1500)
    return () => clearInterval(zeitgeber)
  }, [aktiv, stand, onDatenGeaendert])

  const ausfuehren = (aufruf, erfolg) =>
    aufruf
      .then((ergebnis) => {
        if (erfolg) setHinweis({ ton: 'erfolg', titel: erfolg(ergebnis) })
        return laden()
      })
      .catch((e) => setHinweis({ ton: 'fehler', titel: e.message }))

  if (!stand) {
    return (
      <div className="seite">
        <SeitenKopf titel="Einrichtung" />
        {hinweis && <Hinweis {...hinweis} />}
      </div>
    )
  }

  const daten = stand.daten
  const uebernahme = daten.stand
  let nummer = 0
  const naechste = () => ++nummer

  return (
    <div className="seite einrichtung">
      <SeitenKopf titel="Willkommen im Studien-Hub">
        Ein paar Schritte, dann läuft alles im Hintergrund. Jeder Schritt lässt sich überspringen und später unter „Status“
        wiederholen.
      </SeitenKopf>

      {hinweis && <Hinweis key={hinweis.titel} {...hinweis} onSchliessen={() => setHinweis(null)} />}

      {daten.quelle && (
        <Schritt nummer={naechste()} titel="Bisherige Daten übernehmen" erledigt={Boolean(daten.uebernommen)}>
          <p>
            Gefunden: <code className="pfad">{daten.quelle}</code>. Übernommen werden Datenbank, Unterlagen, Modelle und die
            Zugangsdaten aus der dortigen .env. Der bisherige Stand im Hub wird vorher gesichert.
          </p>
          {uebernahme.laeuft && (
            <Fortschritt prozent={uebernahme.gesamt ? (100 * uebernahme.kopiert) / uebernahme.gesamt : 0} label={uebernahme.schritt} />
          )}
          {uebernahme.fehler && <Hinweis ton="fehler" titel={`Übernahme fehlgeschlagen: ${uebernahme.fehler}`} />}
          {daten.uebernommen && <p className="leise klein">Übernommen: {daten.uebernommen}</p>}
          {!uebernahme.laeuft && (
            <div className="knopf-gruppe">
              <Button variante="bestaetigen" onClick={() => setRueckfrage(true)}>
                {daten.uebernommen ? 'Erneut übernehmen' : 'Übernehmen'}
              </Button>
            </div>
          )}
        </Schritt>
      )}

      <Schritt nummer={naechste()} titel="TISS-Kalender" erledigt={stand.tiss.eingerichtet}>
        <Feld label="iCal-Link aus TISS" hilfe="TISS → Favoriten → Kalender exportieren (iCal), Link kopieren und hier einfügen.">
          <Eingabe value={tissUrl} placeholder="https://tiss.tuwien.ac.at/events/rest/calendar/personal?…" onChange={(e) => setTissUrl(e.target.value)} />
        </Feld>
        <div className="knopf-gruppe">
          <Button
            variante="bestaetigen"
            disabled={!tissUrl.trim()}
            onClick={() =>
              ausfuehren(
                api.tissEinstellungenSpeichern({ ical_url: tissUrl.trim() }).then(() => api.tissImport()),
                (e) => `Kalender importiert: ${e.neu ?? 0} neue Termine.`,
              ).then(() => onDatenGeaendert?.())
            }
          >
            Speichern und importieren
          </Button>
        </div>
      </Schritt>

      <Schritt nummer={naechste()} titel="TUWEL-Token" erledigt={stand.tuwel.eingerichtet}>
        <p className="leise">
          Für den direkten Zugriff auf TUWEL (optional – Unterlagen holt sonst die Browser-Erweiterung). Der Token wird in der
          Windows-Anmeldeinformationsverwaltung gespeichert, nicht in einer Datei.
        </p>
        <Feld label="Anmelde-Link oder Token" hilfe="Der Text nach „moodledownloader://token=“ oder der ganze Link.">
          <Eingabe type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
        </Feld>
        <div className="knopf-gruppe">
          <Button
            variante="bestaetigen"
            disabled={!token.trim()}
            onClick={() => ausfuehren(api.tuwelTokenSetzen(token), () => 'TUWEL-Token gespeichert.').then(() => setToken(''))}
          >
            Speichern
          </Button>
        </div>
      </Schritt>

      <Schritt nummer={naechste()} titel="MB Cloud" erledigt={stand.mbcloud.eingerichtet}>
        <p className="leise">
          Altprüfungen und Lösungen der Fachschaft (inoffiziell). Die Anmeldung öffnet sich im Browser; der Hub bekommt nur ein
          App-Passwort, das du in der MB Cloud jederzeit widerrufen kannst.
        </p>
        {stand.mbcloudWartet && <p>Warte auf die Bestätigung im Browser …</p>}
        <div className="knopf-gruppe">
          <Button
            variante="bestaetigen"
            onClick={() =>
              api
                .mbcloudVerbinden()
                .then(({ login_url }) => {
                  window.open(login_url, '_blank', 'noopener')
                  setStand({ ...stand, mbcloudWartet: true })
                })
                .catch((e) => setHinweis({ ton: 'fehler', titel: e.message }))
            }
          >
            {stand.mbcloud.eingerichtet ? 'Neu verbinden' : 'Verbinden'}
          </Button>
        </div>
      </Schritt>

      <Schritt nummer={naechste()} titel="Browser-Erweiterung in Edge laden" erledigt={stand.erweiterung.verbunden}>
        <p className="leise">Die Erweiterung lädt TUWEL-Unterlagen und den STEOP-Status mit deiner Anmeldung im Browser.</p>
        <ol className="anleitung">
          <li>
            In Edge die Adresse <code>edge://extensions</code> öffnen (kopieren und in die Adresszeile einfügen).
            <KopierFeld wert="edge://extensions" label="Adresse der Erweiterungsseite" />
          </li>
          <li>Links unten „Entwicklermodus“ einschalten.</li>
          <li>
            „Entpackte Erweiterung laden“ wählen und diesen Ordner auswählen:
            <KopierFeld wert={stand.erweiterung.ordner} label="Ordner der Erweiterung" />
            <Button klein icon="extern" onClick={() => ausfuehren(api.ordnerOeffnen('erweiterung'))}>
              Ordner öffnen
            </Button>
          </li>
          <li>
            Fertig – die Erweiterung holt sich den Schlüssel selbst. Zum Testen TUWEL öffnen; der erste Lauf startet dann von
            allein. Die ID der Erweiterung ist immer <code>{stand.erweiterung.id}</code>.
          </li>
        </ol>
        <p className="leise klein">Chrome geht genauso über chrome://extensions.</p>
      </Schritt>

      <Schritt nummer={naechste()} titel="KI verbinden (Claude Desktop)" erledigt={stand.ki.eingerichtet}>
        <p className="leise">
          Trägt den Hub als MCP-Server in Claude Desktop ein (mit Sicherung der bisherigen Konfiguration). Danach Claude Desktop
          ganz beenden und neu starten.
        </p>
        <div className="knopf-gruppe">
          <Button variante="bestaetigen" onClick={() => ausfuehren(api.kiEinrichten(), () => 'In Claude Desktop eingetragen.')}>
            {stand.ki.eingerichtet ? 'Erneut eintragen' : 'Eintragen'}
          </Button>
        </div>
      </Schritt>

      <Schritt nummer={naechste()} titel="Modelle herunterladen" erledigt={stand.modelle.every((m) => m.vorhanden)}>
        <p className="leise">Laufen danach offline auf diesem Laptop. Die Transkription brauchst du nur für Vorlesungsvideos.</p>
        {stand.modelle.map((m) => (
          <div key={m.id} className="modell-zeile">
            <div className="reihe">
              <strong>{m.name}</strong>
              <span className="leise klein">{m.groesse_mb} MB</span>
              {m.vorhanden && !m.laeuft ? (
                <Badge ton="bestaetigen" icon="erledigt">
                  vorhanden
                </Badge>
              ) : (
                !m.laeuft && (
                  <Button klein icon="laden" onClick={() => ausfuehren(api.modellLaden(m.id))}>
                    Herunterladen
                  </Button>
                )
              )}
            </div>
            {m.laeuft && <Fortschritt prozent={m.prozent} label="Wird geladen" />}
            {m.fehler && <Hinweis ton="fehler" titel={`Download fehlgeschlagen: ${m.fehler}`} />}
          </div>
        ))}
      </Schritt>

      <div className="knopf-gruppe einrichtung-fuss">
        <Button onClick={onFertig}>Später</Button>
        <Button variante="primaer" onClick={() => api.einrichtungAbschliessen().then(onFertig)}>
          Fertig
        </Button>
      </div>

      {rueckfrage && (
        <Rueckfrage
          titel="Bisherige Daten übernehmen?"
          text={`Die Daten aus ${daten.quelle} ersetzen den aktuellen Stand im Hub. Der aktuelle Stand wird vorher gesichert und lässt sich unter „Status“ wiederherstellen.`}
          bestaetigen="Übernehmen"
          ton="bestaetigen"
          onNein={() => setRueckfrage(false)}
          onJa={() => {
            setRueckfrage(false)
            ausfuehren(api.datenUebernehmen())
          }}
        />
      )}
    </div>
  )
}
