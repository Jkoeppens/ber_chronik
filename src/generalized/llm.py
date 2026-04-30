"""
llm.py — Provider-Abstraktion für LLM-Aufrufe

Unterstützte Provider:
  anthropic  – Anthropic API
  ollama     – Lokales Ollama

Task-Typen (wählen automatisch das passende Modell je Provider):
  TASK_CLASSIFY  – schnell, viele Requests (Segment → Kategorie)
  TASK_ANALYZE   – Qualität wichtig (Taxonomie-Vorschlag, Ingest-Analyse)
  TASK_EXTRACT   – Qualität wichtig, strukturiertes JSON (Entity-Extraktion)

Konfiguration in .env:
  LLM_PROVIDER=ollama        # oder: anthropic
  ANTHROPIC_API_KEY=sk-...

  # Modell-Override pro Task (optional, sonst greifen Defaults):
  ANTHROPIC_MODEL_CLASSIFY=claude-haiku-4-5-20251001
  ANTHROPIC_MODEL_ANALYZE=claude-sonnet-4-6
  ANTHROPIC_MODEL_EXTRACT=claude-sonnet-4-6

  OLLAMA_MODEL_CLASSIFY=llama3.1:8b
  OLLAMA_MODEL_ANALYZE=llama3.1:8b
  OLLAMA_MODEL_EXTRACT=llama3.1:8b

Verwendung:
  from src.generalized.llm import get_provider, TASK_ANALYZE

  provider = get_provider(task=TASK_ANALYZE)   # wählt Modell automatisch
  text = provider.complete(prompt, system="...")
  data = provider.complete_json(prompt, system="...")
"""

import json
import os
from pathlib import Path

import requests

from src.generalized.config import ROOT

# ── Task-Konstanten ────────────────────────────────────────────────────────────

TASK_CLASSIFY = "classify"   # schnell, viele Requests → Haiku / llama3.1:8b
TASK_ANALYZE  = "analyze"    # Qualität wichtig       → Sonnet / llama3.1:8b
TASK_EXTRACT  = "extract"    # Qualität wichtig       → Sonnet / llama3.1:8b

_ANTHROPIC_DEFAULTS: dict[str, str] = {
    TASK_CLASSIFY: "claude-haiku-4-5-20251001",
    TASK_ANALYZE:  "claude-sonnet-4-6",
    TASK_EXTRACT:  "claude-sonnet-4-6",
}

_OLLAMA_DEFAULTS: dict[str, str] = {
    TASK_CLASSIFY: "llama3.1:8b",
    TASK_ANALYZE:  "llama3.1:8b",
    TASK_EXTRACT:  "llama3.1:8b",
}


def _extract_json(text: str):
    """Extrahiert das erste vollständige JSON-Objekt oder -Array aus dem Text.

    Handles: code fences, leading prose, trailing text after JSON.
    Uses raw_decode so only the first valid JSON token is parsed.
    """
    t = text.strip()
    # Remove code fences
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch in ('{', '['):
            try:
                obj, _ = decoder.raw_decode(t, i)
                return obj
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("No valid JSON found in LLM response", t, 0)


class LLMProvider:
    max_concurrency: int = 1
    max_chars_per_chunk: int = 8000

    def complete(self, prompt: str, system: str = None) -> str:
        raise NotImplementedError

    def complete_json(self, prompt: str, system: str = None):
        raw = self.complete(prompt, system=system)
        return _extract_json(raw)


class AnthropicProvider(LLMProvider):
    """Ruft die Anthropic Messages API auf (synchron)."""
    max_concurrency = 10
    max_chars_per_chunk = 8000

    def __init__(self, model: str = "claude-haiku-4-5-20251001", api_key: str = None):
        import anthropic as _anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY nicht gesetzt")
        self._client = _anthropic.Anthropic(api_key=key)
        self.model = model

    def complete(self, prompt: str, system: str = None) -> str:
        kwargs = dict(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return msg.content[0].text.strip()


class OllamaProvider(LLMProvider):
    """Ruft ein lokales Ollama-Modell auf."""
    max_concurrency = 1
    max_chars_per_chunk = 2000

    def __init__(self, model: str = "llama3.1:8b", base_url: str | None = None):
        self.model    = model
        self.base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")

    def complete(self, prompt: str, system: str = None, json_mode: bool = False) -> str:
        payload: dict = {
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"num_ctx": 8192},
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        try:
            r = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=300,
            )
            r.raise_for_status()
            return r.json().get("response", "").strip()
        except requests.RequestException as e:
            raise RuntimeError(f"Ollama nicht erreichbar ({self.base_url}): {e}") from e

    def complete_json(self, prompt: str, system: str = None):
        raw = self.complete(prompt, system=system, json_mode=True)
        return _extract_json(raw)


def get_provider(
    name: str = None,
    task: str = None,
    model: str = None,
) -> LLMProvider:
    """
    Gibt einen konfigurierten LLMProvider zurück.

    name   – "anthropic" oder "ollama"; überschreibt LLM_PROVIDER aus .env.
    task   – TASK_CLASSIFY / TASK_ANALYZE / TASK_EXTRACT; bestimmt das Modell.
    model  – Expliziter Modell-Override; hat Vorrang vor task.
    """
    provider_name = (name or os.environ.get("LLM_PROVIDER", "ollama")).lower()

    if provider_name == "anthropic":
        if model:
            resolved = model
        elif task:
            env_key  = f"ANTHROPIC_MODEL_{task.upper()}"
            resolved = os.environ.get(env_key, _ANTHROPIC_DEFAULTS.get(task, "claude-haiku-4-5-20251001"))
        else:
            resolved = "claude-haiku-4-5-20251001"
        return AnthropicProvider(model=resolved)

    elif provider_name == "ollama":
        if model:
            resolved = model
        elif task:
            env_key  = f"OLLAMA_MODEL_{task.upper()}"
            resolved = (os.environ.get(env_key)
                        or os.environ.get("OLLAMA_MODEL")
                        or _OLLAMA_DEFAULTS.get(task, "llama3.1:8b"))
        else:
            resolved = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        return OllamaProvider(model=resolved)

    else:
        raise ValueError(
            f"Unbekannter LLM_PROVIDER: '{provider_name}'. "
            "Erlaubt: 'anthropic', 'ollama'"
        )
