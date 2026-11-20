"""The facecam is where most clips found it, and each streamer's webcam place is remembered: a clip whose own look
was fooled (a game character's face in a cutscene) or found nothing uses the remembered place, and clips of a video
that disagree with the rest are made again with it.

Runs against the code directly, with its own empty data folder; facecam detection and rendering are replaced."""
import os, sys, tempfile
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-cam-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import auth, ctx, db, jobs  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


WEBCAM = [1440, 0, 480, 360]            # top right, where this streamer's webcam always is
WEBCAM2 = [1446, 4, 470, 352]           # the same place, measured a little differently
CHARACTER = [600, 300, 500, 400]        # a game character's face in a cutscene
answers = []
jobs._camera = lambda job, clip: answers.pop(0)
jobs._src_size = lambda job, clip: (1920, 1080)
made = []
jobs.render_one = lambda job, clip, words: made.append((clip["id"], list(clip.get("facecam") or [])))
user = auth.local_user()


def clip(i, layout="split"):
    return {"id": f"clip{i:02d}", "layout": layout, "status": "done", "start": i * 60, "end": i * 60 + 30}


with ctx.as_user(user.id):
    job = {"id": "j1", "uploader": "Sharkshe S", "creator": None, "clips": [clip(i) for i in range(1, 7)]}
    answers[:] = [WEBCAM, CHARACTER, WEBCAM2, None, WEBCAM, "full"]
    for c in job["clips"]:
        jobs._use_camera(job, c)
    got = {c["id"]: (c.get("camera"), c.get("facecam"), c.get("camera_from")) for c in job["clips"]}
    check("the first clip uses what it found", got["clip01"][1], WEBCAM)
    check("once two clips agree, the place is remembered", jobs._remembered(job) is not None)
    check("a clip that found nothing uses the remembered place", got["clip04"][:2], ("box", jobs._px(jobs._remembered(job), 1920, 1080)))
    check("a clip that agrees keeps its own measure", got["clip05"][1], WEBCAM)
    check("a camera filling the picture (just chatting) stays so", got["clip06"][0], "full")
    check("the clip fooled before anything was remembered still has the character, until the video is done", got["clip02"][1], CHARACTER)

    fixed = jobs._agree_cameras(job, [])
    check("when the video is done, the clip that disagreed is made again", (fixed, [m[0] for m in made]), (1, ["clip02"]))
    check("...with the webcam most clips found", jobs._iou(made[0][1], WEBCAM) >= 0.8)
    check("...and the full-camera clip is left alone", any(m[0] == "clip06" for m in made), False)

    # the next video of the same channel: a cutscene clip first, and the remembered place wins
    job2 = {"id": "j2", "uploader": "sharkshe  s", "creator": None, "clips": [clip(1)]}
    answers[:] = [CHARACTER]
    jobs._use_camera(job2, job2["clips"][0])
    c = job2["clips"][0]
    check("next video, same channel: a fooled first clip uses the remembered webcam", (jobs._iou(c["facecam"], WEBCAM) >= 0.8, c.get("camera_from")),
          (True, "remembered"))

    # another channel knows nothing of it
    job3 = {"id": "j3", "uploader": "Someone Else", "creator": None, "clips": [clip(1)]}
    answers[:] = [CHARACTER]
    jobs._use_camera(job3, job3["clips"][0])
    check("another channel doesn't get this streamer's webcam", job3["clips"][0]["facecam"], CHARACTER)

    # the streamer moves their webcam: two clips agreeing on the new place replace the old one
    MOVED = [0, 720, 480, 360]
    job4 = {"id": "j4", "uploader": "Sharkshe S", "creator": None, "clips": [clip(1), clip(2), clip(3)]}
    answers[:] = [MOVED, MOVED, MOVED]
    for c in job4["clips"]:
        jobs._use_camera(job4, c)
    check("a webcam that moved is learnt again from two clips", jobs._iou(jobs._px(jobs._remembered(job4), 1920, 1080), MOVED) >= 0.8)
    check("...and used from then on", jobs._iou(job4["clips"][2]["facecam"], MOVED) >= 0.8)

    # a layout without a facecam isn't touched
    c = clip(9, layout="blur")
    jobs._use_camera(job, c)
    check("layouts without a facecam aren't looked at", "camera" in c, False)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
