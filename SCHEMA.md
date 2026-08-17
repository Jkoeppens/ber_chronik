# Datenbankschema

Stand nach der Durchsprache. Ersetzt Abschnitt 2 von `DATENMODELL.md`.

Acht Tabellen. Grundsätze, die in allen gelten:

- **Ein Sachverhalt, eine Stelle.** Kein Wert steht zweimal.
- **Keine Darstellungsdaten.** Farben, Anzeigeformate und Sortierungen für die
  Oberfläche gehören nicht hierher.
- **Fremdschlüssel wirken.** `PRAGMA foreign_keys = ON` bei jeder Verbindung —
  heute ist er deklariert und ausgeschaltet, und das Ergebnis sind elf
  Dokumentzeilen ohne Projekt.

---

## Schema

```sql
PRAGMA foreign_keys = ON;

-- ── projekt ───────────────────────────────────────────────────────────────────
CREATE TABLE projekt (
    id              TEXT    NOT NULL PRIMARY KEY,
    titel           TEXT    NOT NULL DEFAULT '',
    eigentuemer_id  INTEGER NOT NULL REFERENCES zugang(id),
    angelegt_am     TEXT    NOT NULL,
    jahr_von        INTEGER,
    jahr_bis        INTEGER,
    oeffentlich     INTEGER NOT NULL DEFAULT 0,
    dropbox_ordner  TEXT,
    dropbox_token   TEXT
);

-- ── zugang ────────────────────────────────────────────────────────────────────
CREATE TABLE zugang (
    id           INTEGER NOT NULL PRIMARY KEY,
    token        TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL DEFAULT '',
    organisation TEXT    NOT NULL DEFAULT '',
    rolle        TEXT    NOT NULL DEFAULT 'nutzer',  -- verwalter | nutzer
    angelegt_am  TEXT    NOT NULL
);

-- Zusätzliche Zugänge. Der Eigentümer steht an projekt.eigentuemer_id.
CREATE TABLE projekt_zugang (
    projekt_id TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    zugang_id  INTEGER NOT NULL REFERENCES zugang(id)  ON DELETE CASCADE,
    PRIMARY KEY (projekt_id, zugang_id)
);

-- ── quelle ────────────────────────────────────────────────────────────────────
CREATE TABLE quelle (
    id            TEXT NOT NULL PRIMARY KEY,
    projekt_id    TEXT NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    quellformat   TEXT NOT NULL,   -- literaturexzerpt | presseexzerpt | pressesammlung
    pfad          TEXT,            -- DOCX-Datei oder Dropbox-Ordner
    eingelesen_am TEXT NOT NULL
);

-- ── einheit ───────────────────────────────────────────────────────────────────
CREATE TABLE einheit (
    id                 INTEGER NOT NULL PRIMARY KEY,
    quelle_id          TEXT    NOT NULL REFERENCES quelle(id) ON DELETE CASCADE,
    position           INTEGER NOT NULL,
    typ                TEXT    NOT NULL,   -- content | heading | bibliography | meta
    text               TEXT    NOT NULL,

    -- Herkunft im Material
    publikation        TEXT,               -- Zeitungskürzel, Buchtitel, Artikeltitel
    chronologie_gruppe TEXT,               -- worüber interpoliert wird
    publikationsdatum  TEXT,               -- Rohform aus der Quellennotation
    quellpfad          TEXT,               -- einzelne Clip-Datei, nur pressesammlung
    url                TEXT,
    autor              TEXT,
    kurzfassung        TEXT,
    seite              INTEGER,
    ebene              INTEGER,            -- 1|2|3, nur literaturexzerpt
    ist_zitat          INTEGER,            -- NULL = nicht erhoben, 0 = geprüft

    -- Ergebnis der Datierung
    datum              TEXT,               -- "1989" | "1989-06" | "1989-06-15"
    jahr_von           INTEGER,            -- nur bei echten Spannen
    jahr_bis           INTEGER,
    praezision         TEXT,               -- exakt | ueberschrift | ereignis
                                           -- | jahrzehnt | interpoliert | manuell

    -- Ergebnis der Klassifikation
    kategorie_id       INTEGER REFERENCES kategorie(id) ON DELETE SET NULL,
    konfidenz          TEXT,               -- high | medium | low

    UNIQUE (quelle_id, position)
);

-- ── anker ─────────────────────────────────────────────────────────────────────
CREATE TABLE anker (
    id         INTEGER NOT NULL PRIMARY KEY,
    einheit_id INTEGER NOT NULL REFERENCES einheit(id) ON DELETE CASCADE,
    jahr       INTEGER,
    herkunft   TEXT    NOT NULL,   -- text | ueberschrift | frontmatter
                                   -- | quellennotation | ereignis | jahrzehnt | manuell
    fundstelle TEXT    NOT NULL DEFAULT ''
);

-- ── kategorie ─────────────────────────────────────────────────────────────────
CREATE TABLE kategorie (
    id           INTEGER NOT NULL PRIMARY KEY,
    projekt_id   TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    beschreibung TEXT    NOT NULL DEFAULT '',
    schlagworte  TEXT    NOT NULL DEFAULT '',
    UNIQUE (projekt_id, name)
);

-- ── akteur ────────────────────────────────────────────────────────────────────
CREATE TABLE akteur (
    id              INTEGER NOT NULL PRIMARY KEY,
    projekt_id      TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    normalform      TEXT    NOT NULL,
    typ             TEXT,
    status          TEXT    NOT NULL,
                            -- vorgeschlagen | bestaetigt | abgelehnt
                            -- kein Vorgabewert: der Erzeuger muss sich äußern
    zusammenfassung TEXT,
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
    jahr_von   INTEGER,
    jahr_bis   INTEGER
);

-- ── einheit_akteur ────────────────────────────────────────────────────────────
CREATE TABLE einheit_akteur (
    einheit_id INTEGER NOT NULL REFERENCES einheit(id) ON DELETE CASCADE,
    akteur_id  INTEGER NOT NULL REFERENCES akteur(id)  ON DELETE CASCADE,
    PRIMARY KEY (einheit_id, akteur_id)
);

-- ── lauf ──────────────────────────────────────────────────────────────────────
-- Ein Verarbeitungsschritt, der gelaufen ist. Was womit erzeugt wurde.
CREATE TABLE lauf (
    id          INTEGER NOT NULL PRIMARY KEY,
    projekt_id  TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    schritt     TEXT    NOT NULL,   -- ingest | datierung | klassifikation | …
    begonnen_am TEXT    NOT NULL,
    beendet_am  TEXT,               -- NULL, solange der Lauf läuft
    parameter   TEXT,               -- JSON: womit er aufgerufen wurde
    status      TEXT    NOT NULL    -- laeuft | erfolg | fehler
);

-- ── Indizes ───────────────────────────────────────────────────────────────────
CREATE INDEX idx_einheit_quelle_pos ON einheit (quelle_id, position);
CREATE INDEX idx_einheit_jahr       ON einheit (jahr_von);
CREATE INDEX idx_einheit_kategorie  ON einheit (kategorie_id);
CREATE INDEX idx_anker_einheit      ON anker (einheit_id);
CREATE INDEX idx_ea_akteur          ON einheit_akteur (akteur_id);
CREATE INDEX idx_lauf_projekt       ON lauf (projekt_id, begonnen_am);
```

---

## Was sich je Tabelle geändert hat

### `projekt`

**Entfernt:** `quellentyp` — gehört zur Quelle. Ein Projekt darf Exzerpte und
Obsidian-Sammlungen gleichzeitig tragen; ein Typ auf Projektebene widerspricht dem
und ist einer der vier heutigen Ablageorte von `doc_type`.

**Entfernt:** `status` — wird heute geschrieben und von niemandem gelesen.

**Ergänzt:** `dropbox_ordner`, `dropbox_token` — die Obsidian-Anbindung hängt am
Projekt, nicht an einer globalen Datei. Heute liegen alle Zugangsdaten in einer
einzigen `dropbox_tokens.json` für die ganze Installation; beim zweiten Nutzer
überschreiben sie sich gegenseitig.

**Ergänzt:** `eigentuemer_id` — jedes Projekt gehört genau einem Zugang, und die
Datenbank erzwingt das. Als Flag in `projekt_zugang` war Eigentum optional: eine
Einfügung, die es vergisst, hätte lautlos ein herrenloses Projekt erzeugt.

### `zugang`

**Getrennt vom Projekt.** Ein Zugang gehörte im Entwurf zu genau einem Projekt.
Tatsächlich ist ein Einladungscode eine Person, die mehrere Projekte haben kann —
also eine eigene Tabelle plus `projekt_zugang` für die Zuordnung.

`projekt_zugang` hält nur noch die *zusätzlichen* Zugänge und trägt kein Flag mehr.
Wer ein Projekt besitzt, steht an `projekt.eigentuemer_id`.

**Entfernt:** `laeuft_ab_am` — Token laufen nicht mehr ab.

**Behalten:** `rolle` mit zwei Stufen. `verwalter` steht über allen Projekten,
`nutzer` sieht nur die eigenen und öffentlichen.

### `quelle`

**Zusammengelegt:** `quellentyp` und `herkunft` werden zu `quellformat` mit drei
Werten. Zwei Spalten mit je zwei Werten ergäben vier Kombinationen, von denen es nur
drei gibt — `literaturexzerpt` per Obsidian existiert nicht.

**Umbenannt:** `dateiname` → `pfad`. Bei DOCX die Datei, bei einer Sammlung der
Dropbox-Ordner.

### `einheit`

**Entfernt:** `kennung` (`s0001`) — kodierte nur die Position im Namen.
`einheit.id` ist die stabile Referenz, `position` die Reihenfolge.

**Ergänzt:** `position` — heute steckt die Reihenfolge in der Array-Position und im
Zähler in `s0001`. Eine Datenbank garantiert keine Zeilenreihenfolge; ohne diese
Spalte wäre die Interpolation zufällig. Der Zähler existiert bereits in
`parse_document`, er wird nur nicht ausgeschrieben.

**Ergänzt:** `chronologie_gruppe` — worüber die Interpolation gruppiert. Heute
geschieht das über `source`, und das bedeutet je Format etwas anderes: bei
Literaturexzerpten das exzerpierte Werk (richtig), bei einer Chronik die Zeitung
(falsch, es ist eine durchgehende Zeitachse). Das Format entscheidet beim Einlesen,
was die Gruppe ist; die Interpolation liest nur noch die Spalte.

**Ergänzt:** `quellpfad` — die einzelne Clip-Datei bei Sammlungen. Ohne sie liest
ein zweiter Sync dieselben Artikel erneut ein.

**Geändert:** die Zeitangaben. `datum` nimmt die genaueste bekannte Form auf —
`"1989"`, `"1989-06"` oder `"1989-06-15"` —, `praezision` sagt, wie sie zustande kam.
`jahr_von`/`jahr_bis` bleiben für echte Spannen: Jahrzehnte, „zwischen 1908 und 1912".

**Geändert:** `ist_zitat` ist nullable. `parse_document` erhebt das Merkmal nur bei
Presseexzerpten; der Vorgabewert `0` hätte für jedes Literaturexzerpt „geprüft, kein
Zitat" behauptet. `NULL` heißt nicht erhoben, `0` heißt geprüft.

### `anker`

**Ergänzt:** `quellennotation` als Herkunft. Die BER-Chronik trägt 577 tagesgenaue
Erscheinungsdaten in der Quellennotation, die heute geparst und nie gelesen werden.

### `kategorie`

**Entfernt:** `position` — existierte nur, um Farben abzuleiten. Farben werden in der
Oberfläche vergeben.

### `akteur`

**Ergänzt:** `status` mit drei Werten. Ablehnungen liegen heute in
`entities_rejected.json`, also getrennt von den Entitäten, auf die sie sich beziehen.
`abgelehnt` heißt dabei nicht gelöscht: die Zeile bleibt, damit der nächste
Extraktionslauf den Fehlfund überspringt.

Kein Vorgabewert. `vorgeschlagen` ist der Zustand, in dem GLiNER einen Fund ablegt,
`bestaetigt` setzt nur ein Mensch im Entity-Editor. Welcher von beiden gilt, weiß
allein der Erzeuger — die Datenbank rät nicht für ihn.

**Geändert:** `typ` ist nullable. Der Vorgabewert `Konzept` war eine Behauptung über
Funde, deren Art der Extraktor nicht bestimmen konnte.

**Ergänzt:** `zusammenfassung` — optionaler Zwischenspeicher für die
KI-Zusammenfassungen. Wird nur für wenige Akteure erzeugt, bleibt sonst leer.

### `periode`

**Entfernt:** `farbe` — Darstellung.

**Geändert:** `jahr_von` und `jahr_bis` sind nullable. Die LLM-Analyse liefert
Perioden nicht immer mit Jahreszahlen; unter `NOT NULL` müsste der Erzeuger welche
erfinden oder die Periode verwerfen.

### `einheit_akteur`

Unverändert. Zwei Spalten, eine Zeile je Nennung.

### `lauf`

**Neu.** Heute steht nirgends, womit ein Bestand erzeugt wurde: `segments.json`
trägt kein Datum, und `ingested_at` in der Doc-Config wird beim Wiederholen
überschrieben. Ein Lauf hält fest, welcher Schritt wann mit welchen Parametern
lief und wie er ausging.

`status` hat keinen Vorgabewert und drei Werte: `laeuft` wird beim Start
geschrieben, `erfolg` oder `fehler` beim Ende. `beendet_am` bleibt `NULL`,
solange der Lauf läuft — ein abgestürzter Prozess hinterlässt damit eine
erkennbar unvollständige Zeile statt gar keiner.

---

## Was ersatzlos wegfällt

| Feld | wo heute | warum |
|---|---|---|
| `is_geicke` | Altdaten | Das heutige `parse_document` schreibt es nicht mehr |
| `causal_theme` | `data.json` | Steht immer auf `[]`, kein Skript füllt es |
| `entities[].score` | `config.json` | GLiNER-Konfidenz, nach Bestätigung bedeutungslos |
| `doc_type` je Segment | `segments.json` | Steht an der Quelle, wird nur wiederholt |
| `date_js` | `data.json` | Darstellungsform, entsteht beim Export |
| `color_map`, `node_color_map` | `project_meta.json` | Darstellung |

**Bleiben Dateien:** `bge_embeddings.npy`, `_v2_checkpoint.json`,
`obsidian_checkpoint.json` — Zwischenspeicher zur Laufzeit, jederzeit wegwerfbar.

---

## Offene Punkte

**Farbzuweisung für Kategorien.** Heute leitet der Export die Farbe aus dem
Listenplatz ab, weshalb sich alle Farben verschieben, sobald eine Kategorie gelöscht
oder umsortiert wird. Die Datenbank hält keine Farben — die Oberfläche braucht also
eine Regel, die ohne Reihenfolge auskommt. Naheliegend wäre eine Ableitung aus dem
Kategorienamen: stabil, solange der Name gleich bleibt.

**Jahrzehnt-Anker.** `detect_anchors` erkennt „1890er Jahre", verwirft aber den Wert
und setzt nur `praezision = jahrzehnt`. Das Segment gilt danach als undatiert. Ein
solcher Anker weiß mehr — 1890 bis 1899. Vor einer Änderung sollte gezählt werden,
wie oft der Fall in `osmanisch` und `nahda` tatsächlich vorkommt; bei `damaskus` war
es genau einer.

**Fundstellen bei Akteuren.** `einheit_akteur` hält heute nur das Paar. Speicherte man
zusätzlich die Position im Text, entfiele die zweite Suche in `highlight.js`, die
dieselben Aliase im Browser noch einmal durchgeht. Preis: eine Zeile je Vorkommen
statt je Einheit.

**Verwalterrolle.** `zugang.rolle` unterscheidet `verwalter` und `nutzer`. Wie weit
die Verwalterrechte reichen — alle Projekte sehen, alle bearbeiten, Zugänge anlegen —
ist noch nicht festgelegt.

**`chronologie_gruppe` ist eine Vermutung.** Der Wert entsteht beim Einlesen aus der
Überschriftenformatierung des DOCX: was als Heading 1 oder 2 formatiert ist, gilt als
exzerpiertes Werk. Das ist nur so verlässlich wie die Formatierung im Ausgangsmaterial.

Beleg aus `damaskus`: von 34 Gruppen sind die größten erwartbar Werktitel
(`Hasan Kayali – Arabs and Young Turks`, 146 Einheiten), aber eine Gruppe mit 46
Einheiten heißt `Gelvin 127 (schreibt was über Haqaiq)` — eine Notiz des Historikers,
kein Werk. Die Interpolation liefe darüber als eigenen Block und würde 46 Einheiten
gegen einen Anker datieren, der keiner ist.

Die Spalte muss deshalb von Hand korrigierbar sein: der Historiker muss Gruppen
zusammenlegen, trennen und umbenennen können, ohne das DOCX zu ändern und ohne neu
einzulesen. Wo diese Korrektur im Wizard sitzt — eigener Schritt oder Teil der
Zeitkorrektur in Schritt 3 — ist offen.
