"""
entity_gliner.py — NER-Extraktion via GLiNER für mehrsprachige historische Texte.

Modell:  urchade/gliner_multi  (multilingual, läuft lokal ohne GPU)
Labels:  GLINER_LABELS aus config.py  (verfeinerte Kategorien)
Threshold: GLINER_THRESHOLD (default 0.7)

Pipeline:
  Phase 1: GLiNER-Erkennung pro Segment (chunked, mit Modell-Cache)
  Phase 2: _normalize_entity() + Seed-Normalisierung + Lowercase-Filter
  Phase 3: _merge() — programmatische Dedup
  Phase 4: Embedding-Clustering (θ=EMB_THRESHOLD) — Sprachvarianten zusammenführen

Kein LLM im GLiNER-Pfad. Schnittstelle identisch zu entity_spacy.extract_with_spacy().
"""

import sys
import time
from collections import Counter, defaultdict

from src.generalized.config import (
    GLINER_LABELS,
    GLINER_MAX_CHARS,
    GLINER_MODEL,
    GLINER_THRESHOLD,
)
from src.generalized.entity_utils import _merge, _normalize_entity

# Threshold für Embedding-Clustering (Cosine-Similarity)
# 0.92 trifft sicher Duplikate + Sprachvarianten, vermeidet semantisch
# verschiedene Entities (getestet auf damaskus_test_2, 2026-05-04)
EMB_THRESHOLD = 0.92

# Label-Mapping: verfeinerte GLiNER-Labels → VALID_TYPES
_LABEL_TO_TYPE: dict[str, str] = {
    "Person":                             "Person",
    "Organisation":                       "Organisation",
    "geographischer Ort":                 "Ort",
    "politische Bewegung":                "Organisation",
    "religiöse Institution":              "Organisation",
    "Zeitung oder Publikation":           "Organisation",
    "politische Bewegung oder Ideologie": "Konzept",
    "religiöse Strömung oder Konzept":    "Konzept",
}

# Modell-Cache: einmal laden, für alle Aufrufe wiederverwenden
_gliner_model      = None
_gliner_model_name: str | None = None


def _load_gliner(model_name: str):
    global _gliner_model, _gliner_model_name
    if _gliner_model is not None and _gliner_model_name == model_name:
        return _gliner_model
    try:
        from gliner import GLiNER
    except ImportError:
        print("FEHLER: gliner nicht installiert.\n  pip install gliner", file=sys.stderr)
        raise
    print(f"GLiNER: {model_name} wird geladen …")
    _gliner_model      = GLiNER.from_pretrained(model_name)
    _gliner_model_name = model_name
    print("GLiNER: Modell geladen")
    return _gliner_model



def _chunk(text: str, max_chars: int = GLINER_MAX_CHARS) -> list[str]:
    """Teilt Text an Satzgrenzen in Stücke à max_chars Zeichen."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        split = text.rfind(". ", 0, max_chars)
        split = (split + 1) if split != -1 else max_chars
        chunks.append(text[:split].strip())
        text = text[split:].strip()
    return [c for c in chunks if c]


def _build_alias_map(seed: list[dict]) -> dict[str, str]:
    """Baut eine lowercase-Alias → Normalform-Map aus dem Seed.

    Wird genutzt um GLiNER-Kurzformen (z.B. "Enver") auf den vollständigen
    Seed-Namen ("Ismail Enver") zu normalisieren bevor _merge() läuft.
    """
    alias_map: dict[str, str] = {}
    for e in seed:
        full = e.get("normalform") or ""
        if not full:
            continue
        alias_map[full.lower()] = full
        for a in e.get("aliases", []):
            if a:
                alias_map[a.lower()] = full
    return alias_map


def _embedding_cluster(entities: list[dict], threshold: float) -> list[dict]:
    """Führt Embedding-basiertes Clustering via Union-Find durch.

    Mergt Entities deren Cosine-Similarity >= threshold ist.
    Normalform: vollständigste (meiste Wörter, bei Gleichstand längster String).
    Aliases: alle Varianten aus dem Cluster.
    Typ: Mehrheitsvoting.
    Score: Maximum aus dem Cluster.
    """
    import numpy as np
    from src.generalized.embeddings import EMB_TASK_CLUSTER, get_embedding_provider

    texts = [e.get("normalform", "") for e in entities]
    embs  = get_embedding_provider(EMB_TASK_CLUSTER).encode(texts)

    n      = len(entities)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sim = embs @ embs.T
    for i in range(n):
        for j in range(i + 1, n):
            if float(sim[i, j]) >= threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    result: list[dict] = []
    for root, indices in groups.items():
        cluster = [entities[i] for i in indices]
        best    = max(cluster, key=lambda e: (
            len(e.get("normalform", "").split()),
            len(e.get("normalform", "")),
        ))
        all_aliases: set[str] = set()
        for e in cluster:
            if e.get("normalform") != best["normalform"]:
                all_aliases.add(e["normalform"])
            all_aliases.update(e.get("aliases", []))
        all_aliases.discard(best["normalform"])
        typ   = Counter(e.get("typ", "Konzept") for e in cluster).most_common(1)[0][0]
        scores = [e.get("score") for e in cluster if e.get("score") is not None]
        score  = max(scores) if scores else None
        result.append({
            "normalform": best["normalform"],
            "typ":        typ,
            "aliases":    sorted(all_aliases),
            "score":      score,
        })
    return result


def extract_with_gliner(
    segments: list[dict],
    rejected_lc: set[str],
    seed: list[dict] = (),
) -> list[dict]:
    """Extrahiert Entities aus Segmenten via GLiNER NER.

    seed wird für Alias→Vollname-Normalisierung genutzt.
    Gibt eine deduplizierte Entity-Liste im Standard-Format zurück.
    """
    t_total = time.perf_counter()

    model     = _load_gliner(GLINER_MODEL)
    alias_map = _build_alias_map(seed)

    def _skip(s: dict) -> bool:
        if s.get("item_type") == "videoRecording":
            return True
        if s.get("item_type") is None and len(s.get("text", "")) > 20_000:
            return True
        return False

    content_segs  = [s for s in segments if s.get("type") == "content" and not _skip(s)]
    skipped_video = sum(1 for s in segments
                        if s.get("type") == "content"
                        and s.get("item_type") == "videoRecording")
    skipped_long  = sum(1 for s in segments
                        if s.get("type") == "content"
                        and s.get("item_type") is None
                        and len(s.get("text", "")) > 20_000)
    if skipped_video:
        print(f"  {skipped_video} videoRecording-Segment(e) übersprungen")
    if skipped_long:
        print(f"  {skipped_long} Segment(e) übersprungen (kein item_type, >20k Zeichen)")
    print(f"GLiNER NER: {len(content_segs)} Segmente  (θ={GLINER_THRESHOLD}) …")

    # ── Phase 1+2: GLiNER-Erkennung, Filter, Seed-Normalisierung ─────────────
    t1 = time.perf_counter()
    raw_entities: list[dict] = []

    for seg in content_segs:
        text = seg.get("text", "")
        if not text:
            continue
        for chunk in _chunk(text):
            try:
                entities = model.predict_entities(
                    chunk, GLINER_LABELS, threshold=GLINER_THRESHOLD
                )
            except Exception as exc:
                print(
                    f"  WARNING: GLiNER Fehler in Segment "
                    f"{seg.get('segment_id', '?')}: {exc}",
                    file=sys.stderr,
                )
                continue
            for ent in entities:
                typ  = _LABEL_TO_TYPE.get(ent["label"], "Konzept")
                norm = ent["text"].strip()
                if not norm:
                    continue
                # Lowercase-Filter: reine Kleinbuchstaben unter 5 Zeichen
                if norm == norm.lower() and len(norm) < 5:
                    continue
                # Seed-Normalisierung: Kurzform → Vollname
                full = alias_map.get(norm.lower())
                if full and full != norm:
                    norm = full
                n = _normalize_entity(
                    {"normalform": norm, "typ": typ, "aliases": [],
                     "score": round(ent["score"], 3)},
                    "gliner", rejected_lc,
                )
                if n is not None:
                    raw_entities.append(n)

    t_gliner = time.perf_counter() - t1
    print(f"  {len(raw_entities)} Roh-Entities  [{t_gliner:.1f}s]")

    # ── Phase 3: _merge() — programmatische Dedup ────────────────────────────
    t3      = time.perf_counter()
    deduped = _merge([raw_entities])
    t_merge = time.perf_counter() - t3
    print(f"  {len(deduped)} nach _merge()  [{t_merge:.2f}s]")

    # ── Phase 4: Embedding-Clustering (ersetzt _llm_group) ───────────────────
    t4 = time.perf_counter()
    if deduped:
        clustered = _embedding_cluster(deduped, EMB_THRESHOLD)
    else:
        clustered = []
    t_emb = time.perf_counter() - t4
    print(f"  {len(clustered)} nach Embedding-Clustering θ={EMB_THRESHOLD}  [{t_emb:.1f}s]")

    t_total_elapsed = time.perf_counter() - t_total
    print(f"  Gesamt: {len(clustered)} Entities  [{t_total_elapsed:.1f}s]")
    return clustered
