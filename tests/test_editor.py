"""The clip editor: what an edit can hold, how it's checked, how it becomes the clip (cuts, transitions, sounds,
punch-ins, looks, the big text's effects) and what the editor opens with. Rendered for real with ffmpeg.

Runs against the code directly, with its own empty data folder; nothing outside this machine is contacted."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-editor-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import config, ctx, db, edit, jobs, render  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


def refused(n, fn):
    try:
        fn()
        check(n, "accepted", "refused")
    except edit.EditError:
        check(n, True)


# ---- checking an edit
e = edit.clean({"cuts": [[12, 10], [11, 13], [30, 40]], "fx": [{"t": 15, "type": "flash", "d": 9}], "sfx": [{"t": 16, "kind": "boom", "vol": 5}],
                "punch": [{"t": 18, "z": 3, "d": 1}], "look": "warm", "hook_fx": "glow", "hook_y": 5, "hook_dur": 4}, 10, 30)
check("cuts are put in order, joined where they touch and kept inside the clip", e["cuts"], [[10.0, 13.0]])
check("a transition's length, a sound's volume and a zoom are kept inside their range", (e["fx"][0]["d"], e["sfx"][0]["vol"], e["punch"][0]["z"]), (1.5, 1.5, 1.8))
check("the big text's place is kept on the screen", e["hook_y"], 120)
check("...its effect, look and how long it stays are kept", (e["hook_fx"], e["look"], e["hook_dur"]), ("glow", "warm", 4.0))
check("the default look and text effect aren't stored", edit.clean({"look": "natural", "hook_fx": "box"}, 0, 10), {})
refused("an unknown transition is refused", lambda: edit.clean({"fx": [{"t": 1, "type": "explode"}]}, 0, 10))
refused("an unknown sound is refused", lambda: edit.clean({"sfx": [{"t": 1, "kind": "../../etc/passwd"}]}, 0, 10))
refused("an unknown look is refused", lambda: edit.clean({"look": "x; rm -rf"}, 0, 10))
refused("a time that isn't a number is refused", lambda: edit.clean({"fx": [{"t": "nan", "type": "flash"}]}, 0, 10))
refused("cutting out almost the whole clip is refused", lambda: edit.clean({"cuts": [[0, 9.5]]}, 0, 10))
check("times outside the reach of the clip are brought inside it", edit.clean({"sfx": [{"t": 999, "kind": "ding"}]}, 10, 20)["sfx"][0]["t"], 32.0)

# ---- cuts and time
keep = edit.keep_from_cuts([[12, 14], [20, 21]], 10, 30)
check("the parts kept after the cuts", keep, [(0.0, 2.0), (4.0, 10.0), (11.0, 20.0)])
check("no cuts: the whole clip (an empty list)", edit.keep_from_cuts([], 10, 30), [])
check("kept parts of the cuts and of the silences cut, together", edit.intersect([(0, 5), (6, 20)], [(0, 2), (4, 20)]), [(0, 2), (4, 5), (6, 20)])
length = sum(b - a for a, b in keep)
check("a moment after a cut moves back by the cut", edit.to_out(16, 10, keep, length), 4.0)
check("a transition on a cut lands on the join", edit.to_out(14, 10, keep, length), 2.0)
check("a moment inside a cut lands on the join after it", edit.to_out(13, 10, keep, length), 2.0)

# ---- sounds, made here from nothing
for kind in edit.SOUNDS:
    f = edit.sound_file(kind)
    check(f"sound {kind}: made, and a real sound", bool(f) and f.stat().st_size > 2000)

# ---- a real clip, with every effect
work = Path(tempfile.mkdtemp(prefix="pc-editor-src-"))
src = work / "source.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=40", "-f", "lavfi", "-i",
                "sine=f=220:d=40", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
words = [{"s": 10.2 + i * 0.5, "e": 10.6 + i * 0.5, "w": w} for i, w in enumerate("bro this is actually crazy look at that".split())]
ed = edit.clean({"cuts": [[14, 16]], "fx": [{"t": 16, "type": t, "d": 0.4} for t in ["flash"]]
                 + [{"t": 11 + i * 1.6, "type": t, "d": 0.4} for i, t in enumerate(["glitch", "wipe", "spin", "shake", "whoosh", "zoom", "blur", "fade"]) if not 13.6 < 11 + i * 1.6 < 16.4],
                 "sfx": [{"t": 12, "kind": "riser"}, {"t": 20, "kind": "ding"}], "punch": [{"t": 18, "z": 1.3, "d": 1}],
                 "look": "cinema", "hook_fx": "pop", "hook_dur": 4}, 10, 30)
clip = {"start": 10, "end": 30, "layout": "blur", "hook": "WAIT FOR IT", "style": "hype", "edit": ed, "captions": True}
out_dir = work / "out"
t0 = time.time()
got = render.render_clip(src, out_dir, "fx", clip, words, 1280, 720)
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out_dir / "fx.mp4")],
                           capture_output=True, text=True).stdout or 0)
check("a clip with every transition, sounds, a punch-in, a look and a popping heading is made", got.get("file") == "fx.mp4" and not got.get("fx_note"))
check("...two seconds shorter: the part cut in the editor is gone", abs(dur - 18) < 0.15, True)
print(f"     (made in {time.time() - t0:.1f}s)")
ass = (out_dir / "fx.ass").read_text(encoding="utf-8")
check("the heading pops in (grows from small) and leaves after 4 seconds", "\\fscx30" in ass and "0:00:04.00" in ass.split("WAIT FOR IT")[0].splitlines()[-1])
# a flash is a white frame at the join (two seconds in): brightness goes up
def mean_at(t):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(out_dir / "fx.mp4"), "-frames:v", "1", "-vf", "scale=1:1",
                        "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
    return p.stdout[0] if p.stdout else 0
check("the flash lights the picture at the join", mean_at(4.0) > mean_at(3.4) + 60, True)

# effects this ffmpeg can't make never cost the clip: it's made without them, and says so
real = render._render_in
calls = []


def fake(*a, **k):
    calls.append(bool(k.get("post") or k.get("sfx")))
    if k.get("post") or k.get("sfx"):
        raise RuntimeError("Render failed: No such filter: 'rgbashift'")
    return real(*a, **k)


render._render_in = fake
got = render.render_clip(src, out_dir, "fx2", clip, words, 1280, 720)
render._render_in = real
check("an ffmpeg that can't make the effects still makes the clip, with a note", (calls, bool(got.get("fx_note"))), ([True, False], True))

# ---- saving an edit with a clip, and what the editor opens with
ctx.set_uid("u_0123456789abcdef")
job = jobs.create({"name": "test"}, {}, enqueue=False)
job.update(source_path=str(src), duration=40, width=1280, height=720, status="done",
           clips=[{"id": "c1", "start": 10.0, "end": 30.0, "hook": "WAIT", "title": "t", "description": "", "style": "hype",
                   "layout": "blur", "status": "done", "version": 1, "score": 80}])
jobs.save(job)
(Path(job["dir"]) / "words.json").write_text(json.dumps(words), encoding="utf-8")
data = jobs.editor_data(job["id"], "c1")
check("the editor gets a preview copy with room either side of the clip", (data["p0"], data["p1"]), (0.0, 40.0))
check("...a thumbnail strip, the waveform and a hype curve", (Path(job["dir"]) / "edit" / "c1" / "strip.jpg").is_file() and len(data["peaks"]) > 500 and len(data["hype"]) > 100)
check("...the clip's words, in its source time", [w["w"] for w in data["words"]][:3], ["bro", "this", "is"])
check("...where the heading and captions sit, and every caption style with its colours", data["hook_y"] > 0 and data["styles"]["hype"]["active"].startswith("#"))
check("...and the editor's choices", set(data["options"]["transitions"]) == set(edit.TRANSITIONS) and "boom" in data["options"]["sounds"])
again = jobs.editor_data(job["id"], "c1")
check("opening it again uses the same preview copy (not made twice)", again["preview"], data["preview"])
jobs._q.put = lambda *a, **k: None                # no worker here: only saving is checked
jobs.request_render(job["id"], "c1", {"start": 11, "end": 29, "edit": {"cuts": [[5, 12]], "fx": [{"t": 15, "type": "wipe"}], "look": "bw"}})
c = job["clips"][0]
check("an edit is saved with the clip, checked against its new start and end", c["edit"], {"cuts": [[11.0, 12.0]], "fx": [{"t": 15.0, "type": "wipe", "d": 0.4, "sound": True}], "look": "bw"})
jobs.request_render(job["id"], "c1", {"edit": {}})
check("an empty edit takes the edit away", "edit" not in job["clips"][0])
try:
    jobs.request_render(job["id"], "c1", {"edit": {"fx": [{"t": 15, "type": "nope"}]}})
    check("a bad edit is refused when saving", "accepted", "refused")
except ValueError:
    check("a bad edit is refused when saving", True)

# ---- the library: the person's own fonts, sounds and media, used in a clip
from studio import library  # noqa: E402
import shutil as _sh  # noqa: E402
uid = "u_0123456789abcdef"


def up(name, src_file=None, make=None):
    f = work / ("up-" + name)
    if src_file:
        _sh.copyfile(src_file, f)
    else:
        make(f)
    return f


font = library.add(uid, "font", "MyFont.ttf", up("MyFont.ttf", src_file="studio/fonts/Bangers-Regular.ttf"))
check("a font is added, with its full name read from it (what the caption renderer finds it by)", (font["kind"], font["family"]), ("font", "Bangers Regular"))
snd = library.add(uid, "sound", "bruh.mp3", up("bruh.wav", make=lambda f: subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=500:d=1.2", str(f)], check=True)))
check("a sound is added, made into AAC, with its length", (snd["kind"], round(snd["dur"], 1)), ("sound", 1.2))
img = library.add(uid, "media", "meme.png", up("meme.png", make=lambda f: subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=400x300", "-frames:v", "1", str(f)], check=True)))
check("a picture is added, with a thumbnail", (img["type"], bool(img.get("thumb"))), ("image", True))
vid = library.add(uid, "media", "reaction.mp4", up("reaction.mp4", make=lambda f: subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:r=30:d=3", "-f", "lavfi", "-i", "sine=f=800:d=3",
     "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(f)], check=True)))
check("a video is added, with its sound and length", (vid["type"], vid["audio"], round(vid["dur"])), ("video", True, 3))
for name, kind, why in [("evil.ttf", "font", "isn't a font"), ("x.exe", "media", "isn't a picture or video"), ("big.mp3", "sound", "no sound")]:
    try:
        library.add(uid, kind, name, up(name, make=lambda f: f.write_text("not really")))
        check(f"a file that {why} is refused", "accepted", "refused")
    except library.LibraryError:
        check(f"a file that {why} is refused", True)
check("the library lists them, newest first, with no paths on this computer",
      [i["kind"] for i in library.listing(uid)] == ["media", "media", "sound", "font"] and "/" not in str([i.get("family") for i in library.listing(uid)])
      and all(not str(v).startswith(str(config.DATA_DIR)) for i in library.listing(uid) for v in i.values()))
check("someone else can't reach a person's library", library.path("u_fedcba9876543210", img["id"]), None)

ed = edit.clean({"hook_font": font["id"], "cap_font": font["id"], "sfx": [{"t": 12, "kind": "lib:" + snd["id"]}],
                 "media": [{"id": img["id"], "t": 11, "d": 2, "x": 0.5, "y": 0.3, "w": 0.4}, {"id": vid["id"], "t": 14, "d": 5, "x": 0.5, "y": 0.7, "w": 0.5, "vol": 1}]},
                10, 30)
check("an edit can use library fonts, sounds and media", (ed["hook_font"], ed["sfx"][0]["kind"], len(ed["media"])), (font["id"], "lib:" + snd["id"], 2))
refused("a library id that isn't one is refused", lambda: edit.clean({"media": [{"id": "../../x", "t": 1}]}, 0, 10))
clip = {"start": 10, "end": 30, "layout": "blur", "hook": "MY OWN FONT", "style": "hype", "edit": ed, "captions": True,
        "lib": library.resolve(uid, ed)}
got = render.render_clip(src, out_dir, "lib", clip, words, 1280, 720)
ass = (out_dir / "lib.ass").read_text(encoding="utf-8")
check("a clip is made with the person's font (heading and captions), sound, picture and video", got.get("file") == "lib.mp4" and not got.get("fx_note"))
check("...the heading and the captions are drawn in their font", "Style: Hook,Bangers Regular" in ass and "Style: Cap,Bangers Regular" in ass)
# a bold or black font from a family ("Poppins ExtraBold" in "Poppins"): asked for by its full name, which every
# system finds, not by the family alone, which Windows doesn't (the heading then came out in a plain fallback font)
bold = library.add(uid, "font", "Poppins-ExtraBold.ttf", up("Poppins-ExtraBold.ttf", src_file="studio/fonts/Poppins-ExtraBold.ttf"))
check("a bold font from a family is kept under its full name", bold["family"], "Poppins ExtraBold")
idx = library._index(uid)
for it in idx:
    if it["id"] == bold["id"]:
        it["family"] = "Poppins"          # as fonts added before this fix were kept
library._save(uid, idx)
ed2 = edit.clean({"hook_font": bold["id"]}, 10, 30)
clip2 = {"start": 10, "end": 20, "layout": "blur", "hook": "BOLD FONT", "style": "hype", "edit": ed2, "captions": True, "lib": library.resolve(uid, ed2)}
render.render_clip(src, out_dir, "lib2", clip2, words, 1280, 720)
check("...and one added before is drawn by its full name too", "Style: Hook,Poppins ExtraBold," in (out_dir / "lib2.ass").read_text(encoding="utf-8"))
def colour_at(t, x, y):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(out_dir / "lib.mp4"), "-frames:v", "1", "-vf", f"crop=2:2:{x}:{y},scale=1:1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return tuple(p.stdout[:3]) if len(p.stdout) >= 3 else (0, 0, 0)
r, g_, b_ = colour_at(1.5, 540, int(0.3 * 1920))
check("...the red picture shows where it was put, when it was put there", (r, g_, b_), lambda c: c[0] > 180 and c[1] < 80 and c[2] < 80)
r2 = colour_at(5.0, 540, int(0.3 * 1920))
check("...and is gone after its two seconds", r2, lambda c: not (c[0] > 180 and c[1] < 80))
library.delete(uid, img["id"])
check("deleting a picture from the library takes its file away", library.get(uid, img["id"]) is None and library.resolve(uid, ed).get(img["id"]) is None)
# ---- the stream's own sound: turned down (or off) in the editor
check("the stream's volume is kept, from 0 to 1.5 (full volume isn't stored)", (edit.clean({"voice": 0.25}, 0, 10).get("voice"), edit.clean({"voice": 1}, 0, 10).get("voice"), edit.clean({"voice": 9}, 0, 10).get("voice")), (0.25, None, 1.5))
def loudness(f):
    p = subprocess.run(["ffmpeg", "-i", str(f), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    import re as _re
    m = _re.search(r"mean_volume: (-?[\d.]+) dB", p.stderr)
    return float(m.group(1)) if m else 0.0
full = render.render_clip(src, out_dir, "vfull", {"start": 10, "end": 18, "layout": "blur", "hook": "", "captions": False, "edit": edit.clean({"look": "warm"}, 10, 18)}, [], 1280, 720)
low = render.render_clip(src, out_dir, "vlow", {"start": 10, "end": 18, "layout": "blur", "hook": "", "captions": False, "edit": edit.clean({"look": "warm", "voice": 0.2}, 10, 18)}, [], 1280, 720)
a_, b_ = loudness(out_dir / "vfull.mp4"), loudness(out_dir / "vlow.mp4")
check("...and the clip's sound is that much quieter", (a_, b_), lambda x: x[0] - x[1] > 10)

# ---- caption words fixed by hand (report #201): kept with the edit, used in the captions, styling codes dropped
fx = edit.clean({"fix": {"12.0": "Mizo", "13.5": "{\\b1}bad<i>", "14.2": ""}}, 10, 18)
check("words fixed by hand are kept with the edit, as plain text", fx.get("fix"), {"12.00": "Mizo", "13.50": "b1badi", "14.20": ""})
ws = [{"s": 2.0, "e": 2.4, "w": "Missou"}, {"s": 3.5, "e": 3.9, "w": "x"}, {"s": 4.2, "e": 4.5, "w": "um"}, {"s": 5.0, "e": 5.3, "w": "ok"}]
check("...the captions say the fixed word, a hidden word is gone, the rest as heard (a piece starting at 10 s)",
      [w["w"] for w in edit.fix_words(ws, fx["fix"], 10.0)], ["Mizo", "b1badi", "ok"])
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
