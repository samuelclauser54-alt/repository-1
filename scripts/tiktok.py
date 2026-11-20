"""TikTok Content Posting API helper for reel-autopilot.

The account holder authorizes the app once; after that the token refreshes itself
(access token lasts 24 h, refresh token 365 days).

    python3 scripts/tiktok.py auth            print the login link (open it on the account holder's phone/computer)
    python3 scripts/tiktok.py code <CODE>     trade the code shown on the callback page for tokens -> ~/.tiktok_token.json
    python3 scripts/tiktok.py refresh         get a fresh access token
    python3 scripts/tiktok.py info            what the account allows (privacy options, max video length)
    python3 scripts/tiktok.py post <reel-id>  post one queued reel by id (uploads the mp4 file)
    python3 scripts/tiktok.py draft <reel-id> send it to the account's TikTok inbox as a draft; the holder taps Post
    python3 scripts/tiktok.py stats           views / likes / shares of the latest videos

Until the app passes TikTok's audit, every post is forced to SELF_ONLY (private). After the audit,
set TIKTOK_PRIVACY=PUBLIC_TO_EVERYONE.

Env (or ~/.tiktok_app.json): TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI,
MEDIA_BASE_URL (default: the GitHub Pages address that already serves the IG videos).
"""
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(ROOT, "queue.json")
API = "https://open.tiktokapis.com/v2"
TOKEN_FILE = os.path.expanduser(os.environ.get("TIKTOK_TOKEN_FILE", "~/.tiktok_token.json"))
APP_FILE = os.path.expanduser("~/.tiktok_app.json")
SCOPES = "user.info.basic,video.upload,video.publish"   # video.upload = drafts to inbox; add ",video.list" later for stats
MEDIA = os.environ.get("MEDIA_BASE_URL", "https://samuelclauser54-alt.github.io/reel-autopilot")


def app():
    cfg = json.load(open(APP_FILE)) if os.path.exists(APP_FILE) else {}
    get = lambda k: os.environ.get(k) or cfg.get(k)
    return {k: get(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI")}


def http(method, url, body=None, form=False, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"TikTok {e.code}: {e.read().decode()[:500]}")


def save(tok):
    tok["saved_at"] = int(time.time())
    with open(TOKEN_FILE, "w") as f:
        json.dump(tok, f, indent=1)
    os.chmod(TOKEN_FILE, 0o600)


def token():
    """Current access token, refreshed when it is within an hour of expiring."""
    tok = json.load(open(TOKEN_FILE))
    if time.time() > tok["saved_at"] + tok.get("expires_in", 86400) - 3600:
        tok = refresh()
    return tok["access_token"]


def refresh():
    a = app()
    old = json.load(open(TOKEN_FILE))
    tok = http("POST", f"{API}/oauth/token/", {
        "client_key": a["TIKTOK_CLIENT_KEY"], "client_secret": a["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": old["refresh_token"]}, form=True)
    if "access_token" not in tok:
        raise SystemExit(f"refresh failed: {tok}")
    save(tok)
    return tok


def reel(rid):
    for q in json.load(open(QUEUE)):
        if q["id"] == rid:
            return q
    raise SystemExit(f"no reel {rid} in queue.json")


def caption(q):
    """TikTok title: the reel's own TikTok caption if it has one, else the IG caption trimmed to 2200 chars."""
    if q.get("tiktok_caption"):
        return q["tiktok_caption"][:2200]
    path = os.path.join(ROOT, "captions", f"{q['id']}.txt")
    text = open(path).read().strip() if os.path.exists(path) else q.get("title", "")
    return text[:2200]


def video_bytes(q):
    """The reel's mp4: from videos/ on this Mac, else downloaded from GitHub Pages (works in Actions too)."""
    local = os.path.join(ROOT, "videos", q["video"])
    if os.path.exists(local):
        return open(local, "rb").read()
    return urllib.request.urlopen(f"{MEDIA}/{q['video']}", timeout=300).read()


def file_source(data):
    """FILE_UPLOAD source block. TikTok rules: chunks 5-64 MB, count = floor(size / chunk), the last chunk takes
    the remainder; a file under 64 MB goes up as one chunk. No domain verification needed (unlike PULL_FROM_URL)."""
    size = len(data)
    chunk = size if size <= 64_000_000 else 10_000_000
    return {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": size // chunk}


def upload(url, data, src):
    n, chunk, size = src["total_chunk_count"], src["chunk_size"], src["video_size"]
    for i in range(n):
        a = i * chunk
        b = size if i == n - 1 else a + chunk
        req = urllib.request.Request(url, data=data[a:b], method="PUT", headers={
            "Content-Type": "video/mp4", "Content-Length": str(b - a),
            "Content-Range": f"bytes {a}-{b - 1}/{size}"})
        try:
            urllib.request.urlopen(req, timeout=300).read()
        except urllib.error.HTTPError as e:
            raise SystemExit(f"upload chunk {i + 1}/{n} failed: {e.code} {e.read().decode()[:300]}")


def post(rid):
    q = reel(rid)
    t = token()
    info = http("POST", f"{API}/post/publish/creator_info/query/", {}, token=t)["data"]
    privacy = os.environ.get("TIKTOK_PRIVACY", "SELF_ONLY")
    if privacy not in info["privacy_level_options"]:
        raise SystemExit(f"{privacy} not allowed; options are {info['privacy_level_options']}")
    body = {
        "post_info": {
            "title": caption(q),
            "privacy_level": privacy,
            "disable_comment": False, "disable_duet": False, "disable_stitch": False,
            "video_cover_timestamp_ms": int(q.get("thumb_ms", 1000)),
            "is_aigc": False,     # code-drawn simulations, not generative-AI footage
        },
    }
    data = video_bytes(q)
    body["source_info"] = file_source(data)
    r = http("POST", f"{API}/post/publish/video/init/", body, token=t)
    pid = r.get("data", {}).get("publish_id")
    if not pid:
        raise SystemExit(f"init failed: {r}")
    upload(r["data"]["upload_url"], data, body["source_info"])
    print("publish_id", pid)
    for _ in range(60):                       # TikTok downloads + processes the video (usually < 2 min)
        time.sleep(10)
        s = http("POST", f"{API}/post/publish/status/fetch/", {"publish_id": pid}, token=t)["data"]
        print(" ", s.get("status"), s.get("fail_reason", ""))
        if s.get("status") == "PUBLISH_COMPLETE":
            return pid
        if s.get("status") == "FAILED":
            raise SystemExit(f"publish failed: {s}")
    raise SystemExit("timed out waiting for TikTok to process the video")


def draft(rid):
    """Upload-to-inbox: works before the audit. TikTok notifies the account holder, who adds the caption and posts."""
    q = reel(rid)
    t = token()
    data = video_bytes(q)
    src = file_source(data)
    r = http("POST", f"{API}/post/publish/inbox/video/init/", {"source_info": src}, token=t)
    pid = r.get("data", {}).get("publish_id")
    if not pid:
        raise SystemExit(f"draft upload failed: {r}")
    upload(r["data"]["upload_url"], data, src)
    print("draft sent, publish_id", pid)
    print("caption to paste:\n" + caption(q))
    return pid


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    a = app()
    if cmd == "auth":
        state = secrets.token_urlsafe(16)
        print("https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
            "client_key": a["TIKTOK_CLIENT_KEY"], "scope": SCOPES, "response_type": "code",
            "redirect_uri": a["TIKTOK_REDIRECT_URI"], "state": state}))
    elif cmd == "code":
        code = urllib.parse.unquote(sys.argv[2])
        tok = http("POST", f"{API}/oauth/token/", {
            "client_key": a["TIKTOK_CLIENT_KEY"], "client_secret": a["TIKTOK_CLIENT_SECRET"],
            "code": code, "grant_type": "authorization_code",
            "redirect_uri": a["TIKTOK_REDIRECT_URI"]}, form=True)
        if "access_token" not in tok:
            raise SystemExit(f"token exchange failed: {tok}")
        save(tok)
        print("saved", TOKEN_FILE, "scopes:", tok.get("scope"))
    elif cmd == "refresh":
        refresh()
        print("refreshed")
    elif cmd == "info":
        print(json.dumps(http("POST", f"{API}/post/publish/creator_info/query/", {}, token=token()), indent=1))
    elif cmd == "post":
        post(sys.argv[2])
    elif cmd == "draft":
        draft(sys.argv[2])
    elif cmd == "stats":
        fields = "id,title,create_time,view_count,like_count,comment_count,share_count,duration"
        r = http("POST", f"{API}/video/list/?fields={fields}", {"max_count": 20}, token=token())
        for v in r["data"]["videos"]:
            print(f"{time.strftime('%m-%d %H:%M', time.localtime(v['create_time']))}  "
                  f"{v.get('view_count', 0):>9,} views  {v.get('like_count', 0):>6,} likes  "
                  f"{v.get('share_count', 0):>5,} shares  {v['title'][:40]!r}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
