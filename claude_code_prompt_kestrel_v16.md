Create the next version of the Kestrel bump chart notebook.

Base file: `notebooks/kestrel-trends_bumpchart-20260722-v15.ipynb`
New file: copy it to `notebooks/kestrel-trends_bumpchart-20260722-v16.ipynb` (bump the date if you run this on a different day) and make all edits there. Add a changelog row in the "Changelog" markdown cell at the top describing these changes (follow the existing v1..v15 row format/style).

Make these changes to the embedded HTML/CSS/JS that `render_bump_chart_interactive` generates:

1. **Header rename**: Change every occurrence of "Kestrel - Trending Submodule" to "Kestrel - Trending (X/Twitter)". This appears in at least two places: the `<title>` tag and the `<h1>` inside `#brand`.

2. **Per-row clipboard-copy button** in the topic stats table (`#stbl`, populated by `renderStatsTable()` in the JS block): add a small button/icon using the clipboard emoji (📋) to the left of the topic name in each row's first `<td>`. Clicking it copies that row's topic name verbatim (the raw `r.name` value, not the formatted display text) to the clipboard via `navigator.clipboard.writeText()`. Give it an `aria-label` like "Copy topic" and make sure it doesn't break existing table styling/sorting.

3. **"Copy search query" button** in the table header: place it in the `<th>Topic</th>` header cell, to the right of the word "Topic" (e.g. `<th>Topic <button id="copyAllTopics">Copy search query</button></th>`). Clicking it should:
   - Collect the topic names currently in the stats table (i.e. the active/currently-displayed rows — same source list `renderStatsTable`/`buildStatsRows` uses).
   - Build a single string in this exact format, OR-joining all topics with no AND-grouping, wrapping any topic containing a space in double quotes, leaving single-word topics unquoted:
     `"search_query": "(topic1 OR topic2 OR ... OR topicN)"`
     Example shape only (do not hardcode these values — they must come from the live active topics):
     `"search_query": "(\"pemadaman bergilir\" OR mati_lampu OR PLN)"`
   - Copy that full string to the clipboard via `navigator.clipboard.writeText()`.
   - Handle the empty-list case gracefully (e.g. no-op or disabled button when there are zero active topics).

4. **Footer edits** (the `<footer id="ftr">` block):
   - Add the text "Feedback: " immediately before the `contact(at)lokanetra.dev` line, so it reads "Feedback: contact(at)lokanetra.dev".
   - Add a new line "License: MIT" where "MIT" is a hyperlink to `https://opensource.org/license/mit` (open in a new tab with `target="_blank" rel="noopener"`, consistent with the other footer links).

5. **CI schedule**: In `.github/workflows/hourly-run.yml`, change the cron schedule from `"0 */4 * * *"` (every 4 hours) to `"*/30 * * * *"` (every 30 minutes). Also consider renaming the workflow/job name from "hourly" references if any exist, for clarity, but this is optional/cosmetic.

After making changes:
- Execute the new notebook end-to-end (`jupyter nbconvert --to notebook --execute --inplace notebooks/kestrel-trends_bumpchart-20260722-v16.ipynb`) to confirm it runs clean and regenerates `dataset/trends/latest_interactive.html`.
- Open/inspect the generated `latest_interactive.html` to visually confirm: the new header text, the clipboard button per row, the "Copy search query" button in the Topic header, and the updated footer.
- Confirm the old v15 notebook is left untouched (the CI workflow already auto-resolves the latest `kestrel-trends_bumpchart-*.ipynb` file by sort order, so no other pipeline changes should be needed).
