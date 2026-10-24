import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Hub } from '../hub.js'
import { NichtEingeloggt } from '../lib.js'
import {
  TissNichtEingeloggt,
  fensterUmleitung,
  tissSeite,
  istPruefungsEreignis,
  istUnlesbar,
  listeAusUrl,
  monateUm,
  monatsEreignisse,
  pruefungenAusHtml,
  pruefungsListeUrl,
  tissListeMelden,
  tissPruefungenAbrufen,
  tuwelPruefungen,
  tuwelPruefungenAbrufen,
  wienIso,
} from '../pruefungen.js'

// Nachbau der TISS-Prüfungsliste: je Termin eine „groupWrapper“-Box mit Kopf und Details
const box = ({ kopf, datum, zeit, ort, anmeldung, abmeldung = '', knopf = '', id = '' }) => `
<div class="groupWrapper"${id ? ` id="examDate_${id}"` : ''}>
  <div class="groupHeaderWrapper"><span class="groupHeadertrigger">${kopf}</span></div>
  <div class="groupContent"><table>
    <tr><th>Datum</th><td>${datum}</td></tr><tr><th>Zeit</th><td>${zeit}</td></tr>
    <tr><th>Ort</th><td>${ort}</td></tr>
    <tr><th>Anmeldung</th><td>${anmeldung}</td></tr>${abmeldung}
  </table>${knopf}</div>
</div>`

const SEITE = `<h1>104.297 Mathematik 1 – Prüfungstermine</h1>
${box({ kopf: 'Schriftliche Prüfung 1. Termin', datum: 'Fr. 23.01.2027', zeit: '09:00 - 11:00', ort: 'Audi Max',
  anmeldung: 'von 01.12.2026 08:00 bis 20.01.2027 23:59', abmeldung: '<tr><th>Abmeldung</th><td>bis 21.01.2027 12:00</td></tr>',
  knopf: '<input type="submit" value="Abmelden" />', id: '4711' })}
${box({ kopf: 'Schriftliche Prüfung 2. Termin', datum: 'Sa. 06.03.2027', zeit: '10:00', ort: 'HS 1 Elektrotechnik',
  anmeldung: 'von 01.02.2027 08:00 bis 03.03.2027 23:59', knopf: '<input type="submit" value="Anmelden" />' })}`

test('Adressen der Prüfungsliste', () => {
  assert.equal(pruefungsListeUrl('104.297', '2026W'),
    'https://tiss.tuwien.ac.at/education/course/examDateList.xhtml?courseNr=104297&semester=2026W')
  assert.deepEqual(listeAusUrl('https://tiss.tuwien.ac.at/education/course/examDateList.xhtml?courseNr=104297&semester=2026W'),
    { nummer: '104.297', semester: '2026W' })
  assert.equal(listeAusUrl('https://tiss.tuwien.ac.at/education/favorites.xhtml'), null)
})

test('Termine aus der TISS-Prüfungsliste: Zeit, Ort, Anmeldefrist, angemeldet', () => {
  const [erster, zweiter] = pruefungenAusHtml(SEITE, '104.297')
  assert.deepEqual(erster, {
    extern_id: 'tiss:4711',
    titel: 'Schriftliche Prüfung 1. Termin',
    start: '2027-01-23T09:00:00',
    ende: '2027-01-23T11:00:00',
    ort: 'Audi Max',
    anmeldung_von: '2026-12-01T08:00:00',
    anmeldung_bis: '2027-01-20T23:59:00',
    abmeldung_bis: '2027-01-21T12:00:00',
    angemeldet: true, // Knopf „Abmelden“
  })
  assert.equal(zweiter.extern_id, 'tiss:104.297:2027-03-06T10:00:00') // ohne TISS-Kennung: Nummer und Zeit
  assert.deepEqual([zweiter.start, zweiter.ende, zweiter.ort, zweiter.angemeldet], ['2027-03-06T10:00:00', null, 'HS 1 Elektrotechnik', false])
  assert.equal(zweiter.anmeldung_von, '2027-02-01T08:00:00')
})

test('Tabelle statt Boxen, Fristen mit eigenen Beschriftungen, Text „Sie sind angemeldet“', () => {
  const html = `<table><tr><th>Termin</th><th>Datum</th><th>Anmeldebeginn</th><th>Anmeldeende</th></tr>
    <tr><td>Mündliche Prüfung</td><td>12.02.2027 14:00 - 18:00</td><td>Anmeldebeginn: 10.01.2027 10:00</td>
        <td>Anmeldeende: 05.02.2027</td><td>Sie sind angemeldet</td></tr>
    <tr><td>Prüfung</td><td>Anmeldung bis 01.03.2027</td><td>05.03.2027</td></tr></table>`
  const [a, b] = pruefungenAusHtml(html, '330.001')
  assert.deepEqual([a.titel, a.start, a.ende, a.anmeldung_von, a.anmeldung_bis, a.angemeldet],
    ['Mündliche Prüfung', '2027-02-12T14:00:00', '2027-02-12T18:00:00', '2027-01-10T10:00:00', '2027-02-05T23:59:00', true])
  // nur Anmeldeschluss, Prüfung ohne Uhrzeit (Standard 9 Uhr, Ende unbekannt)
  assert.deepEqual([b.start, b.ende, b.anmeldung_von, b.anmeldung_bis, b.angemeldet],
    ['2027-03-05T09:00:00', null, null, '2027-03-01T23:59:00', false])
})

test('leere und unlesbare Listen', () => {
  assert.deepEqual(pruefungenAusHtml('<p>Derzeit keine Prüfungstermine.</p>', '1'), [])
  assert.equal(istUnlesbar('<p>Derzeit sind keine aktuellen Prüfungstermine vorhanden.</p>', []), false)
  assert.equal(istUnlesbar('<section>Prüfung am 23.01.2027</section>', []), true) // Daten da, aber kein Block erkannt
  assert.equal(istUnlesbar('<p>Loading...</p>', []), true) // lieber melden als still „0 Termine“
})

// Antwort von TISS beim ersten Aufruf (Aufbau wie im Original, gekürzt)
const HUELLE = `<div id="buffer">Loading...</div><script type="text/javascript">
    var newWindowId = 'uninitializedWindowId';
    var redirectUrl = '\\/education\\/course\\/examDateList.xhtml?semester=2026W\\x26courseNr=104297';
    window.onload = function() { handleWindowId(newWindowId, redirectUrl) }
</script>`

test('TISS-Fenster-ID: Hülle erkennen, Cookie setzen, mit dsrid/dswid neu laden', async () => {
  assert.equal(fensterUmleitung(HUELLE), '/education/course/examDateList.xhtml?semester=2026W&courseNr=104297')
  assert.equal(fensterUmleitung(SEITE), null)
  const cookies = []
  const geholt = []
  const fetchFn = async (url) => {
    geholt.push(url)
    return new Response(url.includes('dswid=') ? SEITE : HUELLE, { status: 200 })
  }
  const html = await tissSeite(pruefungsListeUrl('104.297', '2026W'), {
    fetchFn, cookieSetzen: async (name, wert) => cookies.push([name, wert]), zufall: () => 0.5,
  })
  assert.equal(html, SEITE)
  assert.deepEqual(cookies, [['dsrwid-500', '5500']])
  assert.equal(geholt[1],
    'https://tiss.tuwien.ac.at/education/course/examDateList.xhtml?semester=2026W&courseNr=104297&dsrid=500&dswid=5500')
  // bleibt TISS bei der Hülle, ist das ein Fehler – kein stilles „keine Termine“
  const stur = async () => new Response(HUELLE, { status: 200 })
  await assert.rejects(tissSeite('https://tiss.tuwien.ac.at/x', { fetchFn: stur, cookieSetzen: async () => {} }), /Fenster-ID nicht angenommen/)
})

test('TISS-Login: Login-Seite oder Umleitung zum Login-Server = nicht eingeloggt, Lauf bricht ab', async () => {
  const login = async () => new Response('<form>Passwort vergessen?</form>', { status: 200 })
  await assert.rejects(tissSeite('https://tiss.tuwien.ac.at/x', { fetchFn: login }), TissNichtEingeloggt)
  const umleitung = async () => Promise.reject(new TypeError('Failed to fetch'))
  await assert.rejects(tissSeite('https://tiss.tuwien.ac.at/x', { fetchFn: umleitung }), TissNichtEingeloggt)

  const { hub, aufrufe } = hubMitProtokoll()
  const ergebnis = await tissPruefungenAbrufen({ hub, lvas: [MATHE, { ...MATHE, lva_id: 8 }], fetchFn: login })
  assert.equal(ergebnis.status, 'teilweise')
  assert.deepEqual(aufrufe[0].daten.lvas, []) // nichts gesendet, also auch nichts gelöscht
  assert.deepEqual(aufrufe[0].daten.fehler, ['Nicht in TISS eingeloggt – TISS im Browser öffnen und anmelden.'])
})

function hubMitProtokoll(abruf = { lvas: [] }) {
  const aufrufe = []
  const fetchFn = async (url, optionen) => {
    aufrufe.push({ url, daten: optionen.body ? JSON.parse(optionen.body) : null })
    return new Response(JSON.stringify(url.endsWith('/abruf') ? abruf : { neu: 1 }), { status: 200 })
  }
  return { hub: new Hub({ basis: 'http://hub', schluessel: 'k', fetchFn }), aufrufe }
}

const MATHE = { lva_id: 7, name: 'Mathe', nummern: ['104.297'], semester: ['2026W', '2027S'], tuwel_kurse: [55] }

test('TISS-Abruf: alle Semester, Fehler machen die Liste unvollständig', async () => {
  const { hub, aufrufe } = hubMitProtokoll()
  const geholt = []
  const tiss = async (url, optionen) => {
    geholt.push(url)
    assert.equal(optionen.credentials, 'include')
    return url.includes('2027S') ? new Response('', { status: 404 }) : new Response(SEITE, { status: 200 })
  }
  const ergebnis = await tissPruefungenAbrufen({ hub, lvas: [MATHE], fetchFn: tiss })
  assert.equal(geholt.length, 2)
  assert.deepEqual([ergebnis.status, ergebnis.termine], ['ok', 2])
  const gesendet = aufrufe[0].daten
  assert.equal(aufrufe[0].url, 'http://hub/api/pruefungen/sync')
  assert.deepEqual([gesendet.quelle, gesendet.lvas[0].lva_id, gesendet.lvas[0].vollstaendig, gesendet.lvas[0].termine.length],
    ['tiss', 7, true, 2])

  const kaputt = async () => new Response('Fehler', { status: 500 })
  const teilweise = await tissPruefungenAbrufen({ hub, lvas: [MATHE], fetchFn: kaputt })
  assert.equal(teilweise.status, 'teilweise')
  assert.equal(aufrufe[1].daten.lvas[0].vollstaendig, false) // der Hub löscht dann nichts
  assert.match(aufrufe[1].daten.fehler[0], /Mathe \(104\.297, 2026W\): TISS antwortet mit HTTP 500/)
})

test('geöffnete Prüfungsliste melden (unvollständig, LVA über die Nummer)', async () => {
  const { hub, aufrufe } = hubMitProtokoll({ lvas: [MATHE] })
  const url = 'https://tiss.tuwien.ac.at/education/course/examDateList.xhtml?courseNr=104297&semester=2026W'
  const ergebnis = await tissListeMelden({ hub, html: SEITE, url })
  assert.deepEqual([ergebnis.status, ergebnis.termine], ['ok', 2])
  assert.deepEqual([aufrufe[1].daten.lvas[0].lva_id, aufrufe[1].daten.lvas[0].vollstaendig], [7, false])
  const fremd = await tissListeMelden({ hub, html: SEITE, url: url.replace('104297', '999999') })
  assert.equal(fremd.status, 'unbekannt')
  assert.equal((await tissListeMelden({ hub, html: HUELLE, url })).status, 'laedt') // Hülle: nichts senden
  assert.equal(aufrufe.length, 3)
})

// --- TUWEL-Kalender ----------------------------------------------------------------------------

test('Prüfungen im TUWEL-Kalender erkennen', () => {
  assert.ok(istPruefungsEreignis({ name: 'Prüfung Mathematik 1' }))
  assert.ok(istPruefungsEreignis({ name: '1. Kurztest öffnet', modulename: 'quiz', eventtype: 'open' }))
  assert.ok(istPruefungsEreignis({ name: 'Test 2' }))
  assert.ok(!istPruefungsEreignis({ name: 'Kurztest 1 schließt', modulename: 'quiz', eventtype: 'close' }))
  assert.ok(!istPruefungsEreignis({ name: 'Prüfungseinsicht' }))
  assert.ok(!istPruefungsEreignis({ name: 'Abgabe Übung 3', modulename: 'assign' }))
  assert.ok(!istPruefungsEreignis({ name: 'Vorlesung' }))
})

test('Monatsansichten zu Terminen je LVA, Wiener Zeit', () => {
  const start = Date.UTC(2026, 10, 14, 9, 0) / 1000 // 14.11.2026 10:00 in Wien (MEZ)
  const ereignis = { id: 3, name: '1. Kurztest öffnet', course: { id: 55 }, timestart: start, timeduration: 3600, location: 'online' }
  const monate = [
    { weeks: [{ days: [{ events: [ereignis] }, { events: [{ ...ereignis }] }] }] }, // über zwei Tage: einmal
    { weeks: [{ days: [{ events: [{ id: 4, name: 'Prüfung', course: { id: 99 }, timestart: start }] }] }] }, // fremder Kurs
  ]
  assert.equal(wienIso(Date.UTC(2027, 6, 1, 7, 30) / 1000), '2027-07-01T09:30:00') // Sommerzeit
  assert.deepEqual(tuwelPruefungen(monatsEreignisse(monate), [MATHE]), [{
    lva_id: 7, vollstaendig: true,
    termine: [{ extern_id: 'tuwel:3', titel: '1. Kurztest', start: '2026-11-14T10:00:00', ende: '2026-11-14T11:00:00',
      ort: 'online', angemeldet: false }],
  }])
  assert.deepEqual(monateUm(new Date(2026, 11, 15), 1, 2).map((m) => `${m.monat}/${m.jahr}`), ['11/2026', '12/2026', '1/2027', '2/2027'])
})

test('TUWEL-Abruf: fehlender Monat = unvollständig, abgemeldet = Abbruch', async () => {
  const { hub, aufrufe } = hubMitProtokoll()
  let n = 0
  const tuwel = { kalenderMonat: async () => (n++ === 0 ? Promise.reject(new Error('Zeitüberschreitung')) : { weeks: [] }) }
  const ergebnis = await tuwelPruefungenAbrufen({ hub, tuwel, lvas: [MATHE], heute: new Date(2026, 9, 24) })
  assert.equal(ergebnis.status, 'teilweise')
  assert.deepEqual([aufrufe[0].daten.quelle, aufrufe[0].daten.lvas[0].vollstaendig], ['tuwel', false])
  const abgemeldet = { kalenderMonat: async () => Promise.reject(new NichtEingeloggt()) }
  await assert.rejects(tuwelPruefungenAbrufen({ hub, tuwel: abgemeldet, lvas: [MATHE] }), NichtEingeloggt)
  assert.deepEqual(await tuwelPruefungenAbrufen({ hub, tuwel, lvas: [{ ...MATHE, tuwel_kurse: [] }] }), { status: 'ok', termine: 0 })
})
