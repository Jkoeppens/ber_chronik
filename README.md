# BER Chronik

Ein interaktives Tool das 28 Jahre Planungs- und Baugeschichte des Berliner Flughafens BER durchsuchbar macht.

## Was es kann

- **Timeline** — alle Ereignisse von 1989 bis 2017 nach Jahr und Thema, klickbar und filterbar
- **Akteursnetzwerk** — Personen, Organisationen und Gremien als Graph; Knotengröße zeigt Häufigkeit, Kanten entstehen aus gemeinsamen Erwähnungen
- **KI-Suche** — Fragen in natürlicher Sprache werden gegen die Originalabsätze der Chronik beantwortet, mit klickbaren Quellenverweisen
- **Ko-Navigation** — Timeline, Netzwerk und Panel sind synchronisiert: ein ausgewählter Akteur wird in allen Ansichten gleichzeitig hervorgehoben

## Architektur

Die Datenaufbereitung läuft lokal: spaCy extrahiert Personen, Organisationen und Gremien per Named Entity Recognition, Ollama mit einem lokalen Llama-Modell klassifiziert die Themen der einzelnen Absätze. Das aufbereitete Datenmaterial liegt als statisches JSON vor und wird direkt im Browser geladen. Die Visualisierung — Timeline und Netzwerkgraph — ist vollständig in D3.js im Browser implementiert. Für die KI-gestützte Suche läuft ein FastAPI-Backend auf einem externen Server; es nimmt Suchanfragen entgegen, wählt relevante Absätze per Volltextsuche aus und synthetisiert die Antwort über die Claude API.

## Datengrundlage

Grundlage ist das Protokoll des Berliner Untersuchungsausschusses zum BER, ca. 100 Seiten. Themenklassifikation und Entitätserkennung sind eigenständig durchgeführt und nicht mit dem Originaldokument ausgeliefert.

## Tech Stack

Python · spaCy · Ollama (Llama 3.1) · FastAPI · D3.js · Claude API (Anthropic)

## Status

Prototyp, in aktiver Entwicklung.

---

## Was das Dokument ist – und was das bedeutet

978 Absätze, 29 Jahresabschnitte. Geicke hat drei Typen von Einträgen gemischt:

- **Belegte Ereignisse** mit Datum und Quellenangabe
  `„Am 13. Oktober gibt das OLG Hochtief Recht..." Tsp, 14.10.2000`
- **Paraphrasen ohne Quelle** – Geickes eigene Einordnung, oft besonders wertvoll
- **Direkte Zitate** aus Artikeln, meist in „Anführungszeichen"

Das hat Konsequenzen: Es gibt keine perfekt saubere Datentabelle am Ende. Das Ziel ist eine *hinreichend strukturierte* Tabelle, bei der du jeden Eintrag zum Originalabsatz zurückverfolgen kannst.

---

## Architektur

```
Rohdokument (DOCX)
      │
      ▼
paragraphs_raw.csv          ← Schritt 1
      │
      ▼
paragraphs_enriched.csv     ← Schritte 2–4
  (Datum, Quelle, Typ, Akteure, Konfidenz)
      │
      ▼
viz/data.json               ← Schritt 5a
      │
      ├──► Timeline-Visualisierung  ✅
      └──► Akteursnetzwerk          ✅
```

Die CSV ist die einzige Quelle der Wahrheit. Alle Visualisierungen lesen daraus.
Manuelle Korrekturen gehen in eine separate `overrides.csv`, nie direkt in die generierte Datei.

---

## Phase 1: Recherchetool

### Schritt 1 – Ingest ✅

**Skript:** `src/berchronik/ingest_docx.py`
**Output:** `data/interim/paragraphs_raw.csv`

978 Zeilen (davon 29 Jahres-Überschriften), `year_bucket` 1989–2017, `doc_anchor` (p1…p978) für Rückverfolgbarkeit.

---

### Schritt 2 – Feature-Extraktion ✅

**Skripte:** `src/berchronik/parse_features.py` + `src/berchronik/classify_events.py`
**Output:** `data/interim/paragraphs_enriched.csv`

Zwei Stufen, die zusammen die enriched CSV befüllen:

**Stufe 2a – Regex-Features** (`parse_features.py`):

| Feld | Methode | Beispiel |
|------|---------|---------|
| `date_raw` | Regex im Text | `„13. Oktober"`, `„Am 3. August"` |
| `date_precision` | aus Regex-Match | `exact` / `month_day` / `month` / `year` / `none` |
| `source_name` | `findall` überall im Text | `Tsp`, `BerlZtg;Tsp` (`;`-getrennt bei mehreren) |
| `source_date` | wie source_name | `14.10.2000`, `30.04.91` (zwei- oder vierstellig) |
| `is_quote` | beginnt mit `„` | `True/False` |
| `is_geicke` | kein Quellbeleg, kein Zitat | eigene Einordnung des Autors |

**Stufe 2b – LLM-Klassifikation** (`classify_events.py`):

| Feld | Methode | Beispiel |
|------|---------|---------|
| `event_type` | Ollama lokal, Modell `mistral` | `Klage`, `Kosten`, `Termin`, … |
| `confidence` | vom LLM bewertet | `high` / `med` / `low` |

Mögliche Werte für `event_type`: `Beschluss` · `Vertrag` · `Klage` · `Personalie` · `Kosten` · `Termin` · `Technik` · `Planung` · `Claim`

Der Prompt ist auf Englisch, Kategorienamen bleiben Deutsch. Bei ungültigem JSON-Response: einmal Retry, danach `event_type=None` / `confidence=low`.

**Hinweis:** Alles hier ist automatisch und fehlerbehaftet. Das ist gewollt. Fehler werden nicht im Skript gefixt, sondern in `event_type_manual` oder `overrides/` korrigiert.

---

### Schritt 3 – Ereignistypen definieren (manuell, iterativ)

**Kein Skript. Du arbeitest in der CSV.**

| `event_type` | Bedeutung |
|------|-----------|
| `Beschluss` | Politische oder behördliche Entscheidung |
| `Vertrag` | Unterzeichnung, Letter of Intent |
| `Klage` | Gericht, OLG, Vergabekammer, Urteil |
| `Personalie` | Rücktritt, Ernennung, Wechsel |
| `Kosten` | Kostensteigerung, Budget, Kredit |
| `Termin` | Eröffnungstermin, Verzögerung, Verschiebung |
| `Technik` | Brandschutz, Baumängel, Systeme |
| `Planung` | Ausschreibung, Konzept, Standortwahl |
| `Claim` | Pressemeinung, Einschätzung ohne Ereignis |

Manuelle Korrekturen: Feld `event_type_manual` in der CSV (überschreibt `event_type` beim Export).
`causal_theme` (Array, `;`-getrennt) bleibt leer bis manuell befüllt.

---

### Schritt 4 – Akteure ✅

**Skript:** `src/berchronik/entities.py`
**Input:** `config/entities_seed.csv`
**Output:** Spalte `actors` in `paragraphs_enriched.csv`, `data/interim/entity_candidates.csv`

Zweistufig:

**Stufe 4a – Dictionary-Matching:**
`config/entities_seed.csv` enthält Aliase und Normalformen (213 Zeilen, Typen: Person/Org/Gremium).

- **Multi-Wort-Aliase** (z.B. `Flughafen Berlin Brandenburg`) → spaCy `PhraseMatcher`
- **Einzel-Wort-Aliase** (z.B. `SPD`, `CDU`, `BER`) → Regex mit `\b`-Wortgrenzen

Der Regex-Fix war nötig weil spaCy `SPD-Fraktion` als ein Token tokenisiert und `PhraseMatcher` `SPD` darin nicht findet. Regex mit `\bSPD\b` matcht korrekt auf die Wortgrenze zwischen `D` und `-`.

Ergebnis: **659/949 Absätze** mit mindestens einem Akteur, **112 eindeutige Normalformen** in der enriched CSV.

**Stufe 4b – NER-Kandidaten:**
spaCy `de_core_news_sm` erkennt PER/ORG-Entitäten die nicht im Dictionary stehen → `entity_candidates.csv` zur manuellen Entscheidung (Schwellwert: ≥ 2 Nennungen).

---

### Schritt 5 – Visualisierung ✅

**Skript:** `src/berchronik/export_viz.py`
**Output:** `viz/data.json`, `viz/entities_summary.json`

```bash
# Daten exportieren
PYTHONPATH=src python -m berchronik.export_viz

# Mistral-Zusammenfassungen generieren (Ollama muss laufen)
PYTHONPATH=src python -m berchronik.export_viz --summaries
```

**`viz/index.html`** – Alles in einer Datei, kein Build-Tool, D3.js v7 via CDN.

**Tab 1 – Timeline:**
- Liniendiagramm, X-Achse 1989–2017, eine Linie pro Ereignistyp
- Klick auf einen Punkt → alle Absätze dieses Jahres/Typs im Panel, scrollbar
- Entity-Highlighting im Absatztext (Person=blau, Org=orange, Gremium=lila, Partei=rot)
- Klick auf markierten Namen → Mistral-Zusammenfassung, Wikipedia-Navigation zwischen Entities

**Tab 2 – Netzwerk:**
- D3 Force-Graph: Knoten = Entities, Kanten = gemeinsame Nennungen im selben Absatz
- Knotengröße nach Anzahl Nennungen, Farbe nach Typ
- Gestrichelter Rand = keine Mistral-Zusammenfassung vorhanden
- Klick auf Knoten → alle Absätze dieser Entity, chronologisch

**Entity-Zusammenfassungen:**
69 Entities mit ≥ 3 Nennungen haben eine Mistral-Zusammenfassung in `viz/entities_summary.json`.
Resume-fähig: bricht die Generierung ab, startet sie dort wo sie aufgehört hat.

---

## Repo-Struktur

```
ber-chronik/
  README.md
  .gitignore
  vercel.json                         ← Deployment-Config (outputDirectory: viz)
  requirements.txt

  data/
    raw/                              ← nicht im Repo (Urheberrecht)
      Flh_Bln_Chronik_1989-2017.docx
    interim/
      paragraphs_raw.csv              ← Schritt 1 Output
      paragraphs_enriched.csv         ← Schritte 2–4 Output
      entity_candidates.csv           ← NER-Kandidaten zur manuellen Prüfung

  config/
    entities_seed.csv                 ← Akteursliste (213 Aliase, 125 Normalformen)
    sources_seed.csv                  ← Medienkürzel-Normalisierung

  src/berchronik/
    ingest_docx.py                    ← Schritt 1
    parse_features.py                 ← Schritt 2a
    classify_events.py                ← Schritt 2b (Mistral via Ollama)
    entities.py                       ← Schritt 4
    export_viz.py                     ← Schritt 5 (data.json + Summaries)

  viz/
    index.html                        ← Timeline + Netzwerk (eine Datei)
    data.json                         ← 949 Absätze
    entities_summary.json             ← 69 Mistral-Zusammenfassungen
    entities_seed.csv                 ← Kopie für self-contained Deployment

  overrides/
    notes.md                          ← Entscheidungen und Beobachtungen

  .github/workflows/
    deploy.yml                        ← GitHub Pages Deployment
```

---

## Lokale Entwicklung

### Voraussetzungen

- Python 3.11 (via pyenv empfohlen)
- [Ollama](https://ollama.com) mit `mistral`-Modell für LLM-Klassifikation und Zusammenfassungen

### Setup

```bash
# Repository klonen
git clone git@github.com:Jkoeppens/ber_chronik.git
cd ber_chronik

# Virtuelle Umgebung erstellen (Python 3.11 explizit)
python3.11 -m venv .venv
source .venv/bin/activate

# Dependencies installieren
pip install -r requirements.txt

# spaCy-Modell laden
python -m spacy download de_core_news_sm
```

### Pipeline ausführen

```bash
# Schritt 1 – DOCX einlesen (data/raw/ muss das Original enthalten)
PYTHONPATH=src python -m berchronik.ingest_docx

# Schritt 2a – Regex-Features extrahieren
PYTHONPATH=src python -m berchronik.parse_features

# Schritt 2b – Ereignistypen klassifizieren (Ollama muss laufen: ollama serve)
PYTHONPATH=src python -m berchronik.classify_events

# Schritt 4 – Akteure matchen
PYTHONPATH=src python -m berchronik.entities

# Schritt 5a – Daten für Visualisierung exportieren
PYTHONPATH=src python -m berchronik.export_viz

# Schritt 5b – Mistral-Zusammenfassungen generieren (resume-fähig)
PYTHONPATH=src python -m berchronik.export_viz --summaries
```

### Visualisierung lokal starten

```bash
# Server aus dem Projektroot starten
python3 -m http.server 8765

# Dann im Browser öffnen:
# http://localhost:8765/viz/
```

### Nur Visualisierung (ohne Pipeline)

Alle nötigen Dateien liegen bereits im Repo (`viz/data.json`, `viz/entities_summary.json`).
Direkt Server starten und `http://localhost:8765/viz/` öffnen.

---

## Phase 2: Öffentliche Erzählung (später)

Erst wenn Phase 1 stabil ist. Die Datenbasis bleibt dieselbe.

- **Kuratierte Narrative** – 5–10 Schlüsselmomente in der CSV markieren
- **Chat-Interface** – Frage stellen, Antwort mit verlinkten Originalquellen (Embeddings auf enriched CSV)
- **Öffentliches Deployment** – GitHub Pages ✅ bereits eingerichtet
