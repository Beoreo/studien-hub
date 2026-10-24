// Screenshots aller Reiter bei 1440 px und 390 px Breite (Design-Prüfung).
// Aufruf: node scripts/screenshots.mjs <basis-url> <ausgabe-ordner> [reiter,reiter,…]
// Beispiel: node scripts/screenshots.mjs http://127.0.0.1:8000 ../screenshots kalender,lvas
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const BEREICHE = {
  kalender: 'Kalender',
  lvas: 'LVAs',
  pruefungen: 'Prüfungen',
  wissen: 'Wissensstand',
  bericht: 'Wochenbericht',
  arbeit: 'Arbeitszeiten',
  import: 'TISS-Import',
  tuwel: 'TUWEL',
  mbcloud: 'MB Cloud',
  ki: 'KI verbinden',
  status: 'Status',
}
const BREITEN = [1440, 390]

const [basis = 'http://127.0.0.1:8000', ausgabe = 'screenshots', auswahl] = process.argv.slice(2)
const reiter = auswahl ? auswahl.split(',') : Object.keys(BEREICHE)
mkdirSync(ausgabe, { recursive: true })

const browser = await chromium.launch()
for (const breite of BREITEN) {
  const seite = await browser.newPage({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 })
  const fehler = []
  seite.on('pageerror', (e) => fehler.push(e.message))
  await seite.goto(basis, { waitUntil: 'networkidle' })
  for (const id of reiter) {
    // neue Oberfläche: data-bereich; alte: Reiter über die Beschriftung; Bereiche ohne Reiter (Einrichtung) über #id
    const knopf = seite.locator(`[data-bereich="${id}"]`)
    if (!BEREICHE[id]) {
      await seite.goto(`${basis}/#${id}`, { waitUntil: 'networkidle' })
    } else if (await knopf.count()) {
      if (!(await knopf.first().isVisible())) await seite.locator('[data-menue]').click()
      await knopf.first().click()
    } else {
      await seite.locator('header button', { hasText: BEREICHE[id] }).first().click()
    }
    await seite.waitForLoadState('networkidle')
    await seite.waitForTimeout(800)
    const datei = path.join(ausgabe, `${id}-${breite}.png`)
    await seite.screenshot({ path: datei, fullPage: true })
    // horizontales Überlaufen der Seite = etwas ist zu breit
    const ueberlauf = await seite.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    console.log(`${datei}${ueberlauf > 0 ? `  ÜBERLAUF ${ueberlauf}px` : ''}`)
  }
  if (fehler.length) console.log(`Fehler bei ${breite}px:`, fehler)
  await seite.close()
}
await browser.close()
