# kestrel-trending

Scrapes Indonesia's Twitter/X trending topics from [trends24.in/indonesia/](https://trends24.in/indonesia/) and renders a rank-over-time bump chart.

## Architecture

Two independent modules, run back-to-back every 30 minutes by
`.github/workflows/hourly-run.yml`'s single `run` job (one job, not two, so a scrape-job
push and a report-job push can't race each other):

- **`trending/scraper.py`** — fetches trends24.in/indonesia/ and appends new rows to one
  central CSV, `dataset/trends/trends24_id.csv`, deduping on `(name_norm, hour_label)` —
  latest capture wins. No charts, no per-run files — just fetch and append.
- **`trending/report.py`** — reads that CSV and rebuilds one self-contained interactive
  Plotly HTML dashboard (`dataset/trends/latest_interactive.html`, also published to
  `docs/trending/index.html` for GitHub Pages). Embeds only the last 90 days of data in the
  page (`LOOKBACK_DAYS` in `trending/report.py`) so the HTML payload doesn't grow unbounded
  as the CSV does over time; the CSV itself keeps full history.
- **`site/`** — Astro homepage that fronts GitHub Pages (`docs/index.html`), linking to the
  dashboard at `/trending/`. `npm run build` (run from `site/`) first stages the generated
  dashboard HTML + `src/logo/lokentra.dev-logo.svg` into `site/public/` via
  `site/scripts/stage-dashboard.mjs`, then runs `astro build` with `outDir: '../docs'` so
  the existing "Deploy from a branch: main/docs" GitHub Pages setup keeps working unchanged.

The CSV schema:

```
captured_at_utc, run_id, source_url, hour_label,
rank, name, name_norm, tweet_count_raw, tweet_count,
best_position, total_tweets, trending_for_raw, trending_for_hours
```

`best_position`, `total_tweets`, and `trending_for_*` are always `null` — trends24.in's
Indonesia subpage does not expose the detail-stats table that the worldwide page has.

### Building the site locally

Requires Node 20+ and a dashboard already generated at `dataset/trends/latest_interactive.html`
(run `python -m trending.report` first if that file is missing or stale — the site build
stages a copy of it, it doesn't generate one).

```
cd site
npm install
npm run build      # stage dashboard+logo -> astro build -> ../docs
```

Output lands in `docs/` at the repo root: `docs/index.html` (homepage) and
`docs/trending/index.html` (dashboard). Open `docs/index.html` directly in a browser to check
the result, or `npm run preview` from `site/` to serve it locally. For iterating on the
homepage itself, `npm run dev` (also from `site/`) starts Astro's dev server with live reload
at `http://localhost:4321/kestrel-trending/` (note the `/kestrel-trending/` base path — set in
`site/astro.config.mjs` to match the GitHub Pages project-page URL).

## Chart features

- **Y-axis**: rank 1 at top, inverted, capped at `TOP_N`
- **X-axis**: dual top + bottom labels; each column shows three time zones — `UTC / GMT+8 / GMT+7`
- **Lines**: one per topic, colored from a stable 150-color warm-autumn (pumpkin) palette
- **Nodes**: boxed keyword label at each topic's **first** and **last** non-NaN hour only
- **Color assignment**: `MD5(name_norm) mod 150` — same topic always gets the same color across runs and light/dark

## Interactive chart

The dashboard is a fully self-contained Plotly file (no CDN dependency at runtime except the
optional Alte Haas Grotesk web font):

- **Combined dataset**: renders the whole embedded lookback window merged together — see
  `LOOKBACK_DAYS` above for how much history a given build embeds; the full history always
  lives in `dataset/trends/trends24_id.csv`.
- **Dynamic chart width**: width is computed client-side at each redraw as `Math.max(containerW, hi.length × 80px)` — short ranges fill the viewport, long ranges grow beyond it and trigger `overflow-x: auto` scrolling. Y-axis rank labels are in a sticky panel outside the scroll area so they stay visible while scrolling.
- **Boxed keyword labels**: first and last non-NaN appearance of each topic gets a bordered label box, via Plotly `layout.annotations`.
- **Four-line tick labels**: each hour column's x-axis tick (top and bottom) shows UTC / GMT+8 / GMT+7 times plus a fourth line with the GMT+7 calendar date, computed Python-side in `format_tz_label`.
- **Dual top + bottom x-axes**: hour labels appear on both the top and bottom edge of the chart (Plotly `xaxis2`, `overlaying='x'`, `side='top'`).
- **Time-range dropdown**: Last 6h / 24h / 3d / 7d / All — filters the embedded dataset and re-renders client-side via `Plotly.react()`. No backend required.
- **Per-topic checkboxes**: sidebar checkbox list for hard show/hide of individual topics (independent of opacity dimming). Rows sorted alphabetically regardless of time range.
- **Dim-opacity toggle**: toolbar `Dim:` control sets the opacity of unselected traces when a topic is emphasised by hover or pin. Setting persists across page reloads via `localStorage`.
- **Bring-to-front**: when a trace is pinned or hovered, it's moved to the last draw position so it renders above crossing traces at full opacity. Order resets on unpin / unhover / Escape / Reset view.
- **Unified state model**: single `S = {range, checked, pinned, hovered, dark, dimOpacity}` object with one `applyVis()` function as the only `Plotly.restyle` caller.
- **Click-to-pin**: click a trace to lock its emphasis; click again or press Escape to unpin.
- **Light/dark toggle**: both palettes embedded; swap is instant client-side. Default dark. `localStorage` remembers the last choice.
- **Topic stats panel**: hover or pin a trace to see appearances, best rank, and total tweets in a floating panel.
- **Sidebar search**: debounced (150 ms) substring filter in the sidebar that shows/hides checkbox rows by topic display name — scoped to the current time range. URL query-param sync (`?range=7d`).
- **Date-range picker**: quick presets plus a custom calendar picker (`#drngWrap`) — click a day or navigate months without the panel closing prematurely (a click-outside-detection race that briefly broke this is fixed as of v20 — see the changelog below). Escape and an actual click outside the panel still close it.
- **Day-boundary markers**: thick dashed vertical lines at each timezone's calendar midnight crossing (UTC, GMT+8, GMT+7), with stacked annotations. Recomputed on every range change.
- **Date-range indicator**: compact text in the toolbar showing the start and end of the currently displayed range across all three timezones. Updates on every range change.
- **Download CSV**: reconstructs the embedded dataset into a downloadable `.csv`.
- **Topic-stats table**: persistent `<table>` below the chart, one row per topic currently checked in the sidebar, scoped to the selected time range — topic name (with a per-row clipboard-copy button and a "Copy search query" button that builds a ready-to-paste `(topic1 OR topic2 OR ...)` query for the active topic set), first appeared, rank at first appearance, highest rank achieved (+ when), last rank before disappearing (+ when, flagged `(still trending)` if still present). Sorted best-rank-ascending.
- **Font**: Alte Haas Grotesk via `fonts.cdnfonts.com` CDN; fallback stack `'Helvetica Neue', Arial, sans-serif`.
- **Accessibility**: ARIA labels on all controls, Escape key clears active state, collapsible sidebar on mobile.
- **Offline-capable**: `plotly.js` is embedded in the HTML so the file works locally and on GitHub Pages without any backend.

Static PNG output (light/dark bump-chart images) was dropped in the Phase 3 migration —
see the changelog below.

## GitHub Pages

`site/` is an Astro project that builds to `docs/` at the repo root (`site/astro.config.mjs`,
`outDir: '../docs'`). `docs/index.html` is the generated homepage; `docs/trending/index.html`
is the generated dashboard. Both are rebuilt by the `report` job in
`.github/workflows/hourly-run.yml` and committed — don't hand-edit anything under `docs/`,
it's fully regenerated on every report run. Repo Settings → Pages is configured to deploy
from `main` / `docs` (unchanged by this migration).

## Notebooks (retired)

`notebooks/kestrel-trends_bumpchart-*.ipynb` was the original pipeline: every run wrote a
fresh `dataset/trends/run_<timestamp>/` folder (raw CSV + 2 PNGs + interactive HTML), then
refreshed `dataset/trends/latest_*` and `docs/*` stable copies. That produced 500+ run
folders and a multi-MB-per-commit footprint. As of the Phase 3 migration, the notebook is no
longer executed in CI — `trending/scraper.py` and `trending/report.py` (see Architecture
above) replace it. The latest notebook version is kept in the repo for historical/reference
purposes only; its chart-rendering logic is what `trending/report.py` is ported from.

| Version | Notes |
|---------|-------|
| v1 | All visible topics, plain circle nodes |
| v2 | Limit to top 30; bold text with bounding box labels |
| v3 | Vertical per-hour gridlines; dual UTC/GMT+8/GMT+7 x-axis; `TOP_N` configurable |
| v4 | Boxed keyword labels replace dot markers at every hour position |
| v5 | Fill all rank slots 1..`TOP_N`: filter on `min(rank) <= TOP_N` instead of topic cap |
| v6 | Readable static output (2× font sizes, first+last-only labels); dark-mode PNG; Plotly interactive HTML with hover-highlight and topic search; `build_rank_pivot` shared helper; `refresh_latest_pointers` stable latest-copy outputs |
| v7 | Interactive chart overhaul: combined-dataset JSON embedded from all runs; natural-width scroll container + sticky y-axis; boxed first+last labels matching static PNG; dual top+bottom x-axes; unified JS state model fixing search+hover conflict; time-range dropdown; per-topic checkboxes; click-to-pin; light/dark toggle with localStorage; Alte Haas Grotesk font; Download CSV; URL sync; `OUTPUT_ROOT` anchored to repo root via `.git` detection |
| v8 | Bug fixes: inline Plotly.js injection via `plotly.offline.get_plotlyjs()`; `_ts()` timestamp parser fix so range dropdown actually filters |
| v9 | IIFE scope fix: all controls wired with `addEventListener` inside closure; Select All / Deselect All sidebar buttons |
| v10 | Four fixes: (1) sidebar row-filter search replaces toolbar chart-dimming search; (2) sidebar list scoped to current time range; (3) day-boundary markers with tri-timezone labels; (4) dynamic chart width computed client-side per redraw |
| v11 | Date-range indicator in toolbar: compact `<span id="drng">` between Download CSV and the flex spacer, showing `[DayName, DD Mon YYYY, UTC: HH:MM, GMT+8: HH:MM, GMT+7: HH:MM] to [...]` for the currently visible range. Shared `fmtTs(epochSec,off)` helper and module-level `DAYS`/`MONS`/`tzList` constants replace inline date math in `buildDayBoundaries`. |
| v15 | Persistent topic-stats table below the chart (first/best/last rank + GMT+7 timestamps, "(still trending)" flag); Light/Dark PNG toolbar buttons; `docs/index.html` header/footer chrome removed (redundant with the iframed chart's own toolbar/footer). |
| v16 | Per-row clipboard-copy button + "Copy search query" button in the topic-stats table; "License: MIT" footer link added. |
| v19 | (see CHANGELOG.md for the fix applied on top in v20) |
| v20 | **Calendar picker fix**: `e.stopPropagation()` in the day-cell/month-nav/Apply/Cancel handlers so a click inside the custom date-range picker no longer gets misread as a click-outside and closes the panel before a selection registers. "License: MIT" footer link removed. See CHANGELOG.md for the full root-cause writeup. `trending/report.py` (see Architecture above) is the ported, actively-maintained successor of this notebook's chart code — it independently avoids the same class of bug via `event.composedPath()` instead. |

## Requirements

```
requests>=2.31.0
beautifulsoup4>=4.12.0
pandas>=2.0.0
plotly>=5.18.0
```

Install:

```bash
pip install -r requirements.txt
```

`matplotlib` is only needed to run the retired notebooks manually (PNG rendering was dropped
from `trending/report.py`). Playwright is not required for the current scraper — install it
only if the detail-stats table is confirmed to be JS-injected on the Indonesia subpage:

```bash
pip install playwright && playwright install chromium
```

## Usage

```bash
python -m trending.scraper   # fetch + append to dataset/trends/trends24_id.csv
python -m trending.report    # rebuild dataset/trends/latest_interactive.html
```

Then, to rebuild the deployed site (see "Building the site locally" above):

```bash
cd site && npm install && npm run build
```

**Config** (`trending/report.py` module constants) — the values you'd change for normal use:

| Constant | Default | Description |
|----------|---------|-------------|
| `LOOKBACK_DAYS` | `90` | How much history gets embedded in the dashboard HTML |
| `TOP_N` | `15` | Number of top-ranked topics to display |
| `PALETTE_SIZE` | `150` | Colors in the pumpkin palette (must stay at 150) |

`trending/scraper.py`'s `MIN_EXPECTED_TRENDS` (default `30`) is the schema-drift guard —
raises if the largest hour-column is smaller, rather than silently writing partial data.

## Scraping policy

`trends24.in/robots.txt` blocks named AI-training crawlers but permits the generic
`User-agent: *` catch-all. The scraper uses an honest, non-spoofed User-Agent string and
reads ranked topic names into a chart (reference use, not model training). One request per
scrape run.

## License

MIT License

Copyright (c) 2026 ishakmartins.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
