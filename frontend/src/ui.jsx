// Einheitliche Bausteine der Oberfläche. Alle Seiten verwenden nur diese (CLAUDE.md „Design-Regeln“).
import { useEffect, useId, useRef, useState } from 'react'
import {
  BookOpen,
  Briefcase,
  CalendarClock,
  CalendarOff,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CircleCheck,
  Copy,
  CircleHelp,
  Cloud,
  Download,
  Ellipsis,
  ExternalLink,
  EyeOff,
  FileCheck,
  GraduationCap,
  Info,
  ListFilter,
  Menu,
  Pencil,
  Plus,
  RefreshCw,
  School,
  Search,
  Sparkles,
  Star,
  Trash2,
  TriangleAlert,
  Upload,
  User,
  UserCheck,
  Video,
  X,
} from 'lucide-react'

// --- Icons: eine Größe, eine Strichstärke; Bedeutung je Name ----------------------------------------

export const ICONS = {
  // Fachliche Bedeutungen (stehen in der Legende)
  steop: { icon: Star, name: 'STEOP' },
  anwesenheit: { icon: UserCheck, name: 'Anwesenheitspflicht' },
  aufzeichnung: { icon: Video, name: 'Aufzeichnung' },
  pruefung: { icon: GraduationCap, name: 'Prüfung' },
  anmeldung: { icon: CalendarClock, name: 'Prüfungsanmeldung ab' },
  abgabe: { icon: FileCheck, name: 'Abgabe' },
  arbeit: { icon: Briefcase, name: 'Arbeit' },
  persoenlich: { icon: User, name: 'Persönlicher Termin' },
  lernen: { icon: BookOpen, name: 'Lernen' },
  frei: { icon: CalendarOff, name: 'Feiertag / frei' },
  tuwel: { icon: School, name: 'TUWEL' },
  mbcloud: { icon: Cloud, name: 'MB Cloud' },
  ki: { icon: Sparkles, name: 'KI' },
  warnung: { icon: TriangleAlert, name: 'Warnung' },
  ausgeblendet: { icon: EyeOff, name: 'nicht besucht' },
  // Bedienung
  erledigt: { icon: CircleCheck, name: 'erledigt' },
  info: { icon: Info, name: 'Info' },
  hilfe: { icon: CircleHelp, name: 'Legende' },
  schliessen: { icon: X, name: 'Schließen' },
  zurueck: { icon: ChevronLeft, name: 'Zurück' },
  weiter: { icon: ChevronRight, name: 'Weiter' },
  auf: { icon: ChevronRight, name: 'Aufklappen' },
  runter: { icon: ChevronDown, name: 'Nach unten' },
  hoch: { icon: ChevronUp, name: 'Nach oben' },
  kopieren: { icon: Copy, name: 'Kopieren' },
  mehr: { icon: Ellipsis, name: 'Weitere Aktionen' },
  filter: { icon: ListFilter, name: 'Filter' },
  menue: { icon: Menu, name: 'Menü' },
  suche: { icon: Search, name: 'Suchen' },
  loeschen: { icon: Trash2, name: 'Löschen' },
  bearbeiten: { icon: Pencil, name: 'Bearbeiten' },
  neu: { icon: Plus, name: 'Neu' },
  ok: { icon: Check, name: 'OK' },
  laden: { icon: Download, name: 'Herunterladen' },
  hochladen: { icon: Upload, name: 'Hochladen' },
  aktualisieren: { icon: RefreshCw, name: 'Aktualisieren' },
  extern: { icon: ExternalLink, name: 'Öffnen' },
}

/** Icon nach Bedeutung. Mit `label` (ohne sichtbaren Text daneben) bekommt es Tooltip und aria-label;
 *  ohne `label` ist es Schmuck neben einem Text und für Screenreader verborgen. */
export function Icon({ name, label, className = '' }) {
  const eintrag = ICONS[name]
  if (!eintrag) return null
  const Komponente = eintrag.icon
  const svg = <Komponente className={`icon ${className}`} strokeWidth={1.75} aria-hidden={label ? undefined : true} />
  if (!label) return svg
  return (
    <span role="img" aria-label={label} title={label} className="icon-mit-label">
      {svg}
    </span>
  )
}

// --- Button -----------------------------------------------------------------------------------------

/** variante: primaer (genau einer je Ansicht) | bestaetigen | verwerfen | umriss (Standard, auch „Abbrechen“).
 *  Mit `href` wird ein Link im Button-Aussehen daraus (z. B. Downloads). */
export function Button({ variante = 'umriss', icon, klein, href, className = '', children, ...rest }) {
  const klasse = `knopf knopf-${variante}${klein ? ' klein' : ''} ${className}`
  const inhalt = (
    <>
      {icon && <Icon name={icon} />}
      {children}
    </>
  )
  if (href) {
    return (
      <a className={klasse} href={href} {...rest}>
        {inhalt}
      </a>
    )
  }
  return (
    <button type="button" className={klasse} {...rest}>
      {inhalt}
    </button>
  )
}

/** Button nur mit Icon: `label` ist Pflicht (Tooltip und aria-label). ton: verwerfen färbt rot. */
export function IconButton({ icon, label, ton, aktiv, klein, className = '', ...rest }) {
  return (
    <button
      type="button"
      className={`knopf knopf-icon${ton ? ` ton-${ton}` : ''}${aktiv ? ' aktiv' : ''}${klein ? ' klein' : ''} ${className}`}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  )
}

// --- Eingabefeld, Auswahl, Kontrollkästchen ------------------------------------------------------------

/** Beschriftetes Feld um ein Eingabeelement (Eingabe, Auswahl …). */
export function Feld({ label, hilfe, fehler, children, className = '' }) {
  return (
    <label className={`feld ${className}`}>
      <span className="feld-beschriftung">{label}</span>
      {children}
      {hilfe && <span className="feld-hilfe">{hilfe}</span>}
      {fehler && <span className="feld-fehler">{fehler}</span>}
    </label>
  )
}

/** Eingabefeld; breite: schmal | mittel | (voll). Mehrzeilig mit `mehrzeilig`. */
export function Eingabe({ breite, mehrzeilig, className = '', ...rest }) {
  const klasse = `eingabe${breite ? ` ${breite}` : ''} ${className}`
  return mehrzeilig ? <textarea className={klasse} {...rest} /> : <input className={klasse} {...rest} />
}

/** Auswahl; `optionen` = [{ wert, name }] oder Kinder (<option>). */
export function Auswahl({ optionen, breite, className = '', children, ...rest }) {
  return (
    <select className={`eingabe${breite ? ` ${breite}` : ''} ${className}`} {...rest}>
      {optionen ? optionen.map((o) => <option key={o.wert} value={o.wert}>{o.name}</option>) : children}
    </select>
  )
}

/** Zahl, die beim Verlassen des Feldes gespeichert wird (leer = null). */
export function ZahlEingabe({ wert, onSpeichern, schritt = '1', min = '0', max, leerErlaubt = true, breite = 'schmal', ...rest }) {
  return (
    <Eingabe
      type="number"
      breite={breite}
      min={min}
      max={max}
      step={schritt}
      key={wert ?? 'leer'}
      defaultValue={wert ?? ''}
      onBlur={(e) => {
        const neu = e.target.value === '' ? null : Number(e.target.value)
        if (neu === null && !leerErlaubt) return
        if (neu !== (wert ?? null)) onSpeichern(neu)
      }}
      {...rest}
    />
  )
}

/** Kontrollkästchen oder Optionsfeld mit Beschriftung (`typ="radio"`). */
export function Kontrolle({ label, typ = 'checkbox', className = '', title, ...rest }) {
  return (
    <label className={`kontrolle ${className}`} title={title}>
      <input type={typ} {...rest} />
      <span>{label}</span>
    </label>
  )
}

// --- Karte, Tabelle, Badge -----------------------------------------------------------------------------

/** Karte mit optionalem Kopf (Titel, Icon, Aktionen). Mit `aufklappbar` als <details>. */
export function Karte({ titel, icon, aktionen, aufklappbar, offen, className = '', children, ...rest }) {
  if (aufklappbar) {
    return (
      <details className={`karte ${className}`} open={offen} {...rest}>
        <summary>
          <Icon name="auf" className="icon-auf" />
          {icon && <Icon name={icon} />}
          <span>{titel}</span>
          {aktionen && <span className="karte-summary-aktionen">{aktionen}</span>}
        </summary>
        {children}
      </details>
    )
  }
  return (
    <section className={`karte ${className}`} {...rest}>
      {(titel || aktionen) && (
        <div className="karte-kopf">
          {titel && (
            <h2>
              {icon && <Icon name={icon} />}
              {titel}
            </h2>
          )}
          {aktionen && <div className="knopf-gruppe">{aktionen}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

export function Tabelle({ className = '', children, ...rest }) {
  return (
    <div className="tabelle-huelle">
      <table className={`tabelle ${className}`} {...rest}>
        {children}
      </table>
    </div>
  )
}

/** ton: neutral | primaer | bestaetigen | verwerfen | umriss */
export function Badge({ ton = 'neutral', icon, title, children }) {
  return (
    <span className={`badge badge-${ton}`} title={title}>
      {icon && <Icon name={icon} />}
      {children}
    </span>
  )
}

// --- Hinweis ---------------------------------------------------------------------------------------------

const HINWEIS_ICON = { info: 'info', erfolg: 'erledigt', fehler: 'warnung', warnung: 'warnung' }

/** Eine Zeile Zusammenfassung (`titel`), Details (children) aufklappbar. ton: info | erfolg | warnung | fehler.
 *  `aktionen` stehen in der Zeile. Je Ansicht höchstens ein Hinweis gleichzeitig. */
export function Hinweis({ ton = 'info', titel, children, aktionen, onSchliessen, offen = false }) {
  const [auf, setAuf] = useState(offen)
  const id = useId()
  return (
    <div className={`hinweis hinweis-${ton}`} role={ton === 'fehler' ? 'alert' : 'status'}>
      <div className="hinweis-zeile">
        <Icon name={HINWEIS_ICON[ton]} />
        <span className="hinweis-text">{titel}</span>
        {children && (
          <Button klein aria-expanded={auf} aria-controls={id} onClick={() => setAuf(!auf)}>
            {auf ? 'Weniger' : 'Details'}
          </Button>
        )}
        {aktionen}
        {onSchliessen && <IconButton icon="schliessen" label="Hinweis schließen" klein onClick={onSchliessen} />}
      </div>
      {children && auf && (
        <div className="hinweis-details" id={id}>
          {children}
        </div>
      )}
    </div>
  )
}

// --- Dialog und Seitenleiste ---------------------------------------------------------------------------

function useEscape(onSchliessen) {
  useEffect(() => {
    const taste = (e) => e.key === 'Escape' && onSchliessen?.()
    window.addEventListener('keydown', taste)
    return () => window.removeEventListener('keydown', taste)
  }, [onSchliessen])
}

/** Modaler Dialog. `aktionen` = Buttons im Fuß (rechts). */
export function Dialog({ titel, icon, onSchliessen, aktionen, breit, children }) {
  useEscape(onSchliessen)
  const ref = useRef(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <div className="abdunkeln" onMouseDown={(e) => e.target === e.currentTarget && onSchliessen?.()}>
      <div className={`dialog${breit ? ' breit' : ''}`} role="dialog" aria-modal="true" aria-label={titel} tabIndex={-1} ref={ref}>
        <div className="dialog-kopf">
          <h2>
            {icon && <Icon name={icon} />}
            {titel}
          </h2>
          {onSchliessen && <IconButton icon="schliessen" label="Schließen" onClick={onSchliessen} />}
        </div>
        {children}
        {aktionen && <div className="dialog-fuss">{aktionen}</div>}
      </div>
    </div>
  )
}

/** Rückfrage vor einer Aktion, die sich nicht rückgängig machen lässt. */
export function Rueckfrage({ titel, text, bestaetigen = 'Löschen', ton = 'verwerfen', onJa, onNein }) {
  return (
    <Dialog
      titel={titel}
      onSchliessen={onNein}
      aktionen={
        <>
          <Button onClick={onNein}>Abbrechen</Button>
          <Button variante={ton} onClick={onJa}>
            {bestaetigen}
          </Button>
        </>
      }
    >
      <p>{text}</p>
    </Dialog>
  )
}

/** Seitenleiste rechts (Details zu einem Eintrag, auf schmalen Bildschirmen auch Filter). */
export function Seitenleiste({ titel, icon, onSchliessen, aktionen, children, farbe }) {
  useEscape(onSchliessen)
  const ref = useRef(null)
  useEffect(() => ref.current?.focus(), [])
  return (
    <div className="abdunkeln seitlich" onMouseDown={(e) => e.target === e.currentTarget && onSchliessen?.()}>
      <aside
        className="seitenleiste"
        role="dialog"
        aria-modal="true"
        aria-label={titel}
        tabIndex={-1}
        ref={ref}
        style={farbe ? { borderLeft: `var(--streifen) solid ${farbe}` } : undefined}
      >
        <div className="seitenleiste-kopf">
          <h2>
            {icon && <Icon name={icon} />}
            {titel}
          </h2>
          <IconButton icon="schliessen" label="Schließen" onClick={onSchliessen} />
        </div>
        <div className="seitenleiste-inhalt">{children}</div>
        {aktionen && <div className="seitenleiste-fuss">{aktionen}</div>}
      </aside>
    </div>
  )
}

// --- Menü (weitere, zurückhaltende Aktionen) ---------------------------------------------------------

/** Aufklappmenü hinter einem Icon-Button. eintraege = [{ name, icon, ton, onClick }] */
export function Menue({ label = 'Weitere Aktionen', icon = 'mehr', eintraege }) {
  const [offen, setOffen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!offen) return
    const klick = (e) => !ref.current?.contains(e.target) && setOffen(false)
    const taste = (e) => e.key === 'Escape' && setOffen(false)
    document.addEventListener('mousedown', klick)
    document.addEventListener('keydown', taste)
    return () => {
      document.removeEventListener('mousedown', klick)
      document.removeEventListener('keydown', taste)
    }
  }, [offen])
  return (
    <div className="menue" ref={ref}>
      <IconButton icon={icon} label={label} aria-haspopup="menu" aria-expanded={offen} onClick={() => setOffen(!offen)} />
      {offen && (
        <div className="menue-liste" role="menu">
          {eintraege.map((e) => (
            <button
              key={e.name}
              type="button"
              role="menuitem"
              className={`menue-eintrag${e.ton ? ` ton-${e.ton}` : ''}`}
              title={e.title}
              onClick={() => {
                setOffen(false)
                e.onClick()
              }}
            >
              {e.icon && <Icon name={e.icon} />}
              {e.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// --- Fortschritt -----------------------------------------------------------------------------------------

/** Fortschrittsbalken 0–100 mit Beschriftung (z. B. Download, Datenübernahme). */
export function Fortschritt({ prozent, label }) {
  const wert = Math.max(0, Math.min(100, Math.round(prozent)))
  return (
    <div className="fortschritt">
      <div className="fortschritt-balken" role="progressbar" aria-valuenow={wert} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
        <span style={{ width: `${wert}%` }} />
      </div>
      <span className="klein leise">
        {label} · {wert} %
      </span>
    </div>
  )
}

// --- Leerer Zustand und Seitenkopf -------------------------------------------------------------------

export function LeererZustand({ icon = 'info', titel, children, aktion }) {
  return (
    <div className="leer">
      <Icon name={icon} />
      <h3>{titel}</h3>
      {children && <p>{children}</p>}
      {aktion}
    </div>
  )
}

/** Kopf einer Seite: Titel, ein Satz Beschreibung, höchstens ein Hauptbutton (`aktion`). */
export function SeitenKopf({ titel, children, aktion }) {
  return (
    <div className="seiten-kopf">
      <div className="seiten-kopf-text">
        <h1>{titel}</h1>
        {children && <p>{children}</p>}
      </div>
      {aktion && <div className="knopf-gruppe">{aktion}</div>}
    </div>
  )
}

// --- Hilfen -----------------------------------------------------------------------------------------------

export const komma = (zahl) => String(zahl).replace('.', ',')

// Häufige lange Wörter in LVA-Titeln und ihre üblichen Kürzel; Füllwörter fallen beim Kürzen weg
const KUERZEL = {
  mathematik: 'Mathe',
  grundlagen: 'Grdl.',
  einführung: 'Einf.',
  technisches: 'Techn.',
  technische: 'Techn.',
  technischen: 'Techn.',
  maschinenbau: 'MB',
  wirtschaftsingenieurwesen: 'WiIng',
  werkstoffkunde: 'Werkstoffk.',
  unternehmensführung: 'Unternehmensf.',
  konstruktionslehre: 'Konstruktionsl.',
  fertigungstechnik: 'Fertigungst.',
  projektmanagement: 'Projektmgmt.',
  darstellende: 'Darst.',
  geometrie: 'Geom.',
  metallischer: 'met.',
  nichtmetallischer: 'nichtmet.',
  programmierung: 'Progr.',
  elektrotechnik: 'ET',
  thermodynamik: 'Thermo',
  und: '&',
}
const FUELLWOERTER = new Set(['der', 'die', 'das', 'des', 'in', 'im', 'zur', 'zum', 'von'])
const MAX_KURZ = 22

/** Name einer LVA aus der API (mit Typ, damit VO und UE gleichen Titels unterscheidbar sind). */
export const lvaName = (lva) => kurzTitel(lva.titel, lva.kurzname, lva.typ)

/** Kurzer Anzeigename einer LVA: eigener Kurzname, sonst gekürzter Titel – Zusatz nach „für“/„–“/Klammer weg,
 *  lange Wörter abgekürzt, Füllwörter weg („Mathematik 1 für MB, WIMB und VT“ → „Mathe 1“,
 *  „Einführung in Maschinenbau und Wirtschaftsingenieurwesen“ → „Einf. MB & WiIng“). */
export function kurzTitel(titel, kurzname, typ) {
  if (kurzname) return kurzname
  if (!titel) return ''
  // Namen vom Backend tragen den Typ am Ende („Mathematik 1 für MB, WIMB und VT UE“): abtrennen, kürzen, wieder anhängen
  const endung = titel.match(/\s(VO|UE|VU|SE|PR|LU|PS|EX|KO|AG|PV|SV|UV|VL)$/)
  if (endung) return kurzTitel(titel.slice(0, endung.index), null, typ || endung[1])
  if (typ) return `${kurzTitel(titel)} ${typ}`
  const kern = titel.split(/\s+(?:für|for)\s+|\s+[-–]\s+|\s*[(:,]\s*/)[0].trim()
  const woerter = kern.split(/\s+/)
  let t = woerter.map((w) => KUERZEL[w.toLowerCase()] ?? w).join(' ')
  if (t.length <= MAX_KURZ) return t
  t = woerter
    .filter((w, i) => i === 0 || !FUELLWOERTER.has(w.toLowerCase()))
    .map((w) => KUERZEL[w.toLowerCase()] ?? w)
    .join(' ')
  if (t.length <= MAX_KURZ) return t
  // immer noch zu lang: ganze Wörter bis zur Grenze, ohne hängendes „&“ oder Bindestrich
  let gekuerzt = ''
  for (const w of t.split(' ')) {
    if (`${gekuerzt} ${w}`.trim().length > MAX_KURZ - 1) break
    gekuerzt = `${gekuerzt} ${w}`.trim()
  }
  return `${(gekuerzt || t.slice(0, MAX_KURZ - 1)).replace(/[\s&-]+$/, '')}…`
}
