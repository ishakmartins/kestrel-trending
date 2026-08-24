# Changelog

## notebooks/kestrel-trends_bumpchart-20260824-v20.ipynb (2026-08-24)

New copy of `kestrel-trends_bumpchart-20260726-v19.ipynb` (v19 left untouched). Changes,
both in the `render_bump_chart_interactive` cell's generated JS/HTML:

- **Fixed date-range calendar picker.** Clicking a day cell or a month-nav arrow closed the
  panel instead of selecting anything. Cause: the day/nav click handlers called
  `renderCal()`, which does `el.innerHTML = html` and destroys the clicked DOM node before
  the click event finishes bubbling to the `document`-level click-outside listener; a
  detached node fails `wrap.contains(e.target)`, so the listener treated the click as
  "outside" and closed the panel. Fix: `e.stopPropagation()` in the day-cell and month-nav
  click handlers (and, as a precaution, the Apply/Cancel button handlers) so the click never
  reaches the document listener.
- **Removed the "License: MIT" footer link/button** from the rendered dashboard footer.
  Project license itself is unchanged (see `LICENSE`).

Verified: notebook executed end-to-end via `nbconvert`; `dataset/trends/latest_interactive.html`
regenerated and confirmed to contain the `e.stopPropagation()` calls and no footer License
line. Could not click-test in a live browser this session (Chrome extension not connected) —
recommend a manual pass before merging.

**Correction to an earlier note in this file**: kolibri's `trending/report.py` was checked
before assuming it needed the same patch — it does **not** have this bug. Its click-outside
listener already uses `e.composedPath().includes(wrap)` instead of `wrap.contains(e.target)`,
which is dispatch-time-fixed and unaffected by the DOM mutation that breaks `.contains()`.
No fix needed there; not touched.

## Phases 2-4: trending/ module split, Astro site, notebook-pipeline retirement (2026-08-24)

- **`trending/scraper.py` + `trending/report.py`** (new) replace the notebook-per-run CI
  pipeline. Ported from `kolibri/trending/{scraper,report}.py` — which itself was ported
  from this repo's v19 notebook — with paths/branding pointed back at kestrel-trending
  (`dataset/trends/trends24_id.csv` master CSV, `dataset/trends/latest_interactive.html`
  dashboard output, `TOP_N=15` matching the old notebook default, Alte Haas Grotesk CDN
  link restored since kolibri's copy had dropped it). `report.py`'s calendar code already
  had the composedPath fix noted above — left as-is. PNG rendering dropped entirely
  (matplotlib removed from requirements.txt); static PNGs are no longer produced anywhere
  in the pipeline.
- **Master CSV backfill**: `dataset/trends/combined/trends24_id_combined.csv` (45,304 rows)
  run through `append_rows()`'s own dedupe logic once → `dataset/trends/trends24_id.csv`,
  same row count (nothing was actually duplicated). Spot-checked: every `(name_norm,
  hour_label)` key in both the oldest (`run_20260726-010848`) and newest
  (`run_20260824-112653`) run folders' raw CSVs is present in the master CSV — 0 missing
  either direction.
- **Cleanup**: 522 `run_*/` folders, `dataset/trends/combined/`, `delete.py` (dead —
  referenced a `_to_delete/` convention that no longer exists), and the standalone PNG
  outputs (`dataset/trends/latest_{dark,light}.png`, `docs/latest_{dark,light}.png`) all
  removed. Git history untouched, as instructed.
- **`site/`** (new): Astro project mirroring `kestrel-reports`' design system (same CSS
  custom properties, dark-first theme, font stack, footer link set) and `kolibri/site/`'s
  build shape (`outDir: '../docs'`, staged dashboard+logo via
  `site/scripts/stage-dashboard.mjs`). Homepage at `docs/index.html` (replaces the old
  hand-written iframe wrapper), dashboard at `docs/trending/index.html`. GitHub Pages stays
  on the existing "main/docs" deploy — no repo settings change needed or made.
- **`.github/workflows/hourly-run.yml`** rewritten: `scrape` job every 30 min
  (`python -m trending.scraper`, cheap/append-only), `report` job hourly
  (`python -m trending.report` + `npm run build` in `site/`, commits `docs/` +
  the master CSV's dashboard-adjacent file), mirroring `kolibri.yml`'s job split.
- **`README.md`** rewritten for the new architecture; old per-run-folder section replaced,
  version history table kept with v20 appended, notebook marked retired-but-kept-for-reference.

Verified this session: `npm run build` (from `site/`) produces `docs/index.html` +
`docs/trending/index.html` with correct `/kestrel-trending/` base paths, no footer License
text, and the calendar fix's `composedPath` call present in the built dashboard.
`python -m trending.scraper` run twice back-to-back against the live page: 45,304 rows both
times (idempotent, zero net growth). `python -m trending.report`: one dashboard file, 90-day
bounded lookback, ~5.3 MB. `python -m trending.test_scraper`: self-checks pass. Could not
click-test the built dashboard in a live browser (Chrome extension not connected this
session) — recommend a manual pass before merging.

Not done, out of scope for this branch: GitHub repo Pages settings were not touched (already
correct — main/docs). No commit was made to the sibling `kolibri` repo (none needed, see
correction above).
