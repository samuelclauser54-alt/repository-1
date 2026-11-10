#!/bin/bash
# Commit local queue additions safely while GitHub Actions also edits queue.json (status updates).
# Remote wins for reels it knows about (posted status); reels only present locally are appended; then push.
set -euo pipefail
cd "$(dirname "$0")/.."
git fetch -q origin main
cp queue.json /tmp/queue_local.$$.json
git show origin/main:queue.json > /tmp/queue_remote.$$.json
python3 - /tmp/queue_local.$$.json /tmp/queue_remote.$$.json <<'PY'
import json, sys
loc, rem = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
ids = {x["id"] for x in rem}
order = [x["id"] for x in loc]                       # keep MY order for queued reels
remd = {x["id"]: x for x in rem}
# remote wins once a reel is posted/failed (Actions wrote it); while still queued, local edits (order, trial flag) win
merged = [remd[x["id"]] if x["id"] in remd and remd[x["id"]]["status"] != "queued" else x for x in loc] + [x for x in rem if x["id"] not in {y["id"] for y in loc}]
posted = [x for x in merged if x["status"] != "queued"]
queued = [x for x in merged if x["status"] == "queued"]
json.dump(posted + queued, open("queue.json.merged", "w"), indent=2)
print("queued:", [x["id"] for x in queued])
PY
git checkout -q queue.json            # local changes are saved in the merged file
git pull -q --rebase origin main
mv queue.json.merged queue.json
git add -A
git commit -qm "queue: add reels $(date +%F)

Co-Authored-By: Claude <noreply@anthropic.com>" || true
git push -q
rm -f /tmp/queue_local.$$.json /tmp/queue_remote.$$.json
echo pushed
