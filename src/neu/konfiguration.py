"""
konfiguration.py — was gerade eingestellt ist

Eine Stelle, die die Umgebung liest und beantwortet: welcher Embedding- und
welcher Sprachmodell-Anbieter ist aktiv, mit welchem Modell, welcher Schwelle,
und liegen die nötigen Schlüssel vor.

Lädt nichts, ruft nichts auf, prüft keinen Schlüssel gegen den Anbieter — nur
Umgebung und Konstanten. Das darf beim Hochfahren keine Sekunde kosten und kein
Modell aus dem Netz holen.

Was hier zusammenläuft, steht sonst an vier Stellen: die Anbieterwahl in
src/neu/*/anbieter.py, die Schwellen in kern.py, die Modellnamen in beiden.
Auseinanderlaufen können sie trotzdem — deshalb nimmt dieses Modul die Werte
von dort und schreibt sie nicht noch einmal auf.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

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
class Anbieterlage:
    """Was für einen Anbieter eingestellt ist und was ihm fehlt."""

    anbieter: str | None            # None = nicht gesetzt
    bekannt: bool                   # steht im Wertevorrat
    modell: str | None
    schluessel_name: str | None     # welche Variable gebraucht wird, oder None
    schluessel_vorhanden: bool | None   # None = wird keiner gebraucht
    einsatzbereit: bool
    hinweis: str | None = None      # was fehlt, in einem Satz
    # Beim Embedding: 'local' sind zwei Modelle mit zwei Aufgaben — bge-m3 für
    # Themen und Zuordnung, MiniLM für das Zusammenführen von Akteuren. Diese
    # Stelle nannte lange nur MiniLM, und die Taxonomiefläche schrieb es an den
    # Kopf, wo bge-m3 rechnete. Seit der Modellname der Schlüssel des
    # Vektorspeichers ist (src/neu/vektoren.py), ist das kein Schönheitsfehler
    # mehr. `modell` ist deshalb das der Kategorien; hier steht das andere.
    modell_akteure: str | None = None


@dataclass
class Lage:
    env_datei: str | None           # geladene Datei, oder None
    embedding: Anbieterlage
    llm: Anbieterlage
    schwelle_akteure: float | None  # Zusammenführen, hängt am Embedding-Modell
    band_akteure: tuple[float, float] | None
    schwellen_kategorien: dict[str, float] = field(default_factory=dict)
    ollama_frist_sekunden: int | None = None


def _embedding_lage() -> tuple[Anbieterlage, float | None]:
    from src.neu.akteure.anbieter import (
        EMBEDDING_ANBIETER, MODELL_MINILM, MODELL_VOYAGE,
        SCHWELLE_MINILM, SCHWELLE_VOYAGE,
    )
    from src.neu.taxonomie.anbieter import EMBEDDING_MODELLE

    roh = (os.environ.get("EMBEDDING_PROVIDER") or "").strip().lower()
    if not roh:
        return Anbieterlage(
            anbieter=None, bekannt=False, modell=None,
            schluessel_name=None, schluessel_vorhanden=None, einsatzbereit=False,
            hinweis="EMBEDDING_PROVIDER ist nicht gesetzt. Erlaubt: "
                    + " | ".join(EMBEDDING_ANBIETER),
        ), None

    if roh not in EMBEDDING_ANBIETER:
        return Anbieterlage(
            anbieter=roh, bekannt=False, modell=None,
            schluessel_name=None, schluessel_vorhanden=None, einsatzbereit=False,
            hinweis=f"Unbekannter EMBEDDING_PROVIDER '{roh}'. Erlaubt: "
                    + " | ".join(EMBEDDING_ANBIETER),
        ), None

    if roh == "voyage":
        da = bool(os.environ.get("VOYAGE_API_KEY"))
        return Anbieterlage(
            anbieter="voyage", bekannt=True, modell=MODELL_VOYAGE,
            modell_akteure=MODELL_VOYAGE,
            schluessel_name="VOYAGE_API_KEY", schluessel_vorhanden=da,
            einsatzbereit=da,
            hinweis=None if da else "VOYAGE_API_KEY fehlt.",
        ), SCHWELLE_VOYAGE

    return Anbieterlage(
        anbieter="local", bekannt=True,
        modell=EMBEDDING_MODELLE["local"], modell_akteure=MODELL_MINILM,
        schluessel_name=None, schluessel_vorhanden=None, einsatzbereit=True,
    ), SCHWELLE_MINILM


def _llm_lage() -> tuple[Anbieterlage, int | None]:
    from src.neu.taxonomie.anbieter import (
        LLM_ANBIETER, MODELL_ANTHROPIC, MODELL_OLLAMA, ollama_frist,
    )

    roh = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if not roh:
        return Anbieterlage(
            anbieter=None, bekannt=False, modell=None,
            schluessel_name=None, schluessel_vorhanden=None, einsatzbereit=False,
            hinweis="LLM_PROVIDER ist nicht gesetzt. Erlaubt: "
                    + " | ".join(LLM_ANBIETER),
        ), None

    if roh not in LLM_ANBIETER:
        return Anbieterlage(
            anbieter=roh, bekannt=False, modell=None,
            schluessel_name=None, schluessel_vorhanden=None, einsatzbereit=False,
            hinweis=f"Unbekannter LLM_PROVIDER '{roh}'. Erlaubt: "
                    + " | ".join(LLM_ANBIETER),
        ), None

    if roh == "anthropic":
        da = bool(os.environ.get("ANTHROPIC_API_KEY"))
        modell = os.environ.get("ANTHROPIC_MODEL_ANALYZE") or MODELL_ANTHROPIC
        return Anbieterlage(
            anbieter="anthropic", bekannt=True, modell=modell,
            schluessel_name="ANTHROPIC_API_KEY", schluessel_vorhanden=da,
            einsatzbereit=da,
            hinweis=None if da else "ANTHROPIC_API_KEY fehlt.",
        ), None

    modell = os.environ.get("OLLAMA_MODEL") or MODELL_OLLAMA
    return Anbieterlage(
        anbieter="ollama", bekannt=True, modell=modell,
        schluessel_name=None, schluessel_vorhanden=None, einsatzbereit=True,
    ), ollama_frist()


def lage() -> Lage:
    """Liest die Umgebung und gibt zurück, was eingestellt ist."""
    from src.neu.akteure.kern import band
    from src.neu.kategorien.kern import SCHWELLE_HIGH, SCHWELLE_MEDIUM

    embedding, schwelle = _embedding_lage()
    llm, frist = _llm_lage()

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
