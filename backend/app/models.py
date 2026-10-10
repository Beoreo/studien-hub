"""Datenmodell der Stufe 1 (siehe KONZEPT.md, Abschnitt „Datenmodell“).

Alles hängt an der LVA; Arbeitsblöcke und Arbeitsregel sind davon unabhängig.
"""

from datetime import datetime, time

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Terminarten
TYP_VO = "VO"
TYP_UE = "UE"
TYP_VU = "VU"
TYP_PRUEFUNG = "PRUEFUNG"
TYP_SONSTIGE = "SONSTIGE"
TERMIN_TYPEN = [TYP_VO, TYP_UE, TYP_VU, TYP_PRUEFUNG, TYP_SONSTIGE]

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
    def anzeigename(self) -> str:
        typ = "Prüfung" if self.ist_pruefung else self.typ
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


class Einstellung(Base):
    """Einfache Schlüssel-Wert-Einstellungen, z. B. der TISS-iCal-Link."""

    __tablename__ = "einstellung"

    schluessel: Mapped[str] = mapped_column(String(100), primary_key=True)
    wert: Mapped[str | None] = mapped_column(Text)


def lies_einstellung(session, schluessel: str) -> str | None:
    eintrag = session.get(Einstellung, schluessel)
    return eintrag.wert if eintrag else None


def setze_einstellung(session, schluessel: str, wert: str | None) -> None:
    eintrag = session.get(Einstellung, schluessel)
    if eintrag is None:
        session.add(Einstellung(schluessel=schluessel, wert=wert))
    else:
        eintrag.wert = wert
