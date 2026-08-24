"""Build one self-contained interactive Plotly HTML dashboard from the central trending CSV.

Replaces `render_bump_chart_interactive` and its helpers from the retired
notebooks/kestrel-trends_bumpchart-*.ipynb pipeline — already debugged across 20
notebook versions (see README.md changelog). PNG rendering is dropped entirely per the
Phase 3 migration decision: HTML-only dashboard, no matplotlib dependency.

Growth-bound decision: the JSON blob embedded in the HTML is built from only the last
LOOKBACK_DAYS (default 90) of df, not the full history — the old notebook pipeline
embedded its *entire* history on every render, which is exactly the kind of unbounded
growth this migration is meant to fix, just at the HTML-payload layer instead of the
git-history layer. The existing "All" time-range dropdown then means "all embedded data"
(up to LOOKBACK_DAYS) rather than all-time-ever; no JS changes needed for this since the
dropdown already filters client-side from whatever JSON got embedded. Full history stays
safe in the CSV (git-tracked) regardless of what a given report build embeds.
"""
import colorsys
import hashlib
import json
import logging
import re
from pathlib import Path

import pandas as pd

from trending.scraper import CSV_PATH, REPO_ROOT

log = logging.getLogger("trending.report")

LOOKBACK_DAYS = 90
TOP_N = 15  # matches the notebook-era default (README "Config cell" table)
PALETTE_SIZE = 150
OUT_PATH = REPO_ROOT / "dataset" / "trends" / "latest_interactive.html"


def build_pumpkin_palette(n: int = 150) -> list[str]:
    """Preset palette of n warm-autumn hex colors anchored on Pumpkin (#FF7518).

    Grid: 6 hue x 5 saturation x 5 lightness = 150. Hue [4,69], sat [70,100]%, lit [35,65]%.
    colorsys.hls_to_rgb(h, l, s) takes HLS order (not HSL).
    """
    assert n == 150, f"Grid 6x5x5=150 exactly; got n={n}."
    n_h, n_s, n_l = 6, 5, 5
    hue_min, hue_max = 4 / 360, 69 / 360
    sat_min, sat_max = 0.70, 1.00
    lit_min, lit_max = 0.35, 0.65
    return _grid_palette(n_h, n_s, n_l, hue_min, hue_max, sat_min, sat_max, lit_min, lit_max)


def build_pumpkin_palette_dark(n: int = 150) -> list[str]:
    """Dark-mode variant: same hue/sat range, lightness 55-82% so colors stay vivid on #121212."""
    assert n == 150, f"Grid 6x5x5=150 exactly; got n={n}."
    n_h, n_s, n_l = 6, 5, 5
    hue_min, hue_max = 4 / 360, 69 / 360
    sat_min, sat_max = 0.70, 1.00
    lit_min, lit_max = 0.55, 0.82
    return _grid_palette(n_h, n_s, n_l, hue_min, hue_max, sat_min, sat_max, lit_min, lit_max)


def _grid_palette(n_h, n_s, n_l, hue_min, hue_max, sat_min, sat_max, lit_min, lit_max) -> list[str]:
    hues = [hue_min + i * (hue_max - hue_min) / (n_h - 1) for i in range(n_h)]
    sats = [sat_min + i * (sat_max - sat_min) / (n_s - 1) for i in range(n_s)]
    lits = [lit_min + i * (lit_max - lit_min) / (n_l - 1) for i in range(n_l)]
    palette: list[str] = []
    for h in hues:
        for s in sats:
            for l in lits:
                r, g, b = colorsys.hls_to_rgb(h, l, s)
                palette.append(f"#{min(255,int(r*255)):02x}{min(255,int(g*255)):02x}{min(255,int(b*255)):02x}")
    return palette


def get_topic_color(name_norm: str, palette: list[str]) -> str:
    """Stable color for name_norm: MD5(name_norm) mod len(palette) - same topic, same color always."""
    idx = int(hashlib.md5(name_norm.encode()).hexdigest(), 16) % len(palette)
    return palette[idx]


def shorten_hour_label(label: str) -> str:
    """'Sun Jul 19 2026 16:40:28 GMT+0000 (...)' -> '16:40Z'. Falls back to first 12 chars."""
    m = re.search(r"(\d{1,2}:\d{2}):\d{2}\s*GMT", str(label))
    return (m.group(1) + "Z") if m else str(label)[:12]


def format_tz_label(raw_label: str) -> str:
    """3-line x-axis label from a JS Date string: UTC / GMT+8 / GMT+7, e.g. '16:40Z\\n00:40+8\\n23:40+7'."""
    m = re.search(r"(\d{1,2}):(\d{2}):\d{2}\s*GMT", str(raw_label))
    if not m:
        return shorten_hour_label(raw_label)
    total_min = int(m.group(1)) * 60 + int(m.group(2))

    def _fmt(mins: int) -> str:
        return f"{(mins // 60) % 24:02d}:{mins % 60:02d}"

    return f"{_fmt(total_min)}Z\n{_fmt(total_min + 480)}+8\n{_fmt(total_min + 420)}+7"


def parse_hour_label_ts(lbl: str) -> int:
    """'Wed Jul 22 2026 23:39:12 GMT+0000 (...)' -> Unix timestamp. 0 on parse failure."""
    from datetime import datetime
    try:
        core = lbl.split(" (")[0]
        dt = datetime.strptime(core, "%a %b %d %Y %H:%M:%S GMT%z")
        return int(dt.timestamp())
    except Exception:
        log.warning("Could not parse hour_label as timestamp: %r", lbl)
        return 0


def build_rank_pivot(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Pivot df into a (name_norm x hour_label) rank matrix, filtered to top_n.

    Columns ordered oldest-left -> newest-right via chronological sort on parse_hour_label_ts
    (hour_label strings sort lexicographically by weekday name, NOT chronologically once the
    data spans a weekday boundary). Only topics reaching rank <= top_n in >=1 hour included.
    Rows ordered by best (lowest) rank across all hours.
    """
    pivot = df.pivot_table(index="name_norm", columns="hour_label", values="rank", aggfunc="min")
    ordered_cols = sorted(pivot.columns, key=parse_hour_label_ts)
    pivot = pivot[ordered_cols]
    pivot = pivot.loc[pivot.min(axis=1) <= top_n]
    pivot = pivot.loc[pivot.min(axis=1).sort_values().index]
    return pivot


def get_first_last_positions(y_vals) -> set:
    """{first_idx, last_idx} of non-NaN/non-None positions in y_vals - declutters labels to
    first+last appearance only, same rule the static PNG used to apply."""
    non_nan = [xi for xi, yv in enumerate(y_vals) if yv is not None and not (isinstance(yv, float) and pd.isna(yv))]
    if not non_nan:
        return set()
    return {non_nan[0], non_nan[-1]}


def render_bump_chart_interactive(
    df_combined: pd.DataFrame,
    palette_light: list[str],
    palette_dark: list[str],
    out_path: Path,
    top_n: int = 30,
) -> None:
    """Generate a fully self-contained interactive bump chart HTML from df_combined.

    df_combined should already be trimmed to whatever lookback window the caller wants
    embedded (see LOOKBACK_DAYS) - this function embeds exactly what it's given.

    Features (see README.md "Interactive chart" section for the full changelog):
    rank-over-time bump chart, dynamic pixel width,
    boxed first/last-appearance labels, day-boundary markers, dual top+bottom
    UTC/GMT+8/GMT+7 x-axes, quick + calendar custom time-range picker, per-topic sidebar
    checkboxes + search, dim-opacity + click-to-pin with bring-to-front, light/dark
    toggle persisted via localStorage, persistent topic-stats table, download CSV,
    "copy search query" button. No PNG buttons/links - PNGs no longer exist in this
    pipeline.
    """
    if df_combined is None or df_combined.empty:
        log.warning("df_combined is empty — skipping interactive chart render")
        return

    pivot = build_rank_pivot(df_combined, top_n)
    hour_cols = list(pivot.columns)
    topic_list = list(pivot.index)
    n_hours = len(hour_cols)
    n_topics = len(topic_list)
    if n_hours == 0 or n_topics == 0:
        log.warning("Empty pivot — skipping interactive chart render")
        return

    hour_ts = [parse_hour_label_ts(h) for h in hour_cols]
    max_ts = max(hour_ts) if hour_ts else 0

    tc_col = "tweet_count" if "tweet_count" in df_combined.columns else None
    topics_json = []
    for name_norm in topic_list:
        y_vals = pivot.loc[name_norm].values
        cl = get_topic_color(name_norm, palette_light)
        cd = get_topic_color(name_norm, palette_dark)
        grp = df_combined[df_combined["name_norm"] == name_norm]
        nm = grp["name"].mode()
        display = str(nm.iloc[0]) if not nm.empty else name_norm
        bp_s = grp["best_position"].dropna() if "best_position" in grp.columns else pd.Series(dtype="float64")
        tt_s = grp["total_tweets"].dropna() if "total_tweets" in grp.columns else pd.Series(dtype="float64")
        bp = int(bp_s.min()) if not bp_s.empty else None
        tt = int(tt_s.max()) if not tt_s.empty else None
        pts = []
        for hi, (yv, hcol) in enumerate(zip(y_vals, hour_cols)):
            if yv is None or (isinstance(yv, float) and pd.isna(yv)):
                continue
            tc = None
            if tc_col:
                m = grp[grp["hour_label"] == hcol][tc_col]
                if not m.empty and pd.notna(m.iloc[0]):
                    try:
                        tc = int(m.iloc[0])
                    except (ValueError, TypeError):
                        tc = None
            pts.append([hi, int(yv), tc])
        topics_json.append({"n": name_norm, "d": display, "cl": cl, "cd": cd, "bp": bp, "tt": tt, "pts": pts})

    hours_json = [{"l": format_tz_label(lbl).replace("\n", "<br>"), "ts": ts} for lbl, ts in zip(hour_cols, hour_ts)]

    dataset = {"topN": top_n, "maxTs": max_ts, "hours": hours_json, "topics": topics_json}
    data_json = json.dumps(dataset, separators=(",", ":"), ensure_ascii=False)

    import plotly.offline as _plo
    plotly_js = f"<script>{_plo.get_plotlyjs()}</script>"

    # Inline the logo SVG so the exported HTML stays fully offline/self-contained.
    _logo_path = REPO_ROOT / "src" / "logo" / "lokentra.dev-logo.svg"
    logo_svg = _logo_path.read_text(encoding="utf-8").strip()
    logo_svg = re.sub(r'<svg\s+width="\d+"\s+height="\d+"', "<svg", logo_svg, count=1)

    H = []
    H.append('<!DOCTYPE html><html lang="en">')
    H.append('<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">')
    H.append('<title>Kestrel - Trending (X/Twitter)</title>')
    H.append('<link rel="preconnect" href="https://fonts.cdnfonts.com" crossorigin>')
    H.append('<link href="https://fonts.cdnfonts.com/css/alte-haas-grotesk" rel="stylesheet">')
    H.append(plotly_js)

    H.append('<style>')
    H.append(':root{--bg:#09090b;--bg2:#18181b;--fg:#fafafa;--fg2:#a1a1aa;--bd:#27272a;'
             '--acc:#3b82f6;--ibg:#18181b;--ibd:#3f3f46;--btn:#27272a;--btnh:#3f3f46;'
             '--st:#3f3f46;--radius:2px;--sh:0 1px 2px rgba(0,0,0,.4)}')
    H.append('body.light{--bg:#fff;--bg2:#fafafa;--fg:#09090b;--fg2:#71717a;--bd:#e4e4e7;'
             '--acc:#2563eb;--ibg:#fff;--ibd:#d4d4d8;--btn:#f4f4f5;--btnh:#e4e4e7;'
             '--st:#d4d4d8;--sh:0 1px 2px rgba(0,0,0,.08)}')
    H.append('*{box-sizing:border-box;margin:0;padding:0}')
    H.append("body{font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
             'background:var(--bg);color:var(--fg);display:flex;flex-direction:column;height:100vh;overflow:hidden}')
    H.append('#tb{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:10px;padding:12px 16px;'
             'background:var(--bg);border-bottom:1px solid var(--bd);flex-shrink:0;flex-wrap:wrap}')
    H.append('#tb h1{font-size:15px;font-weight:600;letter-spacing:-.01em;margin-right:4px;white-space:nowrap}')
    H.append('#brand{display:flex;align-items:center;gap:11px;margin-right:8px}')
    H.append('#lka{display:flex;align-items:center;line-height:0}')
    H.append('#lka svg{height:22px;width:auto;display:block}')
    H.append('#rng{font-family:inherit;font-size:13px;background:var(--btn);color:var(--fg);'
             'border:1px solid var(--bd);border-radius:var(--radius);padding:6px 10px;cursor:pointer}')
    H.append('.btn{font-family:inherit;font-size:13px;font-weight:500;background:var(--btn);color:var(--fg);'
             'border:1px solid var(--bd);border-radius:var(--radius);padding:6px 12px;cursor:pointer;transition:background .15s;'
             'text-decoration:none;display:inline-block}')
    H.append('.btn:hover{background:var(--btnh)}')
    H.append('.btn[aria-disabled=true]{display:none}')
    H.append('#tb .sp{flex:1}')
    H.append('#drngWrap{position:relative}')
    H.append('#drngBtn{font-family:inherit;font-size:13px;background:var(--btn);color:var(--fg);'
             'border:1px solid var(--bd);border-radius:var(--radius);padding:6px 10px;cursor:pointer;'
             'max-width:460px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}')
    H.append('#drngBtn.qsrc{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}')
    H.append('#drngPanel{position:absolute;top:calc(100% + 4px);left:0;background:var(--bg2);'
             'border:1px solid var(--bd);border-radius:var(--radius);padding:14px;box-shadow:var(--sh);'
             'z-index:50;display:flex;flex-direction:column;gap:10px}')
    H.append('#drngPanel[hidden]{display:none}')
    H.append('.ddcals{display:flex;gap:14px}')
    H.append('.cal{width:190px}')
    H.append('.calhd{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}')
    H.append('.calhd button{font-family:inherit;background:none;border:none;color:var(--fg);'
             'cursor:pointer;font-size:13px;padding:2px 6px}')
    H.append('.calhd button:hover{opacity:.7}')
    H.append('.calhd span{font-size:11px;color:var(--fg2)}')
    H.append('.calgrid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}')
    H.append('.calgrid .dow{font-size:9px;color:var(--fg2);text-align:center}')
    H.append('.calday{font-size:10px;text-align:center;padding:3px 0;border-radius:var(--radius);'
             'cursor:pointer;color:var(--fg)}')
    H.append('.calday:hover{background:var(--btnh)}')
    H.append('.calday.sel{background:var(--acc);color:#fff}')
    H.append('.calday.dis{color:var(--fg2);opacity:.3;cursor:not-allowed;pointer-events:none}')
    H.append('.calday.otherm{visibility:hidden}')
    H.append('.ddftr{display:flex;justify-content:flex-end;gap:6px}')
    H.append('#lay{display:flex;flex:1;overflow:hidden}')
    H.append('#sb{width:200px;flex-shrink:0;background:var(--bg2);border-right:1px solid var(--bd);'
             'display:flex;flex-direction:column;overflow:hidden;transition:width .2s}')
    H.append('#sb.cl{width:0;overflow:hidden}')
    H.append('#sbi{padding:8px;overflow-y:auto;flex:1}')
    H.append('#ssi{font-family:inherit;font-size:13px;background:var(--ibg);color:var(--fg);'
             'border:1px solid var(--ibd);border-radius:var(--radius);padding:6px 10px;width:100%;margin-bottom:6px}')
    H.append('#ssi::placeholder{color:var(--fg2)}')
    H.append('#sbi h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--fg2);margin-bottom:6px}')
    H.append('#sba{display:flex;gap:4px;margin:0 0 6px}')
    H.append('#sba .btn{font-size:10px;padding:2px 7px;flex:1}')
    H.append('.cr{display:flex;align-items:center;gap:5px;padding:2px 0;cursor:pointer}')
    H.append('.cr input[type=checkbox]{accent-color:var(--acc);cursor:pointer;width:13px;height:13px;flex-shrink:0}')
    H.append('.cr label{font-size:11px;color:var(--fg);cursor:pointer;overflow:hidden;'
             'text-overflow:ellipsis;white-space:nowrap;max-width:150px}')
    H.append('.csw{width:8px;height:8px;border-radius:50%;flex-shrink:0}')
    H.append('#ca{flex:1;display:flex;flex-direction:column;overflow:hidden}')
    H.append('#stp{display:none;position:fixed;right:12px;bottom:12px;z-index:100;'
             'background:var(--bg2);border:1px solid var(--bd);border-radius:var(--radius);'
             'padding:14px 16px;font-size:12px;line-height:1.7;max-width:220px;box-shadow:var(--sh)}')
    H.append('#stp .stc{float:right;cursor:pointer;margin-left:8px;color:var(--fg2)}')
    H.append('#stp .stn{font-weight:700;font-size:13px;margin-bottom:4px;word-break:break-word}')
    H.append('#cr{display:flex;flex:1;overflow:hidden}')
    H.append('#yp{width:72px;flex-shrink:0;overflow:hidden;background:var(--bg);'
             'border-right:1px solid var(--bd);position:relative}')
    H.append('#yr{position:absolute;top:0;left:0;right:0;bottom:0}')
    H.append('.yl{font-size:10px;color:var(--fg2);text-align:right;line-height:1;'
             'position:absolute;right:4px;transform:translateY(-50%)}')
    H.append('#scr{flex:1;overflow-x:auto;overflow-y:hidden;background:var(--bg)}')
    H.append('#scr::-webkit-scrollbar{height:6px}')
    H.append('#scr::-webkit-scrollbar-thumb{background:var(--st);border-radius:3px}')
    H.append('#pd{min-width:100%}')
    H.append('#stt{flex-shrink:0;max-height:220px;overflow:auto;margin:10px 16px;'
             'border:1px solid var(--bd);border-radius:var(--radius);background:var(--bg2);box-shadow:var(--sh)}')
    H.append("#stbl{width:100%;border-collapse:collapse;font-family:inherit;font-size:12px}")
    H.append('#stbl th,#stbl td{padding:8px 12px;text-align:left;white-space:nowrap;'
             'font-weight:500;font-size:12px;font-family:inherit;color:var(--fg);border-bottom:1px solid var(--bd)}')
    H.append('#stbl thead th{position:sticky;top:0;background:var(--bg2);z-index:1;color:var(--fg2);font-weight:500}')
    H.append('#stbl .cpb{font-size:11px;background:transparent;border:none;cursor:pointer;padding:0 4px 0 0;line-height:1;vertical-align:middle;color:inherit}')
    H.append('#stbl .cpb:hover{opacity:.7}')
    H.append('.btn:disabled{opacity:.4;cursor:not-allowed}')
    H.append('@media(max-width:600px){#sb{position:absolute;z-index:200;height:100%;box-shadow:var(--sh)}}')
    H.append('#ftr{display:flex;align-items:center;gap:20px;padding:16px 20px;'
             'background:var(--bg);border-top:1px solid var(--bd);flex-shrink:0;'
             'flex-wrap:wrap;font-size:12px;color:var(--fg2)}')
    H.append('#ftr p{margin:0}')
    H.append('#ftr a{color:var(--fg2);text-decoration:none}')
    H.append('#ftr a:hover{text-decoration:underline}')
    H.append('#ftr .cp{margin-left:auto}')
    H.append('</style>')
    H.append('<script>const _D=' + data_json + ';</script>')
    H.append('</head><body>')

    H.append(
        '<div id="tb" role="toolbar" aria-label="Chart controls">'
        '<button id="hb" class="btn" aria-label="Toggle sidebar" aria-expanded="true">&#9776;</button>'
        '<div id="brand">'
        f'<a id="lka" href="https://lokanetra.dev/" target="_blank" rel="noopener" aria-label="Lokanetra">{logo_svg}</a>'
        '<h1>Kestrel - Trending (X/Twitter)</h1></div>'
        '<div class="sp"></div>'
        '<label for="rng" style="font-size:12px;color:var(--fg2)">Range:</label>'
        '<select id="rng" aria-label="Time range">'
        '<option value="6h" selected>Last 6h</option>'
        '<option value="24h">Last 24h</option>'
        '<option value="3d">Last 3d</option>'
        '<option value="7d">Last 7d</option>'
        '<option value="All">All</option>'
        '</select>'
        '<button id="rst" class="btn" aria-label="Reset all filters">Reset view</button>'
        '<button id="dlb" class="btn" aria-label="Download combined CSV">Download CSV</button>'
        '<div id="drngWrap">'
        '<button id="drngBtn" class="btn" aria-haspopup="true" aria-expanded="false" '
        'aria-label="Custom date range"></button>'
        '<div id="drngPanel" role="dialog" aria-label="Select date range" hidden>'
        '<div class="ddcals"><div class="cal" id="calStart"></div><div class="cal" id="calEnd"></div></div>'
        '<div class="ddftr">'
        '<button id="drngCancel" class="btn" type="button">Cancel</button>'
        '<button id="drngApply" class="btn" type="button">Apply</button>'
        '</div>'
        '</div>'
        '</div>'
        '<button id="db" class="btn" aria-label="Toggle light/dark mode">&#x2600;</button>'
        '</div>'
    )

    H.append(
        '<div id="lay">'
        '<div id="sb" role="complementary" aria-label="Topic visibility">'
        '<div id="sbi">'
        '<input id="ssi" type="search" placeholder="Search topics…" aria-label="Search topics" autocomplete="off">'
        '<h2>Topics</h2>'
        '<div id="sba">'
        '<button id="sall" class="btn" aria-label="Select all topics">All</button>'
        '<button id="snone" class="btn" aria-label="Deselect all topics">None</button>'
        '</div>'
        '<div id="cbl"></div></div>'
        '</div>'
        '<div id="ca">'
        '<div id="cr">'
        '<div id="yp" aria-hidden="true"><div id="yr"></div></div>'
        '<div id="scr"><div id="pd"></div></div>'
        '</div>'
        '<div id="stt">'
        '<table id="stbl">'
        '<thead><tr>'
        '<th>Topic <button id="copyAllTopics" class="btn" aria-label="Copy search query for active topics">Copy search query</button></th><th>First appeared</th><th>Rank at first appearance</th>'
        '<th>Highest rank achieved</th><th>When highest rank achieved</th>'
        '<th>Last rank before disappearing</th><th>When it disappeared</th>'
        '<th>Total trending hours</th>'
        '</tr></thead>'
        '<tbody id="stbody"></tbody>'
        '</table>'
        '</div>'
        '</div>'
        '</div>'
        '<div id="stp" role="tooltip" aria-live="polite">'
        '<span id="stc" class="stc" title="Close">&#x2715;</span>'
        '<div class="stn" id="stn"></div><div id="stb"></div>'
        '</div>'
    )

    H.append(
        '<footer id="ftr">'
        '<p><a href="https://github.com/ishakmartins/kestrel-trending" target="_blank" rel="noopener">GitHub: kestrel-trending</a></p>'
        '<p>Cookies: <a href="https://lokanetra.dev/cookies" target="_blank" rel="noopener">https://lokanetra.dev/cookies</a></p>'
        '<p>Privacy: <a href="https://lokanetra.dev/privacy" target="_blank" rel="noopener">https://lokanetra.dev/privacy</a></p>'
        '<p>Terms: <a href="https://lokanetra.dev/terms" target="_blank" rel="noopener">https://lokanetra.dev/terms</a></p>'
        '<p>Feedback: contact(at)lokanetra.dev</p>'
        '<p class="cp">&copy; 2026 Lokanetra. All rights reserved.</p>'
        '</footer>'
    )

    # JS block: raw string — width computed client-side, no bake-in substitution needed.
    JS = r"""<script>
(function(){
"use strict";
const D=_D,N=D.topics.length;
const S={range:"6h",customRange:null,checked:{},pinned:null,hovered:null,dark:true};

(function(){
  const sd=localStorage.getItem("kestrel_dark");
  if(sd==="0")S.dark=false;
  if(!S.dark)document.body.classList.add("light");
  document.getElementById("db").textContent=S.dark?"☀":"🌙";
  const p=new URLSearchParams(location.search);
  if(p.has("range")){
    S.range=p.get("range");
    if(S.range==="custom"&&p.has("start")&&p.has("end")){
      S.customRange={startTs:Number(p.get("start")),endTs:Number(p.get("end"))};
    }
  }
  D.topics.forEach(t=>{S.checked[t.n]=true;});
})();

function syncUrl(){
  const p=new URLSearchParams();
  if(S.range==="custom"&&S.customRange){
    p.set("range","custom");
    p.set("start",String(S.customRange.startTs));
    p.set("end",String(S.customRange.endTs));
  } else if(S.range!=="6h"){
    p.set("range",S.range);
  }
  history.replaceState(null,"",p.toString()?"?"+p:location.pathname);
}

function rngSec(r){return{"6h":21600,"24h":86400,"3d":259200,"7d":604800}[r]||null;}

function isQuickSource(){return S.range!=="custom";}

function filtHi(){
  if(S.range==="custom"&&S.customRange){
    const{startTs,endTs}=S.customRange;
    return D.hours.reduce((a,h,i)=>{if(h.ts>=startTs&&h.ts<=endTs)a.push(i);return a;},[]);
  }
  const s=rngSec(S.range);
  if(!s)return D.hours.map((_,i)=>i);
  const cut=D.maxTs-s;
  return D.hours.reduce((a,h,i)=>{if(h.ts>=cut)a.push(i);return a;},[]);
}

function buildTraces(hi){
  const hm={};hi.forEach((g,l)=>{hm[g]=l;});
  const tr=D.topics.map(t=>{
    const col=S.dark?t.cd:t.cl;
    const pts=t.pts.filter(p=>hm[p[0]]!==undefined);
    const xA=[],yA=[],tA=[];let pv=null;
    pts.forEach(p=>{
      const l=hm[p[0]];
      if(pv!==null&&l!==pv+1){xA.push(null);yA.push(null);tA.push("");}
      xA.push(l);yA.push(p[1]);
      tA.push("<b>"+t.d+"</b><br>Rank "+p[1]+(p[2]!=null?" · "+p[2].toLocaleString()+" tweets":""));
      pv=l;
    });
    return{type:"scatter",mode:"lines",name:t.d,x:xA,y:yA,text:tA,
      hovertemplate:"%{text}<extra></extra>",
      line:{color:col,width:1.8},opacity:1,connectgaps:false,showlegend:false};
  });
  tr.push({type:"scatter",mode:"markers",x:[0],y:[null],xaxis:"x2",
    showlegend:false,hoverinfo:"skip",marker:{size:0,opacity:0}});
  return tr;
}

function buildLayout(hi){
  const tv=hi.map((_,l)=>l);
  const tt=hi.map(i=>D.hours[i].l.replace(/<br>/g,"\n"));
  const d=S.dark,bg=d?"#121212":"#fff",fg=d?"#e0e0e0":"#111";
  const grid=d?"#2a2a2a":"#ccc",gridx=d?"#383838":"#999";
  const tf={family:"'Alte Haas Grotesk','Helvetica Neue',Arial,sans-serif",size:9};
  const axC={tickmode:"array",tickvals:tv,ticktext:tt,tickfont:tf,showline:false,zeroline:false,automargin:true};
  const perHourPx=80;
  const containerW=document.getElementById("scr").clientWidth||1200;
  const dynW=Math.max(containerW,hi.length*perHourPx);
  return{
    width:dynW,height:560,
    paper_bgcolor:bg,plot_bgcolor:bg,
    font:{family:"'Alte Haas Grotesk','Helvetica Neue',Arial,sans-serif",color:fg,size:11},
    margin:{l:5,r:10,t:40,b:80},
    xaxis:Object.assign({},axC,{showgrid:true,gridcolor:gridx,gridwidth:1,side:"bottom"}),
    xaxis2:Object.assign({},axC,{overlaying:"x",side:"top",matches:"x",showgrid:false}),
    yaxis:{range:[D.topN+0.5,0.5],showticklabels:false,showgrid:true,
      gridcolor:grid,gridwidth:1,zeroline:false,showline:false},
    hovermode:"closest",dragmode:"pan",
  };
}

function buildAnns(hi){
  const hm={};hi.forEach((g,l)=>{hm[g]=l;});
  const anns=[];
  D.topics.forEach(t=>{
    if(S.checked[t.n]===false)return;
    const col=S.dark?t.cd:t.cl,bx=S.dark?"#1c1c1c":"#fff";
    const pts=t.pts.filter(p=>hm[p[0]]!==undefined);
    if(!pts.length)return;
    (pts.length===1?[pts[0]]:[pts[0],pts[pts.length-1]]).forEach(p=>{
      anns.push({x:hm[p[0]],y:p[1],text:t.d,showarrow:false,
        font:{family:"'Alte Haas Grotesk','Helvetica Neue',Arial,sans-serif",size:10,color:col},
        bgcolor:bx,bordercolor:col,borderwidth:1,borderpad:3,opacity:0.93,
        xanchor:"center",yanchor:"middle"});
    });
  });
  return anns;
}

const DAYS=["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
const MONS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const tzList=[{name:"UTC",off:0},{name:"GMT+8",off:28800},{name:"GMT+7",off:25200}];
function fmtTs(epochSec,off){
  const dt=new Date((epochSec+off)*1000);
  return{
    dayName:DAYS[dt.getUTCDay()],
    dd:String(dt.getUTCDate()).padStart(2,"0"),
    mon:MONS[dt.getUTCMonth()],
    mm:String(dt.getUTCMonth()+1).padStart(2,"0"),
    yyyy:String(dt.getUTCFullYear()),
    hhmm:String(dt.getUTCHours()).padStart(2,"0")+":"+String(dt.getUTCMinutes()).padStart(2,"0")
  };
}

function fmtGmt7(ts){
  const f=fmtTs(ts,25200);
  return f.dayName+", "+f.dd+" "+f.mon+" "+f.yyyy+" "+f.hhmm;
}

function utcDateNum(ts){
  const f=fmtTs(ts,0);
  return Number(f.yyyy)*10000+Number(f.mm)*100+Number(f.dd);
}
function dateNumParts(n){return{y:Math.floor(n/10000),m:Math.floor(n/100)%100,d:n%100};}

const hourDateMap=(function(){
  const m={};
  D.hours.forEach(h=>{
    const k=utcDateNum(h.ts);
    if(!m[k])m[k]={minTs:h.ts,maxTs:h.ts};
    else{
      if(h.ts<m[k].minTs)m[k].minTs=h.ts;
      if(h.ts>m[k].maxTs)m[k].maxTs=h.ts;
    }
  });
  return m;
})();
const _dateNums=Object.keys(hourDateMap).map(Number).sort((a,b)=>a-b);
const maxDateNum=_dateNums.length?_dateNums[_dateNums.length-1]:null;

const Cal={startNum:null,endNum:null,startView:null,endView:null};

function renderCal(containerId,viewYM,selNum,onPick){
  const el=document.getElementById(containerId);
  const{y,m}=viewYM;
  let html='<div class="calhd"><button type="button" data-nav="-1" aria-label="Previous month">&#8249;</button>'
    +'<span>'+MONS[m-1]+" "+y+'</span>'
    +'<button type="button" data-nav="1" aria-label="Next month">&#8250;</button></div>';
  html+='<div class="calgrid">';
  ["S","M","T","W","T","F","S"].forEach(d=>{html+='<div class="dow">'+d+'</div>';});
  const startDow=new Date(Date.UTC(y,m-1,1)).getUTCDay();
  const daysInMonth=new Date(Date.UTC(y,m,0)).getUTCDate();
  for(let i=0;i<startDow;i++)html+='<div class="calday otherm">.</div>';
  for(let d=1;d<=daysInMonth;d++){
    const num=y*10000+m*100+d;
    const has=!!hourDateMap[num];
    html+='<div class="calday'+(has?"":" dis")+(num===selNum?" sel":"")+'" data-num="'+num+'">'+d+'</div>';
  }
  el.innerHTML=html;
  el.querySelectorAll("[data-nav]").forEach(b=>{
    b.addEventListener("click",()=>{
      const dir=Number(b.getAttribute("data-nav"));
      let nm=viewYM.m+dir,ny=viewYM.y;
      if(nm<1){nm=12;ny--;}
      if(nm>12){nm=1;ny++;}
      viewYM.y=ny;viewYM.m=nm;
      renderCal(containerId,viewYM,selNum,onPick);
    });
  });
  el.querySelectorAll(".calday[data-num]").forEach(c=>{
    if(c.classList.contains("dis"))return;
    c.addEventListener("click",()=>{onPick(Number(c.getAttribute("data-num")));});
  });
}

function refreshCals(){
  renderCal("calStart",Cal.startView,Cal.startNum,pickStart);
  renderCal("calEnd",Cal.endView,Cal.endNum,pickEnd);
}
function pickStart(num){
  Cal.startNum=num;
  if(Cal.endNum!=null&&Cal.endNum<num)Cal.endNum=num;
  refreshCals();
}
function pickEnd(num){
  Cal.endNum=num;
  if(Cal.startNum!=null&&Cal.startNum>num)Cal.startNum=num;
  refreshCals();
}

function currentRangeDateNums(){
  if(S.range==="custom"&&S.customRange){
    return{s:utcDateNum(S.customRange.startTs),e:utcDateNum(S.customRange.endTs)};
  }
  const hi=(S.hi&&S.hi.length)?S.hi:filtHi();
  if(!hi.length)return{s:null,e:null};
  return{s:utcDateNum(D.hours[hi[0]].ts),e:utcDateNum(D.hours[hi[hi.length-1]].ts)};
}

function openDrngPanel(){
  const{s,e}=currentRangeDateNums();
  Cal.startNum=s;Cal.endNum=e;
  const sp=dateNumParts(s||maxDateNum),ep=dateNumParts(e||maxDateNum);
  Cal.startView={y:sp.y,m:sp.m};
  Cal.endView={y:ep.y,m:ep.m};
  refreshCals();
  document.getElementById("drngPanel").hidden=false;
  document.getElementById("drngBtn").setAttribute("aria-expanded","true");
}
function closeDrngPanel(){
  document.getElementById("drngPanel").hidden=true;
  document.getElementById("drngBtn").setAttribute("aria-expanded","false");
}
function applyDrng(){
  if(Cal.startNum==null||Cal.endNum==null)return;
  const sInfo=hourDateMap[Cal.startNum],eInfo=hourDateMap[Cal.endNum];
  if(!sInfo||!eInfo)return;
  S.customRange={startTs:sInfo.minTs,endTs:eInfo.maxTs};
  S.range="custom";
  closeDrngPanel();
  redraw();
}

function buildDayBoundaries(hi){
  const dk=S.dark;
  const fc=dk?"#888":"#666",bc=dk?"#1c1c1c":"#fff",lc=dk?"#555":"#aaa";
  const byPos={};
  tzList.forEach(tz=>{
    let prevDate=null;
    hi.forEach((g,l)=>{
      const f=fmtTs(D.hours[g].ts,tz.off);
      const date=Number(f.yyyy)*10000+Number(f.mm)*100+Number(f.dd);
      if(prevDate!==null&&date!==prevDate){
        if(!byPos[l])byPos[l]=[];
        byPos[l].push(f.dayName+", "+f.dd+" "+f.mm+" "+f.yyyy+" ("+tz.name+")");
      }
      prevDate=date;
    });
  });
  const positions=Object.keys(byPos).map(Number).sort((a,b)=>a-b);
  const groups=[];
  positions.forEach(pos=>{
    if(groups.length===0||pos>groups[groups.length-1].pos+1){
      groups.push({pos,labels:[...byPos[pos]]});
    } else {
      groups[groups.length-1].labels.push(...byPos[pos]);
    }
  });
  const shapes=[],anns=[];
  groups.forEach(({pos,labels})=>{
    shapes.push({
      type:"line",x0:pos-0.5,x1:pos-0.5,y0:0,y1:1,yref:"paper",
      line:{color:lc,width:3,dash:"dash"}
    });
    anns.push({
      x:pos-0.5,y:0.98,yref:"paper",
      text:labels.join("<br>"),
      showarrow:false,xanchor:"left",yanchor:"top",
      font:{family:"'Alte Haas Grotesk','Helvetica Neue',Arial,sans-serif",size:8,color:fc},
      bgcolor:bc,bordercolor:lc,borderwidth:1,borderpad:2,opacity:0.9,xshift:3
    });
  });
  return{shapes,anns};
}

function applyVis(){
  const gd=document.getElementById("pd");
  if(!gd.data)return;
  const op=D.topics.map(t=>{
    const chk=S.checked[t.n]!==false;
    if(!chk)return 0;
    if(S.pinned)return S.pinned===t.n?1:0.06;
    if(S.hovered)return S.hovered===t.n?1:0.06;
    return 1;
  });
  op.push(0);
  Plotly.restyle(gd,{opacity:op},Array.from({length:op.length},(_,i)=>i));
  if(S.hi){
    Plotly.relayout(gd,{annotations:[...buildAnns(S.hi),...S.dbAnns]});
  }
}

function updYp(){
  const gd=document.getElementById("pd");
  if(!gd._fullLayout)return;
  const fl=gd._fullLayout,m=fl.margin,pH=fl.height-m.t-m.b;
  const yr=fl.yaxis.range;
  const yBig=Math.max(yr[0],yr[1]),ySm=Math.min(yr[0],yr[1]);
  const panel=document.getElementById("yr");
  panel.innerHTML="";
  for(let r=1;r<=D.topN;r++){
    if(r<ySm-0.5||r>yBig+0.5)continue;
    const el=document.createElement("div");
    el.className="yl";el.textContent=r;
    el.style.top=(m.t+(r-ySm)/(yBig-ySm)*pH)+"px";
    panel.appendChild(el);
  }
}

function rebuildCb(hi){
  const hiSet=new Set(hi);
  const list=document.getElementById("cbl");
  list.innerHTML="";
  D.topics.forEach(t=>{
    if(!t.pts.some(p=>hiSet.has(p[0])))return;
    const col=S.dark?t.cd:t.cl;
    const row=document.createElement("div");row.className="cr";
    const sw=document.createElement("div");sw.className="csw";sw.style.background=col;
    const cb=document.createElement("input");cb.type="checkbox";
    cb.checked=S.checked[t.n]!==false;
    cb.setAttribute("aria-label","Show "+t.d);
    cb.addEventListener("change",()=>{S.checked[t.n]=cb.checked;applyVis();renderStatsTable(S.hi);});
    const lb=document.createElement("label");lb.textContent=t.d;lb.title=t.d;
    lb.addEventListener("click",()=>{cb.click();});
    row.appendChild(sw);row.appendChild(cb);row.appendChild(lb);
    list.appendChild(row);
  });
  const sv=document.getElementById("ssi").value.trim().toLowerCase();
  if(sv){
    list.querySelectorAll(".cr").forEach(row=>{
      const lb=row.querySelector("label");
      row.style.display=(lb&&lb.textContent.toLowerCase().includes(sv))?"":"none";
    });
  }
}

function buildStatsRows(hi){
  const hiSet=new Set(hi);
  let maxHiTs=-Infinity;
  hi.forEach(g=>{if(D.hours[g].ts>maxHiTs)maxHiTs=D.hours[g].ts;});
  const rows=[];
  D.topics.forEach(t=>{
    if(S.checked[t.n]===false)return;
    const pts=t.pts.filter(p=>hiSet.has(p[0]))
      .slice()
      .sort((a,b)=>D.hours[a[0]].ts-D.hours[b[0]].ts);
    if(!pts.length)return;
    const first=pts[0],last=pts[pts.length-1];
    let best=pts[0];
    pts.forEach(p=>{if(p[1]<best[1])best=p;});
    rows.push({
      name:t.d,
      firstTs:D.hours[first[0]].ts,firstRank:first[1],
      bestRank:best[1],bestTs:D.hours[best[0]].ts,
      lastRank:last[1],lastTs:D.hours[last[0]].ts,
      stillTrending:D.hours[last[0]].ts===maxHiTs,
      hoursCount:pts.length,
    });
  });
  rows.sort((a,b)=>a.bestRank-b.bestRank||a.firstTs-b.firstTs);
  return rows;
}

function renderStatsTable(hi){
  const tbody=document.getElementById("stbody");
  if(!tbody||!hi)return;
  const rows=buildStatsRows(hi);
  tbody.innerHTML="";
  const cat=document.getElementById("copyAllTopics");
  if(cat)cat.disabled=rows.length===0;
  rows.forEach(r=>{
    const tr=document.createElement("tr");
    const tdName=document.createElement("td");
    const cpb=document.createElement("button");
    cpb.type="button";cpb.className="cpb";cpb.textContent="📋";
    cpb.setAttribute("aria-label","Copy topic");
    cpb.addEventListener("click",()=>{navigator.clipboard.writeText(r.name);});
    tdName.appendChild(cpb);
    tdName.appendChild(document.createTextNode(r.name));
    tr.appendChild(tdName);
    [
      fmtGmt7(r.firstTs),
      String(r.firstRank),
      String(r.bestRank),
      fmtGmt7(r.bestTs),
      String(r.lastRank),
      fmtGmt7(r.lastTs)+(r.stillTrending?" (still trending)":""),
      String(r.hoursCount),
    ].forEach(v=>{const td=document.createElement("td");td.textContent=v;tr.appendChild(td);});
    tbody.appendChild(tr);
  });
}

function buildSearchQuery(names){
  if(!names||!names.length)return "";
  const parts=names.map(n=>n.indexOf(" ")>=0?JSON.stringify(n):n);
  return '"search_query": "('+parts.join(" OR ")+')"';
}

function copyAllTopics(){
  const rows=buildStatsRows(S.hi||[]);
  const q=buildSearchQuery(rows.map(r=>r.name));
  if(!q)return;
  navigator.clipboard.writeText(q);
}

let _first=true;
function updDrng(hi){
  const btn=document.getElementById("drngBtn");
  if(!hi.length){btn.textContent="(no data in range)";btn.classList.toggle("qsrc",isQuickSource());return;}
  function fmt(ts){
    const f0=fmtTs(ts,0);
    const parts=tzList.map(tz=>tz.name+": "+fmtTs(ts,tz.off).hhmm);
    return "["+f0.dayName+", "+f0.dd+" "+f0.mon+" "+f0.yyyy+", "+parts.join(", ")+"]";
  }
  btn.textContent=fmt(D.hours[hi[0]].ts)+" to "+fmt(D.hours[hi[hi.length-1]].ts);
  btn.classList.toggle("qsrc",isQuickSource());
}

function redraw(){
  const gd=document.getElementById("pd");
  const hi=filtHi(),tr=buildTraces(hi),ly=buildLayout(hi);
  updDrng(hi);
  const db=buildDayBoundaries(hi);
  ly.shapes=db.shapes;
  ly.annotations=[...buildAnns(hi),...db.anns];
  S.hi=hi;S.dbAnns=db.anns;
  (_first?Plotly.newPlot:Plotly.react)(gd,tr,ly,{responsive:false,displayModeBar:true,scrollZoom:true})
    .then(()=>{if(_first){attEv(gd);_first=false;}updYp();rebuildCb(hi);renderStatsTable(hi);applyVis();syncUrl();});
}

let _hoverRafPending=false;
function applyVisOnHoverFrame(){
  if(_hoverRafPending)return;
  _hoverRafPending=true;
  requestAnimationFrame(()=>{_hoverRafPending=false;applyVis();});
}

function attEv(gd){
  let _lastYRange=null;
  gd.on("plotly_hover",d=>{
    if(!d.points||!d.points[0])return;
    const ti=d.points[0].curveNumber;
    if(ti>=N)return;
    const topic=D.topics[ti];
    if(topic.n===S.hovered)return;
    S.hovered=topic.n;shSt(S.hovered);applyVisOnHoverFrame();
  });
  gd.on("plotly_unhover",()=>{
    S.hovered=null;
    if(!S.pinned)document.getElementById("stp").style.display="none";
    applyVis();
  });
  gd.on("plotly_click",d=>{
    if(!d.points||!d.points[0])return;
    const ti=d.points[0].curveNumber;
    if(ti>=N)return;
    const kn=D.topics[ti].n;
    S.pinned=(S.pinned===kn)?null:kn;
    if(S.pinned)shSt(kn);
    else document.getElementById("stp").style.display="none";
    applyVis();
  });
  gd.on("plotly_relayout",()=>{
    const yr=gd._fullLayout&&gd._fullLayout.yaxis&&gd._fullLayout.yaxis.range;
    if(!yr)return;
    if(_lastYRange&&_lastYRange[0]===yr[0]&&_lastYRange[1]===yr[1])return;
    _lastYRange=[yr[0],yr[1]];
    updYp();
  });
}

function shSt(kn){
  const t=D.topics.find(x=>x.n===kn);if(!t)return;
  document.getElementById("stn").textContent=t.d;
  let b="<div>Appearances: "+t.pts.length+" / "+D.hours.length+" hrs</div>";
  if(t.pts.length)b+="<div>Best rank: #"+Math.min(...t.pts.map(p=>p[1]))+"</div>";
  if(t.bp!=null)b+="<div>Best position: #"+t.bp+"</div>";
  if(t.tt!=null)b+="<div>Total tweets: "+t.tt.toLocaleString()+"</div>";
  document.getElementById("stb").innerHTML=b;
  document.getElementById("stp").style.display="block";
}
function clSt(){document.getElementById("stp").style.display="none";S.pinned=null;applyVis();}

function setRange(v){S.range=v;S.customRange=null;redraw();}

let _sb=null;
function sbSch(){
  clearTimeout(_sb);
  _sb=setTimeout(()=>{
    const v=document.getElementById("ssi").value.trim().toLowerCase();
    document.querySelectorAll("#cbl .cr").forEach(row=>{
      const lb=row.querySelector("label");
      row.style.display=(!v||(lb&&lb.textContent.toLowerCase().includes(v)))?"":"none";
    });
  },150);
}

function rstV(){
  S.range="All";S.customRange=null;S.pinned=null;S.hovered=null;
  D.topics.forEach(t=>{S.checked[t.n]=true;});
  document.getElementById("ssi").value="";
  document.querySelectorAll("#cbl .cr").forEach(row=>{row.style.display="";});
  document.getElementById("rng").value="All";
  document.getElementById("stp").style.display="none";
  redraw();
}

function dlCsv(){
  const rows=["name_norm,display,hour_label,hour_ts,rank,tweet_count"];
  D.topics.forEach(t=>{
    t.pts.forEach(p=>{
      const h=D.hours[p[0]];
      rows.push([t.n,t.d,h.l.replace(/<br>/g," | "),h.ts,p[1],p[2]!=null?p[2]:""].join(","));
    });
  });
  const bl=new Blob([rows.join("\n")],{type:"text/csv"});
  const u=URL.createObjectURL(bl),a=document.createElement("a");
  a.href=u;a.download="kestrel_trends24_id.csv";a.click();URL.revokeObjectURL(u);
}

function tDk(){
  S.dark=!S.dark;
  document.body.classList.toggle("light",!S.dark);
  document.getElementById("db").textContent=S.dark?"☀":"🌙";
  localStorage.setItem("kestrel_dark",S.dark?"1":"0");
  redraw();
}

function tSb(){
  const s=document.getElementById("sb");
  s.classList.toggle("cl");
  document.getElementById("hb").setAttribute("aria-expanded",s.classList.contains("cl")?"false":"true");
}

document.addEventListener("keydown",e=>{
  if(e.key==="Escape"){
    S.pinned=null;S.hovered=null;document.getElementById("stp").style.display="none";applyVis();
    closeDrngPanel();
  }
});

document.getElementById("hb").addEventListener("click", tSb);
document.getElementById("rng").addEventListener("change", e=>setRange(e.target.value));
document.getElementById("ssi").addEventListener("input", sbSch);
document.getElementById("rst").addEventListener("click", rstV);
document.getElementById("dlb").addEventListener("click", dlCsv);
document.getElementById("db").addEventListener("click", tDk);
document.getElementById("stc").addEventListener("click", clSt);
document.getElementById("copyAllTopics").addEventListener("click", copyAllTopics);
document.getElementById("sall").addEventListener("click",()=>{D.topics.forEach(t=>{S.checked[t.n]=true;});document.querySelectorAll("#cbl input[type=checkbox]").forEach(cb=>{cb.checked=true;});applyVis();renderStatsTable(S.hi);});
document.getElementById("snone").addEventListener("click",()=>{D.topics.forEach(t=>{S.checked[t.n]=false;});document.querySelectorAll("#cbl input[type=checkbox]").forEach(cb=>{cb.checked=false;});applyVis();renderStatsTable(S.hi);});
document.getElementById("drngBtn").addEventListener("click",()=>{
  const p=document.getElementById("drngPanel");
  if(p.hidden)openDrngPanel();else closeDrngPanel();
});
document.getElementById("drngApply").addEventListener("click", applyDrng);
document.getElementById("drngCancel").addEventListener("click", closeDrngPanel);
document.addEventListener("click",e=>{
  const wrap=document.getElementById("drngWrap");
  if(!e.composedPath().includes(wrap))closeDrngPanel();
});
if(S.range!=="custom")document.getElementById("rng").value=S.range;
redraw();
})();
</script>"""
    H.append(JS)
    H.append('</body></html>')

    html = "\n".join(H)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    log.info(
        "Interactive chart saved: %s (%d topics, %d hour-columns, ~%d KB)",
        out_path, n_topics, n_hours, len(html.encode("utf-8")) // 1024,
    )


def run(csv_path: Path = CSV_PATH, out_path: Path = OUT_PATH, lookback_days: int = LOOKBACK_DAYS, top_n: int = TOP_N) -> None:
    """Read csv_path, trim to the last lookback_days (by hour_label timestamp), render out_path."""
    df = pd.read_csv(csv_path, encoding="utf-8")
    if lookback_days is not None:
        cutoff = df["hour_label"].map(parse_hour_label_ts).max() - lookback_days * 86400
        df = df[df["hour_label"].map(parse_hour_label_ts) >= cutoff]
        log.info("Trimmed to last %d days: %d rows", lookback_days, len(df))

    palette_light = build_pumpkin_palette(PALETTE_SIZE)
    palette_dark = build_pumpkin_palette_dark(PALETTE_SIZE)
    render_bump_chart_interactive(df, palette_light, palette_dark, out_path, top_n=top_n)


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=CSV_PATH)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    ap.add_argument("--top-n", type=int, default=TOP_N)
    args = ap.parse_args()
    run(args.csv, args.out, args.lookback_days, args.top_n)
