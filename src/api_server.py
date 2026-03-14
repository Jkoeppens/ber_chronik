"""
BER Chronik Chat API
POST /chat  →  { answer, sources, keywords }

Run with:
    pip install fastapi uvicorn requests
    uvicorn src.api_server:app --reload --port 8000
"""

import json
import re
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_URL     = "http://localhost:11434/api/generate"
MODEL          = "mistral"
MAX_PARAGRAPHS = 20
DATA_PATH      = Path(__file__).parent.parent / "viz" / "data.json"

# ── Prompt ────────────────────────────────────────────────────────────────────
ANSWER_PROMPT = """\
Du beantwortest eine Frage zur Geschichte des Flughafens Berlin Brandenburg (BER) \
auf Basis von Auszügen aus einer deutschen Chronik (1989–2017).

Frage: {question}

Gefundene Auszüge ({count} gesamt):
{paragraphs}

Antworte auf Deutsch. Gliedere deine Antwort nach den relevanten thematischen \
Kategorien die sich aus den Auszügen ergeben – z.B. „Zeitlicher Verlauf", \
„Beteiligte Personen", „Kosten", „Entscheidungen". Nenne konkrete Daten, Personen \
und Beschlüsse. Halte dich strikt an die Auszüge, erfinde keine Fakten. \
Falls die Auszüge nicht genug Information enthalten, sage das kurz.

Antworte mit Fließtext und kurzen Überschriften (##), keine JSON-Ausgabe.\
"""

# ── German stopwords for keyword extraction ───────────────────────────────────
STOPWORDS = {
    "aber", "alle", "allem", "allen", "aller", "alles", "also", "als", "am",
    "an", "auch", "auf", "aus", "bei", "beim", "bin", "bis", "bitte", "da",
    "damit", "dann", "dass", "dem", "den", "denn", "der", "des", "dessen",
    "die", "dies", "dieser", "dieses", "doch", "dort", "durch", "ein", "eine",
    "einem", "einen", "einer", "eines", "er", "es", "etwa", "euch", "euer",
    "gibt", "haben", "hatte", "hier", "ihm", "ihn", "ihnen", "ihr", "ihre",
    "im", "immer", "ist", "kann", "kein", "keine", "mal", "man", "mehr",
    "mich", "mir", "mit", "nach", "nicht", "noch", "nun", "nur", "oder",
    "ohne", "sehr", "sein", "sich", "sie", "sind", "soll", "sowie", "über",
    "um", "und", "unter", "uns", "vom", "von", "vor", "war", "waren", "warum",
    "was", "weil", "wenn", "wer", "werden", "wie", "wird", "wir", "wird",
    "worden", "wurde", "wurden", "wäre", "würde", "wird", "ziel", "zu",
    "zum", "zur", "zwischen",
}

# ── Data ─────────────────────────────────────────────────────────────────────
with open(DATA_PATH, encoding="utf-8") as _f:
    ENTRIES: list[dict] = json.load(_f)["entries"]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="BER Chronik Chat API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer:   str
    sources:  list[str]
    keywords: list[str]


# ── Helpers ───────────────────────────────────────────────────────────────────
def call_ollama(prompt: str) -> str:
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")


def extract_keywords(question: str, min_len: int = 4, max_kw: int = 6) -> list[str]:
    """Tokenize question, drop stopwords, return up to max_kw content words."""
    tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", question)
    return [
        t.lower() for t in tokens
        if len(t) >= min_len and t.lower() not in STOPWORDS
    ][:max_kw]


def search_entries(entries: list[dict], keywords: list[str]) -> list[dict]:
    """Return entries where at least one keyword appears in the text (OR logic)."""
    if not keywords:
        return []
    hits = []
    for e in entries:
        text_lower = (e.get("text") or "").lower()
        if any(kw in text_lower for kw in keywords):
            hits.append(e)
    return hits


# ── Endpoint ──────────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    # Step 1: extract keywords from question (no LLM call)
    keywords = extract_keywords(question)

    # Step 2: OR search over all entries
    hits = search_entries(ENTRIES, keywords)
    hits = hits[:MAX_PARAGRAPHS]

    if not hits:
        return ChatResponse(
            answer="Zu dieser Frage wurden keine passenden Einträge in der Chronik gefunden.",
            sources=[],
            keywords=keywords,
        )

    # Step 3: synthesise structured answer via Mistral
    para_block = "\n\n".join(
        f"[{e['doc_anchor']}, {e.get('year', '?')}] {e.get('text', '')}"
        for e in hits
    )
    answer = call_ollama(
        ANSWER_PROMPT.format(question=question, count=len(hits), paragraphs=para_block)
    )
    if not answer:
        answer = "Die Zusammenfassung konnte nicht generiert werden."

    sources = [e["doc_anchor"] for e in hits if e.get("doc_anchor")]
    return ChatResponse(answer=answer, sources=sources, keywords=keywords)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "entries": len(ENTRIES)}
