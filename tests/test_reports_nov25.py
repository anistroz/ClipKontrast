"""Fixes from the bug reports of 22-25 November (version 2026.11.22.5):

- YouTube "The page needs to be reloaded": one of YouTube's apps failing to describe a video isn't the video failing.
- Gemini 503 "This model is currently experiencing high demand": tried again, then another model (the busy one kept
  as the backup), said in plain words.
- "This clip took too long and was stopped": a slow clip no longer makes the clips waiting behind it fail; ffmpeg is
  stopped when it stops making progress, not after a fixed time.
- Clips that say "being made" when nothing is making them can be deleted; a video can be deleted while it stops.
- A long stream's audio download moves the bar even when its size isn't known (it looked stuck at 3%).
- The speech model download survives an old folder Windows won't let go (WinError 183).
- An ffmpeg that can't draw captions (Homebrew's plain one) still makes the clip, and says how to get captions.
- A full drive and Ollama not running are said plainly.

Everything outside this machine is replaced."""
import contextlib, os, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-nov25-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from unittest.mock import patch  # noqa: E402
from studio import account, ai, auth, brain, config, ctx, db, fetch_model, jobs, media, render, safe, tools  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- YouTube: "The page needs to be reloaded" from one of its apps -> the next one is asked
asked = []


class FakeYdl:
    def __init__(self, opts):
        self.client = ((opts.get("extractor_args") or {}).get("youtube") or {}).get("player_client")

    def extract_info(self, url, download=False):
        asked.append(self.client)
        if self.client is None:
            raise RuntimeError("ERROR: [youtube] PHSsdHu2Er0: The page needs to be reloaded.")
        return {"title": "I RACED USAIN BOLT!", "uploader": "x", "duration": 600, "_type": "video"}


@contextlib.contextmanager
def fake_ydl(opts):
    yield FakeYdl(opts)


media._yt_refused_until = 0.0
with patch.object(media, "_ydl", fake_ydl):
    i = media.info("https://www.youtube.com/watch?v=PHSsdHu2Er0")
check("'The page needs to be reloaded' from one of YouTube's apps: the next is asked, and the video opens",
      (i["title"], asked[:2]), ("I RACED USAIN BOLT!", [None, ["android_vr"]]))
asked.clear()


class PrivateYdl(FakeYdl):
    def extract_info(self, url, download=False):
        asked.append(self.client)
        raise RuntimeError("ERROR: [youtube] abc: Private video. Sign in if you've been granted access")


with patch.object(media, "_ydl", lambda opts: contextlib.nullcontext(PrivateYdl(opts))):
    try:
        media.info("https://www.youtube.com/watch?v=abcdefghijk"); check("a private video is said at once", False)
    except RuntimeError as e:
        check("...but a private video is said at once, without asking every app", (len(asked), "Private video" in str(e)), (1, True))
check("a current yt-dlp version: the one with YouTube's November fixes", __import__("yt_dlp").version.__version__ >= "2026.11.23")
req = (config.ROOT / "requirements.txt").read_text()
check("...and the app ships it", "yt-dlp==2026.11.23" in req)

# ---- Gemini 503 "high demand"
BUSY = ('HTTP 503 { "error": { "code": 503, "message": "This model is currently experiencing high demand. Spikes in demand '
        'are usually temporary. Please try again later.", "status": "UNAVAILABLE" } }')
ai.save("gemini", ["gemini-flash-latest"], "", "test-key-123")
tried = []


def busy_call(model, prompt, schema, timeout=None):
    tried.append(model)
    if model == "gemini-flash-latest":
        raise ai.AIError(BUSY)
    return ["ok"], 5, 1


listed = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3-flash", "gemini-3-pro"]
with patch.object(ai, "call", busy_call), patch.object(ai, "list_models", return_value=listed), patch("time.sleep"):
    r = ai.test()
check("a busy Gemini model at Save and test: tried again, then another model answers, and it's used",
      (tried[:2], r["model"], ai.models()[:2]), (["gemini-flash-latest", "gemini-flash-latest"], "gemini-flash-lite-latest",
                                                 ["gemini-flash-lite-latest", "gemini-flash-latest"]))
check("...the busy one is kept as the backup, so it's used again once it's free", "gemini-flash-latest" in ai.models())
check("a busy model is said in plain words: the key is fine", "very busy right now" in ai.explain(ai.AIError(BUSY)) and "key is fine" in ai.explain(ai.AIError(BUSY)))
ai.save("gemini", ["gemini-flash-latest"], "", "test-key-123")
brain._swapped["at"] = 0.0
brain._down.update(until=0.0, why=None)
tried.clear()
with patch.object(ai, "call", busy_call), patch.object(ai, "list_models", return_value=listed), patch("time.sleep"), \
        patch.object(brain.config, "ai_ready", return_value=True):
    out, used, _t = brain.ask_ai("pick", purpose="test")
check("while clipping: a busy model -> another one answers, the clips still get the AI", (out, used), (["ok"], "gemini-flash-lite-latest"))

# ---- clips: a slow one doesn't fail the ones waiting behind it
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
user = auth.local_user()
with ctx.as_user(user.id):
    job = jobs.create({"type": "file", "path": "/nope.mp4", "name": "x"}, {}, enqueue=False)
job["clips"] = [{"id": f"c{i}", "status": "queued"} for i in range(3)]
began = {}
pool = ThreadPoolExecutor(1)


def make(c, secs):
    began[c["id"]] = time.time()
    time.sleep(secs)
    c["status"] = "done"


futs = [(pool.submit(make, job["clips"][0], 2.5), job["clips"][0]), (pool.submit(make, job["clips"][1], 0.1), job["clips"][1]),
        (pool.submit(make, job["clips"][2], 0.1), job["clips"][2])]
with patch.object(jobs, "CLIP_MINUTES", 1.5 / 60), patch.object(jobs.creators, "log", lambda *a: None):
    jobs._wait_for_clips(job, futs, began, 1)
check("one slow clip (given up on) that then finishes: the clips waiting behind it are made, not failed",
      [c["status"] for c in job["clips"][1:]], ["done", "done"])
pool.shutdown()
check("render: ffmpeg is stopped when it stops making progress (not after a fixed 10 minutes)",
      render.RENDER_SECONDS >= 3600 and render.RENDER_STALL <= 300)
frozen = Path(tempfile.mkdtemp()) / "frozen.sh"
frozen.write_text("#!/bin/sh\nsleep 20\n"); frozen.chmod(0o755)
t0 = time.time()
try:
    render._encode([str(frozen)], ".", stall=2); check("a frozen encoder is stopped", False)
except subprocess.TimeoutExpired:
    check("a frozen encoder is stopped, soon", time.time() - t0 < 8)

# ---- stuck clips can be deleted, a video can be deleted while it stops
with ctx.as_user(user.id):
    j2 = jobs.create({"type": "file", "path": "/nope.mp4", "name": "x"}, {}, enqueue=False)
    j2.update(status="error")
    j2["clips"] = [{"id": "s1", "status": "rendering"}]
    check("a clip that says 'being made' while nothing makes it (its video failed): it can be deleted",
          account.delete_clip(j2["id"], "s1"), True)
    j2["status"] = "running"
    j2["clips"] = [{"id": "s2", "status": "done"}]
    from studio import server  # noqa: E402
    try:
        server.rerender(j2["id"], "s2", {})
    except server.HTTPException as e:
        check("re-making a finished clip while its video is still being made: says the video is, not the clip",
              "video is still being made" in e.detail)
    j2.update(status="running", stop=True)
    r = server.delete_job(j2["id"])
    check("Delete while a video is stopping: accepted, done once it has stopped", (r.get("later"), j2.get("delete_when_stopped")), (True, True))
    jobs._stopped(j2)
    check("...and it's gone once stopped", jobs.get(j2["id"]), None)

# ---- a long stream's audio: the bar moves when the size isn't known
seen = []
d = Path(tempfile.mkdtemp())


class HookYdl:
    def __init__(self, opts):
        self.opts = opts

    def download(self, urls):
        for k in (1, 5, 9):
            self.opts["progress_hooks"][0]({"status": "downloading", "fragment_index": k, "fragment_count": 10, "downloaded_bytes": k * 3e6})
            time.sleep(1.05)
        (d / "audio_src.m4a").write_bytes(b"x" * 5000)


with patch.object(media, "_ydl", lambda opts: contextlib.nullcontext(HookYdl(opts))):
    media.download_audio("https://kick.com/x/videos/1", d, lambda p, note="": seen.append((round(p, 1) if p is not None else None, note)))
check("no size known (a long stream in pieces): the pieces done move the bar, with MB so far",
      seen, [(0.1, "3 MB"), (0.5, "15 MB"), (0.9, "27 MB")])

# ---- the speech model: an old folder Windows won't let go
base = Path(tempfile.mkdtemp())
dest, got = base / "speech-model", base / "speech-model.unpacking"
dest.mkdir(); (dest / "old.bin").write_text("old")
got.mkdir(); (got / "model.onnx").write_text("new")
real_rmtree, real_rename = shutil.rmtree, Path.rename
with patch("shutil.rmtree", lambda p, ignore_errors=False: None if Path(p) == dest else real_rmtree(p, ignore_errors=ignore_errors)), \
        patch.object(Path, "rename", lambda self, t: (_ for _ in ()).throw(FileExistsError(183, "Cannot create a file when that file already exists")) if self == dest or Path(t) == dest else real_rename(self, t)), \
        patch("time.sleep"):
    fetch_model._put_in_place(got, dest)
check("speech model: an old folder that can't be removed or moved (WinError 183): the new files are put in anyway",
      (dest / "model.onnx").read_text(), "new")

# ---- an ffmpeg that can't draw captions
work = Path(tempfile.mkdtemp())
src = work / "s.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223344:size=1280x720:rate=15", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-t", "6", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
words = [{"w": "bhai", "s": 1.2, "e": 1.6}, {"w": "kya", "s": 1.7, "e": 2.0}]
with patch.dict(tools._captions, {"ok": False}):
    out = render.render_clip(src, work / "c", "nocap", {"start": 1, "end": 5, "layout": "blur"}, words, 1280, 720)
check("an ffmpeg without libass (Homebrew's plain one): the clip is still made", (work / "c" / out["file"]).is_file())
check("...and says how to get captions", "brew install ffmpeg-full" in tools.NO_CAPTIONS or "full build" in tools.NO_CAPTIONS)
check("this computer's ffmpeg is told apart (it can draw them here)", tools.can_draw_captions())

# ---- plain words
check("a full drive is said plainly", "drive is full" in safe.friendly(RuntimeError("ERROR: unable to write data: [Errno 28] No space left on device (tried 5 ways)")))
ai.save("ollama", ["llama3.2"], "http://127.0.0.1:11434", "")
check("Ollama not running: said as that, not as the internet", "Ollama isn't running" in ai.explain(RuntimeError("ConnectError: [Errno 111] Connection refused")))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
