// STEOP-Status aus TISS (Lehre → LVA Cockpit → STEOP Status) – reine Textauswertung, ohne DOM, mit node testbar.
//
// Die Seite hat eine Tabelle „Studium | Abgeschlossen | Erlaubte Non-STEOP ECTS“; der Status steht nur als
// Symbol da. Welches Symbol was bedeutet, sagt die Legende darunter. Deshalb wird jedes Symbol über seine
// Kennung (Bilddatei, CSS-Klasse oder Titel) mit der Legende abgeglichen; Schlüsselwörter sind nur Rückfall.
// Die „Detailansicht offener STEOPs“ nennt die LVAs der noch offenen STEOP-Bedingungen.

export const TISS = 'https://tiss.tuwien.ac.at'

const LVA_NUMMER = /\b(\d{3}\.[0-9A-Z]{3})\b/g
const SYMBOL = /<img\b[^>]*>|<(?:i|span|em|div)\b[^>]*class="[^"]*(?:icon|fa-|fa |glyph|status|check|cross|tick)[^"]*"[^>]*>/gi

const text = (html) =>
  (html || '')
    .replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()

const attribut = (tag, name) => (tag.match(new RegExp(`\\b${name}="([^"]*)"`, 'i')) || [])[1] || ''

/** Kennung eines Symbols: Bilddatei, sonst CSS-Klasse, sonst Titel/Alt-Text. */
export function symbolKennung(tag) {
  const src = attribut(tag, 'src')
  if (src) return `bild:${src.split(/[?#]/)[0].split('/').pop().toLowerCase()}`
  const klasse = attribut(tag, 'class')
  if (klasse) return `klasse:${klasse.toLowerCase().split(/\s+/).sort().join(' ')}`
  return `titel:${(attribut(tag, 'title') || attribut(tag, 'alt')).toLowerCase()}`
}

function bedeutung(beschriftung) {
  const t = (beschriftung || '').toLowerCase()
  if (/nicht abgeschlossen|not completed|offen|open/.test(t)) return 'offen'
  if (/ausgenommen|whitelist|exempt/.test(t)) return 'ausgenommen'
  if (/abgeschlossen|completed|erfüllt|fulfilled/.test(t)) return 'abgeschlossen'
  return null
}

function bedeutungAusSymbol(tag) {
  const datei = attribut(tag, 'src').split(/[?#]/)[0].split('/').pop()
  const merkmale = [attribut(tag, 'alt'), attribut(tag, 'title'), attribut(tag, 'class'), datei].join(' ').toLowerCase()
  return (
    bedeutung(merkmale) ||
    (/cross|delete|error|false|remove|times|nok/.test(merkmale) && 'offen') ||
    (/flash|lightning|bolt|white|star/.test(merkmale) && 'ausgenommen') ||
    (/check|tick|true|ok|green|done|success/.test(merkmale) && 'abgeschlossen') ||
    null
  )
}

/** Legende: Kennung jedes Symbols -> Bedeutung, aus dem Text, der dem Symbol folgt. */
export function legendeLesen(html) {
  const start = html.search(/>\s*Legende\s*</i)
  if (start < 0) return new Map()
  const ende = html.slice(start).search(/Detailansicht|<\/form>|<footer/i)
  const abschnitt = html.slice(start, ende > 0 ? start + ende : undefined)
  const symbole = [...abschnitt.matchAll(SYMBOL)]
  const legende = new Map()
  symbole.forEach((m, i) => {
    const bis = i + 1 < symbole.length ? symbole[i + 1].index : abschnitt.length
    const sinn = bedeutung(text(abschnitt.slice(m.index + m[0].length, bis)))
    if (sinn) legende.set(symbolKennung(m[0]), sinn)
  })
  return legende
}

function statusAusZelle(zelle, legende) {
  const symbol = (zelle.match(SYMBOL) || [])[0]
  if (symbol) return legende.get(symbolKennung(symbol)) || bedeutungAusSymbol(symbol)
  return bedeutung(text(zelle)) // Status als Text statt Symbol
}

/** Ist das die STEOP-Statusseite? */
export function istSteopSeite(html) {
  return /STEOP\s*Status/i.test(html) && /Non-STEOP|STEOP-Bedingung|Abgeschlossen/i.test(html)
}

/**
 * Wertet die STEOP-Statusseite aus. Ergebnis:
 * { studien: [{ studium, status: 'abgeschlossen'|'ausgenommen'|'offen'|null, erlaubte_ects }],
 *   abgeschlossen: bool|null, erlaubte_ects: number|null, steop_nummern: [...] }
 * `abgeschlossen` ist null, wenn kein Status sicher erkannt wurde.
 */
export function steopAusHtml(html) {
  if (!istSteopSeite(html)) return null
  const legende = legendeLesen(html)
  const tabellen = [...html.matchAll(/<table\b[\s\S]*?<\/table>/gi)].map((m) => m[0])
  const tabelle = tabellen.find((t) => /Non-STEOP/i.test(t)) || tabellen.find((t) => /Studium/i.test(t) && /Abgeschlossen/i.test(t))
  const studien = []
  for (const zeile of (tabelle || '').match(/<tr\b[\s\S]*?<\/tr>/gi) || []) {
    const zellen = zeile.match(/<td\b[\s\S]*?<\/td>/gi)
    if (!zellen || zellen.length < 2) continue // Kopfzeile mit <th>
    const ects = text(zellen[2] || '').replace(',', '.').match(/\d+(\.\d+)?/)
    studien.push({
      studium: text(zellen[0]),
      status: statusAusZelle(zellen[1], legende),
      erlaubte_ects: ects ? Number(ects[0]) : null,
    })
  }

  const detail = html.search(/Detailansicht offener STEOPs?/i)
  const nummern = detail >= 0 ? [...new Set([...text(html.slice(detail)).matchAll(LVA_NUMMER)].map((m) => m[1]))] : []
  const bedingung = detail >= 0 ? text(html.slice(detail)).match(/STEOP-Bedingung:?\s*([^]*?)(?=\bP\d+\s*:|$)/i) : null

  const erkannt = studien.length > 0 && studien.every((s) => s.status)
  const ects = studien.map((s) => s.erlaubte_ects).filter((e) => e !== null)
  return {
    studien,
    abgeschlossen: erkannt ? studien.every((s) => s.status !== 'offen') : null,
    erlaubte_ects: ects.length ? Math.min(...ects) : null,
    steop_nummern: nummern,
    kriterien: detail >= 0 ? kriterienLesen(html.slice(detail), legende) : [],
    // Rohfassung der Detailansicht (bleibt lokal im Hub): zum Prüfen, falls TISS den Aufbau ändert
    detail_html: detail >= 0 ? html.slice(detail, detail + 150000) : null,
    verknuepfung: bedingung && /\bOR\b|\bODER\b/i.test(bedingung[1]) && !/\bAND\b|\bUND\b/i.test(bedingung[1]) ? 'OR' : 'AND',
  }
}

// --- Kriterien der offenen STEOPs ---------------------------------------------------------------------
//
// Die Detailansicht ist ein Baum, z. B. „P4: 9 ECTS aus:“ → „1 aus:“ (LVAs), „1 aus:“ (LVAs), „Alle aus:“ (LVAs).
// Die Verschachtelung ergibt sich aus der Tiefe der Block-Elemente; stehen alle Knoten auf gleicher Tiefe
// (flache Tabelle), gilt: P-Kriterien oben, Kriterien ohne P-Namen darunter, LVAs beim letzten Kriterium.

const BLOCK = new Set(['div', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'p', 'section',
  'fieldset', 'dl', 'dt', 'dd', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'details', 'summary'])
const KRITERIUM = /(?:\b(P\d+)\s*:\s*)?(?:(\d+(?:[.,]\d+)?)\s*ECTS|(\d+)|(Alle|all))\s+(?:aus|of)\s*:/gi
const SYMBOL_MARKE = '\u0001'

/** HTML -> Text mit Tiefe je Zeichen und Symbolen als Marken (für die Zuordnung von Status zu Knoten).
 *  `zeilen` sind die Grenzen von Zeilen (Block-Elemente außer Tabellenzellen: eine Tabellenzeile = eine Zeile). */
function textMitTiefe(html) {
  let t = ''
  const tiefen = [] // [Startposition im Text, Tiefe]
  const symbole = [] // [Position im Text, Kennung, Tag]
  const grenzen = [] // Positionen der Block-Elemente (Zeilen-/Zellgrenzen)
  const zeilen = [] // Positionen der Zeilengrenzen
  let tiefe = 0
  let kopfzelle = 0 // Text in <th> ist Spaltenkopf, keine LVA
  const anhaengen = (s) => {
    if (!s) return
    if (!tiefen.length || tiefen[tiefen.length - 1][1] !== tiefe) tiefen.push([t.length, tiefe])
    t += s
  }
  const teile = html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>|<!--[\s\S]*?-->/gi, ' ').split(/(<[^>]+>)/)
  for (const teil of teile) {
    if (!teil.startsWith('<')) {
      if (!kopfzelle) anhaengen(teil.replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/\s+/g, ' '))
      continue
    }
    if (/^<th\b/i.test(teil)) kopfzelle += 1
    if (/^<\/th\b/i.test(teil)) kopfzelle = Math.max(0, kopfzelle - 1)
    if (SYMBOL.test(teil)) {
      SYMBOL.lastIndex = 0
      symbole.push([t.length, symbolKennung(teil), teil])
      anhaengen(SYMBOL_MARKE)
    }
    SYMBOL.lastIndex = 0
    const name = (teil.match(/^<\/?([a-z0-9]+)/i) || [])[1]?.toLowerCase()
    if (!BLOCK.has(name)) continue
    if (teil.startsWith('</')) tiefe = Math.max(0, tiefe - 1)
    else if (!teil.endsWith('/>')) tiefe += 1
    grenzen.push(t.length)
    if (name !== 'td' && name !== 'th') zeilen.push(t.length)
    anhaengen(' ')
  }
  zeilen.push(t.length)
  const tiefeBei = (pos) => {
    let ergebnis = 0
    for (const [start, d] of tiefen) {
      if (start > pos) break
      ergebnis = d
    }
    return ergebnis
  }
  return { t, tiefeBei, symbole, grenzen, zeilen }
}

// Zeilen, die sicher keine LVA sind (Überschriften, Studium, Bedingung, Legende)
const KEINE_LVA = /STEOP-Bedingung|Detailansicht|Legende|^\d{6}\b|^(LVA|Titel|Typ|ECTS|Semester|Status|Nr\.?|Nummer|\s)+$/i

function erfuelltAus(symbole, von, bis, legende) {
  const symbol = symbole.find(([pos]) => pos >= von && pos < bis)
  if (!symbol) return null
  const sinn = legende.get(symbol[1]) || bedeutungAusSymbol(symbol[2])
  return sinn === 'offen' ? false : sinn ? true : null
}

/** Baum der STEOP-Kriterien: [{ name, art: 'ects'|'anzahl'|'alle', wert, erfuellt, kinder: [Knoten | LVA] }],
 *  LVA = { art: 'lva', nummer (oder null, wenn TISS nur den Titel zeigt), titel, ects, erfuellt }.
 *  Jede Textzeile unter einem Kriterium ist eine LVA. `erfuellt` null = kein Symbol erkannt. */
export function kriterienLesen(html, legende = new Map()) {
  const { t, tiefeBei, symbole, grenzen, zeilen } = textMitTiefe(html)
  const marken = []
  for (const m of t.matchAll(KRITERIUM)) {
    marken.push({
      pos: m.index, ende: m.index + m[0].length, tiefe: tiefeBei(m.index), name: m[1] || null,
      art: m[2] ? 'ects' : m[3] ? 'anzahl' : 'alle', wert: m[2] ? Number(m[2].replace(',', '.')) : m[3] ? Number(m[3]) : null,
    })
  }
  const kriterien = [...marken]
  for (let z = 0; z + 1 < zeilen.length; z++) {
    const [von, bis] = [zeilen[z], zeilen[z + 1]]
    if (kriterien.some((k) => k.pos < bis && k.ende > von)) continue // Zeile des Kriteriums selbst
    const inhalt = t.slice(von, bis).replaceAll(SYMBOL_MARKE, ' ').replace(/\s+/g, ' ').trim()
    if (inhalt.length < 3 || KEINE_LVA.test(inhalt)) continue
    const start = von + t.slice(von, bis).search(/[^\s\u0001]/)
    marken.push({ pos: start, ende: start, zeilenende: bis, tiefe: tiefeBei(start), art: 'lva', inhalt })
  }
  marken.sort((a, b) => a.pos - b.pos)

  const wurzel = []
  const stapel = []
  marken.forEach((marke, i) => {
    const bis = i + 1 < marken.length ? marken[i + 1].pos : t.length
    if (marke.art === 'lva') {
      // Status-Symbol irgendwo in der Zeile (auch vor dem Titel)
      const erfuellt = erfuelltAus(symbole, Math.max(...zeilen.filter((g) => g <= marke.pos)), marke.zeilenende, legende)
      const nummer = (marke.inhalt.match(LVA_NUMMER) || [])[0] || null
      // ECTS: „4,0 ECTS“ oder eine eigene Spalte „4,0“ (Dezimalzahl, die nicht zur Nummer gehört)
      const ohneNummer = marke.inhalt.replace(LVA_NUMMER, ' ')
      const ectsMuster = /\(?\s*(\d+(?:[.,]\d+)?)\s*ECTS\s*\)?/i.test(ohneNummer) ? /\(?\s*(\d+(?:[.,]\d+)?)\s*ECTS\s*\)?/i : /(?:^|\s)(\d{1,2}[.,]\d)(?=\s|$)/
      const ects = ohneNummer.match(ectsMuster)
      const titel = ohneNummer.replace(ectsMuster, ' ')
        .replace(/^[-–•·*\s]+/, '').replace(/\s+/g, ' ').trim().slice(0, 120)
      while (stapel.length && marke.tiefe < stapel[stapel.length - 1].tiefe) stapel.pop()
      const eltern = stapel[stapel.length - 1]
      if (!eltern || !titel && !nummer) return // Zeile ohne Kriterium (z. B. Überschrift): ignorieren
      const doppelt = eltern.knoten.kinder.some((k) => k.art === 'lva' && (nummer ? k.nummer === nummer : k.titel === titel))
      if (!doppelt) {
        eltern.knoten.kinder.push({ art: 'lva', nummer, titel, ects: ects ? Number(ects[1].replace(',', '.')) : null, erfuellt })
      }
      return
    }
    // Status-Symbol eines Kriteriums: nur direkt beim Text, nicht bei den Kindern
    const zeile = Math.max(i ? marken[i - 1].pos : 0, ...grenzen.filter((g) => g <= marke.pos))
    const erfuellt = erfuelltAus(symbole, zeile, Math.min(bis, ...grenzen.filter((g) => g >= marke.ende)), legende)
    const knoten = { name: marke.name, art: marke.art, wert: marke.wert, erfuellt, kinder: [] }
    if (marke.name) stapel.length = 0 // P-Kriterien stehen oben
    while (stapel.length) {
      const oben = stapel[stapel.length - 1]
      const tiefer = marke.tiefe > oben.tiefe
      const unterP = marke.tiefe === oben.tiefe && oben.knoten.name && !marke.name
      if (tiefer || unterP) break
      stapel.pop()
    }
    const eltern = stapel[stapel.length - 1]
    ;(eltern ? eltern.knoten.kinder : wurzel).push(knoten)
    stapel.push({ knoten, tiefe: marke.tiefe })
  })
  return wurzel
}
