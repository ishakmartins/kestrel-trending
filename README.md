# kestrel-trending

Scrapes Indonesia's Twitter/X trending topics from [trends24.in/indonesia/](https://trends24.in/indonesia/) and renders a rank-over-time bump chart. One HTTP request per run; outputs a raw CSV and a PNG.

## What it produces

Each run writes to `dataset/trends/run_<YYYYMMDD-HHMMSS>/`:

| File | Description |
|------|-------------|
| `trends24_id_raw_<run_id>.csv` | Flat denormalized table — one row per topic per hour-column |
| `trends24_id_bumpchart_<run_id>.png` | Bump chart: rank (Y) over time (X), top N topics (light mode) |
| `trends24_id_bumpchart_<run_id>_dark.png` | Same chart on a `#121212` dark background with brighter palette |
| `trends24_id_bumpchart_<run_id>_interactive.html` | Self-contained Plotly interactive chart (hover-highlight, topic search) |

After each run, stable "latest" copies are refreshed at `dataset/trends/`:

| File | Description |
|------|-------------|
| `latest_light.png` | Most recent light PNG |
| `latest_dark.png` | Most recent dark PNG |
| `latest_interactive.html` | Most recent interactive HTML |

The CSV schema:

```
captured_at_utc, run_id, source_url, hour_label,
rank, name, name_norm, tweet_count_raw, tweet_count,
best_position, total_tweets, trending_for_raw, trending_for_hours
```

`best_position`, `total_tweets`, and `trending_for_*` are currently `null` — trends24.in's Indonesia subpage does not expose the detail-stats table that the worldwide page has.

## Chart features

- **Y-axis**: rank 1 at top, inverted, capped at `TOP_N`
- **X-axis**: dual top + bottom labels; each column shows three time zones — `UTC / GMT+8 / GMT+7`
- **Lines**: one per topic, colored from a stable 150-color warm-autumn (pumpkin) palette
- **Nodes**: boxed keyword label at each topic's **first** and **last** non-NaN hour only (decluttered from v5's every-hour labeling, making 10pt text readable without overlap)
- **Color assignment**: `MD5(name_norm) mod 150` — same topic always gets the same color across runs and across light/dark/interactive outputs
- **Overflow**: topics beyond palette size get dashed lines; chart annotates the count
- **Dark mode PNG**: separate `_dark.png` uses a `#121212` background and a shifted palette (lightness 55–82% instead of 35–65%) so colors stay vivid instead of muddy

## Interactive chart

The `_interactive.html` is a fully self-contained Plotly file (no CDN dependency at runtime):

- **Combined dataset**: the chart renders all collected runs merged together. Each run appends to `dataset/trends/combined/trends24_id_combined.csv`; on duplicate `(topic, hour)` pairs the later capture wins. The full history is embedded as a compact JSON blob in the HTML.
- **Scrollable x-axis**: natural pixel width (`max(1400, n_hours × 80px)`) in an `overflow-x: auto` container. Y-axis rank labels are in a sticky panel outside the scroll area so they stay visible while scrolling.
- **Boxed keyword labels**: first and last non-NaN appearance of each topic gets a bordered label box — same rule as the static PNG, via Plotly `layout.annotations`.
- **Dual top + bottom x-axes**: hour labels appear on both the top and bottom edge of the chart (Plotly `xaxis2`, `overlaying='x'`, `side='top'`).
- **Time-range dropdown**: Last 6h / 24h / 3d / 7d / All — filters the embedded dataset and re-renders client-side via `Plotly.react()`. No backend required.
- **Per-topic checkboxes**: sidebar checkbox list for hard show/hide of individual topics (independent of opacity dimming).
- **Unified state model**: single `S = {range, search, checked, pinned, hovered, dark}` object with one `applyVis()` function as the only `Plotly.restyle` caller, fixing the v6 race condition where hover-restore wiped the active search filter.
- **Click-to-pin**: click a trace to lock its emphasis; click again or press Escape to unpin.
- **Light/dark toggle**: both palettes embedded; swap is instant client-side. Default dark. `localStorage` remembers the last choice.
- **Topic stats panel**: hover or pin a trace to see appearances, best rank, and total tweets in a floating panel.
- **Search**: debounced (150 ms) substring filter across topic name and display name. URL query-param sync (`?range=7d&filter=foo`).
- **Download CSV**: reconstructs the combined dataset from the embedded JSON blob into a downloadable `.csv`.
- **Font**: Alte Haas Grotesk via `fonts.cdnfonts.com` CDN; fallback stack `'Helvetica Neue', Arial, sans-serif`. No local font files bundled.
- **Accessibility**: ARIA labels on all controls, Escape key clears active state, collapsible sidebar on mobile.
- **Offline-capable**: `plotly.js` is embedded in the HTML so the file works locally and on GitHub Pages without any backend.

## Notebooks

| Version | Notes |
|---------|-------|
| v1 | All visible topics, plain circle nodes |
| v2 | Limit to top 30; bold text with bounding box labels |
| v3 | Vertical per-hour gridlines; dual UTC/GMT+8/GMT+7 x-axis; `TOP_N` configurable |
| v4 | Boxed keyword labels replace dot markers at every hour position |
| v5 | Fill all rank slots 1..`TOP_N`: filter on `min(rank) <= TOP_N` instead of topic cap |
| v6 | Readable static output (2× font sizes, first+last-only labels); dark-mode PNG; Plotly interactive HTML with hover-highlight and topic search; `build_rank_pivot` shared helper; `refresh_latest_pointers` stable latest-copy outputs |
| v7 | Interactive chart overhaul: combined-dataset JSON embedded from all runs; natural-width scroll container + sticky y-axis; boxed first+last labels matching static PNG; dual top+bottom x-axes; unified JS state model fixing search+hover conflict; time-range dropdown; per-topic checkboxes; click-to-pin; light/dark toggle with localStorage; Alte Haas Grotesk font; Download CSV; URL sync; `OUTPUT_ROOT` anchored to repo root via `.git` detection |

## Requirements

```
requests>=2.31.0
beautifulsoup4>=4.12.0
pandas>=2.0.0
matplotlib>=3.7.0
plotly>=5.18.0
```

Install:

```bash
pip install -r requirements.txt
```

Playwright is not required for the current scraper. Install it only if the detail-stats table is confirmed to be JS-injected on the Indonesia subpage:

```bash
pip install playwright && playwright install chromium
```

## Usage

Open the latest versioned notebook in `notebooks/` and run all cells top to bottom. No environment variables or manual steps required.

**Config cell** (`Part B`) — the only values you need to change for normal use:

| Constant | Default | Description |
|----------|---------|-------------|
| `TRENDS24_URL` | `https://trends24.in/indonesia/` | Source page |
| `OUTPUT_ROOT` | `dataset/trends` | Output root directory |
| `TOP_N` | `15` | Number of top-ranked topics to display |
| `PALETTE_SIZE` | `150` | Colors in the pumpkin palette (must stay at 150) |
| `MIN_EXPECTED_TRENDS` | `30` | Schema-drift guard — raises if largest column is smaller |

## Scraping policy

`trends24.in/robots.txt` blocks named AI-training crawlers but permits the generic `User-agent: *` catch-all. The scraper uses an honest, non-spoofed User-Agent string and reads ranked topic names into a chart (reference use, not model training). One request per run.

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
