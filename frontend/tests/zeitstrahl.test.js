import assert from 'node:assert/strict'
import { test } from 'node:test'
import { abstandText, anteileMitMindest, tagNummer, zeitstrahl } from '../src/zeitstrahl.js'

const d = (tag, monat, jahr = 2027) => new Date(jahr, monat - 1, tag, 9)
const nah = (a, b) => Math.abs(a - b) < 1e-9

test('Anteile: proportional, aber jeder mindestens der Mindestanteil', () => {
  assert.deepEqual(anteileMitMindest([1, 1], 0.1), [0.5, 0.5])
  const [klein, gross] = anteileMitMindest([1, 99], 0.3)
  assert.ok(nah(klein, 0.3) && nah(gross, 0.7))
  const drei = anteileMitMindest([1, 1, 100], 0.2)
  assert.ok(nah(drei[0], 0.2) && nah(drei[1], 0.2) && nah(drei[2], 0.6))
  assert.ok(nah(anteileMitMindest([3, 7, 1, 40], 0.15).reduce((a, b) => a + b), 1))
})

test('Maßstab passt sich den Abständen an: nahe Termine getrennt, ferne weiter weg, aber nicht linear', () => {
  const { punkte, abschnitte } = zeitstrahl([
    { datum: d(20, 1), name: 'a' },
    { datum: d(23, 1), name: 'b' },
    { datum: d(23, 1, 2027), name: 'b2' }, // gleicher Tag: ein Punkt
    { datum: d(23, 4), name: 'c' },
  ])
  assert.deepEqual(punkte.map((p) => p.eintraege.map((e) => e.name)), [['a'], ['b', 'b2'], ['c']])
  assert.equal(punkte[0].pos, 0)
  assert.equal(punkte[2].pos, 1)
  assert.deepEqual(abschnitte.map((a) => a.tage), [3, 90])
  const kurz = punkte[1].pos - punkte[0].pos
  const lang = punkte[2].pos - punkte[1].pos
  assert.ok(kurz >= 0.3 - 1e-9, 'Mindestabstand für nahe Termine')
  assert.ok(lang > kurz, 'ferner Termin weiter weg')
  assert.ok(lang / kurz < 90 / 3, 'nicht linear gestreckt')
  assert.ok(nah(abschnitte[0].mitte, kurz / 2))
})

test('ohne Abschnitte: ein Punkt in der Mitte, leer bleibt leer', () => {
  assert.deepEqual(zeitstrahl([]), { punkte: [], abschnitte: [] })
  const { punkte } = zeitstrahl([{ datum: d(1, 3) }])
  assert.equal(punkte[0].pos, 0.5)
})

test('Tagesnummer und Abstandstext', () => {
  assert.equal(tagNummer(new Date(2027, 2, 29, 1)) - tagNummer(new Date(2027, 2, 27, 23)), 2) // über die Zeitumstellung
  assert.deepEqual([1, 5, 30, 90].map(abstandText), ['1 Tag', '5 Tage', '4 Wo.', '3 Mon.'])
})
