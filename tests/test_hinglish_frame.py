"""Two things clippers asked for:

1. Hinglish captions that work: a Whisper made for Indian Hindi writes each Hindi clip's captions in Roman letters
   straight from the clip's sound (no Devanagari to spell out, no AI), downloaded once and checked against its
   SHA256SUMS; Hinglish is told from English better (three stretches, Hindi + Urdu share); a stuck model's repeats
   are taken out.
2. The webcam AND the game set on a frame of the video before any clip is made, with how the frame is shared, and
   remembered for the streamer.

The speech models and the download are replaced; ffmpeg runs for real. Nothing outside this machine is contacted."""
import hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-hl-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_UPDATE_CHECK="0", CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import auth, brain, config, ctx, db, jobs, media, render, whisper  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ================================================================ 1. Hinglish
# ---- telling Hinglish from English
class Info:
    def __init__(self, probs):
        self.all_language_probs = sorted(probs.items(), key=lambda kv: -kv[1])
        self.language, self.language_probability = self.all_language_probs[0]


class FakeDetect:
    def __init__(self, probs):
        self.probs, self.calls = probs, 0

    def transcribe(self, audio, **kw):
        self.calls += 1
        return iter([]), Info(self.probs)


whisper.installed = lambda: True
whisper.ENABLED = whisper.HL_ON = True            # tests/run.py turns Whisper off; here it's all stand-ins anyway
real_get = whisper._get
audio = (np.random.RandomState(0).normal(0, 3000, 16000 * 200)).astype(np.int16)
m = FakeDetect({"en": 0.6, "hi": 0.3, "ur": 0.05, "es": 0.05})
whisper._get = lambda note=None, name=None: m
check("Hinglish (English on top, Hindi close behind): it's Hindi", whisper.detect(audio)[0], "hi")
check("...listened to in three places, not one", m.calls, 3)
m = FakeDetect({"en": 0.93, "hi": 0.04, "de": 0.03})
check("plain English stays English", whisper.detect(audio)[0], "en")
m = FakeDetect({"ur": 0.7, "hi": 0.2, "en": 0.1})
check("Urdu on top (Whisper often calls Hindi that): the video is still handled as Hindi", jobs._detect_language({}, audio), "hi")
whisper._get = real_get

# ---- a stuck model's repeats
W = lambda t: [{"w": x, "s": float(i), "e": i + 0.5} for i, x in enumerate(t.split())]           # noqa: E731
txt = lambda ws: " ".join(w["w"] for w in ws)                                                   # noqa: E731
check("'nan nan nan nan nan nan' is cut to three", txt(whisper.drop_loops(W("haan dekh na nan nan nan nan nan nan"))), "haan dekh na nan nan nan")
check("a phrase stuck on repeat is cut", txt(whisper.drop_loops(W("oh my god oh my god oh my god oh my god bhai"))), "oh my god oh my god bhai")
check("real repeats someone says are kept", txt(whisper.drop_loops(W("bhaago bhaago bhaago police aa gayi haan haan"))), "bhaago bhaago bhaago police aa gayi haan haan")

# ---- downloading the model: every file checked against SHA256SUMS
rel = Path(tempfile.mkdtemp(prefix="pc-hl-rel-"))
files = {"config.json": b"{}", "tokenizer.json": b"{\"t\":1}", "vocabulary.json": b"[]", "preprocessor_config.json": b"{}",
         "model.bin": os.urandom(4096)}
for k, v in files.items():
    (rel / k).write_bytes(v)
(rel / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in files.items()))
from studio import fetch_model  # noqa: E402
asked = []


def fake_download(url, dest, share=(0, 100), progress=None):
    name = url.rsplit("/", 1)[1]
    asked.append(name)
    shutil.copyfile(rel / name, dest)


real_dl = fetch_model._download
fetch_model._download = fake_download
check("not downloaded yet: not ready", whisper.hinglish_ready(), False)
good = files["model.bin"]
(rel / "model.bin").write_bytes(b"tampered" + good)
check("a damaged or changed file is refused", (whisper.fetch_hinglish(), whisper.hinglish_ready(), "damaged" in whisper.hl_state["error"]), (False, False, True))
(rel / "model.bin").write_bytes(good)
asked.clear()
check("a whole, matching download: ready", (whisper.fetch_hinglish(), whisper.hinglish_ready()), (True, True))
check("...files already fetched and matching aren't fetched again", asked.count("config.json"), 0)
check("...and it isn't fetched again once it's here", (whisper.fetch_hinglish(), asked.count("model.bin")), (True, 1))
fetch_model._download = real_dl
check("a bug report says whether it's there", "Hinglish captions model: ready" in __import__("studio.diagnose", fromlist=["x"]).details())

# ---- each Hindi clip's captions, written by it
work = Path(tempfile.mkdtemp(prefix="pc-hl-work-"))
src = work / "stream.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=15", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-t", "40", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
heard = []


def fake_hinglish(a):
    heard.append(len(a) / 16000)
    return [{"w": w, "s": 1.0 + i * 0.5, "e": 1.4 + i * 0.5} for i, w in enumerate("bhai ye kya ho gaya yaar".split())]


real_hl = whisper.hinglish
whisper.hinglish = fake_hinglish
brain.english_captions = lambda *a, **k: (_ for _ in ()).throw(AssertionError("the AI was asked"))
job = {"id": "j", "dir": str(work), "lang": "hi", "options": {"caption_lang": "auto"}, "creator": None}
clip = {"id": "clip01", "start": 10.0, "end": 25.0}
got = jobs._caption_words(job, clip, [{"w": "यह", "s": 11.0, "e": 11.5}], 0.0, src)
check("a Hindi clip: its captions come from the Hinglish model, in Roman letters, no AI", [w["w"] for w in got], "bhai ye kya ho gaya yaar".split())
check("...from the clip's own sound (with a second either side)", round(heard[0]), 17)
check("...timed on the video's clock", got[0]["s"], 10.0)
jobs._caption_words(job, clip, [], 0.0, src)
check("...remaking the clip (another style) doesn't listen again", len(heard), 1)
live_clip = {"id": "clip02", "start": 110.0, "end": 120.0, "src_offset": 100.0}
got = jobs._caption_words(job, live_clip, [], 100.0, src)
check("a live clip (a piece of the stream): its sound is read from the piece, the words on the piece's clock",
      (round(heard[-1]), got[0]["s"]), (12, 10.0))
check("captions in Hindi script chosen: not used", jobs._caption_words(dict(job, options={"caption_lang": "deva"}), dict(clip, id="c3"), [{"w": "यह", "s": 11.0, "e": 11.5}], 0.0, src)[0]["w"], "यह")
brain.english_captions = lambda raw, *a, **k: raw
check("an English video: not used", jobs._caption_words(dict(job, lang="en"), dict(clip, id="c4"), [{"w": "hello", "s": 11.0, "e": 11.5}], 0.0, src)[0]["w"], "hello")
whisper.hinglish_ready = lambda: False
started = []
whisper.fetch_hinglish_soon = lambda: started.append(1)
got = jobs._caption_words(job, {"id": "c5", "start": 10.0, "end": 25.0}, [{"w": "यह", "s": 11.0, "e": 11.5}], 0.0, src)
check("not downloaded yet: it starts downloading, and the captions are made the old way (Hindi spelled out)",
      (started, got[0]["w"] in ("yah", "yeh")), ([1], True))
whisper.hinglish = real_hl

# ================================================================ 2. Webcam and game set before the clips
check("a box is checked", (jobs.clean_box([0.7, 0, 0.3, 0.3]), jobs.clean_box(None)), ([0.7, 0.0, 0.3, 0.3], None))
for bad in ([0.9, 0.9, 0.5, 0.5], [0.1, 0.1, 0.01, 0.2], [0, 0, "1", 1], [0, 0, 1], [float("nan"), 0, 0.5, 0.5], [True, 0, 0.5, 0.5]):
    try:
        jobs.clean_box(bad)
        check(f"a bad box is refused: {bad!r}", False)
    except ValueError:
        check(f"a bad box is refused: {bad!r}", True)
check("the share of the frame is one of the choices", (jobs.clean_options({"split": "half"}), jobs.clean_options({"split": "<x>"})),
      ({"split": "half"}, {"split": "balanced"}))

jobs._src_size = lambda j, c: (1280, 720)
found = []
jobs._camera = lambda j, c: (found.append(1), [10, 10, 200, 150])[1]
user = auth.local_user()
with ctx.as_user(user.id):
    j1 = {"id": "j1", "uploader": "Frame Channel", "creator": None, "clips": [],
          "options": {"cam_box": [0.75, 0.0, 0.25, 0.3], "game_box": [0.1, 0.1, 0.6, 0.8], "split": "half"}}
    c = {"id": "a", "layout": "split"}
    jobs._use_camera(j1, c)
    check("set before the clips: that's the webcam, nothing searched for", (c["facecam"], c["camera_from"], found), ([960, 0, 320, 216], "manual", []))
    check("...the game box, in the video's pixels", c["game"], [128, 72, 768, 576])
    check("...and the share of the frame", c["split"], "half")
    j2 = {"id": "j2", "uploader": "frame channel", "creator": None, "clips": [], "options": {}}
    c2 = {"id": "b", "layout": "split"}
    jobs._use_camera(j2, c2)
    check("the streamer's next video: the same webcam, game and share, remembered",
          (c2["facecam"], c2.get("game"), c2.get("split")), ([960, 0, 320, 216], [128, 72, 768, 576], "half"))
    j3 = {"id": "j3", "uploader": "Other Channel", "creator": None, "clips": [], "options": {}}
    c3 = {"id": "c", "layout": "split"}
    jobs._use_camera(j3, c3)
    check("another streamer: the whole game, the usual share", (c3.get("game"), c3.get("split")), (None, "balanced"))

# ---- making the clip
check("the share sets the webcam band's height", [render.split_top({"split": k}) for k in ("balanced", "half", "small", "big", None)], [720, 960, 608, 1312, 720])
f = render._filter("split", 1920, [960, 0, 320, 216], "", [128, 72, 768, 576], 960)
check("the game is cut out before it's placed, the webcam fills its band", "crop=768:576:128:72,scale=1080:960" in f and "scale=1080:960:force" in f)
check("captions stay on the game, whatever the share", all(render.geometry(1280, 720, "split", t)[3] > t for t in (608, 720, 960, 1312)))
out = render.render_clip(src, work / "clips", "fr", {"start": 2, "end": 6, "layout": "split", "facecam": [960, 0, 320, 216],
                                                     "game": [128, 72, 768, 576], "split": "big", "style": "bounce"},
                         [{"w": "bhai", "s": 2.5, "e": 3.0}], 1280, 720)
meta = media.probe(work / "clips" / out["file"])
check("a clip with the game box and 'Big webcam' is made, 1080x1920", (meta["width"], meta["height"]), (1080, 1920))

# ---- a frame of a link: a few seconds fetched the way clip pieces are, else the thumbnail, never just an error
real_frame, real_prev, real_sec = media.frame, media.preview, media.download_section
import base64 as _b64  # noqa: E402
thumb_jpeg = (work / "t.jpg")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:size=320x180", "-frames:v", "1", str(thumb_jpeg)], check=True)
media._PREVIEWS.clear(); media._FRAMES.clear()
media.preview = lambda url: {"title": "t", "uploader": "Frame Channel", "duration": 13 * 3600, "is_live": False,
                             "thumb": "data:image/jpeg;base64," + _b64.b64encode(thumb_jpeg.read_bytes()).decode()}
asked_at = []


def fake_section(url, out_dir, stem, start, end, height=720, exact=False):
    asked_at.append((round(start), round(end - start)))
    dst = Path(out_dir) / f"{stem}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "3", "-t", "3", "-i", str(src), "-c", "copy", str(dst)], check=True)
    return dst


media.download_section = fake_section
f = media.frame("https://www.youtube.com/watch?v=abcdefghijk", 0.35)
check("a 13-hour stream: three seconds from 35% in are fetched (the clip-piece way), not the video",
      asked_at, [(round(13 * 3600 * 0.35), 3)])
check("...and its picture comes back, in the video's shape", (f["thumb"], f["w"], f["h"]), (False, 960, 540))
media.download_section = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP Error 403: Forbidden (tried 5 ways)"))
f = media.frame("https://www.youtube.com/watch?v=abcdefghijk", 0.6)
check("YouTube won't give even a few seconds: the thumbnail, said so (not an error)", (f["thumb"], f["w"]), (True, 320))
media.preview = lambda url: {"title": "t", "uploader": "x", "duration": 100, "is_live": False, "thumb": ""}
try:
    media.frame("https://www.youtube.com/watch?v=zzzzzzzzzzz", 0.5)
    check("no picture at all: a message that says what to do", False)
except ValueError as e:
    check("no picture at all: a message that says what to do", "Fix facecam" in str(e))
media.frame, media.preview, media.download_section = real_frame, real_prev, real_sec

# ---- a stream whose replay YouTube hasn't made: said plainly, and only when that's really the reason
from studio import safe  # noqa: E402
check("YouTube's own 'live event has ended': the replay isn't ready, with what to do instead",
      ("12 hours" in safe.friendly(RuntimeError("ERROR: [youtube] x: This live event has ended. (tried 5 ways)")),
       "upload the video file" in safe.POST_LIVE), (True, True))
check("...but a note one of the other ways left behind doesn't decide it",
      safe.friendly(RuntimeError("ERROR: HTTP Error 403: Forbidden (tried 5 ways) (This live event has ended.)")) == safe.POST_LIVE, False)

# ---- the frame to draw on, from a link
from fastapi.testclient import TestClient  # noqa: E402
from studio import server  # noqa: E402
web = TestClient(server.app, base_url="http://127.0.0.1:8765")
media.frame = lambda url, at=0.35: {"image": "data:image/jpeg;base64,AAAA", "w": 1280, "h": 720, "uploader": "Frame Channel", "at": at, "live": False}
r = web.get("/api/frame", params={"url": "https://www.youtube.com/watch?v=abcdefghijk", "at": 0.6})
check("a frame of a link comes back, to draw on", (r.status_code, r.json()["w"], r.json()["at"]), (200, 1280, 0.6))
check("...with where the webcam and game were set for this streamer last time", (r.json()["last"].get("box"), r.json()["last"].get("split")),
      ([0.75, 0.0, 0.25, 0.3], "half"))
check("only video sites", web.get("/api/frame", params={"url": "http://169.254.169.254/latest"}).status_code, 400)

page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the page: a 'Set webcam & game' button on each video, with a facecam layout", all(x in page for x in ('data-act="frameset"', "function frameBtn", "facecamLayout()")))
check("...an editor with both boxes, the share and a 9:16 preview", all(x in page for x in ('id="feGame"', 'id="feCam"', "data-fesplit", 'id="fePrev"', "/api/frame?url=")))
check("...a file's frame is read in the browser, not uploaded first", "function fileFrame" in page)
check("...and each video is sent with its own frame", "...(l.frame || {})" in page and "...(f.frame || {})" in page)
check("a link whose replay YouTube hasn't made is flagged the moment it's pasted", "Replay not ready" in page and "i.post_live" in page)
check("...the editor says when it's only the thumbnail", "f.thumb ?" in page)

# the page's script must load at all: one missing bracket and the whole app is a blank page
import re as _re  # noqa: E402
if shutil.which("node"):
    js = Path(tempfile.mkdtemp(prefix="pc-js-")) / "app.mjs"
    js.write_text(max(_re.findall(r"<script[^>]*>(.*?)</script>", page, _re.S), key=len), encoding="utf-8")
    p = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    check("the page's script has no syntax errors", p.returncode == 0 or p.stderr[-300:], True)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
