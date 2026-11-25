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
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
