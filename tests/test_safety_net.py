"""A video someone asked clips of never comes back with none: when the AI finds nothing that stands out (or too
little is heard to ask it), the liveliest parts are clipped. And a long video in Hindi listens to less of it.

Runs the whole pipeline on a real video file, with the speech model and the AI replaced; nothing outside this
machine is contacted."""
import os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-net-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0", CLIPKONTRAST_SKIP_STATIC="0")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import auth, brain, ctx, db, jobs, transcribe  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


work = Path(tempfile.mkdtemp(prefix="pc-net-work-"))
src = work / "stream.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-filter_complex", "[1:a]volume='if(between(t,40,48),1.0,0.05)':eval=frame[a]",
                "-map", "0:v", "-map", "[a]", "-t", "120", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)

transcribe.model_ready = lambda: True
jobs._pick_language = lambda job, o, yt, audio, resuming=False: (job.__setitem__("lang", "en"), ("en", yt))[1]
asked = []


def no_clips(prompt, purpose=""):
    asked.append(purpose)
    return [], "test-model", 10            # the AI answers, and finds nothing


brain.ask_ai = no_clips
brain.config.ai_ready = lambda: True          # the AI is set up (and answers through the fake above)
user = auth.local_user()


def run(words, label):
    transcribe.transcribe = lambda audio, on_progress=None: [dict(w) for w in words]
    with ctx.as_user(user.id):
        job = jobs.create({"type": "file", "path": str(src), "name": label}, {"max_clips": 6, "min_len": 15, "max_len": 60,
                                                                            "layout": "blur", "zoom": False}, enqueue=False)
        jobs._run_job(job)
    return job


talk = [{"w": w, "s": round(i * 0.45, 2), "e": round(i * 0.45 + 0.4, 2)}
        for i, w in enumerate(("so this is what happened today and then he said that. " * 30).split())]
job = run(talk, "the AI finds nothing")
check("the AI was asked", len(asked) >= 1)
check("the AI found nothing, and the video still has clips", (job["status"], len(job["clips"]) >= 1), ("done", True))
check("...made for real", all(c["status"] == "done" and (Path(job["dir"]) / "clips" / c["file"]).is_file() for c in job["clips"]))
check("...from the liveliest part (the loud stretch at 40-48 s)", any(c["start"] <= 44 <= c["end"] for c in job["clips"]))
check("...and it says why", job["ai"]["note"], "Nothing stood out to the AI, so the liveliest parts were clipped.")
check("not a single 'nothing found'", "nothing clip-worthy" in job["stage"], False)
check("a 2-minute video gets at most 2 such clips", len(job["clips"]) <= 2)

job = run([], "nothing heard at all")
check("nothing heard at all (music, a game with no talking): still clipped", (job["status"], len(job["clips"]) >= 1), ("done", True))

# ---- a long video in Hindi listens to less of it
d = np.random.RandomState(3).normal(-30, 3, 3600).astype(np.float32)
en = jobs._hot_regions(d, 6)
hi = jobs._hot_regions(d, 6, jobs.WHISPER_REGION, 2)
check("Whisper (Hindi) listens to clearly less of a long video", sum(b - a for a, b in hi) < 0.8 * sum(b - a for a, b in en))
check("...still from across the whole video", hi[-1][1] > 0.75 * len(d) and hi[0][0] < 0.25 * len(d))
check("seconds shown as minutes", (jobs._mmss(130.7), jobs._mmss(5)), ("2:10", "0:05"))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
