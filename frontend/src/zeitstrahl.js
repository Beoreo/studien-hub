// Zeitstrahl, dessen Maßstab sich den Abständen anpasst (reine Logik, mit node --test geprüft).
//
// Linear wären drei Tage zwischen zwei Prüfungen neben drei Monaten bis zur nächsten unlesbar. Deshalb wächst jeder
// Abschnitt nur mit der Wurzel der Tage, und jeder bekommt mindestens einen festen Teil der Länge – nahe Termine
// liegen so nie übereinander, ferne bleiben sichtbar weiter weg. Die echten Abstände stehen als Beschriftung dran.

const TAG_MS = 24 * 60 * 60 * 1000

/** Fortlaufende Tagesnummer (lokales Datum, unabhängig von Uhrzeit und Sommerzeit). */
export function tagNummer(datum) {
  return Math.round(Date.UTC(datum.getFullYear(), datum.getMonth(), datum.getDate()) / TAG_MS)
}

/** Anteile proportional zu `gewichte`, aber jeder mindestens `mindest`; Summe 1. */
export function anteileMitMindest(gewichte, mindest) {
  const fest = new Set()
  for (;;) {
    const frei = gewichte.reduce((s, g, i) => (fest.has(i) ? s : s + g), 0)
    const rest = 1 - fest.size * mindest
    const anteile = gewichte.map((g, i) => (fest.has(i) ? mindest : frei > 0 ? (rest * g) / frei : rest / (gewichte.length - fest.size)))
    const zuKlein = anteile.map((a, i) => !fest.has(i) && a < mindest - 1e-12)
    if (!zuKlein.some(Boolean)) return anteile
    zuKlein.forEach((klein, i) => klein && fest.add(i))
  }
}

/**
 * Einträge ({ datum: Date, … }) auf dem Zeitstrahl. Einträge am selben Tag teilen sich einen Punkt.
 * Ergebnis: { punkte: [{ tag: Date, pos (0–1), eintraege }], abschnitte: [{ tage, mitte (0–1) }] }.
 * `minAnteil`: so viel der Länge wird gleichmäßig auf die Abschnitte verteilt (Rest nach Wurzel der Tage).
 */
export function zeitstrahl(eintraege, { minAnteil = 0.6 } = {}) {
  const jeTag = new Map()
  for (const e of eintraege) {
    const n = tagNummer(e.datum)
    if (!jeTag.has(n)) jeTag.set(n, { tag: new Date(e.datum.getFullYear(), e.datum.getMonth(), e.datum.getDate()), eintraege: [] })
    jeTag.get(n).eintraege.push(e)
  }
  const tage = [...jeTag.keys()].sort((a, b) => a - b)
  if (tage.length === 0) return { punkte: [], abschnitte: [] }
  if (tage.length === 1) return { punkte: [{ ...jeTag.get(tage[0]), pos: 0.5 }], abschnitte: [] }

  const luecken = tage.slice(1).map((t, i) => t - tage[i])
  const anteile = anteileMitMindest(luecken.map(Math.sqrt), minAnteil / luecken.length)
  const punkte = []
  const abschnitte = []
  let pos = 0
  tage.forEach((t, i) => {
    punkte.push({ ...jeTag.get(t), pos })
    if (i < luecken.length) {
      abschnitte.push({ tage: luecken[i], mitte: pos + anteile[i] / 2 })
      pos += anteile[i]
    }
  })
  punkte[punkte.length - 1].pos = 1 // Rundungsfehler
  return { punkte, abschnitte }
}

/** „1 Tag“, „12 Tage“, „3 Wo.“, „4 Mon.“ */
export function abstandText(tage) {
  if (tage === 1) return '1 Tag'
  if (tage < 21) return `${tage} Tage`
  if (tage < 63) return `${Math.round(tage / 7)} Wo.`
  return `${Math.round(tage / 30.44)} Mon.`
}
