// Reine Hilfsfunktionen ohne Browser-APIs – mit `node --test` testbar.

export const TUWEL = 'https://tuwel.tuwien.ac.at'

const VIDEO_URL =
  /(youtube\.com|youtu\.be|vimeo\.com|lecturetube|opencast|panopto|zoom\.us\/rec|\.(mp4|m4v|webm|mov|mkv|avi|wmv|m3u8)(\?|#|$))/i
const VIDEO_MODUL = /opencast|video|lecturetube|panopto|kaltura/i
const VIDEO_ENDUNG = /\.(mp4|m4v|webm|mov|mkv|avi|wmv|m3u8)$/i
const BILD_ENDUNG = /\.(png|jpe?g|gif|svg|webp|bmp|ico)$/i
// Module, deren Ansichtsseite Dateien verlinkt (Ordner, Aufgabenblätter, Textseiten)
const SEITEN_MIT_DATEIEN = new Set(['folder', 'assign', 'page', 'book'])

export class NichtEingeloggt extends Error {
  constructor(meldung = 'Nicht in TUWEL eingeloggt – bitte TUWEL im Browser öffnen und anmelden.') {
    super(meldung)
    this.name = 'NichtEingeloggt'
  }
}

/** Liest den Sitzungsschlüssel (sesskey) aus dem Seitenquelltext einer TUWEL-Seite. */
export function sesskeyAusHtml(html) {
  const treffer = html.match(/"sesskey":"([^"]+)"/)
  return treffer ? treffer[1] : null
}

/** Erkennt, ob TUWEL auf die Anmeldung umgeleitet hat. */
export function istLoginSeite(url, html = '') {
  return /\/login\/|idp\.|shibboleth|saml/i.test(url) || (!sesskeyAusHtml(html) && /id="login"|name="username"/.test(html))
}

export function istVideoUrl(url) {
  return VIDEO_URL.test(url || '')
}

export function ohneAbfrage(url) {
  return url.split(/[?#]/)[0]
}

/** Dateiname und Unterordner aus einer pluginfile-URL: …/pluginfile.php/<ctx>/<komp>/<bereich>/<item>/<pfad> */
export function dateiInfoAusUrl(url) {
  const pfad = ohneAbfrage(url)
  const teile = pfad.split('/pluginfile.php/')[1]?.split('/') ?? [pfad.split('/').pop()]
  // ctx, komponente, bereich, itemid, …rest
  const rest = teile.length > 4 ? teile.slice(4) : teile.slice(-1)
  const entschluesselt = rest.map((t) => {
    try {
      return decodeURIComponent(t)
    } catch {
      return t
    }
  })
  return { dateiname: entschluesselt.at(-1) || 'datei', unterordner: entschluesselt.slice(0, -1).join('/') }
}

/** Alle Dateilinks (pluginfile) einer Aktivitätsseite; Bilder nur aus Ordnern/Dateiressourcen. */
export function pluginfileLinks(html, basis = TUWEL) {
  const muster = /(?:https?:\/\/[^"'\s<>]+)?\/pluginfile\.php\/\d+\/(mod_[a-z0-9]+)\/[a-z0-9_]+\/\d+\/[^"'\s<>]+/gi
  const gefunden = new Map()
  for (const treffer of html.matchAll(muster)) {
    let url = treffer[0].replace(/&amp;/g, '&')
    if (url.startsWith('/')) url = basis + url
    url = ohneAbfrage(url)
    const komponente = treffer[1].toLowerCase()
    const { dateiname, unterordner } = dateiInfoAusUrl(url)
    if (BILD_ENDUNG.test(dateiname) && !['mod_folder', 'mod_resource'].includes(komponente)) continue
    if (!gefunden.has(url)) gefunden.set(url, { url, komponente, dateiname, unterordner })
  }
  return [...gefunden.values()]
}

/** Externe Ziel-URL einer „Link/URL“-Aktivität (Weiterleitung oder Hinweisseite). */
export function zielDerUrlAktivitaet(endUrl, html, basis = TUWEL) {
  if (endUrl && !endUrl.startsWith(basis)) return endUrl
  const treffer =
    html.match(/class="urlworkaround"[\s\S]*?href="([^"]+)"/) || html.match(/<div[^>]+class="[^"]*urlworkaround[^"]*"[\s\S]*?<a[^>]+href="([^"]+)"/)
  return treffer ? treffer[1].replace(/&amp;/g, '&') : null
}

/** Wertet die Antwort von core_courseformat_get_state aus (Abschnitte und Aktivitäten eines Kurses). */
export function zustandLesen(zustand) {
  const daten = typeof zustand === 'string' ? JSON.parse(zustand) : zustand
  const abschnitte = new Map()
  for (const s of daten.section || []) {
    abschnitte.set(String(s.id), s.title || s.name || (s.number != null ? `Abschnitt ${s.number}` : ''))
  }
  const aktivitaeten = (daten.cm || [])
    .filter((cm) => cm.uservisible !== false)
    .map((cm) => ({
      cmId: Number(cm.id),
      name: cm.name || '',
      modul: cm.module || cm.modname || '',
      url: cm.url || null,
      abschnitt: abschnitte.get(String(cm.sectionid)) || '',
    }))
  return { abschnitte, aktivitaeten }
}

/** Wie eine Aktivität behandelt wird: 'video', 'datei' (Ressource), 'seite' (Dateien auf der Seite), 'link' oder null. */
export function klassifiziere(aktivitaet) {
  const modul = (aktivitaet.modul || '').toLowerCase()
  if (VIDEO_MODUL.test(modul)) return 'video'
  if (modul === 'resource') return 'datei'
  if (modul === 'url') return 'link'
  if (SEITEN_MIT_DATEIEN.has(modul)) return 'seite'
  return null
}

export function istVideoDatei(dateiname, inhaltstyp = '') {
  return VIDEO_ENDUNG.test(dateiname) || /^video\//i.test(inhaltstyp)
}

/** Dateiname aus Content-Disposition, falls vorhanden. */
export function dateinameAusKopf(contentDisposition) {
  if (!contentDisposition) return null
  const utf8 = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].trim().replace(/"/g, ''))
    } catch {
      /* weiter mit einfacher Form */
    }
  }
  const einfach = contentDisposition.match(/filename="?([^";]+)"?/i)
  return einfach ? einfach[1].trim() : null
}
