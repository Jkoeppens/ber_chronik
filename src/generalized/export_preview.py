"""
export_preview.py — HTML-Vorschau mit vertikaler Zeitleiste und Korrektur-Loop

Input:  data/interim/generalized/anchors_interpolated.json
        data/interim/generalized/overrides.json  (optional, wird als Startzustand geladen)
Output: data/interim/generalized/preview.html

Layout:
  Sticky Header: Statistik + Filter-Buttons + Quellen-Dropdown + Override-Buttons
  Linke Spalte (sticky): Zeitleiste 1780–1920 mit Scroll-Marker
  Rechte Spalte (scrollbar): Karten chronologisch nach time_from

Korrektur-Loop:
  Jede Karte hat einen „Bearbeiten"-Button. Das Inline-Formular erlaubt Text,
  Zeitraum, Undatierbar-Flag und eine Notiz anzupassen. Korrekturen werden im
  Browser gesammelt und als overrides.json heruntergeladen.
"""

import argparse
import json
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

from src.generalized.utils import render_template as _render_template  # noqa: E402

# 10-Farben-Palette für Kategorien (Reihenfolge = Taxonomie-Reihenfolge)
CAT_PALETTE = [
    "#0891b2", "#d97706", "#16a34a", "#9333ea",
    "#dc2626", "#0d9488", "#c2410c", "#4f46e5",
    "#0369a1", "#b45309",
]


PREC_ORDER = ["exact", "heading", "event", "interpolated", "decade", "manual", None]
PREC_LABEL = {
    "exact": "exact", "heading": "heading", "event": "event",
    "interpolated": "interpolated", "decade": "decade",
    "manual": "manual", None: "undated",
}
PREC_COLOR = {
    "exact": "#2563eb", "heading": "#0891b2", "event": "#16a34a",
    "interpolated": "#9ca3af", "decade": "#d97706",
    "manual": "#7c3aed", None: "#dc2626",
}

# ── Card sort key: undated last, then by time_from, then time_to ───────────────
def sort_key(s: dict):
    tf = s.get("time_from")
    tt = s.get("time_to") or tf or 0
    return (0 if tf is not None else 1, tf or 9999, tt)


def time_label(s: dict) -> str:
    tf, tt = s.get("time_from"), s.get("time_to")
    if tf is None:
        return "undatiert"
    if tt is None or tt == tf:
        return str(tf)
    return f"{tf}\u2013{tt}"


def build_quality_report(
    segments: list[dict],
    classifications: dict[str, dict],
    taxonomy: list[dict] | None = None,
) -> dict:
    """Berechnet Kategorieverteilung und Qualitätswarnungen."""
    total = len(segments)
    if not total:
        return {"warnings": [], "categories": {}, "low_confidence": 0,
                "low_confidence_pct": 0.0, "total": 0}

    cat_counts: dict[str, int] = {}
    low_conf = 0
    for seg in segments:
        cls = classifications.get(seg.get("segment_id", ""), {})
        cat = cls.get("category") or "Ohne Kategorie"
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if cls.get("confidence") == "low":
            low_conf += 1

    cat_pct = {cat: round(n / total * 100, 1) for cat, n in
               sorted(cat_counts.items(), key=lambda x: -x[1])}
    low_conf_pct = round(low_conf / total * 100, 1)

    warnings: list[str] = []
    catch_all = {"anderes", "sonstiges", "andere", "other", "misc", "quellenm", "ohne kategorie"}
    for cat, pct in cat_pct.items():
        if pct < 2.0:
            warnings.append(f'Kategorie "{cat}" hat nur {pct} % Anteil (< 2 %)')
        if any(kw in cat.lower() for kw in catch_all) and pct > 15:
            warnings.append(f'Catch-all-Kategorie "{cat}" hat {pct} % Anteil (> 15 %)')
    if low_conf_pct > 15:
        warnings.append(
            f"{low_conf} Einträge mit niedriger Konfidenz ({low_conf_pct} %)"
        )

    return {
        "warnings":           warnings,
        "categories":         cat_pct,
        "low_confidence":     low_conf,
        "low_confidence_pct": low_conf_pct,
        "total":              total,
    }


def _build_css() -> str:
    return f"""\
/* ── Tokens ── */
:root{{
  --c-bg:#f4f3f0;--c-surface:#fff;
  --c-border:#e5e2dc;--c-border-ui:#e0ddd8;
  --c-text:#1a1a1a;--c-text-2:#555;--c-text-3:#888;--c-text-4:#aaa;
  --c-primary:#6d28d9;--c-primary-h:#5b21b6;
  --c-primary-tint:#ede9fe;--c-primary-bg:#faf5ff;--c-primary-ring:#c4b5fd;
  --c-success:#16a34a;--c-danger:#dc2626;
  --c-danger-bg:#fef2f2;--c-danger-border:#fca5a5;
  --c-code-bg:#f8fafc;--c-code-border:#e2e8f0;
}}
/* ── Reset & base ── */
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html{{font-size:13px}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:var(--c-bg);color:var(--c-text);height:100vh;display:flex;flex-direction:column;overflow:hidden}}

/* ── Header ── */
#header{{flex:0 0 auto;background:var(--c-surface);border-bottom:1px solid var(--c-border-ui);
         padding:10px 24px;display:flex;flex-direction:column;gap:8px;z-index:10}}
#stats{{display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.stat-pill{{display:flex;flex-direction:column;align-items:center;padding:4px 10px;
            background:#f9f8f5;border:1px solid var(--c-border-ui);border-radius:4px;min-width:64px}}
.sv{{font-size:16px;font-weight:700;line-height:1.2}}
.sl{{font-size:10px;color:var(--c-text-3);text-transform:uppercase;letter-spacing:.04em}}
#controls{{display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.fb{{padding:4px 10px;border:1px solid var(--c-border);border-radius:20px;background:var(--c-surface);
     cursor:pointer;font-size:11px;color:var(--c-text-2);transition:background .15s,color .15s}}
.fb.active{{background:var(--fc,#333);color:#fff;border-color:var(--fc,#333)}}
.fb[data-prec=""]{{--fc:#333}}
.fc{{font-size:10px;opacity:.8}}
#src-filter{{padding:4px 8px;border:1px solid var(--c-border);border-radius:4px;font-size:11px;
             max-width:280px;background:var(--c-surface)}}
#override-btns{{display:flex;gap:6px;margin-left:auto}}
#btn-export{{padding:4px 10px;border:1px solid var(--c-primary);border-radius:4px;
             background:var(--c-surface);color:var(--c-primary);font-size:11px;cursor:pointer;
             transition:background .15s,color .15s}}
#btn-export:disabled{{border-color:var(--c-border);color:var(--c-text-4);cursor:default}}
#btn-export:not(:disabled):hover{{background:var(--c-primary);color:#fff}}
#btn-recompute{{padding:4px 10px;border:1px solid var(--c-border);border-radius:4px;
                background:var(--c-surface);color:var(--c-text-2);font-size:11px;cursor:pointer;
                transition:background .15s}}
#btn-recompute:not(:disabled):hover{{background:#f3f4f6}}
#btn-recompute:disabled{{color:var(--c-text-4);cursor:default}}
#recompute-log{{font-size:11px;color:#374151;background:var(--c-code-bg);
                border:1px solid var(--c-code-border);border-radius:4px;padding:6px 10px;display:none;
                font-family:ui-monospace,monospace;white-space:pre-wrap;max-height:120px;overflow-y:auto}}
#recompute-log.error{{background:var(--c-danger-bg);border-color:var(--c-danger-border);color:var(--c-danger)}}
#cat-controls{{display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding-top:2px}}
.cf{{padding:3px 9px;border:1px solid var(--c-border);border-radius:20px;background:var(--c-surface);
     cursor:pointer;font-size:11px;color:var(--c-text-2);transition:background .15s,color .15s}}
.cf.active{{background:var(--fc,#333);color:#fff;border-color:var(--fc,#333)}}
.cf[data-cat=""]{{--fc:#333}}
#quality-report{{display:none;background:#fffbeb;border:1px solid #fcd34d;border-radius:4px;
                 padding:6px 12px;font-size:11px}}
#quality-report summary{{cursor:pointer;font-weight:600;color:#92400e;user-select:none}}
.qr-warn{{color:#b45309;margin-top:3px}}
.qr-low{{color:var(--c-text-3);margin-top:3px}}

/* ── Main layout ── */
#main{{flex:1 1 0;display:flex;overflow:hidden}}

/* ── Timeline ── */
#timeline{{flex:0 0 72px;position:relative;background:#fff;border-right:1px solid #e0ddd8;
           overflow:hidden;user-select:none}}
.tick{{position:absolute;left:0;right:0;display:flex;align-items:center;transform:translateY(-50%);
       cursor:pointer}}
.tick:hover .tick-yr{{color:#2563eb}}
.tick-yr{{font-size:10px;color:#bbb;width:36px;text-align:right;padding-right:4px;flex-shrink:0;
          transition:color .15s}}
.tick-line{{flex:1;height:1px;background:#eee}}
.tick[data-decade] .tick-yr{{color:#888;font-weight:600}}
.tick[data-decade] .tick-line{{background:#ccc}}
#tl-marker{{position:absolute;left:0;right:0;height:2px;background:#2563eb;
            transition:top .2s ease;pointer-events:none;z-index:2}}
#tl-marker::before{{content:"";position:absolute;left:36px;top:-4px;
                    width:8px;height:8px;background:#2563eb;border-radius:50%}}
#tl-year-label{{position:absolute;right:4px;font-size:10px;font-weight:700;color:#2563eb;
                transition:top .2s ease;transform:translateY(-100%);pointer-events:none;z-index:2}}

/* ── Cards panel ── */
#cards{{flex:1 1 0;overflow-y:auto;padding:12px 14px;display:flex;flex-direction:column;gap:8px}}

/* ── Card ── */
.card{{background:var(--c-surface);border-radius:6px;border:1px solid var(--c-border);
       border-left:4px solid var(--prec-color,#ccc);
       padding:8px 12px;cursor:default;position:relative;
       transition:box-shadow .15s}}
.card:hover{{box-shadow:0 2px 8px rgba(0,0,0,.08)}}
.card.hidden{{display:none}}
.card.has-override{{box-shadow:0 0 0 2px #7c3aed33}}
.card-source{{font-size:10px;color:var(--c-text-4);margin-bottom:2px;
              white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:calc(100% - 60px)}}
.card-meta{{display:flex;align-items:center;gap:6px;margin-bottom:5px}}
.card-time{{font-size:13px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--c-text)}}
.badge{{font-size:9px;text-transform:uppercase;letter-spacing:.05em;padding:1px 5px;
        border-radius:3px;color:#fff;background:var(--prec-color,#999)}}
.cat-badge{{font-size:9px;padding:1px 6px;border-radius:3px;color:#fff;
           white-space:nowrap;max-width:140px;overflow:hidden;text-overflow:ellipsis}}
.card-text{{font-size:12px;line-height:1.55;color:var(--c-text-2)}}
.card-page{{font-size:10px;color:var(--c-text-4);margin-left:4px}}
.card-note{{font-size:10px;color:var(--c-primary);margin-top:4px;font-style:italic}}

/* ── Edit button ── */
.btn-edit{{position:absolute;top:6px;right:8px;padding:2px 7px;
           border:1px solid #d1d5db;border-radius:3px;background:var(--c-code-bg);
           color:var(--c-text-2);font-size:10px;cursor:pointer;line-height:1.4;
           transition:background .12s,border-color .12s}}
.btn-edit:hover{{background:var(--c-primary-tint);border-color:var(--c-primary);color:var(--c-primary)}}
.btn-edit.active{{background:var(--c-primary);border-color:var(--c-primary);color:#fff}}

/* ── Inline edit form ── */
.edit-form{{margin-top:8px;padding:10px;background:#f9f8f5;border-radius:4px;
            border:1px solid var(--c-border-ui);display:flex;flex-direction:column;gap:8px}}
.ef-row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.ef-label{{font-size:10px;color:var(--c-text-3);min-width:50px}}
.ef-textarea{{width:100%;font-size:12px;line-height:1.5;padding:5px 7px;
              border:1px solid #d1d5db;border-radius:3px;resize:vertical;min-height:60px;
              font-family:inherit}}
.ef-textarea:focus{{border-color:var(--c-primary);outline:none}}
.ef-input{{padding:3px 7px;border:1px solid #d1d5db;border-radius:3px;font-size:12px;width:72px}}
.ef-input:focus{{border-color:var(--c-primary);outline:none}}
.ef-input-wide{{width:100%;padding:3px 7px;border:1px solid #d1d5db;border-radius:3px;font-size:12px}}
.ef-check{{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--c-text-2);cursor:pointer}}
.ef-actions{{display:flex;gap:6px}}
.btn-save{{padding:4px 12px;background:var(--c-primary);color:#fff;border:none;
           border-radius:3px;font-size:11px;cursor:pointer;font-family:inherit}}
.btn-save:hover{{background:var(--c-primary-h)}}
.btn-cancel{{padding:4px 10px;background:var(--c-surface);color:var(--c-text-2);
             border:1px solid var(--c-border);border-radius:3px;font-size:11px;cursor:pointer;font-family:inherit}}
.btn-cancel:hover{{background:#f3f4f6}}

/* ── empty state ── */
#empty{{display:none;padding:40px;text-align:center;color:#999;font-size:13px}}"""


def _build_body(
    stats_pills: str,
    filter_btns: str,
    source_opts: str,
    tick_labels: str,
    cat_filter_btns: str,
) -> str:
    return f"""\
<div id="header">
  <div id="stats">{stats_pills}</div>
  <div id="controls">
    {filter_btns}
    <select id="src-filter">{source_opts}</select>
    <div id="override-btns">
      <button id="btn-export" disabled>Overrides exportieren</button>
      <button id="btn-recompute">Neu berechnen</button>
    </div>
  </div>
  <div id="recompute-log"></div>
  <div id="cat-controls">{cat_filter_btns}</div>
  <details id="quality-report">
    <summary>Qualitätsbericht</summary>
    <div id="qr-body"></div>
  </details>
</div>

<div id="main">
  <div id="timeline">
    {tick_labels}
    <div id="tl-marker"></div>
    <div id="tl-year-label"></div>
  </div>
  <div id="cards">
    <div id="empty">Keine Segmente mit diesen Filtern.</div>
  </div>
</div>"""


def _build_js(
    js_data: str,
    js_initial_overrides: str,
    js_cat_colors: str,
    js_quality_report: str,
    year_min: int,
    year_max: int,
    js_categories: str = "[]",
) -> str:
    return _render_template(
        "preview.js",
        js_data=js_data,
        js_initial_overrides=js_initial_overrides,
        js_cat_colors=js_cat_colors,
        js_quality_report=js_quality_report,
        year_min=str(year_min),
        year_max=str(year_max),
        js_categories=js_categories,
    )


def build_html(segments: list[dict], initial_overrides: list[dict],
               classifications: dict[str, dict] | None = None,
               taxonomy: list[dict] | None = None,
               title: str | None = None) -> str:
    page_title = title or "Dokument-Preview"
    segments = sorted(segments, key=sort_key)

    # ── Category colour map (Reihenfolge aus Taxonomie, sonst alphabetisch) ──
    classifications = classifications or {}
    if taxonomy:
        ordered_cats = [c["name"] for c in taxonomy if c.get("name")]
        # Kategorien im Daten die nicht in Taxonomie → hinten anhängen
        data_cats = sorted({v["category"] for v in classifications.values() if v.get("category")})
        for c in data_cats:
            if c not in ordered_cats:
                ordered_cats.append(c)
    else:
        ordered_cats = sorted({v["category"] for v in classifications.values() if v.get("category")})
    cat_colors: dict[str, str] = {
        cat: CAT_PALETTE[i % len(CAT_PALETTE)] for i, cat in enumerate(ordered_cats)
    }
    js_cat_colors = json.dumps(cat_colors, ensure_ascii=False)

    # ── Category counts (für Filterbuttons) ──────────────────────────────────
    cat_counts: dict[str, int] = {}
    for v in classifications.values():
        c = v.get("category")
        if c:
            cat_counts[c] = cat_counts.get(c, 0) + 1

    # ── Qualitätsbericht ──────────────────────────────────────────────────────
    quality_report = build_quality_report(segments, classifications, taxonomy)
    js_quality_report = json.dumps(quality_report, ensure_ascii=False)

    # ── Zeitachse: aus Daten berechnen, auf volle Dekaden runden ─────────────
    years = [s["time_from"] for s in segments if s.get("time_from") is not None]
    years += [s["time_to"]  for s in segments if s.get("time_to")   is not None]
    if years:
        YEAR_MIN = (min(years) // 10) * 10
        YEAR_MAX = ((max(years) + 9) // 10) * 10
    else:
        YEAR_MIN, YEAR_MAX = 1900, 2000

    # ── Stats ─────────────────────────────────────────────────────────────────
    total = len(segments)
    prec_counts: dict = {p: 0 for p in PREC_ORDER}
    for s in segments:
        prec_counts[s.get("precision")] = prec_counts.get(s.get("precision"), 0) + 1
    def _src_name(s: dict) -> str:
        src = s.get("source") or ""
        return src.get("name", "") if isinstance(src, dict) else src

    sources = sorted({_src_name(s) for s in segments}, key=lambda x: x.lower())
    n_sources = len(sources)

    # ── JSON data for JS ──────────────────────────────────────────────────────
    js_data = json.dumps([
        {
            "id":         s["segment_id"],
            "source":     s.get("source") or "",
            "date_raw":   s.get("date_raw"),
            "text":       s.get("text", ""),
            "time_from":  s.get("time_from"),
            "time_to":    s.get("time_to"),
            "precision":  s.get("precision"),
            "page":       s.get("page"),
            "category":   classifications.get(s["segment_id"], {}).get("category"),
            "confidence": classifications.get(s["segment_id"], {}).get("confidence"),
        }
        for s in segments
    ], ensure_ascii=False)

    js_initial_overrides = json.dumps(
        {o["segment_id"]: o for o in initial_overrides},
        ensure_ascii=False,
    )

    js_categories = json.dumps(ordered_cats, ensure_ascii=False)

    # ── Stats bar HTML ────────────────────────────────────────────────────────
    def stat_pill(label, value, color=""):
        style = f' style="border-left:3px solid {color}"' if color else ""
        return f'<div class="stat-pill"{style}><span class="sv">{value}</span><span class="sl">{label}</span></div>'

    stats_pills = stat_pill("gesamt", total)
    for p in PREC_ORDER:
        n = prec_counts.get(p, 0)
        stats_pills += stat_pill(PREC_LABEL[p], n, PREC_COLOR[p])
    stats_pills += stat_pill("Quellen", n_sources)

    # ── Filter buttons ────────────────────────────────────────────────────────
    filter_btns = '<button class="fb active" data-prec="">Alle</button>'
    for p in PREC_ORDER:
        label = PREC_LABEL[p]
        col   = PREC_COLOR[p]
        val   = p if p is not None else "null"
        filter_btns += (
            f'<button class="fb" data-prec="{val}" '
            f'style="--fc:{col}">{label} '
            f'<span class="fc">{prec_counts.get(p,0)}</span></button>'
        )

    # ── Category filter buttons ───────────────────────────────────────────────
    cat_filter_btns = '<button class="cf active" data-cat="">Alle Kategorien</button>'
    for cat in ordered_cats:
        col = cat_colors.get(cat, "#888")
        n   = cat_counts.get(cat, 0)
        cat_filter_btns += (
            f'<button class="cf" data-cat="{escape(cat)}" style="--fc:{col}">'
            f'{escape(cat)} <span class="fc">{n}</span></button>'
        )

    # ── Source dropdown ───────────────────────────────────────────────────────
    source_opts = '<option value="">Alle Quellen</option>'
    for src in sources:
        short = src[:60] + ("…" if len(src) > 60 else "")
        source_opts += f'<option value="{escape(src)}">{escape(short)}</option>'

    # ── Timeline tick HTML (rendered by JS, but axis labels in HTML) ──────────
    tick_labels = ""
    for yr in range(YEAR_MIN, YEAR_MAX + 1, 10):
        pct = (yr - YEAR_MIN) / (YEAR_MAX - YEAR_MIN) * 100
        tick_labels += (
            f'<div class="tick" style="top:{pct:.2f}%" data-year="{yr}">'
            f'<span class="tick-yr">{yr}</span>'
            f'<span class="tick-line"></span>'
            f'</div>'
        )

    css  = _build_css()
    body = _build_body(stats_pills, filter_btns, source_opts, tick_labels, cat_filter_btns)
    js   = _build_js(
        js_data, js_initial_overrides, js_cat_colors, js_quality_report,
        YEAR_MIN, YEAR_MAX, js_categories,
    )
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{page_title}</title>
<style>
{css}
</style>
</head>
<body>
{body}
<script>
{js}
</script>
</body>
</html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="HTML-Vorschau generieren")
    ap.add_argument("--project",  required=True, help="Projektname (z.B. ber, damaskus)")
    ap.add_argument("--document", required=True, help="Dokument-ID (z.B. main)")
    args = ap.parse_args()

    project_dir     = ROOT / "data" / "projects" / args.project
    doc_dir         = project_dir / "documents" / args.document
    input_path      = doc_dir / "anchors_interpolated.json"
    output_path     = doc_dir / "preview.html"
    overrides_path  = doc_dir / "overrides.json"
    classified_path = doc_dir / "classified.json"
    config_path     = project_dir / "config.json"

    if not input_path.exists():
        print(f"Datei nicht gefunden: {input_path}", file=sys.stderr)
        sys.exit(1)

    segments = json.loads(input_path.read_text(encoding="utf-8"))

    initial_overrides: list[dict] = []
    if overrides_path.exists():
        initial_overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        print(f"← {overrides_path}  ({len(initial_overrides)} Overrides geladen)")

    classifications: dict[str, dict] = {}
    if classified_path.exists():
        for r in json.loads(classified_path.read_text(encoding="utf-8")):
            if r.get("segment_id"):
                classifications[r["segment_id"]] = r
        print(f"← {classified_path}  ({len(classifications)} Klassifizierungen geladen)")

    # Taxonomie von Projektebene; Fallback: per-doc taxonomy_proposal.json
    taxonomy: list[dict] | None = None
    if config_path.exists():
        taxonomy = json.loads(config_path.read_text(encoding="utf-8")).get("taxonomy") or None
    if taxonomy is None:
        fallback = doc_dir / "taxonomy_proposal.json"
        if fallback.exists():
            taxonomy = json.loads(fallback.read_text(encoding="utf-8"))
    if taxonomy is not None:
        print(f"← taxonomy  ({len(taxonomy)} Kategorien geladen)")

    page_title: str | None = None
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            page_title = cfg.get("title") or None
        except Exception:
            pass

    html = build_html(segments, initial_overrides, classifications, taxonomy, title=page_title)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"→ {output_path}  ({len(segments)} Segmente, {len(html):,} Bytes)")


if __name__ == "__main__":
    main()
