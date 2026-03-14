"""
BER Chronik Chat API
POST /chat  →  { answer, sources, params }

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
OLLAMA_URL    = "http://localhost:11434/api/generate"
MODEL         = "mistral"
MAX_PARAGRAPHS = 20
DATA_PATH     = Path(__file__).parent.parent / "viz" / "data.json"

VALID_EVENT_TYPES = {
    "Beschluss", "Vertrag", "Klage", "Personalie",
    "Kosten", "Termin", "Technik", "Planung", "Claim",
}

# ── Prompts ───────────────────────────────────────────────────────────────────
SEARCH_PROMPT = """\
You are a search assistant for a German chronology of Berlin Brandenburg Airport (BER), 1989–2017.

Given a user question, extract search parameters to filter the chronology entries.

Valid event_type values: Beschluss, Vertrag, Klage, Personalie, Kosten, Termin, Technik, Planung, Claim

Return ONLY valid JSON, no explanation:
{{
  "event_type": "<one valid type, or null>",
  "keywords":   ["<word>", ...],
  "year_from":  <integer or null>,
  "year_to":    <integer or null>
}}

Rules:
- keywords: 1–4 German words that should appear in matching paragraphs
- Set event_type null if the question spans multiple types or is unclear
- Set year range null if not implied by the question

User question: "{question}"\
"""

ANSWER_PROMPT = """\
You are answering a question about the history of Berlin Brandenburg Airport (BER) \
based on excerpts from a German chronology (1989–2017).

Question: {question}

Relevant excerpts ({count} total):
{paragraphs}

Write a concise answer in German (4–7 sentences).
- Base your answer strictly on the excerpts above, do not invent facts
- Mention specific dates, persons, and decisions where relevant
- If the excerpts do not contain enough information, say so briefly

Reply with plain text only, no headings, no bullet points.\
"""

# ── Data ─────────────────────────────────────────────────────────────────────
with open(DATA_PATH, encoding="utf-8") as _f:
    ENTRIES: list[dict] = json.load(_f)["entries"]

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="BER Chronik Chat API", version="1.0")

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
    answer:  str
    sources: list[str]
    params:  dict[str, Any]


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


def extract_json(text: str) -> dict:
    """Pull the first {...} block out of a possibly noisy LLM response."""
    m = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in response")
    return json.loads(m.group(0))


def filter_entries(entries: list[dict], params: dict) -> list[dict]:
    event_type = params.get("event_type")
    keywords   = [k.lower() for k in (params.get("keywords") or [])]
    year_from  = params.get("year_from")
    year_to    = params.get("year_to")

    results = []
    for e in entries:
        # event_type (only if valid)
        if event_type and event_type in VALID_EVENT_TYPES:
            if e.get("event_type") != event_type:
                continue

        # year range
        year = e.get("year")
        if year_from and year and year < year_from:
            continue
        if year_to and year and year > year_to:
            continue

        # keywords – OR logic: at least one must appear in text
        if keywords:
            text_lower = (e.get("text") or "").lower()
            if not any(kw in text_lower for kw in keywords):
                continue

        results.append(e)
    return results


# ── Endpoint ──────────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question must not be empty")

    # Step 1: extract search params from question
    search_raw = call_ollama(SEARCH_PROMPT.format(question=question))
    try:
        params = extract_json(search_raw)
    except (ValueError, json.JSONDecodeError):
        params = {"event_type": None, "keywords": [], "year_from": None, "year_to": None}

    # Step 2: filter entries
    hits = filter_entries(ENTRIES, params)

    # Fallback: if event_type was set but yielded nothing, retry without it
    if not hits and params.get("event_type"):
        hits = filter_entries(ENTRIES, {**params, "event_type": None})

    # Cap to MAX_PARAGRAPHS
    hits = hits[:MAX_PARAGRAPHS]

    if not hits:
        return ChatResponse(
            answer="Zu dieser Frage wurden keine passenden Einträge in der Chronik gefunden.",
            sources=[],
            params=params,
        )

    # Step 3: synthesise answer
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
    return ChatResponse(answer=answer, sources=sources, params=params)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "entries": len(ENTRIES)}
