"""Fetch all sources once, keep every current match with its full text, and save them to a JSON file for review.

Usage: python3 -I tools/dump_matches.py OUT.json [CACHE.json]
CACHE.json (optional) keeps zaplata.bg ads between reruns, so only new ads are downloaded.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import job_watch as j  # noqa: E402

out_path = Path(sys.argv[1])
cache_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
cache = json.loads(cache_path.read_text()) if cache_path and cache_path.exists() else {}
stats = {"errors": []}
jobs = j.zaplata({}, True, stats, set(), cache) + j.himalayas(stats) + j.jobicy(stats) + j.remoteok(stats) \
    + j.workingnomads(stats) + j.weworkremotely(stats) + j.remotive(stats)
if cache_path:
    cache_path.write_text(json.dumps(cache, ensure_ascii=False))
out, keys = [], set()
for x in jobs:
    if x["key"] in keys:
        continue
    keys.add(x["key"])
    r = j.analyse(x)
    if r:
        r["text"] = x["text"]
        out.append(r)
out_path.write_text(json.dumps(out, ensure_ascii=False))
print(len(out), "matches", stats["errors"])
