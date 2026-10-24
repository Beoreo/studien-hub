// STEOP-Status aus TISS an den Hub schicken – aus einer geöffneten Seite oder per Abruf mit der Browser-Sitzung.
import { TISS, istSteopSeite, steopAusHtml } from './tiss.js'

/** Wertet den Seitenquelltext aus und meldet ihn dem Hub. Ergebnis für Popup und Speicher. */
export async function steopMelden(hub, html) {
  const daten = steopAusHtml(html)
  if (!daten) return { status: 'keine-steop-seite' }
  if (!daten.studien.length) return { status: 'unlesbar', meldung: 'STEOP-Tabelle nicht gefunden – hat TISS die Seite geändert?' }
  const antwort = await hub.steop(daten)
  return {
    status: daten.abgeschlossen === null ? 'unsicher' : 'ok',
    abgeschlossen: daten.abgeschlossen,
    erlaubte_ects: daten.erlaubte_ects,
    steop_nummern: daten.steop_nummern.length,
    kriterien: daten.kriterien.length,
    uebernommen: antwort?.uebernommen ?? false,
    meldung: daten.abgeschlossen === null ? 'Status-Symbol nicht erkannt – Hub behält den bisherigen Stand.' : undefined,
  }
}

/** Holt die gemerkte STEOP-Seite mit der TISS-Sitzung (nur wenn man in TISS eingeloggt ist). */
export async function steopAbrufen({ hub, url, fetchFn = (...a) => fetch(...a) }) {
  if (!url?.startsWith(TISS)) return { status: 'unbekannt', meldung: 'STEOP-Seite einmal in TISS öffnen (LVA Cockpit → STEOP Status).' }
  const antwort = await fetchFn(url, { credentials: 'include' })
  if (!antwort.ok) return { status: 'fehler', meldung: `TISS antwortet mit HTTP ${antwort.status}` }
  const html = await antwort.text()
  if (!istSteopSeite(html)) return { status: 'login', meldung: 'Nicht in TISS eingeloggt – STEOP-Status nicht aktualisiert.' }
  return steopMelden(hub, html)
}
