// Verbindung zum lokalen Studien-Hub. Jede schreibende Anfrage trägt den gemeinsamen Schlüssel.

export class HubFehler extends Error {}

export class Hub {
  constructor({ basis = 'http://127.0.0.1:8000', schluessel = '', fetchFn = (...a) => fetch(...a) } = {}) {
    this.basis = basis.replace(/\/$/, '')
    this.schluessel = schluessel
    this.fetch = fetchFn
  }

  async anfrage(pfad, optionen = {}) {
    let antwort
    try {
      antwort = await this.fetch(`${this.basis}/api/tuwel${pfad}`, {
        ...optionen,
        headers: { 'X-Studienhub-Schluessel': this.schluessel, ...(optionen.headers || {}) },
      })
    } catch {
      throw new HubFehler('Studien-Hub nicht erreichbar – läuft er (npm run dev oder start.ps1)?')
    }
    if (antwort.status === 401) throw new HubFehler('Schlüssel falsch – im Hub unter „TUWEL“ kopieren und hier eintragen.')
    if (!antwort.ok) {
      let meldung = `Hub antwortet mit HTTP ${antwort.status}`
      try {
        meldung = (await antwort.json()).detail || meldung
      } catch {
        /* keine JSON-Antwort */
      }
      throw new HubFehler(meldung)
    }
    return antwort.json()
  }

  json(pfad, daten) {
    return this.anfrage(pfad, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(daten) })
  }

  pruefen() {
    return this.anfrage('/sync/pruefen')
  }

  kurse(kurse) {
    return this.json('/sync/kurse', { kurse })
  }

  inhalt(kursId, eintraege, { nachtrag = false } = {}) {
    return this.json('/sync/inhalt', { kurs_id: kursId, eintraege, nachtrag })
  }

  datei(kursId, eintrag, blob) {
    const formular = new FormData()
    formular.append('kurs_id', String(kursId))
    formular.append('eintrag', JSON.stringify(eintrag))
    formular.append('datei', blob, eintrag.dateiname)
    return this.anfrage('/sync/datei', { method: 'POST', body: formular })
  }

  ende(statistik) {
    return this.json('/sync/ende', { statistik })
  }

  fehler(meldung, art = 'fehler') {
    return this.json('/sync/fehler', { meldung, art })
  }
}
