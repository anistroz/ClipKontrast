"""Making clips faster: several clips at once on any computer, and a long video in Hindi listened to by the quick
model (its clips' captions still written by the full one). Each step's time is kept and sent with a bug report.

Runs the whole pipeline on a real 21-minute video file, with Whisper and the AI replaced; nothing outside this
machine is contacted."""
import os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-speed-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import auth, brain, ctx, db, diagnose, jobs, transcribe, whisper  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- several clips at once
real_cpu, real_ram = os.cpu_count, transcribe.RAM_GB
for cpus, ram, want in ((4, 16, 2), (8, 16, 3), (12, 32, 4), (32, 64, 6), (8, 6, 2)):
    os.cpu_count = lambda c=cpus: c
    transcribe.RAM_GB = ram
    check(f"{cpus} CPUs and {ram} GB: {want} clips made at once", jobs.render_workers(), want)
os.cpu_count, transcribe.RAM_GB = real_cpu, real_ram

# ---- the quick model: fake Whisper models, to see which one does what
calls = []


class Seg:
    def __init__(self, s, e, text):
        self.start, self.end, self.text = s, e, text
        self.words = [type("W", (), {"word": w, "start": s + i * 0.3, "end": s + i * 0.3 + 0.25})() for i, w in enumerate(text.split())]


class FakeModel:
    def __init__(self, name):
        self.name = name

    def transcribe(self, audio, **kw):
        calls.append((self.name, kw.get("word_timestamps")))
        return iter([Seg(0.0, 3.0, "यह तो कमाल है"), Seg(3.0, 5.0, "चलो भाई")]), None


whisper.ready = lambda note=None: True
broken = {"quick": False}


def fake_get(note=None, name=None):
    name = name or whisper.MODEL
    if name == whisper.SCAN_MODEL and broken["quick"]:
        raise OSError("couldn't download")
    return FakeModel(name)


whisper._get = fake_get
import numpy as np  # noqa: E402
a = np.zeros(16000 * 5, np.int16)
w = whisper.transcribe(a, "hi", quick=True)
check("finding the moments uses the quick model, without word-by-word timing", calls[-1], (whisper.SCAN_MODEL, False))
check("...its words are spread over each line, in order", [x["w"] for x in w] == "यह तो कमाल है चलो भाई".split() and all(w[i]["s"] < w[i + 1]["s"] for i in range(len(w) - 1)))
whisper.transcribe(a, "hi")
check("captions use the full model, word by word", calls[-1], (whisper.MODEL, True))
broken["quick"] = True
whisper.transcribe(a, "hi", quick=True)
check("the quick model can't be downloaded: the full one finds the moments instead", calls[-1][0], whisper.MODEL)
broken["quick"] = False

# ---- the whole pipeline, a 21-minute video in Hindi
work = Path(tempfile.mkdtemp(prefix="pc-speed-work-"))
src = work / "long.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x334455:size=320x180:rate=15", "-f", "lavfi",
                "-i", "sine=f=300:sample_rate=16000", "-filter_complex",
                "[1:a]volume='if(between(mod(t,300),100,110),1.0,0.05)':eval=frame[a]", "-map", "0:v", "-map", "[a]",
                "-t", "1260", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "32k", str(src)], check=True)
transcribe.model_ready = lambda: True
jobs._pick_language = lambda job, o, yt, audio, resuming=False: (job.__setitem__("lang", "hi"), ("hi", yt))[1]
heard = []


def fake_whisper(audio, lang=None, on_progress=None, note=None, quick=False):
    heard.append((quick, round(len(audio) / 16000)))
    n = len(audio) // 16000
    if on_progress:
        on_progress(1.0)
    word = "रफ" if quick else "सही"
    return [{"w": word, "s": float(i), "e": i + 0.6} for i in range(0, n, 1)]


whisper.transcribe = fake_whisper


def pick(prompt, purpose=""):
    return [{"start": 400, "end": 430, "score": 80, "hook": "Kya baat", "title": "t", "description": "", "hashtags": [],
             "highlight_words": [], "reason": "r", "category": "funny"}], "test-model", 10


brain.ask_ai = pick
brain.english_captions = lambda raw, *a, **k: raw
seen_caps = []
real_render = jobs.render.render_clip


def spy_render(src_, out_dir, name, clip, words, w_, h_):
    seen_caps.append([x["w"] for x in words])
    return real_render(src_, out_dir, name, clip, words, w_, h_)


jobs.render.render_clip = spy_render
user = auth.local_user()
with ctx.as_user(user.id):
    job = jobs.create({"type": "file", "path": str(src), "name": "Hindi stream"},
                      {"max_clips": 2, "min_len": 15, "max_len": 60, "layout": "blur", "zoom": False, "caption_lang": "deva"}, enqueue=False)
    jobs._run_job(job)
quick_secs = sum(s for q, s in heard if q)
check("the video is done, with its clip made", (job["status"], [c["status"] for c in job["clips"]]), ("done", ["done"]))
check("the long video was listened to by the quick model", quick_secs > 0 and all(q for q, s in heard[:-1]))
check("...only its lively parts, well under half of it", quick_secs < 0.5 * 1260)
check("the clip's captions were written again by the full model", heard[-1][0], False)
check("...and those are the words on the clip", bool(seen_caps) and set(seen_caps[0]) == {"सही"})
t = job.get("timings") or {}
check("each step's time is kept with the video", set(t) >= {"audio", "transcript", "picking", "clips"} and all(isinstance(v, int) for v in t.values()))
d = diagnose.details()
check("...and a bug report shows them, with how many clips are made at once", "Recent videos:" in d and "transcript" in d and "Clips made at once" in d)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
