# Vision — BER Chronik / Generalisierter Ingest

## Was das ist

Ein Werkzeug das historische Quelltexte — Forschungsnotizen, Presseartikel, Chroniken — in interaktiv explorierbare Zeitreihen verwandelt. Gebaut aus der Erfahrung historischer Forschungsarbeit, versucht es generalisierbar zu sein ohne den konkreten Anwendungsfall aus den Augen zu verlieren.

## Grundprinzip: Vorschlag → Feedback → Run

Gilt für jeden Schritt der Pipeline:

- **Taxonomie:** LLM schlägt Kategorien vor → Nutzer korrigiert → Pipeline klassifiziert
- **Zeitanker:** System erkennt Anker → Nutzer korrigiert via Editor → Interpolation läuft neu
- **Entities:** LLM schlägt Entities vor → Nutzer korrigiert im Editor → Vollständiger Lauf mit Few-Shot

Kein Schritt ist einmalig. Jeder Schritt ist wiederholbar mit besserem Input.

## Was die Exploration zeigen muss

Die Exploration-App (viz/) ist der Maßstab für den Ingest. Was der Ingest produziert muss zur Exploration passen:

- Zeitanker → Timeline
- Taxonomie → Kategorien und Farben
- Entities → Netzwerk und Highlighting

Änderungen am Ingest-Output müssen immer mit der Exploration-App abgeglichen werden.

## Zielgruppe

Historiker und Forschende die mit heterogenem Quellmaterial arbeiten. Das System ist auf eigene Arbeitspraxis zugeschnitten aber versucht generalisierbar zu sein:

- Verschiedene Dokumenttypen (`buchnotizen`, `presseartikel`) sind wählbar
- Einzelne Pipeline-Schritte sind aus/an/austauschbar
- Möglichst einfach – kein Programmieraufwand für den Nutzer

## Technische Prinzipien

- **Lokal-first:** Ollama als Default, Anthropic als Option
- **Provider-agnostisch:** kein Modellname hardcoded außer in `llm.py`
- **Vorschlag → Feedback → Run** auch technisch: Resume-fähige Pipeline, kein Schritt verliert Arbeit
- **Leichtgewichtig:** keine unnötigen Dependencies in der Produktiv-Pipeline

## Was experimentell bleibt

BERT/mBERT-Ansätze für Entity-Erkennung liegen in `notebooks/test_cluster_quality.py` und `notebooks/test_ner_*.py`. Sie sind nicht produktiv. Vor einer Implementierung braucht es:

- Klaren Recall-Vorteil gegenüber LLM-only
- Span-basiertes NER (nicht Token-basiert)
- Ausreichend Trainingsdaten aus dem Segment-Annotator

## Was nicht in VISION.md steht

Konkrete Implementierungsentscheidungen, offene Bugs, aktuelle Modellnamen → gehören in `STATUS.md`.