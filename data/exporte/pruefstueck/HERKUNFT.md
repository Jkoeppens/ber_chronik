# Prüfstück

Ein eingefrorener Export des Projekts `ber`, erzeugt am 9. September 2026 mit

    python3 -m src.neu.export.cli --projekt ber

und danach unverändert hierher kopiert. **Er wird nie neu erzeugt.** Genau das
macht ihn zum Prüfmaß: die Playwright-Tests laden `/viz/?project=pruefstueck`
und vergleichen gegen feste Zahlen — 949 Einträge, 7 Kategorien, 869 Knoten,
1989 bis 2017.

Verändert jemand die Dateien, ändern sich die Tests unter der Hand, ohne dass
irgendwo etwas bricht. Dagegen wacht `test_pruefstueck_ist_unveraendert` in
`tests/test_neu_pruefstueck.py`: es hält die Prüfsummen aller vier Dateien.

## Warum hier und nicht in tests/

`viz/highlight.js` bildet die Datenbasis aus dem URL-Parameter:

    DATA_BASE = `../data/exporte/${PAGE_PROJECT}/`

Ein anderer Ort wäre nur über eine Änderung an viz/ erreichbar gewesen — und
das Prüfstück soll den echten Weg prüfen, nicht einen eigens dafür gebauten.

`data/exporte/` ist in `.gitignore`, weil dort sonst nur Erzeugnisse liegen.
Für dieses eine Verzeichnis steht dort eine Ausnahme.

## Was er nicht enthält

`entities_summary.json` fehlt, weil `ber` in `data/neu.db` keine
Akteurs-Zusammenfassungen hat. Der Kasten `.ep-summary` in der Akteursansicht
ist damit nicht abgedeckt; die Tests fallen dort auf die Absatzliste zurück,
so wie viz/ es auch täte. Wer die Abdeckung will, braucht ein Prüfstück aus
einem Projekt mit Zusammenfassungen — `nahda-durchlauf` hat 69, dafür nur 278
Einheiten und ein dünneres Netz.
