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

/**
 * Wie eine Aktivität behandelt wird: 'opencast' (LectureTube-Serie oder -Episode), 'video',
 * 'datei' (Ressource), 'seite' (Dateien auf der Seite), 'link' oder null.
 */
export function klassifiziere(aktivitaet) {
  const modul = (aktivitaet.modul || '').toLowerCase()
  if (modul === 'opencast') return 'opencast'
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

// --- LectureTube (Moodle-Plugin mod_opencast) ----------------------------------------------
// TUWEL holt die Episoden serverseitig von Opencast und rendert sie in die Seite:
//   Serie:   <li class="episode" title="…"><a href="…view.php?id=…&e=<id>">… <span class="duration">1:23:45</span>
//            <div class="title">…</div><span class="date">13.10.2026</span></a></li>
//            oder (Listenansicht) eine Tabelle mit den Spalten Titel (Link), Dauer, Datum
//   Episode: <script>window.episode = {"metadata":{"id","title","duration",…},"streams":[…]}</script>

const DAUER = /^\d{1,3}:\d{2}(?::\d{2})?$/
const DATUM = /\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.?\s+[A-Za-zÄÖÜäöüß]+\.?\s+\d{4}\b/

function text(html) {
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim()
}

function absolut(url, basis) {
  const sauber = url.replace(/&amp;/g, '&')
  return sauber.startsWith('http') ? sauber : basis + (sauber.startsWith('/') ? '' : '/mod/opencast/') + sauber
}

/** Liest alle Episoden einer LectureTube-Serienseite (Kachel- und Listenansicht). */
export function opencastSerie(html, basis = TUWEL) {
  const bloecke = [
    ...[...html.matchAll(/<li[^>]*class="[^"]*\bepisode\b[^"]*"[^>]*>([\s\S]*?)<\/li>/g)].map((m) => ({ form: 'kacheln', html: m[0] })),
    ...[...html.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)].map((m) => ({ form: 'tabelle', html: m[0] })),
  ]
  const episoden = new Map()
  for (const block of bloecke) {
    const link = block.html.match(/href="([^"]*opencast\/view\.php\?[^"]*?\b(?:amp;)?e=([A-Za-z0-9_-]+)[^"]*)"/)
    if (!link) continue
    const id = link[2]
    if (episoden.has(id)) continue
    const titel =
      block.html.match(/class="title"[^>]*>([\s\S]*?)<\/div>/)?.[1] ??
      block.html.match(/<li[^>]*\btitle="([^"]*)"/)?.[1] ??
      block.html.match(/<a[^>]*href="[^"]*e=[^"]*"[^>]*>([\s\S]*?)<\/a>/)?.[1] ??
      ''
    const zellen = [...block.html.matchAll(/<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/g)].map((z) => text(z[1]))
    const dauer = text(block.html.match(/class="duration"[^>]*>([\s\S]*?)<\//)?.[1] ?? '') || zellen.find((z) => DAUER.test(z)) || ''
    const datum =
      text(block.html.match(/class="date"[^>]*>([\s\S]*?)<\//)?.[1] ?? '') || zellen.find((z) => DATUM.test(z) && !DAUER.test(z)) || ''
    episoden.set(id, {
      episodeId: id,
      url: absolut(link[1], basis),
      titel: text(titel),
      dauerText: DAUER.test(dauer) ? dauer : '',
      datumText: datum,
      form: block.form,
    })
  }
  return [...episoden.values()]
}

/** Liest window.episode einer Episodenseite: Titel, Dauer in Sekunden und direkte Medien-URLs. */
export function opencastEpisode(html) {
  const start = html.indexOf('window.episode')
  if (start < 0) return null
  const json = jsonAb(html, html.indexOf('{', start))
  if (!json) return null
  let daten
  try {
    daten = JSON.parse(json)
  } catch {
    return null
  }
  const meta = daten.metadata || {}
  const medien = []
  for (const stream of daten.streams || []) {
    for (const [art, quellen] of Object.entries(stream.sources || {})) {
      for (const q of quellen || []) {
        if (q?.src) medien.push({ src: q.src, art, inhalt: stream.content || '', breite: q.res?.w || 0, hoehe: q.res?.h || 0 })
      }
    }
  }
  // bevorzugt: MP4 der Präsentation bzw. des Vortragenden in höchster Auflösung, sonst HLS
  medien.sort((a, b) => (a.art === 'mp4' ? 0 : 1) - (b.art === 'mp4' ? 0 : 1) || b.breite * b.hoehe - a.breite * a.hoehe)
  const dauer = Number(meta.duration)
  return {
    episodeId: meta.id ? String(meta.id) : null,
    titel: meta.title || '',
    // Paella erwartet Sekunden; sehr große Werte sind Millisekunden aus Opencast
    dauerSekunden: Number.isFinite(dauer) && dauer > 0 ? Math.round(dauer > 100000 ? dauer / 1000 : dauer) : null,
    medienUrl: medien[0]?.src || null,
    medienDomains: [...new Set(medien.map((m) => domain(m.src)).filter(Boolean))],
  }
}

/** Schneidet ein JSON-Objekt ab Position `start` aus (Klammern zählen, Zeichenketten beachten). */
function jsonAb(text, start) {
  if (start < 0) return null
  let tiefe = 0
  let inString = false
  for (let i = start; i < text.length; i++) {
    const z = text[i]
    if (inString) {
      if (z === '\\') i++
      else if (z === '"') inString = false
    } else if (z === '"') inString = true
    else if (z === '{') tiefe++
    else if (z === '}' && --tiefe === 0) return text.slice(start, i + 1)
  }
  return null
}

export function domain(url) {
  try {
    return new URL(url).hostname
  } catch {
    return null
  }
}

/**
 * Kurzbeschreibung einer Videoseite, falls sie keine bekannte Struktur hat: eingebettete
 * Frames, Formulare (LTI-Start) und externe Domains – damit sich neue Quellen nachrüsten lassen.
 */
export function seitenAnalyse(html, basis = TUWEL) {
  const eigen = domain(basis)
  const iframes = [...html.matchAll(/<iframe[^>]+src="([^"]+)"/g)].map((m) => domain(absolut(m[1], basis))).filter(Boolean)
  const lti = /lti_message_type|launch_presentation|oauth_consumer_key|mod\/lti\//i.test(html)
  const externe = [...html.matchAll(/(?:src|href|action)="(https?:\/\/[^"]+)"/g)]
    .map((m) => domain(m[1]))
    .filter((d) => d && d !== eigen)
  return { iframes: [...new Set(iframes)], lti, domains: [...new Set(externe)].slice(0, 10) }
}

// --- Erscheinungsdatum ------------------------------------------------------------------------

/**
 * Antwort von core_course_get_updates_since auswerten: je Aktivität (cmId) die Unix-Zeit der
 * neuesten Datei (Inhalt, Aufgaben-Anhänge, Beschreibung) und der letzten Einstellungsänderung.
 */
export function aenderungenLesen(daten) {
  const ergebnis = new Map()
  for (const instanz of daten?.instances || []) {
    if (instanz.contextlevel !== 'module') continue
    const zeiten = Object.fromEntries((instanz.updates || []).map((u) => [u.name, Number(u.timeupdated) || null]))
    const dateien = zeiten.contentfiles ?? zeiten.introattachmentfiles ?? zeiten.introfiles ?? null
    ergebnis.set(Number(instanz.id), { dateien, einstellungen: zeiten.configuration ?? null })
  }
  return ergebnis
}
