# BER Chronik — Projekteinstieg

## Was ist das hier?

BER Chronik ist ein Werkzeug, das heterogene historische Quelltexte — Forschungsnotizen,
Presseartikel, Chroniken — automatisch in eine interaktiv explorierbare Zeitvisualisierung
verwandelt.

---

## Das Problem, das es löst

Ein Historiker hat hunderte oder tausende Seiten Quellmaterial: DOCX-Dokumente mit
Absätzen, gescrapte Presseartikel, Exzerpte. Er weiß, was darin steht — aber er kann
nicht sehen, wann etwas passiert ist, welche Akteure immer wieder auftauchen, oder was
genau in einem bestimmten Jahr besonders viel passiert ist. Eine Datenbank wäre zu starr;
eine Stichwortsuche zu flach.

BER Chronik löst das, indem es das Material maschinen-verarbeitet und für visuelle
Exploration aufbereitet: Zeitstrahl, Netzwerk, Chat — alles auf Basis des Originaltexts,
ohne dass der Historiker programmieren muss.

Das System ist für eigenen Betrieb ausgelegt (lokal oder selbst gehostet), nicht als
Dienst. Der Nutzer steuert sein Material, seine Taxonomie und seine Entitätsliste.

---

## Die sieben Schritte: vom Rohdokument zur Visualisierung

**Schritt 1 — Ingest**
Das Rohdokument wird ins System gebracht. Es gibt zwei Wege: ein DOCX-Upload (für
Forschungsnotizen und Geicke-Stil-Pressearchive) oder ein Obsidian/Dropbox-Sync (für
Web-geclippte Presseartikel im Markdown-Format). Je nach Weg unterscheidet sich, wie
das Dokument strukturiert ist und welche Metadaten verfügbar sind.

**Schritt 2 — Segmentierung und Anker-Erkennung**
Das Dokument wird in semantische Einheiten (Segmente) zerlegt. Gleichzeitig sucht das
System nach Zeitankern: explizite Jahreszahlen im Text, Datumsangaben aus Frontmatter-Feldern,
oder Jahres-Überschriften im DOCX. Jeder gefundene Anker bekommt eine Präzisionsstufe
(exakt/Jahrzehnt/interpoliert).

**Schritt 3 — Zeitkorrektur**
Der Historiker bekommt eine Vorschau aller datierten Segmente und kann Fehler korrigieren:
falsch erkannte Jahreszahlen, fehlende Anker. Korrekturen werden als Overrides gespeichert
und sind wiederholbar.

**Schritt 4 — Taxonomie**
Das System schlägt auf Basis des Textes Kategorien vor (z.B. „Klage", „Personalie",
„Kosten"). Der Historiker verfeinert die Vorschläge im Taxonomy-Editor. Die bestätigte
Taxonomie ist der Maßstab für alle nachfolgenden Klassifizierungen.

**Schritt 5 — Klassifizierung**
Jedes Segment wird einer Taxonomie-Kategorie zugeordnet. Das geschieht entweder über
LLM-Klassifikation (präziser, kostet API-Calls) oder über BGE-M3 Cosine-Similarity
(schneller, lokal). Die Klassifizierung ist wiederholbar wenn sich die Taxonomie ändert.

**Schritt 6 — Entity-Erkennung und -Matching**
Personen, Organisationen und Orte werden per GLiNER erkannt und gegen eine kurierte
Entitätsliste gematcht. Der Historiker kann Entitäten im Editor hinzufügen, umbenennen,
zusammenführen und ablehnen. Nach jeder Änderung läuft das Matching neu.

**Schritt 7 — Export**
Das System generiert alle Dateien für die Visualisierungs-App: eine strukturierte
JSON-Datei mit allen datierten und klassifizierten Segmenten, ein vorberechnetes
Netzwerk-Layout, Entitäts-Alias-Tabellen und optionale KI-Zusammenfassungen pro Entität.
Die Visualisierung ist danach direkt im Browser nutzbar.

---

## Die drei Ausgaben

**Timeline-Heatmap**
Alle Segmente als Punkte auf einem Zeitstrahl, gruppiert nach Jahr und Monat, eingefärbt
nach Kategorie. Der Historiker sieht auf einen Blick, in welchen Jahren bestimmte
Ereignistypen gehäuft auftraten. Ein Klick auf einen Punkt öffnet den Originaltext.
Die Timeline ist filterbar nach Kategorie und Entität.

**Akteursnetzwerk**
Alle Entitäten als Knoten, verbunden wenn sie im selben Segment erscheinen. Die
Kantendicke zeigt Häufigkeit, die Kantenfarbe den dominanten Ereignistyp. Der Historiker
kann einen Akteur anwählen und bekommt seinen Ego-Graphen — alle direkten Verbindungen
mit den zugehörigen Quellabsätzen. Das Netzwerk ist filterbar nach Entitätstyp und
Ereignistyp.

**Chat und Volltextsuche**
Fragen auf Deutsch werden von Claude Haiku auf Basis der Originalsegmente beantwortet,
mit konkreten Quellenbelegen. Kurze Eingaben ohne Fragezeichen lösen stattdessen
Volltextsuche aus und zeigen direkt die passenden Absätze. Beide Modi sind im gleichen
Interface — die Heuristik ist unsichtbar.

---

## Was eine neue Instanz zuerst lesen sollte

**1. `DECISIONS.md`** — Warum das System so gebaut ist wie es ist.
Enthält alle nicht-offensichtlichen Entscheidungen: warum `config.json` die einzige
Quelle für Taxonomie und Entitäten ist, warum classified.json ein gemeinsames Dokument
ist, warum Obsidian Zotero abgelöst hat. Bevor irgendwas geändert wird, sollte
überprüft werden ob eine relevante Entscheidung schon dokumentiert ist.

**2. `src/generalized/WIZARD_FLOW.md`** — Wie Wizard und Pipeline zusammenhängen.
Beschreibt die 7 Wizard-Schritte, welche Endpoints aufgerufen werden, welche Dateien
dabei entstehen, und wo kritische Abhängigkeiten liegen. Unverzichtbar bevor an
`dev_server.py` oder `ingest_wizard.html` gearbeitet wird.

**3. `STATUS.md`** — Was gerade tatsächlich funktioniert und was nicht.
Listet bekannte Fallbacks, offene Inkonsistenzen und Bugs. Verhindert dass Arbeit
in einen Bereich investiert wird, der gerade sowieso kaputt ist.

`ARCHITECTURE.md` kommt danach — es erklärt die technischen Muster (Datenpfade, SSE,
Auth), setzt aber Verständnis des Wizards voraus.
