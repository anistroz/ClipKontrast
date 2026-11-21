"""Clip an exact moment: the start and the end chosen by the clipper (slider or typed), one clip of exactly that part,
quickly: only that part is listened to, nothing is picked by the AI (it only writes the big text and the title), no
chat replay. "Best clips inside it" lets the AI pick from just that stretch, as before.

Runs the whole pipeline on a real video file, with the speech model and the AI replaced."""
import os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-exact-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765")
sys.path.insert(0, ".")
from studio import auth, brain, config, ctx, db, jobs, media, transcribe  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- the settings
check("an exact moment is checked", jobs.clean_options({"range_start": 60, "range_end": 105, "exact": True}),
      {"range_start": 60.0, "range_end": 105.0, "exact": True})
for bad, why in (({"exact": True}, "no part chosen"), ({"range_start": 60, "range_end": 61, "exact": True}, "under 3 seconds"),
                 ({"range_start": 0, "range_end": 400, "exact": True}, "over 3 minutes"), ({"range_start": 10, "range_end": 50, "exact": "yes"}, "not on/off")):
    try:
        jobs.clean_options(bad)
        check(f"refused: {why}", False)
    except ValueError:
        check(f"refused: {why}", True)
check("longer parts are fine without 'exact' (the AI picks inside them)", jobs.clean_options({"range_start": 0, "range_end": 900})["range_end"], 900.0)

# ---- the pipeline
work = Path(tempfile.mkdtemp(prefix="pc-exact-work-"))
src = work / "stream.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223344:size=640x360:rate=15", "-f", "lavfi",
                "-i", "sine=f=300:sample_rate=48000", "-t", "180", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
heard = []


def fake_transcribe(audio, on_progress=None):
    heard.append(len(audio) / 16000)
    return [{"w": w, "s": t + i * 0.4, "e": t + i * 0.4 + 0.3} for t in range(0, int(len(audio) / 16000) - 3, 3)
            for i, w in enumerate("bro what was that.".split())]


transcribe.model_ready = lambda: True
transcribe.transcribe = fake_transcribe
jobs._pick_language = lambda job, o, yt, audio, resuming=False: (job.__setitem__("lang", "en"), ("en", yt))[1]
asked = []


def fake_ask(prompt, schema=None, purpose="", timeout=None):
    asked.append(purpose)
    return ([{"start": 0, "end": 0, "score": 70, "hook": "WHAT WAS THAT", "title": "He did not see it coming", "description": "d",
              "hashtags": ["gta"], "reason": "r", "category": "shock", "highlight_words": []}], "m1", 20)


brain.ask_ai = fake_ask
brain.config.ai_ready = lambda: True
chat = []
media.ChatReplay = lambda *a, **k: chat.append(a)
user = auth.local_user()
with ctx.as_user(user.id):
    job = jobs.create({"type": "file", "path": str(src), "name": "Day 2"},
                      {"range_start": 62, "range_end": 107, "exact": True, "max_clips": 1, "layout": "blur", "zoom": False}, enqueue=False)
    jobs._run_job(job)
c = job["clips"]
check("one clip, of exactly the part chosen", (job["status"], len(c), c and (c[0]["start"], c[0]["end"]), c and c[0]["status"]),
      ("done", 1, (62.0, 107.0), "done"))
check("...only that part was listened to (quick)", heard and max(heard) <= 46)
check("...the AI didn't pick moments, it only wrote the big text and the title", ("Video: finding clips" not in asked and "Video: final pick" not in asked,
                                                                                  c[0]["hook"], c[0]["title"]),
      (True, "WHAT WAS THAT", "He did not see it coming"))
check("...the clip file is there, 45 seconds long", abs(media.probe(Path(job["dir"]) / "clips" / c[0]["file"])["duration"] - 45) < 1.5)
check("...it says so", any("exactly the part you chose" in x for x in job["ai"].get("log", [])))

brain.config.ai_ready = lambda: False
with ctx.as_user(user.id):
    job2 = jobs.create({"type": "file", "path": str(src), "name": "Day 2"},
                       {"range_start": 10, "range_end": 25, "exact": True, "layout": "blur", "zoom": False}, enqueue=False)
    jobs._run_job(job2)
check("no AI: the clip is still made, exactly, just without a title", (job2["status"], [(x["start"], x["end"]) for x in job2["clips"]]),
      ("done", [(10.0, 25.0)]))

page = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
check("the page: an Exact moment button on each video and a callout under them",
      all(x in page for x in ('data-act="moment"', "function momentBtn", "Clip an exact moment", "Know when it happened?")))
check("...sliders for the whole video and a fine-tune one, typed times and second buttons",
      all(x in page for x in ('id="moA"', 'id="moB"', 'id="moFa"', 'id="moFb"', 'id="moSa"', 'id="moSb"', "data-nudge", "function parseTime")))
check("...a YouTube preview that moves only when a slider is let go",
      all(x in page for x in ("youtube-nocookie.com/embed/", 'addEventListener("change", preview)')))
check("...exactly this part, or the best clips inside it", all(x in page for x in ('value="exact"', 'value="best"', "function momentOpts")))
import re as _re, shutil as _sh  # noqa: E402
if _sh.which("node"):
    js = Path(tempfile.mkdtemp(prefix="pc-js-")) / "app.mjs"
    js.write_text(max(_re.findall(r"<script[^>]*>(.*?)</script>", page, _re.S), key=len), encoding="utf-8")
    p = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    check("the page's script has no syntax errors", p.returncode == 0 or p.stderr[-300:], True)
    probe = Path(tempfile.mkdtemp(prefix="pc-js-")) / "t.mjs"
    fn = _re.search(r"function parseTime\(v\) \{.*?\n\}", page, _re.S).group(0)
    probe.write_text(fn + '\nconsole.log(JSON.stringify(["1:02:30","62:30","3750","1h2m30s","992s","bad"].map(parseTime)));', encoding="utf-8")
    out = subprocess.run(["node", str(probe)], capture_output=True, text=True).stdout.strip()
    check("typed times are read every way people write them", out, "[3750,3750,3750,3750,992,null]")

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
