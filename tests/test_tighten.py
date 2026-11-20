"""Two ideas from video-use, made for clips of streams: quiet pauses and filler words cut out (never the game's action:
quiet is measured by the sound, not by the talking), and the AI checking each clip's facecam after it is made,
fixing a clip whose facecam shows the game.

Rendered for real with ffmpeg; the AI is replaced. Nothing outside this machine is contacted."""
import os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-tight-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import auth, brain, creators, ctx, db, jobs, render  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


work = Path(tempfile.mkdtemp(prefix="pc-tight-work-"))


def video(name, volume, t=20):
    f = work / name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i",
                    "sine=f=300:sample_rate=48000", "-filter_complex", f"[1:a]volume='{volume}':eval=frame[a]", "-map", "0:v",
                    "-map", "[a]", "-t", str(t), "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(f)], check=True)
    return f


def dur(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True).stdout.strip() or 0)


W = [{"w": "hello", "s": 1.0, "e": 1.4}, {"w": "umm", "s": 2.0, "e": 2.6}, {"w": "so", "s": 3.0, "e": 3.3},
     {"w": "after", "s": 12.0, "e": 12.5}, {"w": "done.", "s": 15.0, "e": 15.5}]
pause = video("pause.mp4", "if(between(t,8,11),0.0,0.5)")
keep = render.tighten_plan(pause, 0, 20, W)
check("a quiet pause and a filler word are cut out", (len(keep), abs(20 - sum(b - a for a, b in keep) - 3.2) < 0.15), (3, True))
moved = render.tightened_words(W, 0, keep)
check("...the filler word's caption goes with it", [w["w"] for w in moved], ["hello", "so", "after", "done."])
check("...and the words after a cut move up with the picture", [w["s"] for w in moved], [1.0, 2.4, 8.75, 11.75])

action = video("action.mp4", "0.5")       # the game loud all through, nobody talking from 5 s to 15 s
check("the game's action with no talking is never cut", render.tighten_plan(action, 0, 20, [W[0], W[-1]]), [])
mostly = video("mostly.mp4", "if(between(t,2,16),0.0,0.5)")
check("a clip that is mostly quiet is left as it is", render.tighten_plan(mostly, 0, 20, W), [])
check("filler words are only um, uh, hmm and the like", [bool(render.FILLER.match(x)) for x in ("umm", "Uhh.", "hmm", "ahh", "um,", "umbrella", "hum", "ok")],
      [True, True, True, True, True, False, False, False])

out = render.render_clip(pause, work, "cut", {"start": 0, "end": 20, "layout": "blur", "hook": "Hook", "tighten": True, "zoom": True}, W, 1280, 720)
check("the clip made is shorter by what was cut", abs(dur(work / "cut.mp4") - (20 - out["tightened"])) < 0.15 and 3.0 < out["tightened"] < 3.4)
ass = (work / "cut.ass").read_text(encoding="utf-8")
check("its captions follow the cuts", "UMM" not in ass and ("0:00:08.75" in ass or "0:00:08.7" in ass))
out = render.render_clip(pause, work, "whole", {"start": 0, "end": 20, "layout": "split", "facecam": (0, 0, 400, 300), "hook": "H"}, W, 1280, 720)
check("switched off (and in clips made before it existed): nothing is cut", (out["tightened"], round(dur(work / "whole.mp4"), 1)), (0, 20.0))
render._tighten_filter, real = (lambda keep, fc: "nonsense[", render._tighten_filter)
out = render.render_clip(pause, work, "safe", {"start": 0, "end": 20, "layout": "blur", "hook": "H", "tighten": True}, W, 1280, 720)
render._tighten_filter = real
check("if cutting fails, the clip is still made, whole", (out["tightened"], round(dur(work / "safe.mp4"), 1)), (0, 20.0))

check("a setting for every video, on by default", (jobs.DEFAULTS["tighten"], jobs.clean_options({"tighten": False})), (True, {"tighten": False}))
check("...and for a creator", creators._clean({"tighten": 0})["tighten"], False)

# ---- the AI checks each clip's facecam after it is made
REAL_BAND = jobs._cam_band
made = []
jobs.render_one = lambda job, clip, words: made.append((clip["id"], clip.get("camera"), clip.get("facecam")))
jobs._src_size = lambda job, clip: (1920, 1080)
jobs._cam_band = lambda job, clip: b"jpeg"
user = auth.local_user()
WEBCAM, GAME = [1440, 0, 480, 360], [600, 300, 500, 400]
with ctx.as_user(user.id):
    job = {"id": "j", "uploader": "Checked Channel", "creator": None, "dir": str(work),
           "clips": [{"id": f"c{i}", "status": "done", "layout_used": "split", "facecam": box, "camera": "box"}
                     for i, box in enumerate((WEBCAM, GAME, WEBCAM))]}
    verdicts = {"c0": True, "c1": False, "c2": None}
    brain.is_streamer_cam = lambda jpeg, timeout=None: verdicts[current[0]]
    current = [None]
    real_band = REAL_BAND
    jobs._cam_band = lambda job, clip: (current.__setitem__(0, clip["id"]) or b"jpeg")
    fixed = jobs._check_cameras(job, [])
    check("a clip whose facecam shows the game is made again; the others aren't", (fixed, [m[0] for m in made]), (1, ["c1"]))
    check("...with no webcam remembered, it shows the whole picture instead", made[0][1:], ("none", None))
    jobs._remember(job, [0.75, 0.0, 0.25, 1 / 3], 3)
    made.clear()
    job["clips"][1].update(facecam=GAME, camera="box")
    jobs._check_cameras(job, [])
    check("...with this streamer's webcam remembered, it uses that", (made[0][1], jobs._iou(made[0][2], WEBCAM) > 0.9), ("box", True))
    made.clear()
    verdicts["c1"] = None
    check("the AI unable to look changes nothing", (jobs._check_cameras(job, []), made), (0, []))
    jobs._cam_band = real_band
    check("only the facecam layouts are looked at", jobs._cam_band({"dir": str(work)}, {"file": "x.mp4", "layout_used": "blur", "facecam": WEBCAM}), b"")

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
