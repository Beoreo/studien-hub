// Prüfungstermine für den Hub: TISS-Prüfungslisten (LVA → „Prüfungstermine“) und Prüfungen im TUWEL-Kalender.
// Reine Textauswertung ohne DOM (mit node testbar); der Abruf bekommt fetch, Hub und TUWEL von außen.
//
// TISS zeigt je Termin Datum, Uhrzeit, Ort und die Anmeldefrist. Weil sich der Aufbau der Seite ändern kann, wird
// jeder Termin-Block als Text gelesen und über Beschriftungen („Anmeldung“, „Abmeldung“, „Ort“) ausgewertet.
import { NichtEingeloggt } from './lib.js'
import { TISS } from './tiss.js'

const DATUM = String.raw`(\d{1,2})\.(\d{1,2})\.(\d{4})`
const DATUM_ZEIT = String.raw`${DATUM}(?:,?\s*(?:um\s*)?(\d{1,2}):(\d{2}))?`
const KEINE_TERMINE = /keine\s+(?:\S+\s+){0,3}(?:Prüfungs)?termine|keine\s+Prüfung|keine\s+Einträge|no\s+(?:\S+\s+){0,2}exam|no\s+entries/i

const text = (html) =>
  (html || '')
    .replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<!--[\s\S]*?-->/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#x?[0-9a-f]+;/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()

const zwei = (n) => String(n).padStart(2, '0')

/** Datum (und Uhrzeit) aus den Gruppen eines DATUM_ZEIT-Treffers als lokale ISO-Zeit ohne Zeitzone. */
function iso(tag, monat, jahr, stunde, minute, standardZeit = '00:00') {
  if (!tag) return null
  const zeit = stunde !== undefined ? `${zwei(stunde)}:${minute}` : standardZeit
  return `${jahr}-${zwei(monat)}-${zwei(tag)}T${zeit}:00`
}

export function pruefungsListeUrl(nummer, semester) {
  return `${TISS}/education/course/examDateList.xhtml?courseNr=${nummer.replace('.', '')}&semester=${semester}`
}

/** courseNr und Semester aus der Adresse einer Prüfungsliste („104297“ → „104.297“). */
export function listeAusUrl(url) {
  try {
    const u = new URL(url)
    if (!/examDateList/i.test(u.pathname)) return null
    const nr = (u.searchParams.get('courseNr') || '').replace('.', '')
    return nr.length >= 6 ? { nummer: `${nr.slice(0, 3)}.${nr.slice(3)}`, semester: u.searchParams.get('semester') } : null
  } catch {
    return null
  }
}

/** Ein Block je Termin: TISS fasst jeden Termin in eine „groupWrapper“-Box; sonst eine Tabellenzeile je Termin. */
function bloecke(html) {
  const boxen = html.split(/(?=<div\b[^>]*class="[^"]*\bgroupWrapper\b)/i)
  if (boxen.length > 1) return boxen.slice(1)
  return (html.match(/<tr\b[\s\S]*?<\/tr>/gi) || []).filter((z) => /<td\b/i.test(z))
}

function finden(t, muster) {
  const m = t.match(new RegExp(muster, 'i'))
  return m ? { m, rest: t.replace(m[0], ' ') } : { m: null, rest: t }
}

/** Anmelde- und Abmeldefrist aus dem Text eines Blocks; der Rest enthält nur noch den Termin selbst. */
function fristen(t) {
  let rest = t
  let von = null
  let bis = null
  let ab = null
  let r = finden(rest, String.raw`(?:Anmeldebeginn|Anmeldestart|Registration\s+start)\s*:?\s*${DATUM_ZEIT}`)
  if (r.m) [von, rest] = [iso(...r.m.slice(1, 6)), r.rest]
  r = finden(rest, String.raw`(?:Anmeldeende|Anmeldeschluss|Registration\s+(?:end|deadline))\s*:?\s*${DATUM_ZEIT}`)
  if (r.m) [bis, rest] = [iso(...r.m.slice(1, 6), '23:59'), r.rest]
  r = finden(
    rest,
    String.raw`(?:Anmelde(?:frist|zeitraum|zeit)|Anmeldung|Registration(?:\s+period)?)\s*:?\s*(von|from|ab|bis|until)?\s*${DATUM_ZEIT}` +
      String.raw`(?:\s*(?:-|–|bis|to|until)\s*${DATUM_ZEIT})?`,
  )
  if (r.m) {
    const nurEnde = /bis|until/i.test(r.m[1] || '')
    const erstes = iso(...r.m.slice(2, 7), nurEnde ? '23:59' : '00:00')
    if (nurEnde) bis ??= erstes
    else {
      von ??= erstes
      if (r.m[7]) bis ??= iso(...r.m.slice(7, 12), '23:59')
    }
    rest = r.rest
  }
  r = finden(rest, String.raw`(?:Abmelde(?:frist|ende|schluss)|Abmeldung|Deregistration(?:\s+deadline)?)\s*:?\s*(?:bis|until)?\s*${DATUM_ZEIT}`)
  if (r.m) [ab, rest] = [iso(...r.m.slice(1, 6), '23:59'), r.rest]
  return { anmeldung_von: von, anmeldung_bis: bis, abmeldung_bis: ab, rest }
}

// Spaltenköpfe und Wochentage, die vor dem Datum stehen können – gehören nicht zum Titel
const BESCHRIFTUNG = /^(Datum|Date|Zeit|Time|Uhrzeit|Ort|Location|Beginn|Ende|Mo|Di|Mi|Do|Fr|Sa|So|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?,?:?$/i

function titelAus(block, vorDatum) {
  const kopf = block.match(/<(\w+)\b[^>]*class="[^"]*groupHeader[^"]*"[^>]*>([\s\S]*?)<\/\1>/i)
  const roh = kopf ? text(kopf[2]) : vorDatum
  const titel = roh
    .replace(new RegExp(DATUM_ZEIT, 'g'), ' ')
    .replace(/\d{1,2}:\d{2}\s*(?:-|–)?\s*(?:\d{1,2}:\d{2})?/g, ' ')
    .split(/\s+/)
    .filter((w) => !BESCHRIFTUNG.test(w) && !/^[-–|,:]$/.test(w))
    .join(' ')
    .replace(/[\s,:–-]+$/, '')
    .trim()
  return titel.length >= 3 ? titel.slice(0, 120) : 'Prüfung'
}

const ANGEMELDET_TEXT = /Sie sind (?:zu dieser Prüfung |für diesen Termin |bereits )?angemeldet|bereits angemeldet|angemeldet seit|Status\s*:?\s*angemeldet\b|you are registered|already registered|registered since/i
const ABMELDEN_KNOPF = /(?:value="|>)\s*(?:Abmelden|Deregister|Unregister)\s*(?:"|<)/i

/** Ein Termin aus einem Block, oder null, wenn kein Prüfungsdatum darin steht. */
export function terminAusBlock(block, nummer) {
  const { anmeldung_von, anmeldung_bis, abmeldung_bis, rest } = fristen(text(block))
  const m = rest.match(new RegExp(String.raw`${DATUM}(?:\D{0,24}?(\d{1,2}):(\d{2}))?(?:\s*(?:Uhr)?\s*(?:-|–|bis)\s*(\d{1,2}):(\d{2}))?`))
  if (!m) return null
  const [, tag, monat, jahr, sh, sm, eh, em] = m
  const start = iso(tag, monat, jahr, sh, sm, '09:00')
  const ende = sh !== undefined && eh !== undefined ? iso(tag, monat, jahr, eh, em) : null
  const ort = rest.match(/(?:Ort|Location|Hörsaal|Raum)\s*:?\s*(.{2,80}?)(?=\s+(?:Anmeld|Abmeld|Prüfungs|Modus|Mode|Registration|Datum|Date|Zeit|Time|Termin|Teilnehm|Participants|Info|Anmerkung|Status|$)|$)/i)
  const kennung = block.match(/(?:examDate(?:Id)?|dateId|terminId)[\W_]{0,3}(\d{3,})/i)
  return {
    extern_id: kennung ? `tiss:${kennung[1]}` : `tiss:${nummer}:${start}`,
    titel: titelAus(block, rest.slice(0, m.index)),
    start,
    // Uhrzeit unbekannt: der Hub zeigt den Termin ganztägig
    ende: ende && ende > start ? ende : null,
    ort: ort ? ort[1].trim() : null,
    anmeldung_von,
    anmeldung_bis,
    abmeldung_bis,
    angemeldet: (ANGEMELDET_TEXT.test(text(block)) || ABMELDEN_KNOPF.test(block)) && !/nicht angemeldet|not registered/i.test(text(block)),
  }
}

/** Alle Termine einer Prüfungsliste (ohne Doppelte). */
export function pruefungenAusHtml(html, nummer) {
  const termine = new Map()
  for (const block of bloecke(html || '')) {
    const termin = terminAusBlock(block, nummer)
    if (termin && !termine.has(termin.extern_id)) termine.set(termin.extern_id, termin)
  }
  return [...termine.values()]
}

/** Keine Termine erkannt, ohne dass TISS ausdrücklich „keine Termine“ schreibt: lieber melden als still 0 Termine. */
export function istUnlesbar(html, termine) {
  return !termine.length && !KEINE_TERMINE.test(text(html))
}

// --- Seiten mit der TISS-Sitzung holen -------------------------------------------------------------
//
// TISS (DeltaSpike) liefert beim ersten Aufruf nur eine „Loading…“-Hülle: Ein Skript erzeugt eine Fenster-ID, legt
// sie im Cookie „dsrwid-<Token>“ ab und lädt die Seite mit ?dsrid=<Token>&dswid=<ID> neu. Ohne JavaScript bauen wir
// das nach; das Cookie setzt der Hintergrund über die cookies-Berechtigung (`cookieSetzen`).

export class TissNichtEingeloggt extends Error {
  constructor(meldung = 'Nicht in TISS eingeloggt – TISS im Browser öffnen und anmelden.') {
    super(meldung)
    this.name = 'TissNichtEingeloggt'
  }
}

/** Ziel der „Loading…“-Hülle (redirectUrl im Skript), sonst null. */
export function fensterUmleitung(html) {
  if (!/handleWindowId\s*\(/.test(html || '')) return null
  const m = html.match(/redirectUrl\s*=\s*'([^']*)'/)
  if (!m) return null
  return m[1].replace(/\\\//g, '/').replace(/\\x26/gi, '&').replace(/\\x3d/gi, '=').replace(/&amp;/g, '&')
}

const istLoginSeite = (url, html) =>
  !String(url || TISS).startsWith(TISS) || /Passwort vergessen|forgot (?:your )?password|name="j_username"|name="pw"/i.test(html)

/** Eine TISS-Seite wie im Browser holen (Fenster-ID-Handshake). null bei 404; wirft TissNichtEingeloggt. */
export async function tissSeite(url, { fetchFn = (...a) => fetch(...a), cookieSetzen, zufall = Math.random } = {}) {
  const holen = async (adresse) => {
    try {
      return await fetchFn(adresse, { credentials: 'include' })
    } catch {
      // Umleitung zum Login-Server (ohne Host-Berechtigung) scheitert im Hintergrund als Netzwerkfehler
      throw new TissNichtEingeloggt()
    }
  }
  let antwort = await holen(url)
  if (antwort.status === 404) return null
  if (!antwort.ok) throw new Error(`TISS antwortet mit HTTP ${antwort.status}`)
  let html = await antwort.text()
  const ziel = fensterUmleitung(html)
  if (ziel) {
    if (!cookieSetzen) throw new Error('TISS verlangt eine Fenster-ID, die Erweiterung darf aber keine Cookies setzen.')
    const token = String(Math.floor(zufall() * 999) + 1)
    const fenster = String(Math.floor(zufall() * 9000) + 1000)
    await cookieSetzen(`dsrwid-${token}`, fenster)
    const adresse = new URL(ziel, TISS)
    adresse.searchParams.set('dsrid', token)
    adresse.searchParams.set('dswid', fenster)
    antwort = await holen(adresse.href)
    if (!antwort.ok) throw new Error(`TISS antwortet mit HTTP ${antwort.status}`)
    html = await antwort.text()
    if (fensterUmleitung(html)) throw new Error('TISS hat die Fenster-ID nicht angenommen (Seite bleibt bei „Loading…“).')
  }
  if (istLoginSeite(antwort.url, html)) throw new TissNichtEingeloggt()
  return html
}

/** TISS-Prüfungslisten aller LVAs aus `lvas` (Hub: /api/pruefungen/abruf) lesen und an den Hub schicken. */
export async function tissPruefungenAbrufen({ hub, lvas, fetchFn, cookieSetzen }) {
  const daten = { quelle: 'tiss', lvas: [], fehler: [], unlesbar_html: null }
  lvas: for (const lva of lvas) {
    const termine = new Map()
    let vollstaendig = true
    for (const nummer of lva.nummern) {
      for (const semester of lva.semester) {
        try {
          const html = await tissSeite(pruefungsListeUrl(nummer, semester), { fetchFn, cookieSetzen })
          if (html === null) continue // LVA in diesem Semester nicht angeboten
          const liste = pruefungenAusHtml(html, nummer)
          if (istUnlesbar(html, liste)) {
            vollstaendig = false
            daten.fehler.push(`${lva.name} (${nummer}, ${semester}): keine Termine erkannt – Seite gespeichert zur Prüfung`)
            daten.unlesbar_html ??= html.slice(0, 150000)
          }
          liste.forEach((t) => termine.set(t.extern_id, t))
        } catch (fehler) {
          if (fehler instanceof TissNichtEingeloggt) {
            daten.fehler.push(fehler.message) // gilt für alle weiteren Seiten: abbrechen, nichts löschen
            break lvas
          }
          vollstaendig = false // ohne vollständige Liste löscht der Hub nichts
          daten.fehler.push(`${lva.name} (${nummer}, ${semester}): ${fehler.message}`)
        }
      }
    }
    daten.lvas.push({ lva_id: lva.lva_id, termine: [...termine.values()], vollstaendig })
  }
  const antwort = await hub.pruefungen(daten)
  return { status: daten.fehler.length ? 'teilweise' : 'ok', termine: daten.lvas.reduce((n, l) => n + l.termine.length, 0), ...antwort }
}

/** Eine einzelne, gerade geöffnete Prüfungsliste melden (nicht vollständig: der Hub löscht nichts). */
export async function tissListeMelden({ hub, html, url }) {
  const liste = listeAusUrl(url)
  if (!liste) return { status: 'keine-liste' }
  if (fensterUmleitung(html)) return { status: 'laedt' } // „Loading…“-Hülle; die echte Seite kommt gleich
  const { lvas } = await hub.pruefungenAbruf()
  const lva = lvas.find((l) => l.nummern.includes(liste.nummer))
  if (!lva) return { status: 'unbekannt', meldung: `LVA ${liste.nummer} wird im Hub nicht besucht.` }
  const termine = pruefungenAusHtml(html, liste.nummer)
  const antwort = await hub.pruefungen({ quelle: 'tiss', lvas: [{ lva_id: lva.lva_id, termine, vollstaendig: false }], fehler: [] })
  return { status: 'ok', termine: termine.length, ...antwort }
}

// --- TUWEL-Kalender ------------------------------------------------------------------------------

const PRUEFUNG_WORT = /prüfung|pruefung|klausur|\bexam|kolloquium|kurztest|zwischentest|teiltest|\btest\s*\d|\d\.\s*test\b|midterm/i
const KEINE_PRUEFUNG = /einsicht|besprechung|vorbereitung|anmeldung|registration|abgabe|übungsklausur|probeklausur|ergebnis|fragestunde|repetitorium|review/i

/** Ist ein Kalendereintrag eine Prüfung? Abgaben und das Schließen eines Tests zählen nicht. */
export function istPruefungsEreignis(ereignis) {
  const name = ereignis.name || ''
  if (!PRUEFUNG_WORT.test(name) || KEINE_PRUEFUNG.test(name)) return false
  if (ereignis.modulename === 'assign' || ['close', 'due', 'gradingdue'].includes(ereignis.eventtype)) return false
  return !/\b(schließt|closes|fällig|due)\b/i.test(name)
}

/** Unix-Zeit als lokale Wiener Zeit ohne Zeitzone (so speichert der Hub). */
export function wienIso(sekunden) {
  const teile = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Europe/Vienna', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    })
      .formatToParts(new Date(sekunden * 1000))
      .map((p) => [p.type, p.value]),
  )
  return `${teile.year}-${teile.month}-${teile.day}T${teile.hour}:${teile.minute}:00`
}

/** Alle Einträge aus Monatsansichten (core_calendar_get_calendar_monthly_view), ohne Doppelte. */
export function monatsEreignisse(monate) {
  const ereignisse = new Map()
  for (const monat of monate) {
    for (const woche of monat?.weeks || []) {
      for (const tag of woche.days || []) for (const e of tag.events || []) ereignisse.set(e.id, e)
    }
  }
  return [...ereignisse.values()]
}

/** Prüfungen aus dem Kalender je LVA (Zuordnung über die TUWEL-Kurse aus dem Abruf). */
export function tuwelPruefungen(ereignisse, lvas) {
  const lvaNachKurs = new Map(lvas.flatMap((l) => l.tuwel_kurse.map((k) => [k, l.lva_id])))
  const jeLva = new Map(lvas.filter((l) => l.tuwel_kurse.length).map((l) => [l.lva_id, []]))
  for (const e of ereignisse) {
    const lvaId = lvaNachKurs.get(e.course?.id ?? e.courseid)
    if (!lvaId || !istPruefungsEreignis(e)) continue
    jeLva.get(lvaId).push({
      extern_id: `tuwel:${e.id}`,
      titel: (e.name || '').replace(/\s*\(?(?:öffnet|opens|beginnt)\)?\s*$/i, '').trim() || 'Prüfung',
      start: wienIso(e.timestart),
      ende: e.timeduration > 0 ? wienIso(e.timestart + e.timeduration) : null,
      ort: e.location || null,
      angemeldet: false,
    })
  }
  return [...jeLva.entries()].map(([lva_id, termine]) => ({ lva_id, termine, vollstaendig: true }))
}

/** Monate um heute: einer zurück, acht voraus (Prüfungen des Semesters und der Nachtermine). */
export function monateUm(heute = new Date(), zurueck = 1, voraus = 8) {
  const monate = []
  for (let i = -zurueck; i <= voraus; i++) {
    const d = new Date(heute.getFullYear(), heute.getMonth() + i, 1)
    monate.push({ jahr: d.getFullYear(), monat: d.getMonth() + 1 })
  }
  return monate
}

/** TUWEL-Kalender (mit der Browser-Sitzung) lesen und die Prüfungen an den Hub schicken. */
export async function tuwelPruefungenAbrufen({ hub, tuwel, lvas, heute = new Date() }) {
  const mitKurs = lvas.filter((l) => l.tuwel_kurse.length)
  if (!mitKurs.length) return { status: 'ok', termine: 0 }
  const monate = []
  const fehler = []
  for (const { jahr, monat } of monateUm(heute)) {
    try {
      monate.push(await tuwel.kalenderMonat(jahr, monat))
    } catch (f) {
      if (f instanceof NichtEingeloggt) throw f
      fehler.push(`TUWEL-Kalender ${monat}/${jahr}: ${f.message}`)
    }
  }
  // fehlt ein Monat, ist die Liste nicht vollständig: der Hub löscht dann nichts
  const lvasDaten = tuwelPruefungen(monatsEreignisse(monate), mitKurs).map((l) => ({ ...l, vollstaendig: !fehler.length }))
  const antwort = await hub.pruefungen({ quelle: 'tuwel', lvas: lvasDaten, fehler })
  return { status: fehler.length ? 'teilweise' : 'ok', termine: lvasDaten.reduce((n, l) => n + l.termine.length, 0), ...antwort }
}
