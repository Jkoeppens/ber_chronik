# BER Chronik – Projektplan

**Quelle:** Chronik der Entwicklung 1989–2017, zusammengestellt von André Geicke  
**Ziel:** Interaktives Recherchetool (Phase 1) → öffentliche Erzählung (Phase 2)  
**Prinzip:** Reproduzierbar, verständlich, kein Blackbox-Code

---

## Arbeitsumgebung

**Planung & Entscheidungen** → hier (Claude Chat)  
**Implementierung** → Claude Code (Terminal, Datei-Zugriff, Skripte ausführen)  
**Versionierung** → Git-Repo, reproduzierbar, kein Blackbox-Code

Wechsel zu Claude Code sobald du anfängst, Skripte zu schreiben oder auszuführen. Bring den Plan als `README.md` mit ins Repo. Wenn du inhaltliche Entscheidungen zu treffen hast (Kategorien, Akteursliste, was gesplittet wird), komm zurück hierher.

---

## Was das Dokument ist – und was das bedeutet

978 Absätze, 29 Jahresabschnitte. Geicke hat drei Typen von Einträgen gemischt:

- **Belegte Ereignisse** mit Datum und Quellenangabe  
  `„Am 13. Oktober gibt das OLG Hochtief Recht..." Tsp, 14.10.2000`
- **Paraphrasen ohne Quelle** – Geickes eigene Einordnung, oft besonders wertvoll
- **Direkte Zitate** aus Artikeln, meist in „Anführungszeichen"

Das hat Konsequenzen: Es gibt keine perfekt saubere Datentabelle am Ende. Das Ziel ist eine *hinreichend strukturierte* Tabelle, bei der du jeden Eintrag zum Originalabsatz zurückverfolgen kannst.

---

## Architektur: Zwei Phasen, eine Datenbasis

```
Rohdokument (DOCX)
      │
      ▼
paragraphs_raw.csv        ← du hast das bereits
      │
      ▼
paragraphs_enriched.csv   ← Phase 1 Ziel
  (Datum, Quelle, Typ, Akteure, Konfidenz)
      │
      ├──► Timeline-Visualisierung (Phase 1)
      ├──► Akteursnetzwerk         (Phase 1)
      └──► Chat-Interface          (Phase 2)
```

Die CSV ist die einzige Quelle der Wahrheit. Alle Visualisierungen lesen daraus.  
Manuelle Korrekturen gehen in eine separate `overrides.csv`, nie direkt in die generierte Datei.

---

## Phase 1: Recherchetool

### Schritt 1 – Ingest ✅ (erledigt)
**Skript:** `src/ingest_docx.py`  
**Output:** `data/interim/paragraphs_raw.csv`

978 Zeilen, year_bucket 1989–2017, doc_anchor für Rückverfolgbarkeit.

---

### Schritt 2 – Feature-Extraktion
**Skripte:** `src/berchronik/parse_features.py` + `src/berchronik/classify_events.py`
**Output:** `data/interim/paragraphs_enriched.csv`

Zwei Stufen, die zusammen die enriched CSV befüllen:

**Stufe 2a – Regex-Features** (`parse_features.py`):

| Feld | Methode | Beispiel |
|------|---------|---------|
| `date_raw` | Regex im Text | `„13. Oktober"`, `„Am 3. August"` |
| `date_precision` | aus Regex-Match | `exact` / `month_day` / `month` / `year` / `none` |
| `source_name` | Regex überall im Text, `findall` | `Tsp`, `BerlZtg;Tsp` (`;`-getrennt bei mehreren) |
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

**Wichtig:** Alles hier ist automatisch und fehlerbehaftet. Das ist gewollt.
Fehler werden nicht im Skript gefixt, sondern in `overrides.csv` korrigiert.

---

### Schritt 3 – Ereignistypen definieren (manuell, iterativ)
**Kein Skript. Du arbeitest in der CSV.**

Die Taxonomie hat zwei unabhängige Achsen:

**Achse 1 – `event_type`** (was ist passiert, maschinell erkennbar per Keyword):

| Wert | Bedeutung |
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

Achse 1 befüllt `parse_features.py` automatisch. Jeder Eintrag hat **genau einen** Wert.

**Achse 2 – `causal_theme`** (warum relevant fürs Scheitern, manuell kuratiert):

`Standortwahl` · `Generalunternehmer` · `Governance` · `Pol_Eitelkeit` · `Finanzierung` · `Brandschutz` · `Oeffentlicher_Widerstand` · `Externer_Schock`

Achse 2 ist ein Array – ein Eintrag kann mehrere Themen haben. Sie bleibt leer bis du sie manuell befüllst. Vollständigkeit nicht nötig: 30% Abdeckung reicht für die Erzählung.

**Workflow:**  
Öffne `paragraphs_enriched.csv` in einem Tabelleneditor (Numbers, LibreOffice, Google Sheets).  
Filtere auf `confidence = low` oder `event_type = ?`.  
Trag Korrekturen in `event_type_manual` und `causal_theme` ein.  
`apply_overrides.py` mergt deine Korrekturen in die Haupttabelle.

---

### Schritt 4 – Akteure
**Skript:** `src/entities.py`  
**Input:** `config/entities_seed.csv` (du pflegst diese Datei)  
**Output:** Spalte `actors` in `paragraphs_enriched.csv`

Zweistufig:

1. **Dictionary-Matching** – du legst eine Seed-Liste an mit Kürzeln und Normalformen:
   ```
   Kürzel, Normalform, Typ
   Tsp, Tagesspiegel, Medium
   BBF, Berlin-Brandenburg Flughafenholding, Org
   FBB, Flughafen Berlin Brandenburg GmbH, Org
   Wowereit, Klaus Wowereit, Person
   ```
2. **Kandidatenliste** – alles was häufig vorkommt aber nicht im Dictionary ist,  
   landet in `data/interim/entity_candidates.csv` zur manuellen Entscheidung.

Die Seed-Liste wächst iterativ. Du fängst mit 20 Einträgen an, nicht mit 200.

---

### Schritt 5 – Visualisierung (Timeline)
**Technologie:** Einfaches HTML/JS, keine Build-Pipeline nötig, läuft lokal im Browser.

**Was die Timeline zeigt:**
- X-Achse: Jahr (1989–2017)
- Y-Achse / Farbe: Ereignistyp
- Jeder Punkt: ein Absatz – klickbar, öffnet Originaltext + Quellenangabe
- Filter: Jahr, Ereignistyp, Akteur, Suchtext
- Density-Ansicht: Heatmap wann welche Typen auftreten (das „Scheiternsmuster" sichtbar machen)

**Meilenstein:** Erste lauffähige Version schon nach Schritt 2, auch mit unvollständigen Daten.  
Lieber früh sehen ob das Interface stimmt.

---

### Schritt 6 – Akteursnetzwerk
**Technologie:** D3.js Force-Graph oder einfaches Cytoscape.js

Knoten: Personen + Organisationen  
Kanten: Beide erscheinen im selben Absatz  
Gewicht: Häufigkeit der gemeinsamen Nennungen  
Filter: Zeitraum eingrenzbar

---

## Phase 2: Öffentliche Erzählung (später)

Erst wenn Phase 1 stabil ist. Die Datenbasis bleibt dieselbe.

Was hinzukommt:
- **Kuratierte Narrative** – du markierst 5–10 „Schlüsselmomente" in der CSV, die als Anker für die Erzählung dienen
- **Chat-Interface** – Frage stellen, Antwort mit verlinkten Originalquellen; funktioniert über Embeddings auf der enriched CSV
- **Öffentliches Deployment** – GitHub Pages oder Vercel, statische Seite

---

## Repo-Struktur

```
ber-chronik/
  README.md               ← dieser Plan, gekürzt
  .gitignore

  data/
    raw/
      Flh_Bln_Chronik_1989-2017.docx
    interim/
      paragraphs_raw.csv
      paragraphs_enriched.csv
      entity_candidates.csv
    processed/
      paragraphs_final.csv    ← nach Override-Merge
      entities_dictionary.csv

  config/
    event_types.yml           ← Keyword → Typ Mapping
    entities_seed.csv         ← deine Akteursliste

  src/
    ingest_docx.py            ✅ fertig
    parse_features.py         ← nächster Schritt
    entities.py
    apply_overrides.py
    export_viz.py

  viz/
    index.html                ← Timeline
    network.html              ← Akteursnetz

  overrides/
    paragraphs_overrides.csv  ← deine manuellen Korrekturen
    notes.md                  ← Beobachtungen während Review
```

**Gitignore:** `data/raw/` bleibt lokal (Urheberrecht). Alles andere wird versioniert.

---

## Arbeitsweise

**Du steuerst, ich schreibe Code.**  
Du verstehst was jedes Skript tut – ich erkläre bevor ich schreibe, nicht danach.  
Experimente passieren in Notebooks (`notebooks/`), sauberer Code landet in `src/`.  
Jede manuelle Korrektur geht in `overrides/`, nie in generierte Dateien.

**Nächster konkreter Schritt:** `parse_features.py`

---

## Offene Fragen (zu entscheiden, nicht jetzt)

- Soll das Dokument selbst im Repo sein, oder nur die abgeleiteten CSVs?
- Sollen Geickes eigene Kommentare (`is_geicke = True`) anders behandelt werden als belegte Ereignisse?
- Welche Akteure sind für das Netzwerk wirklich interessant – alle, oder nur die mit >3 Nennungen?