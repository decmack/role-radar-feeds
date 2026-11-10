# feed-cache
Nightly snapshot of public job-board JSON APIs (Greenhouse, Ashby, Lever, Workable) for the boards listed in `feeds.json`.
Keeps Sydney-eligible postings, diffs against `state/seen.json` and writes `latest.json` (new postings, per-feed counts, open ids).
A feed that errors keeps its previous snapshot. Run locally: `python3 radar.py`. Tests: `python3 -m unittest tests.test_radar`.
