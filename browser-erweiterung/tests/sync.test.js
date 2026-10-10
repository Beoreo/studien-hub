import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Hub } from '../hub.js'
import { NichtEingeloggt } from '../lib.js'
import { sammleEintraege, synchronisiere } from '../sync.js'
import { Tuwel } from '../tuwel.js'

const T = 'https://tuwel.tuwien.ac.at'

// --- nachgebautes TUWEL --------------------------------------------------------------

const ZUSTAND = JSON.stringify({
  section: [{ id: '1', title: 'Woche 1' }],
  cm: [
    { id: '100', name: 'Skript', module: 'resource', sectionid: '1', url: `${T}/mod/resource/view.php?id=100` },
    { id: '101', name: 'Übungsblätter', module: 'folder', sectionid: '1', url: `${T}/mod/folder/view.php?id=101` },
    { id: '102', name: 'VO 1 Video', module: 'url', sectionid: '1', url: `${T}/mod/url/view.php?id=102` },
    { id: '103', name: 'Doku', module: 'url', sectionid: '1', url: `${T}/mod/url/view.php?id=103` },
    { id: '104', name: 'Aufzeichnung', module: 'resource', sectionid: '1', url: `${T}/mod/resource/view.php?id=104` },
  ],
})

function antwort(body, { status = 200, url = '', kopf = {} } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    url,
    headers: { get: (n) => kopf[n.toLowerCase()] ?? null },
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    json: async () => (typeof body === 'string' ? JSON.parse(body) : body),
    blob: async () => new Blob([typeof body === 'string' ? body : JSON.stringify(body)]),
  }
}

function tuwelFetch({ eingeloggt = true, aufrufe = [] } = {}) {
  return async (url, optionen = {}) => {
    aufrufe.push({ url, methode: optionen.method || 'GET', credentials: optionen.credentials })
    if (url === `${T}/my/`) {
      return eingeloggt
        ? antwort('<script>M.cfg={"sesskey":"SK1"}</script>', { url })
        : antwort('<form id="login"><input name="username"></form>', { url: `${T}/login/index.php` })
    }
    if (url.startsWith(`${T}/lib/ajax/service.php`)) {
      const [{ methodname }] = JSON.parse(optionen.body)
      if (methodname === 'core_course_get_enrolled_courses_by_timeline_classification') {
        return antwort([{ error: false, data: { courses: [
          { id: 1, shortname: '185.A91-2026W', fullname: 'EP1' },
          { id: 2, shortname: 'XYZ', fullname: 'Fremd' },
        ] } }])
      }
      if (methodname === 'core_courseformat_get_state') return antwort([{ error: false, data: ZUSTAND }])
      if (methodname === 'core_course_get_updates_since') {
        return antwort([{ error: false, data: { instances: [
          { contextlevel: 'module', id: 100, updates: [{ name: 'configuration', timeupdated: 1790000000 }, { name: 'contentfiles', timeupdated: 1791879300 }] },
          { contextlevel: 'module', id: 101, updates: [{ name: 'contentfiles', timeupdated: 1791000000 }] },
          { contextlevel: 'module', id: 102, updates: [{ name: 'configuration', timeupdated: 1790500000 }] },
        ], warnings: [] } }])
      }
    }
    if (url.includes('/mod/resource/view.php?id=100')) {
      return antwort('', {
        url: `${T}/pluginfile.php/9/mod_resource/content/3/skript.pdf`,
        kopf: { 'content-type': 'application/pdf', 'last-modified': 'Tue, 13 Oct 2026 08:15:00 GMT' },
      })
    }
    if (url.includes('/mod/resource/view.php?id=104')) {
      return antwort('', { url: `${T}/pluginfile.php/9/mod_resource/content/1/vo.mp4`, kopf: { 'content-type': 'video/mp4' } })
    }
    if (url === `${T}/mod/folder/view.php?id=101`) {
      return antwort(`<a href="${T}/pluginfile.php/8/mod_folder/content/0/Teil%201/blatt1.pdf?forcedownload=1">b</a>`, { url })
    }
    if (url === `${T}/mod/url/view.php?id=102`) return antwort('', { url: 'https://lecturetube.tuwien.ac.at/v/77' })
    if (url === `${T}/mod/url/view.php?id=103`) {
      return antwort('<div class="urlworkaround"><a href="https://docs.python.org">x</a></div>', { url })
    }
    if (url.includes('/pluginfile.php/')) return antwort(`INHALT:${url}`, { url, kopf: { 'last-modified': 'Fri, 02 Oct 2026 07:30:00 GMT' } })
    return antwort('nicht gefunden', { status: 404, url })
  }
}

// --- nachgebauter Hub ------------------------------------------------------------------

function hubAttrappe({ bekannt = [] } = {}) {
  const protokoll = { kurse: null, inhalte: [], nachtraege: [], dateien: [], ende: null, fehler: null }
  return {
    protokoll,
    pruefen: async () => ({ ok: true }),
    kurse: async (kurse) => {
      protokoll.kurse = kurse
      return { kurse: kurse.map((k) => ({ ...k, lva_name: k.id === 1 ? 'EP1' : null, synchronisieren: k.id === 1 })) }
    },
    inhalt: async (kursId, eintraege, optionen = {}) => {
      if (optionen.nachtrag) {
        protokoll.nachtraege.push(eintraege)
        return { herunterladen: [], unveraendert: 0, videos_neu: 0, details: [], datum_fehlt: [] }
      }
      protokoll.inhalte.push({ kursId, eintraege })
      const dateien = eintraege.filter((e) => e.art === 'datei')
      return {
        herunterladen: dateien.filter((e) => !bekannt.includes(e.url)).map((e) => e.url),
        unveraendert: dateien.filter((e) => bekannt.includes(e.url)).length,
        videos_neu: eintraege.filter((e) => e.art === 'video').length,
        // wie der Hub: bekannte Dateien ohne TUWEL-Datum brauchen Last-Modified
        datum_fehlt: dateien.filter((e) => bekannt.includes(e.url) && !e.tuwel_zeit && !e.last_modified).map((e) => e.url),
      }
    },
    datei: async (kursId, eintrag, blob) => {
      protokoll.dateien.push({ kursId, eintrag, inhalt: await blob.text() })
      return { status: 'neu' }
    },
    ende: async (statistik) => {
      protokoll.ende = statistik
    },
    fehler: async (meldung, art) => {
      protokoll.fehler = { meldung, art }
    },
  }
}

// --- Tests -------------------------------------------------------------------------------

test('Einträge eines Kurses: Dateien, Ordner, Videos; normale Links ignoriert', async () => {
  const aufrufe = []
  const tuwel = new Tuwel({ fetchFn: tuwelFetch({ aufrufe }) })
  await tuwel.anmelden()
  const { eintraege, fehler } = await sammleEintraege(tuwel, 1)
  assert.deepEqual(fehler, [])
  assert.deepEqual(
    eintraege.map((e) => [e.cm_id, e.art, e.dateiname ?? null, e.unterordner ?? null, e.url]),
    [
      [100, 'datei', 'skript.pdf', '', `${T}/pluginfile.php/9/mod_resource/content/3/skript.pdf`],
      [101, 'datei', 'blatt1.pdf', 'Teil 1', `${T}/pluginfile.php/8/mod_folder/content/0/Teil%201/blatt1.pdf`],
      [102, 'video', null, null, 'https://lecturetube.tuwien.ac.at/v/77'],
      [104, 'video', null, null, `${T}/pluginfile.php/9/mod_resource/content/1/vo.mp4`],
    ],
  )
  assert.ok(eintraege.every((e) => e.abschnitt === 'Woche 1'))
  // Videodateien werden nie heruntergeladen, Ressourcen nur per HEAD aufgelöst
  assert.ok(!aufrufe.some((a) => a.url.endsWith('vo.mp4')))
  assert.ok(aufrufe.filter((a) => a.url.includes('mod/resource')).every((a) => a.methode === 'HEAD'))
  assert.ok(aufrufe.every((a) => a.credentials === 'include'))
})

test('kompletter Lauf: nur zugeordnete Kurse, nur angeforderte Dateien', async () => {
  const hub = hubAttrappe({ bekannt: [`${T}/pluginfile.php/9/mod_resource/content/3/skript.pdf`] })
  const meldungen = []
  const ergebnis = await synchronisiere({ tuwel: new Tuwel({ fetchFn: tuwelFetch() }), hub, melde: (m) => meldungen.push(m) })

  assert.equal(ergebnis.status, 'ok')
  assert.deepEqual(hub.protokoll.kurse.map((k) => k.kurzname), ['185.A91-2026W', 'XYZ'])
  assert.deepEqual(hub.protokoll.inhalte.map((i) => i.kursId), [1]) // Fremdkurs übersprungen
  assert.deepEqual(hub.protokoll.dateien.map((d) => d.eintrag.dateiname), ['blatt1.pdf']) // Skript bekannt
  assert.match(hub.protokoll.dateien[0].inhalt, /^INHALT:/)
  assert.deepEqual(ergebnis.statistik, { kurse: 1, neu: 1, geaendert: 0, unveraendert: 1, videos: 2, fehler: [], hinweise: [] })

  // Erscheinungsdatum: TUWEL-Zeiten je Aktivität, Last-Modified aus den Antworten
  const gesendet = Object.fromEntries(hub.protokoll.inhalte[0].eintraege.map((e) => [e.cm_id, e]))
  assert.equal(gesendet[100].tuwel_zeit, 1791879300) // Ressource: Dateizeit, nicht Einstellungen
  assert.equal(gesendet[100].last_modified, 'Tue, 13 Oct 2026 08:15:00 GMT')
  assert.equal(gesendet[101].tuwel_zeit, 1791000000) // Ordner mit genau einer Datei
  assert.equal(gesendet[102].tuwel_zeit, 1790500000) // Video-Link: Einstellungen
  assert.equal(hub.protokoll.dateien[0].eintrag.last_modified, 'Fri, 02 Oct 2026 07:30:00 GMT') // vom Download
  assert.deepEqual(hub.protokoll.nachtraege, []) // Skript hat ein TUWEL-Datum, nichts nachzutragen
  assert.deepEqual(hub.protokoll.ende, ergebnis.statistik)
  assert.ok(meldungen.length > 3)
})

test('nicht eingeloggt: Hub bekommt einen Login-Hinweis, nichts wird synchronisiert', async () => {
  const hub = hubAttrappe()
  const ergebnis = await synchronisiere({ tuwel: new Tuwel({ fetchFn: tuwelFetch({ eingeloggt: false }) }), hub })
  assert.equal(ergebnis.status, 'login')
  assert.equal(hub.protokoll.fehler.art, 'login')
  assert.equal(hub.protokoll.kurse, null)
})

test('Sitzung läuft mitten im Lauf ab', async () => {
  const basis = tuwelFetch()
  let anfragen = 0
  const fetchFn = async (url, optionen) => {
    if (url.includes('/pluginfile.php/8/') && ++anfragen) return antwort('<form id="login">', { url: `${T}/login/index.php` })
    return basis(url, optionen)
  }
  const hub = hubAttrappe()
  const ergebnis = await synchronisiere({ tuwel: new Tuwel({ fetchFn }), hub })
  assert.equal(ergebnis.status, 'login')
  assert.equal(hub.protokoll.fehler.art, 'login')
  assert.equal(hub.protokoll.ende, null)
})

test('Fehler einer Aktivität bricht den Kurs nicht ab', async () => {
  const basis = tuwelFetch()
  const fetchFn = async (url, optionen) =>
    url === `${T}/mod/folder/view.php?id=101` ? antwort('kaputt', { status: 500, url }) : basis(url, optionen)
  const tuwel = new Tuwel({ fetchFn })
  await tuwel.anmelden()
  const { eintraege, fehler } = await sammleEintraege(tuwel, 1)
  assert.equal(fehler.length, 1)
  assert.match(fehler[0], /Übungsblätter: TUWEL antwortet mit HTTP 500/)
  assert.ok(eintraege.some((e) => e.cm_id === 100))
})

test('TUWEL-Fehler aus der Web-Schnittstelle', async () => {
  const fetchFn = async (url, optionen) => {
    if (url.includes('service.php')) {
      return antwort([{ error: true, exception: { errorcode: 'servicerequireslogin', message: 'Bitte anmelden' } }])
    }
    return tuwelFetch()(url, optionen)
  }
  const tuwel = new Tuwel({ fetchFn })
  await assert.rejects(() => tuwel.kurse(), NichtEingeloggt)
})

test('Hub-Client: Schlüssel im Kopf, verständliche Fehler', async () => {
  const gesehen = []
  const ok = new Hub({
    schluessel: 'geheim',
    fetchFn: async (url, optionen) => {
      gesehen.push({ url, kopf: optionen.headers })
      return antwort({ ok: true })
    },
  })
  await ok.pruefen()
  assert.equal(gesehen[0].url, 'http://127.0.0.1:8000/api/tuwel/sync/pruefen')
  assert.equal(gesehen[0].kopf['X-Studienhub-Schluessel'], 'geheim')

  const falsch = new Hub({ fetchFn: async () => antwort({ detail: 'x' }, { status: 401 }) })
  await assert.rejects(() => falsch.pruefen(), /Schlüssel falsch/)
  const weg = new Hub({ fetchFn: async () => Promise.reject(new TypeError('Failed to fetch')) })
  await assert.rejects(() => weg.pruefen(), /nicht erreichbar/)
  const konflikt = new Hub({ fetchFn: async () => antwort({ detail: 'Kurs ist keiner LVA zugeordnet' }, { status: 409 }) })
  await assert.rejects(() => konflikt.inhalt(1, []), /keiner LVA zugeordnet/)
})


test('gespeicherte Dateien ohne Datum: nur Kopf abfragen und als Nachtrag senden', async () => {
  const aufrufe = []
  const basis = tuwelFetch({ aufrufe })
  // ohne TUWEL-Änderungsdaten (z. B. Funktion gesperrt)
  const fetchFn = async (url, optionen = {}) =>
    optionen.body?.includes?.('core_course_get_updates_since') ? antwort('verboten', { status: 403, url }) : basis(url, optionen)
  const skript = `${T}/pluginfile.php/9/mod_resource/content/3/skript.pdf`
  const ordnerDatei = `${T}/pluginfile.php/8/mod_folder/content/0/Teil%201/blatt1.pdf`
  const hub = hubAttrappe({ bekannt: [skript, ordnerDatei] })
  const ergebnis = await synchronisiere({ tuwel: new Tuwel({ fetchFn }), hub })

  assert.equal(ergebnis.status, 'ok')
  assert.ok(ergebnis.statistik.hinweise.some((h) => h.includes('Änderungsdaten nicht verfügbar')))
  assert.deepEqual(hub.protokoll.dateien, []) // nichts erneut heruntergeladen
  // Das Skript brachte Last-Modified schon beim Auflösen mit; nur die Ordnerdatei wird nachgetragen
  assert.equal(hub.protokoll.inhalte[0].eintraege.find((e) => e.url === skript).last_modified, 'Tue, 13 Oct 2026 08:15:00 GMT')
  const nachtrag = hub.protokoll.nachtraege[0]
  assert.deepEqual(nachtrag.map((e) => [e.url, e.last_modified]), [[ordnerDatei, 'Fri, 02 Oct 2026 07:30:00 GMT']])
  // für die Ordnerdatei genügte ein HEAD-Aufruf
  assert.ok(aufrufe.some((a) => a.url === ordnerDatei && a.methode === 'HEAD'))
  assert.ok(!aufrufe.some((a) => a.url === ordnerDatei && a.methode === 'GET'))
})
