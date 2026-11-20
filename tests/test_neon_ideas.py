"""Three ideas from NeonClipping, made for ClipKontrast:
1. the facecam set by hand (a box drawn on a frame, or a corner chosen before making clips), remembered per streamer;
2. the free AI on this computer (Ollama) when the AI key isn't answering, reading only the best moments, so it's quick;
3. better moments with no AI at all: a raised voice (2-4 kHz) and shouted words, not loudness alone.

Runs against the code directly; Ollama, the AI and rendering are replaced. Nothing outside this machine is contacted."""
import os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-neon-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0",
                  CLIPKONTRAST_PUBLIC_URL="http://127.0.0.1:8765", CLIPKONTRAST_OLLAMA_URL="http://127.0.0.1:9")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import auth, brain, config, ctx, db, jobs, media  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---------------------------------------------------------------- 3. moments without AI
sr = 16000
t = np.arange(sr * 4) / sr
low = (0.3 * np.sin(2 * np.pi * 300 * t) * 32767).astype(np.int16)
high = (0.3 * np.sin(2 * np.pi * 3000 * t) * 32767).astype(np.int16)
v = media.voice_per_second(np.concatenate([low, high]))
check("a raised voice (energy at 2-4 kHz) is told from low game sound", (float(v[:4].max()) < 0.05, float(v[4:].min()) > 0.9), (True, True))

n = 600
db_ = np.full(n, -30.0, dtype=np.float32) + np.random.RandomState(1).normal(0, 0.5, n).astype(np.float32)
db_[100:110] += 6                    # louder for a moment, nothing said
db_[400:410] += 5                    # a bit louder, with shouting and shouted words
voice = np.full(n, 0.05, dtype=np.float32)
voice[400:410] = 0.6
words = [{"w": w, "s": 400 + i * 0.6, "e": 400.5 + i * 0.6} for i, w in enumerate("oh my god bhaago bhaago bhai police aa gayi".split())]
words += [{"w": "talking", "s": float(s), "e": s + 0.5} for s in range(0, n, 7)]
s = brain.moment_scores(db_, words, voice)
check("shouted words and a raised voice beat a moment that is only loud", float(s[400:412].max()) > float(s[100:112].max()))
c = brain.moment_candidates(db_, words, 2, 15, 60, float(n), voice)
check("the best moment found is the shouting one", c[0]["start"] <= 404 <= c[0]["end"])
check("...its hook comes from what was shouted", c[0]["hook"].startswith(("OH MY", "MY GOD", "GOD", "BHAAGO")) or "BHAAGO" in c[0]["hook"])
check("...and moments don't overlap", c[1]["end"] <= c[0]["start"] or c[1]["start"] >= c[0]["end"])
lines_words = words

# no AI key, no Ollama: picked from the sound and the words
brain._LOCAL.update(at=0.0, model=None, models=[])
config.ai_ready = lambda: False
found, info = brain.find_clips(sorted(lines_words, key=lambda w: w["s"]), db_, float(n), max_clips=2, log=lambda m: None, voice=voice)
check("no AI at all: clips are still picked, from the sound and the words", (len(found) >= 1, info["model"], "sound and the words" in info["note"]),
      (True, None, True))
check("...the shouting moment among them", any(f["start"] <= 404 <= f["end"] for f in found))

# ---------------------------------------------------------------- 2. the free AI on this computer
check("Ollama not running: no free AI, quickly", (brain.local_models(fresh=True), brain.local_model()), ([], None))
asked = []


def fake_local(prompt, schema, model, purpose="", timeout=90):
    asked.append(prompt)
    return {"score": 95, "hook": "Police aa gayi", "title": "They called the police", "description": "Chaos.", "hashtags": ["gta6"]}, 120


brain._LOCAL.update(at=9e12, model="llama3.2:3b", models=["llama3.2:3b"])
real_ask_local = brain.ask_local
brain.ask_local = fake_local
found, info = brain.find_clips(sorted(lines_words, key=lambda w: w["s"]), db_, float(n), title="GTA", uploader="X", max_clips=2,
                               log=lambda m: None, voice=voice)
check("AI key not answering, Ollama there: the free AI scores the best moments", (info["model"], "free AI on this computer" in info["note"]),
      ("ollama:llama3.2:3b", True))
check("...it reads only those moments (short, quick), not the whole video", 1 <= len(asked) <= 4 and all(len(p) < 3000 for p in asked))
check("...and its title and hook are used", any(f["title"] == "They called the police" for f in found))
brain.ask_local = real_ask_local
check("answer shapes are turned into plain JSON schema for it",
      brain._json_schema({"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"a": {"type": "INTEGER"}}}}),
      {"type": "array", "items": {"type": "object", "properties": {"a": {"type": "integer"}}}})
brain._LOCAL.update(at=0.0, model=None, models=[])

from fastapi.testclient import TestClient  # noqa: E402
from studio import server  # noqa: E402
web = TestClient(server.app, base_url="http://127.0.0.1:8765")
r = web.get("/api/local-ai").json()
check("Settings can tell Ollama isn't there", (r["running"], r["model"], r["suggested"]), (False, None, "llama3.2:3b"))
check("...and the model can't be fetched without it", web.post("/api/local-ai/pull", headers={"Origin": "http://127.0.0.1:8765"}).status_code, 400)

# ---------------------------------------------------------------- 1. the facecam set by hand
work = Path(tempfile.mkdtemp(prefix="pc-neon-work-"))
src = work / "stream.mp4"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=15", "-f", "lavfi", "-i",
                "sine=f=300:sample_rate=48000", "-t", "30", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)], check=True)
queued = []
jobs._q.put = lambda item, user=None: queued.append(item)
user = auth.local_user()
with ctx.as_user(user.id):
    job = jobs.create({"type": "file", "path": str(src), "name": "s"}, {"layout": "split"}, enqueue=False)
    job.update(source_path=str(src), uploader="Hand Set Channel", status="done",
               clips=[{"id": f"clip0{i}", "start": 2 + i * 8, "end": 9 + i * 8, "status": "done", "layout": "split" if i else "blur",
                       "facecam": [400, 200, 300, 200], "camera": "box"} for i in range(3)])
    jobs.save(job)
    O = {"Origin": "http://127.0.0.1:8765"}
    r = web.get(f"/api/jobs/{job['id']}/clips/clip01/frame")
    check("a frame of the clip's video comes back, to draw on", (r.status_code, r.json()["image"].startswith("data:image/jpeg;base64,")), (200, True))
    check("...with the box in use", [round(v, 3) for v in r.json()["box"]], [round(400 / 1280, 3), round(200 / 720, 3), round(300 / 1280, 3), round(200 / 720, 3)])
    check("a box outside the picture is refused", web.post(f"/api/jobs/{job['id']}/facecam", json={"box": [0.9, 0.9, 0.5, 0.5]}, headers=O).status_code, 400)
    check("...and one that's too small", web.post(f"/api/jobs/{job['id']}/facecam", json={"box": [0.1, 0.1, 0.01, 0.01]}, headers=O).status_code, 400)
    r = web.post(f"/api/jobs/{job['id']}/facecam", json={"box": [0.7, 0.0, 0.3, 0.3], "clip": "clip01"}, headers=O)
    check("set for one clip: only that one is made again", (r.json()["remade"], [q[2] for q in queued]), (1, ["clip01"]))
    c1 = next(c for c in job["clips"] if c["id"] == "clip01")
    check("...with the box drawn, in the video's pixels", (c1["facecam"], c1["camera_from"]), ([896, 0, 384, 216], "manual"))
    queued.clear()
    r = web.post(f"/api/jobs/{job['id']}/facecam", json={"box": [0.7, 0.0, 0.3, 0.3]}, headers=O)
    check("set for the whole video: every clip is made again", r.json()["remade"], 3)
    check("...a clip without a facecam layout is switched to facecam on top", job["clips"][0]["layout"], "split")
    check("...and the place is remembered for this streamer, as set by hand", (jobs._remembered_info(job).get("manual"), jobs._remembered(job)),
          (True, [0.7, 0.0, 0.3, 0.3]))

    # the streamer's next video: the drawn place is used, whatever the search finds, and the clips don't overrule it
    job2 = {"id": "j2", "uploader": "hand set channel", "creator": None, "options": {}, "clips": []}
    jobs._camera = lambda j, c: [10, 10, 200, 150]
    jobs._src_size = lambda j, c: (1280, 720)
    cl = {"id": "x", "layout": "split"}
    jobs._use_camera(job2, cl)
    check("next video: the place set by hand is used, not what the search found", (cl["facecam"], cl["camera_from"]), ([896, 0, 384, 216], "manual"))
    for i in range(3):
        jobs._use_camera(job2, {"id": f"y{i}", "layout": "split"})
    check("...and clips that keep finding another place don't replace it", jobs._remembered(job2), [0.7, 0.0, 0.3, 0.3])
    check("...nor does the end-of-video vote", jobs._agree_cameras(job2, []), 0)

    # "no webcam", set by hand
    queued.clear()
    web.post(f"/api/jobs/{job['id']}/facecam", json={"box": None}, headers=O)
    cl = {"id": "z", "layout": "split"}
    jobs._use_camera(job2, cl)
    check("'no webcam' set by hand: the whole picture, from then on", (cl["camera"], "facecam" in cl), ("none", False))

    # a corner chosen before making clips
    job3 = {"id": "j3", "uploader": "Corner Channel", "creator": None, "options": {"cam_hint": "tr"}, "clips": []}
    jobs._camera = lambda j, c: [100, 400, 300, 200]                   # the search was fooled: bottom left
    cl = {"id": "a", "layout": "split"}
    jobs._use_camera(job3, cl)
    check("a corner chosen: a box found elsewhere is not the webcam; the usual size in that corner is used",
          (cl["facecam"], cl["camera_from"]), (jobs._px(jobs.CAM_PRESETS["tr"], 1280, 720), "chosen"))
    jobs._camera = lambda j, c: [930, 10, 340, 190]                    # found, in that corner
    cl = {"id": "b", "layout": "split"}
    jobs._use_camera(job3, cl)
    check("...a box found in that corner is used as found", cl["facecam"], [930, 10, 340, 190])
    job4 = {"id": "j4", "uploader": "No Cam", "creator": None, "options": {"cam_hint": "none"}, "clips": []}
    cl = {"id": "c", "layout": "split"}
    jobs._use_camera(job4, cl)
    check("'No webcam' chosen: the whole picture", cl["camera"], "none")
    check("the corner is a video setting, checked", (jobs.clean_options({"cam_hint": "tr"}), jobs.clean_options({"cam_hint": "<x>"})),
          ({"cam_hint": "tr"}, {"cam_hint": "auto"}))

print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
