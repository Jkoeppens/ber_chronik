"""
kern.py — Taxonomie-Vorschlag durch iteratives Verfeinern

Der Kreislauf: Segmente embedden → KMeans → TF-IDF-Schlagworte → ein
kontrastiver LLM-Call über alle Gruppen → die Beschreibungen zurück-embedden
→ die Embeddings ersetzen die Zentroide → neu zuordnen. Je Cluster wird
eingefroren, sobald sich die Beschreibung nicht mehr bewegt.

Reine Funktionen: Embedding und Sprachmodell kommen als Funktionen von außen
herein. Keine Datei, kein Netz, kein print. Damit ist der ganze Kreislauf ohne
Modell und ohne Schlüssel prüfbar.

Fachlogik unverändert übernommen aus
src/generalized/test_tfidf_anchor_taxonomy.py, Funktion _run_tfidf_anchor
samt _compute_tfidf_keywords, _kmeanspp_sample, _build_prompt,
_parse_llm_response, _neighbor_aggregate, _compute_centroids und den
Konstanten. Der Prompt ist wörtlich der der Vorlage.

Nicht übernommen: die spätere Prompt-Fassung v2 ("Beschreibung als
Hypothese"). Für sie gibt es eine Messung, nach der sie besser konvergiert
(pipeline_log_sonnet_t0_v2.jsonl) — das ist eine eigene Änderung mit eigenem
Vergleich, nicht Teil dieser Übernahme.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

# ── Konstanten, unverändert aus der Vorlage ───────────────────────────────────

N_CLUSTERS = 7
N_ITER = 4                    # LLM-Calls (alle km_interval k-means-Schritte)
N_SEGMENTS_PER_CLUSTER = 10   # k-means++ Stichprobe je Cluster
KM_INTERVAL = 5               # k-means-Schritte zwischen LLM-Calls
MIN_LENGTH = 30
SEG_CHARS = 500
SHORT_THRESHOLD = 100
TOP_K_KW = 8
EARLY_STOP_DELTA = 0.01       # Cluster einfrieren wenn sim-Verbesserung < 1%

STOPWORDS = {
    "der", "die", "das", "und", "in", "von", "zu", "den", "mit", "ist", "im",
    "dem", "des", "ein", "eine", "sich", "auch", "auf", "an", "für", "es",
    "als", "bei", "aber", "oder", "aus", "hat", "nicht", "wird", "war",
    "waren", "dass", "wenn", "nach", "durch", "um", "so", "wie",
    "über", "bis", "dann", "diese", "dieser", "diesem", "diesen", "dieses",
    "er", "sie", "wir", "ihre", "ihrer", "ihren", "ihrem", "ihres",
    "sein", "seiner", "seinem", "seinen", "seine", "eines", "einem", "einen",
    "werden", "haben", "noch", "mehr", "nur", "schon", "sehr", "hier", "da",
    "beim", "am", "zum", "zur", "januar", "februar", "märz", "april",
    "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember",
}
STOPWORDS_EXTRA = {
    "osm", "arab", "the", "and", "was", "were",
    "with", "that", "this", "from", "have", "not",
    "al", "ibn", "abu", "bin",
}

SYSTEM = (
    "Du analysierst Gruppen von Texten. "
    "Schreibe präzise, kontrastierende Beschreibungen — kein allgemeines Intro, keine Floskeln."
)

PROMPT_TEMPLATE = """\
Du analysierst {n} Gruppen von Texten.

Für jede Gruppe sind folgende Keywords konstant charakteristisch \
(diese sollen in deiner Beschreibung vorkommen):

{keyword_section}
{prev_section}
Neue Beispieltexte:
{segment_section}

Schreibe neue Beschreibungen unter Einbeziehung der Keywords und Beispieltexte. \
Die neue Beschreibung soll nicht wiederholen was die vorherige schon sagt. \
Frage stattdessen: Was hält diese Texte zusammen? \
Welches übergeordnete Prinzip, welche strukturelle Gemeinsamkeit erklärt warum \
diese Segmente in einer Gruppe landen — \
nicht was sie beschreiben, sondern wie sie funktionieren. \
Jede Gruppe muss sich klar von den anderen unterscheiden.

Antworte für jede Gruppe im Format (kein weiterer Text):

## Gruppe 1
[2-4 Wörter Titel]
[2-3 Sätze Beschreibung die die Keywords einschließt]

## Gruppe 2
[Titel]
[Beschreibung]
"""


# ── Ergebnisgestalt ───────────────────────────────────────────────────────────

@dataclass
class Runde:
    """Was in einer LLM-Runde geschah — die Trajektorie, Zeile für Zeile."""

    km_iter: int
    llm_runde: int
    aenderungsanteil: float
    eingefroren_gesamt: int
    neu_eingefroren: list[int]
    # je Cluster: sim gegen das vorige Label und dessen Veränderung
    sim: dict[int, float | None]
    delta: dict[int, float | None]
    schlagworte: dict[int, list[str]]
    titel: dict[int, str]


@dataclass
class Vorschlag:
    """Das Ergebnis eines Laufs."""

    kategorien: list[dict]          # name, description, keywords
    labels: np.ndarray
    eingefroren: list[int]
    runden: list[Runde] = field(default_factory=list)
    llm_calls: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    fruehzeitig_beendet: bool = False
    # Was schieflief, ohne den Lauf zu beenden: teilweise gelesene Antworten.
    # Eine leere Liste heißt, dass jede Runde vollständig gelesen wurde.
    warnungen: list[str] = field(default_factory=list)


# ── Bausteine ─────────────────────────────────────────────────────────────────

def nachbar_aggregat(embs: np.ndarray, texte: Sequence[str]) -> np.ndarray:
    """Kurze Segmente mit ihren Nachbarn mitteln — sonst tragen sie kein Signal."""
    angereichert = embs.copy()
    for i, text in enumerate(texte):
        if len(text) < SHORT_THRESHOLD:
            nachbarn = [embs[i]]
            if i > 0:
                nachbarn.append(embs[i - 1])
            if i < len(embs) - 1:
                nachbarn.append(embs[i + 1])
            v = np.mean(nachbarn, axis=0)
            angereichert[i] = v / max(float(np.linalg.norm(v)), 1e-9)
    return angereichert


def zentroide(embs: np.ndarray, labels: np.ndarray, n_clusters: int) -> np.ndarray:
    zent = np.zeros((n_clusters, embs.shape[1]), dtype=np.float32)
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            continue
        v = embs[idx].mean(axis=0)
        zent[cid] = v / max(float(np.linalg.norm(v)), 1e-9)
    return zent


def tfidf_schlagworte(
    texte: Sequence[str],
    labels: np.ndarray,
    n_clusters: int = N_CLUSTERS,
    top_k: int = TOP_K_KW,
) -> dict[int, list[str]]:
    """TF-IDF-Schlagworte je Cluster aus der aktuellen Zusammensetzung."""
    from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS as _EN_SW

    stopworte = STOPWORDS | set(_EN_SW) | STOPWORDS_EXTRA
    vec = TfidfVectorizer(
        max_features=8000, min_df=2, sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-ZäöüÄÖÜß]{3,}\b",
    )
    X = vec.fit_transform(list(texte))
    namen = vec.get_feature_names_out()
    ergebnis: dict[int, list[str]] = {}
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            ergebnis[cid] = []
            continue
        mittel = np.asarray(X[idx].mean(axis=0)).flatten()
        rang = mittel.argsort()[::-1]
        ergebnis[cid] = [namen[i] for i in rang
                         if namen[i].lower() not in stopworte][:top_k]
    return ergebnis


def kmeanspp_stichprobe(
    embs: np.ndarray, idx: np.ndarray, m: int, rng: np.random.Generator
) -> np.ndarray:
    """K-means++: m möglichst verschiedene Segmente aus einem Cluster."""
    if len(idx) <= m:
        return idx
    zentrum = embs[idx].mean(axis=0)
    norm = float(np.linalg.norm(zentrum))
    if norm > 1e-9:
        zentrum /= norm
    dists = np.linalg.norm(embs[idx] - zentrum, axis=1)
    gewaehlt = [int(dists.argmin())]
    min_quad = np.full(len(idx), np.inf)
    for _ in range(m - 1):
        letztes = embs[idx[gewaehlt[-1]]]
        d2 = np.sum((embs[idx] - letztes) ** 2, axis=1)
        min_quad = np.minimum(min_quad, d2)
        min_quad[np.array(gewaehlt)] = 0.0
        summe = min_quad.sum()
        if summe <= 1e-15:
            break
        neu = int(rng.choice(len(idx), p=min_quad / summe))
        gewaehlt.append(neu)
    return idx[np.array(gewaehlt, dtype=int)]


def baue_prompt(
    texte: Sequence[str],
    seg_embs: np.ndarray,
    labels: np.ndarray,
    schlagwort_map: dict[int, list[str]],
    vorherige_beschreibungen: Sequence[str | None],
    vorherige_runde: int | None,
    rng: np.random.Generator,
    n_clusters: int = N_CLUSTERS,
    m: int = N_SEGMENTS_PER_CLUSTER,
) -> str:
    """Der kontrastive Prompt über ALLE Gruppen, auch die eingefrorenen.

    Die eingefrorenen bleiben drin, damit die aktiven sich davon abgrenzen.
    """
    kw_zeilen = [
        f"Gruppe {cid+1} Keywords: {', '.join(schlagwort_map.get(cid, []))}"
        for cid in range(n_clusters)
    ]
    keyword_section = "\n".join(kw_zeilen)

    if any(d is not None for d in vorherige_beschreibungen):
        zeilen = "\n".join(
            f"Gruppe {cid+1}: {vorherige_beschreibungen[cid]}"
            if vorherige_beschreibungen[cid] else f"Gruppe {cid+1}: (keine)"
            for cid in range(n_clusters)
        )
        prev_section = f"\nVorherige Beschreibung (Iteration {vorherige_runde}):\n{zeilen}\n"
    else:
        prev_section = ""

    bloecke: list[str] = []
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            bloecke.append(f"--- Gruppe {cid+1} ---\n(Leer)")
            continue
        stichprobe = kmeanspp_stichprobe(seg_embs, idx, m, rng)
        snips = "\n\n".join(f"[{i+1}] {texte[j][:300]}" for i, j in enumerate(stichprobe))
        bloecke.append(f"--- Gruppe {cid+1} ---\n{snips}")

    return PROMPT_TEMPLATE.format(
        n=n_clusters,
        keyword_section=keyword_section,
        prev_section=prev_section,
        segment_section="\n\n".join(bloecke),
    )


# Die Kopfzeile einer Gruppe. Der Prompt verlangt '## Gruppe N', aber welche
# Auszeichnung ein Modell daraus macht, ist Geschmackssache seines Trainings:
# llama3.2:3b schreibt durchgehend '**Gruppe 1**', andere 'Gruppe 1:'. Alle drei
# meinen dasselbe, und an der Auszeichnung eine Antwort scheitern zu lassen, ist
# keine Strenge, sondern eine Verwechslung von Form und Inhalt.
#
# Was streng bleibt: die Zeile muss aus dem Kopf bestehen und aus nichts sonst.
# Sonst zerlegt ein 'Gruppe 1: die Texte …' mitten in einer Beschreibung die
# Antwort an der falschen Stelle. '## Gruppe 1: Titel' wird deshalb nicht
# gelesen — und das fällt jetzt auf, weil ein Lauf ohne gelesene Gruppe scheitert.
GRUPPENKOPF = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?\*{0,3}[ \t]*Gruppe[ \t]+(\d+)[ \t]*\*{0,3}[ \t]*:?[ \t]*$",
    re.MULTILINE,
)


class UnlesbareAntwort(ValueError):
    """Das Modell hat geantwortet, aber keine einzige Gruppe war darin zu finden.

    Kein Sonderfall von 'nichts hat sich geändert': wenn keine Gruppe gelesen
    wurde, behält der Kreislauf seinen Stand, embeddet nichts zurück und friert
    nichts ein — die nächste Runde bekommt denselben Prompt und scheitert
    genauso. Vier Aufrufe später steht dann ein Ergebnis da, das keines ist.
    Deshalb sofort und laut.
    """

    def __init__(self, runde: int, roh: str, auszug_zeichen: int = 800):
        self.runde = runde
        self.roh = roh
        auszug = roh.strip()[:auszug_zeichen]
        if len(roh.strip()) > auszug_zeichen:
            auszug += " …"
        super().__init__(
            f"In Runde {runde} war keine einzige Gruppe zu lesen. Erwartet wird je "
            f"Gruppe eine Zeile, die nur aus dem Kopf besteht: '## Gruppe N', "
            f"'**Gruppe N**' oder 'Gruppe N:'. Das Modell antwortete:\n{auszug}"
        )


def parse_antwort(roh: str, n_clusters: int = N_CLUSTERS) -> list[tuple[str, str] | None]:
    """'Gruppe N / Titel / Beschreibung' → [(titel, text), …] oder None.

    Fehlende Gruppen → None; das vorherige Label bleibt dann stehen. Erkannt
    werden alle drei Kopfformen aus GRUPPENKOPF.
    """
    ergebnis: list[tuple[str, str] | None] = [None] * n_clusters
    teile = GRUPPENKOPF.split(roh)
    i = 1
    while i + 1 < len(teile):
        try:
            idx = int(teile[i]) - 1
        except ValueError:
            i += 2
            continue
        zeilen = [z.strip() for z in teile[i + 1].splitlines() if z.strip()]
        if zeilen and 0 <= idx < n_clusters:
            ergebnis[idx] = (zeilen[0], " ".join(zeilen[1:]))
        i += 2
    return ergebnis


def soll_einfrieren(delta: float | None, schwelle: float = EARLY_STOP_DELTA) -> bool:
    """Die Abbruchregel je Cluster: bewegt sich die Beschreibung noch?

    Beim ersten Messwert gibt es kein Delta — dann wird nicht eingefroren.
    """
    return delta is not None and delta < schwelle


def zuordnen(seg_embs: np.ndarray, label_embs: np.ndarray) -> np.ndarray:
    """Jedes Segment an das ähnlichste Label — der Argmax über das Skalarprodukt."""
    return (seg_embs @ label_embs.T).argmax(axis=1)


# ── Der Kreislauf ─────────────────────────────────────────────────────────────

def verfeinern(
    seg_embs: np.ndarray,
    texte: Sequence[str],
    embed: Callable[[list[str]], np.ndarray],
    frage_modell: Callable[[str, str], tuple[str, int, int]],
    n_clusters: int = N_CLUSTERS,
    n_iter: int = N_ITER,
    m: int = N_SEGMENTS_PER_CLUSTER,
    km_interval: int = KM_INTERVAL,
    early_stop_delta: float = EARLY_STOP_DELTA,
    warm_start: Sequence[dict] | None = None,
    eingefroren_start: Sequence[int] | None = None,
) -> Vorschlag:
    """Der iterative Kreislauf, unverändert nach _run_tfidf_anchor.

    Je Runde:
      1. Segmente neu zuordnen
      2. TF-IDF-Schlagworte aus der aktuellen Zusammensetzung
      3. Ein kontrastiver LLM-Call über alle Cluster, auch die eingefrorenen
      4. Je Cluster sim(neu, alt) und delta = sim_neu − sim_vorher;
         delta < early_stop_delta → Cluster einfrieren
      5. Alle eingefroren → Ende

    n_iter ist der harte Sicherheitsstopp, nicht der Normalfall.

    embed        : Texte → normalisierte Embeddings
    frage_modell : (prompt, system) → (antwort, in_tokens, out_tokens)
    warm_start   : vorhandene Kategorien als Ausgangspunkt. cid ist die Position
                   in dieser Liste — die Zuordnung von Cluster zu Kategorie ist
                   damit festgelegt und nicht dem Zufall von KMeans überlassen.
    eingefroren_start : cids, die von Anfang an feststehen (die von Hand
                   gepflegten Kategorien). Sie wirken auf die Rechnung und
                   stehen im Prompt, werden aber nie umgeschrieben.

    Wirft UnlesbareAntwort, wenn in einer Runde keine einzige Gruppe zu lesen
    war. Teilweise gelesene Runden landen als Warnung im Vorschlag.
    """
    from sklearn.cluster import KMeans

    n_segs = len(texte)
    rng = np.random.default_rng(42)
    warnungen: list[str] = []

    if warm_start:
        # Warm heißt: von den vorhandenen Kategorien aus, nicht von einem
        # frischen KMeans. Vorher lief beides nebeneinander — die Beschreibung
        # der N-ten Kategorie ging als 'vorherige' in den Prompt für Gruppe N,
        # während Gruppe N das N-te KMeans-Cluster war, das damit nichts zu tun
        # hatte. Die Paarung war willkürlich, und deshalb verfeinerte
        # 'verfeinern' nichts. Jetzt sind die Kategorien selbst die Label, und
        # cid N ist Kategorie N.
        vt = list(warm_start)[:n_clusters]
        vorherige: list[str | None] = [c.get("description") or None for c in vt]
        zusammenfassungen: list[str] = [
            f"{c.get('name', '')}. {c.get('description', '')}"
            if c.get("description") else c.get("name") or f"Cluster {i+1}"
            for i, c in enumerate(vt)
        ]
        while len(vorherige) < n_clusters:
            vorherige.append(None)
        while len(zusammenfassungen) < n_clusters:
            zusammenfassungen.append(f"Cluster {len(zusammenfassungen)+1}")
        label_embs = np.asarray(embed(list(zusammenfassungen)), dtype=np.float32)
        labels = zuordnen(seg_embs, label_embs)
    else:
        labels = KMeans(n_clusters=n_clusters, random_state=42,
                        n_init="auto").fit_predict(seg_embs)
        label_embs = zentroide(seg_embs, labels, n_clusters)
        vorherige = [None] * n_clusters
        zusammenfassungen = [f"Cluster {i+1}" for i in range(n_clusters)]

    vorherige_llm_runde: int | None = None
    kw_map: dict[int, list[str]] = {}
    eingefroren: set[int] = set(eingefroren_start or ())
    von_anfang_fest = set(eingefroren)
    sim_verlauf: dict[int, list[float]] = {cid: [] for cid in range(n_clusters)}
    llm_calls = 0
    in_ges = 0
    out_ges = 0
    runden: list[Runde] = []
    frueh = len(eingefroren) >= n_clusters

    # Steht schon alles fest, gibt es nichts zu fragen. Ein Modellaufruf, dessen
    # Antwort ohnehin verworfen würde, ist kein Nulltarif.
    max_km_iter = 0 if frueh else n_iter * km_interval

    for km_iter in range(1, max_km_iter + 1):
        if km_iter % km_interval != 0:
            labels = zuordnen(seg_embs, label_embs)
            continue

        kw_map = tfidf_schlagworte(texte, labels, n_clusters=n_clusters)

        prompt = baue_prompt(texte, seg_embs, labels, kw_map,
                             vorherige, vorherige_llm_runde, rng,
                             n_clusters=n_clusters, m=m)
        roh, in_tok, out_tok = frage_modell(prompt, SYSTEM)
        geparst = parse_antwort(roh, n_clusters)
        llm_calls += 1
        in_ges += in_tok
        out_ges += out_tok

        gelesen = sum(1 for e in geparst if e is not None)
        if gelesen == 0:
            raise UnlesbareAntwort(km_iter // km_interval, roh)
        if gelesen < n_clusters:
            warnungen.append(
                f"Runde {km_iter // km_interval}: nur {gelesen} von {n_clusters} "
                f"Gruppen gelesen — die übrigen behalten ihre bisherige Beschreibung."
            )

        neue_zusammenfassungen = []
        for cid, eintrag in enumerate(geparst):
            if eintrag is None:
                neue_zusammenfassungen.append(zusammenfassungen[cid])
            else:
                t, b = eintrag
                neue_zusammenfassungen.append(f"{t}. {b}" if b else t)

        schon_eingefroren = set(eingefroren)

        # Nur aktive Cluster mit gültiger Antwort werden zurück-embeddet
        zu_embedden = [cid for cid in range(n_clusters)
                       if cid not in schon_eingefroren and geparst[cid] is not None]
        if zu_embedden:
            ergebnisse = embed([neue_zusammenfassungen[cid] for cid in zu_embedden])
            emb_map = dict(zip(zu_embedden, ergebnisse))
        else:
            emb_map = {}

        neu_eingefroren: list[int] = []
        sim_je_cluster: dict[int, float | None] = {}
        delta_je_cluster: dict[int, float | None] = {}

        for cid in range(n_clusters):
            if cid in schon_eingefroren or cid not in emb_map:
                sim_je_cluster[cid] = None
                delta_je_cluster[cid] = None
                continue

            neues_emb = emb_map[cid]
            sim = float(label_embs[cid] @ neues_emb)
            sim_verlauf[cid].append(sim)
            delta = (sim_verlauf[cid][-1] - sim_verlauf[cid][-2]
                     if len(sim_verlauf[cid]) >= 2 else None)

            # Der Rückweg: das Embedding der Beschreibung ersetzt das Zentroid
            label_embs[cid] = neues_emb
            vorherige[cid] = geparst[cid][1] if geparst[cid][1] else geparst[cid][0]
            zusammenfassungen[cid] = neue_zusammenfassungen[cid]

            sim_je_cluster[cid] = sim
            delta_je_cluster[cid] = delta
            if soll_einfrieren(delta, early_stop_delta):
                eingefroren.add(cid)
                neu_eingefroren.append(cid)

        neue_labels = zuordnen(seg_embs, label_embs)
        gewechselt = int((neue_labels != labels).sum())
        labels = neue_labels

        runden.append(Runde(
            km_iter=km_iter,
            llm_runde=km_iter // km_interval,
            aenderungsanteil=gewechselt / n_segs if n_segs else 0.0,
            eingefroren_gesamt=len(eingefroren),
            neu_eingefroren=neu_eingefroren[:],
            sim=sim_je_cluster,
            delta=delta_je_cluster,
            schlagworte={k: v[:] for k, v in kw_map.items()},
            titel={cid: (geparst[cid][0] if geparst[cid] else zusammenfassungen[cid])
                   for cid in range(n_clusters)},
        ))
        vorherige_llm_runde = km_iter

        if len(eingefroren) == n_clusters:
            frueh = True
            break

    kategorien = []
    for cid in range(n_clusters):
        if cid in von_anfang_fest:
            # Wörtlich zurückgeben, nicht aus der Zusammenfassung rekonstruieren:
            # das Zerlegen am ersten '. ' würde einen Namen zerschneiden, der
            # selbst einen Punkt enthält. Was ein Mensch geschrieben hat, geht
            # hier unangetastet durch.
            vorlage = list(warm_start)[cid]
            kategorien.append({
                "name": vorlage.get("name", ""),
                "description": vorlage.get("description", ""),
                "keywords": list(vorlage.get("keywords") or []),
            })
            continue
        z = zusammenfassungen[cid]
        titel, text = (z.split(". ", 1) if ". " in z else (z, ""))
        kategorien.append({
            "name": titel.strip(),
            "description": text.strip(),
            "keywords": kw_map.get(cid, [])[:3],
        })

    return Vorschlag(
        kategorien=kategorien,
        labels=labels,
        eingefroren=sorted(eingefroren),
        runden=runden,
        llm_calls=llm_calls,
        in_tokens=in_ges,
        out_tokens=out_ges,
        fruehzeitig_beendet=frueh,
        warnungen=warnungen,
    )
