import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Hub } from '../hub.js'
import { steopAbrufen, steopMelden } from '../tiss-sync.js'

const STEOP_SEITE = `<h1>STEOP Status</h1>
<table><tr><th>Studium</th><th>Abgeschlossen</th><th>Erlaubte Non-STEOP ECTS</th></tr>
<tr><td>033282 Wirtschaftsingenieurwesen - Maschinenbau</td><td><img src="/img/cross.png"></td><td>22.0</td></tr></table>
<h2>Legende</h2><div><img src="/img/check.png"> Abgeschlossen</div><div><img src="/img/cross.png"> Nicht abgeschlossen</div>
<h2>Detailansicht offener STEOPs</h2><div>P1: 1 aus: 330.001 VO Grundlagen</div>`

function hubMitProtokoll() {
  const aufrufe = []
  const fetchFn = async (url, optionen) => {
    aufrufe.push({ url, optionen, daten: JSON.parse(optionen.body) })
    return new Response(JSON.stringify({ uebernommen: true }), { status: 200 })
  }
  return { hub: new Hub({ basis: 'http://hub', schluessel: 'geheim', fetchFn }), aufrufe }
}

test('STEOP-Seite wird ausgewertet und an /api/tiss/steop geschickt', async () => {
  const { hub, aufrufe } = hubMitProtokoll()
  const ergebnis = await steopMelden(hub, STEOP_SEITE)
  assert.deepEqual(
    { status: ergebnis.status, abgeschlossen: ergebnis.abgeschlossen, ects: ergebnis.erlaubte_ects, n: ergebnis.steop_nummern },
    { status: 'ok', abgeschlossen: false, ects: 22, n: 1 },
  )
  assert.equal(aufrufe[0].url, 'http://hub/api/tiss/steop')
  assert.equal(aufrufe[0].optionen.headers['X-Studienhub-Schluessel'], 'geheim')
  assert.deepEqual(aufrufe[0].daten.steop_nummern, ['330.001'])
  assert.equal((await steopMelden(hub, '<h1>Favoriten</h1>')).status, 'keine-steop-seite')
  assert.equal(aufrufe.length, 1)
})

test('Abruf mit der TISS-Sitzung: eingeloggt, ausgeloggt, keine gemerkte Seite', async () => {
  const { hub, aufrufe } = hubMitProtokoll()
  const url = 'https://tiss.tuwien.ac.at/education/steop/status.xhtml'
  let gesendet
  const tiss = (html) => async (adresse, optionen) => {
    gesendet = { adresse, optionen }
    return new Response(html, { status: 200 })
  }
  assert.equal((await steopAbrufen({ hub, url, fetchFn: tiss(STEOP_SEITE) })).status, 'ok')
  assert.equal(gesendet.optionen.credentials, 'include')
  assert.equal((await steopAbrufen({ hub, url, fetchFn: tiss('<form id="login">Anmelden</form>') })).status, 'login')
  assert.equal((await steopAbrufen({ hub, url: undefined })).status, 'unbekannt')
  assert.equal((await steopAbrufen({ hub, url: 'https://boese.example/x' })).status, 'unbekannt')
  assert.equal(aufrufe.length, 1)
})
