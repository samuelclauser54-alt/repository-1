"""Format scoreboard: which kind of reel actually spreads?
   python3 scripts/scoreboard.py --snap   append one snapshot of every post + follower count (run hourly by launchd)
   python3 scripts/scoreboard.py          report: each post at 24 h, then medians per format
Formats come from queue.json "format" (default: "lesson", or "sim" for x- ids). Snapshots live in
~/shorts/data/snapshots.csv so views can be compared at the same age (24 h) instead of whenever we look."""
import csv
import datetime as dt
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = open(os.path.expanduser("~/.config/reel-autopilot/token")).read().strip()
IG = "https://graph.instagram.com/v25.0"
SNAP = os.path.expanduser("~/shorts/data/snapshots.csv")
COLS = ["at", "media_id", "posted", "views", "reach", "likes", "comments", "shares", "saved", "avg_watch_ms", "followers"]


def get(path, **kw):
    kw["access_token"] = T
    return json.load(urllib.request.urlopen(f"{IG}/{path}?{urllib.parse.urlencode(kw)}"))


def snap():
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    fol = get("me", fields="followers_count")["followers_count"]
    rows, after = [], None
    while True:
        kw = dict(fields="id,timestamp,like_count,comments_count", limit=100)
        if after:
            kw["after"] = after
        r = get("me/media", **kw)
        for m in r["data"]:
            try:
                ins = {x["name"]: x["values"][0]["value"] for x in get(
                    f"{m['id']}/insights", metric="views,reach,saved,shares,ig_reels_avg_watch_time")["data"]}
            except Exception:
                continue
            rows.append([now, m["id"], m["timestamp"], ins["views"], ins["reach"], m.get("like_count", 0),
                         m.get("comments_count", 0), ins["shares"], ins["saved"], ins["ig_reels_avg_watch_time"], fol])
        after = r.get("paging", {}).get("cursors", {}).get("after")
        if not r.get("paging", {}).get("next"):
            break
    os.makedirs(os.path.dirname(SNAP), exist_ok=True)
    new = not os.path.exists(SNAP)
    with open(SNAP, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(COLS)
        w.writerows(rows)
    print(f"{now}: {len(rows)} posts, {fol} followers")


def ts(s):
    return dt.datetime.fromisoformat(s.replace("+0000", "+00:00"))


def report():
    queue = {q["media_id"]: q for q in json.load(open(f"{ROOT}/queue.json")) if q.get("media_id")}
    by = {}
    for r in csv.DictReader(open(SNAP)):
        by.setdefault(r["media_id"], []).append(r)
    print(f"{'reel':14} {'format':10} {'age h':>5} {'views':>7} {'@24h':>7} {'like%':>6} {'share%':>6} {'save%':>6}")
    fmt_rows = {}
    for mid, rs in sorted(by.items(), key=lambda kv: kv[1][0]["posted"]):
        q = queue.get(mid, {})
        fmt = q.get("format") or ("sim" if q.get("id", "").startswith("x-") else "lesson")
        last = rs[-1]
        age = (ts(last["at"]) - ts(last["posted"])).total_seconds() / 3600
        at24 = [r for r in rs if 20 <= (ts(r["at"]) - ts(r["posted"])).total_seconds() / 3600 <= 28]
        v24 = int(at24[0]["views"]) if at24 else None
        reach = max(int(last["reach"]), 1)
        like, share, save = (100 * int(last[k]) / reach for k in ("likes", "shares", "saved"))
        if age > 72:
            continue
        print(f"{q.get('id', mid[-8:]):14} {fmt:10} {age:5.0f} {int(last['views']):7} {v24 if v24 else '-':>7} "
              f"{like:6.2f} {share:6.2f} {save:6.2f}")
        if v24:
            fmt_rows.setdefault(fmt, []).append((v24, like, share))
    if fmt_rows:
        print("\nper format (posts with a 24 h snapshot): n, median views@24h, median like%, median share%")
        for fmt, xs in sorted(fmt_rows.items(), key=lambda kv: -statistics.median(x[0] for x in kv[1])):
            print(f"  {fmt:10} {len(xs):3} {statistics.median(x[0] for x in xs):8.0f} "
                  f"{statistics.median(x[1] for x in xs):6.2f} {statistics.median(x[2] for x in xs):6.2f}")
    fol = [(r["at"], int(r["followers"])) for rs in by.values() for r in rs]
    if fol:
        fol.sort()
        day = [f for f in fol if ts(f[0]) > ts(fol[-1][0]) - dt.timedelta(hours=24)]
        print(f"\nfollowers now {fol[-1][1]}  (+{fol[-1][1] - day[0][1]} in the last 24 h of snapshots)")


if __name__ == "__main__":
    snap() if "--snap" in sys.argv else report()
