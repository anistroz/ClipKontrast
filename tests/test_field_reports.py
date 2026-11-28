"""Fixes for what clippers reported from the app (the bug reports of 20-21 November):

- "'str' object has no attribute 'get'": the stream's chat replay can never stop a video, whatever shape its lines
  come in; and a failed video's report now says where it failed (file:line, no paths).
- WinError 32 / 5 (a file held by an antivirus): job.json and working files are tried again, not failed on; and
  WinError 4551 (Windows Smart App Control) says what to do.
- YouTube's bot check: one of YouTube's apps refused isn't YouTube refusing; the others are asked first.
- Gemini: a model the service doesn't know is swapped for the closest one it offers at Save and test; a model that
  won't answer in JSON mode is asked plainly; a working test clears "the AI isn't working".
- A campaign's tag is found however it was written; a copy from the zip can tell when a newer one is out.

Everything outside this machine is replaced."""
import json, os, sys, tempfile, time
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-field-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="1",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from unittest.mock import patch  # noqa: E402
from studio import ai, auth, brain, config, ctx, db, earn, jobs, media, safe, updates  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- the chat replay can't stop a video
odd = ['"just text"', "123", "[1, 2]", '{"replayChatItemAction": "x"}',
       json.dumps({"replayChatItemAction": {"actions": ["str", {"addChatItemAction": "s"},
                                                        {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {"message": "plain", "authorName": "bob"}}}}],
                                            "videoOffsetTimeMsec": "5000"}}),
       json.dumps({"replayChatItemAction": {"actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
           "message": {"runs": ["oops", {"emoji": "x"}, {"text": "lol"}]}, "authorName": {"simpleText": "amy"}}}}}], "videoOffsetTimeMsec": "7000"}})]
check("odd chat lines are skipped or read, never a crash", [media._chat_line(x) for x in odd],
      [None, None, None, None, (5.0, "bob", "plain"), (7.0, "amy", "lol")])


class BrokenChat:
    def __init__(self, *a, **k):
        pass

    def messages(self, wait=0.0):
        raise AttributeError("'str' object has no attribute 'get'")

    def stop(self):
        pass


import shutil, subprocess  # noqa: E402
from studio import transcribe  # noqa: E402
work = Path(tempfile.mkdtemp(prefix="pc-field-work-"))
src = work / "s.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:size=320x180:rate=10", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=16000", "-t", "120", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
URL = "https://www.youtube.com/watch?v=abcdefghijk"
media.info = lambda url: {"title": "GTA 6 LIVE", "uploader": "u", "duration": 120.0, "is_live": False, "thumbnail": "", "kind": "video",
                          "channel_url": "", "live_status": "was_live", "handle": "u", "platform": "youtube"}
media.save_thumb = lambda *a, **k: False
media.youtube_words = lambda url: ([{"w": "bro", "s": float(t), "e": t + 0.4} for t in range(0, 120, 2)], "en")
media.download_audio = lambda url, d, on_progress=None: (shutil.copyfile(src, Path(d) / "audio_src.mp4"), Path(d) / "audio_src.mp4")[1]
media.download = lambda url, d, height=720: (shutil.copyfile(src, Path(d) / "source.mp4"), Path(d) / "source.mp4")[1]
real_chat = media.ChatReplay
media.ChatReplay = BrokenChat
transcribe.model_ready = lambda: True
brain.config.ai_ready = lambda: False
user = auth.local_user()
with ctx.as_user(user.id):
    job = jobs.create({"type": "url", "url": URL, "name": URL}, {"max_clips": 1, "layout": "blur", "zoom": False}, enqueue=False)
    jobs._run_job(job)
check("a chat replay that breaks: the video is still made, and it says the chat wasn't used",
      (job["status"], len(job["clips"]) >= 1, any("chat replay couldn't be read" in x for x in job["ai"].get("log", []))), ("done", True, True))
media.ChatReplay = real_chat

# ---- a failed video says where it failed, in the bug report
from studio import diagnose  # noqa: E402
with ctx.as_user(user.id):
    j2 = jobs.create({"type": "file", "path": str(src), "name": "x"}, {}, enqueue=False)
real_run = jobs._run_job
jobs._run_job = lambda job: {}.get("a").get("b")         # fails the way the report did


class OneJob:
    def __init__(self):
        self.n = 0

    def get(self, *a, **k):
        self.n += 1
        if self.n > 1:
            raise SystemExit
        return ("job", j2["id"], None)

    def done(self):
        pass


try:
    with patch.object(jobs, "_q", OneJob()):
        jobs._worker()
except SystemExit:
    pass
jobs._run_job = real_run
check("a failed video's report says where it failed (file:line, no folders)",
      (bool(j2.get("error_where")), "test_field_reports.py" in j2.get("error_where", ""), "/" not in j2.get("error_where", "")), (True, True, True))
check("...and the bug report carries it", "(at " in diagnose.details())

# ---- Stop: a video being made stops at its next step; one waiting its turn never starts (report #96)
import threading as _th  # noqa: E402
real_audio = media.download_audio


def slow_audio(url, d, on_progress=None):
    for i in range(400):                   # a long download, saying how far it got
        time.sleep(0.05)
        on_progress and on_progress(i / 400)
    return real_audio(url, d, on_progress)


media.download_audio = slow_audio
with ctx.as_user(user.id):
    j3 = jobs.create({"type": "url", "url": URL, "name": URL}, {"max_clips": 1, "layout": "blur", "zoom": False}, enqueue=False)


class Queue1(OneJob):
    def get(self, *a, **k):
        self.n += 1
        if self.n > 1:
            raise SystemExit
        return ("job", self._jid, None)


q = Queue1(); q._jid = j3["id"]
j3["status"] = "queued"


def run_worker():
    try:
        with patch.object(jobs, "_q", q):
            jobs._worker()
    except SystemExit:
        pass


t = _th.Thread(target=run_worker); t.start()
for _ in range(100):
    if j3.get("status") == "running":
        break
    time.sleep(0.05)
time.sleep(0.3)
with ctx.as_user(user.id):
    jobs.stop(j3["id"])
t.join(20)
check("Stop while downloading: the video stops at its next step, said as stopped, not as an error to report",
      (t.is_alive(), j3["status"], j3["stage"], "error_where" in j3), (False, "error", "Stopped by you", False))

# ---- Stop while in the middle of something that never says how far it got (report #215, #193): stopped anyway
def stuck_audio(url, d, on_progress=None):
    time.sleep(6)                          # a long step that only looks at Stop when it's done
    return real_audio(url, d, on_progress)


media.download_audio = stuck_audio
with ctx.as_user(user.id):
    j5 = jobs.create({"type": "url", "url": URL, "name": URL}, {"max_clips": 1, "layout": "blur", "zoom": False}, enqueue=False)


class Counting(Queue1):
    done_calls = 0

    def done(self):
        Counting.done_calls += 1


q5 = Counting(); q5._jid = j5["id"]
j5["status"] = "queued"
grace, jobs.STOP_GRACE = jobs.STOP_GRACE, 1
real_worker = jobs._worker
p5 = patch.object(jobs, "_q", q5); p5.start()
def run5():
    try:
        real_worker()
    except SystemExit:
        pass
t = _th.Thread(target=run5, daemon=True); t.start()
for _ in range(400):
    if j5.get("status") == "running":
        break
    time.sleep(0.05)
with ctx.as_user(user.id):
    jobs.stop(j5["id"])
time.sleep(2.0)
check("Stop during a long step: after a few seconds it's stopped anyway, not 'Stopping…' for minutes",
      (j5["status"], j5["stage"], t.is_alive()), ("error", "Stopped by you", True))
check("...its place in the line is given to the next video at once", Counting.done_calls, 1)
t.join(15)
check("...and when the old step finally ends, nothing changes and its place isn't given back twice",
      (t.is_alive(), j5["status"], j5["stage"], Counting.done_calls, j5["id"] in jobs._freed), (False, "error", "Stopped by you", 1, False))
p5.stop()
jobs.STOP_GRACE = grace
media.download_audio = real_audio
with ctx.as_user(user.id):
    j4 = jobs.create({"type": "url", "url": URL, "name": URL}, {"max_clips": 1}, enqueue=False)
j4["status"] = "queued"
with ctx.as_user(user.id):
    jobs.stop(j4["id"])
q2 = Queue1(); q2._jid = j4["id"]
with patch.object(jobs, "_q", q2), patch.object(jobs, "_run_job", side_effect=AssertionError("must not start")):
    try:
        jobs._worker()
    except SystemExit:
        pass
check("Stop while waiting its turn: stopped at once, and never started", (j4["status"], j4["stage"]), ("error", "Stopped by you"))
try:
    with ctx.as_user(user.id):
        jobs.stop(j4["id"])
    check("a video that isn't being made can't be stopped", False)
except ValueError:
    check("a video that isn't being made can't be stopped", True)
page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the page has a Stop button on a video being made", 'data-act="stopjob"' in page and "/stop`, {method: \"POST\"}" in page)

# ---- a file held by an antivirus
calls = {"n": 0}
real_replace = Path.replace


def held(self, target):
    calls["n"] += 1
    if calls["n"] <= 2:
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")
    return real_replace(self, target)


with patch.object(Path, "replace", held):
    j2["stage"] = "saved through a held file"
    jobs.save(j2)
check("job.json held a moment by an antivirus: tried again, saved, no crash",
      json.loads((Path(j2["dir"]) / "job.json").read_text())["stage"], "saved through a held file")
f = work / "held.wav"
f.write_text("x")
n = {"k": 0}
real_unlink = Path.unlink


def held_unlink(self, missing_ok=False):
    n["k"] += 1
    if n["k"] <= 1:
        raise PermissionError(32, "in use")
    return real_unlink(self, missing_ok=missing_ok)


with patch.object(Path, "unlink", held_unlink):
    check("a working file held a moment: deleted on the next try", (media.remove(f), f.exists()), (True, False))
check("WinError 4551 (Smart App Control) says what to do",
      "Smart App Control" in safe.friendly(RuntimeError("[WinError 4551] An Application Control policy has blocked this file")))
check("WinError 32 / 5 say an antivirus held a file, and to exclude ClipKontrast's folders",
      all("antivirus" in safe.friendly(RuntimeError(e)) for e in ("[WinError 32] The process cannot access the file", "[WinError 5] Access is denied: 'x'")))

# ---- YouTube's bot check: the other apps are asked first
media._yt_refused_until = 0.0
asked = []


def fetch(client, log):
    asked.append(client)
    with media._youtube_guard(URL):
        if client is None:
            raise RuntimeError("Sign in to confirm you're not a bot")
        (work / "dl.mp4").write_bytes(b"x" * 4096)


got = media._each_client(URL, work, "dl", fetch)
check("one of YouTube's apps asked to prove it isn't a bot: the next one is asked, and it works",
      (asked[:2], got.name, media.youtube_paused()), ([None, ["android_vr"]], "dl.mp4", False))
asked.clear()


def all_refused(client, log):
    asked.append(client)
    with media._youtube_guard(URL):
        raise RuntimeError("Sign in to confirm you're not a bot")


try:
    media._each_client("https://www.youtube.com/watch?v=zzzzzzzzzzz", work, "dl2", all_refused)
    check("every app refused: YouTube is taken as refusing (and paused a while)", False)
except media.YouTubeBlocked:
    check("every app refused: YouTube is taken as refusing (and paused a while)", (len(asked), media.youtube_paused()), (len(media.YT_CLIENTS), True))
media._yt_refused_until = 0.0

# ---- Gemini settings
ai.save("gemini", ["gemini-2.5-flash"], "", "test-key-123")
tried = []


def fake_call(model, prompt, schema, timeout=None):
    tried.append(model)
    if model == "gemini-2.5-flash":
        raise ai.AIError('HTTP 404 {"error": {"code": 404, "message": "models/gemini-2.5-flash is not found"}}')
    return ["ok"], 5, 1


with patch.object(ai, "call", fake_call), patch.object(ai, "list_models", return_value=[
        "gemini-3-flash", "gemini-3-pro", "gemini-2.0-flash-lite", "text-embedding-004", "imagen-4", "gemini-3-flash-preview-tts"]):
    ai.problem.update(text="Gemini doesn't know the model", at=time.time())
    r = ai.test()
check("a model the service doesn't offer: swapped at Save and test for the closest one it does, and saved",
      (r["switched_from"], r["model"], ai.models()[0]), ("gemini-2.5-flash", "gemini-3-flash", "gemini-3-flash"))
check("...and the dashboard stops saying the AI isn't working", ai.problem["text"], "")


# Google stops giving a model to new keys but still lists it (report #102/#103): the next ones are tried
ai.save("gemini", ["gemini-2.5-flash"], "", "test-key-123")
tried = []
RETIRED = 'HTTP 404 {"error": {"code": 404, "message": "This model models/gemini-2.5-flash is no longer available to new users."}}'


def retired_call(model, prompt, schema, timeout=None):
    tried.append(model)
    if model in ("gemini-2.5-flash", "gemini-flash-latest"):
        raise ai.AIError(RETIRED.replace("gemini-2.5-flash", model))
    return ["ok"], 5, 1


listed = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-flash-latest", "gemini-3-flash-preview", "gemini-2.0-flash", "gemma-3-27b-it",
          "gemini-embedding-001", "gemini-2.5-flash-image"]
with patch.object(ai, "call", retired_call), patch.object(ai, "list_models", return_value=listed):
    r = ai.test()
check("a model still listed but not given to new keys: never picked again; the next that answers is saved",
      (r["switched_from"], r["model"], ai.models()[0], "gemini-2.5-flash" not in tried[1:]), ("gemini-2.5-flash", tried[-1], tried[-1], True))
check("...the latest-flash name is tried first, then the newest fast ones (never images, embeddings, Gemma)",
      (tried[1], all(not any(w in m for w in ("embedding", "image", "gemma")) for m in tried)), ("gemini-flash-latest", True))
check("a new Gemini setup starts on Google's current fast model", ai.PROVIDERS["gemini"][4], "gemini-flash-latest")

# ...and while clipping, the same happens by itself, so videos keep their AI
ai.save("gemini", ["gemini-2.5-flash"], "", "test-key-123")
brain._swapped["at"] = 0.0
brain._down.update(until=0.0, why=None)
tried.clear()
with patch.object(ai, "call", retired_call), patch.object(ai, "list_models", return_value=listed), \
        patch.object(brain.config, "ai_ready", return_value=True):
    out, used, _t = brain.ask_ai("pick clips", purpose="test")
check("while clipping: a retired model is swapped, the answer comes from the new one, and it's kept",
      (out, used, ai.models()[0]), (["ok"], tried[-1], tried[-1]))
with patch.object(ai, "call", lambda *a, **k: (_ for _ in ()).throw(ai.AIError("HTTP 401 API key not valid"))), \
        patch.object(ai, "list_models", return_value=listed):
    try:
        ai.test(); check("a wrong key is said as a wrong key, not hidden by trying other models", False)
    except Exception as e:
        check("a wrong key is said as a wrong key, not hidden by trying other models", "refused the key" in ai.explain(e))


class R:
    def __init__(self, code, data=None, text=""):
        self.status_code, self._d, self.text = code, data, text

    def json(self):
        return self._d


posts = []


def fake_post(url, json=None, headers=None, timeout=None):
    posts.append(json)
    if "responseMimeType" in (json.get("generationConfig") or {}):
        return R(400, text='{"error": {"code": 400, "message": "JSON mode is not enabled for models/gemma-3"}}')
    return R(200, {"candidates": [{"content": {"parts": [{"text": 'Sure! ```json\n{"items": ["ok"]}\n```'}]}}], "usageMetadata": {}})


with patch.object(ai.httpx, "post", fake_post):
    out, _s, _w = ai._gemini("gemma-3", "hi", {"type": "ARRAY", "items": {"type": "STRING"}})
check("a model that won't answer in JSON mode: asked again plainly, and its JSON found", (out, len(posts)), (["ok"], 2))

# ---- campaigns and updates
check("a campaign tag is found however it's written",
      (earn.tag_in("GTA 6 Launch × Mizo Plays", "my clip #gta6launchxmizoplays"), earn.tag_in("#GTA6Launch", "GTA 6 launch!"),
       earn.tag_in("#MizoPlays", "nothing here")), (True, True, False))
updates.RUNNING = ""
config.APP_VERSION = "2026.11.21.6"
man = {"version": "2026.11.22.2", "notes": ["Exact moment pictures"]}
with patch.object(updates.httpx, "get", return_value=type("R", (), {"status_code": 200, "content": json.dumps(man).encode()})()):
    up = updates.check(force=True)
check("a copy from the zip knows when a newer one is out, and offers the download", (up["zip"], up["latest"], up["url"]), (True, "2026.11.22.2", config.DOWNLOAD_URL))
page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("...the page says how: download, unzip over the folder, the data folder stays", "up.zip" in page and "isn't in the zip, so it stays" in page)
wf = (config.ROOT / ".github" / "workflows" / "windows-app.yml").read_text(encoding="utf-8")
check("...and the zip carries its version", "--add-file=VERSION" in wf)

# ---- the webcam isn't blurry: a layout that shows it fetches the video at 1080p
check("webcam layouts fetch 1080p, the others keep the quality chosen",
      (jobs._src_height({"quality": 720, "layout": "split"}), jobs._src_height({"quality": 720, "layout": "gameplay"}),
       jobs._src_height({"quality": 720, "layout": "blur"}), jobs._src_height({"quality": 720, "layout": "blur"}, "split"),
       jobs._src_height({"quality": 1080, "layout": "crop"})), (1080, 1080, 720, 1080, 1080))
check("Fill the screen and Zoomed in fetch 1080p too: from 720p their middle was blown up and blurry (report #216)",
      (jobs._src_height({"quality": 720, "layout": "crop"}), jobs._src_height({"quality": 720, "layout": "zoom"})), (1080, 1080))
src_jobs = (config.ROOT / "studio" / "jobs.py").read_text(encoding="utf-8")
check("...everywhere a video or a piece of it is fetched", 'int(o["quality"])' not in src_jobs and 'options"]["quality"]' not in src_jobs)

# ---- a connection that kept dropping says so in plain words (not YouTube's notes about tokens)
check("download timeouts and dropped connections: a plain message, what to do",
      all(safe.friendly(RuntimeError(t)).startswith(safe.NET_DROP) and "Details: " in safe.friendly(RuntimeError(t)) for t in (
          "[download] Got error: The read operation timed out (tried 5 ways) ([youtube] x: mweb client https formats require a GVS PO Token)",
          "[download] Got error: Remote end closed connection without response (tried 5 ways) (SABR)")))
check("...but a bot check with a timeout note behind it is still the bot check",
      not safe.friendly(RuntimeError("Sign in to confirm you are not a bot (tried 2 ways) (timed out)")).startswith(safe.NET_DROP))
check("a link that won't open says why, in plain words (the site's reason, not 'check it's public')",
      [safe.link_reason(RuntimeError(t))[:36] for t in (
          "ERROR: [youtube] abc: Private video. Sign in if you've been granted access to this video",
          "ERROR: [youtube] abc: Join this channel to get access to members-only content like this video",
          "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate for some users.",
          "ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader",
          "ERROR: Unsupported URL: https://www.youtube.com/feed/history",
          "ERROR: [kick] 1234: Something odd happened C:\\Users\\bob\\file.txt")],
      ["This video is private, so it can't b", "This video is for the channel's memb", "YouTube only shows this video to sig", "YouTube says this video is unavailab", "That isn't a link to a single video.", "Couldn't open that video: Something "])
check("...and never shows a folder of this computer", "bob" not in safe.link_reason(RuntimeError("ERROR: [kick] 1234: Something odd happened C:\\Users\\bob\\file.txt")))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
