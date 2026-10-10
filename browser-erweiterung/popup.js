const api = globalThis.browser ?? globalThis.chrome
const $ = (id) => document.getElementById(id)

const STATUS_TEXT = {
  ok: 'Erfolgreich',
  laeuft: 'Läuft',
  login: 'Bitte in TUWEL einloggen',
  fehler: 'Fehler',
  einrichten: 'Einrichtung nötig',
}

function zeit(ms) {
  return ms ? new Date(ms).toLocaleString('de-AT', { dateStyle: 'short', timeStyle: 'short' }) : '–'
}

async function zeigeZustand() {
  const { zustand, letzterErfolg } = await api.storage.local.get(['zustand', 'letzterErfolg'])
  const box = $('zustand')
  box.className = `zustand ${zustand?.status || ''}`
  box.replaceChildren()
  const kopf = document.createElement('strong')
  kopf.textContent = zustand ? STATUS_TEXT[zustand.status] || zustand.status : 'Noch nicht gelaufen'
  const meldung = document.createElement('div')
  meldung.textContent = zustand?.meldung || ''
  const erfolg = document.createElement('div')
  erfolg.className = 'klein'
  erfolg.textContent = `Letzter erfolgreicher Lauf: ${zeit(letzterErfolg)}`
  box.append(kopf, meldung, erfolg)
  if (zustand?.statistik?.fehler?.length) {
    const liste = document.createElement('ul')
    for (const f of zustand.statistik.fehler.slice(0, 5)) {
      const li = document.createElement('li')
      li.textContent = f
      liste.append(li)
    }
    box.append(liste)
  }
  $('sync').disabled = zustand?.status === 'laeuft' && Date.now() - (zustand.aktualisiert || 0) < 120000
}

async function ladeEinstellungen() {
  const { hubUrl, schluessel } = await api.storage.local.get(['hubUrl', 'schluessel'])
  $('hubUrl').value = hubUrl || 'http://127.0.0.1:8000'
  $('schluessel').value = schluessel || ''
  if (!schluessel) $('einstellungen').open = true
}

$('sync').addEventListener('click', () => {
  $('sync').disabled = true
  api.runtime.sendMessage({ art: 'sync' })
})

$('speichern').addEventListener('click', async () => {
  await api.storage.local.set({ hubUrl: $('hubUrl').value.trim() || 'http://127.0.0.1:8000', schluessel: $('schluessel').value.trim() })
  $('pruefung').textContent = 'prüfe …'
  const antwort = await api.runtime.sendMessage({ art: 'pruefen' })
  $('pruefung').textContent = antwort?.ok ? '✓ verbunden' : `✗ ${antwort?.meldung || 'Fehler'}`
})

api.storage.onChanged.addListener((aenderungen) => {
  if (aenderungen.zustand || aenderungen.letzterErfolg) zeigeZustand()
})

ladeEinstellungen()
zeigeZustand()
