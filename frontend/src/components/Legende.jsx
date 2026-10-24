import { Dialog, Icon, ICONS } from '../ui.jsx'

// Die eine Legende der Oberfläche: Symbole und Kalender-Einträge. Ansichten zeigen keine eigene Legende.
const SYMBOLE = ['steop', 'anwesenheit', 'aufzeichnung', 'pruefung', 'anmeldung', 'abgabe', 'arbeit', 'persoenlich', 'lernen', 'frei', 'tuwel', 'mbcloud', 'ki', 'warnung']

const EINTRAEGE = [
  { klasse: 'termin', name: 'Termin', text: 'Streifen in der Farbe der LVA' },
  { klasse: 'arbeit', name: 'Arbeit', text: 'flächig neutral' },
  { klasse: 'persoenlich', name: 'Persönlicher Termin', text: 'weiß, Personen-Symbol – Arbeit und Lernen weichen aus' },
  { klasse: 'lernen', name: 'Lernen', text: 'Streifen in der Farbe der LVA, Buch-Symbol' },
  { klasse: 'termin vorschlag', name: 'Vorschlag', text: 'gestrichelt – noch nicht fixiert' },
  { klasse: 'termin ausgeblendet', name: 'nicht besucht', text: 'blass – LVA zählt nicht für die Planung' },
  { klasse: 'frei', name: 'Feiertag / frei', text: 'ganztägig, keine Arbeit und kein Lernen' },
  { klasse: 'anmeldung', name: 'Prüfungsanmeldung', text: 'ganztägig – ab diesem Tag kannst du dich anmelden' },
]

export default function Legende({ onSchliessen }) {
  return (
    <Dialog titel="Legende" icon="hilfe" onSchliessen={onSchliessen} breit>
      <div className="legende">
        <section>
          <h3>Symbole</h3>
          <ul className="legende-liste">
            {SYMBOLE.map((s) => (
              <li key={s}>
                <Icon name={s} />
                {ICONS[s].name}
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3>Kalender</h3>
          <ul className="legende-liste">
            {EINTRAEGE.map((e) => (
              <li key={e.name}>
                <span className={`legende-muster eintrag ${e.klasse}`} style={{ '--lva': 'var(--lva-1)' }} />
                <span>
                  <strong>{e.name}</strong> <span className="leise">– {e.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Dialog>
  )
}
