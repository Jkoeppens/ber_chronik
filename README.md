# BER Chronik 1989–2017

Interaktives Recherchetool zur Geschichte des Flughafens Berlin Brandenburg.
**Quelle:** Chronik 1989–2017, zusammengestellt von André Geicke.

---

## Was das ist

978 Absätze aus einem DOCX-Dokument, maschinell verarbeitet und als interaktive Web-App aufbereitet. Das Tool erlaubt:

- **Timeline-Heatmap** – Ereignisse nach Jahr, Monat und Typ (Kosten, Klage, Personalie …)
- **Akteursnetzwerk** – wer tritt gemeinsam in Absätzen auf, wie oft, mit welchem Kontext
- **Chat-Interface** – Fragen auf Deutsch, beantwortet mit Claude Haiku auf Basis der Originalquellen
- **Volltextsuche** – Entity-Namen oder Stichwörter öffnen direkt die Originalabsätze

---

## Architektur

```
Rohdokument (DOCX)
      │
      ▼
paragraphs_raw.csv         src/berchronik/ingest_docx.py
      │
      ▼
paragraphs_enriched.csv    src/berchronik/parse_features.py
  (Datum, Quelle, Typ,      src/berchronik/classify_events.py
   Akteure, Konfidenz)       src/berchronik/entities.py
      │
      ├──► viz/data.json              src/berchronik/export_viz.py
      └──► viz/entities_summary.json  src/berchronik/export_viz.py --summaries
                │
                ▼
          Browser-App (viz/)
          + Chat-API  (src/api_server.py)
```

### Datenpipeline (`src/berchronik/`)

| Skript | Aufgabe |
|---|---|
| `ingest_docx.py` | DOCX → `paragraphs_raw.csv`, 978 Zeilen |
| `parse_features.py` | Regex-Extraktion: Datum, Quelle, Zitat-Flag |
| `classify_events.py` | LLM-Klassifikation: `event_type`, `confidence` |
| `entities.py` | Akteurs-Matching gegen `config/entities_seed.csv` |
| `apply_overrides.py` | Manuelle Korrekturen aus `overrides/` einarbeiten |
| `export_viz.py` | → `viz/data.json` und `viz/entities_summary.json` |
| `export_graph.py` | → Netzwerk-Rohdaten |
| `export_timeline.py` | → Timeline-Rohdaten |

### Browser-App (`viz/`)

Kein Build-Tool, kein Framework. Plain HTML/JS, direkt im Browser ladbar.

| Datei | Aufgabe |
|---|---|
| `boot.js` | App-Start: Daten laden, Timeline + Netzwerk initialisieren |
| `chart.js` | Timeline-Heatmap (D3.js) |
| `network.js` | Akteursnetzwerk mit D3 Force-Layout |
| `panel.js` | Seitenpanel: Absatz-Karten, Entity-View, Navigation |
| `search.js` | Chat-API-Anbindung und Volltextsuche |
| `highlight.js` | Zentraler Highlight-State (`hlState`), `setHighlight()` |
| `tabs.js` | Tab-Umschaltung Timeline ↔ Netzwerk, geteilte Globals |
| `utils.js` | Hilfsfunktionen |
| `tutorial.js` | Interaktives Tutorial-Overlay |

Ladereihenfolge in `index.html` ist zwingend — Details in `ARCHITECTURE.md`.

### Chat-API (`src/api_server.py`)

FastAPI-Server, streamt Antworten von **Claude Haiku** (`claude-haiku-4-5-20251001`).

```
POST /chat  →  { answer, sources, keywords }   (SSE-Stream)
```

Heuristik in `search.js`: Enthält die Eingabe `?` oder mehr als 4 Wörter → KI-Modus; sonst Volltextsuche.

---

## Starten

### Voraussetzungen

```bash
pip install -r requirements.txt
npm install            # für precompute_network.js + Playwright
```

`.env` anlegen:
```
ANTHROPIC_API_KEY=sk-...
```

### Entwicklung

```bash
# Chat-API
uvicorn src.api_server:app --reload --port 8000

# Statische Dateien
python3 -m http.server 3000 --directory viz
```

Dann `http://localhost:3000` öffnen.

### Netzwerk-Layout vorberechnen

```bash
node src/precompute_network.js   # → viz/network_layout.json
```

---

## Repo-Struktur

```
ber-chronik/
  README.md
  ARCHITECTURE.md        State-Map, Aufrufketten, Risikoanalyse
  DECISIONS.md           Warum-Entscheidungen die nicht aus dem Code hervorgehen

  data/
    raw/                 Rohdokument (nicht versioniert, Urheberrecht)
    interim/
      paragraphs_raw.csv
      paragraphs_enriched.csv
      entity_candidates.csv

  config/
    event_types.yml      Keyword → Typ Mapping
    entities_seed.csv    Akteursliste mit Kürzeln und Normalformen

  src/
    api_server.py        FastAPI Chat-API
    precompute_network.js  Netzwerk-Layout vorberechnen (Node.js)
    berchronik/          Python-Pipeline (ingest, parse, classify, export …)

  viz/
    index.html           App-Einstiegspunkt
    data.json            Alle Einträge (generiert)
    entities_summary.json  KI-Zusammenfassungen pro Akteur (generiert)
    *.js / style.css     Browser-Code

  overrides/
    paragraphs_overrides.csv  Manuelle Korrekturen
    notes.md

  tests/                 Playwright E2E-Tests
```

---

## Ereignistypen

| Typ | Bedeutung |
|---|---|
| `Beschluss` | Politische oder behördliche Entscheidung |
| `Vertrag` | Unterzeichnung, Letter of Intent |
| `Klage` | Gericht, OLG, Vergabekammer, Urteil |
| `Personalie` | Rücktritt, Ernennung, Wechsel |
| `Kosten` | Kostensteigerung, Budget, Kredit |
| `Termin` | Eröffnungstermin, Verzögerung, Verschiebung |
| `Technik` | Brandschutz, Baumängel, Systeme |
| `Planung` | Ausschreibung, Konzept, Standortwahl |
| `Claim` | Pressemeinung, Einschätzung ohne konkretes Ereignis |

---

## Tests

```bash
npm test   # Playwright E2E
```

---

## Phase 2 (noch offen)

- Kuratierte Narrative: 5–10 Schlüsselmomente als Anker
- Öffentliches Deployment (GitHub Pages / Vercel / Railway)
- Chat-Interface für Endnutzer ohne Recherche-Hintergrund
