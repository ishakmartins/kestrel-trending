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

Not done this session (flagged, not attempted — see PR description): kolibri repo's
`trending/report.py` has the identical calendar bug (ported from this same notebook) and
needs the same fix, in a separate commit in that repo. Phases 2-4 of the requested revamp
(Astro site, scraper/report module split, run-folder backfill+deletion, GitHub Actions
rewrite) are not started — out of scope for this pass, see PR description for why.
