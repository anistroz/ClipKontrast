"""Recording only when the clipper asked for it.

- Live clipping from Home records that one stream (now, or when they next go live), not every stream after it.
- Auto-record (every stream) is only on where it was turned on in Setup; it used to be turned on for good by Live
  clipping, so once, it is turned off where it was on, with a notice saying where to turn it back on.
- Stop sticks: a stopped recording doesn't start again by itself while that stream goes on, however often the app
  checks or is opened again; once they've gone offline, auto-record works as usual.
- Closing the app stops recordings: they don't start again when it's opened. Only ClipKontrast restarting itself to
  update carries them on (and a server, which restarts only for updates and crashes).

Recording itself and the platforms are replaced; nothing outside this machine is contacted."""
import os, sys, tempfile
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-rec-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from studio import auth, config, creators, ctx, db, jobs, live, notices, profiles, selfupdate  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


on_air = {"live": True}
started = []
profiles.live_shared = lambda plat, url: {"live": on_air["live"]}
live.resolve = lambda url: {"urls": [url], "title": "t", "uploader": "u"}
live.active_for = lambda cid: None
live.start_session = lambda c, url: started.append((c["id"], url))
user = auth.local_user()
with ctx.as_user(user.id):
    # ---- Live clipping from Home: that stream only
    c = creators.create({"name": "Mizo", "channel": "https://www.twitch.tv/mizo", "watch_once": True})
    live._watch_user(user.id)
    check("Live clipping: they're live, so their stream is recorded", [x[0] for x in started], [c["id"]])
    c = creators.get(c["id"])
    check("...and only that stream: not watched for the next ones", (c["watch_once"], c["auto_watch"]), (False, False))
    started.clear()
    live._watch_user(user.id)
    check("...the next round records nothing", started, [])

    # ---- Stop sticks, until they've gone offline
    a = creators.create({"name": "Auto", "channel": "https://www.twitch.tv/auto", "auto_watch": True})
    creators.update(a["id"], {"hold": True})                 # what pressing Stop does (server.stop_live)
    live._watch_one(creators.get(a["id"]))
    check("Stop pressed, still live: not recorded again by itself", started, [])
    on_air["live"] = False
    live._watch_one(creators.get(a["id"]))
    check("...they've gone offline: the hold goes", creators.get(a["id"])["hold"], False)
    on_air["live"] = True
    live._watch_one(creators.get(a["id"]))
    check("...live again: auto-record records as usual", [x[0] for x in started], [a["id"]])

    # ---- the Stop button sets the hold
    from fastapi.testclient import TestClient  # noqa: E402
    from studio import server  # noqa: E402

    class FakeSession:
        def __init__(self, cid):
            self.job, self.stopped = {"creator": cid}, False

        def stop(self):
            self.stopped = True

    fs = FakeSession(a["id"])
    live.mine = lambda jid: fs
    web = TestClient(server.app, base_url="http://127.0.0.1:8765")
    r = web.post("/api/live/j1/stop", headers={"Origin": "http://127.0.0.1:8765"})
    check("pressing Stop: the recording stops and stays stopped for this stream", (r.status_code, fs.stopped, creators.get(a["id"])["hold"]),
          (200, True, True))

# ---- opening the app again
check("closing the app means stop: recordings don't resume when it opens", live._should_resume(), False)
(config.DATA_DIR / live.RESUME_MARK).write_text("1")
check("...unless it restarted itself to update", live._should_resume(), True)
check("...and that's once", (live._should_resume(), (config.DATA_DIR / live.RESUME_MARK).exists()), (False, False))
threads = []
selfupdate.threading.Thread = lambda target=None, daemon=None: type("T", (), {"start": lambda self: threads.append(1)})()
selfupdate._quit(75)
check("updating writes the mark that carries recordings on", (config.DATA_DIR / live.RESUME_MARK).exists())
(config.DATA_DIR / live.RESUME_MARK).unlink()

with ctx.as_user(user.id):
    job = jobs.create({"type": "live", "url": "https://www.twitch.tv/auto", "name": "Auto live"}, {}, enqueue=False, creator=a["id"], kind="live")
    job.update(status="done", was_live=True)
    jobs.save(job)
resumed = []
live._resume_recordings = lambda paused: resumed.append(paused)
live.watch_loop = lambda: None
live.threading.Thread = lambda target=None, args=(), daemon=None: type("T", (), {"start": lambda self: target(*args) if target is live._resume_recordings else None})()
live.start()
check("app opened again after being closed mid-recording: nothing restarts", resumed, [])
check("...the recording says it stopped when the app was closed", (jobs._jobs[job["id"]]["stage"], "was_live" in jobs._jobs[job["id"]]),
      ("Recording stopped when ClipKontrast was closed", False))

# ---- once: auto-record turned off where it was on, with a notice
with ctx.as_user(user.id):
    for x in creators.all_creators():
        creators.update(x["id"], {"auto_watch": x["name"] == "Auto"})
mark = config.user_dir(user.id) / "autorecord-v2"
mark.unlink(missing_ok=True)
live._autorecord_once()
with ctx.as_user(user.id):
    check("once: auto-record turned off where Live clipping had turned it on", creators.get(a["id"])["auto_watch"], False)
    n = [x for x in notices.mine()["items"] if "only on where you turn it on" in x["title"]]
    check("...with a notice naming them and saying where to turn it back on", len(n) == 1 and "Auto" in n[0]["body"] and "Setup" in n[0]["body"])
    creators.update(a["id"], {"auto_watch": True})
live._autorecord_once()
with ctx.as_user(user.id):
    check("...and never again: turned back on, it stays on", creators.get(a["id"])["auto_watch"], True)

page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the page says Live clipping records that stream, and where auto-record is", "that stream only" in page and "records their next stream" in page)

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
