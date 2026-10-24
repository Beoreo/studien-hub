// Hintergrund: täglicher Lauf, Lauf beim Öffnen von TUWEL und auf Knopfdruck aus dem Popup.
// Dazu der STEOP-Status aus TISS: beim Öffnen der Seite „STEOP Status“ und bei jedem Lauf (gemerkte Adresse),
// und die Prüfungstermine (TISS-Prüfungslisten, TUWEL-Kalender) nach dem Lauf und beim Öffnen einer Prüfungsliste.
import { Hub } from './hub.js'
import { TUWEL } from './lib.js'
import { tissListeMelden, tissPruefungenAbrufen, tuwelPruefungenAbrufen } from './pruefungen.js'
import { synchronisiere } from './sync.js'
import { steopAbrufen, steopMelden } from './tiss-sync.js'
import { Tuwel } from './tuwel.js'

const api = globalThis.browser ?? globalThis.chrome
const STUNDE = 60 * 60 * 1000
const ABSTAND_BEI_BESUCH = 6 * STUNDE // beim TUWEL-Besuch höchstens alle 6 h
const STANDARD = { hubUrl: 'http://127.0.0.1:8000', schluessel: '' }
let laeuft = false

async function einstellungen() {
  const werte = { ...STANDARD, ...(await api.storage.local.get(['hubUrl', 'schluessel'])) }
  if (!werte.schluessel) werte.schluessel = await schluesselHolen(werte.hubUrl)
  return werte
}

/** Schlüssel automatisch vom Hub holen (kein Abtippen mehr); ohne laufenden Hub bleibt er leer. */
async function schluesselHolen(hubUrl) {
  try {
    const schluessel = await new Hub({ basis: hubUrl }).schluesselHolen()
    if (schluessel) await api.storage.local.set({ schluessel })
    return schluessel || ''
  } catch {
    return ''
  }
}

/** „Jetzt synchronisieren“ im Hub (Symbol im Infobereich): neue Anforderung → einmal laufen. */
async function anforderungPruefen() {
  const { hubUrl, schluessel } = await einstellungen()
  if (!schluessel) return
  try {
    const angefordert = await new Hub({ basis: hubUrl, schluessel }).anforderung()
    const { erledigteAnforderung } = await api.storage.local.get('erledigteAnforderung')
    if (angefordert && angefordert !== erledigteAnforderung) {
      await api.storage.local.set({ erledigteAnforderung: angefordert })
      starteSync('hub')
    }
  } catch {
    /* Hub gerade nicht erreichbar – beim nächsten Mal */
  }
}

function weckerStellen() {
  api.alarms.create('taeglich', { delayInMinutes: 1, periodInMinutes: 24 * 60 })
  api.alarms.create('anforderung', { delayInMinutes: 1, periodInMinutes: 2 })
}

async function setzeZustand(zustand) {
  await api.storage.local.set({ zustand: { ...zustand, aktualisiert: Date.now() } })
}

async function badge(text, farbe = '#b45309') {
  await api.action.setBadgeText({ text })
  if (text) await api.action.setBadgeBackgroundColor({ color: farbe })
}

export async function starteSync(anlass) {
  if (laeuft) return { status: 'laeuft' }
  const { hubUrl, schluessel } = await einstellungen()
  if (!schluessel) {
    await setzeZustand({ status: 'einrichten', meldung: 'Schlüssel aus dem Hub (Reiter „TUWEL“) eintragen.' })
    await badge('!')
    return { status: 'einrichten' }
  }
  laeuft = true
  await badge('…', '#2563eb')
  const tuwel = new Tuwel()
  try {
    const ergebnis = await synchronisiere({
      tuwel,
      hub: new Hub({ basis: hubUrl, schluessel }),
      // jeder Speicheraufruf hält den Service-Worker während langer Läufe wach
      melde: (text) => setzeZustand({ status: 'laeuft', meldung: text, anlass }),
    })
    const { letzterErfolg } = await api.storage.local.get('letzterErfolg')
    await api.storage.local.set({ letzterErfolg: ergebnis.status === 'ok' ? Date.now() : letzterErfolg || 0 })
    await setzeZustand({ ...ergebnis, anlass, ende: Date.now() })
    await badge(ergebnis.status === 'ok' ? (ergebnis.statistik.fehler.length ? '!' : '') : '!')
    await steopAktualisieren()
    await pruefungenAktualisieren(anlass, ergebnis.status === 'ok' ? tuwel : null)
    return ergebnis
  } catch (fehler) {
    // Hub neu installiert oder Schlüssel neu erzeugt: alten Schlüssel vergessen, der nächste Lauf holt den aktuellen
    if (fehler.schluesselFalsch) await api.storage.local.remove('schluessel')
    await setzeZustand({ status: 'fehler', meldung: fehler.message, anlass, ende: Date.now() })
    await badge('!')
    return { status: 'fehler', meldung: fehler.message }
  } finally {
    laeuft = false
  }
}

async function steopSpeichern(ergebnis, url) {
  const werte = { tissSteop: { ...ergebnis, zeit: Date.now() } }
  if (url && ergebnis.status !== 'keine-steop-seite') werte.tissSteopUrl = url
  await api.storage.local.set(werte)
}

/** STEOP-Status mit der TISS-Sitzung neu holen; Fehler hier stören den TUWEL-Lauf nicht. */
async function steopAktualisieren() {
  const { hubUrl, schluessel } = await einstellungen()
  const { tissSteopUrl } = await api.storage.local.get('tissSteopUrl')
  if (!schluessel || !tissSteopUrl) return
  try {
    await steopSpeichern(await steopAbrufen({ hub: new Hub({ basis: hubUrl, schluessel }), url: tissSteopUrl }))
  } catch (fehler) {
    await steopSpeichern({ status: 'fehler', meldung: fehler.message })
  }
}

/** Prüfungstermine aus TISS (Prüfungslisten) und TUWEL (Kalender) – höchstens alle 12 h, auf Knopfdruck immer.
 *  `tuwel` nur nach einem erfolgreichen TUWEL-Lauf (sonst fehlt die Anmeldung). Fehler stören den Lauf nicht. */
async function pruefungenAktualisieren(anlass, tuwel) {
  const { hubUrl, schluessel } = await einstellungen()
  const { pruefungenZuletzt = 0 } = await api.storage.local.get('pruefungenZuletzt')
  if (!schluessel || (!['manuell', 'hub'].includes(anlass) && Date.now() - pruefungenZuletzt < 12 * STUNDE)) return
  const hub = new Hub({ basis: hubUrl, schluessel })
  const zustand = { zeit: Date.now() }
  // Fehler einer Quelle gehen an den Hub, damit der Reiter „Prüfungen“ sie zeigt (nicht nur das Popup)
  const quelle = async (name, abruf) => {
    try {
      return await abruf()
    } catch (fehler) {
      await hub.pruefungen({ quelle: name, lvas: [], fehler: [fehler.message] }).catch(() => {})
      return { status: 'fehler', meldung: fehler.message }
    }
  }
  try {
    const { lvas } = await hub.pruefungenAbruf()
    zustand.tiss = await quelle('tiss', () => tissPruefungenAbrufen({ hub, lvas, cookieSetzen: tissCookieSetzen }))
    if (tuwel) zustand.tuwel = await quelle('tuwel', () => tuwelPruefungenAbrufen({ hub, tuwel, lvas }))
    await api.storage.local.set({ pruefungenZuletzt: Date.now() })
  } catch (fehler) {
    zustand.fehler = fehler.message
  }
  await api.storage.local.set({ pruefungen: zustand })
}

/** Kurzlebiges Cookie für den Fenster-ID-Handshake von TISS (pruefungen.js: tissSeite). */
async function tissCookieSetzen(name, wert) {
  await api.cookies.set({
    url: 'https://tiss.tuwien.ac.at/', name, value: wert, path: '/', secure: true, sameSite: 'no_restriction',
    expirationDate: Math.floor(Date.now() / 1000) + 60,
  })
}

async function faellig(abstand) {
  const { letzterErfolg = 0 } = await api.storage.local.get('letzterErfolg')
  return Date.now() - letzterErfolg > abstand
}

api.runtime.onInstalled.addListener(weckerStellen)

api.runtime.onStartup.addListener(async () => {
  // der tägliche Wecker bleibt erhalten; die Nachfrage beim Hub sicherheitshalber neu stellen
  if (!(await api.alarms.get('anforderung'))) api.alarms.create('anforderung', { delayInMinutes: 1, periodInMinutes: 2 })
  if (await faellig(20 * STUNDE)) starteSync('browserstart')
})

api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'taeglich') starteSync('zeitplan')
  if (alarm.name === 'anforderung') anforderungPruefen()
})

// Wer TUWEL öffnet, ist eingeloggt – guter Zeitpunkt für einen Lauf
api.tabs.onUpdated.addListener(async (_tabId, info, tab) => {
  if (info.status === 'complete' && tab.url?.startsWith(TUWEL) && (await faellig(ABSTAND_BEI_BESUCH))) {
    starteSync('tuwel-besuch')
  }
})

api.runtime.onMessage.addListener((nachricht, _absender, antworten) => {
  if (nachricht?.art === 'sync') {
    starteSync('manuell').then(antworten)
    return true // asynchrone Antwort
  }
  if (nachricht?.art === 'tiss-steop') {
    einstellungen()
      .then(({ hubUrl, schluessel }) => {
        if (!schluessel) return { status: 'einrichten', meldung: 'Schlüssel aus dem Hub eintragen.' }
        return steopMelden(new Hub({ basis: hubUrl, schluessel }), nachricht.html)
      })
      .catch((fehler) => ({ status: 'fehler', meldung: fehler.message }))
      .then(async (ergebnis) => {
        await steopSpeichern(ergebnis, nachricht.url)
        antworten(ergebnis)
      })
    return true
  }
  if (nachricht?.art === 'tiss-pruefungen') {
    // gerade geöffnete Prüfungsliste (auch nach dem An- oder Abmelden in TISS)
    einstellungen()
      .then(({ hubUrl, schluessel }) => {
        if (!schluessel) return { status: 'einrichten', meldung: 'Schlüssel aus dem Hub eintragen.' }
        return tissListeMelden({ hub: new Hub({ basis: hubUrl, schluessel }), html: nachricht.html, url: nachricht.url })
      })
      .catch((fehler) => ({ status: 'fehler', meldung: fehler.message }))
      .then(antworten)
    return true
  }
  if (nachricht?.art === 'pruefen') {
    einstellungen()
      .then(({ hubUrl, schluessel }) => new Hub({ basis: hubUrl, schluessel }).pruefen())
      .then(() => antworten({ ok: true }))
      .catch((fehler) => antworten({ ok: false, meldung: fehler.message }))
    return true
  }
  return false
})
