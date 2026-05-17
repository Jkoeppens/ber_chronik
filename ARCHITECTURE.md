# BER Chronik — Server-Architektur

> Dieses Dokument beschreibt den Server-seitigen Teil des Systems:
> Dateipfade, Auth-Pattern, SSE-Protokoll, Datenbank und historisches Erbe.
> Viz/JS-Architektur lebt in DECISIONS.md (Abschnitt „Architektur").

---

## Datenpfade (PROJECTS_DIR-Schema)

`PROJECTS_DIR` ist `data/projects/`. Darunter liegen Projekte als Verzeichnisse,
jedes mit einem Slug als Name (Beispiel: `ber`, `damaskus`).

```
data/
└── projects/
    └── {project_id}/                   ← _slugify(title), z.B. "ber"
        ├── config.json                 ← Einzige autoritative Quelle:
        │                                  taxonomy, entities, title, year_min/max,
        │                                  doc_type, obsidian.*
        ├── obsidian_checkpoint.json    ← Welche .md-Dateien bereits ingested
        ├── documents/
        │   └── {doc_id}/               ← doc_id = uuid4 hex (8 Zeichen), außer "main"
        │       ├── config.json         ← doc_type, original_filename, ingested_at
        │       ├── segments.json       ← parse_document / ingest_obsidian Output
        │       ├── anchors.json        ← detect_anchors Output
        │       ├── anchors_interpolated.json  ← interpolate_anchors Output
        │       ├── classified.json     ← classify_segments + match_entities (D-P3)
        │       ├── overrides.json      ← manuelle Anker-Korrekturen
        │       ├── preview.html        ← export_preview Output
        │       └── bge_embeddings.npy  ← Cache für BGE-M3 (git-ignoriert)
        └── exploration/
            ├── data.json               ← export_exploration Output (Haupt-Datendatei)
            ├── project_meta.json       ← Farb-Mapping, Taxonomie-Summary
            ├── entities_seed.csv       ← Alias-Tabelle für Entity-Highlighting
            ├── entities_summary.json   ← LLM-Zusammenfassungen pro Entity
            └── network_layout.json     ← Vorberechnetes D3-Netzwerk-Layout

data/
├── projects.db                         ← SQLite: Projekt-Auth, Token, Dokument-Metadaten
└── dropbox_tokens.json                 ← Dropbox OAuth2 Tokens (refresh_token + access_token)
```

### Kanonizität

`config.json` auf Projektebene ist die einzige autoritative Quelle für Taxonomie
(D-P1) und Entities (D-P4). Die Felder `year_min`/`year_max` werden von
`export_exploration.py` am Ende eines jeden Exports frisch aus den tatsächlichen
Eintrags-Jahren berechnet und zurückgeschrieben — nicht aus den Rohanker-Daten.

`classified.json` auf Dokumentebene ist ein gemeinsames Dokument (D-P3):
`classify_segments.py` schreibt `category` + `confidence`,
`match_entities.py` ergänzt `actors` in-place. Beide müssen in dieser Reihenfolge
laufen, damit kein Mischzustand entsteht.

### SQLite (`projects.db`)

Zwei Tabellen:
- `projects`: `id`, `title`, `doc_type`, `created_at`, `status`, `token`, `is_public`, `owner_token`
- `documents`: `doc_id`, `project_id`, `ingested_at`, `doc_type`, `ingest_source`, `original_filename`

`projects.db` ist die autoritative Quelle für Auth-Token. `config.json` ist die
autoritative Quelle für Inhaltsdaten. Die beiden überschneiden sich nicht —
`projects.db` kennt keine Taxonomie, `config.json` kennt keine Token.

---

## SSE-Protokoll

Alle langen Pipeline-Operationen streamen als `text/event-stream`. Der Vertrag
ist implizit (kein OpenAPI-Schema), aber fest — jeder Client, der SSE konsumiert,
verlässt sich auf genau diese Sentinels:

| Sentinel | Richtung | Bedeutung |
|---|---|---|
| `data: __ok__\n\n` | Server → Client | Schritt erfolgreich abgeschlossen. `run_pipeline_sse` bricht innere Schleife ab und geht zum nächsten Schritt. |
| `data: __error__ <text>\n\n` | Server → Client | Fataler Fehler. `run_pipeline_sse` bricht ab und schickt kein `__done__`. Client sollte UI als fehlgeschlagen markieren. |
| `data: __done__\n\n` | Server → Client | Gesamte Pipeline abgeschlossen (alle Schritte). Immer letztes Event wenn kein `__error__` kam. |
| `data: __link__:<url>\n\n` | Server → Client | Optionaler Deeplink direkt vor `__done__`. Wizard öffnet diesen Link automatisch. Aktuell nur in `POST /ingest/run` nach `export_exploration`. |

Alle anderen `data:` Zeilen sind menschenlesbare Fortschrittszeilen (stdout/stderr
des Subprozesses). Der Client darf sie anzeigen, aber nicht programmatisch parsen.

### Implementierung

```python
async def run_script_sse(script_path, args):
    # …startet subprocess, leitet stdout/stderr zeilenweise weiter…
    if proc.returncode != 0:
        yield f"data: __error__ {label} Exit-Code {proc.returncode}\n\n"
        return
    yield "data: __ok__\n\n"

async def run_pipeline_sse(steps):
    for script, args in steps:
        async for chunk in run_script_sse(script, args):
            if chunk == "data: __ok__\n\n":
                break                        # → nächster Schritt
            yield chunk
            if "__error__" in chunk:
                return                       # Kein __done__
    yield "data: __done__\n\n"
```

`sse_response(gen)` wraps jeden async Generator in `StreamingResponse` mit
`Cache-Control: no-cache` und `X-Accel-Buffering: no` (verhindert Nginx-Pufferung).

---

## Auth-Pattern: `_require_token`

### Aufrufsyntax (Walrus-Operator)

```python
@app.post("/taxonomy/save")
async def save_taxonomy(request: Request):
    project = request.query_params.get("project")
    if err := await _require_token(request, project): return err
    # …
```

`_require_token` gibt `None` bei Erfolg, eine fertige `JSONResponse(403)` bei
Misserfolg zurück. Der Walrus-Operator (`:=`) weist das Ergebnis zu und prüft
gleichzeitig ob es truthy ist — `None` ist falsy, daher kein Early-Return.

### Was geprüft wird

1. Token aus `?token=` Query-Parameter oder `X-Project-Token` Header
2. Projekt existiert in SQLite (`projects` Tabelle)
3. Token stimmt mit `projects.token` überein und ist nicht abgelaufen (30 Tage TTL)
4. Wenn Projekt einen `owner_token` hat: Invite-Token des Requesters muss passen

### Warum kein FastAPI `Dependency`

FastAPI `Depends()` ist für Middleware gedacht die für jede Route gleich ist.
`_require_token` braucht aber die `project`-ID, die je nach Endpoint unterschiedlich
kommt:
- Manche Endpoints: `project = request.query_params.get("project")` (Wizard-Flows)
- Manche Endpoints: `project_id` als Pfadparameter (REST `/api/projects/{project_id}/…`)
- Einige Endpoints: kein Token nötig (GET `/api/projects` Übersicht, statische Assets)

Eine `Depends()`-Lösung müsste diese Unterschiede über Overrides oder komplexe
Parameter-Forwarding lösen. Das explizite Inline-Pattern ist lesbarer und hat
keine versteckten Abhängigkeiten.

`_require_admin_key` (für Projekt-Erstellung) folgt demselben Muster, ist aber
synchron da kein DB-Lookup nötig.

---

## `z`-Präfix: Zotero-Erbgut

Im Codebase taucht `z` als Variablen- oder Kommentar-Präfix sporadisch auf
(z.B. in Kommentaren in `detect_anchors.py`: „Zotero/Obsidian",
in `interpolate_anchors.py`: „DOCX, Zotero, Obsidian").

**Das ist historisch bedingt.** Zotero war bis 2026-05-12 der primäre externe
Ingest-Pfad. `ingest_zotero.py` existiert noch auf dem Dateisystem, hat aber
keine aktiven Endpoints mehr in `dev_server.py`. Alle Zotero-Referenzen im
restlichen Code beschreiben das frühere Verhalten, sind aber inhaltlich weiterhin
korrekt — Obsidian folgt denselben Konventionen (ein content-Segment pro Artikel,
`date`-Feld für Datierung, gleicher presseartikel-Bypass in `interpolate_anchors.py`).

Ein `z_`-Präfix auf einer Variable ist kein Code-Stil, sondern ein Zufallstreffer.
Das System hat keine einheitliche Namenskonvention für Quell-Typ-Präfixe.

---

## Locks: `_project_lock(project)`

```python
_project_locks: dict[str, asyncio.Lock] = {}

def _project_lock(project: str) -> asyncio.Lock:
    if project not in _project_locks:
        _project_locks[project] = asyncio.Lock()
    return _project_locks[project]
```

Alle Endpoints die `config.json` lesen und zurückschreiben (Read-Modify-Write)
laufen unter `async with _project_lock(project):`. Das verhindert Race Conditions
wenn zwei Requests gleichzeitig z.B. taxonomy und entities in dieselbe Datei
schreiben.

Lock-Granularität ist Projekt-ID (nicht global), damit parallele Requests auf
unterschiedliche Projekte sich nicht blockieren.

---

## Entfernte Features

### Zotero-Ingest

**Deaktiviert seit: 2026-05-12** (ersetzt durch Obsidian/Dropbox, D-I1)

Der Zotero-Flow war ein direkter API-Ingest ohne Wizard-Schritte:

1. Nutzer konfiguriert API-Key, User-ID, Collection-ID in der Projektkarte
2. `POST /api/projects/{id}/zotero/config` speichert Credentials in `config.json["zotero"]`
3. `GET /api/projects/_new/zotero/test` testet die Verbindung via pyzotero im Thread-Executor
4. `POST /api/projects/{id}/zotero/sync` (SSE) → `ingest_zotero.py` läuft durch:
   - pyzotero: Items der Collection laden
   - Checkpoint prüfen (`zotero_checkpoint.json`) — neue Items identifizieren
   - Segmente bauen, detect_anchors, interpolate, classify, match_entities, export_preview
   - Checkpoint aktualisieren

**Diese Endpoints existieren nicht mehr in `dev_server.py`.**
`ingest_zotero.py` liegt noch im Dateisystem (`src/generalized/ingest_zotero.py`),
wird aber von keinem Endpoint aufgerufen. `D-E3` (`videoRecording`-Filterung) und
das `item_type`-Feld in Segmenten sind Zotero-Erbgut, das durch GLiNER/Obsidian
faktisch obsolet ist aber nicht entfernt wurde.

`WIZARD_FLOW.md` enthält noch einen Zotero-Flow-Abschnitt — dort als historische
Dokumentation belassen.

---

## Segment-Schema

Ein Segment ist ein Dict. Welche Felder gesetzt sind, hängt davon ab welche Skripte
bisher gelaufen sind. Die Tabelle zeigt den vollständigen Lebenszyklus:

| Feld | Typ | Gesetzt von | Mögliche Werte / Hinweis |
|---|---|---|---|
| `segment_id` | `str` | `parse_document`, `ingest_obsidian` | `"s0001"` … `"s9999"` — fortlaufend pro Dokument |
| `type` | `str` | `parse_document`, `ingest_obsidian` | `"content"` \| `"heading"` — headings werden nach detect_anchors herausgefiltert |
| `text` | `str` | `parse_document`, `ingest_obsidian` | Originaler Absatztext |
| `source` | `str \| dict \| None` | `parse_document` | String (Quellenname) oder `{"name": "…", "date": "…"}` bei DOCX mit Datumsangabe; `None` für unbekannte Quellen |
| `page` | `int \| None` | `parse_document` | DOCX-Seitennummer, `None` bei Obsidian |
| `doc_type` | `str` | `parse_document`, `ingest_obsidian` | `"presseartikel"` \| `"buchnotizen"` — Typ des übergeordneten Dokuments |
| `ingest_source` | `str` | `parse_document`, `ingest_obsidian` | `"docx"` \| `"obsidian"` |
| `source_date` | `str \| None` | `parse_document` | Datumsstring aus DOCX-Quellen-Notation (z.B. `"15.03.2005"`), nur DOCX |
| `is_quote` | `bool` | `parse_document` | `True` wenn Text mit Anführungszeichen beginnt |
| `date` | `str \| None` | `ingest_obsidian` | ISO-Datum aus Frontmatter (`published` oder `created`), nur Obsidian |
| `date_raw` | `str \| None` | `detect_anchors` (via presseartikel-Bypass) | Rohes Datum für Timeline-Positionierung; analog zu `date` bei Obsidian/Zotero |
| `url` | `str` | `ingest_obsidian` | Quell-URL; leer (`""`) für DOCX |
| `author` | `str` | `ingest_obsidian` | Autor aus Frontmatter; fehlt bei DOCX-Segmenten |
| `abstract` | `str` | `ingest_obsidian` | Beschreibung aus Frontmatter; fehlt bei DOCX-Segmenten |
| `obsidian_path` | `str` | `ingest_obsidian` | Relativer Pfad der Markdown-Quelldatei |
| `anchors` | `list[dict]` | `detect_anchors` | Erkannte Zeitanker: `[{"type": "exact"\|"decade"\|"event", "value": int\|null, "span": str}]` |
| `time_from` | `int \| None` | `detect_anchors`, `interpolate_anchors` | Jahr-Untergrenze; `None` wenn undatiert |
| `time_to` | `int \| None` | `detect_anchors`, `interpolate_anchors` | Jahr-Obergrenze; gleich `time_from` bei Punkt-Datierung |
| `precision` | `str \| None` | `detect_anchors`, `interpolate_anchors` | `"exact"` \| `"heading"` \| `"event"` \| `"decade"` \| `"manual"` \| `"interpolated"` \| `null` |
| `category` | `str \| None` | `classify_segments` | Taxonomie-Kategorie-Label; `None` wenn Klassifizierung fehlschlug |
| `confidence` | `str \| None` | `classify_segments` | `"high"` \| `"medium"` \| `"low"` \| `None` (None = Fehlerfall, wird bei Resume erneut versucht) |
| `actors` | `list[str]` | `match_entities` | Normformen der erkannten Entitäten; `[]` wenn keine Treffer |

### Wann ein Feld fehlen kann

- DOCX-Segmente haben kein `url`, `author`, `abstract`, `obsidian_path`, `date`.
- Obsidian-Segmente haben kein `source_date`, `is_quote`, `page`.
- `anchors`, `time_from`, `time_to`, `precision` fehlen vor `detect_anchors`-Lauf.
- `category`, `confidence`, `actors` fehlen vor `classify_segments`-Lauf (bzw. vor `match_entities`-Lauf für `actors`).
- `precision = null` und `time_from = null` bedeuten: kein Anker gefunden, Interpolation nicht möglich.

---

## data.json-Schema (exploration/data.json)

`exploration/data.json` ist die zentrale Schnittstelle zwischen Pipeline
und Visualisierungs-App. Autoritative Quelle: `export_exploration.py:build_entries()`.

### Toplevel

```json
{
  "generated": "2026-05-16",
  "count":     1234,
  "entries":   [ … ]
}
```

| Feld | Typ | Inhalt |
|---|---|---|
| `generated` | `str` | ISO-Datum des letzten Exports |
| `count` | `int` | Anzahl Einträge (= `len(entries)`) |
| `entries` | `list[dict]` | Alle datierten content-Segmente (undatierte werden herausgefiltert) |

### Entry-Schema

Jedes Element von `entries` entspricht einem datierten content-Segment:

| Feld | Typ | Inhalt |
|---|---|---|
| `id` | `int` | Fortlaufend ab 1 — stabiler Index für die Visualisierung |
| `doc_anchor` | `str` | `segment_id` aus dem Segment (`"s0001"`) |
| `year` | `int \| null` | `time_from` des Segments — Jahr-Untergrenze für Heatmap-Einordnung |
| `date_raw` | `str \| null` | Rohes Datum (`"15.03.2005"`, `"2005"`, `"2005-03-15"`) — für Tooltip |
| `date_js` | `str \| null` | ISO-8601-String (`"2005-03-15"`) — für präzises Timeline-Positioning; bei Jahresdatum `"{year}-01-01"` |
| `date_precision` | `str` | `"exact"` (exact/heading/manual) \| `"year"` (interpolated/decade/event) \| `"none"` |
| `text` | `str` | Originaltext des Segments |
| `event_type` | `str \| null` | Taxonomie-Kategorie nach Normalisierung; `null` wenn unklassifiziert |
| `confidence` | `str \| null` | `"high"` \| `"med"` \| `"low"` \| `null` (`"medium"` wird zu `"med"` normiert) |
| `source_name` | `str \| null` | Quellname (aus `seg.source`) |
| `source_date` | `str \| null` | Quell-Datum (aus `seg.source.date` oder `date_raw`) |
| `url` | `str` | URL der Quelle; `""` für DOCX-Segmente |
| `is_quote` | `bool` | Aus Segment-Feld — Zitat-Kennzeichnung |
| `actors` | `list[str]` | Normformen der erkannten Entitäten |
| `causal_theme` | `list` | Immer `[]` — reserviert, noch nicht befüllt |

### project_meta.json

Liegt neben `data.json` in `exploration/` und wird von der Viz-App als
Ergänzung zu `data.json` geladen:

```json
{
  "title":    "BER Chronik",
  "doc_type": "presseartikel",
  "taxonomy": [ {"id": "…", "label": "…", "color": "#…"} ],
  "entities": [ {"normalform": "…", "type": "…"} ]
}
```

`year_min` und `year_max` stehen nicht in `data.json` sondern werden von
`export_exploration.py` direkt in `config.json` auf Projektebene zurückgeschrieben
und von `GET /api/projects/{id}` geliefert.
