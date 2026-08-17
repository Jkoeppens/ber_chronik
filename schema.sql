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
    kategorie_herkunft TEXT,               -- llm | bge | manuell
                                           -- NULL = nie klassifiziert
    kategorie_lauf_id  INTEGER REFERENCES lauf(id) ON DELETE SET NULL,

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
    herkunft     TEXT    NOT NULL,   -- vorschlag | manuell
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
