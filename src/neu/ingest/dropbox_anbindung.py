"""
dropbox_anbindung.py — Dateien aus einem Dropbox-App-Ordner holen

Übernommen aus src/generalized/ingest_obsidian.py und dev_server.py: der
OAuth-Fluss mit token_access_type="offline", der Client über
oauth2_refresh_token, das Auflisten über files_list_folder samt _continue, und
das Herunterladen. Vier SDK-Aufrufe, mehr braucht es nicht.

Die App hat Zugriff auf einen App-Ordner, nicht auf die ganze Dropbox: alle
Pfade sind relativ zu /Apps/<App>/. Deshalb sieht `files_list_folder("")` genau
den Ordner, den der Nutzer eingestellt hat.

Zwei Dinge sind hier anders als in der Vorlage:

- Der Anmeldezustand steht in der Datenbank, nicht in einem Wörterbuch im
  Arbeitsspeicher (siehe dienst_anmeldung.py). Zwischen dem Beginn und der
  Rückleitung liegt ein Besuch bei Dropbox; ein Neustart in dieser Zeit ließ
  die Anmeldung bisher mit "Ungültiger OAuth-State" auflaufen, und ein Neustart
  zwischen Rückleitung und Speichern verlor die Zugangsdaten stillschweigend.
- Gespeichert wird nur der refresh_token. Der access_token verfällt nach vier
  Stunden und wird nie gelesen — der Client wird ausschließlich mit
  oauth2_refresh_token gebaut, das SDK holt sich neue Zugriffstoken selbst.
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath

from src.neu.taxonomie.anbieter import AnbieterFehler

# Der Pfad der Rückleitung ist keine freie Wahl: Dropbox nimmt nur Adressen an,
# die in der App-Konsole eingetragen sind, und vergleicht sie samt Pfad. Für
# diese App sind eingetragen:
#   http://localhost:8001/api/obsidian/oauth/callback
#   http://localhost:8002/api/obsidian/oauth/callback
#   https://<ngrok>/api/obsidian/oauth/callback
# Deshalb heißt der Endpoint hier wie in der Vorlage, obwohl der Rest deutsch
# benannt ist — ein eigener Name hätte eine Änderung in der Konsole verlangt,
# die niemand aus dem Repository heraus vornehmen kann.
RUECKLEITUNG_VORGABE = "http://localhost:8002/api/obsidian/oauth/callback"
CSRF_SCHLUESSEL = "dropbox-auth-csrf-token"


def einstellungen() -> tuple[str, str, str]:
    """(app_schluessel, app_geheimnis, rueckleitung). Bricht ab, wenn etwas fehlt."""
    schluessel = os.environ.get("DROPBOX_APP_KEY", "").strip()
    geheimnis = os.environ.get("DROPBOX_APP_SECRET", "").strip()
    if not schluessel or not geheimnis:
        fehlend = [n for n, w in (("DROPBOX_APP_KEY", schluessel),
                                  ("DROPBOX_APP_SECRET", geheimnis)) if not w]
        raise AnbieterFehler(
            f"{' und '.join(fehlend)} fehlen in der Umgebung. Ohne sie gibt es "
            "keine Dropbox-Anmeldung.",
            "dropbox_schluessel_fehlt",
        )
    rueckleitung = os.environ.get("DROPBOX_REDIRECT_URL", "").strip() or RUECKLEITUNG_VORGABE
    return schluessel, geheimnis, rueckleitung


def verfuegbar() -> bool:
    """Ob das SDK installiert und die Umgebung gesetzt ist."""
    try:
        import dropbox  # noqa: F401
    except ImportError:
        return False
    try:
        einstellungen()
    except AnbieterFehler:
        return False
    return True


# ── Anmeldung ─────────────────────────────────────────────────────────────────

def _fluss(sitzung: dict):
    from dropbox.oauth import DropboxOAuth2Flow

    schluessel, geheimnis, rueckleitung = einstellungen()
    return DropboxOAuth2Flow(
        consumer_key=schluessel,
        consumer_secret=geheimnis,
        redirect_uri=rueckleitung,
        session=sitzung,
        csrf_token_session_key=CSRF_SCHLUESSEL,
        # offline: Dropbox gibt zusätzlich einen langlebigen refresh_token.
        token_access_type="offline",
    )


def anmeldung_beginnen() -> tuple[str, str, dict]:
    """Gibt (auth_url, csrf, sitzung) zurück.

    Die Sitzung muss aufbewahrt werden, bis die Rückleitung eintrifft — sie
    gehört in die Datenbank, nicht in den Arbeitsspeicher.
    """
    sitzung: dict = {}
    auth_url = _fluss(sitzung).start()
    return auth_url, sitzung[CSRF_SCHLUESSEL], sitzung


def anmeldung_beenden(sitzung: dict, code: str, state: str) -> str:
    """Tauscht den Code gegen einen refresh_token."""
    try:
        ergebnis = _fluss(dict(sitzung)).finish({"code": code, "state": state})
    except Exception as exc:
        raise AnbieterFehler(
            f"Dropbox hat die Anmeldung abgelehnt: {exc}", "dropbox_anmeldung_abgelehnt"
        ) from exc
    if not ergebnis.refresh_token:
        raise AnbieterFehler(
            "Dropbox hat keinen refresh_token geliefert. Ohne ihn wäre der "
            "Zugang nach vier Stunden wieder zu.",
            "dropbox_ohne_refresh_token",
        )
    return ergebnis.refresh_token


# ── Zugriff ───────────────────────────────────────────────────────────────────

def klient(refresh_token: str):
    """Ein Client, der sich selbst erneuert."""
    try:
        import dropbox
    except ImportError as exc:
        raise AnbieterFehler(
            "dropbox ist nicht installiert: pip install dropbox", "dropbox_fehlt"
        ) from exc
    schluessel, geheimnis, _ = einstellungen()
    return dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=schluessel,
        app_secret=geheimnis,
    )


def konto(dbx) -> str:
    """Der Name des verbundenen Kontos — für die Anzeige."""
    return dbx.users_get_current_account().name.display_name


def ordner_normalisieren(ordner: str) -> str:
    """Dropbox will einen führenden Schrägstrich und kein abschließendes /."""
    ordner = (ordner or "").strip().rstrip("/")
    if ordner and not ordner.startswith("/"):
        ordner = "/" + ordner
    return ordner


def relativer_pfad(voller_pfad: str, ordner: str) -> str:
    """Ein Pfad, eine Form: relativ zum Ordner, ohne führenden Schrägstrich.

    Dropbox liefert path_display als '/Dropbox_test1/x.md', der lokale Weg
    'x.md'. Ohne diese Vereinheitlichung gälte beim Wechsel zwischen beiden
    Wegen jede Datei als neu.

    Verglichen wird ohne Rücksicht auf Groß- und Kleinschreibung — Dropbox
    führt path_display im Original, der eingestellte Ordner kann davon
    abweichen. Zurück kommt die Schreibweise aus path_display.
    """
    voll = (voller_pfad or "").replace("\\", "/")
    praefix = ordner_normalisieren(ordner)
    if praefix and voll.lower().startswith(praefix.lower() + "/"):
        voll = voll[len(praefix) + 1:]
    return str(PurePosixPath(voll.lstrip("/")))


def ordner_liste(dbx) -> list[str]:
    """Die Ordner im App-Ordner, alphabetisch.

    Ein Aufruf mit leerem Pfad: das ist die Wurzel aus Sicht der App. Damit
    muss niemand den Ordnernamen auswendig wissen — der alte Weg hatte nur ein
    Textfeld.
    """
    import dropbox.files

    antwort = dbx.files_list_folder("")
    eintraege = list(antwort.entries)
    while antwort.has_more:
        antwort = dbx.files_list_folder_continue(antwort.cursor)
        eintraege.extend(antwort.entries)
    return sorted(
        e.path_display for e in eintraege
        if isinstance(e, dropbox.files.FolderMetadata)
    )


def md_dateien(dbx, ordner: str) -> list[tuple[str, str]]:
    """Alle .md-Dateien im Ordner als (relativer_pfad, path_display).

    Rekursiv und über alle Seiten — files_list_folder liefert bei vielen
    Dateien nur die erste, den Rest holt files_list_folder_continue.
    """
    import dropbox.files

    ordner = ordner_normalisieren(ordner)
    antwort = dbx.files_list_folder(ordner, recursive=True)
    eintraege = list(antwort.entries)
    while antwort.has_more:
        antwort = dbx.files_list_folder_continue(antwort.cursor)
        eintraege.extend(antwort.entries)

    dateien = [
        e for e in eintraege
        if isinstance(e, dropbox.files.FileMetadata) and e.name.endswith(".md")
    ]
    # Sortiert: die Reihenfolge bestimmt die position, und die Antwort von
    # Dropbox ist zwischen zwei Läufen nicht garantiert dieselbe.
    return sorted(
        ((relativer_pfad(e.path_display, ordner), e.path_display) for e in dateien),
        key=lambda p: p[0].lower(),
    )


def datei_laden(dbx, path_display: str) -> str:
    """Eine Datei als Text. Kaputte Zeichen werden ersetzt, nicht verschluckt."""
    _, antwort = dbx.files_download(path_display)
    return antwort.content.decode("utf-8", errors="replace")
