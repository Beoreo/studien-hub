// LectureTube (mod_opencast): Markup nach templates/series.mustache und output_helper.php des Plugins.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { opencastEpisode, opencastSerie, seitenAnalyse } from '../lib.js'
import { synchronisiere } from '../sync.js'
import { Tuwel } from '../tuwel.js'

const T = 'https://tuwel.tuwien.ac.at'
const ID = (n) => `a1b2c3d4-0000-4000-8000-00000000000${n}`

const KACHELN = `
<ul class="series">
  ${[1, 2, 3, 4]
    .map(
      (n) => `<li class="episode" title="VO ${n} &amp; Übung">
      <a href="${T}/mod/opencast/view.php?id=3053605&amp;e=${ID(n)}">
        <div class="thumbnail"><img src="https://oc.example/thumb${n}.jpg" alt="VO ${n}"/>
          ${n === 4 ? '' : `<span class="duration">1:2${n}:0${n}</span>`}</div>
        <div class="title">VO ${n} &amp; Übung</div>
        <span class="date">${n + 5}.10.2026</span>
      </a></li>`,
    )
    .join('\n')}
</ul>`

const TABELLE = `
<table class="generaltable"><thead><tr><th>Titel</th><th>Dauer</th><th>Datum</th><th></th></tr></thead><tbody>
<tr><td class="cell c0"><a href="${T}/mod/opencast/view.php?id=77&amp;e=${ID(1)}">Kapitel 1</a></td>
    <td class="cell c1">45:07</td><td class="cell c2">06.10.2026</td><td class="cell c3"><i class="icon"></i></td></tr>
<tr><td class="cell c0"><a href="${T}/mod/opencast/view.php?id=77&amp;e=${ID(2)}">Kapitel 2</a></td>
    <td class="cell c1"></td><td class="cell c2">13.10.2026</td><td></td></tr>
</tbody></table>`

const EPISODE = (n, dauer = 4321.5) => `<html><script>window.episode = ${JSON.stringify({
  metadata: { id: ID(n), title: `VO ${n} – mit "Zitat" und } Klammer`, duration: dauer, preview: 'x.jpg' },
  streams: [
    { content: 'presenter', sources: { mp4: [
      { src: `https://oc-presentation.ltcc.tuwien.ac.at/static/${n}/low.mp4`, mimetype: 'video/mp4', res: { w: 640, h: 360 } },
      { src: `https://oc-presentation.ltcc.tuwien.ac.at/static/${n}/high.mp4`, mimetype: 'video/mp4', res: { w: 1920, h: 1080 } },
    ], hls: [{ src: `https://oc-presentation.ltcc.tuwien.ac.at/hls/${n}/master.m3u8`, master: true }] }, type: 'video' },
  ],
})};</script><iframe src="player.html"></iframe></html>`

test('Serienseite in Kachelansicht: alle Aufzeichnungen mit Titel, Datum und Dauer', () => {
  const episoden = opencastSerie(KACHELN)
  assert.equal(episoden.length, 4)
  assert.deepEqual(episoden[0], {
    episodeId: ID(1),
    url: `${T}/mod/opencast/view.php?id=3053605&e=${ID(1)}`,
    titel: 'VO 1 & Übung',
    dauerText: '1:21:01',
    datumText: '6.10.2026',
    form: 'kacheln',
  })
  assert.equal(episoden[3].dauerText, '') // ohne Dauer in der Liste
})

test('Serienseite in Listenansicht (Tabelle)', () => {
  const episoden = opencastSerie(TABELLE)
  assert.deepEqual(
    episoden.map((e) => [e.titel, e.dauerText, e.datumText, e.form]),
    [
      ['Kapitel 1', '45:07', '06.10.2026', 'tabelle'],
      ['Kapitel 2', '', '13.10.2026', 'tabelle'],
    ],
  )
})

test('Episodenseite: window.episode mit Dauer und bester MP4-Quelle', () => {
  const ep = opencastEpisode(EPISODE(2))
  assert.equal(ep.episodeId, ID(2))
  assert.equal(ep.titel, 'VO 2 – mit "Zitat" und } Klammer')
  assert.equal(ep.dauerSekunden, 4322)
  assert.equal(ep.medienUrl, 'https://oc-presentation.ltcc.tuwien.ac.at/static/2/high.mp4')
  assert.deepEqual(ep.medienDomains, ['oc-presentation.ltcc.tuwien.ac.at'])
  assert.equal(opencastEpisode(EPISODE(3, 4321500)).dauerSekunden, 4322) // Millisekunden erkannt
  assert.equal(opencastEpisode('<html>kein Player</html>'), null)
})

test('Analyse unbekannter Videoseiten erkennt LTI und fremde Domains', () => {
  const html = `<form action="https://tool.example/lti/launch" method="post">
    <input name="lti_message_type" value="basic-lti-launch-request"></form>
    <iframe src="https://player.example/embed/1"></iframe>`
  assert.deepEqual(seitenAnalyse(html), {
    iframes: ['player.example'],
    lti: true,
    domains: ['tool.example', 'player.example'],
  })
})

// --- kompletter Lauf mit LectureTube ---------------------------------------------------

function seite(body, url) {
  return { ok: true, status: 200, url, headers: { get: () => null }, text: async () => body, json: async () => JSON.parse(body) }
}

function tuwelMitSerie(aufrufe) {
  const zustand = JSON.stringify({
    section: [{ id: '1', title: 'Vorlesungsaufzeichnungen' }],
    cm: [{ id: '3053605', name: 'LectureTube Videos', module: 'opencast', sectionid: '1', url: `${T}/mod/opencast/view.php?id=3053605` }],
  })
  return async (url, optionen = {}) => {
    aufrufe.push(url)
    if (url === `${T}/my/`) return seite('<script>M.cfg={"sesskey":"S"}</script>', url)
    if (url.includes('service.php')) {
      const [{ methodname }] = JSON.parse(optionen.body)
      return methodname.includes('enrolled')
        ? seite(JSON.stringify([{ error: false, data: { courses: [{ id: 83611, shortname: '104.297-2026W', fullname: 'Mathematik 1' }] } }]), url)
        : seite(JSON.stringify([{ error: false, data: zustand }]), url)
    }
    if (url === `${T}/mod/opencast/view.php?id=3053605`) return seite(KACHELN, url)
    const episode = url.match(/e=a1b2c3d4-0000-4000-8000-00000000000(\d)/)
    if (episode) return seite(EPISODE(Number(episode[1])), url)
    return { ok: false, status: 404, url, headers: { get: () => null } }
  }
}

function hubMitBekannten(bekannteIds) {
  const inhalte = []
  return {
    inhalte,
    pruefen: async () => ({}),
    kurse: async (k) => ({ kurse: k.map((x) => ({ ...x, lva_name: 'Mathe 1', synchronisieren: true })) }),
    inhalt: async (kursId, eintraege, optionen = {}) => {
      inhalte.push(eintraege)
      if (inhalte.length > 1) assert.equal(optionen.nachtrag, true) // Details kommen als Nachtrag
      const neu = eintraege.filter((e) => !bekannteIds.includes(e.episode_id))
      return {
        herunterladen: [],
        unveraendert: 0,
        videos_neu: inhalte.length === 1 ? neu.length : 0,
        // wie der Hub: Details nur für neue Aufzeichnungen ohne Dauer
        details: inhalte.length === 1 ? neu.filter((e) => !e.dauer_text).map((e) => e.url) : [],
      }
    },
    datei: async () => ({ status: 'neu' }),
    ende: async () => {},
    fehler: async () => {},
  }
}

test('Lauf: Serie wird zu einzelnen Aufzeichnungen, Episodenseiten nur für neue ohne Dauer', async () => {
  const aufrufe = []
  const hub = hubMitBekannten([ID(1), ID(2)])
  const ergebnis = await synchronisiere({ tuwel: new Tuwel({ fetchFn: tuwelMitSerie(aufrufe) }), hub })

  assert.equal(ergebnis.status, 'ok')
  const erste = hub.inhalte[0]
  assert.equal(erste.length, 4)
  assert.ok(erste.every((e) => e.art === 'video' && e.cm_id === 3053605 && e.episode_id))
  assert.deepEqual(erste.map((e) => e.dateiname), ['VO 1 & Übung', 'VO 2 & Übung', 'VO 3 & Übung', 'VO 4 & Übung'])
  assert.equal(ergebnis.statistik.videos, 2)

  // Nur Episode 4 (neu und ohne Dauer in der Liste) wird einzeln geöffnet
  assert.deepEqual(aufrufe.filter((u) => u.includes('&e=')), [`${T}/mod/opencast/view.php?id=3053605&e=${ID(4)}`])
  assert.deepEqual(hub.inhalte[1].map((e) => [e.episode_id, e.dauer_sekunden]), [[ID(4), 4322]])
  assert.match(hub.inhalte[1][0].medien_url, /high\.mp4$/)
  assert.ok(ergebnis.statistik.hinweise.some((h) => h.includes('4 Aufzeichnungen')))
  assert.ok(ergebnis.statistik.hinweise.some((h) => h.includes('oc-presentation.ltcc.tuwien.ac.at')))
})
