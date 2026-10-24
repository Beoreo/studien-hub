"""STEOP-Kriterien aus TISS auswerten und eine Variante wählen (reine Logik, ohne DB).

TISS beschreibt jede offene STEOP als Baum, z. B. „P4: 9 ECTS aus:“ mit den Kindern „1 aus:“, „1 aus:“, „Alle aus:“,
darunter die LVAs. Die Browser-Erweiterung liest ihn (tiss.js: kriterienLesen) als
    Knoten = {name, art: ects|anzahl|alle, wert, erfuellt, kinder: [Knoten | LVA]}
    LVA    = {art: "lva", nummer, titel, ects, erfuellt}
`erfuellt` True heißt: in TISS schon erledigt; None = unbekannt. Die oberste Ebene (P1, P2 …) ist mit
`verknuepfung` AND oder OR verbunden.

Eine Variante ist eine Menge von LVAs dieses Semesters (Hub-IDs). Gewählt wird die Variante, die möglichst viele
der obersten Kriterien erfüllt und dafür möglichst wenig ECTS braucht. LVAs, die ohnehin Pflicht sind („Alle aus“),
kommen immer dazu, auch wenn ihr Kriterium dieses Semester noch nicht ganz erfüllbar ist.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import combinations

GENAU = 1e-9
MAX_DURCHPROBIEREN = 15  # bis zu so vielen frei wählbaren LVAs werden alle Kombinationen geprüft


def blaetter(knoten: list[dict] | dict) -> Iterator[dict]:
    for k in knoten if isinstance(knoten, list) else [knoten]:
        if k.get("art") == "lva":
            yield k
        else:
            yield from blaetter(k.get("kinder") or [])


def nummern(kriterien: list[dict]) -> set[str]:
    return {b["nummer"] for b in blaetter(kriterien) if b.get("nummer")}


def hat_lvas(knoten: dict) -> bool:
    return any(True for _ in blaetter(knoten))


# --- LVAs aus TISS den Hub-LVAs zuordnen ----------------------------------------------------------
# TISS nennt die LVAs je nach Ansicht mit Nummer oder nur mit Titel („VO Mechanik 1“). Jedes Blatt hat einen
# Schlüssel: die Nummer, sonst „titel:<normalisierter Titel>“.

TYPEN = {"vo", "ue", "vu", "lu", "se", "pr", "ex", "pa", "ps", "ko", "sp", "ws", "il", "ak", "ri"}


def titel_normal(titel: str) -> str:
    woerter = "".join(z if z.isalnum() else " " for z in (titel or "").casefold()).split()
    woerter = [w for w in woerter if w not in TYPEN and not (len(w) == 5 and w[:4].isdigit() and w[4] in "ws")]
    return " ".join(woerter)


def schluessel(blatt: dict) -> str:
    """Nummer, sonst „titel:[typ:]titel“ – der Typ trennt VO und UE gleichen Titels."""
    if blatt.get("nummer"):
        return blatt["nummer"]
    typ = blatt_typ(blatt.get("titel") or "")
    return f"titel:{typ + ':' if typ else ''}{titel_normal(blatt.get('titel') or '')}"


def blatt_typ(titel: str) -> str | None:
    """Typ-Kürzel im Titel eines Blatts („UE Mechanik 1“ -> „ue“)."""
    woerter = "".join(z if z.isalnum() else " " for z in (titel or "").casefold()).split()
    return next((w for w in woerter if w in TYPEN), None)


def zuordnen(kriterien: list[dict], lvas: list[tuple]) -> dict[int, set[str]]:
    """Hub-LVA-ID -> Schlüssel der Blätter, die sie abdeckt (über die Nummer, sonst über den Titel).
    `lvas` = (ID, Titel, Nummern von LVA und Teilen[, Typ]) des laufenden Semesters. VO und UE gleichen Titels
    sind eigene LVAs: nennt das Blatt einen Typ, gewinnt die LVA dieses Typs."""
    angebot: dict[int, set[str]] = {l[0]: set(l[2]) for l in lvas}
    normal = {l[0]: titel_normal(l[1]) for l in lvas}
    typen = {l[0]: (l[3] or "").casefold() if len(l) > 3 else "" for l in lvas}
    for blatt in blaetter(kriterien):
        if blatt.get("nummer"):
            continue
        gesucht = titel_normal(blatt.get("titel") or "")
        if len(gesucht) < 3:
            continue
        typ = blatt_typ(blatt.get("titel") or "")
        passt = lambda ids: [i for i in ids if typen[i] == typ] or ids if typ else ids  # noqa: E731
        gleich = passt([i for i, t in normal.items() if t == gesucht])
        # sonst: ein Titel enthält den anderen (z. B. „Mechanik 1“ und „Mechanik 1 für WIMB“) – der ähnlichste gewinnt
        enthalten = sorted((abs(len(t) - len(gesucht)), i) for i, t in normal.items()
                           if len(t) >= 3 and (f" {t} " in f" {gesucht} " or f" {gesucht} " in f" {t} "))
        enthalten_ids = passt([i for _, i in enthalten])
        treffer = gleich[:1] or enthalten_ids[:1]
        for i in treffer:
            angebot[i].add(schluessel(blatt))
    return angebot


def _bewerten(knoten: dict, gewaehlt: set[str], ects: dict[str, float]) -> tuple[bool, float]:
    """(erfüllt?, ECTS, die der Knoten zu einem ECTS-Kriterium darüber beiträgt)."""
    if knoten.get("art") == "lva":
        s = schluessel(knoten)
        ok = knoten.get("erfuellt") is True or s in gewaehlt
        return ok, (knoten.get("ects") or ects.get(s, 0.0)) if ok else 0.0
    kinder = [_bewerten(k, gewaehlt, ects) for k in knoten.get("kinder") or []]
    summe = sum(e for ok, e in kinder if ok)
    art, wert = knoten.get("art"), knoten.get("wert") or 0
    if knoten.get("erfuellt") is True:
        return True, max(summe, wert if art == "ects" else 0)
    if art == "ects":
        ok = summe + GENAU >= wert
    elif art == "anzahl":
        ok = sum(1 for o, _ in kinder if o) >= wert
    else:  # alle
        ok = bool(kinder) and all(o for o, _ in kinder)
    return ok, summe if ok else 0.0


def erfuellte_kriterien(kriterien: list[dict], gewaehlt: set[str], ects: dict[str, float]) -> list[bool]:
    return [_bewerten(k, gewaehlt, ects)[0] for k in kriterien]


def gesamt_erfuellt(kriterien: list[dict], verknuepfung: str, gewaehlt: set[str], ects: dict[str, float]) -> bool:
    erfuellt = erfuellte_kriterien(kriterien, gewaehlt, ects)
    return any(erfuellt) if verknuepfung == "OR" else all(erfuellt)


def pflicht_nummern(kriterien: list[dict], verknuepfung: str = "AND") -> set[str]:
    """LVAs, die in jeder Lösung nötig sind: über „Alle aus“ (oder n aus n) von einer Pflicht-Ebene erreichbar."""
    if verknuepfung == "OR":
        return set()

    def pflicht(knoten: dict, muss: bool) -> set[str]:
        if knoten.get("erfuellt") is True:
            return set()
        if knoten.get("art") == "lva":
            return {schluessel(knoten)} if muss else set()
        kinder = knoten.get("kinder") or []
        alle = knoten.get("art") == "alle" or (knoten.get("art") == "anzahl" and (knoten.get("wert") or 0) >= len(kinder))
        return set().union(*(pflicht(k, muss and alle) for k in kinder)) if kinder else set()

    # oberste Ebene: jedes P-Kriterium selbst ist Pflicht, seine Kinder nur bei „Alle aus“
    return set().union(*(pflicht(k, True) for k in kriterien)) if kriterien else set()


def ects_je_nummer(kriterien: list[dict], angebot: dict[int, set[str]], ects_lva: dict[int, float | None]) -> dict[str, float]:
    """ECTS je Blatt-Schlüssel: aus TISS, sonst die ECTS der Hub-LVA (nur beim ersten Teil, damit VO+UE nicht
    doppelt zählen)."""
    ergebnis: dict[str, float] = {}
    verbucht: set[int] = set()
    for blatt in blaetter(kriterien):
        s = schluessel(blatt)
        if blatt.get("ects") is not None:
            ergebnis[s] = blatt["ects"]
            continue
        lva_id = next((i for i, n in angebot.items() if s in n), None)
        if lva_id is not None and lva_id not in verbucht:
            ergebnis[s] = ects_lva.get(lva_id) or 0.0
            verbucht.add(lva_id)
    return ergebnis


def variante_waehlen(kriterien: list[dict], verknuepfung: str, angebot: dict[int, set[str]],
                     ects_lva: dict[int, float | None]) -> set[int]:
    """Hub-LVAs, die die STEOP-Kriterien bestmöglich erfüllen: meiste erfüllte Kriterien, dann wenigste ECTS,
    dann wenigste LVAs. `angebot` = LVA-ID -> Blatt-Schlüssel, die sie abdeckt (`zuordnen`), laufendes Semester."""
    ects = ects_je_nummer(kriterien, angebot, ects_lva)
    offen = {schluessel(b) for b in blaetter(kriterien) if b.get("erfuellt") is not True}
    kandidaten = sorted(i for i, n in angebot.items() if n & offen)
    pflicht_nr = pflicht_nummern(kriterien, verknuepfung)
    pflicht = {i for i in kandidaten if angebot[i] & pflicht_nr}
    frei = [i for i in kandidaten if i not in pflicht]

    def bewertung(auswahl: set[int]) -> tuple:
        gewaehlt = set().union(*(angebot[i] for i in auswahl)) if auswahl else set()
        erfuellt = erfuellte_kriterien(kriterien, gewaehlt, ects)
        anzahl = int(any(erfuellt)) if verknuepfung == "OR" else sum(erfuellt)
        return (-anzahl, sum(ects_lva.get(i) or 0 for i in auswahl), len(auswahl), sorted(auswahl))

    if len(frei) <= MAX_DURCHPROBIEREN:
        moeglich = (pflicht | set(c) for n in range(len(frei) + 1) for c in combinations(frei, n))
        return min(moeglich, key=bewertung)

    # zu viele Kombinationen: gierig die LVA dazunehmen, die am meisten bringt
    auswahl = set(pflicht)
    while True:
        beste = min((auswahl | {i} for i in frei if i not in auswahl), key=bewertung, default=None)
        if beste is None or bewertung(beste)[0] >= bewertung(auswahl)[0]:
            return auswahl
        auswahl = beste


def auswerten(kriterien: list[dict], angebot: dict[int, set[str]], variante: set[int],
              ects_lva: dict[int, float | None]) -> list[dict]:
    """Kriterienbaum für die Anzeige: je Knoten `erfuellt_variante`, je LVA `lva_id` (None = dieses Semester nicht
    angeboten), `in_variante` und `erledigt` (in TISS schon erfüllt)."""
    ects = ects_je_nummer(kriterien, angebot, ects_lva)
    gewaehlt = set().union(*(angebot[i] for i in variante if i in angebot)) if variante else set()

    def knoten_aus(k: dict) -> dict:
        if k.get("art") == "lva":
            lva_id = next((i for i, n in sorted(angebot.items()) if schluessel(k) in n), None)
            return {**k, "lva_id": lva_id, "in_variante": lva_id in variante, "erledigt": k.get("erfuellt") is True}
        return {**k, "erfuellt_variante": _bewerten(k, gewaehlt, ects)[0],
                "kinder": [knoten_aus(c) for c in k.get("kinder") or []]}

    return [knoten_aus(k) for k in kriterien]
