# Datenmodell

Stand: 2026-08-17 | Branch: `datenmodell`

Vier Teile: was die Pipeline heute schreibt (1), wie die SQLite-Struktur aussehen
soll (2), welches Skript welche Spalte füllen würde (3), und was in beide
Richtungen fehlt (4).

---

## 1. IST-ZUSTAND

Nur Pipeline-Skripte aus `src/generalized/`. Pfade relativ zu
`data/projects/{projekt}/`. `{doc}` = Dokument-ID.

| Skript | Datei | Felder |
|---|---|---|
| `parse_document.py` (buchnotizen) | `documents/{doc}/segments.json` | `segment_id`, `level`, `type`, `source`, `text`, `page`, `doc_type` |
| `parse_document.py` (presseartikel) | `documents/{doc}/segments.json` | `segment_id`, `type`, `text`, `source`, `source_date`, `is_quote`, `page`, `ingest_source`, `doc_type` |
| `parse_document.py` | `documents/{doc}/config.json` | `doc_type`, `original_filename`, `ingested_at` |
| `ingest_obsidian.py` | `documents/{doc}/segments.json` | `segment_id`, `type`, `source`, `text`, `page`, `doc_type`, `date`, `url`, `author`, `abstract`, `ingest_source`, `obsidian_path` |
| `ingest_obsidian.py` | `documents/{doc}/obsidian_checkpoint.json` | verarbeitete Dateipfade |
| `ingest_obsidian.py` | `config.json` | `obsidian.dropbox_folder`, `obsidian.doc_type`, `obsidian.tokens`, `doc_id` |
| `detect_anchors.py` | `documents/{doc}/anchors.json` | alle Felder aus `segments.json` **plus** `anchors[]`, `time_from`, `time_to`, `precision`; bei presseartikel zusätzlich `date_raw` |
| ↳ `anchors[]`-Element | | `type` (`exact`\|`decade`\|`event`), `value`, `span`, `source` (`heading`\|`date`, nur wenn geerbt) |
| `interpolate_anchors.py` | `documents/{doc}/anchors_interpolated.json` | dieselben Felder; `time_from`, `time_to`, `precision` überschrieben (`interpolated`\|`manual`). Bei presseartikel unveränderte Kopie |
| ↳ liest `overrides.json` | | `segment_id`, `action` (`set_anchor`\|`undatable`), `time_from`, `time_to`, `text` |
| `propose_taxonomy_pipeline.py` / `propose_taxonomy.py` | `config.json["taxonomy"]` | `name`, `description`, `keywords[]` |
| `classify_segments.py` | `documents/{doc}/classified.json` | alle Felder aus `segments.json` **plus** `category`, `confidence` |
| `classify_segments.py` (`--method bge`) | `documents/{doc}/bge_embeddings.npy` | Embedding-Cache, kein Schema |
| `match_entities.py` | `documents/{doc}/classified.json` (in-place) | **plus** `actors[]` (Liste von Normalformen) |
| `extract_entities_v2.py` | `documents/{doc}/entities_proposal.json` | `normalform`, `typ`, `aliases[]`, `score` (GLiNER) |
| `extract_entities_v2.py` | `config.json["entities"]` | dieselben Felder, kanonisch (D-P4) |
| `export_preview.py` | `documents/{doc}/preview.html` | HTML, kein Schema |
| `export_exploration.py` | `exploration/data.json` | `generated`, `count`, `entries[]` |
| ↳ `entries[]`-Element | | `id`, `doc_anchor`, `year`, `date_raw`, `date_js`, `date_precision`, `text`, `event_type`, `confidence`, `source_name`, `source_date`, `url`, `is_quote`, `actors[]`, `causal_theme[]` |
| `export_exploration.py` | `exploration/entities_seed.csv` | `alias`, `normalform`, `typ` |
| `export_exploration.py` | `exploration/project_meta.json` | `title`, `doc_type`, `taxonomy`, `entity_types`, `color_map`, `node_color_map`, `year_min`, `year_max` |
| `export_exploration.py` | `config.json` (Rückschreiben) | `year_min`, `year_max` (aus den Einträgen berechnet) |
| `generate_entity_summaries.py` | `exploration/entities_summary.json` | `{normalform: {summary, paragraph_ids[], count}}` |
| `precompute_network.js` | `exploration/network_layout.json` | Knoten-/Kantenkoordinaten |
| `db.py` | `data/projects.db` → `projects` | `id`, `title`, `doc_type`, `created_at`, `status`, `token`, `is_public`, `owner_token` |
| `db.py` | `data/projects.db` → `documents` | `doc_id`, `project_id`, `ingested_at`, `doc_type`, `ingest_source`, `original_filename` |

Nicht von Pipeline-Skripten geschrieben, aber gelesen: `config.json["events"]`
(`name`, `year_from`, `year_to`, `id`, `color`), `entities_rejected.json`
(`normalform`), `invites.json` (`{token: {name, org}}`).

---

## 2. SCHEMA

```sql
PRAGMA foreign_keys = ON;

-- ── projekt ───────────────────────────────────────────────────────────────────
CREATE TABLE projekt (
    id          TEXT    NOT NULL PRIMARY KEY,
    titel       TEXT    NOT NULL DEFAULT '',
    quellentyp  TEXT    NOT NULL DEFAULT '',   -- buchnotizen | presseartikel
    angelegt_am TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'aktiv',
    jahr_von    INTEGER,
    jahr_bis    INTEGER,
    oeffentlich INTEGER NOT NULL DEFAULT 0
);

-- ── zugang ────────────────────────────────────────────────────────────────────
CREATE TABLE zugang (
    id          INTEGER NOT NULL PRIMARY KEY,
    projekt_id  TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    token       TEXT    NOT NULL UNIQUE,
    rolle       TEXT    NOT NULL DEFAULT 'leser',  -- eigentuemer | leser
    name        TEXT    NOT NULL DEFAULT '',
    organisation TEXT   NOT NULL DEFAULT '',
    angelegt_am TEXT    NOT NULL,
    laeuft_ab_am TEXT
);

-- ── quelle ────────────────────────────────────────────────────────────────────
-- Ein eingelesenes Dokument: DOCX-Datei oder Obsidian-Ordnerlauf.
CREATE TABLE quelle (
    id            TEXT NOT NULL PRIMARY KEY,
    projekt_id    TEXT NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    quellentyp    TEXT NOT NULL DEFAULT '',   -- buchnotizen | presseartikel
    herkunft      TEXT NOT NULL DEFAULT '',   -- docx | obsidian
    dateiname     TEXT,
    eingelesen_am TEXT NOT NULL DEFAULT ''
);

-- ── kategorie ─────────────────────────────────────────────────────────────────
CREATE TABLE kategorie (
    id          INTEGER NOT NULL PRIMARY KEY,
    projekt_id  TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    beschreibung TEXT   NOT NULL DEFAULT '',
    schlagworte TEXT    NOT NULL DEFAULT '',  -- kommasepariert
    position    INTEGER NOT NULL DEFAULT 0,   -- bestimmt die Farbzuweisung
    UNIQUE (projekt_id, name)
);

-- ── einheit ───────────────────────────────────────────────────────────────────
-- Ein Absatz (buchnotizen), ein Chronikeintrag (Presse-DOCX), ein Artikel (Obsidian).
CREATE TABLE einheit (
    id              INTEGER NOT NULL PRIMARY KEY,
    quelle_id       TEXT    NOT NULL REFERENCES quelle(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,          -- Reihenfolge im Dokument, ab 1
    kennung         TEXT    NOT NULL,          -- s0001 — stabile Referenz nach außen
    typ             TEXT    NOT NULL,          -- content | bibliography | meta | heading
    text            TEXT    NOT NULL,
    ebene           INTEGER,                   -- 1|2|3, nur buchnotizen
    seite           INTEGER,
    publikation     TEXT,                      -- Zeitungskürzel oder Buchtitel
    publikationsdatum TEXT,                    -- Rohform aus der Quellennotation
    url             TEXT,
    autor           TEXT,
    kurzfassung     TEXT,
    ist_zitat       INTEGER NOT NULL DEFAULT 0,
    kategorie_id    INTEGER REFERENCES kategorie(id) ON DELETE SET NULL,
    konfidenz       TEXT,                      -- high | medium | low
    jahr_von        INTEGER,
    jahr_bis        INTEGER,
    datum           TEXT,                      -- ISO YYYY-MM-DD, wenn tagesgenau
    praezision      TEXT,                      -- exact | heading | event | decade
                                               -- | interpolated | manual | NULL
    UNIQUE (quelle_id, kennung),
    UNIQUE (quelle_id, position)
);

-- ── anker ─────────────────────────────────────────────────────────────────────
-- Rohbefund der Datierung. Mehrere pro Einheit möglich; einheit.jahr_von/jahr_bis
-- ist das daraus abgeleitete Ergebnis.
CREATE TABLE anker (
    id         INTEGER NOT NULL PRIMARY KEY,
    einheit_id INTEGER NOT NULL REFERENCES einheit(id) ON DELETE CASCADE,
    jahr       INTEGER,                        -- NULL bei Jahrzehnt-Ankern
    herkunft   TEXT    NOT NULL,               -- text | ueberschrift | frontmatter
                                               -- | ereignis | jahrzehnt | manuell
    fundstelle TEXT    NOT NULL DEFAULT ''     -- der gematchte Textausschnitt
);

-- ── akteur ────────────────────────────────────────────────────────────────────
CREATE TABLE akteur (
    id          INTEGER NOT NULL PRIMARY KEY,
    projekt_id  TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    normalform  TEXT    NOT NULL,
    typ         TEXT    NOT NULL DEFAULT 'Konzept',  -- Person | Organisation | Ort | …
    status      TEXT    NOT NULL DEFAULT 'bestaetigt', -- bestaetigt | abgelehnt
    UNIQUE (projekt_id, normalform)
);

CREATE TABLE akteur_alias (
    id        INTEGER NOT NULL PRIMARY KEY,
    akteur_id INTEGER NOT NULL REFERENCES akteur(id) ON DELETE CASCADE,
    alias     TEXT    NOT NULL,
    UNIQUE (akteur_id, alias)
);

-- ── periode ───────────────────────────────────────────────────────────────────
CREATE TABLE periode (
    id         INTEGER NOT NULL PRIMARY KEY,
    projekt_id TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    name       TEXT    NOT NULL,
    jahr_von   INTEGER NOT NULL,
    jahr_bis   INTEGER NOT NULL,
    farbe      TEXT
);

-- ── einheit_akteur ────────────────────────────────────────────────────────────
CREATE TABLE einheit_akteur (
    einheit_id INTEGER NOT NULL REFERENCES einheit(id) ON DELETE CASCADE,
    akteur_id  INTEGER NOT NULL REFERENCES akteur(id) ON DELETE CASCADE,
    PRIMARY KEY (einheit_id, akteur_id)
);

-- ── Indizes ───────────────────────────────────────────────────────────────────
CREATE INDEX idx_einheit_quelle_pos ON einheit (quelle_id, position);
CREATE INDEX idx_einheit_jahr       ON einheit (jahr_von);
CREATE INDEX idx_einheit_kategorie  ON einheit (kategorie_id);
CREATE INDEX idx_anker_einheit      ON anker (einheit_id);
CREATE INDEX idx_ea_akteur          ON einheit_akteur (akteur_id);
```

---

## 3. ZUORDNUNG

Je Spalte: welches Skript sie füllt, und woher der Wert heute stammt.

### `projekt`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `id` | `dev_server.py` (`POST /api/projects`, `/ingest/upload`) | Projektname, slugifiziert |
| `titel` | `dev_server.py` (`/ingest/save_config`) | `config.json["title"]` |
| `quellentyp` | `dev_server.py` (`/ingest/save_config`) | `config.json["doc_type"]`, aus Wizard-Schritt 1 oder 2 |
| `angelegt_am` | `db.py` `create_project` | `projects.created_at` |
| `status` | `db.py` | `projects.status` |
| `jahr_von` / `jahr_bis` | `export_exploration.py` | `min`/`max` über alle `entries[].year`; vorher LLM-Schätzung aus `/ingest/analyze` |
| `oeffentlich` | `dev_server.py` | `projects.is_public` |

### `zugang`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `token` | `db.py` `_fresh_token` | `secrets.token_urlsafe(32)`, `projects.token` |
| `projekt_id` | `db.py` | `projects.id` |
| `rolle` | — | heute implizit: `projects.owner_token` == Invite-Token → Eigentümer |
| `name`, `organisation` | `invite_auth.py` | `invites.json` `{token: {name, org}}` |
| `angelegt_am` | `db.py` | `projects.created_at` |
| `laeuft_ab_am` | — | heute berechnet in `db.token_valid`: `created_at + 30 Tage` |

### `quelle`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `id` | `dev_server.py` / `ingest_obsidian.py` | `uuid4().hex[:8]`, bzw. `"main"` bei Altprojekten |
| `projekt_id` | `db.py` `upsert_document` | `documents.project_id` |
| `quellentyp` | `parse_document.py` | `--doc-type` bzw. `documents/{doc}/config.json["doc_type"]` |
| `herkunft` | `parse_document.py` / `ingest_obsidian.py` | Segmentfeld `ingest_source` (`docx` / `obsidian`) |
| `dateiname` | `parse_document.py` | `original_filename` aus Doc-Config; bei Obsidian der Dropbox-Ordner |
| `eingelesen_am` | `parse_document.py` / `ingest_obsidian.py` | `ingested_at`, `datetime.now()` beim Parsen |

### `einheit`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `text` | `parse_document.py` | DOCX-Absatz, Seitenzahl abgeschnitten (`extract_page`) |
| | `ingest_obsidian.py` | Markdown-Body nach dem Frontmatter |
| `position` | — | **kein Erzeuger.** Heute implizit: `seg_id`-Zähler in `segment_id` (`s0001`) und Array-Reihenfolge → siehe 4 |
| `kennung` | `parse_document.py` / `ingest_obsidian.py` | `f"s{seg_id:04d}"` |
| `quelle_id` | `export_exploration.py` | dort als Präfix `{doc_id}-{segment_id}` gebaut |
| `typ` | `parse_document.py` | buchnotizen: `is_bibliography()` → `bibliography`/`content`, Organizer-H1 → `meta`. presseartikel: `_YEAR_HEADING` → `heading`, sonst `content` |
| | `ingest_obsidian.py` | immer `content` |
| `ebene` | `parse_document.py` | 1 = Organizer-H1, 2 = unter Organizer-H1, 3 = unter Buchquelle |
| `seite` | `parse_document.py` | `PAGE_NR`-Regex, 1–3 Ziffern am Absatzende |
| `publikation` | `parse_document.py` (presseartikel) | `SOURCE_RE` auf der Quellennotation → `source`, z.B. `"BZ"` |
| | `parse_document.py` (buchnotizen) | zuletzt gesehene Heading-1/2-Zeile → `source` (Buchtitel, **nicht** Publikation) |
| | `ingest_obsidian.py` | Frontmatter `title` → `source` (Artikeltitel, **nicht** Publikation) |
| `publikationsdatum` | `parse_document.py` (presseartikel) | `SOURCE_RE`-Gruppe 2 → `source_date`, Rohform `"01.01.1989"` |
| `url` | `ingest_obsidian.py` | Frontmatter `source` |
| `autor` | `ingest_obsidian.py` | Frontmatter `author`, `[[…]]` bereinigt |
| `kurzfassung` | `ingest_obsidian.py` | Frontmatter `description` → `abstract` |
| `ist_zitat` | `parse_document.py` (presseartikel) | erstes Zeichen ist ein Anführungszeichen |
| `kategorie_id` | `classify_segments.py` | LLM-Antwort oder BGE-Cosine-Argmax, über `normalize_category` auf die Taxonomie normalisiert → `category` |
| `konfidenz` | `classify_segments.py` | LLM-Feld `confidence`; BGE: Schwellwerte 0.5 / 0.35 auf der Cosine-Ähnlichkeit |
| `jahr_von` / `jahr_bis` | `detect_anchors.py` | `min`/`max` der `exact`-Anker, sonst `event`-Anker, sonst geerbtes Überschriftsjahr → `time_from`/`time_to` |
| | `interpolate_anchors.py` | berechnet: Vorgänger-/Nachfolgeranker derselben `source`, sonst Vorwärtserben |
| `datum` | `ingest_obsidian.py` | Frontmatter `published`, Fallback `created` → `date` |
| | `interpolate_anchors.py` | **liefert kein Tagesdatum** — nur Jahre → siehe 4 |
| `praezision` | `detect_anchors.py` | `exact` / `heading` / `event` / `decade` / `NULL` |
| | `interpolate_anchors.py` | `interpolated`, bzw. `manual` aus `overrides.json` |

### `anker`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `einheit_id` | `detect_anchors.py` | Anker hängen am Segment, `anchors[]` |
| `jahr` | `detect_anchors.py` | `_BARE_YEAR`-Regex (1600–2029) im bereinigten Text; bei `event` das hinterlegte Jahr aus `_EVENTS`; `NULL` bei `decade` |
| `herkunft` = `text` | `detect_anchors.py` | `anchors[].type == "exact"` ohne `source`-Feld |
| `herkunft` = `ueberschrift` | `detect_anchors.py` | `anchors[].source == "heading"` — reines Jahres-Heading im DOCX |
| `herkunft` = `frontmatter` | `detect_anchors.py` | `anchors[].source == "date"` — Obsidian-`date`-Feld |
| `herkunft` = `ereignis` | `detect_anchors.py` | `anchors[].type == "event"`, Treffer in `_EVENTS` |
| `herkunft` = `jahrzehnt` | `detect_anchors.py` | `anchors[].type == "decade"`, Treffer in `_DECADE_RE` |
| `herkunft` = `manuell` | `interpolate_anchors.py` | `overrides.json`, `action: "set_anchor"` |
| `fundstelle` | `detect_anchors.py` | `anchors[].span` — gematchter Ausschnitt bzw. Ereignis-Label |

### `kategorie`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `name` | `propose_taxonomy_pipeline.py` | LLM-Label je Cluster (`_parse_taxonomy`), danach im Taxonomy-Editor überschreibbar |
| `beschreibung` | `propose_taxonomy_pipeline.py` | erste Nicht-Keyword-Zeile der LLM-Antwort |
| `schlagworte` | `propose_taxonomy_pipeline.py` | `keywords:`-Zeile, auf 3 gekürzt |
| `projekt_id` | `/taxonomy/save` | schreibt nach `config.json["taxonomy"]` |
| `position` | — | heute implizit: Listenindex in `config.json["taxonomy"]`; `export_exploration.build_meta` leitet daraus `color_map` ab |

### `akteur` / `akteur_alias`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `normalform` | `extract_entities_v2.py` → `entity_gliner.py` | GLiNER-Span, per Embedding-Clustering zur längsten Variante zusammengefasst |
| `typ` | `entity_gliner.py` | häufigstes GLiNER-Label im Cluster (`Person`, `Organisation`, `Ort`, …) |
| `status` | — | heute getrennte Datei `entities_rejected.json` → siehe 4 |
| `projekt_id` | `_mirror_to_config` | `config.json["entities"]` (D-P4) |
| `alias` | `entity_gliner.py` | übrige Cluster-Mitglieder plus deren Aliase; ergänzbar im Entity-Editor |

### `periode`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `name` | `/ingest/analyze` (LLM, nur buchnotizen) | LLM-Analyse einer Stichprobe von 30 Absätzen → `config.json["events"]` |
| `jahr_von` / `jahr_bis` | `/ingest/analyze` | `year_from` / `year_to` derselben LLM-Antwort |
| `farbe` | Wizard Schritt 5 | `color`, im Ereignis-Editor vergeben |
| `projekt_id` | `/ingest/save_config` | `time_config.events` |

### `einheit_akteur`

| Spalte | Skript | Herkunft heute |
|---|---|---|
| `einheit_id`, `akteur_id` | `match_entities.py` | Wortgrenz-Regex über Normalform + alle Aliase je content-Segment → `classified.json["actors"]` |

---

## 4. LÜCKEN

### 4.1 Spalten ohne Erzeuger

| Spalte | Lage heute | Gebraucht? |
|---|---|---|
| `einheit.position` | Kein Skript schreibt eine Positionsnummer. Die Reihenfolge steckt in der Array-Position in `segments.json` und im Zähler in `segment_id` (`s0001`). `interpolate_anchors.py` hängt daran: es sucht Vorgänger-/Nachfolgeranker über den Listenindex. | **Ja.** Ohne explizite Spalte ist die Interpolation an eine Dateireihenfolge gebunden, die eine Datenbank nicht garantiert. Erzeuger wäre `parse_document.py` / `ingest_obsidian.py` — der Zähler existiert bereits, er wird nur nicht ausgeschrieben. |
| `einheit.datum` | Nur der Obsidian-Pfad liefert ein Tagesdatum (`date` aus dem Frontmatter). Presse-DOCX hat mit `source_date` zwar `"01.01.1989"` im Text, parst es aber nie zu einem Datum — `detect_anchors` liest dort nur das Jahres-Heading. Buchnotizen haben nie eines. | **Ja**, aber nur für die zwei Pressetypen. Die Timeline schaltet unterhalb weniger Jahre auf Monats- und Tages-Bins; für Presse-DOCX fehlt dafür heute die Auflösung, obwohl das Datum im Text steht. `parse_document.parse_presseartikel` müsste `source_date` normalisieren. |
| `einheit.jahr_bis` bei `decade` | `detect_anchors` erkennt Jahrzehnt-Anker, setzt aber `time_from = time_to = None` und nur `precision = "decade"`. Der Jahrzehntwert selbst wird verworfen. | **Ja.** Ein „1890er"-Anker weiß, dass er 1890–1899 meint; heute landet das Segment bei den undatierten. Für Literaturexzerpte ist das der Regelfall. |
| `akteur.status` | Ablehnungen liegen in `entities_rejected.json` neben den Entities, nicht bei ihnen. `extract_entities_v2` liest die Datei beim nächsten Lauf als Filter. | **Ja.** Zwei Speicherorte für eine Eigenschaft desselben Objekts; als Spalte entfällt der Abgleich. |
| `kategorie.position` | Nur Listenindex in `config.json["taxonomy"]`. `build_meta` leitet daraus die Farbe ab (`CAT_PALETTE[i % 10]`). | **Ja**, sonst wechseln Kategoriefarben bei jeder Umsortierung. |
| `zugang.rolle` | Implizit über `projects.owner_token`. | **Ja**, wenn mehr als Eigentümer/Nicht-Eigentümer unterschieden werden soll. Sonst genügt ein Flag. |
| `zugang.laeuft_ab_am` | Nirgends gespeichert, `db.token_valid` rechnet `created_at + 30 Tage` bei jeder Prüfung. | Nein. Die Ableitung reicht, solange die TTL für alle gleich ist. Spalte nur, falls Tokens einzeln verlängerbar werden sollen. |
| `periode.farbe` | Kommt aus dem Wizard, nicht aus der Pipeline. In `baseline_damaskus_docx/config.json` fehlt sie, in `damaskus/config.json` ist sie gesetzt. | Nein, kosmetisch. Nullable lassen. |

### 4.2 Felder ohne Spalte

| Feld | Wo heute | Bewertung |
|---|---|---|
| `anchors[].value` / `.span` / `.type` / `.source` | `anchors.json` | Vollständig abgebildet: `anker.jahr`, `.fundstelle`, `.herkunft` (`type` und `source` fallen darin zusammen). |
| `level` | `segments.json`, nur buchnotizen | **Gebraucht** → `einheit.ebene`. Einziger Träger der Buch-Hierarchie; `typ` allein unterscheidet Literaturliste (Ebene 2) und Buchabschnitt (Ebene 3) nicht. |
| `doc_type` je Segment | `segments.json`, jedes Segment | Redundanz. Steht bereits an `quelle.quellentyp`; pro Segment wiederholt, weil die Skripte einzeln aufgerufen werden. Keine Spalte. |
| `is_geicke` | nur `ber/exploration/data.json` und `ber/.../anchors.json` | Altlast. Das heutige `parse_document.py` schreibt das Feld nicht mehr; es überlebt in Altdaten und wird von `**seg` durch die Pipeline durchgereicht. Keine Spalte. |
| `causal_theme` | `data.json`, immer `[]` | Toter Platzhalter — `build_entries` setzt es hart auf `[]`, kein Skript füllt es je. Keine Spalte. |
| `date_raw` | `anchors.json` (presse), `data.json` | Ableitung: `date_raw or date or str(time_from)`. Deckungsgleich mit `einheit.datum` bzw. `publikationsdatum`. Keine eigene Spalte. |
| `date_js` | `data.json` | Reine Darstellungsform (`"1989"` → `"1989-01-01"`), in `build_entries` erzeugt. Gehört in den Export, nicht in die Tabelle. |
| `date_precision` | `data.json` | Auf drei Werte reduziertes `precision` (`PREC_MAP`). Die Tabelle behält die feinere Fassung in `einheit.praezision`; der Export mappt weiter. |
| `confidence` → `"med"` | `data.json` | Nur Umbenennung von `"medium"` im Export. Spalte behält `medium`. |
| `page` | `segments.json` | **Gebraucht** → `einheit.seite`. Bei buchnotizen der Beleg auf die Buchseite; bei beiden Pressetypen konstant `null`. |
| `is_quote` | `segments.json` (Presse-DOCX) | **Gebraucht** → `einheit.ist_zitat`. Unterscheidet Zitat vom Referat, wird in der Viz angezeigt. |
| `abstract`, `author`, `url` | `segments.json` (Obsidian) | **Gebraucht** → `kurzfassung`, `autor`, `url`. Für andere Quellentypen leer. |
| `obsidian_path` | `segments.json` (Obsidian) | Beiwerk für die Pipeline, aber der einzige Rückweg zur Quelldatei und der Schlüssel des Sync-Checkpoints. Falls Wiedereinlesen ohne Duplikate weiter funktionieren soll: als `einheit.quellpfad` aufnehmen. Sonst entbehrlich. |
| `entities[].score` | `config.json["entities"]` (GLiNER) | Beiwerk. Konfidenz des Extraktors, nach Bestätigung durch den Historiker bedeutungslos. Keine Spalte. |
| `entities[].text` | Altdaten (`ber/config.json`) | Vorläufer von `normalform`. Keine Spalte. |
| `entities_summary.json` (`summary`, `paragraph_ids`, `count`) | `exploration/` | Generiertes Artefakt, aus `einheit_akteur` jederzeit neu berechenbar. `count` und `paragraph_ids` sind Aggregate. Höchstens `akteur.zusammenfassung` als Cache. |
| `color_map`, `node_color_map`, `entity_types` | `project_meta.json` | Aus `kategorie.position` und `akteur.typ` abgeleitet. Kein Speicherbedarf. |
| `generated`, `count` | `data.json` | Export-Metadaten. Keine Spalte. |
| `bge_embeddings.npy`, `_v2_checkpoint.json`, `obsidian_checkpoint.json` | `documents/{doc}/` | Laufzeit-Caches. Bleiben Dateien. |
| `obsidian.tokens` | `config.json` | Dropbox-Zugangsdaten, liegen im Klartext in der Projekt-Config. Gehört nicht in `projekt`, sondern in einen eigenen, gesondert behandelten Speicher. |

### 4.3 Zwei Kollisionen, die beim Übertragen auffallen

**`source` trägt drei verschiedene Dinge.** Bei buchnotizen den Buchtitel, bei
Presse-DOCX das Zeitungskürzel, bei Obsidian den Artikeltitel. `interpolate_anchors`
gruppiert darüber die Interpolationsblöcke, `export_exploration` schreibt es als
`source_name` in die Viz, und `group_by_article` bildet daraus den Gruppierungs-
schlüssel. Das Schema oben trennt das nicht auf — `einheit.publikation` erbt die
Mehrdeutigkeit. Sauber wäre entweder eine Spalte `einheit.gruppe` für den
Interpolationsblock neben `publikation`, oder ein Verweis auf eine eigene Werk-Tabelle.

**`classified.json` enthält keine Zeitangaben.** `classify_segments.py` liest
`segments.json`, nicht `anchors_interpolated.json`. Die Datierung und die
Klassifikation laufen also auf zwei getrennten Kopien derselben Segmente, die
`export_exploration.py` erst am Ende über `segment_id` wieder zusammenführt.
In der Tabelle `einheit` fällt das zusammen — was den Merge-Schritt und die
Präfix-Logik `{doc_id}-{segment_id}` überflüssig macht.
