"""Datenmodell der Stufe 1 (siehe KONZEPT.md, Abschnitt „Datenmodell“).

Alles hängt an der LVA; Arbeitsblöcke und Arbeitsregel sind davon unabhängig.
"""

from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Terminarten
TYP_VO = "VO"
TYP_UE = "UE"
TYP_VU = "VU"
TYP_PRUEFUNG = "PRUEFUNG"
TYP_ABGABE = "ABGABE"
TYP_SONSTIGE = "SONSTIGE"
TERMIN_TYPEN = [TYP_VO, TYP_UE, TYP_VU, TYP_PRUEFUNG, TYP_ABGABE, TYP_SONSTIGE]

# Standardgewichte der Verteilung (je 0–10), siehe planung.Gewichte
STANDARD_GEWICHTE = {"gleichmaessig": 5, "buendeln": 5, "lernzeit": 5, "erholung": 5, "zerstueckelung": 5}

# Lernaufwand je Unterlage (pro LVA überschreibbar, siehe lernaufwand.py)
STANDARD_LERNPARAMETER = {
    "minuten_pro_folie": 2.0,
    "minuten_pro_skriptseite": 6.0,
    "minuten_pro_uebungsblatt": 180.0,
    "video_faktor": 1.5,
    "minuten_sonstiges": 15.0,
}

# Arbeitsblöcke
ART_FIX = "fix"
ART_FLEXIBEL = "flexibel"
STATUS_VORSCHLAG = "vorschlag"
STATUS_BESTAETIGT = "bestaetigt"

# Farben, die neue LVAs reihum bekommen
STANDARD_FARBEN = [
    "#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c",
    "#0891b2", "#ca8a04", "#db2777", "#4f46e5", "#65a30d",
]


class Lva(Base):
    __tablename__ = "lva"
    __table_args__ = (UniqueConstraint("schluessel", "semester"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nummer, falls bekannt, sonst der Titel – identifiziert die LVA beim Import
    schluessel: Mapped[str] = mapped_column(String(300))
    nummer: Mapped[str | None] = mapped_column(String(20))
    titel: Mapped[str] = mapped_column(String(300))
    kurzname: Mapped[str | None] = mapped_column(String(50))
    semester: Mapped[str] = mapped_column(String(10))
    farbe: Mapped[str] = mapped_column(String(9), default=STANDARD_FARBEN[0])
    steop: Mapped[bool] = mapped_column(Boolean, default=False)
    anwesenheitspflicht: Mapped[bool] = mapped_column(Boolean, default=False)
    aufzeichnung: Mapped[bool] = mapped_column(Boolean, default=False)
    tuwel_kurs_id: Mapped[int | None] = mapped_column(Integer)
    ects: Mapped[float | None] = mapped_column(Float)
    # Abweichungen von STANDARD_LERNPARAMETER, nur gesetzte Schlüssel
    lernparameter: Mapped[dict | None] = mapped_column(JSON)

    termine: Mapped[list["Termin"]] = relationship(back_populates="lva", cascade="all, delete-orphan")

    @property
    def anzeigename(self) -> str:
        return self.kurzname or self.titel


class Termin(Base):
    __tablename__ = "termin"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    tiss_uid: Mapped[str | None] = mapped_column(String(300), unique=True)
    typ: Mapped[str] = mapped_column(String(12), default=TYP_SONSTIGE)
    titel: Mapped[str] = mapped_column(String(500), default="")
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    ende: Mapped[datetime] = mapped_column(DateTime)
    ort: Mapped[str | None] = mapped_column(String(300))
    beschreibung: Mapped[str | None] = mapped_column(Text)
    # Abweichungen von den LVA-Markierungen; None = Wert der LVA gilt
    steop_abweichung: Mapped[bool | None] = mapped_column(Boolean)
    anwesenheit_abweichung: Mapped[bool | None] = mapped_column(Boolean)
    aufzeichnung_abweichung: Mapped[bool | None] = mapped_column(Boolean)
    quelle: Mapped[str] = mapped_column(String(10), default="tiss")
    geaendert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lva: Mapped[Lva] = relationship(back_populates="termine")

    @property
    def ist_steop(self) -> bool:
        return self.lva.steop if self.steop_abweichung is None else self.steop_abweichung

    @property
    def hat_anwesenheitspflicht(self) -> bool:
        return self.lva.anwesenheitspflicht if self.anwesenheit_abweichung is None else self.anwesenheit_abweichung

    @property
    def wird_aufgezeichnet(self) -> bool:
        return self.lva.aufzeichnung if self.aufzeichnung_abweichung is None else self.aufzeichnung_abweichung

    @property
    def ist_pruefung(self) -> bool:
        return self.typ == TYP_PRUEFUNG

    @property
    def ist_abgabe(self) -> bool:
        return self.typ == TYP_ABGABE

    @property
    def anzeigename(self) -> str:
        typ = "Prüfung" if self.ist_pruefung else "Abgabe" if self.ist_abgabe else self.typ
        return f"{self.lva.anzeigename} {typ}".strip()


class Arbeitsblock(Base):
    __tablename__ = "arbeitsblock"

    id: Mapped[int] = mapped_column(primary_key=True)
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    ende: Mapped[datetime] = mapped_column(DateTime)
    art: Mapped[str] = mapped_column(String(10), default=ART_FIX)
    status: Mapped[str] = mapped_column(String(12), default=STATUS_BESTAETIGT)
    arbeitgeber: Mapped[str | None] = mapped_column(String(200))
    notiz: Mapped[str | None] = mapped_column(Text)
    # Fixe Zeiten als Serie: alle Blöcke einer Serie teilen diese Kennung
    serie_id: Mapped[str | None] = mapped_column(String(40), index=True)

    @property
    def dauer_stunden(self) -> float:
        return (self.ende - self.start).total_seconds() / 3600


class Arbeitsregel(Base):
    """Regeln für die Verteilung flexibler Stunden. Es gibt genau eine Regel (id=1)."""

    __tablename__ = "arbeitsregel"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Gesamtstunden pro Woche; bestätigte Blöcke werden davon abgezogen
    stunden_pro_woche: Mapped[float] = mapped_column(Float, default=0)
    tage: Mapped[list[int]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])  # 0 = Montag
    bevorzugte_tage: Mapped[list[int]] = mapped_column(JSON, default=list)
    fruehester_beginn: Mapped[time] = mapped_column(Time, default=time(8, 0))
    spaetestes_ende: Mapped[time] = mapped_column(Time, default=time(18, 0))
    min_block_minuten: Mapped[int] = mapped_column(Integer, default=120)
    max_block_minuten: Mapped[int] = mapped_column(Integer, default=480)
    puffer_minuten: Mapped[int] = mapped_column(Integer, default=30)
    arbeitgeber: Mapped[str | None] = mapped_column(String(200))
    # Zusätzliche freie Tage neben den gesetzlichen Feiertagen, z. B. 24.12. oder Urlaub.
    # Einträge: {"von": "JJJJ-MM-TT", "bis": "JJJJ-MM-TT" | None, "bezeichnung": str, "jaehrlich": bool}
    freie_tage: Mapped[list[dict]] = mapped_column(JSON, default=list)
    # Kriterien für eine entspannte Woche (siehe planung.py)
    max_tag_stunden: Mapped[float] = mapped_column(Float, default=9)  # Uni plus Arbeit pro Tag
    lernfenster_minuten: Mapped[int] = mapped_column(Integer, default=120)
    voller_unitag_stunden: Mapped[float] = mapped_column(Float, default=6)
    min_freie_tage: Mapped[int] = mapped_column(Integer, default=1)
    gewichte: Mapped[dict] = mapped_column(JSON, default=lambda: dict(STANDARD_GEWICHTE))
    # Lernblöcke (werden vor der Arbeitszeit geplant)
    lern_min_block_minuten: Mapped[int] = mapped_column(Integer, default=45)
    lern_max_block_minuten: Mapped[int] = mapped_column(Integer, default=120)
    lern_tage: Mapped[list[int]] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4, 5])
    ects_warnschwelle: Mapped[float] = mapped_column(Float, default=0.5)  # ±50 % gilt als starke Abweichung


class Einstellung(Base):
    """Einfache Schlüssel-Wert-Einstellungen, z. B. der TISS-iCal-Link."""

    __tablename__ = "einstellung"

    schluessel: Mapped[str] = mapped_column(String(100), primary_key=True)
    wert: Mapped[str | None] = mapped_column(Text)


# --- Stufe 2: TUWEL-Sync -------------------------------------------------------

ZUORDNUNG_AUTO = "auto"  # automatisch über LVA-Nummer oder Titel
ZUORDNUNG_MANUELL = "manuell"  # in der Oberfläche festgelegt
ZUORDNUNG_AUS = "aus"  # Kurs nicht synchronisieren

DOK_NEU = "neu"
DOK_GEAENDERT = "geaendert"
DOK_UNVERAENDERT = "unveraendert"


class TuwelKurs(Base):
    """Ein TUWEL-Kurs, wie ihn die Browser-Erweiterung meldet, und seine Zuordnung zu einer LVA."""

    __tablename__ = "tuwel_kurs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)  # Moodle-Kurs-ID
    kurzname: Mapped[str] = mapped_column(String(300), default="")
    name: Mapped[str] = mapped_column(String(500), default="")
    idnumber: Mapped[str | None] = mapped_column(String(300))
    lva_id: Mapped[int | None] = mapped_column(ForeignKey("lva.id", ondelete="SET NULL"))
    zuordnung: Mapped[str] = mapped_column(String(10), default=ZUORDNUNG_AUTO)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lva: Mapped[Lva | None] = relationship()


class Dokument(Base):
    """Eine Datei oder ein Video-Link aus TUWEL, abgelegt pro LVA (KONZEPT.md, Datenmodell)."""

    __tablename__ = "dokument"
    __table_args__ = (UniqueConstraint("tuwel_cm_id", "schluessel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    tuwel_kurs_id: Mapped[int] = mapped_column(Integer, index=True)
    tuwel_cm_id: Mapped[int] = mapped_column(Integer)  # Aktivität im Kurs
    # eindeutig je Aktivität: Unterordner/Dateiname, bei Links die URL
    schluessel: Mapped[str] = mapped_column(String(1000))
    abschnitt: Mapped[str] = mapped_column(String(300), default="")
    aktivitaet: Mapped[str] = mapped_column(String(500), default="")
    dateiname: Mapped[str] = mapped_column(String(500))
    typ: Mapped[str] = mapped_column(String(12))  # pdf, folien, dokument, sonstiges, video
    ist_link: Mapped[bool] = mapped_column(Boolean, default=False)  # Video: nur Eintrag, kein Download
    quelle_url: Mapped[str] = mapped_column(Text)
    pfad: Mapped[str | None] = mapped_column(Text)  # relativ zum Unterlagen-Ordner
    pruefsumme: Mapped[str | None] = mapped_column(String(64))  # SHA-256
    groesse: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default=DOK_NEU)  # Ergebnis des letzten Laufs
    # Nur Aufzeichnungen (LectureTube/Opencast): einzelne Episode einer Serie
    episode_id: Mapped[str | None] = mapped_column(String(100))
    aufnahme_am: Mapped[date | None] = mapped_column(Date)
    dauer_sekunden: Mapped[int | None] = mapped_column(Integer)
    medien_url: Mapped[str | None] = mapped_column(Text)  # direkte Videodatei, kann ablaufen
    # Erscheinungsdatum und woher es stammt: "tuwel", "last-modified" oder "aufnahme"
    erschienen_am: Mapped[datetime | None] = mapped_column(DateTime)
    erschienen_quelle: Mapped[str | None] = mapped_column(String(20))
    # Für den Lernaufwand: Seitenzahl und Art ("folien", "skript", "uebung", "video", "sonstiges")
    seiten: Mapped[int | None] = mapped_column(Integer)
    lernart: Mapped[str | None] = mapped_column(String(12))
    # Eigene Lernzeit in Minuten statt der Schätzung (0 = nicht lernen, z. B. Nachschlagematerial)
    lern_minuten: Mapped[int | None] = mapped_column(Integer)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    geaendert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lva: Mapped[Lva] = relationship()


LERN_VORSCHLAG = "vorschlag"
LERN_BESTAETIGT = "bestaetigt"


class Lernblock(Base):
    """Geplante Lernzeit für eine LVA (KONZEPT.md, Datenmodell „Lernblock“)."""

    __tablename__ = "lernblock"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    thema: Mapped[str] = mapped_column(String(500), default="")
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    ende: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(12), default=LERN_VORSCHLAG)
    # Welche Unterlagen der Block abdeckt: {dokument_id: minuten}
    zuteilung: Mapped[dict] = mapped_column(JSON, default=dict)
    erledigt: Mapped[bool] = mapped_column(Boolean, default=False)
    tatsaechliche_minuten: Mapped[int | None] = mapped_column(Integer)  # selbst eingetragen
    notiz: Mapped[str | None] = mapped_column(Text)

    lva: Mapped[Lva] = relationship()

    @property
    def geplante_minuten(self) -> int:
        return int((self.ende - self.start).total_seconds() // 60)


def lies_einstellung(session, schluessel: str) -> str | None:
    eintrag = session.get(Einstellung, schluessel)
    return eintrag.wert if eintrag else None


def setze_einstellung(session, schluessel: str, wert: str | None) -> None:
    eintrag = session.get(Einstellung, schluessel)
    if eintrag is None:
        session.add(Einstellung(schluessel=schluessel, wert=wert))
    else:
        eintrag.wert = wert
