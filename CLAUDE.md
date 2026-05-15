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

## Drei Quellentypen

Das System kennt genau drei Quellentypen. Welcher Typ vorliegt, bestimmt wie das System
jeden einzelnen Pipeline-Schritt ausführt — Segmentierung, Datierung, Interpolation.
Wer das nicht weiß, versteht weder den Wizard noch den Code.

**Literaturexzerpt** (Beispiele: Damaskus-Studie, Osmanisches Reich)
Strukturierte Forschungsnotizen, als DOCX. Der Historiker hat ein Werk exzerpiert und
die Notizen nach Kapiteln oder Jahres-Überschriften gegliedert. Ein Segment entspricht
einem Absatz. Datierung läuft über Jahres-Überschriften im Text oder explizite
Jahreszahlen im Fließtext; wo beides fehlt, interpoliert das System zwischen bekannten
Ankern. Die inhaltliche Tiefe variiert stark — ein Absatz kann eine Dekade oder ein
einzelnes Ereignis beschreiben.

**Pressezusammenfassung** (Geicke-Stil, Beispiel: BER Chronik 1989–2017)
Eine verdichtete Chronik, als DOCX. Jeder Eintrag beschreibt ein konkretes Ereignis mit
expliziter Datumsangabe im Text. Ein Segment entspricht einem solchen Ereigniseintrag.
Datierung ist fast immer exakt — Jahres-Überschriften im DOCX oder Datumsangaben im
Fließtext. Interpolation wird kaum gebraucht. Der Informationsdichtetyp ist hoch und
homogen.

**Pressesammlung** (Obsidian-Ingest, Beispiel: tagesaktuelle Berichterstattung)
Ganze Presseartikel aus Web-Clipping via Obsidian, als Markdown-Dateien mit
YAML-Frontmatter. Ein Segment entspricht einem Artikel. Datierung kommt aus dem
Frontmatter-Feld `published` (oder `created` als Fallback) — immer exakt auf den Tag.
Interpolation entfällt vollständig. Die Segmente sind heterogen in Länge und Stil;
viele sprechen dieselben Ereignisse aus unterschiedlichen Blickwinkeln an.

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
Alle Segmente als Punkte auf einem Zeitstrahl, eingefärbt nach Kategorie. Die
Zeitraum-Granularität passt sich dynamisch an den abgedeckten Zeitraum an: bei mehreren
Jahrzehnten sind die Bins Jahre, bei wenigen Jahren Monate, bei noch kürzerem Zeitraum
Tage. Das bestimmt was die Visualisierung zeigt — ein Jahrzehnte-Projekt und ein
Jahres-Archiv sehen grundlegend anders aus. Ein Klick auf einen Punkt öffnet den
Originaltext. Die Timeline ist filterbar nach Kategorie und Entität.

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

## Lesereihenfolge

**1. `CLAUDE.md`** (dieser Text) — Zweck, Quellentypen, was das System leistet.
Ohne das ist jedes andere Dokument Kontext ohne Rahmen.

**2. `src/generalized/WIZARD_FLOW.md`** — Wie ein Dokument durch das System läuft.
Beschreibt die 7 Wizard-Schritte, welche Endpoints aufgerufen werden, welche Dateien
dabei entstehen, und wo kritische Abhängigkeiten zwischen Schritten liegen. Der
konkrete Ablauf vor den Gründen.

**3. `DECISIONS.md`** — Warum so und nicht anders.
Enthält alle nicht-offensichtlichen Entscheidungen: warum `config.json` die einzige
Quelle für Taxonomie und Entitäten ist, warum `classified.json` ein gemeinsames
Dokument ist, warum Obsidian Zotero abgelöst hat. Vor jeder Änderung prüfen ob eine
relevante Entscheidung schon dokumentiert ist.

**4. `ARCHITECTURE.md`** — Technische Muster.
Datenpfade, SSE-Protokoll, Auth-Pattern, Locks. Setzt Verständnis des Wizards voraus.

**5. `STATUS.md`** — Was gerade tatsächlich funktioniert und was nicht.
Bekannte Fallbacks, offene Inkonsistenzen, Bugs. Zuletzt lesen — es erklärt Abweichungen
vom Soll-Zustand, der erst durch die anderen Dokumente klar ist.
