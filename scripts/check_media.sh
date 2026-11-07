#!/bin/bash
# Check that every queued video is live on GitHub Pages (Instagram fetches it from there).
cd "$(dirname "$0")/.." || exit 1
BASE="https://samuelclauser54-alt.github.io/repository-1"
bad=0
for v in $(python3 -c "import json;[print(q['video']) for q in json.load(open('queue.json')) if q['status']=='queued']"); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -I "$BASE/$v")
  [ "$code" = 200 ] || { echo "NOT LIVE ($code): $v"; bad=1; }
done
[ $bad = 0 ] && echo "all live"
