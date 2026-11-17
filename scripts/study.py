"""Session report: where the account stands and what is working.   python3 scripts/study.py [days]
Prints followers and daily follows, every reel in the window (views, skip, watch, slot), medians by family and by
posting slot, and how many reels met the hit bar (skip < 25% and watch >= 81%). Run it at the start of each session."""
import collections
import datetime
import json
import os
import statistics as st
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = open(os.path.expanduser("~/.config/reel-autopilot/token")).read().strip()
IG = "https://graph.instagram.com/v25.0"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
CT = datetime.timezone(datetime.timedelta(hours=-6))


def get(path, **kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    try:
        return json.load(urllib.request.urlopen(f"{IG}/{path}?{q}&access_token={T}"))
    except Exception:
        return {}


def family(i):
    for pre, name in (("x-league", "league"), ("x-escape", "league")):
        if i.startswith(pre):
            return name
    fam = {"gates": "gates gates2 flip speed tiny narrow gust", "rocket": "rocket barge tumble pad drop heavy push"}
    for name, ids in fam.items():
        if i[2:] in ids.split():
            return name
    return "new world: " + i if i.startswith("x-") else "other"


Q = {q.get("media_id"): q for q in json.load(open(os.path.join(ROOT, "queue.json")))}
me = get("me", fields="followers_count,media_count")
now = int(time.time())
fc = get("me/insights", metric="follower_count", period="day", since=now - (DAYS + 1) * 86400, until=now)
print(f"followers {me.get('followers_count')}   posts {me.get('media_count')}")
if fc.get("data"):
    print("new follows per day:", "  ".join(f"{v['end_time'][5:10]}:{v['value']}" for v in fc["data"][0]["values"]))
cut = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DAYS)).isoformat()
rows = []
for m in get("me/media", fields="id,timestamp,like_count", limit=80).get("data", []):
    if m["timestamp"] < cut or m["id"] not in Q:
        continue
    q = Q[m["id"]]
    d = get(f"{m['id']}/insights", metric="views,saved,shares,ig_reels_avg_watch_time,reels_skip_rate").get("data")
    if not d:
        continue
    ins = {x["name"]: x["values"][0]["value"] for x in d}
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", os.path.join(ROOT, "videos", q["video"])],
                         capture_output=True, text=True).stdout.strip()
    t = datetime.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")).astimezone(CT)
    rows.append(dict(id=q["id"], t=t, views=ins["views"], skip=ins.get("reels_skip_rate", 0), trial=bool(q.get("trial")),
                     watch=100 * ins["ig_reels_avg_watch_time"] / 1000 / float(dur) if dur else 0))
rows.sort(key=lambda r: r["t"])
print(f"\n{'reel':14} {'posted CT':11} {'views':>8} {'skip%':>6} {'watch%':>6}")
for r in rows:
    bar = "  HIT BAR" if r["skip"] < 25 and r["watch"] >= 81 else ""
    print(f"{r['id']:14} {r['t']:%m-%d %H:%M} {r['views']:8d} {r['skip']:6.1f} {r['watch']:6.0f}{'  trial' if r['trial'] else ''}{bar}")
main = [r for r in rows if not r["trial"]]
if main:
    v = [r["views"] for r in main]
    print(f"\nmain grid: {len(v)} reels, mean {int(st.mean(v))}, median {int(st.median(v))}, over 20k: {sum(x >= 20000 for x in v)}, total {sum(v)}")
    for title, key in (("family", lambda r: family(r["id"])), ("slot", lambda r: f"{r['t'].hour:02d}h")):
        b = collections.defaultdict(list)
        for r in main:
            b[key(r)].append(r["views"])
        print(f"\nby {title}:")
        for k in sorted(b, key=lambda k: -st.median(b[k]) if title == "family" else k):
            print(f"  {k:26} n {len(b[k]):2d}  median {int(st.median(b[k])):7d}  in order: {b[k] if title == 'family' else ''}")
