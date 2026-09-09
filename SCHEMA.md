# Datenbankschema

Stand nach der Durchsprache. Ersetzt Abschnitt 2 von `DATENMODELL.md`.

Vierzehn Tabellen. Grundsätze, die in allen gelten:

- **Ein Sachverhalt, eine Stelle.** Kein Wert steht zweimal. Die einzige
  Ausnahme ist `einheit_embedding`, und sie ist keine: dort steht kein
  Sachverhalt, sondern ein Rechenergebnis, das jederzeit wieder herstellbar ist.
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
    rolle        TEXT    NOT NULL DEFAULT 'nutzer'
                         CHECK (rolle IN ('verwalter', 'nutzer')),
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
    quellformat   TEXT NOT NULL
                  CHECK (quellformat IN ('literaturexzerpt', 'presseexzerpt',
                                         'pressesammlung')),
    pfad          TEXT,            -- DOCX-Datei oder Dropbox-Ordner
    eingelesen_am TEXT NOT NULL
);

-- ── einheit ───────────────────────────────────────────────────────────────────
CREATE TABLE einheit (
    id                 INTEGER NOT NULL PRIMARY KEY,
    quelle_id          TEXT    NOT NULL REFERENCES quelle(id) ON DELETE CASCADE,
    position           INTEGER NOT NULL,
    typ                TEXT    NOT NULL
                       CHECK (typ IN ('content', 'heading', 'bibliography', 'meta')),
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
    -- Gliederungstiefe des Literaturexzerpts: 1 Organizer, 2 bibliografische
    -- Ebene, 3 Notiz unter einer Buchquelle. NULL bei jedem anderen Format.
    --
    -- Die Grenze gehört dem heutigen Parser, nicht dem Gegenstand: ein Exzerpt
    -- könnte tiefer gegliedert sein, ingest/kern.py vergibt aber nur diese
    -- drei. Wer den Parser vertieft, hebt hier mit — der CHECK meldet sich
    -- dann, und das ist seine Aufgabe.
    ebene              INTEGER CHECK (ebene IN (1, 2, 3)),
    ist_zitat          INTEGER,            -- NULL = nicht erhoben, 0 = geprüft

    -- Ergebnis der Datierung
    datum              TEXT,               -- "1989" | "1989-06" | "1989-06-15"
    jahr_von           INTEGER,            -- nur bei echten Spannen
    jahr_bis           INTEGER,
    praezision         TEXT                -- Granularität
                       CHECK (praezision IN
                              ('tag', 'monat', 'jahr', 'spanne', 'keine')),
    datierung_herkunft TEXT                -- wie zustande gekommen
                       CHECK (datierung_herkunft IN
                              ('text', 'ueberschrift', 'frontmatter',
                               'quellennotation', 'ereignis', 'interpoliert',
                               'manuell')),
                                           -- NULL = nie datiert
    datierung_lauf_id  INTEGER REFERENCES lauf(id) ON DELETE SET NULL,

    -- Ergebnis der Klassifikation
    kategorie_id       INTEGER REFERENCES kategorie(id) ON DELETE SET NULL,
    konfidenz          TEXT                -- NULL = nie klassifiziert
                       CHECK (konfidenz IN ('high', 'medium', 'low')),
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
    -- Dieselben wie einheit.datierung_herkunft plus jahrzehnt: das gibt es nur
    -- am Anker — der Wert wird erkannt, trägt aber kein Jahr.
    herkunft   TEXT    NOT NULL
                       CHECK (herkunft IN
                              ('text', 'ueberschrift', 'frontmatter',
                               'quellennotation', 'ereignis', 'interpoliert',
                               'manuell', 'jahrzehnt')),
    fundstelle TEXT    NOT NULL DEFAULT ''
);

-- ── kategorie ─────────────────────────────────────────────────────────────────
CREATE TABLE kategorie (
    id           INTEGER NOT NULL PRIMARY KEY,
    projekt_id   TEXT    NOT NULL REFERENCES projekt(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    beschreibung TEXT    NOT NULL DEFAULT '',
    schlagworte  TEXT    NOT NULL DEFAULT '',
    herkunft     TEXT    NOT NULL
                         CHECK (herkunft IN ('vorschlag', 'manuell')),
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

-- ── einheit_embedding ─────────────────────────────────────────────────────────
-- Der Vektor einer Einheit unter einem bestimmten Modell. Kein Sachverhalt,
-- sondern eine Wiederholung: aus text und modell jederzeit neu herstellbar.
-- Deshalb darf die Tabelle jederzeit geleert werden, und deshalb steht der
-- Grundsatz "kein Wert zweimal" ihr nicht entgegen — sie legt nichts ab, was
-- nicht ohnehin abzuleiten wäre, sie legt es nur schneller vor.
--
-- pruefsumme ist sha256 über genau die Zeichenkette, die embeddet wurde (der
-- Text auf 500 Zeichen gekürzt). Stimmt sie nicht mehr, gilt der Vektor als
-- nicht vorhanden — der Speicher veraltet nicht, er wird ungültig.
--
-- modell gehört in den Schlüssel: bge-m3 (1024), MiniLM (384) und voyage-4
-- liefern verschiedene Vektoren. Ein Anbieterwechsel darf keinen alten Wert
-- weiterverwenden, und ein Zurückwechseln soll die alten sofort wieder gelten
-- lassen.
CREATE TABLE einheit_embedding (
    einheit_id   INTEGER NOT NULL REFERENCES einheit(id) ON DELETE CASCADE,
    modell       TEXT    NOT NULL,   -- BAAI/bge-m3 | voyage-4 | …
    pruefsumme   TEXT    NOT NULL,   -- sha256 des embeddeten Texts
    masse        INTEGER NOT NULL,   -- Dimensionen, = len(vektor)/4
    vektor       BLOB    NOT NULL,   -- float32, normalisiert
    berechnet_am TEXT    NOT NULL,
    PRIMARY KEY (einheit_id, modell)
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
    schritt     TEXT    NOT NULL,   -- ingest | datierung | taxonomie |
                                -- klassifikation | akteure | export.
                                -- Geschlossen, aber ohne CHECK: ein neuer
                                -- Schritt soll nicht zuerst als
                                -- Datenbankfehler zur Sprache kommen.
    begonnen_am TEXT    NOT NULL,
    beendet_am  TEXT,               -- NULL, solange der Lauf läuft
    parameter   TEXT,               -- JSON: womit er aufgerufen wurde
    status      TEXT    NOT NULL
                        CHECK (status IN ('laeuft', 'erfolg', 'fehler'))
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

Kein Index auf `einheit_embedding`: der Primärschlüssel `(einheit_id, modell)`
bedient beide Abfragen, die es gibt — das Nachschlagen je Einheit und die
Zählung je Modell.

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

**Wartet auf Schritt 8 — Mehrbenutzerbetrieb.** Vier Stellen sind angelegt und
haben heute keine Wirkung. Das ist keine offene Frage, sondern ein bereitgelegter
Platz:

| Stelle | Stand heute |
|---|---|
| `projekt_zugang` | kein `SELECT`, kein `INSERT` im Code; die Tabelle ist leer |
| `zugang.rolle` | wird beim Anlegen geschrieben, nirgends gelesen |
| `zugang.organisation` | wird einmal geschrieben (`ingest/cli.py`), nirgends gelesen |
| `projekt.oeffentlich` | wird gelesen und ausgeliefert, aber nichts hängt daran |

Bis dahin gehört alles einem festen lokalen Zugang (siehe
`projekte.lokaler_zugang`). Die Spalten jetzt zu entfernen und später wieder
einzuziehen hieße, zweimal zu migrieren; sie leer mitzuführen kostet nichts.

Offen ist an dieser Stelle nur eines, und es steht unten unter den offenen
Punkten: **wie weit die Verwalterrechte reichen.**

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

**Vier Spalten werden geschrieben und noch von niemandem gelesen:** `autor`,
`kurzfassung`, `ebene` und `ist_zitat`. Sie stehen im Modell `Einheit` und gehen
über `GET /api/projekt/{id}/einheiten` hinaus, aber keine Fläche zeigt sie, keine
Rechnung liest sie, und der Export nimmt sie nicht mit. Sie bleiben trotzdem:

- `ebene` trägt die Hierarchie des Literaturexzerpts — 1 für den Organizer, 2 für
  die bibliografische Ebene, 3 für die Notizen unter einer Buchquelle
  (`ingest/kern.py:160/178/181`). Ohne sie wäre ein Exzerpt eine flache Liste
  Absätze, und die Gliederung, die der Historiker im DOCX angelegt hat, wäre beim
  Einlesen verloren. Sie später zurückzugewinnen hieße, jedes Dokument neu
  einzulesen. Der `CHECK` auf 1|2|3 hält fest, was der Parser heute vergibt, nicht
  was ein Exzerpt sein kann — wer tiefer gliedert, hebt ihn mit an. Dass er sich
  dann meldet, ist seine Aufgabe.
- `autor` und `kurzfassung` kommen aus dem Obsidian-Frontmatter und kosten beim
  Einlesen nichts. Sie wegzulassen hieße, sie beim nächsten Sync erst wieder zu
  beschaffen.
- `ist_zitat` unterscheidet Zitat von Fließtext und ist die Grundlage jeder
  späteren Auswertung, die beides trennen will.

Der Unterschied zu `projekt.status`, das aus demselben Grund entfernt wurde: jene
Spalte war aus dem Bestand jederzeit wieder herstellbar, diese vier sind es nicht —
sie stehen nur im Ausgangsmaterial.

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

**Entfernt:** `position` — existierte nur, um Farben abzuleiten. Farben sollen in
der Oberfläche vergeben werden.

Noch tun sie es nicht: `export/kern.farbzuordnung` vergibt sie serverseitig nach
Listenplatz und liefert sie als `color_map` in `project_meta.json` aus, wo
`viz/highlight.js` sie liest. Die Datenbank hält keine Farben — die Regel gilt
also für den Ablageort, noch nicht für die Vergabestelle. Entschieden ist, dass
viz/ sie ableitet; die Umstellung gehört in die viz/-Runde und steht als offener
Punkt unten.

**Ergänzt:** `herkunft` — `vorschlag` für eine Kategorie aus dem Clustering-Lauf,
`manuell` für eine, die der Historiker angelegt oder überarbeitet hat. Ohne die
Spalte ist einem Namen nicht anzusehen, ob je ein Mensch ihn geprüft hat.
Kein Vorgabewert: der Erzeuger muss sich äußern.

**Die Regel dazu:** ein Taxonomielauf ersetzt nur, was er selbst vorgeschlagen
hat. `manuell`-Zeilen gehen als von Anfang an eingefrorene Cluster in den Lauf —
sie wirken auf die Rechnung und stehen im Prompt, damit sich die anderen von
ihnen abgrenzen, werden aber nicht umgeschrieben. Das ist dieselbe Regel wie
`kategorie_herkunft='manuell'` bei `einheit`, eine Ebene höher.

**Kennungen bleiben.** Der Lauf schreibt in die vorhandenen Zeilen (`cid` ist die
Position in der nach `id` sortierten Liste, die er bekommen hat) und legt nur
kalt neue an. Ein `DELETE FROM kategorie WHERE projekt_id = ?` gibt es nicht: es
hat die Handarbeit mitgenommen, alle Kennungen neu vergeben — SQLite vergibt
freigewordene rowids wieder, sodass dieselbe Zahl danach eine andere Kategorie
bezeichnete — und jede Einheit über `ON DELETE SET NULL` kurzzeitig ohne
Kategorie dastehen lassen.

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

### `einheit_akteur`

**Ergänzt:** `start` und `ende` — die Fundstelle im Text der Einheit. Damit wird aus
der Tabelle eine Zeile je *Vorkommen* statt je Einheit, und der Schlüssel ein
eigener: `UNIQUE (einheit_id, akteur_id, start)`.

GLiNER liefert solche Offsets, aber sie werden nicht benutzt: `_zuordnen` in
`akteure/dienst.py` sucht die Fundstellen per Wortgrenz-Regex über Normalform und
Aliase — absichtlich, denn der Regex findet auch die Aliase, die der Erkenner nicht
als Treffer meldet. Was in `start`/`ende` steht, stammt also aus dieser Suche.

Die zweite Suche im Browser bleibt damit bestehen. `data.json` trägt `actors` als
reine Namensliste ohne Positionen, und `viz/highlight.js` sucht die Namen erneut,
um sie einzufärben. Das aufzulösen hieße, die Offsets mitzuexportieren und viz/
umzustellen — beides steht nicht an. Siehe den offenen Punkt „Fundstellen und
Aliase" unten, der denselben Sachverhalt von der anderen Seite beschreibt.

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

### `periode`

Die Tabelle ist entfallen. Sie hielt Zeitabschnitte, die das Sprachmodell in
Wizard-Schritt 3 aus einer Stichprobe von 30 Absätzen vorschlug und die der
Historiker in Schritt 5 nachbessern konnte. Gelesen hat sie nie jemand: die
Datierung nimmt ihre Ereignisse aus einer fest verdrahteten Liste
(`src/neu/datierung/kern.py:EREIGNISSE`), und `viz/` kennt das Feld `events`
nicht. Die sieben Zeilen, die je darin standen, waren die Vorschläge für
damaskus, einmal beim Anlegen der Fixture übernommen.

Damit fällt auch `events` aus `project_meta.json` weg.



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

**Jahrzehnt-Anker — gezählt, erledigt.** Die Erkennung legt für „1890er Jahre" einen
Anker mit `herkunft = 'jahrzehnt'` und `jahr = NULL` an; `datierung/kern.py:348`
wertet ihn nicht aus, die Einheit fällt in die Interpolation. Ein solcher Anker
wüsste mehr — 1890 bis 1899.

Gezählt über den ganzen Bestand, nach dem, was aus den Einheiten tatsächlich wurde:

| Projekt | Jahrzehnt-Anker | Einheit trägt ohnehin eine Jahreszahl | fällt in die Interpolation |
|---|---|---|---|
| `damaskus` | 9 | 8 | **1** |
| `nahda` | 8 | 8 | 0 |
| `osmanisch` | 1 | 1 | 0 |

In acht von neun Fällen bei `damaskus` gewinnt eine Jahreszahl aus dem Fließtext,
der Jahrzehnt-Zweig wird gar nicht erreicht; in `nahda` und `osmanisch` jedes Mal.
**Der Fall betrifft genau eine Einheit im gesamten Bestand.** Damit lohnt die
Auswertung nicht, und der Punkt ist geschlossen. Der Wert bleibt im Vorrat und im
`CHECK`: er kostet nichts, und die Zählung wäre bei anderem Material eine andere.

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

Von Hand korrigierbar wäre die Spalte deshalb gut: der Historiker könnte Gruppen
zusammenlegen, trennen und umbenennen, ohne das DOCX zu ändern und ohne neu
einzulesen. Es gibt dafür heute keinen Weg — keine Route, kein Rumpffeld, keine
Fläche; geschrieben wird `chronologie_gruppe` nur beim Einlesen.

**Das steht nicht an.** Es ist Fachlogik, keine Aufräumarbeit, und es wäre ein
eigener Schritt im Ablauf. Bis dahin gilt: wer eine falsche Gruppe hat, korrigiert
die Überschriftenformatierung im DOCX und liest neu ein. Kein Versäumnis, sondern
eine verschobene Erweiterung.
