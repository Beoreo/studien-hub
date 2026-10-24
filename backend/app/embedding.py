"""Embeddings mit einem lokalen Modell (Stufe 3).

Standard: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` über fastembed (ONNX, ohne PyTorch),
384 Dimensionen, versteht Deutsch und Englisch. Das Modell (≈ 220 MB) wird einmal nach `daten/modelle`
geladen; danach läuft alles offline. Mit `STUDIENHUB_OFFLINE=1` (so startet der MCP-Server) wird nie
nachgeladen – fehlt das Modell, fällt die Suche auf den Volltext zurück.

`HashEmbedder` ist ein einfacher, deterministischer Ersatz für Tests (Wortanteile per Hash).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from typing import Protocol

from .config import DATEN_ORDNER
from .db import EMBEDDING_DIM

MODELL = os.environ.get("STUDIENHUB_EMBEDDING_MODELL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
MODELL_ORDNER = DATEN_ORDNER / "modelle"


class Embedder(Protocol):
    dim: int

    def einbetten(self, texte: list[str]) -> list[list[float]]: ...


def normalisieren(vektor: list[float]) -> list[float]:
    laenge = math.sqrt(sum(x * x for x in vektor)) or 1.0
    return [x / laenge for x in vektor]


class FastEmbedEmbedder:
    dim = EMBEDDING_DIM

    def __init__(self, modell: str = MODELL):
        self.modell = modell
        self._modell = None
        self._fehler: Exception | None = None  # offline ohne Modell: nicht bei jeder Suche erneut versuchen
        self._sperre = threading.Lock()

    def _laden(self):
        with self._sperre:
            if self._fehler is not None:
                raise self._fehler
            if self._modell is None:
                if os.environ.get("STUDIENHUB_OFFLINE") == "1":
                    os.environ["HF_HUB_OFFLINE"] = "1"  # nichts aus dem Netz nachladen
                from fastembed import TextEmbedding

                MODELL_ORDNER.mkdir(parents=True, exist_ok=True)
                try:
                    self._modell = TextEmbedding(self.modell, cache_dir=str(MODELL_ORDNER))
                except Exception as fehler:
                    if os.environ.get("STUDIENHUB_OFFLINE") == "1":
                        self._fehler = fehler
                    raise
        return self._modell

    def einbetten(self, texte: list[str]) -> list[list[float]]:
        if not texte:
            return []
        return [normalisieren([float(x) for x in v]) for v in self._laden().embed(texte, batch_size=32)]


class HashEmbedder:
    """Für Tests: Wörter (und Wortanfänge) werden auf Dimensionen gehasht – ähnliche Texte liegen nah beieinander."""

    dim = EMBEDDING_DIM

    def einbetten(self, texte: list[str]) -> list[list[float]]:
        ergebnis = []
        for text in texte:
            v = [0.0] * self.dim
            for wort in re.findall(r"\w+", text.casefold()):
                for merkmal in (wort, wort[:5]):
                    v[int(hashlib.md5(merkmal.encode()).hexdigest(), 16) % self.dim] += 1.0
            ergebnis.append(normalisieren(v))
        return ergebnis


_standard: Embedder | None = None


def standard_embedder() -> Embedder:
    global _standard
    if _standard is None:
        _standard = FastEmbedEmbedder()
    return _standard


def setze_standard_embedder(embedder: Embedder | None) -> None:
    """Für Tests: eigenen Embedder einsetzen."""
    global _standard
    _standard = embedder
