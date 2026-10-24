// Läuft auf TISS-Seiten: Ist es die Seite „STEOP Status“ oder die Prüfungsliste einer LVA, geht ihr Inhalt an den
// Hintergrund (Auswertung dort). Ändert sich die Seite (Detailansicht aufgeklappt, zu einer Prüfung angemeldet),
// wird erneut gesendet.
;(() => {
  const api = globalThis.browser ?? globalThis.chrome
  const istPruefungsliste = /examDateList/i.test(location.pathname)
  const istSteop = () => /STEOP\s*Status/i.test(document.body?.innerText || '') && !!document.querySelector('table')
  const art = istPruefungsliste ? 'tiss-pruefungen' : istSteop() ? 'tiss-steop' : null
  if (!art) return

  let zuletzt = ''
  const senden = () => {
    const html = document.body.innerHTML
    if (html === zuletzt) return
    zuletzt = html
    api.runtime.sendMessage({ art, html, url: location.href }).catch(() => {})
  }

  let zeitgeber
  new MutationObserver(() => {
    clearTimeout(zeitgeber)
    zeitgeber = setTimeout(senden, 1500)
  }).observe(document.body, { childList: true, subtree: true })
  senden()
})()
