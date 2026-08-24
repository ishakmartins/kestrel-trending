"""Trends24.in/indonesia/ scraper. Fetch page once, append new rows to one central CSV.

Replaces the old per-run notebook pipeline (notebooks/kestrel-trends_bumpchart-*.ipynb).
No charts here — that is report.py's job. This module's only job is fetch -> append.

detail-stats table parsing (best_position/total_tweets/trending_for_*) is dropped:
the /indonesia/ subpage never exposed that table across ~26 days of notebook runs
(confirmed always-null in the old README), so it was dead-hypothesis code. Those
columns are kept in the CSV schema (always None) for compatibility with the historical
data migrated from the notebook era, which has the same always-null columns.
"""
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("trending.scraper")

TRENDS24_URL = "https://trends24.in/indonesia/"
REQUEST_TIMEOUT = 20  # seconds
MIN_EXPECTED_TRENDS = 30  # schema-drift guard; fail loud rather than write partial data

# Honest, non-spoofed User-Agent. trends24.in/robots.txt blocks named AI-training
# crawlers but permits the generic `User-agent: *` catch-all; reading ranked topic
# names into a CSV is reference use, not model training.
USER_AGENT = (
    "Mozilla/5.0 (compatible; kestrel-trend-capture/1.0; "
    "+https://github.com/ishakmartins/kestrel-trending)"
)

CSV_COLUMNS = [
    "captured_at_utc", "run_id", "source_url", "hour_label",
    "rank", "name", "name_norm", "tweet_count_raw", "tweet_count",
    "best_position", "total_tweets", "trending_for_raw", "trending_for_hours",
]


def _find_repo_root() -> Path:
    """Walk up from cwd until .git is found. Falls back to cwd if not found within 6 levels."""
    p = Path.cwd().resolve()
    for _ in range(6):
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path.cwd().resolve()


REPO_ROOT = _find_repo_root()
CSV_PATH = REPO_ROOT / "dataset" / "trends" / "trends24_id.csv"


def normalize_trend_name(name: str) -> str:
    """Strip leading '#', collapse whitespace, lowercase - cross-hour/cross-source dedup key."""
    return re.sub(r"\s+", " ", name.lstrip("#")).strip().lower()


def parse_tweet_count(raw: str) -> int | None:
    """Parse human-readable count like '74M Tweets' -> 74_000_000; '1.2K' -> 1200.
    Returns None on empty input or unrecognised format."""
    if not raw:
        return None
    m = re.match(r"([\d.]+)\s*([KMBkmb]?)", raw.replace(",", ""))
    if not m:
        return None
    n, suffix = float(m.group(1)), m.group(2).upper()
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix)
    return int(n * mult) if mult is not None else None


def fetch_page(url: str, ua: str, timeout: int) -> BeautifulSoup:
    """GET url with honest User-Agent; raise on HTTP error; return parsed BeautifulSoup."""
    resp = requests.get(url, headers={"User-Agent": ua}, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_timeline_columns(soup: BeautifulSoup, min_trends: int = 30) -> list[dict]:
    """Parse every visible hour-column from trends24.in/indonesia/.

    Selectors: column wrapper `.list-container`, hour label first `h3` inside it,
    trend items `ol li a` (text = display name; title attr = tweet-count label).

    Raises RuntimeError on schema drift (no columns found, or largest column has fewer
    than min_trends entries). Fail loud - do not silently write partial data.
    """
    columns = []
    for col_el in soup.select(".list-container"):
        label_el = col_el.select_one("h3")
        hour_label = label_el.get_text(strip=True) if label_el else None
        trends = []
        for rank, a_tag in enumerate(col_el.select("ol li a"), start=1):
            name = a_tag.get_text(strip=True)
            if not name:
                continue
            count_raw = a_tag.get("title", "") or ""
            trends.append({
                "rank": rank,
                "name": name,
                "name_norm": normalize_trend_name(name),
                "tweet_count_raw": count_raw if count_raw else None,
                "tweet_count": parse_tweet_count(count_raw),
            })
        if trends:
            columns.append({"hour_label": hour_label, "trends": trends})

    if not columns:
        raise RuntimeError(
            "Schema drift on trends24.in/indonesia/: no '.list-container' columns found. "
            "Open the page in browser devtools and verify the column-wrapper selector - "
            "the site may have changed its markup."
        )
    max_len = max(len(c["trends"]) for c in columns)
    if max_len < min_trends:
        raise RuntimeError(
            f"Schema drift: largest column has only {max_len} trends, "
            f"expected >= {min_trends}. Verify selectors in devtools."
        )
    return columns


def join_data(
    timeline_columns: list[dict],
    captured_at_utc: datetime,
    run_id: str,
    source_url: str,
) -> pd.DataFrame:
    """Flatten timeline columns into the flat CSV row schema (one row per topic per hour).

    best_position/total_tweets/trending_for_* are always None (see module docstring).
    """
    rows = []
    for col in timeline_columns:
        for trend in col["trends"]:
            rows.append({
                "captured_at_utc": captured_at_utc.isoformat(),
                "run_id": run_id,
                "source_url": source_url,
                "hour_label": col["hour_label"],
                "rank": trend["rank"],
                "name": trend["name"],
                "name_norm": trend["name_norm"],
                "tweet_count_raw": trend.get("tweet_count_raw"),
                "tweet_count": trend.get("tweet_count"),
                "best_position": None,
                "total_tweets": None,
                "trending_for_raw": None,
                "trending_for_hours": None,
            })
    return pd.DataFrame(rows, columns=CSV_COLUMNS)


def append_rows(df_new: pd.DataFrame, csv_path: Path = CSV_PATH) -> pd.DataFrame:
    """Append df_new to csv_path, deduping on (name_norm, hour_label) — latest capture wins.

    Idempotent: running with the same hour_label data twice in a row collapses to the
    same rows, no duplicates. Rewrites the whole file each call (read + concat + dedupe +
    write) rather than a literal OS append, since dedupe requires seeing prior rows -
    fine at this data volume (tens of thousands of rows).
    """
    if csv_path.exists():
        df_old = pd.read_csv(csv_path, encoding="utf-8")
        combined = pd.concat([df_old, df_new], ignore_index=True)
    else:
        combined = df_new

    # format="mixed": rows re-read from a prior CSV write are space-separated
    # ("2026-07-26 01:08:53+00:00"), freshly-appended rows are isoformat() with a
    # literal "T" ("2026-08-21T04:18:49+00:00") — pandas' single-format fast-path
    # infers one from the majority and silently NaTs whichever format is the
    # minority, so per-row parsing is required here.
    combined["captured_at_utc"] = pd.to_datetime(
        combined["captured_at_utc"], utc=True, errors="coerce", format="mixed"
    )
    combined = combined.sort_values("captured_at_utc", ascending=False)
    combined = combined.drop_duplicates(subset=["name_norm", "hour_label"], keep="first")
    combined = combined.sort_values(["hour_label", "rank"]).reset_index(drop=True)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(csv_path, index=False, encoding="utf-8")
    log.info("CSV updated: %s (%d rows, +%d new before dedupe)", csv_path, len(combined), len(df_new))
    return combined


def run(csv_path: Path = CSV_PATH) -> pd.DataFrame:
    """Fetch trends24.in/indonesia/ once and append the parsed rows to csv_path."""
    run_ts = datetime.now(timezone.utc)
    run_id = run_ts.strftime("%Y%m%d-%H%M%S")

    log.info("Fetching %s ...", TRENDS24_URL)
    soup = fetch_page(TRENDS24_URL, USER_AGENT, REQUEST_TIMEOUT)

    timeline_columns = parse_timeline_columns(soup, min_trends=MIN_EXPECTED_TRENDS)
    log.info("Parsed %d hour-column(s)", len(timeline_columns))

    df_new = join_data(timeline_columns, run_ts, run_id, TRENDS24_URL)
    return append_rows(df_new, csv_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run()
