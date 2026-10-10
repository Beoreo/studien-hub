"""Pydantic-Schemas für die API."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LvaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nummer: str | None
    titel: str
    kurzname: str | None
    semester: str
    farbe: str
    steop: bool
    anwesenheitspflicht: bool
    aufzeichnung: bool
    tuwel_kurs_id: int | None
    anzahl_termine: int = 0


class LvaUpdate(BaseModel):
    titel: str | None = None
    kurzname: str | None = None
    farbe: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    steop: bool | None = None
    anwesenheitspflicht: bool | None = None
    aufzeichnung: bool | None = None
    tuwel_kurs_id: int | None = None


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
    lva_steop: bool
    lva_anwesenheitspflicht: bool
    lva_aufzeichnung: bool


class TerminUpdate(BaseModel):
    """Abweichungen von den LVA-Markierungen. `null` setzt auf den LVA-Wert zurück."""

    steop_abweichung: bool | None = None
    anwesenheit_abweichung: bool | None = None
    aufzeichnung_abweichung: bool | None = None


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

    @field_validator("tage", "bevorzugte_tage")
    @classmethod
    def _wochentage(cls, werte: list[int]) -> list[int]:
        if any(w < 0 or w > 6 for w in werte):
            raise ValueError("Wochentage müssen zwischen 0 (Montag) und 6 (Sonntag) liegen")
        return sorted(set(werte))

    @model_validator(mode="after")
    def _plausibel(self):
        if self.min_block_minuten > self.max_block_minuten:
            raise ValueError("Mindestlänge darf nicht größer als die Maximallänge sein")
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


class VorschlagOut(BaseModel):
    woche: date
    soll_stunden: float
    verplant_stunden: float
    fehlende_stunden: float
    bloecke: list[ArbeitsblockOut]
    geopferte_termine: list[GeopferterTermin]


class TissEinstellungen(BaseModel):
    ical_url: str | None = None


class ImportErgebnisOut(BaseModel):
    neu: int
    geaendert: int
    geloescht: int
    unveraendert: int
    neue_lvas: list[str]
    neu_geplante_wochen: list[date]
    letzter_import: datetime | None = None
