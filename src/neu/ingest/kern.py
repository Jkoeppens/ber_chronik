"""
kern.py — Rohtexte zu Einheiten zerlegen

Nimmt eine Folge von Rohtexten und gibt Einheiten zurück. Kennt keine
Datenbank, keine Dateien, kein print. Wer hier etwas ändert, ändert die
Segmentierung — und sonst nichts.

Die Fachlogik ist unverändert übernommen:
  literaturexzerpt  aus src/generalized/parse_document.parse()
  pressesammlung    aus src/generalized/ingest_obsidian._build_segments()
                    samt _parse_frontmatter, _extract_date, _clean_obsidian_links

Übernommen wurde die Logik, nicht die Klempnerei: die Vorlagen öffneten ihre
Dateien selbst, zählten Segment-Kennungen als Zeichenketten ("s0001") und
stempelten doc_type an jedes Segment. Hier kommen die Rohtexte von außen,
die Reihenfolge steht als position in der Einheit, und das Quellformat
gehört zur Quelle, nicht zur Einheit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

# ── Wertevorrat ───────────────────────────────────────────────────────────────

QUELLFORMATE = ("literaturexzerpt", "presseexzerpt", "pressesammlung")


class UnbekanntesQuellformat(ValueError):
    pass


class NichtImplementiert(NotImplementedError):
    pass


def quellformat_pruefen(wert: str) -> str:
    """Prüft gegen den festen Wertevorrat. Nichts wird durchgereicht."""
    if wert not in QUELLFORMATE:
        erlaubt = " | ".join(QUELLFORMATE)
        raise UnbekanntesQuellformat(f"Unbekanntes Quellformat '{wert}'. Erlaubt: {erlaubt}")
    return wert


# ── Ein- und Ausgabe des Kerns ────────────────────────────────────────────────

@dataclass(frozen=True)
class RohAbsatz:
    """Ein Absatz aus einem DOCX: Text und Formatvorlage."""

    text: str
    stil: str


@dataclass(frozen=True)
class RohDatei:
    """Eine Datei aus einem Ordner: Pfad und Inhalt."""

    pfad: str
    inhalt: str


@dataclass
class Einheit:
    """Eine Einheit, wie sie in die Tabelle einheit geht.

    position wird hier vergeben und nicht dem Listenindex überlassen.
    """

    position: int
    typ: str
    text: str
    publikation: str | None = None
    chronologie_gruppe: str | None = None
    publikationsdatum: str | None = None
    quellpfad: str | None = None
    url: str | None = None
    autor: str | None = None
    kurzfassung: str | None = None
    seite: int | None = None
    ebene: int | None = None
    ist_zitat: bool | None = None
    datum: str | None = None


# ── literaturexzerpt ──────────────────────────────────────────────────────────
# Unverändert aus parse_document.py übernommen.

# Seitenzahl: 1–3 Ziffern am Ende, getrennt durch Leerzeichen oder Klammer-zu
PAGE_NR = re.compile(r"[\s)]+(\d{1,3})$")

# Bibliographie-Signale. Reihenfolge und Breite sind bewusst; werden OHNE
# 'page is None'-Guard angewendet, damit auch Kapitelverzeichnis-Einträge mit
# Startseite korrekt klassifiziert werden.
BIBLIO_RE = [
    re.compile(r"^[A-Z][a-z].{0,40}\s:\s[A-Z]"),    # "Author : Title"
    re.compile(r'^["\u201c\u201e\u201a„(]'),         # beginnt mit Anführungszeichen
    re.compile(r"\d:\s*[A-Za-z]{2}\s+\d+"),          # Bibliothekssignatur 4: Re 4618
    re.compile(r"\(\d{4}\)"),                         # Jahr in Klammern (1984)
    re.compile(r"\b(fernleihe|gelesen|nicht gefunden)\b", re.I),
]

# Heading-1-Überschriften, die keine Buchquellen sind, sondern Gliederungs-
# abschnitte einleiten. Rein heuristische Erkennung (Länge, Sprache) ist in
# diesem Dokument unzuverlässig.
ORGANIZER_H1: set[str] = {
    "Notizen",
    "Übertrag von Zeitschriften",
}


def seite_abtrennen(text: str) -> tuple[int | None, str]:
    m = PAGE_NR.search(text)
    if m:
        return int(m.group(1)), text[: m.start()].rstrip()
    return None, text


def ist_bibliographie(text: str) -> bool:
    return any(p.search(text) for p in BIBLIO_RE)


def aus_absaetzen(absaetze: Iterable[RohAbsatz]) -> list[Einheit]:
    """Literaturexzerpt: hierarchische Buchnotizen mit ebene, publikation, seite.

    Drei Strukturebenen:
      1  Projektüberschrift (Organizer-Heading-1), typ = meta
      2  Literaturliste darunter, typ = bibliography
      3  Buch-Abschnitte, typ = bibliography oder content
    """
    einheiten: list[Einheit] = []
    position = 0

    # state: 'bibliographic' = unter Organizer-H1 (→ ebene 2)
    #        'book_source'   = unter Buchquelle-H1 oder H2 (→ ebene 3)
    state = "bibliographic"
    aktuelle_quelle: str | None = None

    for absatz in absaetze:
        text = absatz.text.strip()
        if not text:
            continue
        stil = absatz.stil

        if "Heading 1" in stil:
            if text in ORGANIZER_H1:
                position += 1
                einheiten.append(Einheit(
                    position=position,
                    typ="meta",
                    text=text,
                    publikation=None,
                    chronologie_gruppe=None,
                    ebene=1,
                    seite=None,
                ))
                state = "bibliographic"
                aktuelle_quelle = text
            else:
                state = "book_source"
                aktuelle_quelle = text
            continue

        if "Heading 2" in stil:
            state = "book_source"
            aktuelle_quelle = text
            continue

        seite, sauber = seite_abtrennen(text)

        if state == "bibliographic":
            ebene = 2
            typ = "bibliography"
        else:
            ebene = 3
            typ = "bibliography" if ist_bibliographie(text) else "content"

        position += 1
        einheiten.append(Einheit(
            position=position,
            typ=typ,
            text=sauber,
            # Bei einem Exzerpt ist das Werk zugleich Herkunft und
            # Interpolationsgruppe (SCHEMA.md, chronologie_gruppe).
            publikation=aktuelle_quelle,
            chronologie_gruppe=aktuelle_quelle,
            ebene=ebene,
            seite=seite,
        ))

    return einheiten


# ── pressesammlung ────────────────────────────────────────────────────────────
# Unverändert aus ingest_obsidian.py übernommen.

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def frontmatter_lesen(text: str) -> tuple[dict, str]:
    """YAML-Frontmatter vom Rumpf trennen."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, text[m.end():]


def obsidian_links_saeubern(v) -> str:
    """[[Ziel|Anzeige]] und [[Ziel]] auf den reinen Text reduzieren."""
    return re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", str(v))


def datum_lesen(meta: dict) -> str | None:
    """published → created → None. Gibt YYYY-MM-DD oder YYYY zurück."""
    for feld in ("published", "created"):
        v = meta.get(feld)
        if not v:
            continue
        s = str(v).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return s[:10]
        if re.match(r"^\d{4}$", s):
            return s
    return None


def aus_dateien(dateien: Iterable[RohDatei]) -> list[Einheit]:
    """Pressesammlung: eine Einheit je Datei, Metadaten aus dem Frontmatter.

    Dateien ohne Textinhalt werden übersprungen — sie erzeugen keine Einheit
    und verbrauchen keine position.
    """
    einheiten: list[Einheit] = []
    position = 0

    for datei in dateien:
        if not datei.inhalt.strip():
            continue
        meta, rumpf = frontmatter_lesen(datei.inhalt)
        if not rumpf.strip():
            continue

        position += 1
        einheiten.append(Einheit(
            position=position,
            typ="content",
            text=rumpf.strip(),
            publikation=str(meta.get("title") or Path(datei.pfad).stem),
            # Jede Einheit ist tagesgenau datiert — es wird nicht interpoliert,
            # also gibt es nichts zu gruppieren.
            chronologie_gruppe=None,
            datum=datum_lesen(meta),
            url=str(meta.get("source") or "") or None,
            autor=obsidian_links_saeubern(meta.get("author") or "") or None,
            kurzfassung=str(meta.get("description") or "") or None,
            quellpfad=datei.pfad,
        ))

    return einheiten
