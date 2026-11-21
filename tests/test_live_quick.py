"""Live clipping in one step from the home screen: paste a channel (or a stream that's live now), press Start. The
creator is made by itself (or the one already there is used), auto-record goes on, and recording starts.

Runs against the code directly, with its own empty data folder and the network replaced."""
import os, sys, tempfile
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-quick-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402
from studio import db, jobs, live, media, profiles, server  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


BASE = "http://127.0.0.1:8765"
web = TestClient(server.app, base_url=BASE)
O = {"Origin": BASE}
watched, started = [], []
live.check_now = lambda cid: watched.append(cid)
profiles.refresh = lambda cid, force=False: None
profiles.preview = lambda url: {"name": "Mizo Plays", "platform": "YouTube", "followers": "1M", "pic": ""}


def fake_start(c, url):
    started.append((c["id"], url))
    return jobs.create({"type": "live", "url": url, "name": c["name"] + " live"}, {}, enqueue=False, creator=c["id"], kind="live")


live.start_session = fake_start


def quick(body):
    return web.post("/api/live/quick", json=body, headers=O)


r = quick({"url": "https://www.youtube.com/@MizoPlays", "style": "comic", "layout": "split", "zoom": False, "watermark": "@me"})
check("a channel link starts live clipping", r.status_code, 200)
d = r.json()
c = d["creator"]
check("its creator is made by itself, named from the channel", (d["made"], c["name"], c["channel"]), (True, "Mizo Plays", "https://www.youtube.com/@MizoPlays"))
check("this stream is recorded (now, or when they go live), not every stream: auto-record stays off", (c["watch_once"], c["auto_watch"]), (True, False))
check("the look chosen on the home screen is the creator's", (c["style"], c["layout"], c["zoom"], c["watermark"]), ("comic", "split", False, "@me"))
check("it looks straight away whether they're live", watched, [c["id"]])
check("no recording is forced on a channel that may be offline", (started, d["job"]), ([], None))

r = quick({"url": "youtube.com/@mizoplays/live"})
check("the same channel again, spelled differently: no second creator", (r.status_code, r.json()["made"], r.json()["creator"]["id"]), (200, False, c["id"]))
check("...one creator in all", len(web.get("/api/creators").json() if isinstance(web.get("/api/creators").json(), list) else web.get("/api/creators").json()["creators"]), 1)

media.info = lambda url: {"title": "LIVE", "uploader": "Kick Guy", "duration": 0, "is_live": True, "thumbnail": "", "kind": "video",
                          "channel_url": "https://www.youtube.com/channel/UCkickguy"}
r = quick({"url": "https://www.youtube.com/watch?v=livelivelive"})
check("a stream that is live right now: recording starts at once", (r.status_code, bool(r.json()["job"]), started[-1][1]),
      (200, True, "https://www.youtube.com/watch?v=livelivelive"))
check("...under its channel's creator", (r.json()["creator"]["name"], r.json()["creator"]["channel"]), ("Kick Guy", "https://www.youtube.com/channel/UCkickguy"))

media.info = lambda url: {"title": "Old VOD", "uploader": "x", "duration": 3600, "is_live": False, "thumbnail": "", "kind": "video", "channel_url": ""}
r = quick({"url": "https://www.youtube.com/watch?v=oldvideo123"})
check("a video that isn't live: says to use Clip a video, makes nothing", (r.status_code, "isn't live" in r.json()["detail"]), (400, True))

profiles.preview = lambda url: (_ for _ in ()).throw(RuntimeError("offline"))
r = quick({"url": "https://www.twitch.tv/some_streamer"})
check("the channel can't be looked up: named from the link", (r.status_code, r.json()["creator"]["name"]), (200, "some_streamer"))
for bad in ("https://evil.example/@x", "", "javascript:alert(1)"):
    check(f"{bad or 'nothing'} is refused", quick({"url": bad}).status_code, 400)
check("another website can't start it", web.post("/api/live/quick", json={"url": "https://twitch.tv/x"}, headers={"Origin": "https://evil.example"}).status_code, 403)
check("a channel's two spellings are the same", (server._channel_key("https://www.youtube.com/@A/streams"), server._channel_key("youtube.com/@a")), ("youtube.com/@a", "youtube.com/@a"))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
