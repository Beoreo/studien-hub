"""Text aus Unterlagen lesen und in Abschnitte zerlegen (Stufe 3) – ohne Datenbank.

- PDF (PyMuPDF): Text je Seite; Gliederung aus dem Inhaltsverzeichnis der PDF, sonst aus nummerierten
  Überschriften („2.3 Reibung“) im Text.
- PowerPoint/Impress: Text je Folie; Word/Writer: Absätze mit Überschriften als Gliederung.
- Transkripte: Segmente mit Zeitmarken zu Abschnitten von etwa 90 Sekunden.

Ein Abschnitt bleibt innerhalb eines Kapitels und ist höchstens `MAX_ZEICHEN` lang; er trägt Kapitel,
vollen Gliederungspfad und Seite(n) bzw. Zeitmarken.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_ZEICHEN = 1500
MIN_ZEICHEN = 250  # kurze Seiten (Folien) werden mit der nächsten zusammengelegt
TRANSKRIPT_FENSTER = 90  # Sekunden

NUMMERIERTE_UEBERSCHRIFT = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+([A-ZÄÖÜ][^\n]{2,80})$")


@dataclass
class Gliederungspunkt:
    ebene: int
    titel: str
    seite: int


@dataclass
class Text:
    """Gelesene Unterlage: Seiten (Nummer, Text) und Gliederung."""

    seiten: list[tuple[int, str]] = field(default_factory=list)
    gliederung: list[Gliederungspunkt] = field(default_factory=list)
    art: str = "seiten"  # seiten | folien | absaetze


@dataclass
class AbschnittRoh:
    text: str
    kapitel: str | None = None
    unterkapitel: str | None = None
    seite_von: int | None = None
    seite_bis: int | None = None
    zeit_von: int | None = None
    zeit_bis: int | None = None


def bereinigen(text: str) -> str:
    text = text.replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # Silbentrennung am Zeilenende
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --- Lesen ------------------------------------------------------------------------------------------

def pdf_lesen(pfad: Path) -> Text:
    import pymupdf

    ergebnis = Text()
    with pymupdf.open(pfad) as pdf:
        for nr, seite in enumerate(pdf, start=1):
            ergebnis.seiten.append((nr, bereinigen(seite.get_text("text"))))
        ergebnis.gliederung = [Gliederungspunkt(e, t.strip(), max(s, 1)) for e, t, s in pdf.get_toc(simple=True) if t.strip()]
        if pdf.page_count and sum(1 for r in [pdf[i].rect for i in range(min(3, pdf.page_count))] if r.width > r.height) >= 2:
            ergebnis.art = "folien"
        if not ergebnis.gliederung and ergebnis.art != "folien":
            ergebnis.gliederung = ueberschriften_aus_schrift(pdf)
    if not ergebnis.gliederung:
        ergebnis.gliederung = ueberschriften_erkennen(ergebnis.seiten)
    return ergebnis


def ueberschriften_aus_schrift(pdf) -> list[Gliederungspunkt]:
    """Nummerierte Zeilen, die größer oder fett gesetzt sind als der Fließtext – so sind Skripte ohne
    Inhaltsverzeichnis meist gegliedert. Aufzählungen im Fließtext („3. Schritt …“) fallen damit heraus."""
    from collections import Counter

    zeilen, groessen = [], Counter()
    for nr, seite in enumerate(pdf, start=1):
        for block in seite.get_text("dict")["blocks"]:
            for zeile in block.get("lines", []):
                text = "".join(s["text"] for s in zeile["spans"]).strip()
                if not text:
                    continue
                groesse = max(s["size"] for s in zeile["spans"])
                fett = any(s["flags"] & 16 for s in zeile["spans"])
                groessen[round(groesse, 1)] += len(text)
                zeilen.append((nr, text, groesse, fett))
    if not groessen:
        return []
    fliesstext = groessen.most_common(1)[0][0]
    kandidaten = [(nr, text) for nr, text, groesse, fett in zeilen
                  if groesse >= fliesstext * 1.1 and (fett or groesse >= fliesstext * 1.25)]
    return ueberschriften_erkennen([(nr, text) for nr, text in kandidaten])


def ueberschriften_erkennen(seiten: list[tuple[int, str]]) -> list[Gliederungspunkt]:
    """Nummerierte Überschriften in aufsteigender Reihenfolge („1 Einleitung“, „1.2 Kräfte“, „2 Statik“)."""
    punkte: list[Gliederungspunkt] = []
    letzte: tuple[int, ...] = ()
    for nr, text in seiten:
        for zeile in text.splitlines():
            m = NUMMERIERTE_UEBERSCHRIFT.match(zeile.strip())
            if not m or re.search(r"[.,;:=]\s*$|\d{3,}", m[2]):
                continue
            nummer = tuple(int(x) for x in m[1].split("."))
            if letzte and nummer <= letzte:
                continue  # Inhaltsverzeichnis, Aufzählungen, Wiederholungen
            if letzte and nummer[0] > letzte[0] + 1:
                continue  # Sprung: wohl eine Zahl im Fließtext
            punkte.append(Gliederungspunkt(len(nummer), f"{m[1]} {m[2].strip()}", nr))
            letzte = nummer
    return punkte if len([p for p in punkte if p.ebene == 1]) >= 2 else []


def folien_lesen(pfad: Path) -> Text:
    """PowerPoint (.pptx) und Impress (.odp): Text je Folie."""
    ergebnis = Text(art="folien")
    with zipfile.ZipFile(pfad) as z:
        if pfad.suffix.lower() == ".odp":
            inhalt = z.read("content.xml").decode("utf-8", "ignore")
            for nr, seite in enumerate(re.findall(r"<draw:page\b.*?</draw:page>", inhalt, re.S), start=1):
                ergebnis.seiten.append((nr, _xml_text(seite, r"</text:p>")))
        else:
            folien = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                            key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1])[1]))
            for nr, name in enumerate(folien, start=1):
                ergebnis.seiten.append((nr, _xml_text(z.read(name).decode("utf-8", "ignore"), r"</a:p>")))
    return ergebnis


def docx_lesen(pfad: Path) -> Text:
    """Word (.docx): Absätze; Überschriften-Formatvorlagen bilden die Gliederung."""
    ergebnis = Text(art="absaetze")
    with zipfile.ZipFile(pfad) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    absaetze = []
    for nr, absatz in enumerate(re.findall(r"<w:p\b.*?</w:p>", xml, re.S), start=1):
        text = _xml_text(absatz, "")
        if not text:
            continue
        stil = re.search(r'<w:pStyle w:val="(?:Heading|berschrift|Überschrift)(\d)"', absatz)
        if stil:
            ergebnis.gliederung.append(Gliederungspunkt(int(stil[1]), text, len(absaetze) + 1))
        absaetze.append(text)
    # Absätze als „Seiten“ (ohne echte Seitenzahl); Abschnitte bekommen keine Seitenangabe
    ergebnis.seiten = list(enumerate(absaetze, start=1))
    return ergebnis


def _xml_text(xml: str, absatz_ende: str) -> str:
    if absatz_ende:
        xml = re.sub(absatz_ende, "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
    return bereinigen(text)


def lesen(pfad: Path) -> Text | None:
    """None für Formate ohne Text (Bilder, Archive, Programme …)."""
    endung = pfad.suffix.lower()
    if endung == ".pdf":
        return pdf_lesen(pfad)
    if endung in (".pptx", ".ppsx", ".odp"):
        return folien_lesen(pfad)
    if endung == ".docx":
        return docx_lesen(pfad)
    if endung in (".txt", ".md"):
        return Text(seiten=[(1, bereinigen(pfad.read_text(encoding="utf-8", errors="ignore")))])
    return None


# --- Abschnitte ---------------------------------------------------------------------------------------

def _pfad_fuer_seite(gliederung: list[Gliederungspunkt], seite: int) -> list[str]:
    """Gliederungspfad, der auf dieser Seite gilt (letzter Eintrag je Ebene bis zur Seite)."""
    pfad: list[str] = []
    for p in gliederung:
        if p.seite > seite:
            break
        pfad = pfad[: p.ebene - 1] + [p.titel]
    return pfad


def _teilen(text: str, max_zeichen: int) -> list[str]:
    """Lange Texte an Absatz-, sonst Satzgrenzen teilen."""
    if len(text) <= max_zeichen:
        return [text]
    stuecke, aktuell = [], ""
    for teil in re.split(r"(?<=\n\n)|(?<=[.!?])\s+", text):
        if aktuell and len(aktuell) + len(teil) > max_zeichen:
            stuecke.append(aktuell.strip())
            aktuell = ""
        while len(teil) > max_zeichen:  # ein einzelner Riesenabsatz
            stuecke.append(teil[:max_zeichen])
            teil = teil[max_zeichen:]
        aktuell += teil + " "
    if aktuell.strip():
        stuecke.append(aktuell.strip())
    return stuecke


def abschnitte_bilden(gelesen: Text, max_zeichen: int = MAX_ZEICHEN, min_zeichen: int = MIN_ZEICHEN) -> list[AbschnittRoh]:
    """Seiten zu Abschnitten: nie über eine Kapitelgrenze, kurze Seiten zusammenlegen, lange teilen."""
    mit_seiten = gelesen.art != "absaetze"
    abschnitte: list[AbschnittRoh] = []
    puffer: AbschnittRoh | None = None

    def abschliessen():
        nonlocal puffer
        if puffer and puffer.text.strip():
            abschnitte.append(puffer)
        puffer = None

    for nr, text in gelesen.seiten:
        if not text.strip():
            continue
        pfad = _pfad_fuer_seite(gelesen.gliederung, nr)
        kapitel, unterkapitel = (pfad[0] if pfad else None), (" > ".join(pfad) if pfad else None)
        seite = nr if mit_seiten else None
        if puffer and (puffer.kapitel != kapitel or len(puffer.text) >= min_zeichen
                       or len(puffer.text) + len(text) > max_zeichen):
            abschliessen()
        for stueck in _teilen(text, max_zeichen):
            if puffer is None:
                puffer = AbschnittRoh(stueck, kapitel, unterkapitel, seite, seite)
            else:
                puffer.text += "\n\n" + stueck
                puffer.seite_bis = seite
            if len(puffer.text) >= min_zeichen:
                abschliessen()
    abschliessen()
    return abschnitte


def transkript_abschnitte(segmente: list[tuple[float, float, str]], fenster: int = TRANSKRIPT_FENSTER) -> list[AbschnittRoh]:
    """Whisper-Segmente (Start, Ende, Text) zu Abschnitten von etwa `fenster` Sekunden."""
    abschnitte: list[AbschnittRoh] = []
    for start, ende, text in segmente:
        text = text.strip()
        if not text:
            continue
        if abschnitte and start - abschnitte[-1].zeit_von < fenster:
            abschnitte[-1].text += " " + text
            abschnitte[-1].zeit_bis = int(ende)
        else:
            abschnitte.append(AbschnittRoh(text, zeit_von=int(start), zeit_bis=int(ende)))
    return abschnitte
