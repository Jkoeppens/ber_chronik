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
    ebene              INTEGER,            -- 1|2|3, nur literaturexzerpt
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
