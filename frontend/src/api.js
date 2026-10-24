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
  teilAendern: (id, daten) => anfrage(`/api/lvas/teile/${id}`, { methode: 'PATCH', daten }),
  steopStatus: () => anfrage('/api/lvas/steop'),
  // daten: { abgeschlossen?, erlaubte_ects? } – erlaubte_ects null = Wert aus TISS
  steopSetzen: (daten) => anfrage('/api/lvas/steop', { methode: 'PUT', daten }),
  steopVarianteNeu: () => anfrage('/api/lvas/steop/variante', { methode: 'POST' }),
  steopVarianteAendern: (lvaId, enthalten) =>
    anfrage(`/api/lvas/steop/variante/${lvaId}`, { methode: 'PUT', daten: { enthalten } }),
  freieZeitraeume: () => anfrage('/api/tiss/freie-zeitraeume'),

  pruefungen: () => anfrage('/api/pruefungen'),
  pruefungAnlegen: (daten) => anfrage('/api/pruefungen', { methode: 'POST', daten }),
  pruefungAendern: (id, daten) => anfrage(`/api/pruefungen/${id}`, { methode: 'PATCH', daten }),
  pruefungLoeschen: (id) => anfrage(`/api/pruefungen/${id}`, { methode: 'DELETE' }),
  // terminId null = bei keinem Termin angemeldet; automatisch = eigene Wahl aufheben (zählt wieder TISS)
  pruefungAngemeldet: (lvaId, terminId, automatisch = false) =>
    anfrage(`/api/pruefungen/lva/${lvaId}/angemeldet`, { methode: 'PUT', daten: { termin_id: terminId, automatisch } }),

  termin: (id) => anfrage(`/api/termine/${id}`),
  terminAendern: (id, daten) => anfrage(`/api/termine/${id}`, { methode: 'PATCH', daten }),
  // eigene Termine: zu einer LVA (bleiben beim TISS-Import) oder persönlich ohne LVA
  terminAnlegen: (daten) => anfrage('/api/termine', { methode: 'POST', daten }),
  terminLoeschen: (id) => anfrage(`/api/termine/${id}`, { methode: 'DELETE' }),
  persoenlichAnlegen: (daten) => anfrage('/api/termine/persoenlich', { methode: 'POST', daten }),
  persoenlichAendern: (id, daten) => anfrage(`/api/termine/persoenlich/${id}`, { methode: 'PATCH', daten }),
  persoenlichLoeschen: (id) => anfrage(`/api/termine/persoenlich/${id}`, { methode: 'DELETE' }),

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
  alleArbeitsvorschlaegeLoeschen: () => anfrage('/api/arbeit/vorschlaege-loeschen', { methode: 'POST' }),
  lernBlockAendern: (id, daten) => anfrage(`/api/lernen/bloecke/${id}`, { methode: 'PATCH', daten }),
  lernBlockLoeschen: (id) => anfrage(`/api/lernen/bloecke/${id}`, { methode: 'DELETE' }),
  lernBedarf: (woche) => anfrage(`/api/lernen/bedarf?woche=${woche}`),
  planungWoche: (woche) => anfrage(`/api/planung/woche?woche=${woche}`),

  tuwelStatus: () => anfrage('/api/tuwel/status'),
  tuwelEinrichtung: () => anfrage('/api/tuwel/einrichtung'),
  tuwelNeuerSchluessel: () => anfrage('/api/tuwel/einrichtung/neuer-schluessel', { methode: 'POST' }),
  tuwelKurse: () => anfrage('/api/tuwel/kurse'),
  tuwelKursZuordnen: (id, daten) => anfrage(`/api/tuwel/kurse/${id}`, { methode: 'PATCH', daten }),
  tuwelDokumente: () => anfrage('/api/tuwel/dokumente'),
  dokumentUrl: (id) => `/api/tuwel/dokumente/${id}/datei`,
  dokumentLernzeit: (id, lern_minuten) => anfrage(`/api/tuwel/dokumente/${id}`, { methode: 'PATCH', daten: { lern_minuten } }),

  mbcloudStatus: () => anfrage('/api/mbcloud/status'),
  mbcloudVerbinden: () => anfrage('/api/mbcloud/verbinden', { methode: 'POST', daten: {} }),
  mbcloudVerbindenPruefen: () => anfrage('/api/mbcloud/verbinden/pruefen', { methode: 'POST' }),
  mbcloudLauf: () => anfrage('/api/mbcloud/lauf', { methode: 'POST' }),
  mbcloudOrdner: () => anfrage('/api/mbcloud/ordner'),
  mbcloudOrdnerZuordnen: (id, daten) => anfrage(`/api/mbcloud/ordner/${id}`, { methode: 'PATCH', daten }),
  mbcloudDateien: (lvaId) => anfrage(`/api/mbcloud/dateien?lva_id=${lvaId}`),
  mbcloudDateiLaden: (id) => anfrage(`/api/mbcloud/dateien/${id}/laden`, { methode: 'POST' }),
  altpruefungBearbeitet: (dokumentId, daten) =>
    anfrage(`/api/mbcloud/dokumente/${dokumentId}/bearbeitung`, { methode: 'PATCH', daten }),

  wissenUebersicht: () => anfrage('/api/wissen/uebersicht'),
  themenAbleiten: (lvaId) => anfrage(`/api/wissen/themen/ableiten${lvaId ? `?lva_id=${lvaId}` : ''}`, { methode: 'POST' }),
  themaAnlegen: (daten) => anfrage('/api/wissen/themen', { methode: 'POST', daten }),
  themaAendern: (id, daten) => anfrage(`/api/wissen/themen/${id}`, { methode: 'PATCH', daten }),
  themaLoeschen: (id) => anfrage(`/api/wissen/themen/${id}`, { methode: 'DELETE' }),
  themaEreignis: (id, daten) => anfrage(`/api/wissen/themen/${id}/ereignis`, { methode: 'POST', daten }),
  themaAbschnitte: (id) => anfrage(`/api/wissen/themen/${id}/abschnitte`),
  // Prüfungsstoff einer Prüfung (Stoffliste, Skript, Folien): bestimmt die Themen dieser Prüfung
  stoffHochladen: (lvaId, pruefungAm, datei) => {
    const formular = new FormData()
    formular.append('lva_id', String(lvaId))
    formular.append('pruefung_am', pruefungAm)
    formular.append('datei', datei)
    return anfrage('/api/wissen/stoff', { methode: 'POST', formular })
  },
  stoffLoeschen: (id) => anfrage(`/api/wissen/stoff/${id}`, { methode: 'DELETE' }),
  stoffUrl: (id) => `/api/wissen/stoff/${id}/datei`,

  wochenberichtStatus: () => anfrage('/api/wochenbericht/status'),
  wochenberichte: () => anfrage('/api/wochenbericht'),
  wochenbericht: (id) => anfrage(`/api/wochenbericht/${id}`),
  wochenberichtEinstellen: (aktiv) => anfrage('/api/wochenbericht/einstellung', { methode: 'PUT', daten: { aktiv } }),
  wochenberichtErstellen: () => anfrage('/api/wochenbericht/erstellen', { methode: 'POST' }),
  wochenberichtLoeschen: (id) => anfrage(`/api/wochenbericht/${id}`, { methode: 'DELETE' }),

  kiStatus: () => anfrage('/api/ki/status'),
  kiVorlagen: () => anfrage('/api/ki/vorlagen'),
  kiVorlage: (name, werte) => anfrage(`/api/ki/vorlage?${new URLSearchParams({ name, ...werte })}`),
  kiEinrichten: () => anfrage('/api/ki/einrichten', { methode: 'POST' }),
  kiAustragen: () => anfrage('/api/ki/austragen', { methode: 'POST' }),
  kiVerarbeitung: ({ text, video }) => {
    const p = new URLSearchParams()
    if (text !== undefined) p.set('text', String(text))
    if (video !== undefined) p.set('video', String(video))
    return anfrage(`/api/ki/verarbeitung?${p}`, { methode: 'POST' })
  },
  kiSuche: (frage, lvaId) => anfrage(`/api/ki/suche?frage=${encodeURIComponent(frage)}${lvaId ? `&lva_id=${lvaId}` : ''}`),

  // Betrieb: Status-Seite, Sicherungen, Autostart, Einrichtungsassistent
  systemStatus: () => anfrage('/api/system/status'),
  jetztSynchronisieren: () => anfrage('/api/system/sync', { methode: 'POST' }),
  autostartSetzen: (aktiv) => anfrage('/api/system/autostart', { methode: 'PUT', daten: { aktiv } }),
  sichern: () => anfrage('/api/system/sicherungen', { methode: 'POST' }),
  wiederherstellen: (name) => anfrage(`/api/system/sicherungen/${encodeURIComponent(name)}/wiederherstellen`, { methode: 'POST' }),
  ordnerOeffnen: (art) => anfrage(`/api/system/ordner/${art}`, { methode: 'POST' }),
  einrichtung: () => anfrage('/api/einrichtung'),
  datenUebernehmen: () => anfrage('/api/einrichtung/daten', { methode: 'POST' }),
  tuwelTokenSetzen: (eingabe) => anfrage('/api/einrichtung/tuwel-token', { methode: 'PUT', daten: { eingabe } }),
  modellLaden: (name) => anfrage(`/api/einrichtung/modelle/${name}`, { methode: 'POST' }),
  einrichtungAbschliessen: () => anfrage('/api/einrichtung/abschliessen', { methode: 'POST' }),

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
// icon: Name in ui.jsx (ICONS)
export const MARKIERUNGEN = [
  { wert: 'steop', name: 'STEOP', icon: 'steop' },
  { wert: 'anwesenheit', name: 'Anwesenheitspflicht', icon: 'anwesenheit' },
  { wert: 'aufzeichnung', name: 'Aufzeichnung', icon: 'aufzeichnung' },
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
