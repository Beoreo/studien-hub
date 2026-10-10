import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  aenderungenLesen,
  dateiInfoAusUrl,
  dateinameAusKopf,
  istLoginSeite,
  istVideoDatei,
  istVideoUrl,
  klassifiziere,
  pluginfileLinks,
  sesskeyAusHtml,
  zielDerUrlAktivitaet,
  zustandLesen,
} from '../lib.js'

const T = 'https://tuwel.tuwien.ac.at'

test('sesskey und Login-Erkennung', () => {
  const html = '<script>M.cfg = {"wwwroot":"https:\\/\\/tuwel","sesskey":"Ab12Cd34","sessiontimeout":"28800"};</script>'
  assert.equal(sesskeyAusHtml(html), 'Ab12Cd34')
  assert.equal(sesskeyAusHtml('<html></html>'), null)
  assert.equal(istLoginSeite(`${T}/login/index.php`), true)
  assert.equal(istLoginSeite('https://idp.zid.tuwien.ac.at/simplesaml/x'), true)
  assert.equal(istLoginSeite(`${T}/my/`, html), false)
})

test('Videos erkennen', () => {
  assert.ok(istVideoUrl('https://www.youtube.com/watch?v=x'))
  assert.ok(istVideoUrl('https://lecturetube.tuwien.ac.at/videos/123'))
  assert.ok(istVideoUrl(`${T}/pluginfile.php/1/mod_resource/content/1/vo1.mp4?forcedownload=1`))
  assert.ok(!istVideoUrl('https://example.com/skript.pdf'))
  assert.ok(istVideoDatei('aufzeichnung.MP4'))
  assert.ok(istVideoDatei('stream', 'video/webm'))
  assert.ok(!istVideoDatei('folien.pdf', 'application/pdf'))
})

test('Dateiname und Unterordner aus pluginfile-URL', () => {
  assert.deepEqual(dateiInfoAusUrl(`${T}/pluginfile.php/123/mod_folder/content/0/%C3%9Cbung%201/blatt%202.pdf?forcedownload=1`), {
    dateiname: 'blatt 2.pdf',
    unterordner: 'Übung 1',
  })
  assert.deepEqual(dateiInfoAusUrl(`${T}/pluginfile.php/5/mod_resource/content/7/skript.pdf`), {
    dateiname: 'skript.pdf',
    unterordner: '',
  })
})

test('pluginfile-Links aus Ordner- und Aufgabenseiten', () => {
  const html = `
    <a href="${T}/pluginfile.php/11/mod_folder/content/0/a.pdf?forcedownload=1">a</a>
    <a href="${T}/pluginfile.php/11/mod_folder/content/0/a.pdf?forcedownload=1">doppelt</a>
    <a href="/pluginfile.php/12/mod_assign/introattachment/0/blatt1.pdf">rel</a>
    <img src="${T}/pluginfile.php/13/mod_page/content/2/diagramm.png">
    <img src="${T}/pluginfile.php/14/mod_folder/content/0/foto.jpg">
    <img src="${T}/pluginfile.php/1/user/icon/boost/f1">
    <a href="${T}/pluginfile.php/15/mod_folder/content/0/x.pdf?a=1&amp;b=2">amp</a>`
  const links = pluginfileLinks(html)
  assert.deepEqual(
    links.map((l) => l.dateiname),
    ['a.pdf', 'blatt1.pdf', 'foto.jpg', 'x.pdf'], // Bild aus mod_page und Benutzerbild ausgelassen
  )
  assert.equal(links[1].url, `${T}/pluginfile.php/12/mod_assign/introattachment/0/blatt1.pdf`)
  assert.equal(links[0].komponente, 'mod_folder')
})

test('Ziel einer URL-Aktivität', () => {
  assert.equal(zielDerUrlAktivitaet('https://youtu.be/abc', ''), 'https://youtu.be/abc')
  const html = '<div class="urlworkaround">Klicken Sie auf <a href="https://lecturetube.tuwien.ac.at/v/1?x=1&amp;y=2">Link</a></div>'
  assert.equal(zielDerUrlAktivitaet(`${T}/mod/url/view.php?id=5`, html), 'https://lecturetube.tuwien.ac.at/v/1?x=1&y=2')
  assert.equal(zielDerUrlAktivitaet(`${T}/mod/url/view.php?id=5`, '<p>nichts</p>'), null)
})

test('Kurszustand lesen und Aktivitäten einordnen', () => {
  const zustand = JSON.stringify({
    section: [
      { id: '10', number: 0, title: 'Allgemeines' },
      { id: '11', number: 1, title: 'Woche 1' },
    ],
    cm: [
      { id: '100', name: 'Skript', module: 'resource', sectionid: '10', url: `${T}/mod/resource/view.php?id=100`, uservisible: true },
      { id: '101', name: 'Übungen', module: 'folder', sectionid: '11', url: `${T}/mod/folder/view.php?id=101` },
      { id: '102', name: 'Forum', module: 'forum', sectionid: '10', url: `${T}/mod/forum/view.php?id=102` },
      { id: '103', name: 'Versteckt', module: 'resource', sectionid: '11', uservisible: false },
      { id: '104', name: 'VO-Aufzeichnung', module: 'opencast', sectionid: '11', url: `${T}/mod/opencast/view.php?id=104` },
    ],
  })
  const { aktivitaeten } = zustandLesen(zustand)
  assert.deepEqual(
    aktivitaeten.map((a) => [a.cmId, a.abschnitt, klassifiziere(a)]),
    [
      [100, 'Allgemeines', 'datei'],
      [101, 'Woche 1', 'seite'],
      [102, 'Allgemeines', null],
      [104, 'Woche 1', 'opencast'],
    ],
  )
  assert.equal(klassifiziere({ modul: 'url' }), 'link')
  assert.equal(klassifiziere({ modul: 'assign' }), 'seite')
})

test('Dateiname aus Content-Disposition', () => {
  assert.equal(dateinameAusKopf("inline; filename=\"skript.pdf\"; filename*=UTF-8''%C3%9Cbung.pdf"), 'Übung.pdf')
  assert.equal(dateinameAusKopf('attachment; filename="folien 1.pdf"'), 'folien 1.pdf')
  assert.equal(dateinameAusKopf(''), null)
})

test('Änderungszeiten aus core_course_get_updates_since', () => {
  const zeiten = aenderungenLesen({ instances: [
    { contextlevel: 'module', id: '5', updates: [{ name: 'configuration', timeupdated: 10 }, { name: 'contentfiles', timeupdated: 20 }] },
    { contextlevel: 'module', id: 6, updates: [{ name: 'introattachmentfiles', timeupdated: 30 }, { name: 'introfiles', timeupdated: 25 }] },
    { contextlevel: 'module', id: 7, updates: [{ name: 'configuration', timeupdated: 40 }] },
    { contextlevel: 'course', id: 1, updates: [] },
  ] })
  assert.deepEqual(zeiten.get(5), { dateien: 20, einstellungen: 10 })
  assert.deepEqual(zeiten.get(6), { dateien: 30, einstellungen: null })
  assert.deepEqual(zeiten.get(7), { dateien: null, einstellungen: 40 })
  assert.equal(zeiten.size, 3)
  assert.equal(aenderungenLesen(null).size, 0)
})
