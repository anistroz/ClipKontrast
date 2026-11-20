"""A campaign's resource library: the raw clips folder and the best moments (timestamps pasted from a mod's message),
who sees them, each moment opening its stream at that second, and "Clip in app": a moment of a long stream made
into a clip by downloading only that part.

Runs against the code directly, with its own empty data folder and the network replaced."""
import os, subprocess, sys, tempfile, time
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-res-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="1",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import auth, brain, ctx, db, earn, jobs, media, server, transcribe  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


SOURCES = "Day 2 | https://www.youtube.com/watch?v=abc123def45&list=x\nDay 3 | https://www.youtube.com/live/xyz789ghi01"
MOMENTS = """NINE1NINE RELATED 👇
Day 3
2:37:12 wait for transition + heavy driving race to the club 🌎
2:44:30–2:45:53
2:50:57 - finally found jason

Day 2
13:29
32:57 beach intro
Previous stream | https://www.twitch.tv/videos/123456
1:04:38 wait for view
not a time 99:99:99x"""

# ---- reading the moments
g = earn.parse_moments(MOMENTS, SOURCES)
check("moments are grouped under the stream they name", [x["title"] for x in g], ["Day 3", "Day 2", "Previous stream"])
check("...a name like one of the streams gets its link", [x["url"] for x in g],
      ["https://www.youtube.com/watch?v=xyz789ghi01", "https://www.youtube.com/watch?v=abc123def45", "https://www.twitch.tv/videos/123456"])
d3 = g[0]["moments"]
check("times, ranges and labels are read", [(m["t"], m["end"], m["label"]) for m in d3],
      [(9432, None, "wait for transition + heavy driving race to the club 🌎"), (9870, 9953, ""), (10257, None, "finally found jason")])
check("each moment opens its stream at that second (YouTube, any kind of link made plain)", d3[0]["watch"], "https://www.youtube.com/watch?v=xyz789ghi01&t=9432s")
check("...a plain watch link too", g[1]["moments"][0]["watch"], "https://www.youtube.com/watch?v=abc123def45&t=809s")
check("...and on Twitch", g[2]["moments"][0]["watch"], "https://www.twitch.tv/videos/123456?t=1h4m38s")
check("a line that only looks like a time is not a moment", sum(len(x["moments"]) for x in g), 6)
check("times above any name go with the newest stream", earn.parse_moments("1:00 hello", SOURCES)[0]["url"], "https://www.youtube.com/watch?v=xyz789ghi01")
check("a stream that can't be matched still lists its moments, without links", earn.parse_moments("Old stream\n1:00 hi", "")[0]["moments"][0]["watch"], "")
# ---- the ways people really paste them
for dash in ("-", "--", "\u2010", "\u2011", "\u2013", "\u2014", "\u2212", "~", " to "):
    m = earn.parse_moments(f"2:44:30 {dash}2:45:53", SOURCES)[0]["moments"][0]
    check(f"a range with {dash!r} between the times", (m["t"], m["end"], m["label"]), (9870, 9953, ""))
g2 = earn.parse_moments("CLIP WORTHY TIMESTAMPS👇\n2:37:12 race", "Mizo | https://www.youtube.com/watch?v=LjNhaHf3tNE&t=992s")
check("a heading that names no stream goes with the newest stream", g2[0]["url"], "https://www.youtube.com/watch?v=LjNhaHf3tNE")
check("...and the start time pasted in its link is dropped", g2[0]["moments"][0]["watch"], "https://www.youtube.com/watch?v=LjNhaHf3tNE&t=9432s")
g3 = earn.parse_moments("Old stream\nhttps://youtu.be/abcdefghijk\n1:00 hi\nMore\n2:00 later", "")
check("a link on its own line is the stream of the times below it", (g3[0]["title"], g3[0]["url"]), ("Old stream", "https://www.youtube.com/watch?v=abcdefghijk"))
check("...and the next heading with no stream keeps it", g3[1]["url"], "https://www.youtube.com/watch?v=abcdefghijk")
check("a Drive folder shows inside the page", earn.drive_embed("https://drive.google.com/drive/u/0/folders/1FS-9FvroI8K5_6wWNYoAuk-nqMOTtkGt"),
      "https://drive.google.com/embeddedfolderview?id=1FS-9FvroI8K5_6wWNYoAuk-nqMOTtkGt#grid")
check("...a link that isn't a Drive folder doesn't", earn.drive_embed("https://example.com/folders/abcdefghijkl"), "")
check("the page may show Drive inside it, and nothing else new", "https://drive.google.com" in server.CSP and "frame-ancestors 'none'" in server.CSP)

# ---- saving, and who sees it
camp = earn.save_campaign({"title": "Mizo stream clips", "status": "live", "rate_per_1k": 30, "budget": 1000, "platforms": ["youtube"],
                           "sources": SOURCES, "moments": MOMENTS, "raw_clips": "drive.google.com/drive/folders/1FS-9FvroI8K5_6wWNYoAuk-nqMOTtkGt"})
check("the raw clips folder is saved as a link", camp.get("raw_clips") or earn.campaign(camp["id"], admin=True)["raw_clips"],
      "https://drive.google.com/drive/folders/1FS-9FvroI8K5_6wWNYoAuk-nqMOTtkGt")
for bad in ("javascript:alert(1)", "not a link at all"):
    try:
        earn.save_campaign({"raw_clips": bad}, camp["id"]); check(f"raw clips {bad!r} is refused", False)
    except earn.EarnError:
        check(f"raw clips {bad!r} is refused", True)
pub = earn.campaign(camp["slug"])
check("people who haven't joined see what joining unlocks", pub["resources"], {"moments": 6, "raw_clips": True})
check("everyone sees the best moments (the more people clip them, the better)", len(pub.get("moments") or []), 3)
check("...but only clippers who joined get the raw clips folder", "raw_clips" in pub, False)
check("the list of campaigns stays light: moments only on the campaign itself", "moments" in earn.campaigns()[0], False)
u = auth.signup("clipper@example.com", "test-pass-123", "Raj")[0]
with db.engine.begin() as c:
    c.execute(db.earn_members.insert().values(campaign_id=camp["id"], user_id=u.id, joined_at=time.time()))
mem = earn.campaign(camp["slug"], uid=u.id)
check("a clipper who joined sees the moments and the folder", (len(mem["moments"]), mem["raw_clips"].startswith("https://drive"), bool(mem["raw_clips_embed"])), (3, True, True))
adm = earn.campaign(camp["id"], admin=True)
check("the admin gets the moments as typed, to edit", adm["raw_moments"], MOMENTS)
earn.save_campaign({"status": "ended"}, camp["id"])
check("an ended campaign keeps them to itself", "moments" in earn.campaign(camp["slug"], uid=u.id), False)

S4 = "Day 1 | https://www.youtube.com/live/hrVIm-8R0As?si=x\nVideo of Day 1 | https://youtu.be/pB8YW4vnrew?si=y\nDay 2 | https://www.youtube.com/live/LjNhaHf3tNE?si=z"
check("'Video of Day 1' is that video, not Day 1", earn.parse_moments("Video of Day 1\n1:00 x", S4)[0]["url"], "https://www.youtube.com/watch?v=pB8YW4vnrew")
check("'Day 1' is Day 1", earn.parse_moments("Day 1\n1:00 x", S4)[0]["url"], "https://www.youtube.com/watch?v=hrVIm-8R0As")
check("'Day 2 - CLIP WORTHY TIMESTAMPS' is Day 2, its share tag dropped", earn.parse_moments("Day 2 - CLIP WORTHY TIMESTAMPS\n2:37:12 x", S4)[0]["moments"][0]["watch"],
      "https://www.youtube.com/watch?v=LjNhaHf3tNE&t=9432s")

# ---- the admin sees how the timestamps are read; the app gets every open campaign's moments
from fastapi.testclient import TestClient  # noqa: E402
web = TestClient(server.app, base_url="http://127.0.0.1:8765")
check("only an admin can ask how timestamps are read", web.post("/api/admin/earn/moments-preview", json={"moments": "1:00 x"},
                                                              headers={"Origin": "http://127.0.0.1:8765"}).status_code, 404)
check("...it says which stream each group opens", {k: v for k, v in earn.parse_moments("Day 3\n1:00 x", SOURCES)[0].items() if k in ("title", "url")},
      {"title": "Day 3", "url": "https://www.youtube.com/watch?v=xyz789ghi01"})
earn.save_campaign({"status": "live"}, camp["id"])
server._MOMENTS_CACHE.clear()
pm = web.get("/api/earn/public/moments").json()
check("the website lists the open campaigns' moments for the app, without signing in", [c["slug"] for c in pm["campaigns"]], [camp["slug"]])
check("...only groups whose stream is known (they can be clipped)", all(g["url"] for g in pm["campaigns"][0]["moments"]))
check("...and never the raw clips folder", "raw_clips" in str(pm), False)


class Site:
    status_code = 200

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


from unittest.mock import patch  # noqa: E402
odd = {"campaigns": [pm["campaigns"][0], {"slug": "x<script>", "title": "Odd", "moments": [{"title": "t", "url": "javascript:alert(1)", "moments": [{"t": 1}]}]},
                     {"nonsense": True}]}
os.environ["CLIPKONTRAST_ACCOUNTS"] = "1"
with patch("httpx.get", return_value=Site(odd)):
    server._APP_MOMENTS.clear()
    got = server.campaign_moments(type("Req", (), {"state": type("S", (), {"user": u})()})())
check("the app shows the website's campaign moments", got["campaigns"][0]["title"], "Mizo stream clips")
check("...an odd entry from the site is cleaned or skipped, never trusted", (got["campaigns"][1]["slug"], got["campaigns"][1]["moments"], len(got["campaigns"])),
      ("xscript", [], 2))
with patch("httpx.get", side_effect=OSError("offline")):
    server._APP_MOMENTS.clear()
    check("offline: no campaigns, nothing breaks", server.campaign_moments(type("Req", (), {"state": type("S", (), {"user": u})()})())["campaigns"], [])

# ---- "Clip in app": only that part of a long stream is downloaded
work = Path(tempfile.mkdtemp(prefix="pc-res-work-"))
full = work / "stream.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-t", "200", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(full)], check=True)
asked = {"whole": 0, "audio": 0, "section": None}
media.info = lambda url: {"title": "3 hour stream", "uploader": "Mizo Plays", "duration": 3 * 3600.0, "is_live": False,
                          "thumbnail": "", "kind": "video", "channel_url": ""}
media.save_thumb = lambda *a, **k: False
media.youtube_words = lambda url: None
media.download = lambda *a, **k: asked.__setitem__("whole", asked["whole"] + 1) or (_ for _ in ()).throw(RuntimeError("whole download"))
media.download_audio = lambda *a, **k: asked.__setitem__("audio", asked["audio"] + 1) or (_ for _ in ()).throw(RuntimeError("audio download"))


def fake_section(url, out_dir, stem, start, end, height=720, exact=False):
    asked["section"] = (start, end, exact)
    out = Path(out_dir) / f"{stem}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(full), "-t", f"{end - start:.2f}", "-c", "copy", str(out)], check=True)
    return out


media.download_section = fake_section
transcribe.model_ready = lambda: True
transcribe.transcribe = lambda audio, on_progress=None: [{"w": "word", "s": i * 0.5, "e": i * 0.5 + 0.4} for i in range(len(audio) // 8000)]
jobs._pick_language = lambda job, o, yt, audio, resuming=False: (job.__setitem__("lang", "en"), ("en", yt))[1]
brain.ask_ai = lambda prompt, purpose="": ([{"start": 25, "end": 70, "score": 80, "hook": "", "title": "t", "description": "", "hashtags": [],
                                             "highlight_words": [], "reason": "r", "category": "funny"}], "test-model", 5)
brain.english_captions = lambda raw, *a, **k: raw
with ctx.as_user(u.id):
    job = jobs.create({"type": "url", "url": "https://www.youtube.com/live/xyz789ghi01", "name": "x"},
                      {"range_start": 9424, "range_end": 9507, "max_clips": 1, "min_len": 15, "max_len": 60, "zoom": False}, enqueue=False)
    jobs._run_job(job)
check("only that part was downloaded, a little either side", asked["section"], (9424 - jobs.SECTION_PAD, 9507 + jobs.SECTION_PAD, True))
check("...not the whole stream, nor its whole audio", (asked["whole"], asked["audio"]), (0, 0))
check("the moment became a clip", (job["status"], [c["status"] for c in job["clips"]]), ("done", ["done"]))
c = job["clips"][0] if job["clips"] else {}
check("...inside the part asked for", 0 <= c.get("start", -1) and c.get("end", 999) <= (9507 - 9424) + 2 * jobs.SECTION_PAD)
check("...and it can be made again later, from the part kept", Path(job["source_path"]).is_file() and job["section"] == [9424 - jobs.SECTION_PAD, 9507 + jobs.SECTION_PAD])

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
