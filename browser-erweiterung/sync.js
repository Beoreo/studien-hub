// Ablauf eines Sync-Laufs: Kurse melden, Inhalte je Kurs abgleichen, angeforderte Dateien hochladen.
import {
  NichtEingeloggt,
  dateiInfoAusUrl,
  dateinameAusKopf,
  istVideoDatei,
  istVideoUrl,
  klassifiziere,
  ohneAbfrage,
  pluginfileLinks,
  zielDerUrlAktivitaet,
  zustandLesen,
} from './lib.js'

/** Sammelt alle Dateien und Video-Links eines Kurses. */
export async function sammleEintraege(tuwel, kursId, melde = () => {}) {
  const { aktivitaeten } = zustandLesen(await tuwel.kursZustand(kursId))
  const eintraege = []
  const fehler = []
  for (const akt of aktivitaeten) {
    const art = klassifiziere(akt)
    if (!art) continue
    const basis = { cm_id: akt.cmId, abschnitt: akt.abschnitt, aktivitaet: akt.name }
    try {
      if (art === 'video') {
        if (akt.url) eintraege.push({ ...basis, art: 'video', url: akt.url })
      } else if (art === 'datei') {
        const ziel = await tuwel.aufloesen(`${tuwel.basis}/mod/resource/view.php?id=${akt.cmId}&redirect=1`)
        const info = dateiInfoAusUrl(ziel.url)
        const dateiname = dateinameAusKopf(ziel.disposition) || info.dateiname
        if (istVideoDatei(dateiname, ziel.inhaltstyp)) eintraege.push({ ...basis, art: 'video', url: ohneAbfrage(ziel.url) })
        else eintraege.push({ ...basis, art: 'datei', url: ohneAbfrage(ziel.url), dateiname, unterordner: '' })
      } else if (art === 'link' && akt.url) {
        const seite = await tuwel.html(akt.url)
        const ziel = zielDerUrlAktivitaet(seite.url, seite.html, tuwel.basis)
        if (ziel && istVideoUrl(ziel)) eintraege.push({ ...basis, art: 'video', url: ziel })
      } else if (art === 'seite' && akt.url) {
        const seite = await tuwel.html(akt.url)
        for (const link of pluginfileLinks(seite.html, tuwel.basis)) {
          if (istVideoDatei(link.dateiname)) eintraege.push({ ...basis, art: 'video', url: link.url })
          else eintraege.push({ ...basis, art: 'datei', url: link.url, dateiname: link.dateiname, unterordner: link.unterordner })
        }
      }
    } catch (fehlerObjekt) {
      if (fehlerObjekt instanceof NichtEingeloggt) throw fehlerObjekt
      fehler.push(`${akt.name}: ${fehlerObjekt.message}`)
    }
    melde()
  }
  return { eintraege, fehler }
}

/**
 * Ein kompletter Lauf. `melde(text)` meldet den Fortschritt (hält nebenbei den
 * Service-Worker wach). Liefert { status: 'ok' | 'login' | 'fehler', statistik, meldung }.
 */
export async function synchronisiere({ tuwel, hub, melde = () => {} }) {
  const statistik = { kurse: 0, neu: 0, geaendert: 0, unveraendert: 0, videos: 0, fehler: [] }
  try {
    melde('Prüfe Verbindung zum Hub …')
    await hub.pruefen()
    melde('Prüfe TUWEL-Anmeldung …')
    await tuwel.anmelden()
  } catch (fehler) {
    if (fehler instanceof NichtEingeloggt) {
      await hub.fehler(fehler.message, 'login').catch(() => {})
      return { status: 'login', statistik, meldung: fehler.message }
    }
    return { status: 'fehler', statistik, meldung: fehler.message }
  }

  try {
    melde('Lese Kursliste …')
    const kurse = await tuwel.kurse()
    const { kurse: zuordnung } = await hub.kurse(
      kurse.map((k) => ({ id: k.id, kurzname: k.shortname || '', name: k.fullname || '', idnumber: k.idnumber || null })),
    )
    const aktiv = zuordnung.filter((k) => k.synchronisieren)
    for (const [index, kurs] of aktiv.entries()) {
      const titel = `${index + 1}/${aktiv.length} ${kurs.lva_name || kurs.name}`
      melde(`${titel}: lese Inhalte …`)
      try {
        const { eintraege, fehler } = await sammleEintraege(tuwel, kurs.id, () => melde(`${titel}: lese Inhalte …`))
        statistik.fehler.push(...fehler.map((f) => `${kurs.name}: ${f}`))
        const abgleich = await hub.inhalt(kurs.id, eintraege)
        statistik.unveraendert += abgleich.unveraendert
        statistik.videos += abgleich.videos_neu
        for (const [nr, url] of abgleich.herunterladen.entries()) {
          const eintrag = eintraege.find((e) => e.url === url)
          melde(`${titel}: lade ${nr + 1}/${abgleich.herunterladen.length} ${eintrag.dateiname}`)
          try {
            const blob = await tuwel.datei(url)
            const { status } = await hub.datei(kurs.id, eintrag, blob)
            statistik[status] += 1
          } catch (fehler) {
            if (fehler instanceof NichtEingeloggt) throw fehler
            statistik.fehler.push(`${kurs.name}: ${eintrag.dateiname}: ${fehler.message}`)
          }
        }
        statistik.kurse += 1
      } catch (fehler) {
        if (fehler instanceof NichtEingeloggt) throw fehler
        statistik.fehler.push(`${kurs.name}: ${fehler.message}`)
      }
    }
    await hub.ende(statistik)
    return { status: 'ok', statistik, meldung: zusammenfassung(statistik) }
  } catch (fehler) {
    const art = fehler instanceof NichtEingeloggt ? 'login' : 'fehler'
    await hub.fehler(fehler.message, art).catch(() => {})
    return { status: art, statistik, meldung: fehler.message }
  }
}

export function zusammenfassung(s) {
  const teile = [`${s.kurse} Kurse`, `${s.neu} neu`, `${s.geaendert} geändert`, `${s.unveraendert} unverändert`, `${s.videos} neue Videos`]
  if (s.fehler.length) teile.push(`${s.fehler.length} Fehler`)
  return teile.join(', ')
}
