"""
tests/test_neu_taxonomie_kern.py — src/neu/taxonomie/kern.py

Ohne Netz, ohne Modell, ohne Datenbank: Embedding und Sprachmodell werden als
Funktionen hereingegeben. Der Kreislauf läuft dabei vollständig durch — das
Einfrieren, das Ende, der Warm-Start und die Rundenzahl sind deterministisch
prüfbar.

Ausführen:
  python3 -m pytest tests/test_neu_taxonomie_kern.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.taxonomie.kern import (  # noqa: E402
    EARLY_STOP_DELTA,
    KM_INTERVAL,
    N_ITER,
    PROMPT_TEMPLATE,
    SHORT_THRESHOLD,
    baue_prompt,
    kmeanspp_stichprobe,
    nachbar_aggregat,
    parse_antwort,
    soll_einfrieren,
    tfidf_schlagworte,
    verfeinern,
    zentroide,
    zuordnen,
)


# ── TF-IDF ────────────────────────────────────────────────────────────────────

def test_tfidf_trennt_die_cluster() -> None:
    texte = [
        "Der Flughafen wurde eröffnet und der Flughafen kostet viel",
        "Flughafen Eröffnung Flughafen Termin Flughafen",
        "Das Gericht urteilte über die Klage vor Gericht",
        "Klage Gericht Urteil Klage Verfahren Gericht",
    ]
    labels = np.array([0, 0, 1, 1])
    kw = tfidf_schlagworte(texte, labels, n_clusters=2, top_k=3)
    # Entscheidend ist die Rangfolge: das prägende Wort steht vorn.
    assert kw[0][0] == "flughafen"
    assert kw[1][0] == "gericht"


def test_stopworte_fallen_weg() -> None:
    texte = ["der die das und Flughafen der die das",
             "der die das und Gericht der die das"]
    kw = tfidf_schlagworte(texte, np.array([0, 1]), n_clusters=2, top_k=5)
    for cid in (0, 1):
        assert not ({"der", "die", "das", "und"} & set(kw[cid]))


def test_leerer_cluster_bekommt_leere_liste() -> None:
    texte = ["Flughafen Termin Bau", "Flughafen Termin Kosten",
             "Gericht Klage Urteil", "Gericht Klage Verfahren"]
    kw = tfidf_schlagworte(texte, np.array([0, 0, 1, 1]), n_clusters=3)
    assert kw[2] == []


def test_tfidf_wirft_bei_kleinstkorpus() -> None:
    """Unveränderte Eigenheit der Vorlage: min_df=2 kann alles wegschneiden.

    Bei zwei Dokumenten ohne gemeinsames Wort bleibt kein Term übrig und
    sklearn wirft. Bei den Hunderten Segmenten eines echten Projekts tritt
    das nicht auf; festgehalten, weil es nicht abgefangen wird.
    """
    with pytest.raises(ValueError, match="no terms remain"):
        tfidf_schlagworte(["Flughafen Termin", "Gericht Klage"],
                          np.array([0, 1]), n_clusters=2)


# ── Early-Stop-Regel ──────────────────────────────────────────────────────────

def test_einfrieren_erst_ab_dem_zweiten_messwert() -> None:
    """Ohne Vorgänger gibt es kein Delta — dann wird nicht eingefroren."""
    assert soll_einfrieren(None) is False


def test_einfrieren_unterhalb_der_schwelle() -> None:
    assert soll_einfrieren(0.009) is True
    assert soll_einfrieren(0.0) is True
    assert soll_einfrieren(-0.5) is True      # Verschlechterung friert auch ein
    assert soll_einfrieren(0.011) is False
    assert soll_einfrieren(EARLY_STOP_DELTA) is False   # die Schwelle selbst nicht


# ── Zuordnung und Zentroide ───────────────────────────────────────────────────

def test_zuordnung_per_argmax() -> None:
    seg = np.array([[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]], dtype=np.float32)
    lab = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    assert zuordnen(seg, lab).tolist() == [0, 1, 0]


def test_zentroide_sind_normalisiert() -> None:
    embs = np.array([[3.0, 0.0], [0.0, 4.0]], dtype=np.float32)
    z = zentroide(embs, np.array([0, 0]), n_clusters=2)
    assert np.isclose(np.linalg.norm(z[0]), 1.0)
    assert np.allclose(z[1], 0.0)     # leerer Cluster bleibt Null


def test_nachbar_aggregat_nur_bei_kurzen_texten() -> None:
    embs = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    texte = ["x" * (SHORT_THRESHOLD + 10), "kurz", "y" * (SHORT_THRESHOLD + 10)]
    e = nachbar_aggregat(embs, texte)
    assert np.allclose(e[0], embs[0])      # lang → unverändert
    assert not np.allclose(e[1], embs[1])  # kurz → mit Nachbarn gemittelt
    assert np.isclose(np.linalg.norm(e[1]), 1.0)


# ── Prompt und Antwort ────────────────────────────────────────────────────────

def test_prompt_enthaelt_alle_gruppen_auch_ohne_beschreibung() -> None:
    seg = np.eye(3, dtype=np.float32)
    p = baue_prompt(["a", "b", "c"], seg, np.array([0, 1, 2]),
                    {0: ["x"], 1: ["y"], 2: ["z"]}, [None, None, None], None,
                    np.random.default_rng(0), n_clusters=3, m=2)
    for g in ("Gruppe 1", "Gruppe 2", "Gruppe 3"):
        assert f"{g} Keywords" in p
    assert "Vorherige Beschreibung" not in p     # erste Runde: kein Abschnitt


def test_prompt_traegt_den_rolling_context() -> None:
    seg = np.eye(2, dtype=np.float32)
    p = baue_prompt(["a", "b"], seg, np.array([0, 1]), {0: ["x"], 1: ["y"]},
                    ["alte Beschreibung", None], 5, np.random.default_rng(0),
                    n_clusters=2, m=1)
    assert "Vorherige Beschreibung (Iteration 5)" in p
    assert "alte Beschreibung" in p
    assert "Gruppe 2: (keine)" in p


def test_prompt_ist_der_der_vorlage() -> None:
    """Der Prompt bleibt wörtlich; v2 wird hier ausdrücklich nicht eingebaut."""
    assert "Was hält diese Texte zusammen?" in PROMPT_TEMPLATE
    assert "nicht was sie beschreiben, sondern wie sie funktionieren" in PROMPT_TEMPLATE
    assert "Hypothese" not in PROMPT_TEMPLATE


def test_antwort_wird_geparst() -> None:
    roh = "## Gruppe 1\nBau und Kosten\nEs geht um Geld.\n\n## Gruppe 2\nKlagen\nGerichte."
    e = parse_antwort(roh, 2)
    assert e[0] == ("Bau und Kosten", "Es geht um Geld.")
    assert e[1] == ("Klagen", "Gerichte.")


def test_fehlende_gruppe_wird_none() -> None:
    e = parse_antwort("## Gruppe 1\nNur eine\nBeschreibung.", 3)
    assert e[0] is not None and e[1] is None and e[2] is None


def test_stichprobe_liefert_hoechstens_m() -> None:
    embs = np.random.default_rng(1).normal(size=(20, 4)).astype(np.float32)
    idx = np.arange(20)
    s = kmeanspp_stichprobe(embs, idx, 5, np.random.default_rng(42))
    assert len(s) == 5 and len(set(s.tolist())) == 5
    klein = np.arange(3)
    assert kmeanspp_stichprobe(embs, klein, 5, np.random.default_rng(42)).tolist() == [0, 1, 2]


# ── Der Kreislauf mit erfundenem Anbieter ─────────────────────────────────────

def _welt(n: int = 40, dim: int = 8, seed: int = 7):
    """Zwei klar getrennte Themen — damit KMeans etwas zu finden hat."""
    rng = np.random.default_rng(seed)
    a = rng.normal(loc=[3, 0, 0, 0, 0, 0, 0, 0], scale=0.3, size=(n // 2, dim))
    b = rng.normal(loc=[0, 3, 0, 0, 0, 0, 0, 0], scale=0.3, size=(n // 2, dim))
    embs = np.vstack([a, b]).astype(np.float32)
    embs /= np.linalg.norm(embs, axis=1, keepdims=True)
    texte = ([f"Flughafen Termin Eröffnung Bericht Nummer {i} über den Bau" for i in range(n // 2)]
             + [f"Gericht Klage Urteil Verfahren Nummer {i} vor der Kammer" for i in range(n // 2)])
    return embs, texte


def _fester_anbieter(beschreibungen, protokoll=None):
    """Ein Modell, das immer dieselben Beschreibungen zurückgibt.

    Damit steht das Embedding der Beschreibung nach der ersten Runde fest —
    die Ähnlichkeit ändert sich nicht mehr, delta wird 0, alles friert ein.
    """
    def frage(prompt: str, system: str) -> tuple[str, int, int]:
        if protokoll is not None:
            protokoll.append(prompt)
        bloecke = [f"## Gruppe {i+1}\n{t}\n{b}" for i, (t, b) in enumerate(beschreibungen)]
        return "\n\n".join(bloecke), 100, 20
    return frage


def _embed_fest(dim: int = 8):
    """Embeddet einen Text deterministisch — gleicher Text, gleicher Vektor.

    crc32 statt hash(): hash() ist je Prozess anders gesalzen, der Test wäre
    dann nicht reproduzierbar.
    """
    import zlib

    def embed(texte):
        out = []
        for t in texte:
            rng = np.random.default_rng(zlib.crc32(t.encode("utf-8")))
            v = rng.normal(size=dim).astype(np.float32)
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)
    return embed


def test_kreislauf_friert_ein_und_endet_frueh() -> None:
    embs, texte = _welt()
    vorschlag = verfeinern(
        seg_embs=embs, texte=texte, embed=_embed_fest(),
        frage_modell=_fester_anbieter([("Flughafenbau", "Termine und Kosten."),
                                       ("Klagen", "Gerichte und Verfahren.")]),
        n_clusters=2,
    )
    assert vorschlag.fruehzeitig_beendet is True
    assert vorschlag.eingefroren == [0, 1]
    # Runde 1: erste Messung, kein Delta — kein Einfrieren.
    # Runde 2: das Label IST jetzt das Beschreibungs-Embedding, sim springt
    #          auf 1,0, delta ist groß positiv — kein Einfrieren.
    # Runde 3: sim bleibt 1,0, delta = 0 → beide einfrieren, Ende.
    assert vorschlag.llm_calls == 3
    assert len(vorschlag.runden) == 3
    assert vorschlag.runden[0].neu_eingefroren == []
    assert vorschlag.runden[1].neu_eingefroren == []
    assert sorted(vorschlag.runden[2].neu_eingefroren) == [0, 1]
    assert vorschlag.runden[1].sim[0] == pytest.approx(1.0, abs=1e-5)
    assert vorschlag.runden[2].delta[0] == pytest.approx(0.0, abs=1e-6)


def test_kreislauf_ist_deterministisch() -> None:
    embs, texte = _welt()
    args = dict(seg_embs=embs, texte=texte, embed=_embed_fest(),
                frage_modell=_fester_anbieter([("A", "eins."), ("B", "zwei.")]),
                n_clusters=2)
    a = verfeinern(**args)
    b = verfeinern(**args)
    assert [r.sim for r in a.runden] == [r.sim for r in b.runden]
    assert a.kategorien == b.kategorien
    assert a.labels.tolist() == b.labels.tolist()


def test_sicherheitsstopp_greift_wenn_nichts_einfriert() -> None:
    """N_ITER ist der harte Stopp, wenn kein Cluster je einfriert.

    Das Einfrieren wird über eine unerreichbare Schwelle ausgeschaltet: ein
    *sinkendes* sim friert nach der Regel der Vorlage ebenfalls ein
    (delta < Schwelle), ein „konvergiert nie" ließe sich sonst nicht
    verlässlich herstellen.
    """
    embs, texte = _welt()
    zaehler = {"n": 0}

    def wankelmuetig(prompt: str, system: str) -> tuple[str, int, int]:
        zaehler["n"] += 1
        i = zaehler["n"]
        return (f"## Gruppe 1\nTitel{i}\nBeschreibung Nummer {i}.\n\n"
                f"## Gruppe 2\nAnders{i}\nGanz andere Sache {i}."), 10, 5

    vorschlag = verfeinern(seg_embs=embs, texte=texte, embed=_embed_fest(),
                           frage_modell=wankelmuetig, n_clusters=2,
                           early_stop_delta=-10.0)
    assert vorschlag.fruehzeitig_beendet is False
    assert vorschlag.eingefroren == []
    assert vorschlag.llm_calls == N_ITER          # der harte Stopp, 4
    assert len(vorschlag.runden) == N_ITER


def test_rundenzahl_folgt_dem_km_intervall() -> None:
    embs, texte = _welt()
    zaehler = {"n": 0}

    def wankelmuetig(prompt: str, system: str) -> tuple[str, int, int]:
        zaehler["n"] += 1
        return (f"## Gruppe 1\nT{zaehler['n']}\nB{zaehler['n']}.\n\n"
                f"## Gruppe 2\nU{zaehler['n']}\nC{zaehler['n']}."), 0, 0

    v = verfeinern(seg_embs=embs, texte=texte, embed=_embed_fest(),
                   frage_modell=wankelmuetig, n_clusters=2,
                   early_stop_delta=-10.0)
    # Ein LLM-Call alle KM_INTERVAL Schritte: 5, 10, 15, 20
    assert [r.km_iter for r in v.runden] == [KM_INTERVAL * i for i in range(1, N_ITER + 1)]
    assert [r.llm_runde for r in v.runden] == [1, 2, 3, 4]


def test_warm_start_geht_in_den_ersten_prompt_ein() -> None:
    embs, texte = _welt()
    protokoll: list[str] = []
    verfeinern(
        seg_embs=embs, texte=texte, embed=_embed_fest(),
        frage_modell=_fester_anbieter([("A", "eins."), ("B", "zwei.")], protokoll),
        n_clusters=2,
        warm_start=[{"name": "Altes Thema", "description": "So stand es vorher da."},
                    {"name": "Zweites", "description": "Und so das zweite."}],
    )
    assert "Vorherige Beschreibung" in protokoll[0]
    assert "So stand es vorher da." in protokoll[0]


def test_ohne_warm_start_kein_vorher_abschnitt() -> None:
    embs, texte = _welt()
    protokoll: list[str] = []
    verfeinern(seg_embs=embs, texte=texte, embed=_embed_fest(),
               frage_modell=_fester_anbieter([("A", "eins."), ("B", "zwei.")], protokoll),
               n_clusters=2)
    assert "Vorherige Beschreibung" not in protokoll[0]


def test_eingefrorene_bleiben_im_prompt() -> None:
    """Der Prompt ist kontrastiv: eingefrorene Gruppen bleiben zum Abgrenzen drin."""
    embs, texte = _welt()
    protokoll: list[str] = []
    verfeinern(seg_embs=embs, texte=texte, embed=_embed_fest(),
               frage_modell=_fester_anbieter([("A", "eins."), ("B", "zwei.")], protokoll),
               n_clusters=2)
    assert len(protokoll) >= 2
    assert "Gruppe 1 Keywords" in protokoll[-1]
    assert "Gruppe 2 Keywords" in protokoll[-1]


def test_token_und_kategorien_kommen_heraus() -> None:
    embs, texte = _welt()
    v = verfeinern(seg_embs=embs, texte=texte, embed=_embed_fest(),
                   frage_modell=_fester_anbieter([("Flughafenbau", "Termine."),
                                                  ("Klagen", "Gerichte.")]),
                   n_clusters=2)
    assert v.in_tokens == 100 * v.llm_calls
    assert v.out_tokens == 20 * v.llm_calls
    assert [k["name"] for k in v.kategorien] == ["Flughafenbau", "Klagen"]
    assert all(len(k["keywords"]) <= 3 for k in v.kategorien)


# ── Kein Netz, keine Datei im Kern ────────────────────────────────────────────

def test_kern_kennt_weder_netz_noch_datei_noch_ausgabe() -> None:
    import ast

    quelle = (ROOT / "src" / "neu" / "taxonomie" / "kern.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Call):
            name = ast.unparse(knoten.func)
            assert name != "print", f"print in kern.py, Zeile {knoten.lineno}"
            assert name != "open", f"Dateizugriff in kern.py, Zeile {knoten.lineno}"
        if isinstance(knoten, (ast.Import, ast.ImportFrom)):
            modul = getattr(knoten, "module", None) or ""
            namen = [a.name for a in knoten.names]
            for verboten in ("sqlite3", "requests", "anthropic", "httpx", "voyageai"):
                assert verboten not in modul and verboten not in namen, verboten
