"""
embeddings.py — Provider-Abstraktion für Embedding-Modelle

Unterstützte Provider:
  local   – Lokale Torch-Modelle (kein API-Key nötig)
  voyage  – Voyage AI API (voyage-4)

Task-Typen:
  EMB_TASK_CLUSTER   – Entity-Dedup/-Clustering → MiniLM / Voyage-4
  EMB_TASK_CLASSIFY  – Segment↔Taxonomie cosine similarity → BGE-M3 / Voyage-4

Konfiguration in .env:
  EMBEDDING_PROVIDER=local    # oder: voyage
  VOYAGE_API_KEY=pa-...

Alle Provider geben normalisierte np.ndarray der Form (N, dim) zurück.

Threshold-Hinweise (Voyage-4 hat eine andere Metrik-Skalierung als lokale Modelle):
  Entity-Clustering:    MiniLM → 0.92 | Voyage-4 → ~0.78
  Taxonomie-Classify:   BGE-M3 → 0.35/0.50 confidence-Grenzen | Voyage-4 → ~0.82

Verwendung:
  from src.generalized.embeddings import get_embedding_provider, EMB_TASK_CLUSTER

  provider = get_embedding_provider(task=EMB_TASK_CLUSTER)
  embs = provider.encode(["Flughafen BER", "BER Berlin"])   # → np.ndarray (2, dim)
"""

import os

import numpy as np

# ── Task-Konstanten ────────────────────────────────────────────────────────────

EMB_TASK_CLUSTER  = "cluster"    # Entity-Dedup → MiniLM (local) / Voyage-4
EMB_TASK_CLASSIFY = "classify"   # Taxonomie    → BGE-M3 (local) / Voyage-4

# ── Modul-globale Modell-Caches ───────────────────────────────────────────────

_miniLM_model = None
_miniLM_name:  str | None = None
_bge_model    = None


# ── Basisklasse ───────────────────────────────────────────────────────────────

class EmbeddingProvider:
    def encode(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


# ── Lokale Provider ───────────────────────────────────────────────────────────

class MiniLMProvider(EmbeddingProvider):
    """paraphrase-multilingual-MiniLM-L12-v2 — schnell, gut für kurze Entity-Strings."""

    _MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

    def encode(self, texts: list[str]) -> np.ndarray:
        global _miniLM_model, _miniLM_name
        if _miniLM_model is None or _miniLM_name != self._MODEL_NAME:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers nicht installiert: "
                    "pip install sentence-transformers"
                )
            print(f"Embeddings: {self._MODEL_NAME} wird geladen …", flush=True)
            _miniLM_model = SentenceTransformer(self._MODEL_NAME)
            _miniLM_name  = self._MODEL_NAME
            print("Embeddings: Modell geladen", flush=True)
        raw = _miniLM_model.encode(
            texts, show_progress_bar=False, normalize_embeddings=True
        )
        return np.array(raw, dtype=np.float32)


class BGEProvider(EmbeddingProvider):
    """BAAI/bge-m3 — stark für lange Texte, Taxonomie↔Segment similarity."""

    def encode(self, texts: list[str]) -> np.ndarray:
        global _bge_model
        if _bge_model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError:
                raise RuntimeError(
                    "FlagEmbedding nicht installiert: pip install FlagEmbedding"
                )
            print("Embeddings: BAAI/bge-m3 wird geladen …", flush=True)
            _bge_model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
            print("Embeddings: Modell geladen", flush=True)
        raw = _bge_model.encode(
            texts,
            batch_size=32,
            max_length=512,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )["dense_vecs"]
        embs  = np.array(raw, dtype=np.float32)
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        return embs / np.maximum(norms, 1e-9)


# ── API-Provider ──────────────────────────────────────────────────────────────

class VoyageProvider(EmbeddingProvider):
    """voyage-4 via Voyage AI API — Alternative für Deployment ohne lokale Modelle."""

    # Empfohlene Thresholds (abgeleitet aus Vergleich 2026-05-17)
    THRESHOLD_CLUSTER  = 0.78   # Entity-Clustering (statt 0.92 bei MiniLM)
    THRESHOLD_CLASSIFY = 0.82   # Taxonomie cosine similarity

    def __init__(self, api_key: str = None):
        try:
            import voyageai
        except ImportError:
            raise RuntimeError(
                "voyageai nicht installiert: pip install voyageai"
            )
        key = api_key or os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise RuntimeError("VOYAGE_API_KEY nicht gesetzt")
        self._client = voyageai.Client(api_key=key)

    def encode(self, texts: list[str]) -> np.ndarray:
        result = self._client.embed(texts, model="voyage-4", input_type="query")
        embs  = np.array(result.embeddings, dtype=np.float32)
        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        return embs / np.maximum(norms, 1e-9)


# ── Factory ───────────────────────────────────────────────────────────────────

def get_embedding_provider(
    task: str = None,
    name: str = None,
) -> EmbeddingProvider:
    """
    Gibt einen konfigurierten EmbeddingProvider zurück.

    task  – EMB_TASK_CLUSTER oder EMB_TASK_CLASSIFY; bestimmt das lokale Modell.
    name  – "local" oder "voyage"; überschreibt EMBEDDING_PROVIDER aus .env.
    """
    provider_name = (name or os.environ.get("EMBEDDING_PROVIDER", "local")).lower()

    if provider_name == "local":
        if task == EMB_TASK_CLASSIFY:
            return BGEProvider()
        return MiniLMProvider()

    if provider_name == "voyage":
        return VoyageProvider()

    raise ValueError(
        f"Unbekannter EMBEDDING_PROVIDER: '{provider_name}'. "
        "Erlaubt: 'local', 'voyage'"
    )
