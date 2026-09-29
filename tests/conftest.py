"""
conftest.py — was vor jedem Testmodul gelten muss

Ein einziger Zweck: ZUGANG_PASSWORT steht in der Umgebung, bevor irgendein Test
src.neu.server importiert. Ohne die Variable lässt sich das Modul nicht
importieren — absichtlich, siehe src/neu/zugang.py —, und ein Sammelfehler beim
Import wäre schwer zu lesen.

Gesetzt und nicht umgangen. Die Tests gehen DURCH den Riegel, mit einem
Passwort, das nur hier gilt: ein Schalter, der ihn für Tests abschaltet, wäre
genau die Hintertür, die der Riegel verhindern soll — und niemand würde merken,
wenn sie im Betrieb gesetzt wäre.

autouse=False und ein Modulebenen-Aufruf: eine Fixture käme zu spät, weil
test_neu_server.py den Server auf Modulebene importiert.
"""

import os

#: Nur für die Tests. Kein Geheimnis und keines, das irgendwo sonst gilt.
TEST_PASSWORT = "test-nur-fuer-die-pruefung"

# Vor jedem Import: pytest lädt conftest.py, bevor es ein Testmodul einliest.
os.environ.setdefault("ZUGANG_PASSWORT", TEST_PASSWORT)

# OBSIDIAN_WURZEL ausdrücklich LEER: die Vorgabe des Betriebs ist 'geschlossen',
# und die Tests sollen von der .env der Entwicklungsmaschine nicht abhängen. Wer
# den offenen Fall prüft, setzt sie selbst über monkeypatch.
os.environ["OBSIDIAN_WURZEL"] = ""


def basic_kopf(passwort: str = TEST_PASSWORT, benutzer: str = "pruefung") -> dict:
    """Der Authorization-Kopf für HTTP Basic.

    Selbst gebaut, weil Starlettes TestClient kein auth= kennt — er nimmt nur
    Kopfzeilen. Hier und nicht in jedem Testmodul: die Kodierung soll nicht
    dreimal danebenstehen.
    """
    import base64

    roh = f"{benutzer}:{passwort}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(roh).decode("ascii")}
