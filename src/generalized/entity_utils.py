"""
entity_utils.py — Gemeinsame Konstanten und Hilfsfunktionen für Entity-Erkennung.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

VALID_TYPES   = {"Person", "Organisation", "Ort", "Konzept"}
STOPLIST_SIZE = 50
MIN_TOKEN_LEN = 3

SOURCE_PRIORITY = {
    "seed": 0,
    "llm_iter1": 1, "llm_task1": 1, "llm_task2": 1, "llm_task3": 1, "llm_uncovered": 1,
    "llm_full": 1, "llm_dedup": 1,
    "classifier": 2, "embedding": 2,
}

CAPITAL_RE = re.compile(
    r'\b([A-ZÄÖÜÀÁÂÃÈÉÊËÌÍÎÏÒÓÔÕÙÚÛÝ\u0400-\u042F]'
    r'[\w\u00C0-\u024F\u1E00-\u1EFF\u0400-\u04FF]{2,})\b'
)


def _normalize_entity(ent: dict, source: str, rejected_lc: set[str] = frozenset()) -> dict | None:
    """Setzt _source, korrigiert typ, verwirft Entities mit leerem normalform oder in rejected-Liste."""
    norm = (ent.get("normalform") or "").strip()
    if not norm:
        return None
    if norm.lower() in rejected_lc:
        return None
    for a in ent.get("aliases") or []:
        if a and a.lower() in rejected_lc:
            return None
    ent["normalform"] = norm
    ent["_source"] = source
    if ent.get("typ") not in VALID_TYPES:
        ent["typ"] = "Konzept"
    return ent


def _extract_tokens(segments: list[dict]) -> Counter:
    counter: Counter = Counter()
    for seg in segments:
        for m in CAPITAL_RE.finditer(seg.get("text", "")):
            counter[m.group(1)] += 1
    return counter


def _make_stoplist(counter: Counter, n: int = STOPLIST_SIZE) -> set[str]:
    return {tok for tok, _ in counter.most_common(n)}


def _embed(model, texts: list[str]) -> np.ndarray:
    return model.encode(texts, batch_size=256, normalize_embeddings=True,
                        show_progress_bar=False)


def _add_multiword_aliases(
    candidates: list[dict],
    content_segs: list[dict],
    stoplist: set[str],
    window: int = 2,
    min_count: int = 1,
) -> None:
    WORD_RE = re.compile(r'\b([\w\u00C0-\u024F\u1E00-\u1EFF\u0400-\u04FF]{2,})\b')
    CAP_RE  = re.compile(r'^[A-ZÄÖÜÀÁÂÃÈÉÊËÌÍÎÏÒÓÔÕÙÚÛÝ\u0400-\u042F]')

    corpus: list[tuple[str, list[tuple[str, int, int]]]] = []
    for seg in content_segs:
        text  = seg.get("text", "")
        words = [(m.group(), m.start(), m.end()) for m in WORD_RE.finditer(text)]
        corpus.append((text, words))

    positions: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for ci, (_, words) in enumerate(corpus):
        for wi, (w, _, _) in enumerate(words):
            positions[w.lower()].append((ci, wi))

    total_added = 0
    for cand in candidates:
        all_tokens   = [cand["normalform"]] + list(cand.get("aliases", []))
        single_tokens = [t for t in all_tokens if t and len(t.split()) == 1]

        phrase_counter: Counter = Counter()
        for tok in single_tokens:
            for ci, wi in positions.get(tok.lower(), []):
                text, words = corpus[ci]

                left  = wi - 1
                steps = 0
                while left >= 0 and steps < window:
                    if CAP_RE.match(words[left][0]) and words[left][0] not in stoplist:
                        left -= 1; steps += 1
                    else:
                        break
                left += 1

                right = wi + 1
                steps = 0
                while right < len(words) and steps < window:
                    if CAP_RE.match(words[right][0]) and words[right][0] not in stoplist:
                        right += 1; steps += 1
                    else:
                        break

                if right - left <= 1:
                    continue

                phrase = text[words[left][1]:words[right - 1][2]].strip()
                if phrase.lower() != tok.lower():
                    phrase_counter[phrase] += 1

        existing_lc = {s.lower() for s in [cand["normalform"]] + cand.get("aliases", [])}
        for phrase, count in phrase_counter.items():
            if count >= min_count and phrase.lower() not in existing_lc:
                cand.setdefault("aliases", []).append(phrase)
                existing_lc.add(phrase.lower())
                total_added += 1

    print(f"  Mehrwort-Pass: {total_added} Aliases ergänzt")


def _build_few_shot_block(seed: list[dict]) -> str:
    if not seed:
        return ""
    lines = []
    for ent in seed[:10]:
        aliases   = ent.get("aliases", [])
        alias_str = ", ".join(aliases[:3]) if aliases else ent.get("normalform", "")
        lines.append(f"- {ent.get('normalform','')} ({ent.get('typ','?')}): {alias_str}")
    header = "Bekannte Entities in diesem Material (Orientierung für Stil und Domäne):\n"
    return header + "\n".join(lines) + "\n\n"


def _all_aliases(ent: dict) -> set[str]:
    names = {ent.get("normalform", "").lower()}
    for a in ent.get("aliases", []):
        if a:
            names.add(a.lower())
    return names - {""}


def _merge(groups: list[list[dict]]) -> list[dict]:
    merged: list[dict] = []
    for group in groups:
        for ent in group:
            if not (ent.get("normalform") or "").strip():
                continue
            alias_set = _all_aliases(ent)
            match     = next((e for e in merged if _all_aliases(e) & alias_set), None)
            if match is None:
                merged.append({
                    "normalform": ent.get("normalform", ""),
                    "typ":        ent.get("typ", "Konzept"),
                    "aliases":    list(ent.get("aliases", [])),
                    "_source":    ent.get("_source", "?"),
                })
            else:
                cur_prio = SOURCE_PRIORITY.get(match.get("_source", ""), 99)
                new_prio = SOURCE_PRIORITY.get(ent.get("_source", ""),   99)
                if new_prio < cur_prio:
                    match["normalform"] = ent.get("normalform", match["normalform"])
                    match["_source"]    = ent.get("_source",    match["_source"])
                existing_lc = {a.lower() for a in match["aliases"]}
                for a in ent.get("aliases", []):
                    if a and a.lower() not in existing_lc:
                        match["aliases"].append(a)
                        existing_lc.add(a.lower())

    for ent in merged:
        ent.pop("_source", None)
    return merged


def _print_stats(entities: list[dict]) -> None:
    dist = Counter(e.get("typ", "?") for e in entities)
    for typ in ("Person", "Organisation", "Ort", "Konzept"):
        print(f"  {typ:15s}  {dist.get(typ, 0):3d}")


def _save_checkpoint(path: Path, updates: dict) -> None:
    cp: dict = {}
    if path.exists():
        try:
            cp = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    cp.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cp, ensure_ascii=False), encoding="utf-8")
