#!/bin/bash
# Publish the videos of not-yet-posted reels to the `media` branch (served by GitHub Pages).
# The branch is rebuilt from scratch each time, so posted videos drop out and the repo stays small.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
git pull -q --rebase origin main 2>/dev/null || true
TMP=$(mktemp -d)
python3 -c "
import json
for q in json.load(open('queue.json')):
    if q['status'] in ('queued', 'skipped'): print(q['video'])
" | while read -r v; do cp "videos/$v" "$TMP/"; done
touch "$TMP/.nojekyll"
echo '<!doctype html><title>media</title>' > "$TMP/index.html"
cd "$TMP"
git init -q -b media
git add -A
git commit -q -m "media $(date +%F)"
REMOTE="$(cd "$ROOT" && git remote get-url origin)"
ok=0   # GitHub sometimes drops this large push (HTTP 408): retry instead of leaving new videos offline
for try in 1 2 3 4 5; do
  if git push -q -f "$REMOTE" media; then ok=1; break; fi
  echo "media push failed (try $try), retrying" >&2; sleep 15
done
[ "$ok" = 1 ] || { echo "MEDIA PUSH FAILED: new videos are NOT live" >&2; exit 1; }
rm -rf "$TMP"
echo "media branch now holds $(ls "$ROOT/videos" | wc -l | tr -d ' ') local / upcoming videos pushed"
