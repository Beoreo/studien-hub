import assert from 'node:assert/strict'
import { test } from 'node:test'
import { Hub } from '../hub.js'

function fakeFetch(antworten) {
  const aufrufe = []
  const fetchFn = async (url, optionen) => {
    aufrufe.push({ url, kopf: optionen.headers })
    const daten = antworten[new URL(url).pathname]
    return { ok: daten !== undefined, status: daten === undefined ? 404 : 200, json: async () => daten }
  }
  return { fetchFn, aufrufe }
}

test('Schlüssel automatisch vom Hub holen und „Jetzt synchronisieren“ abfragen', async () => {
  const { fetchFn, aufrufe } = fakeFetch({
    '/api/tuwel/einrichtung': { schluessel: 'abc', ordner: 'x' },
    '/api/tuwel/sync/anforderung': { angefordert: '2026-10-11T21:00:00' },
  })
  const hub = new Hub({ basis: 'http://hub/', fetchFn })
  assert.equal(await hub.schluesselHolen(), 'abc')
  assert.equal(await new Hub({ basis: 'http://hub', schluessel: 'abc', fetchFn }).anforderung(), '2026-10-11T21:00:00')
  assert.equal(aufrufe[0].url, 'http://hub/api/tuwel/einrichtung')
  assert.equal(aufrufe[1].kopf['X-Studienhub-Schluessel'], 'abc')
})
