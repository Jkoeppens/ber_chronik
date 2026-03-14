# Entscheidungslog – Sitzung 2026-03-13

## Umgebung
- Python 3.11.7 via pyenv, venv unter `.venv/`
- `spacy==3.7.6` in requirements.txt auf `>=3.8,<3.9` geändert –
  3.7.6 hat kein vorgefertigtes ARM-Wheel für macOS, 3.8.x schon

## Ingest (ingest_docx.py)
- Skript war vorhanden und korrekt, wurde nur noch nicht ausgeführt
- Ausgabe: 978 Zeilen inkl. 29 Jahresüberschriften + 3 Titelzeilen (Vorspann)
- Vorspann-Zeilen (id 1–3, kein year_bucket) landen in paragraphs_raw.csv –
  offen: sollten sie dort rausgefiltert werden?

## Feature-Extraktion (parse_features.py)
- Neu geschrieben (Datei war leer)
- Jahresüberschriften (is_year_heading=True) werden herausgefiltert → 949 Zeilen
- Regex-basiert: date_raw, date_precision, source_name, source_date, is_quote,
  is_geicke, event_type, confidence
- Bekannte Schwäche: event_type=Claim (448 von 949) ist als Fallback sehr hoch –
  Keyword-Abdeckung prüfen oder LLM-Klassifikation bevorzugen
- Technik (16 Treffer) wirkt zu niedrig angesichts Brandschutz als Kernthema

## LLM-Klassifikation (classify_events.py)
- Neu geschrieben (Datei war leer)
- Modell: Ollama lokal, mistral, http://localhost:11434
- Prompt: Englisch, Kategorienamen Deutsch
- Bei ungültigem JSON: einmal retry, dann event_type=None / confidence=low
- JSON-Extraktion per Regex ({...}) statt blindem json.loads – Mistral schreibt
  manchmal Freitext davor
- Voller Lauf gestartet (949 Zeilen, ~60–80 Min), läuft noch

## Sitzung 2026-03-14

### LLM-Klassifikation – Ergebnisse
- Voller Lauf abgeschlossen: 949 Zeilen, 942 klassifiziert, 7 None
- Claim-Anteil kollabiert von 448 (Regex) auf 5 (Mistral) – LLM weist fast
  alles einer konkreten Kategorie zu; Plausibilität stichprobenartig ok
- Planung (363) und Personalie (181) dominieren – wirkt hoch, zur späteren
  Prüfung vorgemerkt
- Vertrag nur 6 Treffer – ebenfalls prüfenswert

### Quellenextraktion – drei Iterationen
1. Regex schnitt Text vor dem Kürzel mit (Leerzeichen im Zeichenset) → behoben:
   `\b` als Anker, kein Leerzeichen in `[A-Za-zÄÖÜäöüß/.-]{2,20}`
2. Punkt-Kürzel wie `Mittldt.Ztg` wurden abgeschnitten → `.` ins Zeichenset
3. Quellen mitten im Text `(taz, 09.06.1992)` wurden nicht erkannt →
   `$`-Anker entfernt, `findall` statt `search`; mehrere Treffer als `;`-String
4. Zweistellige Jahreszahlen wie `30.04.91` → `\d{2,4}` statt `\d{4}`
- Endergebnis: 577/949 Einträge mit Quelle, 71 mit mehreren Quellen

### Entschieden: mehrteilige Quellnamen (z.B. "Die Wirtschaft")
- Nicht per Regex lösbar ohne hohes Falschtreffrisiko (Leerzeichen im Kürzel)
- Lösung: Normalisierung über entities_seed.csv (Alias → Normalform)

### Workflow: parse_features → Mistral-Merge
- Standard-Reihenfolge: parse_features.py läuft auf paragraphs_raw.csv und
  schreibt alle Spalten außer event_type/confidence
- Mistral-Klassifikationen werden separat rein-gemergt und nicht überschrieben
- Bei erneutem parse_features-Lauf: Mistral-Daten vorher sichern, danach mergen

## Offene Punkte
- Vorspann-Zeilen (id 1–3) aus Ingest bereinigen
- `Sp`/`Spiegel` und `taz`/`Taz` als Duplikate in entities_seed.csv normalisieren
- Vertrag (6) und Planung (363) aus Mistral-Lauf stichprobenartig prüfen
- Merge-Logik bei --dry-run löscht bestehende Spalten für nicht klassifizierte
  Zeilen (known bug, irrelevant für vollen Lauf)
