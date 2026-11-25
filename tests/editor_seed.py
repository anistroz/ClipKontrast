"""Seeds a data folder with one finished video and a made clip, for the editor's browser test (tests/editor_ui.cjs).

    python tests/editor_seed.py <source.mp4>     (CLIPKONTRAST_DATA set to the folder; accounts off)

Prints the video's id and the clip's id."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, ".")
from studio import auth, ctx, db, jobs, media  # noqa: E402
db.init()
src = Path(sys.argv[1]).resolve()
u = auth.local_user()
ctx.set_uid(u.id)
meta = media.probe(src)
job = jobs.create({"name": "GTA 6 day one stream"}, {"captions": True}, enqueue=False)
words = [{"s": 4.2 + i * 0.42, "e": 4.55 + i * 0.42, "w": w} for i, w in enumerate(
    ("okay chat uh this is the jonathan edition box um and honestly it is actually crazy bro look at this "
     "what is inside this thing no way bro uh this is insane chat let's go").split())]
job.update(source_path=str(src), duration=meta["duration"], width=meta["width"], height=meta["height"], status="done", stage="Done",
           progress=1.0, title="GTA 6 day one stream",
           clips=[{"id": "clip01", "start": 4.0, "end": 26.0, "hook": "HE OPENED THE JONATHAN BOX", "title": "He opened the Jonathan box",
                   "description": "No way bro #gaming", "style": "hype", "layout": "blur", "status": "queued", "score": 88,
                   "reason": "The streamer's loudest reaction, and chat went off.", "captions": True}])
jobs.save(job)
(Path(job["dir"]) / "words.json").write_text(json.dumps(words), encoding="utf-8")
jobs.render_one(job, job["clips"][0], words)
jobs.save(job)
print(job["id"], job["clips"][0]["id"], job["clips"][0]["status"], job["clips"][0].get("error") or "")
