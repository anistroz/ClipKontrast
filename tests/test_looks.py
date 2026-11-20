"""The look of the clips: the new caption styles, Hindi in its own script, the clipper's @handle, auto zoom on the
loudest moments, and the previews of each style shown in the app. Rendered for real with ffmpeg.

Runs against the code directly, with its own empty data folder; nothing outside this machine is contacted."""
import os, re, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-looks-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import config, creators, db, jobs, render, whisper  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


W = [{"w": w, "s": 0.2 + i * 0.5, "e": 0.6 + i * 0.5} for i, w in enumerate(["wait", "what", "bro"])]

# ---- every style is whole: its font is bundled, it makes captions, and the app has its preview
ROOT = Path(__file__).resolve().parent.parent
for key, st in render.STYLES.items():
    check(f"style {key}: its font is bundled", (ROOT / "studio" / "fonts" / render.FONT_FILES.get(st["font"], "-")).is_file())
    ass = render.build_ass(W, 0, 2, "", key, [], 300, 1480)
    check(f"style {key}: makes a caption for each word", all(w["w"].upper() in ass.upper() for w in W))
    check(f"style {key}: the app has its moving preview", all((ROOT / "web" / "brand" / "styles" / f"{key}.{e}").is_file() for e in ("webm", "jpg")))
check("the app lists the new styles", {"comic", "pop", "tall", "karaoke", "podcast"} <= set(render.STYLES))

kar = render.build_ass(W, 0, 2, "", "karaoke", [], 300, 1480)
said = [l for l in kar.splitlines() if l.startswith("Dialogue: 1,") and "fscx99" in l]
check("karaoke: a word that has been said stays lit", bool(said) and all(f"\\c&H{render.STYLES['karaoke']['active']}&" in l for l in said))
pod = render.build_ass(W, 0, 2, "", "podcast", [], 300, 1480)
check("podcast: a soft dark band sits behind the line", "\\1a&H5A&" in pod and "\\p1" in pod)
bnc = render.build_ass(W, 0, 2, "", "bounce", [], 300, 1480)
said = [l for l in bnc.splitlines() if l.startswith("Dialogue: 1,") and "fscx" in l and "\\t(0,90,\\fscx100" in l]
check("other styles: a word that has been said goes back to white", bool(said) and all("\\c&HFFFFFF&" in l for l in said))

# ---- Hindi in its own script
check("captions can be asked for in Hindi script", "deva" in whisper.CAPTION_LANGS and jobs.clean_options({"caption_lang": "deva"})["caption_lang"] == "deva")
hi = [{"w": "यह", "s": 0.2, "e": 0.5}, {"w": "पागलपन", "s": 0.5, "e": 1.0}, {"w": "bro", "s": 1.0, "e": 1.4}]
ass = render.build_ass(hi, 0, 2, "", "hype", [], 300, 1480)
check("Hindi is drawn in a font that has it, in any style", "\\fnMukta ExtraBold" in ass and "पागलपन" in ass)
job = {"options": {"caption_lang": "deva"}, "lang": "hi", "title": "t"}
got = jobs._caption_words(job, {"start": 0, "end": 2}, hi, 0)
check("in Hindi script, the words stay as they were heard (no Roman letters, no AI rewrite)", [w["w"] for w in got], ["यह", "पागलपन", "bro"])
job = {"options": {"caption_lang": "auto"}, "lang": "hi", "title": "t"}
jobs.brain.english_captions = lambda raw, *a, **k: raw          # no AI here
got = jobs._caption_words(job, {"start": 0, "end": 2}, hi, 0)
check("as before, Hinglish turns it into Roman letters", not any(re.search("[ऀ-ॿ]", w["w"]) for w in got))

# ---- the clipper's @handle
ass = render.build_ass(W, 0, 2, "", "bounce", [], 300, 1480, watermark="@an1stroz")
mark = [l for l in ass.splitlines() if ",Mark," in l and l.startswith("Dialogue")]
check("the @handle is drawn on the clip, for its whole length", len(mark) == 1 and mark[0].endswith("@an1stroz") and "0:00:02.00" in mark[0])
check("...just under the captions", f"\\pos(540,{1480 + 128})" in mark[0])
low = render.build_ass(W, 0, 2, "", "bounce", [], 300, 1640, watermark="@me")
check("...or just above them when that would be under the app's buttons", "\\pos(540,1500)" in low)
check("nothing in a handle can change the captions", jobs.clean_watermark("@me{\\b1\\pos(0,0)}\n" + "x" * 80), "@meb1pos(0,0)" + "x" * 27)
none = render.build_ass(W, 0, 2, "", "bounce", [], 300, 1480, watermark="")
check("no handle: nothing drawn", "Dialogue: 5" not in none)

# ---- the settings are checked
check("auto zoom and the handle are video settings", jobs.clean_options({"zoom": False, "watermark": " @me "}), {"zoom": False, "watermark": "@me"})
try:
    jobs.clean_options({"zoom": "yes"}); check("auto zoom must be on or off", False)
except ValueError:
    check("auto zoom must be on or off", True)
check("a new video zooms by default, with no handle", (jobs.DEFAULTS["zoom"], jobs.DEFAULTS["watermark"]), (True, ""))
c = creators._clean({"zoom": 0, "watermark": "@creator{x}"})
check("a creator's settings keep them too", (c["zoom"], c["watermark"]), (False, "@creatorx"))

# ---- auto zoom: where, and that it really zooms
work = Path(tempfile.mkdtemp(prefix="pc-looks-work-"))
src = work / "src.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi",
                "-i", "sine=f=220:sample_rate=48000", "-filter_complex", "[1:a]volume='if(between(t,4,5.2),1.0,0.06)':eval=frame[a]",
                "-map", "0:v", "-map", "[a]", "-t", "14", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(src)], check=True)
got = render.zoom_moments(src, 0, 14)
check("the loud moment is found", len(got) == 1 and 4.0 <= got[0] <= 5.3, True)
check("...and given as plain numbers", all(type(t) is float for t in got))
quiet = work / "quiet.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i",
                "anullsrc=r=48000:cl=mono", "-t", "10", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(quiet)], check=True)
check("a silent clip: no zoom", render.zoom_moments(quiet, 0, 10), [])
check("a short clip: no zoom", render.zoom_moments(src, 0, 4), [])
check("no moments: no zoom at all", (render.zoom_expr([]), render._zp("", 1080, 1920)), ("", ""))


def frame(path, t, box):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf",
                          f"crop={box[2]}:{box[3]}:{box[0]}:{box[1]},scale=64:36", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True).stdout
    return raw


def differ(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


clip = {"start": 0, "end": 12, "style": "bounce", "layout": "split", "facecam": (200, 100, 700, 500), "hook": ""}
on = render.render_clip(src, work, "on", dict(clip, zoom=True), [], 1280, 720)
off = render.render_clip(src, work, "off", dict(clip, zoom=False), [], 1280, 720)
TOP, BOTTOM = (0, 60, 1080, 600), (0, 800, 1080, 1100)
check("before the loud moment, zoom or not looks the same", differ(frame(work / "on.mp4", 2.2, TOP), frame(work / "off.mp4", 2.2, TOP)) < 1.5)
check("on the loud moment, the facecam punches in", differ(frame(work / "on.mp4", 5.4, TOP), frame(work / "off.mp4", 5.4, TOP)) > 4)
check("...and the game below stays as it was", differ(frame(work / "on.mp4", 5.4, BOTTOM), frame(work / "off.mp4", 5.4, BOTTOM)) < 1.5)
check("a clip made before auto zoom existed is not zoomed when made again", render.render_clip(src, work, "old", clip, [], 1280, 720)["file"], "old.mp4")
check("...it really isn't", differ(frame(work / "old.mp4", 5.4, TOP), frame(work / "off.mp4", 5.4, TOP)) < 1.5)
real_zp = render._zp
render._zp = lambda z, w, h: ",zoompan=nonsense_option=1" if z else ""          # an ffmpeg that can't zoom this way
try:
    got = render.render_clip(src, work, "fallback", dict(clip, zoom=True), [], 1280, 720)["file"]
except Exception as e:  # noqa: BLE001
    got = str(e)[:80]
render._zp = real_zp
check("if zooming fails, the clip is still made, without it", (got, (work / "fallback.mp4").is_file()), ("fallback.mp4", True))
for key in ("comic", "pop", "tall", "karaoke", "podcast"):
    out = render.render_clip(src, work, f"s_{key}", {"start": 0, "end": 3, "style": key, "layout": "blur", "hook": "Hook", "zoom": True,
                                                     "watermark": "@me"}, W + hi, 1280, 720)
    check(f"style {key} renders for real, with Hindi, a handle and zoom", (work / out["file"]).stat().st_size > 10000)

# ---- one clip can be made again with them changed
jid, cid = "jtest", "clip01"
jobs._jobs[jid] = {"id": jid, "user": "u", "dir": str(work), "clips": [{"id": cid, "start": 1, "end": 10, "style": "bounce", "layout": "blur"}],
                   "options": {}, "creator": None}
jobs.save = lambda job: None
jobs._q.put = lambda *a, **k: None
jobs.request_render(jid, cid, {"zoom": True, "watermark": "@new{x}", "style": "karaoke"})
c = jobs._jobs[jid]["clips"][0]
check("a clip made again takes the new zoom, handle and style", (c["zoom"], c["watermark"], c["style"], c["status"]), (True, "@newx", "karaoke", "queued"))

# ---- the previews are served, and nothing else is
from fastapi.testclient import TestClient  # noqa: E402
from studio import server  # noqa: E402
web = TestClient(server.app, base_url="http://127.0.0.1:8765")
r = web.get("/brand/styles/comic.webm")
check("a style's preview is served to the app", (r.status_code, r.headers["content-type"]), (200, "video/webm"))
for bad in ("..%2Fstyles.webm", "comic.mp4", "COMIC.webm", "x.webm"):
    check(f"/brand/styles/{bad} is refused", web.get(f"/brand/styles/{bad}").status_code, 404)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
