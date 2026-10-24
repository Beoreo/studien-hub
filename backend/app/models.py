"""Datenmodell der Stufe 1 (siehe KONZEPT.md, Abschnitt „Datenmodell“).

Alles hängt an der LVA; Arbeitsblöcke und Arbeitsregel sind davon unabhängig.
"""

from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Table, Text, Time, UniqueConstraint
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

# Farben, die neue LVAs reihum bekommen: gedämpfte Palette der Oberfläche (frontend/src/design.css, --lva-1 … 10)
STANDARD_FARBEN = [
    "#2a6a8f", "#22786a", "#4c7a2e", "#8a6a12", "#a0531c",
    "#a33a55", "#8e3f86", "#6a4a9e", "#44569e", "#6b7419",
]
# frühere Standardfarben (gleiche Reihenfolge) – beim Start auf die neue Palette umgestellt, eigene Farben bleiben
ALTE_STANDARD_FARBEN = [
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
    typ: Mapped[str | None] = mapped_column(String(12))  # VO, UE, VU … – unterscheidet gleichnamige LVAs
    farbe: Mapped[str] = mapped_column(String(9), default=STANDARD_FARBEN[0])
    steop: Mapped[bool] = mapped_column(Boolean, default=False)
    anwesenheitspflicht: Mapped[bool] = mapped_column(Boolean, default=False)
    aufzeichnung: Mapped[bool] = mapped_column(Boolean, default=False)
    tuwel_kurs_id: Mapped[int | None] = mapped_column(Integer)
    ects: Mapped[float | None] = mapped_column(Float)
    # Abweichungen von STANDARD_LERNPARAMETER, nur gesetzte Schlüssel (gewichten nur den Stoff, nicht die Zeit)
    lernparameter: Mapped[dict | None] = mapped_column(JSON)
    # veraltet: früher selbst eingetragene Prüfungstage – beim Start in Pruefungstermin übernommen (db.py)
    eigene_pruefungen: Mapped[list | None] = mapped_column(JSON)
    # Lernbedarf (lernbedarf.py): Ziel und Regler
    ziel: Mapped[str] = mapped_column(String(10), default="normal")  # bestehen | normal | gut
    bedarf_faktor: Mapped[float] = mapped_column(Float, default=1.0)
    # Lernblöcke nur vor Prüfungen: so viele Wochen vor der Prüfungswoche; None = Arbeitsregel.lernphase_wochen
    lernwochen: Mapped[int | None] = mapped_column(Integer)
    # Besuchen nach Abschluss der STEOP: None = besucht, True/False = manuell ein-/ausgeblendet
    # (solange die STEOP offen ist, entscheidet die Variante, siehe lva_auswahl.py)
    besuchen: Mapped[bool | None] = mapped_column(Boolean)

    termine: Mapped[list["Termin"]] = relationship(back_populates="lva", cascade="all, delete-orphan")
    # Gruppen derselben LVA-Nummer (z. B. UE Gruppe 8 und Plenartermine); VO und UE sind eigene LVAs
    teile: Mapped[list["LvaTeil"]] = relationship(
        back_populates="lva", cascade="all, delete-orphan", order_by="LvaTeil.id"
    )

    @property
    def anzeigename(self) -> str:
        """Eigener Kurzname, sonst Titel mit Typ („Mathematik 1 für MB, WIMB und VT UE“)."""
        if self.kurzname:
            return self.kurzname
        return f"{self.titel} {self.typ}" if self.typ else self.titel


class LvaTeil(Base):
    """Untereintrag einer LVA: eigene Nummer, Typ und Gruppe, eigene Markierungen und eigener TUWEL-Kurs."""

    __tablename__ = "lva_teil"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    nummer: Mapped[str | None] = mapped_column(String(20), index=True)
    typ: Mapped[str | None] = mapped_column(String(12))  # VO, UE, VU, …
    gruppe: Mapped[str | None] = mapped_column(String(100))  # z. B. „Gruppe 8“
    steop: Mapped[bool] = mapped_column(Boolean, default=False)
    anwesenheitspflicht: Mapped[bool] = mapped_column(Boolean, default=False)
    aufzeichnung: Mapped[bool] = mapped_column(Boolean, default=False)
    tuwel_kurs_id: Mapped[int | None] = mapped_column(Integer)

    lva: Mapped[Lva] = relationship(back_populates="teile")

    @property
    def bezeichnung(self) -> str:
        return " ".join(filter(None, [self.typ, self.gruppe])) or "Teil"


class FreierZeitraum(Base):
    """Vorlesungsfreie Zeit aus TISS (Ferien, Rektorstag …): sperrt Arbeit und Lernen wie ein Feiertag."""

    __tablename__ = "freier_zeitraum"

    id: Mapped[int] = mapped_column(primary_key=True)
    tiss_uid: Mapped[str | None] = mapped_column(String(300), unique=True)
    bezeichnung: Mapped[str] = mapped_column(String(300))
    von: Mapped[date] = mapped_column(Date, index=True)
    bis: Mapped[date] = mapped_column(Date)  # einschließlich
    quelle: Mapped[str] = mapped_column(String(10), default="tiss")


class Termin(Base):
    __tablename__ = "termin"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    teil_id: Mapped[int | None] = mapped_column(ForeignKey("lva_teil.id", ondelete="SET NULL"), index=True)
    tiss_uid: Mapped[str | None] = mapped_column(String(300), unique=True)
    typ: Mapped[str] = mapped_column(String(12), default=TYP_SONSTIGE)
    titel: Mapped[str] = mapped_column(String(500), default="")
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    ende: Mapped[datetime] = mapped_column(DateTime)
    ort: Mapped[str | None] = mapped_column(String(300))
    beschreibung: Mapped[str | None] = mapped_column(Text)
    # Abweichungen von den Markierungen des Teils (bzw. der LVA); None = deren Wert gilt
    steop_abweichung: Mapped[bool | None] = mapped_column(Boolean)
    anwesenheit_abweichung: Mapped[bool | None] = mapped_column(Boolean)
    aufzeichnung_abweichung: Mapped[bool | None] = mapped_column(Boolean)
    quelle: Mapped[str] = mapped_column(String(10), default="tiss")
    geaendert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lva: Mapped[Lva] = relationship(back_populates="termine")
    teil: Mapped["LvaTeil | None"] = relationship()

    @property
    def markierungsquelle(self):
        """Teil der LVA, falls bekannt; sonst die LVA selbst (ältere oder manuelle Termine)."""
        return self.teil or self.lva

    @property
    def ist_steop(self) -> bool:
        return self.markierungsquelle.steop if self.steop_abweichung is None else self.steop_abweichung

    @property
    def hat_anwesenheitspflicht(self) -> bool:
        quelle = self.markierungsquelle
        return quelle.anwesenheitspflicht if self.anwesenheit_abweichung is None else self.anwesenheit_abweichung

    @property
    def wird_aufgezeichnet(self) -> bool:
        return self.markierungsquelle.aufzeichnung if self.aufzeichnung_abweichung is None else self.aufzeichnung_abweichung

    @property
    def ist_pruefung(self) -> bool:
        return self.typ == TYP_PRUEFUNG

    @property
    def ist_abgabe(self) -> bool:
        return self.typ == TYP_ABGABE

    @property
    def anzeigename(self) -> str:
        typ = "Prüfung" if self.ist_pruefung else "Abgabe" if self.ist_abgabe else self.typ
        if typ == self.lva.typ and not self.lva.kurzname:
            typ = ""  # steht schon im Namen der LVA
        gruppe = self.teil.gruppe if self.teil and self.teil.gruppe else ""
        return " ".join(filter(None, [self.lva.anzeigename, typ, gruppe]))


class PersoenlicherTermin(Base):
    """Eigener Termin ohne LVA (Arzt, Sport …), im Kalender angelegt: Arbeit und Lernen werden darum herum geplant."""

    __tablename__ = "persoenlicher_termin"

    id: Mapped[int] = mapped_column(primary_key=True)
    titel: Mapped[str] = mapped_column(String(300))
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    ende: Mapped[datetime] = mapped_column(DateTime)
    ort: Mapped[str | None] = mapped_column(String(300))
    notiz: Mapped[str | None] = mapped_column(Text)


PRUEFUNG_TISS = "tiss"  # Prüfungsliste der LVA in TISS (mit Anmeldefrist)
PRUEFUNG_TUWEL = "tuwel"  # Kalender des TUWEL-Kurses
PRUEFUNG_MANUELL = "manuell"  # selbst eingetragen


class Pruefungstermin(Base):
    """Ein möglicher Prüfungstermin einer LVA (pruefungen.py). Der TISS-Feed enthält nur Prüfungen, zu denen man schon
    angemeldet ist; hier stehen alle angebotenen Termine samt Anmeldefrist, dazu eigene."""

    __tablename__ = "pruefungstermin"
    __table_args__ = (UniqueConstraint("quelle", "extern_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    quelle: Mapped[str] = mapped_column(String(10), default=PRUEFUNG_MANUELL)
    extern_id: Mapped[str | None] = mapped_column(String(300))  # Kennung in TISS/TUWEL, None bei eigenen
    titel: Mapped[str] = mapped_column(String(300), default="Prüfung")
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    ende: Mapped[datetime | None] = mapped_column(DateTime)  # None = Uhrzeit unbekannt (ganztägig angezeigt)
    ort: Mapped[str | None] = mapped_column(String(300))
    anmeldung_von: Mapped[datetime | None] = mapped_column(DateTime)
    anmeldung_bis: Mapped[datetime | None] = mapped_column(DateTime)
    abmeldung_bis: Mapped[datetime | None] = mapped_column(DateTime)
    tiss_angemeldet: Mapped[bool] = mapped_column(Boolean, default=False)  # laut TISS-Prüfungsliste angemeldet
    # selbst gewählt (Auswahl „Angemeldet“); None = automatisch: laut TISS angemeldet oder Prüfung im Feed am selben Tag
    angemeldet: Mapped[bool | None] = mapped_column(Boolean)
    bearbeitet: Mapped[bool] = mapped_column(Boolean, default=False)  # Zeiten selbst geändert: Import überschreibt nicht
    ausgeblendet: Mapped[bool] = mapped_column(Boolean, default=False)  # importiert, aber selbst entfernt
    notiz: Mapped[str | None] = mapped_column(Text)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lva: Mapped[Lva] = relationship()


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
    # Lernbedarf = (ECTS × 25 h − Präsenz) × ects_faktor × Ziel × Regler, Lernphase vor jeder Prüfung
    ects_faktor: Mapped[float] = mapped_column(Float, default=0.7)
    lernphase_wochen: Mapped[int] = mapped_column(Integer, default=2)


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
    # Herkunft: "tuwel" (offiziell) oder "mbcloud" (inoffiziell, Fachschaft); für die KI (Stufe 4) und Filter
    quelle: Mapped[str] = mapped_column(String(10), default="tuwel")
    kategorie: Mapped[str | None] = mapped_column(String(20))  # nur MB Cloud: altpruefung, loesung, …
    jahr: Mapped[int | None] = mapped_column(Integer)  # Jahr der Prüfung bzw. der Unterlage
    # Altprüfung durchgerechnet: wann, wie lange, wie viele Punkte
    bearbeitet_am: Mapped[datetime | None] = mapped_column(DateTime)
    bearbeitet_minuten: Mapped[int | None] = mapped_column(Integer)
    punkte: Mapped[float | None] = mapped_column(Float)
    punkte_max: Mapped[float | None] = mapped_column(Float)
    # Stufe 3: Text in Abschnitte zerlegt (Status: None = offen, "fertig", "leer", "fehler") und Transkript
    text_status: Mapped[str | None] = mapped_column(String(10))
    text_pruefsumme: Mapped[str | None] = mapped_column(String(64))  # Fassung, die verarbeitet wurde
    text_fehler: Mapped[str | None] = mapped_column(Text)
    transkript_status: Mapped[str | None] = mapped_column(String(10))  # nur Videos: None, fertig, fehler
    transkript_fehler: Mapped[str | None] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    geaendert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lva: Mapped[Lva] = relationship()


LERN_VORSCHLAG = "vorschlag"
LERN_BESTAETIGT = "bestaetigt"


# --- MB Cloud der Fachschaft (inoffizielle Quelle, siehe mbcloud.py) ------------------------------------

MB_AUTO = "auto"  # sicher über die LVA-Nummer im Ordnernamen
MB_VORSCHLAG = "vorschlag"  # nur ähnlicher Titel: wartet auf Bestätigung
MB_BESTAETIGT = "bestaetigt"  # von Hand bestätigt oder zugeordnet – gilt für alle künftigen Dateien
MB_ABGELEHNT = "abgelehnt"  # nicht verwenden


class MbCloudOrdner(Base):
    """LVA-Ordner der MB Cloud (z. B. „Mechanik 1 VO 309.019“) und seine Zuordnung zu einer LVA."""

    __tablename__ = "mbcloud_ordner"

    id: Mapped[int] = mapped_column(primary_key=True)
    pfad: Mapped[str] = mapped_column(String(1000), unique=True)
    name: Mapped[str] = mapped_column(String(500))
    etag: Mapped[str | None] = mapped_column(String(100))
    gelesen_etag: Mapped[str | None] = mapped_column(String(100))  # Stand des letzten vollständigen Lesens
    groesse: Mapped[int | None] = mapped_column(Integer)
    lva_id: Mapped[int | None] = mapped_column(ForeignKey("lva.id", ondelete="SET NULL"))
    zuordnung: Mapped[str | None] = mapped_column(String(12))
    aehnlichkeit: Mapped[float | None] = mapped_column(Float)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lva: Mapped[Lva | None] = relationship()


class MbCloudDatei(Base):
    """Verzeichniseintrag (Datei oder Unterordner) unterhalb eines LVA-Ordners – nur der Index."""

    __tablename__ = "mbcloud_datei"

    id: Mapped[int] = mapped_column(primary_key=True)
    ordner_id: Mapped[int] = mapped_column(ForeignKey("mbcloud_ordner.id", ondelete="CASCADE"), index=True)
    pfad: Mapped[str] = mapped_column(String(1000), unique=True)
    eltern_pfad: Mapped[str] = mapped_column(String(1000), index=True)
    name: Mapped[str] = mapped_column(String(500))
    ist_ordner: Mapped[bool] = mapped_column(Boolean, default=False)
    groesse: Mapped[int | None] = mapped_column(Integer)
    geaendert: Mapped[datetime | None] = mapped_column(DateTime)
    etag: Mapped[str | None] = mapped_column(String(100))
    kategorie: Mapped[str | None] = mapped_column(String(20))
    datum: Mapped[date | None] = mapped_column(Date)  # Prüfungsdatum aus dem Namen
    jahr: Mapped[int | None] = mapped_column(Integer)
    jahr_geschaetzt: Mapped[bool] = mapped_column(Boolean, default=False)  # nur aus dem Änderungsdatum
    gedankenprotokoll: Mapped[bool] = mapped_column(Boolean, default=False)  # keine Originalangabe
    loesung_zu_id: Mapped[int | None] = mapped_column(ForeignKey("mbcloud_datei.id", ondelete="SET NULL"))
    dokument_id: Mapped[int | None] = mapped_column(ForeignKey("dokument.id", ondelete="SET NULL"))
    duplikat: Mapped[bool] = mapped_column(Boolean, default=False)  # gleicher Inhalt schon vorhanden (z. B. TUWEL)
    zuletzt_gesehen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    ordner: Mapped[MbCloudOrdner] = relationship()
    dokument: Mapped["Dokument | None"] = relationship()


class VerworfenerVorschlag(Base):
    """Gelöschter Vorschlag: dort schlägt der Planer in dieser Woche nichts derselben Art mehr vor."""

    __tablename__ = "verworfener_vorschlag"

    id: Mapped[int] = mapped_column(primary_key=True)
    art: Mapped[str] = mapped_column(String(10))  # arbeit | lernen
    start: Mapped[datetime] = mapped_column(DateTime, index=True)
    ende: Mapped[datetime] = mapped_column(DateTime)


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
    # "hub" = vom Planer, "ki" = von Claude vorgeschlagen (bleibt beim Neuplanen, bis du es bestätigst oder löschst)
    quelle: Mapped[str] = mapped_column(String(10), default="hub")

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


# --- Stufe 3: Abschnitte für die Suche --------------------------------------------------------------

QUELLE_TUWEL = "tuwel"
QUELLE_LECTURETUBE = "lecturetube"
QUELLE_MBCLOUD = "mbcloud"


class Abschnitt(Base):
    """Textstück einer Unterlage (Seite(n) eines Skripts, Folie, Minuten eines Videos) mit Herkunft.

    Das Embedding liegt in der sqlite-vec-Tabelle `abschnitt_vec` (rowid = id), der Volltext in `abschnitt_fts`.
    """

    __tablename__ = "abschnitt"

    id: Mapped[int] = mapped_column(primary_key=True)
    dokument_id: Mapped[int] = mapped_column(ForeignKey("dokument.id", ondelete="CASCADE"), index=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)
    quelle: Mapped[str] = mapped_column(String(12))  # tuwel | lecturetube | mbcloud
    offiziell: Mapped[bool] = mapped_column(Boolean, default=True)
    jahr: Mapped[int | None] = mapped_column(Integer)
    kapitel: Mapped[str | None] = mapped_column(String(300))  # oberste Gliederungsebene
    unterkapitel: Mapped[str | None] = mapped_column(String(500))  # voller Pfad „1 Statik > 1.2 Kräfte“
    seite_von: Mapped[int | None] = mapped_column(Integer)
    seite_bis: Mapped[int | None] = mapped_column(Integer)
    zeit_von: Mapped[int | None] = mapped_column(Integer)  # Sekunden (Videos)
    zeit_bis: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    dokument: Mapped["Dokument"] = relationship()
    lva: Mapped[Lva] = relationship()

    @property
    def fundstelle(self) -> str:
        if self.zeit_von is not None:
            m, s = divmod(self.zeit_von, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02} min"
        if self.seite_von is not None:
            return f"S. {self.seite_von}" + (f"–{self.seite_bis}" if self.seite_bis and self.seite_bis != self.seite_von else "")
        return ""


# --- Stufe 4: Themen, Wissensstand, Lernereignisse ---------------------------------------------------

thema_abschnitt = Table(
    "thema_abschnitt", Base.metadata,
    Column("thema_id", ForeignKey("thema.id", ondelete="CASCADE"), primary_key=True),
    Column("abschnitt_id", ForeignKey("abschnitt.id", ondelete="CASCADE"), primary_key=True),
)


class Thema(Base):
    """Thema einer LVA – abgeleitet aus der Kapitelstruktur der Skripte, im Hub bearbeitbar."""

    __tablename__ = "thema"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    titel: Mapped[str] = mapped_column(String(300))
    reihenfolge: Mapped[int] = mapped_column(Integer, default=0)
    quelle: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manuell | stoff (aus hochgeladenem Prüfungsstoff)
    kapitel: Mapped[str | None] = mapped_column(String(300))  # Kapitel, aus dem es abgeleitet wurde
    # Prüfungstage (ISO), zu deren Stoff das Thema gehört; leer = gilt für alle Prüfungen der LVA
    pruefungen: Mapped[list | None] = mapped_column(JSON)

    lva: Mapped[Lva] = relationship()
    abschnitte: Mapped[list[Abschnitt]] = relationship(secondary=thema_abschnitt)
    wissensstand: Mapped["Wissensstand | None"] = relationship(back_populates="thema", cascade="all, delete-orphan", uselist=False)


class Pruefungsstoff(Base):
    """Hochgeladener Stoff einer Prüfung (Stoffliste, Skript oder Folien); daraus entstehen die Themen der Prüfung."""

    __tablename__ = "pruefungsstoff"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    pruefung_am: Mapped[date] = mapped_column(Date)
    dateiname: Mapped[str] = mapped_column(String(500))
    pfad: Mapped[str] = mapped_column(Text)  # relativ zum Unterlagen-Ordner
    themen: Mapped[int] = mapped_column(Integer, default=0)  # daraus erkannte Themen
    hochgeladen_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Wissensstand(Base):
    """Stufe 0 (neu) bis 4 (sicher) je Thema, mit Wiederholungstermin (verteilte Wiederholung)."""

    __tablename__ = "wissensstand"

    thema_id: Mapped[int] = mapped_column(ForeignKey("thema.id", ondelete="CASCADE"), primary_key=True)
    stufe: Mapped[int] = mapped_column(Integer, default=0)
    letzte_uebung: Mapped[date | None] = mapped_column(Date)
    naechste_wiederholung: Mapped[date | None] = mapped_column(Date)

    thema: Mapped[Thema] = relationship(back_populates="wissensstand")


class Lernereignis(Base):
    """Protokoll: Quiz, Altprüfung, Selbsteinschätzung, Lernblock – mit Datum und Ergebnis."""

    __tablename__ = "lernereignis"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    thema_id: Mapped[int | None] = mapped_column(ForeignKey("thema.id", ondelete="SET NULL"), index=True)
    art: Mapped[str] = mapped_column(String(20))  # quiz | altpruefung | selbsteinschaetzung | lernblock
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    ergebnis: Mapped[float | None] = mapped_column(Float)  # 0–1
    stufe_vorher: Mapped[int | None] = mapped_column(Integer)
    stufe_nachher: Mapped[int | None] = mapped_column(Integer)
    notiz: Mapped[str | None] = mapped_column(Text)
    quelle: Mapped[str] = mapped_column(String(10), default="hub")  # hub | ki

    thema: Mapped["Thema | None"] = relationship()


class Notiz(Base):
    """Notiz zu einer LVA oder einem Thema, z. B. von Claude gespeichert."""

    __tablename__ = "notiz"

    id: Mapped[int] = mapped_column(primary_key=True)
    lva_id: Mapped[int | None] = mapped_column(ForeignKey("lva.id", ondelete="CASCADE"), index=True)
    thema_id: Mapped[int | None] = mapped_column(ForeignKey("thema.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    quelle: Mapped[str] = mapped_column(String(10), default="hub")


class Wochenbericht(Base):
    """Wochenbericht aus den TUWEL-Daten der Woche (wochenbericht.py). Kosten/Runden/Vorschläge stammen aus der
    früheren Claude-Version und bleiben leer."""

    __tablename__ = "wochenbericht"

    id: Mapped[int] = mapped_column(primary_key=True)
    woche: Mapped[date] = mapped_column(Date, index=True)  # Montag der Woche, für die geplant wird
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    status: Mapped[str] = mapped_column(String(10), default="laeuft")  # laeuft | ok | fehler
    text: Mapped[str | None] = mapped_column(Text)  # Markdown
    fehler: Mapped[str | None] = mapped_column(Text)
    kosten_usd: Mapped[float | None] = mapped_column(Float)  # Rechenwert laut Claude Code (mit Abo nicht verrechnet)
    dauer_sekunden: Mapped[float | None] = mapped_column(Float)
    runden: Mapped[int | None] = mapped_column(Integer)
    vorschlaege: Mapped[int] = mapped_column(Integer, default=0)  # angelegte Lernblock-Vorschläge
    anlass: Mapped[str] = mapped_column(String(12), default="zeitplan")  # zeitplan | nachgeholt | manuell
    neue_unterlagen: Mapped[int | None] = mapped_column(Integer)  # neue und geänderte TUWEL-Unterlagen der Woche

