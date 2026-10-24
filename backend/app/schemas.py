"""Pydantic-Schemas für die API."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TeilOut(BaseModel):
    """Untereintrag einer LVA (VO, UE, Gruppe …) mit eigenen Markierungen."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nummer: str | None
    typ: str | None
    gruppe: str | None
    bezeichnung: str
    steop: bool
    anwesenheitspflicht: bool
    aufzeichnung: bool
    tuwel_kurs_id: int | None
    anzahl_termine: int = 0


class TeilUpdate(BaseModel):
    steop: bool | None = None
    anwesenheitspflicht: bool | None = None
    aufzeichnung: bool | None = None
    tuwel_kurs_id: int | None = None
    gruppe: str | None = None


class LvaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nummer: str | None
    titel: str
    kurzname: str | None
    semester: str
    typ: str | None = None  # VO, UE … (VO und UE gleichen Titels sind eigene LVAs)
    farbe: str
    steop: bool
    anwesenheitspflicht: bool
    aufzeichnung: bool
    tuwel_kurs_id: int | None
    anzahl_termine: int = 0
    anzahl_videos: int = 0
    video_dauer_sekunden: int = 0  # Summe der bekannten Dauern
    videos_ohne_dauer: int = 0
    ects: float | None = None
    lernparameter: dict[str, float] | None = None  # mit Standardwerten ergänzt (Stoffgewichtung)
    pruefung: datetime | None = None  # nächste Prüfung (sonst die letzte), zu der man antritt (Reiter „Prüfungen“)
    pruefung_quelle: str | None = None  # tiss | tuwel | manuell | vorschlag (nichts angemeldet: nächster Termin)
    ziel: str = "normal"
    bedarf_faktor: float = 1.0
    lernwochen: int | None = None  # Lernblöcke so viele Wochen vor jeder Prüfung; None = Standard der Arbeitsregel
    lernwochen_standard: int = 2
    besuchen: bool | None = None  # nach Abschluss der STEOP: True eingeblendet, False ausgeblendet, None = automatisch
    besucht: bool = True  # gilt gerade (STEOP offen: Variante, sonst manuell oder alle)
    ist_steop: bool = False  # LVA oder einer ihrer Teile ist STEOP
    gesamtbedarf_minuten: int = 0  # Lernbedarf fürs Semester
    wochenbedarf_minuten: int = 0  # in einer normalen Woche außerhalb der Lernphase
    teile: list[TeilOut] = []

    @field_validator("ziel", mode="before")
    @classmethod
    def _ziel_standard(cls, wert):
        return wert or "normal"

    @field_validator("bedarf_faktor", mode="before")
    @classmethod
    def _faktor_standard(cls, wert):
        return 1.0 if wert is None else wert


class LvaUpdate(BaseModel):
    ects: float | None = Field(None, ge=0, le=60)
    lernparameter: dict[str, float] | None = None  # nur geänderte Werte; leeres Objekt = Standard
    ziel: str | None = Field(None, pattern="^(bestehen|normal|gut)$")
    bedarf_faktor: float | None = Field(None, ge=0, le=3)
    lernwochen: int | None = Field(None, ge=0, le=20)  # null = Standard der Arbeitsregel
    besuchen: bool | None = None  # null = wieder automatisch nach STEOP-Status
    titel: str | None = None
    kurzname: str | None = None
    farbe: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    steop: bool | None = None
    anwesenheitspflicht: bool | None = None
    aufzeichnung: bool | None = None
    tuwel_kurs_id: int | None = None


class PruefungsterminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lva_id: int
    quelle: str  # tiss | tuwel | manuell
    titel: str
    start: datetime
    ende: datetime | None  # None = Uhrzeit unbekannt
    ort: str | None
    anmeldung_von: datetime | None
    anmeldung_bis: datetime | None
    abmeldung_bis: datetime | None
    angemeldet: bool = False  # gilt (selbst gewählt oder automatisch)
    angemeldet_automatisch: bool = True  # nicht selbst gewählt, sondern aus TISS (Liste oder Feed)
    tiss_angemeldet: bool
    bearbeitet: bool
    notiz: str | None
    anmeldestatus: str | None = None  # bald | offen | vorbei


class PruefungenLvaOut(BaseModel):
    lva_id: int
    titel: str
    kurzname: str | None
    typ: str | None = None
    farbe: str
    angemeldet_id: int | None  # erster angemeldeter Termin (Auswahl „Angemeldet“)
    lernwochen: int | None = None  # Lernblöcke so viele Wochen vor jeder Prüfung; None = Standard
    lernwochen_standard: int = 2
    feed_pruefungen: list[datetime] = []  # Prüfungen aus dem TISS-Feed ohne passenden Termin in der Liste
    termine: list[PruefungsterminOut] = []


class PruefungenOut(BaseModel):
    lvas: list[PruefungenLvaOut]
    sync: dict[str, dict | None]  # letzter Import je Quelle (tiss, tuwel)


class PruefungsterminNeu(BaseModel):
    lva_id: int
    titel: str = Field("Prüfung", min_length=1, max_length=300)
    start: datetime
    ende: datetime | None = None
    ort: str | None = Field(None, max_length=300)
    anmeldung_von: datetime | None = None
    anmeldung_bis: datetime | None = None
    abmeldung_bis: datetime | None = None
    angemeldet: bool = True
    notiz: str | None = None

    @model_validator(mode="after")
    def _reihenfolge(self):
        if self.ende is not None and self.ende <= self.start:
            raise ValueError("Ende muss nach dem Beginn liegen")
        if self.anmeldung_von and self.anmeldung_bis and self.anmeldung_bis < self.anmeldung_von:
            raise ValueError("Anmeldeschluss liegt vor dem Anmeldebeginn")
        return self


class PruefungsterminAenderung(BaseModel):
    """Nur gesetzte Felder ändern sich. Geänderte Zeiten eines importierten Termins überschreibt der Import nicht mehr."""

    titel: str | None = Field(None, min_length=1, max_length=300)
    start: datetime | None = None
    ende: datetime | None = None
    ort: str | None = Field(None, max_length=300)
    anmeldung_von: datetime | None = None
    anmeldung_bis: datetime | None = None
    abmeldung_bis: datetime | None = None
    angemeldet: bool | None = None  # null = wieder automatisch
    notiz: str | None = None


class AngemeldetWahl(BaseModel):
    termin_id: int | None = None  # None = bei keinem Termin angemeldet
    automatisch: bool = False  # eigene Wahl aufheben: wieder nach TISS (Prüfungsliste, Feed)


class PruefungImport(BaseModel):
    """Ein Termin, wie die Erweiterung ihn liest (Zeiten lokal, ohne Zeitzone)."""

    extern_id: str = Field(min_length=1, max_length=300)
    titel: str = Field("Prüfung", max_length=300)
    start: datetime
    ende: datetime | None = None
    ort: str | None = Field(None, max_length=300)
    anmeldung_von: datetime | None = None
    anmeldung_bis: datetime | None = None
    abmeldung_bis: datetime | None = None
    angemeldet: bool = False

    @field_validator("titel", mode="before")
    @classmethod
    def _titel_standard(cls, wert):
        return (wert or "").strip()[:300] or "Prüfung"

    @field_validator("start", "ende", "anmeldung_von", "anmeldung_bis", "abmeldung_bis", mode="after")
    @classmethod
    def _ohne_zeitzone(cls, wert):
        # Zeiten mit Zeitzone nach Europe/Vienna umrechnen, gespeichert wird naiv lokal
        if wert is not None and wert.tzinfo is not None:
            from zoneinfo import ZoneInfo

            return wert.astimezone(ZoneInfo("Europe/Vienna")).replace(tzinfo=None)
        return wert


class PruefungenLvaImport(BaseModel):
    lva_id: int
    termine: list[PruefungImport] = []
    vollstaendig: bool = True  # alle Termine dieser Quelle für die LVA (fehlende fallen weg)


class PruefungenImport(BaseModel):
    quelle: str = Field(pattern="^(tiss|tuwel)$")
    lvas: list[PruefungenLvaImport] = []
    fehler: list[str] = []  # Probleme beim Lesen (z. B. Seite nicht lesbar), erscheinen in der Oberfläche
    unlesbar_html: str | None = Field(None, max_length=200_000)  # Rohfassung einer Seite ohne erkannte Termine


class SteopStatus(BaseModel):
    """Nur gesetzte Felder werden geändert; erlaubte_ects None = Wert aus TISS."""

    abgeschlossen: bool | None = None
    erlaubte_ects: float | None = Field(None, ge=0, le=240)


class VarianteAenderung(BaseModel):
    enthalten: bool


class SteopStudium(BaseModel):
    studium: str
    status: str | None = Field(None, pattern="^(abgeschlossen|ausgenommen|offen)$")
    erlaubte_ects: float | None = None


class SteopTissIn(BaseModel):
    """STEOP-Status, wie die Erweiterung ihn aus TISS liest. `abgeschlossen` None = nicht sicher erkannt."""

    studien: list[SteopStudium] = []
    abgeschlossen: bool | None = None
    erlaubte_ects: float | None = None
    steop_nummern: list[str] = []
    # Kriterienbaum der offenen STEOPs (steop_kriterien.py), oberste Ebene mit `verknuepfung` verbunden
    kriterien: list[dict] = []
    verknuepfung: str = Field("AND", pattern="^(AND|OR)$")
    detail_html: str | None = Field(None, max_length=200_000)  # Rohfassung der Detailansicht, nur zur Prüfung


class SteopStatusOut(BaseModel):
    abgeschlossen: bool
    quelle: str | None = None  # tiss | manuell | None (noch nie gesetzt)
    tiss: dict | None = None  # letzter Stand aus TISS: studien, erlaubte_ects, steop_nummern, zeit
    erlaubte_ects: float | None = None  # Nicht-STEOP-ECTS, die vor Abschluss vorgezogen werden dürfen
    erlaubte_ects_quelle: str | None = None  # manuell | tiss | None
    vorgezogen_ects: float = 0  # Nicht-STEOP-LVAs in der Variante
    # Variante (nur solange die STEOP offen ist)
    semester: str | None = None
    steop_gesamt: int = 0  # STEOP-LVAs im Semester
    steop_gewaehlt: int = 0  # davon in der Variante
    variante_bearbeitet: bool = False  # False = automatisch erzeugt
    # Kriterien aus TISS, ausgewertet für die Variante (Knoten: erfuellt_variante; LVA: lva_id, in_variante, erledigt)
    kriterien: list[dict] = []
    verknuepfung: str = "AND"
    warnungen: list[str] = []


class TerminOut(BaseModel):
    id: int
    lva_id: int
    lva_titel: str
    lva_farbe: str
    typ: str
    titel: str
    start: datetime
    ende: datetime
    ort: str | None
    beschreibung: str | None
    steop_abweichung: bool | None
    anwesenheit_abweichung: bool | None
    aufzeichnung_abweichung: bool | None
    steop: bool
    anwesenheitspflicht: bool
    aufzeichnung: bool
    # Werte des Teils (bzw. der LVA), die ohne Abweichung gelten
    lva_steop: bool
    lva_anwesenheitspflicht: bool
    lva_aufzeichnung: bool
    teil_id: int | None = None
    teil_bezeichnung: str | None = None
    quelle: str = "tiss"  # tiss | manuell (selbst im Kalender angelegt: bearbeit- und löschbar)


class TerminUpdate(BaseModel):
    """Abweichungen von den LVA-Markierungen. `null` setzt auf den LVA-Wert zurück. Zeit, Titel, Ort und Typ nur bei
    selbst angelegten Terminen."""

    steop_abweichung: bool | None = None
    anwesenheit_abweichung: bool | None = None
    aufzeichnung_abweichung: bool | None = None
    titel: str | None = Field(None, min_length=1, max_length=500)
    start: datetime | None = None
    ende: datetime | None = None
    ort: str | None = Field(None, max_length=300)
    typ: str | None = Field(None, pattern="^(VO|UE|VU|PRUEFUNG|ABGABE|SONSTIGE)$")


class TerminNeu(BaseModel):
    """Eigener Termin zu einer LVA (z. B. Tutorium, Lerngruppe mit Anwesenheit)."""

    lva_id: int
    titel: str = Field(min_length=1, max_length=500)
    start: datetime
    ende: datetime
    ort: str | None = Field(None, max_length=300)
    typ: str = Field("SONSTIGE", pattern="^(VO|UE|VU|PRUEFUNG|ABGABE|SONSTIGE)$")

    @model_validator(mode="after")
    def _reihenfolge(self):
        if self.ende <= self.start:
            raise ValueError("Ende muss nach dem Beginn liegen")
        return self


class PersoenlichNeu(BaseModel):
    """Persönlicher Termin ohne LVA: Arbeit und Lernen werden darum herum geplant."""

    titel: str = Field(min_length=1, max_length=300)
    start: datetime
    ende: datetime
    ort: str | None = Field(None, max_length=300)
    notiz: str | None = None

    @model_validator(mode="after")
    def _reihenfolge(self):
        if self.ende <= self.start:
            raise ValueError("Ende muss nach dem Beginn liegen")
        return self


class PersoenlichAenderung(BaseModel):
    titel: str | None = Field(None, min_length=1, max_length=300)
    start: datetime | None = None
    ende: datetime | None = None
    ort: str | None = Field(None, max_length=300)
    notiz: str | None = None


class PersoenlichOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titel: str
    start: datetime
    ende: datetime
    ort: str | None
    notiz: str | None


class FreierTag(BaseModel):
    """Zusätzlicher freier Tag oder Zeitraum (z. B. 24.12. jährlich oder Urlaub)."""

    von: date
    bis: date | None = None
    bezeichnung: str | None = None
    jaehrlich: bool = False

    @model_validator(mode="after")
    def _reihenfolge(self):
        if self.bis is not None and self.bis < self.von:
            raise ValueError("Ende des freien Zeitraums muss nach dem Beginn liegen")
        if self.jaehrlich and self.bis is not None and (self.bis - self.von).days > 366:
            raise ValueError("Ein jährlicher Zeitraum darf höchstens ein Jahr umfassen")
        return self


class GewichteSchema(BaseModel):
    """Wie stark die Kriterien einer entspannten Woche zählen (0 = egal, 10 = sehr wichtig)."""

    gleichmaessig: float = Field(5, ge=0, le=10)
    buendeln: float = Field(5, ge=0, le=10)
    lernzeit: float = Field(5, ge=0, le=10)
    erholung: float = Field(5, ge=0, le=10)
    zerstueckelung: float = Field(5, ge=0, le=10)


class ArbeitsregelSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stunden_pro_woche: float = Field(ge=0, le=80)
    tage: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    bevorzugte_tage: list[int] = Field(default_factory=list)
    fruehester_beginn: time = time(8, 0)
    spaetestes_ende: time = time(18, 0)
    min_block_minuten: int = Field(120, ge=15, le=24 * 60)
    max_block_minuten: int = Field(480, ge=15, le=24 * 60)
    puffer_minuten: int = Field(30, ge=0, le=240)
    arbeitgeber: str | None = None
    freie_tage: list[FreierTag] = Field(default_factory=list)
    max_tag_stunden: float = Field(9, gt=0, le=24)
    lernfenster_minuten: int = Field(120, ge=0, le=12 * 60)
    voller_unitag_stunden: float = Field(6, ge=0, le=24)
    min_freie_tage: int = Field(1, ge=0, le=7)
    gewichte: GewichteSchema = Field(default_factory=GewichteSchema)
    lern_min_block_minuten: int = Field(45, ge=15, le=8 * 60)
    lern_max_block_minuten: int = Field(120, ge=15, le=8 * 60)
    lern_tage: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    ects_faktor: float = Field(0.7, gt=0, le=2)  # ECTS sind meist zu hoch angesetzt
    lernphase_wochen: int = Field(2, ge=0, le=20)  # Standard: Lernblöcke so viele Wochen vor jeder Prüfung

    @field_validator(
        "max_tag_stunden", "lernfenster_minuten", "voller_unitag_stunden", "min_freie_tage",
        "lern_min_block_minuten", "lern_max_block_minuten", "lern_tage", "ects_faktor", "lernphase_wochen",
        mode="before",
    )
    @classmethod
    def _null_als_standard(cls, wert, info):
        # Regeln aus der Zeit vor diesen Spalten können NULL enthalten
        return cls.model_fields[info.field_name].default if wert is None else wert

    @field_validator("gewichte", mode="before")
    @classmethod
    def _gewichte_standard(cls, wert):
        return wert or {}

    @field_validator("freie_tage", mode="before")
    @classmethod
    def _null_als_leer(cls, wert):
        return wert or []  # Regeln aus der Zeit vor dieser Spalte haben NULL

    @field_validator("tage", "bevorzugte_tage", "lern_tage")
    @classmethod
    def _wochentage(cls, werte: list[int]) -> list[int]:
        if any(w < 0 or w > 6 for w in werte):
            raise ValueError("Wochentage müssen zwischen 0 (Montag) und 6 (Sonntag) liegen")
        return sorted(set(werte))

    @model_validator(mode="after")
    def _plausibel(self):
        if self.min_block_minuten > self.max_block_minuten:
            raise ValueError("Mindestlänge darf nicht größer als die Maximallänge sein")
        if self.lern_min_block_minuten > self.lern_max_block_minuten:
            raise ValueError("Mindestlänge eines Lernblocks darf nicht größer als die Maximallänge sein")
        if self.fruehester_beginn >= self.spaetestes_ende:
            raise ValueError("Frühester Beginn muss vor dem spätesten Ende liegen")
        return self


class ArbeitsblockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    start: datetime
    ende: datetime
    art: str
    status: str
    arbeitgeber: str | None
    notiz: str | None
    serie_id: str | None
    dauer_stunden: float


class ArbeitsblockIn(BaseModel):
    start: datetime
    ende: datetime
    arbeitgeber: str | None = None
    notiz: str | None = None

    @model_validator(mode="after")
    def _reihenfolge(self):
        if self.ende <= self.start:
            raise ValueError("Ende muss nach dem Beginn liegen")
        return self


class ArbeitsblockUpdate(BaseModel):
    start: datetime | None = None
    ende: datetime | None = None
    status: str | None = Field(None, pattern="^(vorschlag|bestaetigt)$")
    arbeitgeber: str | None = None
    notiz: str | None = None


class SerieIn(BaseModel):
    """Fixe Arbeitszeit, die sich wöchentlich wiederholt."""

    wochentage: list[int] = Field(min_length=1)
    beginn: time
    ende: time
    von: date
    bis: date
    arbeitgeber: str | None = None
    notiz: str | None = None

    @model_validator(mode="after")
    def _plausibel(self):
        if self.ende <= self.beginn:
            raise ValueError("Ende muss nach dem Beginn liegen")
        if self.bis < self.von:
            raise ValueError("Enddatum muss nach dem Startdatum liegen")
        if any(w < 0 or w > 6 for w in self.wochentage):
            raise ValueError("Ungültiger Wochentag")
        return self


class SerieOut(BaseModel):
    serie_id: str
    anzahl: int
    erster: datetime
    letzter: datetime
    arbeitgeber: str | None
    notiz: str | None


class GeopferterTermin(BaseModel):
    id: int | None
    titel: str
    start: datetime
    ende: datetime


class LernblockOut(BaseModel):
    id: int
    lva_id: int
    lva_name: str
    lva_farbe: str
    thema: str
    start: datetime
    ende: datetime
    status: str
    erledigt: bool
    tatsaechliche_minuten: int | None
    geplante_minuten: int
    notiz: str | None
    zuteilung: dict[str, int]
    altpruefung: dict | None = None  # Altprüfung aus der MB Cloud, die der Block behandelt


class LernblockUpdate(BaseModel):
    start: datetime | None = None
    ende: datetime | None = None
    status: str | None = Field(None, pattern="^(vorschlag|bestaetigt)$")
    erledigt: bool | None = None
    tatsaechliche_minuten: int | None = Field(None, ge=0, le=24 * 60)
    notiz: str | None = None


class WochenbedarfOut(BaseModel):
    """Lernbedarf einer LVA in einer Woche (aus den ECTS)."""

    lva_id: int
    lva_name: str
    gesamt_minuten: int  # Semesterbedarf
    plan_minuten: int  # Anteil dieser Woche ohne Nachholen
    soll_minuten: int  # inklusive Nachholen
    geplant_minuten: int  # Lernblöcke dieser Woche
    rueckstand_minuten: int  # positiv = hinter dem Plan
    pruefung: date | None
    lernphase: bool
    ohne_ects: bool


class Rueckstand(BaseModel):
    lva_id: int
    lva_name: str
    fehlend_minuten: int
    rueckstand_minuten: int
    nachholen_pro_woche_minuten: int
    bis: date | None
    text: str


class VorschlagOut(BaseModel):
    woche: date
    punktzahl: float
    begruendungen: list[str]
    lernbloecke: list[LernblockOut] = []
    lern_stunden: float = 0
    lern_offen_stunden: float = 0
    konflikte: list[str] = []
    rueckstaende: list[Rueckstand] = []
    hinweise: list[str] = []
    lernbedarf: list[WochenbedarfOut] = []
    soll_stunden: float
    verplant_stunden: float
    fehlende_stunden: float
    bloecke: list[ArbeitsblockOut]
    geopferte_termine: list[GeopferterTermin]


class WochenStunden(BaseModel):
    uni: float
    arbeit: float
    lernen: float
    freizeit: float
    wach: float
    arbeit_soll: float
    vorschlaege: bool


class PruefungCountdown(BaseModel):
    lva_id: int
    lva_name: str
    farbe: str
    zeitpunkt: datetime
    tage: int
    quelle: str | None
    in_dieser_woche: bool


class WochenuebersichtOut(BaseModel):
    woche: date
    stunden: WochenStunden
    pruefungen: list[PruefungCountdown]
    lernstand: list[WochenbedarfOut]


class TissEinstellungen(BaseModel):
    ical_url: str | None = None


class ImportErgebnisOut(BaseModel):
    neu: int
    geaendert: int
    geloescht: int
    unveraendert: int
    neue_lvas: list[str]
    freie_zeitraeume: int = 0
    entfernte_lvas: list[str] = []  # ohne Termine im Feed und ohne Unterlagen
    neu_geplante_wochen: list[date]
    letzter_import: datetime | None = None
