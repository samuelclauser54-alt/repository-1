"""Self-scheduling trigger (approved by the user 2026-11-11). GitHub's cron dropped 4 of 7 slots that day
and the Mac backup only works with the lid open, so this job sleeps until the next slot, starts post-reel
(slot_check=true, so publish.py still decides and can never double-post), then starts the next keeper run.
A job may run 6 h at most, so it sleeps at most 5 h per hop."""
import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CHI = ZoneInfo("America/Chicago")
# one minute after each main window opens, plus the two trial-lane windows
TRIGGERS = ["07:01", "10:01", "11:20", "13:01", "16:01", "17:10", "18:31", "20:46", "23:01"]
MAX_HOP = 5 * 3600
REPO = os.environ["GITHUB_REPOSITORY"]


def next_trigger(now):
    for day in (0, 1):
        for hm in TRIGGERS:
            h, m = map(int, hm.split(":"))
            t = (now + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
            if t > now + timedelta(seconds=20):
                return t


def run(*args):
    for attempt in range(4):
        if subprocess.run(["gh", "workflow", "run", *args, "-R", REPO]).returncode == 0:
            return True
        time.sleep(30)
    return False


now = datetime.now(CHI)
t = next_trigger(now)
wait = (t - now).total_seconds()
print(f"now {now:%H:%M}, next slot trigger {t:%a %H:%M} Chicago, sleeping {min(wait, MAX_HOP) / 60:.0f} min", flush=True)
time.sleep(min(wait, MAX_HOP))
if wait <= MAX_HOP:
    print("starting post-reel:", run("post-reel", "-f", "dry_run=false", "-f", "slot_check=true"), flush=True)
    time.sleep(30)
print("starting next keeper:", run("keeper"), flush=True)
