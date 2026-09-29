# Deployment

Wie der neue Dienst (`src/neu`) gebaut und betrieben wird. Für das alte System
auf Port 8001 gilt nichts davon — es läuft unverändert weiter.

---

## Der Weg: ein Dockerfile, sonst nichts

`Dockerfile` im Wurzelverzeichnis, drei Stufen: Node baut `frontend/build`,
Python baut das venv aus `requirements.lock.txt`, das Endabbild trägt beides.
Kein Node zur Laufzeit. Gemessen am 29. September: 2,46 GB.

`railway.toml` setzt `builder = "dockerfile"` ausdrücklich. Der Startbefehl
steht **nur** im Dockerfile als `CMD` — nicht daneben in `railway.toml`, weil
zwei Orte, die dasselbe sagen können, irgendwann Verschiedenes sagen.

Entsorgt und nicht wiederzubeleben: `railpack.json` (seit 18. Mai ungültig, ihr
`startCommand` startete den alten Server), `fly.toml`, `Dockerfile.local`,
`fly-deploy.yml` (47 Läufe, 47 Fehlschläge).

---

## Ohne diese Variablen startet der Dienst nicht

Genau eine bricht den Start ab. Alle anderen fehlenden Angaben legen nur
einzelne Schritte lahm, die dann mit 503 antworten.

| Variable | Wirkung, wenn sie fehlt |
|---|---|
| `ZUGANG_PASSWORT` | **Der Prozess startet nicht.** Die Meldung nennt die Variable. |

Es gibt keine Vorgabe, und das ist der Punkt: eine Vorgabe würde behaupten,
dieser Dienst dürfe offen stehen.

```
ZUGANG_PASSWORT=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
```

Jede Anfrage verlangt danach HTTP Basic — die Fläche unter `/`, die API,
`/viz/` und die Exportdateien unter `/data/exporte/`. Der Benutzername wird
nicht geprüft; das Geheimnis ist das Passwort. Siehe `src/neu/zugang.py`.

---

## Was auf Railway gesetzt sein muss

Die ersten drei stehen schon in `railway.toml` und brauchen im Dashboard
nichts. Die übrigen sind Geheimnisse und gehören nur dorthin.

| Variable | Wert | Wofür |
|---|---|---|
| `ZUGANG_PASSWORT` | ein Geheimnis | **Pflicht.** Ohne sie startet nichts. |
| `DATA_ROOT` | `/data` | Datenbank, Uploads, Exporte aufs Laufwerk. In `railway.toml`. |
| `LLM_PROVIDER` | `anthropic` | In `railway.toml`. |
| `EMBEDDING_PROVIDER` | `voyage` | In `railway.toml`. Siehe „Platz" unten. |
| `ANTHROPIC_API_KEY` | ein Schlüssel | Taxonomie, Zusammenfassungen, Chat. |
| `VOYAGE_API_KEY` | ein Schlüssel | Einbettungen. |
| `DROPBOX_APP_KEY` | | Obsidian-Anbindung. |
| `DROPBOX_APP_SECRET` | | Dito. |
| `DROPBOX_REDIRECT_URL` | die produktive URL | In `railway.toml`. |

`HF_HOME=/data/huggingface` setzt das Dockerfile selbst — im Dashboard hat es
nichts zu suchen.

**`OBSIDIAN_WURZEL` bleibt ungesetzt.** Im Betrieb kommt Obsidian über Dropbox,
und einen Obsidian-Ordner gibt es auf dem Container gar nicht. Gesetzt wäre sie
eine Tür, die niemand braucht.

### Wirkungslos geworden — erst nach der Umstellung entfernen

`NEU_DB` (von `DATA_ROOT` abgedeckt, und als engere Angabe würde sie die
Datenbank sogar von Uploads und Exporten trennen), `ADMIN_KEY`, `INVITES_JSON`,
`ZOTERO_API_KEY`, `ZOTERO_USER_ID`, `OLLAMA_MODEL`, `RAILWAY_SIM`.

Die Reihenfolge zählt: `ADMIN_KEY` und `INVITES_JSON` gehören zum Invite-Gate
des **alten** Servers. Solange der läuft, würde ihr Entfernen ihn aufmachen.
Erst umstellen, dann räumen.

---

## Der Platz auf dem Laufwerk

Die Railway-Vorgabe ist 5 GB. Darauf passen GLiNER (1,1 GB) und bge-m3 (4,3 GB)
zusammen **nicht**. Mit `EMBEDDING_PROVIDER=voyage` rechnet nur GLiNER lokal,
und das Laufwerk trägt rund 1,2 GB — gemessen am 29. September mit einem
vollständigen Durchlauf.

Ein Umschalten auf `local` im Betrieb lädt bge-m3 nach und füllt es. Was wo
liegt, sagt `GET /api/bestand` und die Seite `/bestand`; sie warnt, sobald
weniger als 6 GB frei sind.

---

## Kein Gesundheitscheck

`railway.toml` setzt kein `healthcheckPath`, das Dockerfile kein `HEALTHCHECK`.
Railway wartet damit darauf, dass der Prozess auf `$PORT` lauscht, und fragt
nichts über HTTP ab.

Das ist beabsichtigt: ein Pfad, der am Riegel vorbei antworten muss, steht
offen. Wer trotzdem einen einträgt, muss ihn in `zugang.OHNE_RIEGEL` aufnehmen
— sonst hält Railway den Dienst wegen 401 für tot — und er darf dann nichts
verraten, auch keine Version und keinen Projektnamen. `tests/test_neu_zugang.py`
hält fest, dass die Liste heute leer ist.

---

## Erststart auf leerem Laufwerk

Fehlt die Datenbank, legt der Server sie beim Hochfahren aus `schema.sql` an und
schreibt es als Warnung ins Protokoll:

```
WARNING:     ====================================================================
WARNING:     LEERE DATENBANK ANGELEGT: /data/neu.db
WARNING:     ====================================================================
```

Wer diese Zeile beim **zweiten** Deploy wiedersieht, weiß, dass das Laufwerk
nicht hält.

---

## Lokal

```bash
cp .env.example .env          # ZUGANG_PASSWORT eintragen, sonst startet nichts
cd frontend && npm install && npm run build && cd ..
PYTHONPATH=. uvicorn src.neu.server:app --port 8002 --reload
```

Der alte Wizard bleibt davon unberührt und läuft weiter auf 8001.
