import argparse
import re
from collections import Counter
from pathlib import Path

import pandas as pd
import spacy
from spacy.matcher import PhraseMatcher
from tqdm import tqdm


def load_seed(seed_path: Path) -> pd.DataFrame:
    df = pd.read_csv(seed_path)
    df["alias"] = df["alias"].str.strip()
    df["normalform"] = df["normalform"].str.strip()
    return df


def build_phrase_matcher(nlp, seed: pd.DataFrame) -> PhraseMatcher:
    """PhraseMatcher for multi-word aliases only (alias contains a space)."""
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    for _, row in seed.iterrows():
        alias = row["alias"]
        if " " not in alias:
            continue  # single-word aliases handled by regex
        matcher.add(row["normalform"], [nlp.make_doc(alias)])
    return matcher


def build_regex_map(seed: pd.DataFrame) -> dict[str, str]:
    """Map alias_lower → normalform for all single-word aliases."""
    return {
        row["alias"].lower(): row["normalform"]
        for _, row in seed.iterrows()
        if " " not in row["alias"]
    }


def build_regex(regex_map: dict[str, str]) -> re.Pattern | None:
    """Single compiled regex covering all single-word aliases.

    Matches both bare form (\\bSPD\\b) and parenthesised form (\\(SPD\\))
    so that abbreviations in brackets are also caught.
    """
    if not regex_map:
        return None
    parts = []
    for alias in sorted(regex_map, key=len, reverse=True):  # longest first
        esc = re.escape(alias)
        parts.append(r"\(" + esc + r"\)")   # (SPD)
        parts.append(r"\b" + esc + r"\b")   # SPD
    return re.compile("|".join(parts), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Stufe 1 – Dictionary matching
# ---------------------------------------------------------------------------

def run_dictionary_matching(
    texts: list[str],
    nlp,
    matcher: PhraseMatcher,
    regex_pat: re.Pattern | None,
    regex_map: dict[str, str],
) -> list[str]:
    """Return ';'-joined normalforms per text ('' if none matched).

    Multi-word aliases → PhraseMatcher on spaCy doc.
    Single-word aliases → regex on raw text (catches SPD inside SPD-Fraktion etc.).
    """
    results = []
    with nlp.select_pipes(disable=["ner"]):
        for text, doc in tqdm(
            zip(texts, nlp.pipe(texts, batch_size=64)),
            total=len(texts), desc="Dictionary matching",
        ):
            seen: set[str] = set()
            actors: list[str] = []

            # Multi-word: PhraseMatcher
            for match_id, _start, _end in matcher(doc):
                norm = nlp.vocab.strings[match_id]
                if norm not in seen:
                    seen.add(norm)
                    actors.append(norm)

            # Single-word: regex on raw text
            if regex_pat:
                for m in regex_pat.finditer(text):
                    key  = m.group(0).strip("()").lower()
                    norm = regex_map.get(key)
                    if norm and norm not in seen:
                        seen.add(norm)
                        actors.append(norm)

            results.append(";".join(actors))
    return results


# ---------------------------------------------------------------------------
# Stufe 2 – spaCy NER → entity candidates
# ---------------------------------------------------------------------------

def run_ner_candidates(
    texts: list[str],
    nlp,
    known_lower: set[str],
    min_count: int = 3,
) -> pd.DataFrame:
    """Run NER, collect PER/ORG entities not in seed, return those >= min_count."""
    counter: Counter = Counter()
    label_map: dict[str, str] = {}

    with nlp.select_pipes(disable=["tagger", "parser", "attribute_ruler", "lemmatizer"]):
        for doc in tqdm(nlp.pipe(texts, batch_size=64), total=len(texts), desc="NER candidates"):
            for ent in doc.ents:
                if ent.label_ not in ("PER", "ORG"):
                    continue
                text = ent.text.strip()
                if not text or text.lower() in known_lower:
                    continue
                counter[text] += 1
                label_map.setdefault(text, ent.label_)

    rows = [
        {"text": t, "label": label_map[t], "count": c}
        for t, c in counter.most_common()
        if c >= min_count
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Entity matching + NER candidates for BER chronik")
    ap.add_argument("--input",      default="data/interim/paragraphs_enriched.csv")
    ap.add_argument("--seed",         default="config/entities_seed.csv")
    ap.add_argument("--sources-seed", default="config/sources_seed.csv")
    ap.add_argument("--output",       default="data/interim/paragraphs_enriched.csv")
    ap.add_argument("--candidates",   default="data/interim/entity_candidates.csv")
    ap.add_argument("--min-count",    type=int, default=2)
    args = ap.parse_args()

    in_path    = Path(args.input).expanduser().resolve()
    seed_path  = Path(args.seed).expanduser().resolve()
    src_path   = Path(args.sources_seed).expanduser().resolve()
    out_path   = Path(args.output).expanduser().resolve()
    cand_path  = Path(args.candidates).expanduser().resolve()

    df   = pd.read_csv(in_path)
    seed = load_seed(seed_path)
    texts = df["text_span"].fillna("").tolist()

    # Known aliases + normalforms for NER-filter: entities + sources (case-insensitive)
    known_lower = set(seed["alias"].str.lower()) | set(seed["normalform"].str.lower())
    if src_path.exists():
        sources = load_seed(src_path)
        known_lower |= set(sources["alias"].str.lower()) | set(sources["normalform"].str.lower())

    print("Loading spaCy model de_core_news_sm …")
    nlp = spacy.load("de_core_news_sm")

    matcher   = build_phrase_matcher(nlp, seed)
    regex_map = build_regex_map(seed)
    regex_pat = build_regex(regex_map)
    print(f"  PhraseMatcher: {sum(1 for _, r in seed.iterrows() if ' ' in r['alias'])} multi-word aliases")
    print(f"  Regex:         {len(regex_map)} single-word aliases")

    # Stufe 1
    print("\nStufe 1: Dictionary matching …")
    df["actors"] = run_dictionary_matching(texts, nlp, matcher, regex_pat, regex_map)
    n_matched = (df["actors"] != "").sum()
    print(f"  {n_matched}/{len(df)} Absätze mit mindestens einem Akteur")

    # Stufe 2
    print("\nStufe 2: NER candidates …")
    candidates = run_ner_candidates(texts, nlp, known_lower, args.min_count)
    print(f"  {len(candidates)} Kandidaten mit count >= {args.min_count}")

    # Write outputs
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\nWrote enriched CSV  -> {out_path}")

    cand_path.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(cand_path, index=False)
    print(f"Wrote candidates    -> {cand_path}")

    # Summary
    print("\nTop 15 actors (Einzelnennungen):")
    actor_counter: Counter = Counter()
    for val in df["actors"]:
        if val:
            for a in str(val).split(";"):
                actor_counter[a.strip()] += 1
    for name, count in actor_counter.most_common(15):
        print(f"  {count:4d}  {name}")

    print(f"\nTop NER-Kandidaten (count >= {args.min_count}):")
    if not candidates.empty:
        print(candidates.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
