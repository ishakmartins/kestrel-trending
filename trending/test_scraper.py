"""Self-check for trending.scraper parsing + dedupe. Run: python trending/test_scraper.py"""
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from trending.scraper import (
    append_rows,
    join_data,
    normalize_trend_name,
    parse_timeline_columns,
    parse_tweet_count,
)

FIXTURE_HTML = """
<html><body>
<div class="list-container"><h3>Wed Jul 22 2026 23:00:00 GMT+0000 (Coordinated Universal Time)</h3>
<ol>
<li><a title="74M Tweets">#Topic One</a></li>
<li><a title="1.2K Tweets">Topic Two</a></li>
</ol></div>
<div class="list-container"><h3>Wed Jul 22 2026 22:00:00 GMT+0000 (Coordinated Universal Time)</h3>
<ol>
<li><a title="500 Tweets">Topic Two</a></li>
</ol></div>
</body></html>
"""


def demo():
    assert normalize_trend_name("#Foo  Bar ") == "foo bar"
    assert parse_tweet_count("74M Tweets") == 74_000_000
    assert parse_tweet_count("1.2K") == 1200
    assert parse_tweet_count("") is None

    soup = BeautifulSoup(FIXTURE_HTML, "html.parser")
    cols = parse_timeline_columns(soup, min_trends=1)
    assert len(cols) == 2
    assert cols[0]["trends"][0]["name"] == "#Topic One"
    assert cols[0]["trends"][0]["tweet_count"] == 74_000_000

    run_ts = datetime(2026, 7, 22, 23, 5, tzinfo=timezone.utc)
    df1 = join_data(cols, run_ts, "run1", "https://example.test")
    assert len(df1) == 3

    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "trends24_id.csv"
        combined1 = append_rows(df1, csv_path)
        assert len(combined1) == 3
        assert combined1["captured_at_utc"].notna().all(), "captured_at_utc should never be null"

        # Re-read from disk: to_csv wrote pandas' space-separated Timestamp format, not
        # our isoformat() "T" format. A genuinely new hour appended next to that on-disk
        # data must still parse — this is the mixed-format round trip that silently
        # NaT'd rows before format="mixed" was added to append_rows.
        cols2 = [{**cols[0], "hour_label": "Wed Jul 22 2026 21:00:00 GMT+0000 (Coordinated Universal Time)"}]
        run_ts2 = datetime(2026, 7, 22, 21, 5, tzinfo=timezone.utc)
        df2 = join_data(cols2, run_ts2, "run2", "https://example.test")
        combined2 = append_rows(df2, csv_path)
        assert len(combined2) == 5, f"expected 2 new rows from the new hour, got {len(combined2)} total"
        assert combined2["captured_at_utc"].notna().all(), "mixed-format round trip produced NaT rows"

        # Same fetch again (idempotent-safe): same (name_norm, hour_label) pairs -> no growth.
        df3 = join_data(cols, datetime(2026, 7, 22, 23, 6, tzinfo=timezone.utc), "run3", "https://example.test")
        combined3 = append_rows(df3, csv_path)
        assert len(combined3) == 5, f"expected no duplicate growth, got {len(combined3)} rows"

    print("OK: all trending.scraper self-checks passed")


if __name__ == "__main__":
    demo()
