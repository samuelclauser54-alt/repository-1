#!/bin/bash
# Publish the videos of not-yet-posted reels to the `media` branch (served by GitHub Pages).
# The branch is always ONE commit (posted videos drop out, the repo stays small), but it is built in a
# persistent local clone that knows what GitHub already has, so only NEW videos are uploaded.
# (Until 2026-11-13 this re-uploaded every queued video, ~220 MB, on each run and often timed out.)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
git pull -q --rebase origin main 2>/dev/null || true
REMOTE="$(git remote get-url origin)"
CACHE="$HOME/.cache/reel-autopilot/media"
mkdir -p "$CACHE"
cd "$CACHE"
[ -d .git ] || { git init -q -b work; git remote add origin "$REMOTE"; }
git remote set-url origin "$REMOTE"
git fetch -q --depth 1 origin media 2>/dev/null || echo "note: could not fetch the media branch, uploading everything" >&2
# rebuild the working tree from the queue
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
python3 -c "
import json
for q in json.load(open('$ROOT/queue.json')):
    if q['status'] in ('queued', 'skipped'): print(q['video'])
" | while read -r v; do cp "$ROOT/videos/$v" .; done
touch .nojekyll
echo '<!doctype html><title>media</title>' > index.html
git checkout -q --orphan "build-$$" 2>/dev/null || git checkout -q -B "build-$$"
git add -A
git commit -q -m "media $(date +%F)"
ok=0   # GitHub sometimes drops the push (HTTP 408): retry instead of leaving new videos offline
for try in 1 2 3 4 5; do
  if git push -q -f origin "HEAD:media"; then ok=1; break; fi
  echo "media push failed (try $try), retrying" >&2; sleep 15
done
git branch -q -M work 2>/dev/null || true
[ "$ok" = 1 ] || { echo "MEDIA PUSH FAILED: new videos are NOT live" >&2; exit 1; }
git gc -q --prune=now 2>/dev/null || true
echo "media branch now holds $(ls | wc -l | tr -d ' ') files; only new videos were uploaded"
