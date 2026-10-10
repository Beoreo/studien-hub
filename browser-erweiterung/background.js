// Hintergrund: täglicher Lauf, Lauf beim Öffnen von TUWEL und auf Knopfdruck aus dem Popup.
import { Hub } from './hub.js'
import { TUWEL } from './lib.js'
import { synchronisiere } from './sync.js'
import { Tuwel } from './tuwel.js'

const api = globalThis.browser ?? globalThis.chrome
const STUNDE = 60 * 60 * 1000
const ABSTAND_BEI_BESUCH = 6 * STUNDE // beim TUWEL-Besuch höchstens alle 6 h
const STANDARD = { hubUrl: 'http://127.0.0.1:8000', schluessel: '' }
let laeuft = false

async function einstellungen() {
  return { ...STANDARD, ...(await api.storage.local.get(['hubUrl', 'schluessel'])) }
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
  try {
    const ergebnis = await synchronisiere({
      tuwel: new Tuwel(),
      hub: new Hub({ basis: hubUrl, schluessel }),
      // jeder Speicheraufruf hält den Service-Worker während langer Läufe wach
      melde: (text) => setzeZustand({ status: 'laeuft', meldung: text, anlass }),
    })
    const { letzterErfolg } = await api.storage.local.get('letzterErfolg')
    await api.storage.local.set({ letzterErfolg: ergebnis.status === 'ok' ? Date.now() : letzterErfolg || 0 })
    await setzeZustand({ ...ergebnis, anlass, ende: Date.now() })
    await badge(ergebnis.status === 'ok' ? (ergebnis.statistik.fehler.length ? '!' : '') : '!')
    return ergebnis
  } catch (fehler) {
    await setzeZustand({ status: 'fehler', meldung: fehler.message, anlass, ende: Date.now() })
    await badge('!')
    return { status: 'fehler', meldung: fehler.message }
  } finally {
    laeuft = false
  }
}

async function faellig(abstand) {
  const { letzterErfolg = 0 } = await api.storage.local.get('letzterErfolg')
  return Date.now() - letzterErfolg > abstand
}

api.runtime.onInstalled.addListener(() => {
  api.alarms.create('taeglich', { delayInMinutes: 1, periodInMinutes: 24 * 60 })
})

api.runtime.onStartup.addListener(async () => {
  if (await faellig(20 * STUNDE)) starteSync('browserstart')
})

api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'taeglich') starteSync('zeitplan')
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
  if (nachricht?.art === 'pruefen') {
    einstellungen()
      .then(({ hubUrl, schluessel }) => new Hub({ basis: hubUrl, schluessel }).pruefen())
      .then(() => antworten({ ok: true }))
      .catch((fehler) => antworten({ ok: false, meldung: fehler.message }))
    return true
  }
  return false
})
