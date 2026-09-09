"""
konfiguration.py — was gerade eingestellt ist

Eine Stelle, die die Umgebung liest und beantwortet: welcher Embedding- und
welcher Sprachmodell-Anbieter ist aktiv, mit welchem Modell, welcher Schwelle,
und liegen die nötigen Schlüssel vor.

Lädt nichts, ruft nichts auf, prüft keinen Schlüssel gegen den Anbieter — nur
Umgebung und Konstanten. Das darf beim Hochfahren keine Sekunde kosten und kein
Modell aus dem Netz holen.

Dieses Modul weiß selbst nichts über Anbieter. Was gilt, kommt aus
src/neu/anbieter.py und damit aus anbieter.toml; hier wird es nur eingesammelt
und in Zeilen gebracht. Vorher las es aus zwei Anbietermodulen und schrieb die
Fallunterscheidung ein drittes Mal auf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.neu.anbieter import Anbieterlage, embedding_lage, llm_lage

WURZEL = Path(__file__).resolve().parent.parent.parent
ENV_DATEI = WURZEL / ".env"


def env_laden(pfad: Path | None = None) -> bool:
    """Lädt .env, ohne gesetzte Umgebungsvariablen zu überschreiben.

    override=False ist der springende Punkt: im Betrieb (Railway) kommen die
    Werte aus der Umgebung, und eine mitdeployte .env darf sie nicht verdrängen.
    Lokal ist die Umgebung leer, dort gewinnt die Datei.
    """
    ziel = pfad or ENV_DATEI
    if not ziel.exists():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    load_dotenv(ziel, override=False)
    return True


# ── Übersicht ─────────────────────────────────────────────────────────────────

@dataclass
class Lage:
    env_datei: str | None           # geladene Datei, oder None
    embedding: Anbieterlage
    llm: Anbieterlage
    schwelle_akteure: float | None  # Zusammenführen, hängt am Embedding-Modell
    band_akteure: tuple[float, float] | None
    schwellen_kategorien: dict[str, float] = field(default_factory=dict)
    ollama_frist_sekunden: int | None = None


def lage() -> Lage:
    """Liest die Umgebung und gibt zurück, was eingestellt ist."""
    from src.neu.akteure.kern import band
    from src.neu.kategorien.kern import SCHWELLE_HIGH, SCHWELLE_MEDIUM

    embedding, schwelle = embedding_lage()
    llm, frist = llm_lage()

    return Lage(
        env_datei=str(ENV_DATEI) if ENV_DATEI.exists() else None,
        embedding=embedding,
        llm=llm,
        schwelle_akteure=schwelle,
        band_akteure=band(schwelle) if schwelle is not None else None,
        schwellen_kategorien={"high": SCHWELLE_HIGH, "medium": SCHWELLE_MEDIUM},
        ollama_frist_sekunden=frist,
    )


# ── Anzeige beim Hochfahren ───────────────────────────────────────────────────

def _zeile(name: str, a: Anbieterlage) -> str:
    if not a.einsatzbereit:
        return f"  {name:10s} ✗  {a.hinweis}"
    teile = [a.anbieter or "?"]
    if a.modell:
        teile.append(a.modell)
    if a.modell_akteure and a.modell_akteure != a.modell:
        teile.append(f"{a.modell_akteure} (Akteure)")
    # Nur was abweicht. Alle drei Aufgaben aufzuzählen, wenn sie dasselbe
    # Modell nehmen, verstellt den Blick auf den einen Fall, der anders ist.
    for aufgabe, m in sorted(a.modelle.items()):
        if m != a.modell and m != a.modell_akteure:
            teile.append(f"{m} ({aufgabe})")
    stand = "Schlüssel vorhanden" if a.schluessel_vorhanden else "ohne Schlüssel, lokal"
    return f"  {name:10s} ✓  {' · '.join(teile)}  ({stand})"


def protokollzeilen(lage_: Lage | None = None) -> list[str]:
    """Was beim Hochfahren zu sehen sein soll. Nie ein Schlüssel, nie ein Token."""
    z = lage_ or lage()
    zeilen = [
        "Konfiguration"
        + (f"  ({z.env_datei} geladen)" if z.env_datei else "  (keine .env)")
    ]
    zeilen.append(_zeile("Embedding", z.embedding))
    if z.schwelle_akteure is not None and z.band_akteure is not None:
        unten, oben = z.band_akteure
        zeilen.append(
            f"  {'':10s}    Akteure: Schwelle {z.schwelle_akteure}, "
            f"Vorschlagsband {unten}–{oben}"
        )
    zeilen.append(_zeile("Sprachmodell", z.llm))
    if z.ollama_frist_sekunden is not None:
        zeilen.append(f"  {'':10s}    Frist je Aufruf: {z.ollama_frist_sekunden} s")
    if not (z.embedding.einsatzbereit and z.llm.einsatzbereit):
        zeilen.append(
            "  Der Server läuft. Schritte, die einen fehlenden Anbieter brauchen, "
            "antworten mit 503."
        )
    return zeilen
