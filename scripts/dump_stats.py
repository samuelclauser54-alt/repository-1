"""Dump every reel's insights + account follower history to stats.json.
   python3 scripts/dump_stats.py [out.json]
Token from $IG_ACCESS_TOKEN or ~/.config/reel-autopilot/token. Runs on GitHub Actions (workflow `stats`) when the
local network blocks graph.instagram.com."""
import json
import os
import sys
import time
import urllib.request

T = os.environ.get("IG_ACCESS_TOKEN") or open(os.path.expanduser("~/.config/reel-autopilot/token")).read().strip()
IG = "https://graph.instagram.com/v25.0"
OUT = sys.argv[1] if len(sys.argv) > 1 else "stats.json"


def get(url):
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(url, timeout=30))
        except Exception as e:  # noqa: BLE001
            err = getattr(e, "read", lambda: b"")().decode()[:300]
            if i == 2:
                return {"error": str(e), "body": err}
            time.sleep(2)


def api(path, **kw):
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    return get(f"{IG}/{path}?{q}&access_token={T}")


out = {"fetched": int(time.time())}
out["me"] = api("me", fields="username,followers_count,follows_count,media_count")
now = int(time.time())
fc = []
for k in range(0, 30, 29):  # follower_count allows <=30 days per call
    r = api("me/insights", metric="follower_count", period="day", since=now - (k + 29) * 86400, until=now - k * 86400)
    fc += r.get("data", [{}])[0].get("values", []) if r.get("data") else []
out["follower_count"] = fc
acct = {}
for metric in ("reach", "views", "profile_views", "accounts_engaged", "follows_and_unfollows", "profile_links_taps"):
    acct[metric] = api("me/insights", metric=metric, period="day", metric_type="total_value",
                       since=now - 7 * 86400, until=now)
out["account_7d"] = acct
media, url = [], f"{IG}/me/media?fields=id,timestamp,caption,like_count,comments_count,media_product_type,permalink&limit=50&access_token={T}"
while url and len(media) < 400:
    r = get(url)
    media += r.get("data", [])
    url = r.get("paging", {}).get("next")
M = "views,reach,saved,shares,likes,comments,total_interactions,ig_reels_avg_watch_time,ig_reels_video_view_total_time,reels_skip_rate,follows,profile_visits"
for m in media:
    d = api(f"{m['id']}/insights", metric=M)
    if "error" in d:  # some metrics are not available on older reels; fall back
        d = api(f"{m['id']}/insights", metric="views,reach,saved,shares,likes,comments,ig_reels_avg_watch_time,reels_skip_rate")
    m["ins"] = {x["name"]: x["values"][0]["value"] for x in d.get("data", [])} if "data" in d else d
json.dump(out | {"media": media}, open(OUT, "w"), indent=1)
print(out["me"], len(media), "media")
