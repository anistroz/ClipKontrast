"""The creator tag: the streamer's channel on the clip, as a platform logo and their handle ("/Mizoplays").

The handle comes from the video's channel by itself (YouTube's @handle, the Twitch or Kick channel name, the
creator's channel link for an uploaded file) or is typed; logos for YouTube, Instagram, Kick, Twitch; four looks;
placed clear of the captions and the @handle watermark. Rendered for real with ffmpeg; nothing leaves this machine."""
import io, os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-tag-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from studio import auth, config, creators, ctx, db, jobs, media, render  # noqa: E402
from studio import tag  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- handles
check("handles written every way people paste them", [tag.clean_handle(v) for v in (
    "@Mizoplays", "/Mizoplays", "https://www.youtube.com/@Mizoplays", "kick.com/xqc", "https://twitch.tv/shroud?x=1",
    "<b>evil</b>", "x" * 50)], ["Mizoplays", "Mizoplays", "Mizoplays", "xqc", "shroud", "bevil", "x" * 30])
check("the site a link is on", [tag.platform_of(u) for u in ("https://www.youtube.com/watch?v=x", "https://youtu.be/x",
                                                             "https://www.twitch.tv/videos/1", "https://kick.com/x/videos/1", "https://example.com")],
      ["youtube", "youtube", "twitch", "kick", ""])
check("YouTube: the channel's @handle", tag.handle_from_info({"uploader_id": "@Mizoplays", "channel": "Mizo Plays"}, "https://youtu.be/x"), "Mizoplays")
check("...an old channel id isn't a handle: the name is used", tag.handle_from_info({"uploader_id": "UCabc123", "channel": "Mizo Plays"}, "https://youtu.be/x"), "MizoPlays")
check("Twitch: the channel name", tag.handle_from_info({"uploader_id": "shroud", "uploader": "shroud"}, "https://twitch.tv/videos/1"), "shroud")
check("Kick: the channel, not a number", tag.handle_from_info({"uploader_id": "1234567", "channel": "xqc"}, "https://kick.com/x"), "xqc")

# ---- settings
check("the tag's settings are checked", jobs.clean_options({"tag": True, "tag_handle": "@Mizo Plays!", "tag_platforms": ["youtube", "evil", "kick", "youtube"],
                                                             "tag_style": "<x>", "tag_pos": "nowhere"}),
      {"tag": True, "tag_handle": "MizoPlays", "tag_platforms": ["youtube", "kick"], "tag_style": "clean", "tag_pos": "bottom_left"})
try:
    jobs.clean_options({"tag": "yes"})
    check("the tag on or off, nothing else", False)
except ValueError:
    check("the tag on or off, nothing else", True)
check("a creator's look keeps the tag (their live clips use it)", creators._clean({"tag": True, "tag_style": "pill", "tag_platforms": ["kick"]}),
      {"tag": True, "tag_style": "pill", "tag_platforms": ["kick"]})

# ---- what each clip gets
job = {"handle": "Mizoplays", "platform": "youtube", "uploader": "Mizo Plays"}
check("off: nothing", tag.spec(job, {"tag": False}), None)
check("on: the video's channel and its site's logo", tag.spec(job, {"tag": True}),
      {"text": "/Mizoplays", "platforms": ["youtube"], "style": "clean", "pos": "bottom_left"})
check("a handle typed wins", tag.spec(job, {"tag": True, "tag_handle": "MizoClips"})["text"], "/MizoClips")
check("Instagram only: @handle", tag.spec(job, {"tag": True, "tag_platforms": ["instagram"]})["text"], "@Mizoplays")
check("no handle anywhere: no tag", tag.spec({}, {"tag": True}), None)
user = auth.local_user()
with ctx.as_user(user.id):
    c = creators.create({"name": "Mizo", "channels": {"youtube": "https://www.youtube.com/@Mizoplays"}})
    up = jobs._with_channel({"creator": c["id"], "handle": "", "platform": ""})
    check("an uploaded file: the creator's channel link gives the handle", (up["handle"], up["platform"]), ("Mizoplays", "youtube"))

# ---- the picture
sizes = {}
for st in tag.STYLES:
    for plats in (["youtube"], ["instagram"], ["kick"], ["twitch"], ["youtube", "instagram", "kick"], []):
        im = tag.image("/Mizoplays", plats, st)
        sizes[(st, tuple(plats))] = im.size
check("every look, with every logo (and several, and none), is drawn", all(70 <= h <= 110 and w > 100 for w, h in sizes.values()))
yt = np.asarray(tag.image("/Mizoplays", ["youtube"], "clean").convert("RGB"))
check("...YouTube's logo is red", bool(((yt[:, :, 0] > 200) & (yt[:, :, 1] < 60) & (yt[:, :, 2] < 90)).sum() > 300))
kk = np.asarray(tag.image("/xqc", ["kick"], "clean").convert("RGB"))
check("...Kick's is green", bool(((kk[:, :, 1] > 200) & (kk[:, :, 0] < 120) & (kk[:, :, 2] < 80)).sum() > 300))

# ---- where it goes
x, y = tag.place((400, 84), "bottom_left", 1476, 720, False)
check("bottom left: under the captions, inside the part the apps don't cover", (x, y > 1476 + 60, y + 84 <= 1840), (40, True, True))
check("...lower when the @handle watermark is under the captions too", tag.place((400, 84), "bottom_left", 1476, 720, True)[1] > y)
check("...the captions low on the screen: still under them", tag.place((400, 84), "bottom_left", 1640, 720, False)[1] > 1640 + 40)
check("bottom centre is centred", tag.place((400, 84), "bottom_center", 1476, 720, False)[0], 340)
check("top left: above the heading", tag.place((400, 84), "top_left", 1380, 300, False)[1] + 84 < 300 - 40)

# ---- on a real clip
work = Path(tempfile.mkdtemp(prefix="pc-tag-work-"))
src = work / "s.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223344:size=1280x720:rate=15", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
words = [{"w": "bhai", "s": 2.2, "e": 2.6}, {"w": "kya", "s": 2.7, "e": 3.0}]


def frame(name, clip):
    out = render.render_clip(src, work / "c", name, clip, words, 1280, 720)
    png = work / f"{name}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(work / "c" / out["file"]), "-frames:v", "1", str(png)], check=True)
    return np.asarray(Image.open(png).convert("RGB")).astype(int), media.probe(work / "c" / out["file"])


base = {"start": 1, "end": 5, "layout": "blur", "style": "bounce", "tighten": True}
plain, _ = frame("plain", base)
tagged, meta = frame("tagged", dict(base, tag={"text": "/Mizoplays", "platforms": ["youtube"], "style": "clean", "pos": "bottom_left"}))
check("a clip with the tag is made, 1080x1920 (with silences cut too)", (meta["width"], meta["height"]), (1080, 1920))
tx, ty = tag.place(tag.image("/Mizoplays", ["youtube"]).size, "bottom_left", render.geometry(1280, 720, "blur")[3], 0, False)
area = (slice(ty, ty + 70), slice(tx, tx + 110))
red = (tagged[area][:, :, 0] > 180) & (tagged[area][:, :, 1] < 90)
check("...YouTube's red logo is where the tag goes", int(red.sum()) > 500)
check("...and not there without it", int(((plain[area][:, :, 0] > 180) & (plain[area][:, :, 1] < 90)).sum()), 0)

# ---- changing it on a made clip
with ctx.as_user(user.id):
    j = jobs.create({"type": "file", "path": str(src), "name": "s"}, {}, enqueue=False)
    j["clips"] = [{"id": "clip01", "start": 1, "end": 5, "status": "done", "style": "bounce", "layout": "blur"}]
    queued = []
    jobs._q.put = lambda item, user=None: queued.append(item)
    jobs.request_render(j["id"], "clip01", {"tag": True, "tag_handle": "@MizoClips", "tag_style": "pill", "tag_pos": "top_left"})
    cl = j["clips"][0]
    check("a made clip: the tag turned on, another handle, another look, re-made",
          (cl["tag"], cl["tag_handle"], cl["tag_style"], cl["tag_pos"], len(queued)), (True, "MizoClips", "pill", "top_left", 1))

# ---- the server and the page
from fastapi.testclient import TestClient  # noqa: E402
from studio import server  # noqa: E402
web = TestClient(server.app, base_url="http://127.0.0.1:8765")
r = web.get("/api/tag-preview", params={"text": "Mizoplays", "platforms": "youtube,kick", "style": "pill"})
check("the style picker's pictures: the tag exactly as drawn, as a PNG", (r.status_code, r.headers["content-type"], Image.open(io.BytesIO(r.content)).size[1] > 60),
      (200, "image/png", True))
check("...the page is told the looks, logos and places", set(web.get("/api/status").json()["tag"]) >= {"styles", "platforms", "positions"})
page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the page: a Creator tag section with handle, logos, looks and place",
      all(x in page for x in ("function tagPanel", 'id="o_tag"', 'id="o_tag_handle"', "data-tagplat", 'data-seg="o_tag_style"', 'data-seg="o_tag_pos"', "/api/tag-preview?")))
check("...sent with each video", all(x in page for x in ("tag:!!$(\"#o_tag\")", "tag_platforms:", "tag_style:", "tag_pos:")))
check("...and changeable on a made clip", all(x in page for x in ('data-f="tag"', 'data-f="tag_handle"', 'data-f="tag_style"', 'data-f="tag_pos"')))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
