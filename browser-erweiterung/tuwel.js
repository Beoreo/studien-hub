// Zugriff auf TUWEL mit der Sitzung des eingeloggten Browsers (kein Token nötig).
import { NichtEingeloggt, TUWEL, aenderungenLesen, istLoginSeite, sesskeyAusHtml } from './lib.js'

export class Tuwel {
  constructor({ fetchFn = (...a) => fetch(...a), basis = TUWEL } = {}) {
    this.fetch = fetchFn
    this.basis = basis
    this.sesskey = null
  }

  async seite(url, optionen = {}) {
    const antwort = await this.fetch(url, { credentials: 'include', ...optionen })
    if (!antwort.ok) throw new Error(`TUWEL antwortet mit HTTP ${antwort.status} (${url.replace(this.basis, '')})`)
    return antwort
  }

  /** Prüft die Anmeldung und holt den Sitzungsschlüssel für Web-Aufrufe. */
  async anmelden() {
    const antwort = await this.seite(`${this.basis}/my/`)
    const html = await antwort.text()
    this.sesskey = sesskeyAusHtml(html)
    if (!this.sesskey || istLoginSeite(antwort.url, html)) throw new NichtEingeloggt()
    return this.sesskey
  }

  /** Aufruf einer Moodle-Funktion über die Web-Schnittstelle, die auch die TUWEL-Seiten selbst nutzen. */
  async ajax(methodname, args) {
    if (!this.sesskey) await this.anmelden()
    const antwort = await this.seite(`${this.basis}/lib/ajax/service.php?sesskey=${this.sesskey}&info=${methodname}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([{ index: 0, methodname, args }]),
    })
    const daten = await antwort.json()
    const ergebnis = Array.isArray(daten) ? daten[0] : daten
    if (ergebnis?.error) {
      const fehler = ergebnis.exception || ergebnis
      if (/servicerequireslogin|requireloginerror|invalidsesskey/i.test(fehler.errorcode || '')) throw new NichtEingeloggt()
      throw new Error(`${methodname}: ${fehler.message || fehler.errorcode || 'Fehler'}`)
    }
    return ergebnis?.data
  }

  async kurse() {
    const daten = await this.ajax('core_course_get_enrolled_courses_by_timeline_classification', {
      classification: 'all',
      limit: 0,
      offset: 0,
      sort: 'fullname',
    })
    return daten?.courses || []
  }

  async kursZustand(kursId) {
    return this.ajax('core_courseformat_get_state', { courseid: kursId })
  }

  /**
   * Wann TUWEL die Aktivitäten eines Kurses zuletzt geändert hat (Unix-Zeit), je Aktivität:
   * { dateien: neueste Datei im Inhalts-/Beschreibungsbereich, einstellungen: Konfiguration }.
   */
  async aenderungen(kursId) {
    const daten = await this.ajax('core_course_get_updates_since', { courseid: kursId, since: 0 })
    return aenderungenLesen(daten)
  }

  /** Nur den Last-Modified-Kopf einer Datei holen, ohne sie herunterzuladen. */
  async kopf(url) {
    let antwort = await this.fetch(url, { credentials: 'include', method: 'HEAD' })
    if (!antwort.ok) antwort = await this.seite(url)
    if (istLoginSeite(antwort.url)) throw new NichtEingeloggt()
    return { lastModified: antwort.headers.get('last-modified') || null }
  }

  async html(url) {
    const antwort = await this.seite(url)
    const html = await antwort.text()
    if (istLoginSeite(antwort.url, html)) throw new NichtEingeloggt()
    return { url: antwort.url, html }
  }

  /** Folgt der Weiterleitung einer Dateiressource, ohne den Inhalt zu laden. */
  async aufloesen(url) {
    let antwort = await this.fetch(url, { credentials: 'include', method: 'HEAD' })
    if (!antwort.ok) antwort = await this.seite(url) // manche Server erlauben kein HEAD
    if (istLoginSeite(antwort.url)) throw new NichtEingeloggt()
    return {
      url: antwort.url,
      inhaltstyp: antwort.headers.get('content-type') || '',
      disposition: antwort.headers.get('content-disposition') || '',
      lastModified: antwort.headers.get('last-modified') || null,
    }
  }

  async datei(url) {
    const antwort = await this.seite(url)
    if (istLoginSeite(antwort.url)) throw new NichtEingeloggt()
    return { blob: await antwort.blob(), lastModified: antwort.headers.get('last-modified') || null }
  }
}
