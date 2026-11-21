"""A creator's last stream, on their page when they aren't live: the newest stream that has ended, read from the
channel's list of streams (yt-dlp, no video), with its picture, title, length and whether YouTube has finished its
replay, ready to clip whole or as an exact moment. yt-dlp and the link lookups are replaced: nothing leaves this
machine."""
import os, sys, tempfile, types
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-last-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from studio import auth, config, creators, ctx, db, media, profiles  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


pages = []
LISTING = {"entries": [{"id": "LIVENOWxxxx", "live_status": "is_live", "title": "live now"},
                       {"id": "NEXTWEEKxxx", "live_status": "is_upcoming", "title": "soon"},
                       {"id": "LjNhaHf3tNE", "live_status": "was_live", "title": "GTA 6 day 2 2026-11-20 18:00"}]}


class FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        pages.append((url, self.opts.get("extract_flat")))
        return LISTING


sys.modules["yt_dlp"] = types.SimpleNamespace(YoutubeDL=FakeYDL)
looked = []
media.preview = lambda url: (looked.append(url), {"title": "GTA 6 day 2", "duration": 12344.0, "is_live": False,
                                                  "thumb": "data:image/jpeg;base64,AAAA", "post_live": False})[1]
got = profiles.last_stream("https://www.youtube.com/@Mizoplays")
check("a YouTube channel: its Streams list is read (just the list, no video)", pages[-1], ("https://www.youtube.com/@Mizoplays/streams", "in_playlist"))
check("...the newest stream that has ended, not the one live now or one still to come",
      (got["url"], got["title"], got["duration"], got["platform"]), ("https://www.youtube.com/watch?v=LjNhaHf3tNE", "GTA 6 day 2", 12344.0, "youtube"))
check("...with its picture, inline", got["thumb"].startswith("data:image/"))
n = len(pages)
profiles.last_stream("https://www.youtube.com/@Mizoplays/")
check("...asked again soon after: answered from what was just read", len(pages), n)
profiles.last_stream("https://www.twitch.tv/shroud")
check("Twitch: its past broadcasts, newest first", pages[-1][0], "https://www.twitch.tv/shroud/videos?filter=archives&sort=time")
LISTING["entries"] = [{"id": "x", "url": "https://evil.example/watch", "live_status": "was_live"}]
check("only video-site links are ever looked up", profiles.last_stream("https://www.youtube.com/@Other"), {})
media.preview = lambda url: {"title": "t", "duration": 9, "thumb": "", "post_live": True}
LISTING["entries"] = [{"id": "PROCESSING1", "live_status": "post_live"}]
check("a stream YouTube is still making the replay of: shown, and said so", profiles.last_stream("https://www.youtube.com/@Busy")["post_live"], True)
LISTING["entries"] = []
check("no streams: no card", profiles.last_stream("https://www.youtube.com/@Nobody"), {})

from fastapi.testclient import TestClient  # noqa: E402
from studio import server  # noqa: E402
web = TestClient(server.app, base_url="http://127.0.0.1:8765")
with ctx.as_user(auth.local_user().id):
    c = creators.create({"name": "Mizo", "channel": "https://www.youtube.com/@Mizoplays"})
r = web.get(f"/api/creators/{c['id']}/last-stream")
check("the creator's page gets it", (r.status_code, r.json().get("url")), (200, "https://www.youtube.com/watch?v=LjNhaHf3tNE"))
check("...an unknown creator: not found", web.get("/api/creators/nobody/last-stream").status_code, 404)

page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the page: a Last stream card when they aren't live, with Clip this stream, Exact moment and Watch",
      all(x in page for x in ("function drawLastStream", 'data-act="lsclip"', 'data-act="lsmoment"', "Last stream", "YouTube is still making this replay")))
check("...Exact moment opens the timeline as soon as the stream's link is found", "openMoment(\"link\", l.id)" in page and "function clipLastStream" in page)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
