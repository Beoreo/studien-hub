import { Fragment, useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Badge, Button, Hinweis, Karte, Kontrolle, LeererZustand, Menue, SeitenKopf, Tabelle } from '../ui.jsx'
import './Wochenbericht.css'

const zeit = (iso) => (iso ? new Date(iso).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' }) : '–')
const ANLASS = { zeitplan: 'Sonntagslauf', nachgeholt: 'nachgeholt', manuell: 'von Hand' }
const wocheText = (iso) => `Woche ab ${new Date(iso).toLocaleDateString('de-AT')}`

// Was in TUWEL in einer Woche dazugekommen ist – sofort aus den Daten des Hubs, ohne Claude
export default function Wochenbericht() {
  const [status, setStatus] = useState(null)
  const [liste, setListe] = useState([])
  const [offen, setOffen] = useState(null)
  const [fehler, setFehler] = useState(null)
  const [laeuft, setLaeuft] = useState(false)

  const laden = useCallback(() => {
    Promise.all([api.wochenberichtStatus(), api.wochenberichte()])
      .then(([s, l]) => {
        setStatus(s)
        setListe(l)
        if (l.length && (!offen || !l.some((b) => b.id === offen.id))) api.wochenbericht(l[0].id).then(setOffen)
        if (!l.length) setOffen(null)
      })
      .catch((e) => setFehler(e.message))
  }, [offen])
  useEffect(laden, []) // eslint-disable-line react-hooks/exhaustive-deps

  const ausfuehren = (aufruf) => aufruf.then(laden).catch((e) => setFehler(e.message))
  const erstellen = () => {
    setLaeuft(true)
    api
      .wochenberichtErstellen()
      .then((b) => {
        setOffen(b)
        laden()
      })
      .catch((e) => setFehler(e.message))
      .finally(() => setLaeuft(false))
  }

  if (!status) {
    return (
      <div className="seite">
        {fehler ? <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} /> : <p className="leise">Lade …</p>}
      </div>
    )
  }

  // Höchstens ein Hinweis: Fehler, sonst Fehler des offenen Berichts
  const hinweis = fehler ? (
    <Hinweis ton="fehler" titel={fehler} onSchliessen={() => setFehler(null)} />
  ) : offen?.status === 'fehler' ? (
    <Hinweis ton="fehler" titel={`Bericht „${wocheText(offen.woche)}“ fehlgeschlagen.`} offen>
      {offen.fehler}
    </Hinweis>
  ) : null

  return (
    <div className="seite">
      <SeitenKopf
        titel="Wochenbericht"
        aktion={
          <Button variante="primaer" icon="aktualisieren" onClick={erstellen} disabled={laeuft}>
            Bericht dieser Woche erstellen
          </Button>
        }
      >
        Was in TUWEL in einer Woche dazugekommen ist: neue und geänderte Unterlagen und Aufzeichnungen je LVA, mit geschätztem
        Stoff.
      </SeitenKopf>
      {hinweis}
      <Kontrolle
        label={`Jeden Sonntag um ${status.stunde} Uhr automatisch erstellen`}
        checked={status.aktiv}
        onChange={(e) => ausfuehren(api.wochenberichtEinstellen(e.target.checked))}
      />

      {liste.length === 0 ? (
        <LeererZustand icon="tuwel" titel="Noch keine Berichte">
          Der erste Bericht entsteht am Sonntag oder mit „Bericht dieser Woche erstellen“.
        </LeererZustand>
      ) : (
        <div className="bericht-aufbau">
          <nav className="bericht-liste" aria-label="Berichte">
            {liste.map((b) => (
              <button
                key={b.id}
                type="button"
                className={`bericht-eintrag${offen?.id === b.id ? ' aktiv' : ''}`}
                aria-current={offen?.id === b.id ? 'true' : undefined}
                onClick={() => api.wochenbericht(b.id).then(setOffen)}
              >
                <span>{wocheText(b.woche)}</span>
                {b.status === 'ok' ? (
                  <span className="leise klein">{b.neue_unterlagen} neu</span>
                ) : b.status === 'laeuft' ? (
                  <Badge ton="primaer">läuft</Badge>
                ) : (
                  <Badge ton="verwerfen" icon="warnung">
                    Fehler
                  </Badge>
                )}
              </button>
            ))}
          </nav>

          {offen && (
            <Karte
              className="bericht-inhalt"
              titel={wocheText(offen.woche)}
              aktionen={
                <Menue
                  eintraege={[
                    {
                      name: 'Bericht löschen',
                      icon: 'loeschen',
                      ton: 'verwerfen',
                      onClick: () => ausfuehren(api.wochenberichtLoeschen(offen.id)).then(() => setOffen(null)),
                    },
                  ]}
                />
              }
            >
              <div className="bericht-meta">
                <span className="leise klein">
                  Erstellt {zeit(offen.erstellt_am)} ({ANLASS[offen.anlass] || offen.anlass})
                </span>
              </div>
              {offen.text && <Markdown text={offen.text} />}
            </Karte>
          )}
        </div>
      )}
    </div>
  )
}
// Kleines Markdown: Überschriften, Listen, Tabellen, **fett**, *kursiv*, `Code` – ohne rohes HTML
function inline(text) {
  const teile = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g)
  return teile.map((t, i) => {
    if (t.startsWith('**') && t.endsWith('**')) return <strong key={i}>{t.slice(2, -2)}</strong>
    if (t.startsWith('`') && t.endsWith('`')) return <code key={i}>{t.slice(1, -1)}</code>
    if (t.startsWith('*') && t.endsWith('*') && t.length > 2) return <em key={i}>{t.slice(1, -1)}</em>
    return <Fragment key={i}>{t}</Fragment>
  })
}

export function Markdown({ text }) {
  const bloecke = []
  const zeilen = text.split('\n')
  for (let i = 0; i < zeilen.length; i++) {
    const zeile = zeilen[i]
    const ueberschrift = zeile.match(/^(#{1,4})\s+(.*)/)
    if (ueberschrift) {
      const Tag = `h${Math.min(ueberschrift[1].length + 1, 5)}`
      bloecke.push(<Tag key={i}>{inline(ueberschrift[2])}</Tag>)
    } else if (/^\s*\|/.test(zeile)) {
      const tabelle = []
      while (i < zeilen.length && /^\s*\|/.test(zeilen[i])) tabelle.push(zeilen[i++])
      i--
      const zellen = (z) => z.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      const [kopf, , ...rest] = tabelle
      bloecke.push(
        <Tabelle key={i}>
          <thead>
            <tr>{zellen(kopf).map((c, j) => <th key={j}>{inline(c)}</th>)}</tr>
          </thead>
          <tbody>
            {rest.map((z, k) => (
              <tr key={k}>{zellen(z).map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>
            ))}
          </tbody>
        </Tabelle>,
      )
    } else if (/^\s*([-*]|\d+\.)\s+/.test(zeile)) {
      const nummeriert = /^\s*\d+\./.test(zeile)
      const punkte = []
      while (i < zeilen.length && /^\s*([-*]|\d+\.)\s+/.test(zeilen[i])) punkte.push(zeilen[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''))
      i--
      const Liste = nummeriert ? 'ol' : 'ul'
      bloecke.push(
        <Liste key={i}>
          {punkte.map((p, k) => (
            <li key={k}>{inline(p)}</li>
          ))}
        </Liste>,
      )
    } else if (zeile.trim()) {
      bloecke.push(<p key={i}>{inline(zeile)}</p>)
    }
  }
  return <div className="markdown">{bloecke}</div>
}
