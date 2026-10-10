// Dünne Hülle um die Backend-API (/api/...).

async function anfrage(pfad, { methode = 'GET', daten, formular } = {}) {
  const optionen = { method: methode, headers: {} }
  if (formular) {
    optionen.body = formular
  } else if (daten !== undefined) {
    optionen.headers['Content-Type'] = 'application/json'
    optionen.body = JSON.stringify(daten)
  }
  const antwort = await fetch(pfad, optionen)
  if (!antwort.ok) {
    let meldung = `${antwort.status} ${antwort.statusText}`
    try {
      const fehler = await antwort.json()
      if (typeof fehler.detail === 'string') meldung = fehler.detail
      else if (Array.isArray(fehler.detail)) meldung = fehler.detail.map((d) => d.msg).join('; ')
    } catch {
      /* keine JSON-Antwort */
    }
    throw new Error(meldung)
  }
  if (antwort.status === 204) return null
  return antwort.json()
}

// Lokale Zeit ohne Zeitzone, so wie das Backend sie speichert
export function lokalIso(datum) {
  const z = (n) => String(n).padStart(2, '0')
  return `${datum.getFullYear()}-${z(datum.getMonth() + 1)}-${z(datum.getDate())}T${z(datum.getHours())}:${z(datum.getMinutes())}:00`
}

export function lokalDatum(datum) {
  return lokalIso(datum).slice(0, 10)
}

// Baut die Query-Parameter für Kalender und Export aus dem Filterzustand
export function filterParameter(filter, von, bis) {
  const p = new URLSearchParams()
  if (von) p.set('von', von)
  if (bis) p.set('bis', bis)
  if (filter.lvas.length) p.set('lva', filter.lvas.join(','))
  if (filter.typen.length) p.set('typ', filter.typen.join(','))
  if (filter.markierungen.length) p.set('markierung', filter.markierungen.join(','))
  p.set('arbeit', filter.arbeit)
  p.set('vorschlaege', String(filter.vorschlaege))
  return p
}

export const api = {
  kalender: (params) => anfrage(`/api/kalender?${params}`),
  exportUrl: (format, params) => `/api/export/${format}?${params}`,

  lvas: () => anfrage('/api/lvas'),
  lvaAendern: (id, daten) => anfrage(`/api/lvas/${id}`, { methode: 'PATCH', daten }),

  termin: (id) => anfrage(`/api/termine/${id}`),
  terminAendern: (id, daten) => anfrage(`/api/termine/${id}`, { methode: 'PATCH', daten }),

  regel: () => anfrage('/api/arbeit/regel'),
  regelSpeichern: (daten) => anfrage('/api/arbeit/regel', { methode: 'PUT', daten }),
  blockAnlegen: (daten) => anfrage('/api/arbeit/bloecke', { methode: 'POST', daten }),
  blockAendern: (id, daten) => anfrage(`/api/arbeit/bloecke/${id}`, { methode: 'PATCH', daten }),
  blockLoeschen: (id) => anfrage(`/api/arbeit/bloecke/${id}`, { methode: 'DELETE' }),
  serien: () => anfrage('/api/arbeit/serien'),
  serieAnlegen: (daten) => anfrage('/api/arbeit/serien', { methode: 'POST', daten }),
  serieLoeschen: (id, ab) => anfrage(`/api/arbeit/serien/${id}${ab ? `?ab=${ab}` : ''}`, { methode: 'DELETE' }),
  vorschlag: (woche) => anfrage(`/api/arbeit/vorschlag?woche=${woche}`, { methode: 'POST' }),
  bestaetigen: (woche) => anfrage(`/api/arbeit/bestaetigen?woche=${woche}`, { methode: 'POST' }),
  verwerfen: (woche) => anfrage(`/api/arbeit/verwerfen?woche=${woche}`, { methode: 'POST' }),

  tuwelStatus: () => anfrage('/api/tuwel/status'),
  tuwelEinrichtung: () => anfrage('/api/tuwel/einrichtung'),
  tuwelNeuerSchluessel: () => anfrage('/api/tuwel/einrichtung/neuer-schluessel', { methode: 'POST' }),
  tuwelKurse: () => anfrage('/api/tuwel/kurse'),
  tuwelKursZuordnen: (id, daten) => anfrage(`/api/tuwel/kurse/${id}`, { methode: 'PATCH', daten }),
  tuwelDokumente: () => anfrage('/api/tuwel/dokumente'),
  dokumentUrl: (id) => `/api/tuwel/dokumente/${id}/datei`,

  tissEinstellungen: () => anfrage('/api/tiss/einstellungen'),
  tissEinstellungenSpeichern: (daten) => anfrage('/api/tiss/einstellungen', { methode: 'PUT', daten }),
  tissImport: () => anfrage('/api/tiss/import', { methode: 'POST' }),
  tissImportDatei: (datei) => {
    const formular = new FormData()
    formular.append('datei', datei)
    return anfrage('/api/tiss/import-datei', { methode: 'POST', formular })
  },
}

export const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
export const TYPEN = [
  { wert: 'VO', name: 'VO' },
  { wert: 'UE', name: 'UE' },
  { wert: 'VU', name: 'VU' },
  { wert: 'PRUEFUNG', name: 'Prüfung' },
  { wert: 'ABGABE', name: 'Abgabe' },
  { wert: 'SONSTIGE', name: 'Sonstige' },
]
export const MARKIERUNGEN = [
  { wert: 'steop', name: 'STEOP', symbol: '★' },
  { wert: 'anwesenheit', name: 'Anwesenheitspflicht', symbol: '✋' },
  { wert: 'aufzeichnung', name: 'Aufzeichnung', symbol: '🎥' },
]

// Gesamtdauer in Sekunden als „5:42 h“ bzw. „45 min“
export function dauerText(sekunden) {
  if (!sekunden) return ''
  const minuten = Math.round(sekunden / 60)
  if (minuten < 60) return `${minuten} min`
  return `${Math.floor(minuten / 60)}:${String(minuten % 60).padStart(2, '0')} h`
}

// Einzelne Aufzeichnung als „1:23:45“
export function laufzeit(sekunden) {
  if (!sekunden) return ''
  const h = Math.floor(sekunden / 3600)
  const m = Math.floor((sekunden % 3600) / 60)
  const s = sekunden % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

export function videoZusammenfassung(anzahl, sekunden, ohneDauer = 0) {
  if (!anzahl) return '–'
  const dauer = dauerText(sekunden)
  return `${anzahl} ${anzahl === 1 ? 'Video' : 'Videos'}${dauer ? ` · ${ohneDauer ? 'mind. ' : ''}${dauer}` : ''}`
}
