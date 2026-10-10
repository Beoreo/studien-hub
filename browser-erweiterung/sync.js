// Ablauf eines Sync-Laufs: Kurse melden, Inhalte je Kurs abgleichen, angeforderte Dateien hochladen.
import {
  NichtEingeloggt,
  dateiInfoAusUrl,
  dateinameAusKopf,
  istVideoDatei,
  istVideoUrl,
  klassifiziere,
  ohneAbfrage,
  opencastEpisode,
  opencastSerie,
  pluginfileLinks,
  seitenAnalyse,
  zielDerUrlAktivitaet,
  zustandLesen,
} from './lib.js'

/**
 * LectureTube-Aktivität (mod_opencast): eine Serie wird in einzelne Aufzeichnungen zerlegt,
 * eine Einzelepisode direkt gelesen. Unbekannte Seiten bleiben ein einzelner Link mit Hinweis.
 */
async function opencastEintraege(tuwel, akt, basis) {
  const seite = await tuwel.html(akt.url)
  const episoden = opencastSerie(seite.html, tuwel.basis)
  if (episoden.length) {
    return {
      eintraege: episoden.map((ep) => ({
        ...basis,
        art: 'video',
        url: ep.url,
        episode_id: ep.episodeId,
        dateiname: ep.titel,
        datum_text: ep.datumText,
        dauer_text: ep.dauerText,
      })),
      hinweise: [`${akt.name}: ${episoden.length} Aufzeichnungen (LectureTube-Serie, ${episoden[0].form})`],
    }
  }
  const einzeln = opencastEpisode(seite.html)
  if (einzeln?.episodeId) {
    return {
      eintraege: [{
        ...basis,
        art: 'video',
        url: akt.url,
        episode_id: einzeln.episodeId,
        dateiname: einzeln.titel || akt.name,
        dauer_sekunden: einzeln.dauerSekunden,
        medien_url: einzeln.medienUrl,
      }],
      hinweise: [`${akt.name}: Einzelaufzeichnung, Medien von ${einzeln.medienDomains.join(', ') || '–'}`],
    }
  }
  const analyse = seitenAnalyse(seite.html, tuwel.basis)
  return {
    eintraege: [{ ...basis, art: 'video', url: akt.url }],
    hinweise: [
      `${akt.name}: unbekannte Videoseite – Frames: ${analyse.iframes.join(', ') || 'keine'}, ` +
        `LTI: ${analyse.lti ? 'ja' : 'nein'}, Domains: ${analyse.domains.join(', ') || 'keine'}`,
    ],
  }
}

/** Details neuer Aufzeichnungen von ihrer Episodenseite (Dauer, direkte Medien-URL). */
export async function episodenDetails(tuwel, eintraege) {
  const ergaenzt = []
  const domains = new Set()
  for (const e of eintraege) {
    const seite = await tuwel.html(e.url)
    const details = opencastEpisode(seite.html)
    if (!details) continue
    details.medienDomains.forEach((d) => domains.add(d))
    ergaenzt.push({
      ...e,
      dateiname: e.dateiname || details.titel,
      dauer_sekunden: details.dauerSekunden,
      medien_url: details.medienUrl,
    })
  }
  return { ergaenzt, domains: [...domains] }
}

/** Sammelt alle Dateien und Video-Links eines Kurses. */
export async function sammleEintraege(tuwel, kursId, melde = () => {}) {
  const { aktivitaeten } = zustandLesen(await tuwel.kursZustand(kursId))
  const eintraege = []
  const fehler = []
  const hinweise = []
  for (const akt of aktivitaeten) {
    const art = klassifiziere(akt)
    if (!art) continue
    const basis = { cm_id: akt.cmId, abschnitt: akt.abschnitt, aktivitaet: akt.name }
    try {
      if (art === 'opencast' && akt.url) {
        const ergebnis = await opencastEintraege(tuwel, akt, basis)
        eintraege.push(...ergebnis.eintraege)
        hinweise.push(...ergebnis.hinweise)
      } else if (art === 'video') {
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
  return { eintraege, fehler, hinweise }
}

/**
 * Ein kompletter Lauf. `melde(text)` meldet den Fortschritt (hält nebenbei den
 * Service-Worker wach). Liefert { status: 'ok' | 'login' | 'fehler', statistik, meldung }.
 */
export async function synchronisiere({ tuwel, hub, melde = () => {} }) {
  const statistik = { kurse: 0, neu: 0, geaendert: 0, unveraendert: 0, videos: 0, fehler: [], hinweise: [] }
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
        const { eintraege, fehler, hinweise } = await sammleEintraege(tuwel, kurs.id, () => melde(`${titel}: lese Inhalte …`))
        statistik.fehler.push(...fehler.map((f) => `${kurs.name}: ${f}`))
        statistik.hinweise.push(...hinweise.map((h) => `${kurs.lva_name || kurs.name}: ${h}`))
        const abgleich = await hub.inhalt(kurs.id, eintraege)
        statistik.unveraendert += abgleich.unveraendert
        statistik.videos += abgleich.videos_neu

        // Nur für neue Aufzeichnungen ohne Dauer die Episodenseite öffnen
        const offen = eintraege.filter((e) => (abgleich.details || []).includes(e.url))
        if (offen.length) {
          melde(`${titel}: lese ${offen.length} neue Aufzeichnungen …`)
          try {
            const { ergaenzt, domains } = await episodenDetails(tuwel, offen)
            if (ergaenzt.length) await hub.inhalt(kurs.id, ergaenzt, { nachtrag: true })
            if (domains.length) statistik.hinweise.push(`LectureTube-Medien von: ${domains.join(', ')}`)
          } catch (fehler) {
            if (fehler instanceof NichtEingeloggt) throw fehler
            statistik.fehler.push(`${kurs.name}: Details der Aufzeichnungen: ${fehler.message}`)
          }
        }
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
