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
-- Kein jahr_von/jahr_bis: der Zeitraum eines Projekts ist MIN(jahr_von) und
-- MAX(jahr_bis) über seine Einheiten. Abgeleitet, nicht abgelegt.
CREATE TABLE projekt (
    id              TEXT    NOT NULL PRIMARY KEY,
    titel           TEXT    NOT NULL DEFAULT '',
    eigentuemer_id  INTEGER NOT NULL REFERENCES zugang(id),
    angelegt_am     TEXT    NOT NULL,
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
    praezision         TEXT,               -- Granularität:
                                           -- tag | monat | jahr | spanne | keine
    datierung_herkunft TEXT,               -- wie zustande gekommen: text
                                           -- | ueberschrift | frontmatter
                                           -- | quellennotation | ereignis
                                           -- | interpoliert | manuell
                                           -- NULL = nie datiert
    datierung_lauf_id  INTEGER REFERENCES lauf(id) ON DELETE SET NULL,

    -- Ergebnis der Klassifikation
    kategorie_id       INTEGER REFERENCES kategorie(id) ON DELETE SET NULL,
    konfidenz          TEXT,               -- high | medium | low
    kategorie_herkunft TEXT                -- automatisch | manuell
                       CHECK (kategorie_herkunft IN ('automatisch', 'manuell')),
                                           -- NULL = nie zugeordnet
    kategorie_lauf_id  INTEGER REFERENCES lauf(id) ON DELETE SET NULL,

    UNIQUE (quelle_id, position),
    -- Der Riegel gegen doppeltes Einlesen: dieselbe Clip-Datei kommt in einer
    -- Quelle genau einmal vor. NULL zählt in SQLite nicht als Dublette, DOCX
    -- ohne quellpfad bleibt also unberührt.
    UNIQUE (quelle_id, quellpfad)
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
    herkunft     TEXT    NOT NULL,   -- vorschlag | manuell
    UNIQUE (projekt_id, name)
);

-- ── akteur ────────────────────────────────────────────────────────────────────
CREATE TABLE akteur (
    id         INTEGER NOT NULL PRIMARY KEY,
    projekt_id TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    normalform TEXT    NOT NULL,
    typ        TEXT    CHECK (typ IN ('Person', 'Organisation', 'Ort', 'Konzept')),
                       -- NULL nur, wenn der Erkenner den Typ nicht bestimmen konnte
    status     TEXT    NOT NULL CHECK (status IN ('aktiv', 'abgelehnt')),
                       -- abgelehnt heißt nicht gelöscht: die Zeile bleibt, damit
                       -- der nächste Lauf den Fehlfund überspringt
    herkunft   TEXT    NOT NULL CHECK (herkunft IN ('gliner', 'manuell')),
                       -- manuell ist gegen Neuläufe geschützt
    zusammenfassung TEXT,   -- KI-Zusammenfassung; hier steht sie, nicht in
                            -- der Exportdatei. entities_summary.json ist die
                            -- Ausgabe, nicht die Wahrheit.
    UNIQUE (projekt_id, normalform)
);

CREATE TABLE akteur_alias (
    id        INTEGER NOT NULL PRIMARY KEY,
    akteur_id INTEGER NOT NULL REFERENCES akteur(id) ON DELETE CASCADE,
    alias     TEXT    NOT NULL,
    UNIQUE (akteur_id, alias)
);

-- Vom Server berechnete Verschmelzungsvorschläge. Ein Erzeugnis des Laufs,
-- kein Zustand: ein Neulauf ersetzt sie vollständig.
CREATE TABLE verschmelzungskandidat (
    id           INTEGER NOT NULL PRIMARY KEY,
    projekt_id   TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    akteur_a_id  INTEGER NOT NULL REFERENCES akteur(id) ON DELETE CASCADE,
    akteur_b_id  INTEGER NOT NULL REFERENCES akteur(id) ON DELETE CASCADE,
                          -- a < b, damit jedes Paar genau einmal vorkommt
    grund        TEXT    NOT NULL
                          CHECK (grund IN ('alias', 'schreibweise', 'aehnlichkeit')),
    mass         REAL,     -- Kosinusähnlichkeit bzw. Editierabstand; NULL bei 'alias'
    berechnet_am TEXT    NOT NULL,
    CHECK (akteur_a_id < akteur_b_id),
    UNIQUE (akteur_a_id, akteur_b_id)
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
-- Eine Zeile je Vorkommen, nicht je Einheit: start und ende zeigen auf die
-- Fundstelle im Text der Einheit (Zeichen-Offsets, ende ausschließlich).
CREATE TABLE einheit_akteur (
    id         INTEGER NOT NULL PRIMARY KEY,
    einheit_id INTEGER NOT NULL REFERENCES einheit(id) ON DELETE CASCADE,
    akteur_id  INTEGER NOT NULL REFERENCES akteur(id)  ON DELETE CASCADE,
    start      INTEGER NOT NULL,
    ende       INTEGER NOT NULL,
    UNIQUE (einheit_id, akteur_id, start)
);

-- ── anmeldung ─────────────────────────────────────────────────────────────────
-- Ein begonnener Dropbox-Anmeldevorgang. In der Datenbank und nicht im
-- Arbeitsspeicher: zwischen dem Beginn und der Rückleitung liegt ein Besuch bei
-- Dropbox, und ein Neustart in dieser Zeit ließ die Anmeldung bisher auflaufen.
CREATE TABLE anmeldung (
    csrf        TEXT NOT NULL PRIMARY KEY,  -- der state-Wert gegen Dropbox
    projekt_id  TEXT REFERENCES projekt(id) ON DELETE CASCADE,
                                            -- NULL: Anmeldung ohne Projekt
    sitzung     TEXT NOT NULL,              -- JSON, was der Fluss sich merkt
    begonnen_am TEXT NOT NULL
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
CREATE INDEX idx_ea_einheit         ON einheit_akteur (einheit_id);
CREATE INDEX idx_akteur_projekt     ON akteur (projekt_id, status);
CREATE INDEX idx_kandidat_projekt   ON verschmelzungskandidat (projekt_id);
CREATE INDEX idx_lauf_projekt       ON lauf (projekt_id, begonnen_am);
```

---

## Was sich je Tabelle geändert hat

### `projekt`

**Entfernt:** `quellentyp` — gehört zur Quelle. Ein Projekt darf Exzerpte und
Obsidian-Sammlungen gleichzeitig tragen; ein Typ auf Projektebene widerspricht dem
und ist einer der vier heutigen Ablageorte von `doc_type`.

**Entfernt:** `status` — wird heute geschrieben und von niemandem gelesen.

**Entfernt:** `jahr_von` und `jahr_bis`. Der Zeitraum ist `MIN(einheit.jahr_von)`
bis `MAX(einheit.jahr_bis)` — eine Ableitung, keine Angabe. Als gespeicherter Wert
war er die Hauptursache für unsichtbares Material: bei Literaturexzerpten schätzte
ein Sprachmodell die Spanne aus zehn Textausschnitten, der Wert landete in
`config.json`, und `d3.bin()` verwarf im Browser stillschweigend alles außerhalb.
Bei `damaskus` standen dort 1895–1918, während das Material von 1780 bis 1995
reicht: 159 von 672 Einheiten waren auf der Zeitachse nicht vorhanden — mehr als
alle undatierten zusammen.

**Ergänzt:** `dropbox_ordner`, `dropbox_token` — die Obsidian-Anbindung hängt am
Projekt. Das ist keine Änderung am Ablageort, sondern eine an der Form: heute
stehen die Zugangsdaten bereits projektweise in
`data/projects/{id}/config.json` unter `obsidian.tokens`, neun Projekte mit
sieben verschiedenen Token. Die oft genannte globale `data/dropbox_tokens.json`
existiert zwar als Datei, wird aber von keiner Zeile geschrieben und nur an
einer einzigen Stelle gelesen: `_dropbox_connected()` setzt daraus einen Haken
in der Oberfläche — für Zugangsdaten, die gar nicht benutzt werden. Sie wird
nicht übernommen.

Gespeichert wird nur der `refresh_token`. Den `access_token` legt das alte
System mit ab, obwohl er nach vier Stunden verfällt und nirgends gelesen wird:
der Client wird ausschließlich mit `oauth2_refresh_token` gebaut, das SDK holt
sich neue Zugriffstoken selbst.

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

**Ergänzt:** `quellpfad` — die einzelne Clip-Datei bei Sammlungen, und damit der
Riegel gegen doppeltes Einlesen: `UNIQUE (quelle_id, quellpfad)`.

Er hat genau eine Form, gleich woher die Datei kommt: **relativ zum
eingestellten Ordner, ohne führenden Schrägstrich**. Dropbox liefert
`path_display` als `/Dropbox_test1/x.md`, der lokale Weg `x.md`; ohne
Vereinheitlichung gälte beim Wechsel zwischen beiden jede Datei als neu. Das
alte System hat das mit einem Vergleich nur über den Dateinamen überbrückt —
das bricht, sobald zwei Unterordner eine gleichnamige Datei enthalten.

**Geändert:** die Zeitangaben. `datum` nimmt die genaueste bekannte Form auf —
`"1989"`, `"1989-06"` oder `"1989-06-15"`. `jahr_von`/`jahr_bis` bleiben für echte
Spannen: Jahrzehnte, „zwischen 1908 und 1912".

**Getrennt:** `praezision` und `datierung_herkunft`. Heute vermischt ein einziges
`precision`-Feld beides — `exact`, `heading`, `event`, `decade`, `interpolated`,
`manual` beantworten teils *wie genau*, teils *woher*. Ein Frontmatter-Datum und
eine Jahresüberschrift stehen dort beide als „exact", obwohl das eine tagesgenau
ist und das andere aufs Jahr. `praezision` sagt jetzt nur noch, wie fein die
Angabe ist (`tag | monat | jahr | spanne | keine`), `datierung_herkunft` nur noch,
woher sie kommt.

`datierung_herkunft = NULL` heißt nie datiert und ist zugleich die
Wiederaufnahme-Bedingung. `manuell` ist gegen Neuläufe geschützt, wie
`kategorie_herkunft`.

**Ergänzt:** `datierung_lauf_id` — welcher Lauf die Datierung geschrieben hat.

**Geändert:** `ist_zitat` ist nullable. `parse_document` erhebt das Merkmal nur bei
Presseexzerpten; der Vorgabewert `0` hätte für jedes Literaturexzerpt „geprüft, kein
Zitat" behauptet. `NULL` heißt nicht erhoben, `0` heißt geprüft.

**Ergänzt:** `kategorie_herkunft` und `kategorie_lauf_id`. Heute steht einer
Zuordnung nicht an, wie sie zustande kam: `confidence` bedeutet im LLM-Pfad die
Selbsteinschätzung des Modells und im BGE-Pfad einen Schwellwert auf der
Kosinusähnlichkeit — zwei verschiedene Größen in einer Spalte, ununterscheidbar.
`kategorie_herkunft` trennt sie und hält zugleich die Handkorrektur fest;
`kategorie_lauf_id` verweist auf den Lauf, der die Zuordnung geschrieben hat.

Zwei Werte, weil es nur zwei Urheber gibt: die Maschine oder der Historiker.

`taxonomie`, `bge` und `llm` standen zwischenzeitlich für drei Wege, aber die
ersten beiden waren dasselbe Verfahren in zwei Fassungen — Beschreibungen
einbetten, Argmax über die Einheiten. Der Unterschied lag nur darin, was
eingebettet wurde (`description` gegen `name+description+keywords`) und wie
lang der Text sein durfte. Für die Frage, ob eine Zuordnung geschützt ist,
trägt diese Unterscheidung nichts; für die Frage, womit gerechnet wurde, steht
sie ohnehin genauer in der `lauf`-Zeile.

`manuell` ist gegen jeden Neulauf geschützt. `automatisch` wird von jedem
Zuordnen ersetzt.

`NULL` heißt nie klassifiziert und ist zugleich die Wiederaufnahme-Bedingung: ein
Lauf nimmt sich `WHERE kategorie_herkunft IS NULL`. Damit braucht es keine
Resume-Datei mehr — der Zustand steht an der Einheit.

`manuell` ist gegen Neuläufe geschützt, auch gegen `--force`. Eine Handkorrektur zu
überschreiben verlangt einen eigenen, ausdrücklichen Wert; sonst löscht der Knopf
„Neu klassifizieren" die Arbeit des Historikers unbemerkt.

### `anker`

**Ergänzt:** `quellennotation` als Herkunft. Die BER-Chronik trägt 577 tagesgenaue
Erscheinungsdaten in der Quellennotation, die heute geparst und nie gelesen werden.

### `kategorie`

**Entfernt:** `position` — existierte nur, um Farben abzuleiten. Farben werden in der
Oberfläche vergeben.

**Ergänzt:** `herkunft` — `vorschlag` für eine Kategorie aus dem Clustering-Lauf,
`manuell` für eine, die der Historiker angelegt oder überarbeitet hat. Ohne die
Spalte ist einem Namen nicht anzusehen, ob je ein Mensch ihn geprüft hat.
Kein Vorgabewert: der Erzeuger muss sich äußern.

### `akteur`

**Ergänzt:** `status` mit zwei Werten, projektweit. Ablehnungen liegen heute in
`entities_rejected.json` — je Dokument, getrennt von den Entitäten, auf die sie sich
beziehen. `abgelehnt` heißt nicht gelöscht: die Zeile bleibt, damit der nächste
Erkennungslauf den Fehlfund überspringt.

Drei Werte wären zwei zu viel. `vorgeschlagen` und `bestaetigt` ließen sich nicht
unterscheiden, weil es keinen Schritt gibt, an dem ein Mensch bestätigt — heute
täuscht der Editor das mit einem `_status:"confirmed"` vor, das er beim Speichern
wieder wegwirft. Was ein Mensch angefasst hat, steht jetzt in `herkunft`.

**Ergänzt:** `herkunft` — `gliner` oder `manuell`, wie bei `kategorie` und
`einheit.datierung_herkunft`. Ein Neulauf ersetzt die `gliner`-Zeilen und lässt die
`manuell`-Zeilen stehen. Heute überschreibt jeder Lauf `config.json["entities"]`
vollständig; von Hand gepflegte Aliase und korrigierte Namen sind danach weg.

**Geändert:** `typ` ist nullable und auf vier Werte festgelegt. `NULL` steht für
einen Fund, dessen Label die Abbildung nicht kennt — heute wird der still zu
`Konzept`. Der Wertevorrat schließt aus, was in `ber` steht: `Werk`.

**Behalten:** `zusammenfassung`. Heute erzeugt `generate_entity_summaries.py`
sie direkt nach `exploration/entities_summary.json` — die Datei ist dort zugleich
Speicher und Ausgabe, und ein Neuexport verliert sie oder erzeugt sie neu auf
Kosten von API-Aufrufen. Hier steht sie an der Zeile, zu der sie gehört; die
Exportdatei ist nur noch eine Ableitung.

### `verschmelzungskandidat`

**Neu.** Heute gibt es zwei Quellen für Duplikatsvorschläge, die einander
widersprechen: der Server rechnet Embeddings im Band 0,80–0,91, der Browser rechnet
bei jedem Tastendruck Levenshtein und Alias-Überschneidung über alle Paare. Ein Badge
aus der einen Quelle verweist auf einen Reiter, der aus der anderen gespeist wird.

Jetzt eine Quelle, drei Regeln, ein Ergebnis in der Datenbank. `grund` sagt, welche
Regel angeschlagen hat, `mass` mit welchem Wert.

Die Tabelle ist ein Erzeugnis des Laufs, kein Zustand: sie hält keine Entscheidungen
fest, sondern nur, was zu prüfen wäre. Ein Neulauf ersetzt sie.

### `periode`

**Entfernt:** `farbe` — Darstellung.

**Geändert:** `jahr_von` und `jahr_bis` sind nullable. Die LLM-Analyse liefert
Perioden nicht immer mit Jahreszahlen; unter `NOT NULL` müsste der Erzeuger welche
erfinden oder die Periode verwerfen.

### `einheit_akteur`

**Ergänzt:** `start` und `ende` — die Fundstelle im Text der Einheit. Damit wird aus
der Tabelle eine Zeile je *Vorkommen* statt je Einheit, und der Schlüssel ein
eigener: `UNIQUE (einheit_id, akteur_id, start)`.

GLiNER liefert diese Offsets ohnehin, der heutige Code wirft sie weg; die Zuordnung
wird danach per Wortgrenz-Regex neu gesucht — einmal beim Erzeugen und noch einmal
im Browser, um die Namen einzufärben. Mit den Offsets entfällt die zweite Suche.

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

**Herkunft des Akteurs-Namens.** `akteur.herkunft` sagt, ob ein Mensch die Zeile
angefasst hat, aber nicht, welcher Lauf sie erzeugt hat — anders als bei
`einheit.datierung_lauf_id` und `kategorie_lauf_id`. Solange ein Neulauf die
`gliner`-Zeilen ohnehin vollständig ersetzt, trüge eine `lauf_id` nichts bei; sobald
Läufe nur noch ergänzen, fehlt sie.

**Fundstellen und Aliase.** Die Offsets in `einheit_akteur` stammen aus dem
Wortgrenz-Regex über Normalform und Aliase, nicht aus GLiNER. Das findet mehr als
der Erkenner — und auch Falsches: der Alias `fatat` trifft jedes Vorkommen des
Wortes. Solange die Zuordnung so entsteht, ist ein zu kurzer Alias ein Fehler mit
Breitenwirkung, und es gibt nichts, was ihn abfängt.

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
