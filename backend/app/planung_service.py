"""Verbindet den Verteilungs-Algorithmus mit der Datenbank."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from .feiertage import gesperrte_tage
from .models import (
    ART_FLEXIBEL,
    STANDARD_GEWICHTE,
    STATUS_BESTAETIGT,
    STATUS_VORSCHLAG,
    LERN_BESTAETIGT,
    LERN_VORSCHLAG,
    TYP_ABGABE,
    TYP_PRUEFUNG,
    TYP_UE,
    TYP_VO,
    TYP_VU,
    Arbeitsblock,
    Arbeitsregel,
    Lernblock,
    Lva,
    PersoenlicherTermin,
    Termin,
    VerworfenerVorschlag,
    lies_einstellung,
    setze_einstellung,
)
from .lernaufwand import offene_unterlagen, pruefungen, pruefungstermine, wochenbedarf
from .lva_auswahl import besuchte_lva_ids
from .lernbedarf import BedarfWoche, nachholen_pro_woche
from .lernplanung import LernBedarf, LernRegeln, LernStoff, plane_lernbloecke, stoff_zuteilen
from .planung import (
    PAUSE,
    Arbeitsregeln,
    Gewichte,
    Intervall,
    PlanTermin,
    vereinige,
    verteile_arbeitszeit,
    wochenbeginn,
)

REGEL_ID = 1


class KeineRegelFehler(Exception):
    """Es wurde noch keine Arbeitsregel angelegt."""


def lade_regel(session: Session) -> Arbeitsregel | None:
    return session.get(Arbeitsregel, REGEL_ID)


def regeln_aus_db(regel: Arbeitsregel, woche: date, session: Session | None = None) -> Arbeitsregeln:
    """Baut die Regeln für eine Woche; Feiertage, freie Tage und (mit Session) TISS-Ferien werden gesperrt."""
    montag = wochenbeginn(woche)
    freie = gesperrte_tage(regel.freie_tage or [], montag, montag + timedelta(days=6), session)
    return Arbeitsregeln(
        stunden_pro_woche=regel.stunden_pro_woche,
        tage=frozenset(regel.tage or []),
        bevorzugte_tage=frozenset(regel.bevorzugte_tage or []),
        fruehester_beginn=regel.fruehester_beginn,
        spaetestes_ende=regel.spaetestes_ende,
        min_block=timedelta(minutes=regel.min_block_minuten),
        max_block=timedelta(minutes=regel.max_block_minuten),
        puffer=timedelta(minutes=regel.puffer_minuten),
        freie_tage=frozenset(freie),
        max_tag=timedelta(hours=_oder(regel.max_tag_stunden, 9)),
        lernfenster=timedelta(minutes=_oder(regel.lernfenster_minuten, 120)),
        voller_unitag=timedelta(hours=_oder(regel.voller_unitag_stunden, 6)),
        min_freie_tage=_oder(regel.min_freie_tage, 1),
        gewichte=Gewichte(**{**STANDARD_GEWICHTE, **(regel.gewichte or {})}),
    )


def _oder(wert, standard):
    """Standardwert für Spalten, die in alten Datenbanken NULL sein können."""
    return standard if wert is None else wert


def plan_termin(termin: Termin) -> PlanTermin:
    return PlanTermin(
        start=termin.start,
        ende=termin.ende,
        titel=termin.anzeigename,
        anwesenheitspflicht=termin.hat_anwesenheitspflicht,
        aufzeichnung=termin.wird_aufgezeichnet,
        pruefung=termin.ist_pruefung,
        abgabe=termin.ist_abgabe,
        vorlesung=termin.typ in (TYP_VO, TYP_VU),
        termin_id=termin.id,
    )


def persoenliche_plan_termine(session: Session, von: datetime, bis: datetime) -> list[PlanTermin]:
    """Persönliche Termine (ohne LVA) wie Pflichttermine: weder Arbeit noch Lernen darüber."""
    return [
        PlanTermin(start=p.start, ende=p.ende, titel=p.titel, anwesenheitspflicht=True)
        for p in session.scalars(select(PersoenlicherTermin).where(PersoenlicherTermin.start < bis, PersoenlicherTermin.ende > von))
    ]


def _wochen_grenzen(woche: date) -> tuple[datetime, datetime]:
    start = datetime.combine(wochenbeginn(woche), time())
    return start, start + timedelta(days=7)


def lern_regeln_aus_db(regel: Arbeitsregel, freie_tage: frozenset[date] = frozenset()) -> LernRegeln:
    return LernRegeln(
        freie_tage=freie_tage,
        tage=frozenset(_oder(regel.lern_tage, [0, 1, 2, 3, 4, 5])),
        fruehester_beginn=regel.fruehester_beginn,
        spaetestes_ende=regel.spaetestes_ende,
        min_block=timedelta(minutes=_oder(regel.lern_min_block_minuten, 45)),
        max_block=timedelta(minutes=_oder(regel.lern_max_block_minuten, 120)),
        max_tag=timedelta(hours=_oder(regel.max_tag_stunden, 9)),
    )


def _fristen(session: Session, termine: list[Termin]) -> dict[int, list[datetime]]:
    """Übungen, Abgaben und Prüfungen je LVA – auch die der gleichnamigen LVA (VO und UE haben eigene Nummern)."""
    verwandt: dict[tuple[str, str], list[int]] = defaultdict(list)
    for lva in session.scalars(select(Lva)):
        verwandt[(lva.semester, lva.titel.casefold())].append(lva.id)
    fristen: dict[int, list[datetime]] = defaultdict(list)
    for t in termine:
        if t.typ in (TYP_UE, TYP_ABGABE, TYP_PRUEFUNG):
            for lva_id in verwandt[(t.lva.semester, t.lva.titel.casefold())]:
                fristen[lva_id].append(t.start)
    return fristen


def _besucht(plan_termine: list[PlanTermin]) -> list[PlanTermin]:
    """Termine, zu denen man hingeht: Pflicht, Prüfung oder ohne Aufzeichnung (keine Abgaben)."""
    return [t for t in plan_termine if t.ist_pflicht or (not t.aufzeichnung and not t.abgabe)]


def _verworfen(session: Session, art: str, von: datetime, bis: datetime) -> list[Intervall]:
    return [Intervall(v.start, v.ende) for v in session.scalars(select(VerworfenerVorschlag).where(
        VerworfenerVorschlag.art == art, VerworfenerVorschlag.start < bis, VerworfenerVorschlag.ende > von))]


def _lernbedarf_der_woche(session: Session, regel: Arbeitsregel, woche: date, lern_fest: list[Lernblock]):
    """Wochenbedarf je LVA abzüglich der bestätigten Lernblöcke dieser Woche."""
    eintraege = wochenbedarf(session, woche, regel)
    fest_je_lva: dict[int, int] = defaultdict(int)
    for b in lern_fest:
        fest_je_lva[b.lva_id] += b.geplante_minuten
    bedarf = []
    for b, _ in eintraege:
        pruefung = None
        if b.pruefung and wochenbeginn(b.pruefung) == wochenbeginn(woche):
            lva = session.get(Lva, b.lva_id)
            zeitpunkte = pruefungen(session, lva)
            pruefung = next((z for z in zeitpunkte if z.date() == b.pruefung), None)
        bedarf.append(LernBedarf(b.lva_id, max(b.soll_minuten - fest_je_lva[b.lva_id], 0), b.prioritaet, pruefung))
    return eintraege, bedarf


def _konflikte(plan, eintraege, woche: date, namen: dict[int, str]) -> list[dict]:
    """Je LVA, die wegen Platzmangels hinter den Plan fällt: wie viel und bis wann sie nachholen müsste."""
    ergebnis = []
    daten_je_lva = {b.lva_id: (b, d) for b, d in eintraege}
    for lva_id, minuten in sorted(plan.offen.items(), key=lambda e: namen.get(e[0], "")):
        b, daten = daten_je_lva[lva_id]
        rueckstand = max(b.rueckstand_minuten, 0) + minuten
        pro_woche, bis = nachholen_pro_woche(rueckstand, daten, woche)
        name = namen.get(lva_id, str(lva_id))
        text = f"{name}: {stunden_text(minuten / 60)} Lernen finden diese Woche keinen Platz"
        text += f" – insgesamt {stunden_text(rueckstand / 60)} hinter dem Plan, nachzuholen "
        text += f"bis zur Prüfung am {bis:%d.%m.}" if bis else "bis Semesterende"
        text += f" (etwa +{stunden_text(pro_woche / 60)} pro Woche)"
        ergebnis.append({
            "lva_id": lva_id, "lva_name": name, "fehlend_minuten": minuten, "rueckstand_minuten": rueckstand,
            "nachholen_pro_woche_minuten": pro_woche, "bis": bis, "text": text,
        })
    return ergebnis


def schlage_woche_vor(session: Session, woche: date) -> dict:
    """Ersetzt die offenen Vorschläge einer Woche. Reihenfolge:

    1. Pflichttermine und Prüfungen sind gesetzt.
    2. Arbeit: die Wochenstunden sind Pflicht und werden zuerst verteilt.
    3. Lernen bis zum Wochenbedarf (aus den ECTS) in die verbleibenden Lücken.
    4. Der Rest ist Freizeit.

    Bestätigte (fixierte, verschobene) Blöcke bleiben, verworfene Vorschläge werden nicht wiederholt.
    Reicht die Zeit nicht, wird zuerst die Lernzeit von LVAs ohne nahe Prüfung gekürzt, nie die Arbeit –
    und gemeldet, welche LVA wie viel nachholen müsste.
    """
    regel = lade_regel(session)
    if regel is None:
        raise KeineRegelFehler("Bitte zuerst die Arbeitsregel festlegen.")
    von, bis = _wochen_grenzen(woche)

    session.execute(delete(Arbeitsblock).where(
        Arbeitsblock.status == STATUS_VORSCHLAG, Arbeitsblock.start >= von, Arbeitsblock.start < bis))
    # Vorschläge von Claude (quelle "ki") bleiben stehen, bis du sie bestätigst oder löschst
    session.execute(delete(Lernblock).where(
        Lernblock.status == LERN_VORSCHLAG, Lernblock.quelle != "ki", Lernblock.start >= von, Lernblock.start < bis))
    # bis eine Woche danach laden: Fristen der Folgewoche und Prüfungen am Montag danach
    termine = session.scalars(
        select(Termin).options(joinedload(Termin.lva)).where(Termin.start < bis + timedelta(days=7), Termin.ende > von)
    ).all()
    besucht_ids = besuchte_lva_ids(session)
    termine = [t for t in termine if t.lva_id in besucht_ids]  # ausgeblendete LVAs sperren nichts
    termine_woche = [t for t in termine if t.start < bis + timedelta(days=1)]
    arbeit_fest = list(session.scalars(select(Arbeitsblock).where(
        Arbeitsblock.status == STATUS_BESTAETIGT, Arbeitsblock.start < bis, Arbeitsblock.ende > von)))
    lern_fest = list(session.scalars(select(Lernblock).where(
        (Lernblock.status == LERN_BESTAETIGT) | (Lernblock.quelle == "ki"), Lernblock.start < bis, Lernblock.ende > von)))
    feste_lernzeit = [Intervall(b.start, b.ende) for b in lern_fest]

    # 1./2. Arbeit nach den Pflichtterminen – bestätigte Lernblöcke sind belegt, offene Lernzeit nicht
    regeln = regeln_aus_db(regel, von.date(), session)
    persoenlich = persoenliche_plan_termine(session, von, bis + timedelta(days=1))
    plan_termine = [plan_termin(t) for t in termine_woche] + persoenlich
    feste_arbeit = [Intervall(b.start, b.ende) for b in arbeit_fest]
    verteilung = verteile_arbeitszeit(
        von.date(), regeln, plan_termine, feste_arbeit, feste_lernzeit, _verworfen(session, "arbeit", von, bis))
    neue_bloecke = []
    for vorschlag in verteilung.bloecke:
        notiz = None
        if vorschlag.ueberplante_termine:
            notiz = "Überplant: " + ", ".join(t.titel for t in vorschlag.ueberplante_termine)
        block = Arbeitsblock(
            start=vorschlag.intervall.start, ende=vorschlag.intervall.ende, art=ART_FLEXIBEL,
            status=STATUS_VORSCHLAG, arbeitgeber=regel.arbeitgeber, notiz=notiz,
        )
        session.add(block)
        neue_bloecke.append(block)

    # 3. Lernen in die Lücken, die Termine und Arbeit lassen
    arbeit = feste_arbeit + [v.intervall for v in verteilung.bloecke]
    besucht = _besucht([plan_termin(t) for t in termine] + persoenlich)
    sperren = [t.intervall.erweitert(regeln.puffer) for t in besucht]
    sperren += [b.erweitert(PAUSE) for b in arbeit + feste_lernzeit]
    sperren += _verworfen(session, "lernen", von, bis)
    grundlast: dict[date, timedelta] = defaultdict(timedelta)
    for iv in [t.intervall for t in besucht] + arbeit + feste_lernzeit:
        grundlast[iv.start.date()] += iv.dauer

    eintraege, bedarf = _lernbedarf_der_woche(session, regel, von.date(), lern_fest)
    namen = {lva.id: lva.anzeigename for lva in session.scalars(select(Lva))}
    lernplan = plane_lernbloecke(
        von.date(), lern_regeln_aus_db(regel, regeln.freie_tage), bedarf, sperren, grundlast,
        _fristen(session, list(termine)), namen,
    )
    stoff = [LernStoff(o.dokument_id, o.lva_id, o.titel, o.erschienen, o.minuten) for o in offene_unterlagen(session, von.date())]
    lernphase = frozenset(b.lva_id for b, _ in eintraege if b.lernphase)
    stoff_zuteilen(
        lernplan.bloecke, stoff, {b.lva_id: b.stoff_anteil for b, _ in eintraege}, lernphase,
        offene_altpruefungen(session, lernphase),
    )
    neue_lernbloecke = []
    for v in lernplan.bloecke:
        block = Lernblock(
            lva_id=v.lva_id, start=v.intervall.start, ende=v.intervall.ende, status=LERN_VORSCHLAG,
            thema=", ".join(v.titel)[:500], zuteilung={str(k): m for k, m in v.zuteilung.items()},
        )
        session.add(block)
        neue_lernbloecke.append(block)

    # 4. Konflikte sichtbar machen statt still zu kürzen
    konflikte = _konflikte(lernplan, eintraege, von.date(), namen)
    hinweise = [
        f"{b.lva_name}: keine ECTS eingetragen – bekommt keine Lernzeit (Reiter „LVAs“)" for b, _ in eintraege if b.ohne_ects
    ]
    if verteilung.fehlend > timedelta(0):
        hinweise.append(
            f"Arbeit: {stunden_text(verteilung.fehlend / timedelta(hours=1))} passen auch ohne Lernzeit nicht in die Woche "
            f"(Pflichttermine, Tagesgrenze, erlaubte Zeiten)."
        )
    geplant_je_lva = {lva_id: lernplan.minuten(lva_id) for lva_id in {b.lva_id for b, _ in eintraege}}
    fest_je_lva: dict[int, int] = defaultdict(int)
    for b in lern_fest:
        fest_je_lva[b.lva_id] += b.geplante_minuten
    session.commit()

    def stunden(d: timedelta) -> float:
        return round(d.total_seconds() / 3600, 2)

    return {
        "woche": von.date(),
        "punktzahl": verteilung.punktzahl,
        "begruendungen": verteilung.begruendungen + lernplan.begruendungen,
        "soll_stunden": stunden(verteilung.soll),
        "verplant_stunden": stunden(verteilung.verplant),
        "fehlende_stunden": stunden(verteilung.fehlend),
        "bloecke": neue_bloecke,
        "lernbloecke": neue_lernbloecke,
        "lern_stunden": round(lernplan.minuten() / 60, 2),
        "lern_offen_stunden": round(sum(lernplan.offen.values()) / 60, 2),
        "konflikte": [k["text"] for k in konflikte],
        "rueckstaende": konflikte,
        "hinweise": hinweise,
        "lernbedarf": [
            _bedarf_out(b, geplant_je_lva.get(b.lva_id, 0) + fest_je_lva[b.lva_id]) for b, _ in eintraege
        ],
        "geopferte_termine": [
            {"id": t.termin_id, "titel": t.titel, "start": t.start, "ende": t.ende}
            for t in verteilung.geopferte_termine
        ],
    }


def offene_altpruefungen(session: Session, lva_ids: Iterable[int]) -> dict[int, list[tuple[int, str]]]:
    """Heruntergeladene Altprüfungen aus der MB Cloud, die weder bearbeitet noch schon einem Block zugeteilt sind –
    neueste zuerst. Titel mit Jahr und Hinweis auf eine vorhandene Lösung."""
    from .models import Dokument, MbCloudDatei

    lva_ids = set(lva_ids)
    if not lva_ids:
        return {}
    vergeben = {int(d) for b in session.scalars(select(Lernblock)) for d in (b.zuteilung or {})}
    eintraege = []
    for doc, datei in session.execute(
        select(Dokument, MbCloudDatei).join(MbCloudDatei, MbCloudDatei.dokument_id == Dokument.id).where(
            Dokument.quelle == "mbcloud", Dokument.kategorie == "altpruefung", Dokument.lva_id.in_(lva_ids),
            Dokument.bearbeitet_am.is_(None), MbCloudDatei.duplikat.is_(False),
        )
    ):
        if doc.id in vergeben:
            continue
        # Prüfungsdatum aus dem Namen, sonst das Jahr – nicht das Änderungsdatum der Datei
        sortierung = datei.datum or (date(datei.jahr, 1, 1) if datei.jahr else date.min)
        titel = f"Altprüfung {datei.datum:%d.%m.%Y}" if datei.datum else f"Altprüfung {datei.jahr or ''}".strip()
        titel += f": {doc.dateiname}"
        if datei.gedankenprotokoll:
            titel += " (Gedankenprotokoll)"
        if session.scalar(select(MbCloudDatei.id).where(MbCloudDatei.loesung_zu_id == datei.id).limit(1)):
            titel += " (mit Lösung)"
        eintraege.append((sortierung, datei.jahr_geschaetzt is False, doc.id, doc.lva_id, titel + " – MB Cloud, inoffiziell"))
    ergebnis: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for _, _, dok_id, lva_id, titel in sorted(eintraege, reverse=True):
        ergebnis[lva_id].append((dok_id, titel))
    return ergebnis


def _bedarf_out(b: BedarfWoche, geplant: int) -> dict:
    return {
        "lva_id": b.lva_id, "lva_name": b.lva_name, "gesamt_minuten": b.gesamt_minuten, "plan_minuten": b.plan_minuten,
        "soll_minuten": b.soll_minuten, "geplant_minuten": geplant, "rueckstand_minuten": b.rueckstand_minuten,
        "pruefung": b.pruefung, "lernphase": b.lernphase, "ohne_ects": b.ohne_ects,
    }


# --- Wochenübersicht ---------------------------------------------------------------------------

WACHSTUNDEN_PRO_TAG = 16  # Grundlage für „Freizeit“: wache Stunden minus Uni, Arbeit und Lernen


def wochenuebersicht(session: Session, woche: date, heute: date | None = None) -> dict:
    """Stunden für Uni, Arbeit, Lernen und Freizeit sowie die nächsten Prüfungen als Countdown."""
    heute = heute or date.today()
    von, bis = _wochen_grenzen(woche)
    regel = lade_regel(session)
    besucht_ids = besuchte_lva_ids(session)
    termine = [t for t in session.scalars(
        select(Termin).options(joinedload(Termin.lva)).where(Termin.start < bis, Termin.ende > von)
    ) if t.lva_id in besucht_ids]
    uni = vereinige(t.intervall for t in _besucht([plan_termin(t) for t in termine]))
    arbeit = list(session.scalars(select(Arbeitsblock).where(Arbeitsblock.start < bis, Arbeitsblock.ende > von)))
    lernen = [b for b in session.scalars(select(Lernblock).where(Lernblock.start < bis, Lernblock.ende > von))
              if b.lva_id in besucht_ids]

    def h(minuten: float) -> float:
        return round(minuten / 60, 1)

    uni_min = sum((iv.dauer for iv in uni), timedelta()) / timedelta(minutes=1)
    arbeit_min = sum((b.ende - b.start).total_seconds() / 60 for b in arbeit)
    lern_min = sum(b.geplante_minuten for b in lernen)
    wach = WACHSTUNDEN_PRO_TAG * 7 * 60
    stunden = {
        "uni": h(uni_min), "arbeit": h(arbeit_min), "lernen": h(lern_min),
        "freizeit": h(max(wach - uni_min - arbeit_min - lern_min, 0)), "wach": h(wach),
        "arbeit_soll": regel.stunden_pro_woche if regel else 0,
        "vorschlaege": any(b.status == STATUS_VORSCHLAG for b in arbeit) or any(b.status == LERN_VORSCHLAG for b in lernen),
    }

    pruefungsliste = []
    for lva in session.scalars(select(Lva).where(Lva.id.in_(besucht_ids))):
        for z, quelle in pruefungstermine(session, lva):
            if z.date() >= heute:
                pruefungsliste.append({
                    "lva_id": lva.id, "lva_name": lva.anzeigename, "farbe": lva.farbe, "zeitpunkt": z,
                    "tage": (z.date() - heute).days, "quelle": quelle, "in_dieser_woche": von <= z < bis,
                })
                break  # je LVA nur die nächste Prüfung
    pruefungsliste.sort(key=lambda p: p["zeitpunkt"])

    lernstand = []
    for b, _ in wochenbedarf(session, von.date(), regel):
        geplant = sum(x.geplante_minuten for x in lernen if x.lva_id == b.lva_id)
        lernstand.append(_bedarf_out(b, geplant))
    return {"woche": von.date(), "stunden": stunden, "pruefungen": pruefungsliste, "lernstand": lernstand}


def stunden_text(h: float) -> str:
    return f"{h:.1f}".replace(".", ",") + " h"


def bestaetige_woche(session: Session, woche: date) -> int:
    """Übernimmt alle Vorschläge der Woche (Arbeit und Lernen) als bestätigte Blöcke."""
    von, bis = _wochen_grenzen(woche)
    anzahl = 0
    for modell, vorschlag, fest in (
        (Arbeitsblock, STATUS_VORSCHLAG, STATUS_BESTAETIGT),
        (Lernblock, LERN_VORSCHLAG, LERN_BESTAETIGT),
    ):
        for block in session.scalars(select(modell).where(modell.status == vorschlag, modell.start >= von, modell.start < bis)):
            block.status = fest
            anzahl += 1
    session.commit()
    return anzahl


def verwerfe_woche(session: Session, woche: date) -> int:
    """Löscht die noch nicht bestätigten Vorschläge der Woche (Abbrechen vor der Bestätigung)."""
    von, bis = _wochen_grenzen(woche)
    anzahl = 0
    for modell, vorschlag in ((Arbeitsblock, STATUS_VORSCHLAG), (Lernblock, LERN_VORSCHLAG)):
        anzahl += session.execute(
            delete(modell).where(modell.status == vorschlag, modell.start >= von, modell.start < bis)
        ).rowcount
    # neu anfangen: auch verworfene Plätze dürfen wieder vorgeschlagen werden
    session.execute(delete(VerworfenerVorschlag).where(VerworfenerVorschlag.start >= von, VerworfenerVorschlag.start < bis))
    session.commit()
    return anzahl


def alle_arbeitsvorschlaege_loeschen(session: Session) -> int:
    """Löscht alle noch nicht bestätigten Arbeitszeit-Vorschläge aller Wochen; bestätigte Blöcke bleiben."""
    anzahl = session.execute(delete(Arbeitsblock).where(Arbeitsblock.status == STATUS_VORSCHLAG)).rowcount
    session.execute(delete(VerworfenerVorschlag).where(VerworfenerVorschlag.art == "arbeit"))
    session.commit()
    return anzahl


# Erhöhen, wenn sich der Verteilungs-Algorithmus ändert: offene Vorschläge werden dann neu berechnet
PLANER_VERSION = "3"
PLANUNGSSTAND = "planungsstand"


def _planungsstand(session: Session) -> str:
    return f"{PLANER_VERSION}:{','.join(map(str, sorted(besuchte_lva_ids(session))))}"


def planung_aktuell_halten(session: Session, heute: date | None = None) -> list[date]:
    """Plant offene Vorschläge neu, wenn sie mit einem anderen Planer oder einer anderen Kursauswahl
    entstanden sind (z. B. neuer STEOP-Stand aus TISS, neue LVAs aus dem Import, neue Version)."""
    if lies_einstellung(session, PLANUNGSSTAND) == _planungsstand(session):
        return []
    return auswahl_geaendert(session, heute)


def auswahl_geaendert(session: Session, heute: date | None = None) -> list[date]:
    """Nach Ein-/Ausblenden einer LVA oder geändertem STEOP-Status: Lernvorschläge ausgeblendeter LVAs
    entfernen und die Wochen ab heute, die schon Vorschläge haben, neu planen."""
    ab = datetime.combine(wochenbeginn(heute or date.today()), time())
    besucht = besuchte_lva_ids(session)
    session.execute(delete(Lernblock).where(
        Lernblock.status == LERN_VORSCHLAG, Lernblock.start >= ab, Lernblock.lva_id.not_in(besucht)))
    session.commit()
    wochen = {
        wochenbeginn(start.date())
        for modell, status in ((Arbeitsblock, STATUS_VORSCHLAG), (Lernblock, LERN_VORSCHLAG))
        for start in session.scalars(select(modell.start).where(modell.status == status, modell.start >= ab))
    }
    geplant = plane_wochen_neu(session, wochen, heute)
    setze_einstellung(session, PLANUNGSSTAND, _planungsstand(session))
    session.commit()
    return geplant


def vorschlag_verwerfen(session: Session, art: str, block) -> None:
    """Merkt sich den Platz eines gelöschten Vorschlags, damit er in dieser Woche nicht wiederkommt."""
    session.add(VerworfenerVorschlag(art=art, start=block.start, ende=block.ende))


def rest_neu_planen(session: Session, tag: date) -> bool:
    """Nach Verschieben, Löschen oder Fixieren: plant die übrigen Vorschläge der Woche neu.

    Nur wenn die Woche schon einen Vorschlag hatte – sonst entstehen keine ungefragten Vorschläge.
    Bestätigte Blöcke bleiben, wie sie sind.
    """
    von, bis = _wochen_grenzen(tag)
    hat_vorschlag = any(
        session.scalar(select(modell.id).where(modell.status == status, modell.start >= von, modell.start < bis).limit(1))
        for modell, status in ((Arbeitsblock, STATUS_VORSCHLAG), (Lernblock, LERN_VORSCHLAG))
    ) or session.scalar(select(VerworfenerVorschlag.id).where(
        VerworfenerVorschlag.start >= von, VerworfenerVorschlag.start < bis).limit(1))
    if not hat_vorschlag or lade_regel(session) is None:
        return False
    schlage_woche_vor(session, von.date())
    return True


def plane_wochen_neu(session: Session, wochen: Iterable[date], heute: date | None = None) -> list[date]:
    """Plant nur die betroffenen Wochen ab der aktuellen Woche neu (wenn eine Regel existiert)."""
    if lade_regel(session) is None:
        return []
    ab = wochenbeginn(heute or date.today())
    geplant = []
    for woche in sorted({wochenbeginn(w) for w in wochen}):
        if woche >= ab:
            schlage_woche_vor(session, woche)
            geplant.append(woche)
    return geplant
