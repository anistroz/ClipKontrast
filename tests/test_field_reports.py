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

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
