"""Post the next queued reel to Instagram. Runs from GitHub Actions cron.

Three slots a day (from 2026-11-02, user asked for 3/day): a random minute
  8:30-10:30 am, 1:30-3:00 pm and 6:30-8:00 pm Chicago time. GitHub cron is unreliable (runs come
  hours late or get dropped), so cron fires ~7 times per window and
  wait_for_slot() makes sure exactly one of them posts, catching up if late.

Safety rules (to look like a normal creator, never like a bot):
  * at most THREE posts per day, never two within 3 hours (3/day in Oct 2026
    got the third reel throttled to ~150-300 views; spacing them out is the mitigation)
  * never re-post something whose caption is already on the account
  * caption must have <= 5 hashtags and <= 2200 chars
  * reels unticked in the "Upcoming posts" issue are skipped

Env: IG_USER_ID, IG_ACCESS_TOKEN, MEDIA_BASE_URL, GITHUB_TOKEN, GITHUB_REPOSITORY, DRY_RUN
"""
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "queue.json")
IG = "https://graph.instagram.com/v25.0"
DRY = os.environ.get("DRY_RUN", "") in ("1", "true")
MIN_GAP = timedelta(hours=2)
CHI = ZoneInfo("America/Chicago")
# local hours: start, aim-by, latest catch-up
# windows run back to back so a late cron run (GitHub often drops most of them) still catches the slot
# 4 main posts a day from 2026-11-07: 3 sims + 1 lesson at night (lessons drive follows: 15-20/day while they ran)
# 7 main posts a day from 2026-11-10 (user asked for more volume): only proven formats go on this grid.
WINDOWS = {"early": (7.0, 7.75, 9.5), "morning": (10.0, 10.75, 12.5), "midday": (13.0, 13.75, 15.5),
           "afternoon": (16.0, 16.75, 18.0), "evening": (18.5, 19.25, 20.25), "late": (20.75, 21.5, 22.5),
           "night": (23.0, 23.6, 23.95)}
# Trial Reels lane (from 2026-11-06): entries with "trial": true go out as Instagram Trial Reels (shown to
# non-followers first, auto-graduated to followers if they do well: graduation_strategy SS_PERFORMANCE).
# Own windows and gaps, so they never displace a main post.
TRIAL_WINDOWS = {"trial-late-morning": (11, 12, 13), "trial-afternoon": (16, 17, 18)}
TRIAL_GAP = timedelta(hours=2)
ANY_GAP = timedelta(minutes=45)


def windows(now):
    return WINDOWS


def at_hour(now, h):
    return now.replace(hour=int(h), minute=int(round(h % 1 * 60)), second=0, microsecond=0)
# cron runs, and the Mac's backup trigger (workflow_dispatch with slot_check), obey the slot rules
SCHEDULED = os.environ.get("GITHUB_EVENT_NAME") == "schedule" or os.environ.get("SLOT_CHECK") == "true"


def wait_for_slot(last, wins=None):
    """Scheduled runs only. GitHub cron can fire hours late or not at all, so it
    fires many times per window and this decides: post once per slot, at a random
    minute between start and aim-by; a late run (cron delay) catches up right
    away, up to the latest hour. Runs outside every slot just exit."""
    now = datetime.now(CHI)
    for name, (a, b, late) in (wins or windows(now)).items():
        start = at_hour(now, a)
        if not start - timedelta(minutes=30) <= now < at_hour(now, late):
            continue
        if last and last.astimezone(CHI) >= start - timedelta(minutes=30):
            print(f"{name} slot already posted at {last.astimezone(CHI):%H:%M}: nothing to do")
            return False
        end = at_hour(now, b) - timedelta(minutes=15)
        if now < end:
            lo = max(now, start)
            at = lo + timedelta(seconds=random.uniform(0, (end - lo).total_seconds()))
            print(f"{name} slot: posting at {at:%H:%M} Chicago")
            time.sleep((at - now).total_seconds())
        else:
            print(f"{name} slot: cron ran late ({now:%H:%M} Chicago), posting now")
        return True
    print(f"{now:%H:%M} Chicago is outside the posting windows: nothing to do")
    return False


def refresh_token():
    """Instagram tokens die after 60 days unless refreshed. Refresh on every
    morning run; if Instagram hands back a *different* token we can't save it
    from here, so leave a note in the issue telling the user to run token.sh."""
    try:
        r = http("GET", "https://graph.instagram.com/refresh_access_token",
                 {"grant_type": "ig_refresh_token", "access_token": os.environ["IG_ACCESS_TOKEN"]})
    except SystemExit as e:   # e.g. token under 24 h old: harmless
        print("token refresh skipped:", e)
        return None
    days = int(r.get("expires_in", 0)) // 86400
    print(f"token refreshed, good for {days} days")
    if r.get("access_token") != os.environ["IG_ACCESS_TOKEN"]:
        return ("⚠️ **Instagram token needs saving.** On your Mac, open Terminal and run "
                "`~/reel-autopilot/scripts/token.sh refresh` (takes 5 seconds).")
    return None


def http(method, url, params=None, headers=None):
    data = None
    if params and method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    elif params:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {url.split('?')[0]} -> {e.code}: {e.read().decode()[:500]}")


def ig(method, path, **params):
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    return http(method, f"{IG}/{path}", params)


def fingerprint(text):
    """first 40 letters/digits, lowercased: survives emoji and quote-mark edits"""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())[:40]


def check_caption(text):
    tags = re.findall(r"#\w+", text)
    if len(tags) > 5:
        raise SystemExit(f"caption has {len(tags)} hashtags (max 5)")
    if len(text) > 2200:
        raise SystemExit(f"caption is {len(text)} chars (max 2200)")


# ---- GitHub control issue: tick boxes = allowed to post -------------------
ISSUE_TITLE = "📅 Upcoming posts"


def gh(method, path, body=None):
    url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}"
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def control_issue():
    for it in gh("GET", "issues?state=open&per_page=50"):
        if it["title"] == ISSUE_TITLE:
            return it
    return None


def unticked(issue):
    """ids whose box the user unticked: '- [ ] `id`'"""
    return set(re.findall(r"- \[ \] `([\w-]+)`", (issue or {}).get("body") or ""))


def render_issue(queue, note=None):
    lines = ([note, ""] if note else []) + ["Untick a box to **skip** that reel. Reels post top to bottom: 8-10 am and 5-7 pm Chicago (plus 12:30-2 pm on 3-a-day dates).",
             "Edit this issue from the GitHub app on your phone.", ""]
    for q in queue:
        if q["status"] == "queued":
            lines.append(f"- [x] `{q['id']}` {q['title']}")
        elif q["status"] == "skipped":
            lines.append(f"- [ ] `{q['id']}` {q['title']}")
    done = [q for q in queue if q["status"] == "posted"][-5:]
    if done:
        lines += ["", "**Recently posted**"] + [f"- {q['posted_at'][:10]} {q['title']}" for q in done]
    return "\n".join(lines)


def sync_issue(queue, issue, note=None):
    body = render_issue(queue, note)
    if issue:
        gh("PATCH", f"issues/{issue['number']}", {"body": body})
    else:
        gh("POST", "issues", {"title": ISSUE_TITLE, "body": body})


# ---- main -----------------------------------------------------------------
def main():
    queue = json.load(open(QUEUE))
    issue = control_issue() if os.environ.get("GITHUB_TOKEN") else None
    off = unticked(issue)
    for q in queue:   # the issue is the source of truth for skip / unskip
        if q["status"] == "queued" and q["id"] in off:
            q["status"] = "skipped"
        elif q["status"] == "skipped" and issue and q["id"] not in off:
            q["status"] = "queued"

    posted = [q for q in queue if q["status"] == "posted"]
    ts = lambda qs: max((datetime.fromisoformat(q["posted_at"]) for q in qs), default=None)
    last = ts([q for q in posted if not q.get("trial")])
    last_trial = ts([q for q in posted if q.get("trial")])
    last_any = ts(posted)
    nxt_main = next((q for q in queue if q["status"] == "queued" and not q.get("trial")), None)
    nxt_trial = next((q for q in queue if q["status"] == "queued" and q.get("trial")), None)
    tried = lambda q: datetime.fromisoformat(q["tried_at"]) if q and q.get("tried_at") else None
    now_utc = datetime.now(timezone.utc)

    err = None
    note = refresh_token() if SCHEDULED else None
    nxt = None
    if nxt_main is None and nxt_trial is None:
        print("queue empty, nothing to post")
        note = note or "⚠️ **Queue is empty.** Approve next week's series so posting keeps going."
    elif not SCHEDULED:
        nxt = nxt_main or nxt_trial                      # manual run: post the next reel now
    else:
        if nxt_main and not (last and now_utc - last < MIN_GAP) and \
                wait_for_slot(max(filter(None, [last, tried(nxt_main)]), default=None)):
            nxt = nxt_main
        elif nxt_trial and not (last_trial and now_utc - last_trial < TRIAL_GAP) and \
                not (last_any and now_utc - last_any < ANY_GAP) and \
                wait_for_slot(max(filter(None, [last_trial, tried(nxt_trial)]), default=None), TRIAL_WINDOWS):
            nxt = nxt_trial
        else:
            print("no lane due right now")
    if nxt is not None:
        try:
            caption = open(os.path.join(ROOT, "captions", f"{nxt['id']}.txt")).read().strip()
            check_caption(caption)
            url = f"{os.environ['MEDIA_BASE_URL'].rstrip('/')}/{nxt['video']}"
            print(f"posting {nxt['id']}  ({url})")
            if DRY:
                print("DRY_RUN: would post now. Caption:\n" + caption)
            else:
                uid = os.environ["IG_USER_ID"]
                recent = ig("GET", f"{uid}/media", fields="caption,timestamp", limit=50).get("data", [])
                if any(fingerprint(m.get("caption")) == fingerprint(caption) for m in recent):
                    print("already on the account: marking posted, not re-posting")
                    nxt.update(status="posted", posted_at=datetime.now(timezone.utc).isoformat())
                else:
                    extra = {}
                    if nxt.get("trial"):
                        extra["trial_params"] = json.dumps({"graduation_strategy": "SS_PERFORMANCE"})
                    if nxt.get("thumb_ms") is not None:
                        extra["thumb_offset"] = str(int(nxt["thumb_ms"]))
                    c = ig("POST", f"{uid}/media", media_type="REELS", video_url=url,
                           caption=caption, share_to_feed="true", **extra)["id"]
                    for _ in range(30):   # Instagram downloads + transcodes the video
                        time.sleep(20)
                        st = ig("GET", c, fields="status_code,status")
                        print("  container:", st.get("status_code"))
                        if st.get("status_code") == "FINISHED":
                            break
                        if st.get("status_code") in ("ERROR", "EXPIRED"):
                            nxt["status"] = "failed"
                            nxt["error"] = st.get("status", "")
                            break
                    else:
                        raise SystemExit("container never finished")
                    if nxt["status"] != "failed":
                        mid = ig("POST", f"{uid}/media_publish", creation_id=c)["id"]
                        nxt.update(status="posted", media_id=mid,
                                   posted_at=datetime.now(timezone.utc).isoformat())
                        print("  published media", mid)
                        if nxt.get("comment"):   # optional first comment from the account (context, no spoilers)
                            try:
                                time.sleep(8)
                                ig("POST", f"{mid}/comments", message=nxt["comment"])
                                print("  first comment posted")
                            except SystemExit as e:   # never let a comment failure undo a successful post
                                print("  first comment failed:", str(e)[:120])
        except SystemExit as e:   # API error: keep it queued (retried next slot), tell the user
            err = str(e)[:300]
            nxt["tried_at"] = datetime.now(timezone.utc).isoformat()   # one try per slot
            note = (f"⚠️ **Posting failed:** `{err}`\n\nIf it says *API access blocked* or mentions the token: "
                    "open developers.facebook.com → your app, fix any alert, generate a new token, then run "
                    "`~/reel-autopilot/scripts/token.sh save` in Terminal. The reel is retried next slot.")

    json.dump(queue, open(QUEUE, "w"), indent=2, ensure_ascii=False)
    open(QUEUE, "a").write("\n")
    if os.environ.get("GITHUB_TOKEN"):
        sync_issue(queue, issue, note)
    if nxt and nxt["status"] == "failed":
        sys.exit(f"Instagram rejected {nxt['id']}: {nxt.get('error')}")
    if err:
        sys.exit(err)


if __name__ == "__main__":
    main()
