import assert from 'node:assert/strict'
import { test } from 'node:test'
import { istSteopSeite, kriterienLesen, legendeLesen, steopAusHtml, symbolKennung } from '../tiss.js'

// Nachbau der Seite „STEOP Status“ (Aufbau wie im TISS: Tabelle, Legende, Detailansicht)
function seite({ status = 'cross', icons = 'bild', details = '' } = {}) {
  const symbol = (art) =>
    icons === 'bild'
      ? `<img src="/education/resources/images/${art}.png?v=3" alt="" />`
      : `<span class="ui-icon status-${art}"></span>`
  return `
  <h1>STEOP Status</h1>
  <table class="standard"><thead><tr><th>Studium</th><th>Abgeschlossen</th><th>Erlaubte Non-STEOP ECTS <img src="/i/info.png" title="Info"></th></tr></thead>
  <tbody><tr><td>033282 Wirtschaftsingenieurwesen - Maschinenbau</td><td>${symbol(status)}</td><td>22.0</td></tr></tbody></table>
  <h2>Legende</h2>
  <table><tr><td>${symbol('check')}</td><td>Abgeschlossen</td></tr>
  <tr><td>${symbol('lightning')}</td><td>Von STEOP ausgenommen ("whitelisted")</td></tr>
  <tr><td>${symbol('cross')}</td><td>Nicht abgeschlossen</td></tr></table>
  <h2>Detailansicht offener STEOPs</h2>
  <div class="panel"><h3>033282 - Wirtschaftsingenieurwesen - Maschinenbau</h3>
  <b>STEOP-Bedingung: P4 AND P3 AND P1 AND P2</b>
  <div class="acc">P4: 9 ECTS aus: ${symbol('cross')}${details}</div></div>`
}

test('STEOP-Seite erkennen', () => {
  assert.ok(istSteopSeite(seite()))
  assert.ok(!istSteopSeite('<h1>Favoriten</h1><table></table>'))
  assert.equal(steopAusHtml('<h1>Kalender</h1>'), null)
})

test('Symbole über die Legende deuten – Bilder', () => {
  const legende = legendeLesen(seite())
  assert.equal(legende.get('bild:check.png'), 'abgeschlossen')
  assert.equal(legende.get('bild:lightning.png'), 'ausgenommen')
  assert.equal(legende.get('bild:cross.png'), 'offen')
  assert.equal(symbolKennung('<img src="/a/b/cross.png?x=1">'), 'bild:cross.png')

  const offen = steopAusHtml(seite())
  assert.deepEqual(offen.studien, [
    { studium: '033282 Wirtschaftsingenieurwesen - Maschinenbau', status: 'offen', erlaubte_ects: 22 },
  ])
  assert.equal(offen.abgeschlossen, false)
  assert.equal(offen.erlaubte_ects, 22)
  assert.equal(steopAusHtml(seite({ status: 'check' })).abgeschlossen, true)
  assert.equal(steopAusHtml(seite({ status: 'lightning' })).abgeschlossen, true) // ausgenommen zählt als erledigt
})

test('Symbole über die Legende deuten – CSS-Klassen', () => {
  assert.equal(steopAusHtml(seite({ icons: 'klasse' })).abgeschlossen, false)
  assert.equal(steopAusHtml(seite({ icons: 'klasse', status: 'check' })).studien[0].status, 'abgeschlossen')
})

test('unbekanntes Symbol: Status bleibt offen statt geraten', () => {
  const html = seite().replace('<td><img src="/education/resources/images/cross.png?v=3" alt="" /></td><td>22.0', '<td><img src="/x/neu.svg"></td><td>22.0')
  const ergebnis = steopAusHtml(html)
  assert.equal(ergebnis.studien[0].status, null)
  assert.equal(ergebnis.abgeschlossen, null)
})

const lvaZeile = (nummer, titel, ects, art = 'cross') =>
  `<li><img src="/education/resources/images/${art}.png" alt="" /> ${nummer} VO ${titel} (${ects} ECTS)</li>`

test('Kriterienbaum aus verschachtelten Listen', () => {
  const details = `<ul>
    <li>1 aus: <img src="/education/resources/images/cross.png" alt="" /><ul>
      ${lvaZeile('330.001', 'Grundlagen BWL', '4,0')}${lvaZeile('330.002', 'Grundlagen VWL', '3,0')}</ul></li>
    <li>1 aus: <img src="/education/resources/images/check.png" alt="" /><ul>
      ${lvaZeile('104.297', 'Mathematik 1', '9,0', 'check')}</ul></li>
    <li>Alle aus: <ul>${lvaZeile('302.001', 'Mechanik 1', '6,0')}${lvaZeile('302.002', 'Mechanik 1 UE', '2,0')}</ul></li>
  </ul>`
  const ergebnis = steopAusHtml(seite({ details }))
  assert.equal(ergebnis.verknuepfung, 'AND')
  const [p4] = ergebnis.kriterien
  assert.deepEqual([p4.name, p4.art, p4.wert, p4.erfuellt], ['P4', 'ects', 9, false])
  assert.deepEqual(p4.kinder.map((k) => [k.art, k.wert, k.erfuellt]), [['anzahl', 1, false], ['anzahl', 1, true], ['alle', null, null]])
  assert.deepEqual(p4.kinder[0].kinder, [
    { art: 'lva', nummer: '330.001', titel: 'VO Grundlagen BWL', ects: 4, erfuellt: false },
    { art: 'lva', nummer: '330.002', titel: 'VO Grundlagen VWL', ects: 3, erfuellt: false },
  ])
  assert.equal(p4.kinder[1].kinder[0].erfuellt, true)
  assert.deepEqual(p4.kinder[2].kinder.map((k) => k.nummer), ['302.001', '302.002'])
})

test('Kriterienbaum aus flacher Tabelle: P oben, Kriterien darunter, LVAs beim letzten Kriterium', () => {
  const zeile = (inhalt) => `<tr><td>${inhalt}</td></tr>`
  const html = `<h2>Detailansicht offener STEOPs</h2><b>STEOP-Bedingung: P1 OR P2</b><table>
    ${zeile('P1: 2 aus:')}${zeile('1 aus:')}${zeile('330.001 VO A 4.0 ECTS')}${zeile('Alle aus:')}${zeile('330.002 UE B 2.0 ECTS')}
    ${zeile('P2: 6 ECTS aus:')}${zeile('104.297 VO Mathe 9.0 ECTS')}</table>`
  const kriterien = kriterienLesen(html)
  assert.deepEqual(kriterien.map((k) => [k.name, k.art, k.wert]), [['P1', 'anzahl', 2], ['P2', 'ects', 6]])
  assert.deepEqual(kriterien[0].kinder.map((k) => [k.art, k.kinder.map((l) => l.nummer)]), [['anzahl', ['330.001']], ['alle', ['330.002']]])
  assert.deepEqual(kriterien[1].kinder.map((l) => [l.nummer, l.ects]), [['104.297', 9]])
  assert.equal(steopAusHtml(seite().replace(/<h2>Detailansicht[\s\S]*/, html)).verknuepfung, 'OR')
})

test('Kriterienbaum mit LVAs nur als Titel (ohne Nummer), Status-Symbol vor dem Titel', () => {
  const html = `<h2>Detailansicht offener STEOPs</h2>
    <div class="panel"><h3>033282 - Wirtschaftsingenieurwesen - Maschinenbau</h3><b>STEOP-Bedingung: P3 AND P1</b>
    <div class="acc"><div class="kopf">P3: Alle aus:</div><div class="inhalt"><table>
      <thead><tr><th>LVA</th><th>ECTS</th></tr></thead>
      <tr><td><img src="/i/check.png"></td><td>VO Mechanik 1</td><td>4,0</td></tr>
      <tr><td><img src="/i/cross.png"></td><td>UE Mechanik 1</td><td>2,0</td></tr></table></div></div>
    <div class="acc"><div class="kopf">P1: 1 aus:</div><div class="inhalt"><ul><li>- Grundlagen der BWL</li><li>- Einführung in die VWL</li></ul></div></div>
    </div>`
  const legende = new Map([['bild:check.png', 'abgeschlossen'], ['bild:cross.png', 'offen']])
  const [p3, p1] = kriterienLesen(html, legende)
  assert.deepEqual(p3.kinder.map((k) => [k.nummer, k.titel, k.ects, k.erfuellt]), [
    [null, 'VO Mechanik 1', 4, true],
    [null, 'UE Mechanik 1', 2, false],
  ])
  assert.deepEqual(p1.kinder.map((k) => k.titel), ['Grundlagen der BWL', 'Einführung in die VWL'])
  assert.ok(steopAusHtml(seite()).detail_html.startsWith('Detailansicht'))
})

test('LVA-Nummern der offenen STEOP-Bedingungen (nach dem Aufklappen)', () => {
  assert.deepEqual(steopAusHtml(seite()).steop_nummern, [])
  const details = '<ul><li>330.001 VO Grundlagen der Betriebs- und Unternehmensführung</li><li>104.297 VO Mathematik 1</li><li>330.001 doppelt</li></ul>'
  assert.deepEqual(steopAusHtml(seite({ details })).steop_nummern, ['330.001', '104.297'])
})
