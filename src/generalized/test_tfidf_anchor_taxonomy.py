"""
test_tfidf_anchor_taxonomy.py — S6-tfidf-anchor standalone

TF-IDF-Keywords pro Iteration + rolling context + per-Cluster Early Stopping.
Provider konfigurierbar: Anthropic (mit Token-Tracking) oder Ollama (lokal).

Ergebnis (Benchmark 2026-05-06, Anthropic Haiku):
  Ø Delta +0.1403  |  IntraSim 0.5067  |  Stab 0.91  |  $0.0356 (4 Calls)
  Synergieeffekt: TF-IDF + rolling context superadditiv (+0.0254 über Summe beider allein)
"""

import json
import re
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from src.generalized.config import ROOT

load_dotenv()

# ── Konfiguration ──────────────────────────────────────────────────────────────

SEGMENTS_PATH   = Path("data/projects/ber/documents/main/segments.json")
CACHE_PATH      = Path("/tmp/ber_bge_embeddings.npy")

N_CLUSTERS               = 7
N_ITER                   = 4       # LLM-Calls (alle km_interval k-means-Schritte)
N_SEGMENTS_PER_CLUSTER   = 10      # k-means++ sample size pro Cluster
PROVIDER                 = "anthropic"          # "anthropic" oder "ollama"
MODEL_ANTHROPIC          = "claude-haiku-4-5-20251001"
MODEL_OLLAMA             = "llama3.2:3b"

KM_INTERVAL     = 5     # k-means-Schritte zwischen LLM-Calls
MIN_LENGTH      = 30
SEG_CHARS       = 500
SHORT_THRESHOLD = 100
TOP_K_KW        = 8

_STOPWORDS = {
    "der", "die", "das", "und", "in", "von", "zu", "den", "mit", "ist", "im",
    "dem", "des", "ein", "eine", "sich", "auch", "auf", "an", "für", "es",
    "als", "bei", "aber", "oder", "aus", "hat", "nicht", "wird", "war",
    "waren", "dass", "wenn", "nach", "durch", "um", "so", "wie",
    "über", "bis", "dann", "diese", "dieser", "diesem", "diesen", "dieses",
    "er", "sie", "wir", "ihre", "ihrer", "ihren", "ihrem", "ihres",
    "sein", "seiner", "seinem", "seinen", "seine", "eines", "einem", "einen",
    "werden", "haben", "noch", "mehr", "nur", "schon", "sehr", "hier", "da",
    "beim", "am", "zum", "zur", "tsp", "januar", "februar", "märz", "april",
    "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember",
}

_ANTHROPIC_PRICES = {
    "claude-haiku-4-5-20251001":  (0.80,  4.00),
    "claude-sonnet-4-20250514":   (3.00,  15.00),
    "claude-sonnet-4-6":          (3.00,  15.00),
    "claude-opus-4-7":            (15.00, 75.00),
}

_OLLAMA_BASE_URL    = "http://localhost:11434"
_anthropic_client   = None   # lazy-initialisiert beim ersten LLM-Call

EARLY_STOP_DELTA = 0.01   # Cluster einfrieren wenn sim-Verbesserung < 1%

_SYSTEM = (
    "Du analysierst Gruppen von Texten über den Berliner Flughafen BER. "
    "Schreibe präzise, kontrastierende Beschreibungen — kein allgemeines Intro, keine Floskeln."
)

_PROMPT_TEMPLATE = """\
Du analysierst {n} Gruppen von Texten über den Berliner Flughafen BER.

Für jede Gruppe sind folgende Keywords konstant charakteristisch \
(diese sollen in deiner Beschreibung vorkommen):

{keyword_section}
{prev_section}
Neue Beispieltexte:
{segment_section}

Verfeinere die Beschreibungen unter Einbeziehung der Keywords und Beispieltexte. \
Jede Gruppe muss sich klar von den anderen unterscheiden.

Antworte für jede Gruppe im Format (kein weiterer Text):

## Gruppe 1: [2-4 Wörter Titel]
[2-3 Sätze Beschreibung die die Keywords einschließt]

## Gruppe 2: ...
"""

# ── Datenladen ────────────────────────────────────────────────────────────────

def load_segments() -> tuple[list[str], list[str]]:
    segs    = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
    content = [s for s in segs
               if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH]
    content.sort(key=lambda s: s.get("segment_id", ""))
    return [s["text"][:SEG_CHARS] for s in content], [s.get("segment_id", "?") for s in content]


# ── Embedding-Helpers ─────────────────────────────────────────────────────────

def _load_bge():
    from FlagEmbedding import BGEM3FlagModel
    print("  Lade BGE-M3…", flush=True)
    return BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)


def _compute_segment_embeddings(bge, texts: list[str]) -> np.ndarray:
    if CACHE_PATH.exists():
        cached = np.load(CACHE_PATH)
        if cached.shape[0] == len(texts):
            print(f"  Embeddings aus Cache ({cached.shape})", flush=True)
            return cached
    t0  = time.perf_counter()
    raw = bge.encode(texts, batch_size=32, max_length=512,
                     return_dense=True, return_sparse=False,
                     return_colbert_vecs=False)["dense_vecs"]
    embs  = np.array(raw, dtype=np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs /= np.maximum(norms, 1e-9)
    np.save(CACHE_PATH, embs)
    print(f"  Embeddings: {embs.shape}  [{time.perf_counter()-t0:.1f}s]")
    return embs


def _embed_texts(bge, texts: list[str]) -> np.ndarray:
    raw  = bge.encode(texts, batch_size=16, max_length=512,
                      return_dense=True, return_sparse=False,
                      return_colbert_vecs=False)["dense_vecs"]
    embs = np.array(raw, dtype=np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    return embs / np.maximum(norms, 1e-9)


def _neighbor_aggregate(embs: np.ndarray, texts: list[str]) -> np.ndarray:
    enriched = embs.copy()
    for i, text in enumerate(texts):
        if len(text) < SHORT_THRESHOLD:
            neighbors = [embs[i]]
            if i > 0:
                neighbors.append(embs[i - 1])
            if i < len(embs) - 1:
                neighbors.append(embs[i + 1])
            v = np.mean(neighbors, axis=0)
            enriched[i] = v / max(float(np.linalg.norm(v)), 1e-9)
    return enriched


def _compute_centroids(embs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    n_clusters = int(labels.max()) + 1
    centroids  = np.zeros((n_clusters, embs.shape[1]), dtype=np.float32)
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            continue
        v = embs[idx].mean(axis=0)
        centroids[cid] = v / max(float(np.linalg.norm(v)), 1e-9)
    return centroids


# ── Algorithmus-Bausteine ─────────────────────────────────────────────────────

def _compute_tfidf_keywords(
    texts: list[str],
    labels: np.ndarray,
    n_clusters: int = N_CLUSTERS,
    top_k: int = TOP_K_KW,
) -> dict[int, list[str]]:
    """TF-IDF-Keywords pro Cluster aus aktueller Segment-Zusammensetzung."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(
        max_features=8000, min_df=2, sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-ZäöüÄÖÜß]{3,}\b",
    )
    X     = vec.fit_transform(texts)
    names = vec.get_feature_names_out()
    result: dict[int, list[str]] = {}
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            result[cid] = []
            continue
        mean_scores = np.asarray(X[idx].mean(axis=0)).flatten()
        ranked      = mean_scores.argsort()[::-1]
        result[cid] = [names[i] for i in ranked
                       if names[i].lower() not in _STOPWORDS][:top_k]
    return result


def _kmeanspp_sample(
    embs: np.ndarray, idx: np.ndarray, m: int, rng: np.random.Generator
) -> np.ndarray:
    """K-means++ sampling: m diverse Segmente aus Cluster idx."""
    if len(idx) <= m:
        return idx
    centroid = embs[idx].mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm > 1e-9:
        centroid /= norm
    dists    = np.linalg.norm(embs[idx] - centroid, axis=1)
    selected = [int(dists.argmin())]
    min_sq_dists = np.full(len(idx), np.inf)
    for _ in range(m - 1):
        last_emb = embs[idx[selected[-1]]]
        d2       = np.sum((embs[idx] - last_emb) ** 2, axis=1)
        min_sq_dists = np.minimum(min_sq_dists, d2)
        min_sq_dists[np.array(selected)] = 0.0
        total = min_sq_dists.sum()
        if total <= 1e-15:
            break
        new_pos = int(rng.choice(len(idx), p=min_sq_dists / total))
        selected.append(new_pos)
    return idx[np.array(selected, dtype=int)]


def _build_prompt(
    texts: list[str],
    seg_embs: np.ndarray,
    labels: np.ndarray,
    keyword_map: dict[int, list[str]],
    prev_descriptions: list[str | None],
    prev_iter: int | None,
    rng: np.random.Generator,
    n_clusters: int = N_CLUSTERS,
    m: int = N_SEGMENTS_PER_CLUSTER,
) -> str:
    """Baut den kombinierten Prompt für einen Iterations-Call."""
    keyword_section = "\n".join(
        f"Gruppe {cid+1} Keywords: {', '.join(keyword_map.get(cid, []))}"
        for cid in range(n_clusters)
    )

    if any(d is not None for d in prev_descriptions):
        prev_lines = "\n".join(
            f"Gruppe {cid+1}: {prev_descriptions[cid]}" if prev_descriptions[cid]
            else f"Gruppe {cid+1}: (keine)"
            for cid in range(n_clusters)
        )
        prev_section = (
            f"\nVorherige Beschreibungen (Iteration {prev_iter}):\n{prev_lines}\n"
        )
    else:
        prev_section = ""

    seg_blocks: list[str] = []
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            seg_blocks.append(f"--- Gruppe {cid+1} ---\n(Leer)")
            continue
        sample_idx = _kmeanspp_sample(seg_embs, idx, m, rng)
        snips = "\n\n".join(
            f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(sample_idx)
        )
        seg_blocks.append(f"--- Gruppe {cid+1} ---\n{snips}")

    return _PROMPT_TEMPLATE.format(
        n=n_clusters,
        keyword_section=keyword_section,
        prev_section=prev_section,
        segment_section="\n\n".join(seg_blocks),
    )


def _parse_llm_response(raw: str, n_clusters: int = N_CLUSTERS) -> list[tuple[str, str]]:
    """Parst '## Gruppe N: Titel\\nBeschreibung' → [(title, body), ...]."""
    results = [("", f"Gruppe {i+1}") for i in range(n_clusters)]
    pattern = re.compile(r"^##\s*Gruppe\s+(\d+)\s*[:\-–—]?\s*(.+?)$", re.MULTILINE)
    matches = list(pattern.finditer(raw))
    for k, m in enumerate(matches):
        idx   = int(m.group(1)) - 1
        title = m.group(2).strip()
        end   = matches[k + 1].start() if k + 1 < len(matches) else len(raw)
        body  = raw[m.end():end].strip().replace("\n", " ")
        if 0 <= idx < n_clusters:
            results[idx] = (title, body)
    return results


def _llm_call(prompt: str, system: str = _SYSTEM) -> tuple[str, int, int]:
    """Unified LLM-Call — dispatcht nach PROVIDER-Konfiguration.

    Gibt (text, input_tokens, output_tokens) zurück.
    Ollama: (text, 0, 0) — kein Token-Tracking.
    """
    global _anthropic_client
    if PROVIDER == "anthropic":
        if _anthropic_client is None:
            import anthropic
            _anthropic_client = anthropic.Anthropic()
        kwargs: dict = dict(
            model=MODEL_ANTHROPIC,
            max_tokens=2048,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        msg = _anthropic_client.messages.create(**kwargs)
        return msg.content[0].text.strip(), msg.usage.input_tokens, msg.usage.output_tokens
    elif PROVIDER == "ollama":
        import requests as _req
        payload: dict = {
            "model": MODEL_OLLAMA, "prompt": prompt, "stream": False,
            "options": {"num_ctx": 8192, "temperature": 0},
        }
        if system:
            payload["system"] = system
        r = _req.post(f"{_OLLAMA_BASE_URL}/api/generate", json=payload, timeout=300)
        r.raise_for_status()
        return r.json().get("response", "").strip(), 0, 0
    else:
        raise ValueError(f"Unbekannter PROVIDER: {PROVIDER!r}  (erwartet: 'anthropic' oder 'ollama')")


# ── Hauptalgorithmus ──────────────────────────────────────────────────────────

def _keyword_diff(prev: list[str], curr: list[str]) -> str:
    """'+new −gone' diff-String zwischen zwei Keyword-Listen."""
    prev_set = set(prev)
    curr_set = set(curr)
    added   = [f"+{w}" for w in curr if w not in prev_set]
    removed = [f"−{w}" for w in prev if w not in curr_set]
    parts   = added + removed
    return ("  [" + "  ".join(parts) + "]") if parts else ""


def _run_tfidf_anchor(
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    n_clusters: int = N_CLUSTERS,
    n_iter: int = N_ITER,
    m: int = N_SEGMENTS_PER_CLUSTER,
    km_interval: int = KM_INTERVAL,
    early_stop_delta: float = EARLY_STOP_DELTA,
) -> dict:
    """S6-tfidf-anchor — rolling context + TF-IDF-Keywords + per-Cluster Early Stopping.

    Pro Iteration:
      1. Segmente neu zuordnen
      2. TF-IDF-Keywords aus aktueller Cluster-Zusammensetzung berechnen
      3. Kontrastiver LLM-Call (alle Cluster, auch eingefrorene, für Kontrast)
      4. Pro Cluster: sim(neu, alt) berechnen; delta = sim_neu - sim_vorherig
         → wenn delta < early_stop_delta: Cluster einfrieren (letztes Label beibehalten)
      5. Wenn alle Cluster eingefroren: Early Stopping

    N_ITER bleibt als harter Sicherheitsstopp.
    """
    from sklearn.cluster import KMeans

    t0     = time.perf_counter()
    n_segs = len(texts)
    rng    = np.random.default_rng(42)

    labels     = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto").fit_predict(seg_embs)
    label_embs = _compute_centroids(seg_embs, labels)

    prev_descs: list[str | None]              = [None] * n_clusters
    summaries: list[str]                      = [f"Cluster {i+1}" for i in range(n_clusters)]
    prev_kw_map: dict[int, list[str]] | None  = None
    prev_llm_iter: int | None                 = None
    kw_map: dict[int, list[str]]              = {}
    frozen: set[int]                          = set()
    sim_history: dict[int, list[float]]       = {cid: [] for cid in range(n_clusters)}
    llm_calls = 0
    total_in  = 0
    total_out = 0
    logs: list[dict] = []

    max_km_iter = n_iter * km_interval

    for km_iter in range(1, max_km_iter + 1):
        if km_iter % km_interval != 0:
            labels = (seg_embs @ label_embs.T).argmax(axis=1)
            continue

        kw_map = _compute_tfidf_keywords(texts, labels, n_clusters=n_clusters)

        prompt = _build_prompt(
            texts, seg_embs, labels, kw_map,
            prev_descs, prev_llm_iter, rng,
            n_clusters=n_clusters, m=m,
        )
        raw, in_tok, out_tok = _llm_call(prompt)
        parsed = _parse_llm_response(raw, n_clusters)
        llm_calls += 1
        total_in  += in_tok
        total_out += out_tok

        new_summaries  = [f"{t}. {b}" if b else t for t, b in parsed]
        all_new_embs   = _embed_texts(bge, new_summaries)

        already_frozen = set(frozen)   # snapshot before this iteration's updates
        newly_frozen: list[int] = []
        stab_info: list[dict]  = []

        for cid in range(n_clusters):
            if cid in already_frozen:
                stab_info.append({"cid": cid, "sim": None, "delta": None, "new_freeze": False})
                continue

            new_emb = all_new_embs[cid]
            sim     = float(label_embs[cid] @ new_emb)
            sim_history[cid].append(sim)
            delta: float | None = (
                sim_history[cid][-1] - sim_history[cid][-2]
                if len(sim_history[cid]) >= 2 else None
            )

            # Apply LLM output (last computed label becomes the frozen label if freeze fires)
            label_embs[cid] = new_emb
            prev_descs[cid] = parsed[cid][1] if parsed[cid][1] else parsed[cid][0]
            summaries[cid]  = new_summaries[cid]

            new_freeze = (delta is not None and delta < early_stop_delta)
            if new_freeze:
                frozen.add(cid)
                newly_frozen.append(cid)

            stab_info.append({"cid": cid, "sim": sim, "delta": delta, "new_freeze": new_freeze})

        new_labels = (seg_embs @ label_embs.T).argmax(axis=1)
        changed    = int((new_labels != labels).sum())
        change_pct = changed / n_segs
        labels     = new_labels

        dist_str = "  ".join(f"C{i+1}={int((labels==i).sum())}" for i in range(n_clusters))
        n_frozen  = len(frozen)
        n_active  = n_clusters - n_frozen

        # ── Ausgabe ───────────────────────────────────────────────────────────
        W = 72
        print(f"\n{'═'*W}", flush=True)
        print(f"  ═══ {km_iter // km_interval}/{n_iter} | Iter {km_iter}  "
              f"│  Aktiv: {n_active}/{n_clusters}  Eingefroren: {n_frozen}/{n_clusters} ═══",
              flush=True)
        print(f"  Wechsel={change_pct*100:.1f}%  │  {dist_str}", flush=True)
        print(f"{'═'*W}", flush=True)

        print(f"\n  Keywords (Iter {km_iter}):", flush=True)
        for cid in range(n_clusters):
            kws      = kw_map.get(cid, [])
            diff_str = _keyword_diff(prev_kw_map.get(cid, []), kws) if prev_kw_map else ""
            print(f"  C{cid+1}: {', '.join(kws)}{diff_str}", flush=True)

        print(f"\n  Label-Stabilität:", flush=True)
        for info in stab_info:
            cid = info["cid"]
            if info["sim"] is None:
                print(f"  C{cid+1}: ❄  (bereits eingefroren)", flush=True)
            else:
                sim_str   = f"sim={info['sim']:.4f}"
                delta_str = (f"  Δ={info['delta']:+.4f}" if info["delta"] is not None
                             else "  (erste Messung)")
                freeze_str = "  → ❄ EINGEFROREN" if info["new_freeze"] else ""
                print(f"  C{cid+1}: {sim_str}{delta_str}{freeze_str}", flush=True)

        for cid, (title, body) in enumerate(parsed):
            if cid in already_frozen:
                tag = "  [❄]"
            elif cid in newly_frozen:
                tag = "  [❄ jetzt eingefroren]"
            else:
                tag = ""
            print(f"\nC{cid+1}: {title}{tag}", flush=True)
            print(f'  "{body}"', flush=True)

        logs.append({
            "km_iter":      km_iter,
            "summaries":    summaries[:],
            "parsed":       parsed[:],
            "kw_map":       {k: v[:] for k, v in kw_map.items()},
            "stab_info":    stab_info,
            "newly_frozen": newly_frozen[:],
            "n_frozen":     n_frozen,
            "change_pct":   change_pct,
        })
        prev_kw_map   = kw_map
        prev_llm_iter = km_iter

        if len(frozen) == n_clusters:
            print(f"\n  Alle {n_clusters} Cluster eingefroren — Early Stopping nach Iter {km_iter}.",
                  flush=True)
            break

    if PROVIDER == "anthropic":
        model       = MODEL_ANTHROPIC
        p_in, p_out = _ANTHROPIC_PRICES.get(model, (3.00, 15.00))
        cost_usd    = total_in * p_in / 1_000_000 + total_out * p_out / 1_000_000
    else:
        model    = MODEL_OLLAMA
        cost_usd = 0.0

    centroids = _compute_centroids(seg_embs, labels)
    return {
        "labels":         labels,
        "label_embs":     label_embs,
        "centroids":      centroids,
        "summaries":      summaries,
        "kw_map":         kw_map,
        "frozen":         sorted(frozen),
        "iteration_logs": logs,
        "llm_calls":      llm_calls,
        "in_tokens":      total_in,
        "out_tokens":     total_out,
        "cost_usd":       cost_usd,
        "elapsed":        time.perf_counter() - t0,
        "model":          model,
    }


# ── Metriken & Ausgabe ────────────────────────────────────────────────────────

def _eval(result: dict, seg_embs: np.ndarray) -> dict:
    label_embs = result["label_embs"]
    centroids  = result["centroids"]
    labels     = result["labels"]
    n          = label_embs.shape[0]
    sim_matrix = label_embs @ centroids.T

    deltas: list[float] = []
    for i in range(n):
        sim_own = float(sim_matrix[i, i])
        others  = [float(sim_matrix[i, j]) for j in range(n) if j != i]
        deltas.append(sim_own - (max(others) if others else 0.0))

    sizes = [int((labels == cid).sum()) for cid in range(n)]
    intra_scores: list[float] = []
    for cid in range(n):
        idx = np.where(labels == cid)[0]
        if len(idx) < 2:
            intra_scores.append(1.0 if len(idx) == 1 else 0.0)
            continue
        sub = seg_embs[idx]
        mat = sub @ sub.T
        k   = len(idx)
        mask = np.triu(np.ones((k, k), dtype=bool), k=1)
        intra_scores.append(float(mat[mask].mean()))

    total     = sum(sizes)
    intra_avg = sum(intra_scores[c] * sizes[c] for c in range(n)) / total if total else 0.0

    result["deltas"]    = deltas
    result["avg_delta"] = float(np.mean(deltas))
    result["intra_avg"] = intra_avg
    return result


def _print_final_table(result: dict) -> None:
    label_embs = result["label_embs"]
    centroids  = result["centroids"]
    summaries  = result["summaries"]
    kw_map     = result["kw_map"]
    labels     = result["labels"]
    n          = label_embs.shape[0]
    sim_matrix = label_embs @ centroids.T

    SEP  = "─" * 80
    print(f"\n{'═'*80}")
    print(f"  Finale Labels ({result['llm_calls']} Calls, ${result['cost_usd']:.4f}, "
          f"{result['elapsed']:.1f}s)")
    print(f"{'═'*80}")
    print(f"\n  {'C':3}  {'Sim_own':>7}  {'Best_other':>10}  {'Delta':>7}  "
          f"{'IntraSim':>8}  {'Seg':>4}  Label")
    print(f"  {'─'*3}  {'─'*7}  {'─'*10}  {'─'*7}  {'─'*8}  {'─'*4}  {'─'*40}")
    for i in range(n):
        sim_own  = float(sim_matrix[i, i])
        others   = [float(sim_matrix[i, j]) for j in range(n) if j != i]
        delta    = sim_own - (max(others) if others else 0.0)
        seg_ct   = int((labels == i).sum())
        intra    = result.get("intra_avg", 0.0)
        label    = summaries[i][:55]
        print(f"  C{i+1:<2}  {sim_own:7.4f}  {max(others) if others else 0:10.4f}  "
              f"{delta:7.4f}  {'—':>8}  {seg_ct:4d}  {label}")

    print(f"\n  {SEP}")
    print(f"  Ø Delta   = {result['avg_delta']:+.4f}")
    print(f"  IntraSim  = {result['intra_avg']:.4f}")
    print(f"  Tokens    = {result['in_tokens']:,} in  +  {result['out_tokens']:,} out")
    print(f"  Kosten    = ${result['cost_usd']:.4f}  ({result['model']})")
    print(f"  Laufzeit  = {result['elapsed']:.1f}s")

    print(f"\n  {'─'*80}")
    print(f"  Cluster-Details:\n")
    for i in range(n):
        title, body = "", summaries[i]
        logs = result.get("iteration_logs", [])
        if logs:
            parsed = logs[-1].get("parsed", [])
            if i < len(parsed):
                title, body = parsed[i]
        kws = ", ".join(kw_map.get(i, []))
        print(f"  C{i+1}: {title or body[:50]}  ({int((labels==i).sum())} Seg.)")
        if title and body:
            print(f"    {body}")
        print(f"    TF-IDF: {kws}\n")

    frozen_list = result.get("frozen", [])
    print(f"  {'─'*80}")
    if frozen_list:
        print(f"  Eingefrorene Cluster: {', '.join(f'C{c+1}' for c in frozen_list)}")
    print(f"  Label-Stabilität per Iteration:")
    for log in result.get("iteration_logs", []):
        active_sims = [
            info["sim"] for info in log.get("stab_info", [])
            if info["sim"] is not None
        ]
        avg_str = f"{sum(active_sims)/len(active_sims):.4f}" if active_sims else "    —"
        nf      = log.get("n_frozen", 0)
        nf_str  = f"  Eingefroren={nf}/{n}" if nf > 0 else ""
        print(f"    Iter {log['km_iter']:2d}: Stab.Ø={avg_str}  "
              f"Wechsel={log['change_pct']*100:.1f}%{nf_str}")
        for info in log.get("stab_info", []):
            cid = info["cid"]
            if info["sim"] is None:
                print(f"      C{cid+1}: ❄")
            else:
                d_str = f"  Δ={info['delta']:+.4f}" if info["delta"] is not None else "  (erste Messung)"
                f_str = "  → ❄" if info["new_freeze"] else ""
                print(f"      C{cid+1}: sim={info['sim']:.4f}{d_str}{f_str}")


# ── Einstiegspunkt ────────────────────────────────────────────────────────────

def main() -> None:
    t_total = time.perf_counter()

    print("  Lade Segmente…", flush=True)
    texts, seg_ids = load_segments()
    print(f"  {len(texts)} Segmente geladen", flush=True)

    model_str = MODEL_ANTHROPIC if PROVIDER == "anthropic" else MODEL_OLLAMA
    print(f"  Provider: {PROVIDER}  ({model_str})", flush=True)

    bge      = _load_bge()
    seg_embs = _compute_segment_embeddings(bge, texts)
    seg_embs = _neighbor_aggregate(seg_embs, texts)

    result = _run_tfidf_anchor(bge, seg_embs, texts)
    result = _eval(result, seg_embs)
    _print_final_table(result)

    print(f"\n  Gesamt: {time.perf_counter()-t_total:.1f}s\n")


if __name__ == "__main__":
    main()
