"""A clip from a long stream (or a live recording) is cut from a piece of the video that starts later than second 0.
The editor's cuts, transitions and sounds are kept in the video's own seconds, so they are moved into the piece's
seconds when the clip is made. Before, on those clips, a part cut in the editor was still in the export (report #200)."""
import os, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-pedit-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
from studio import brain, ctx, db, edit, jobs, render  # noqa: E402
db.init()
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


ed = {"cuts": [[1012.0, 1015.5]], "fx": [{"t": 1015.5, "type": "flash", "d": 0.4, "sound": True}],
      "sfx": [{"t": 1020.0, "kind": "boom", "vol": 0.8}], "punch": [{"t": 1025.0, "z": 1.2, "d": 1.0}], "look": "punchy"}
s = edit.shifted(ed, 1000.0)
check("every time in the edit moves into the piece's seconds", (s["cuts"], s["fx"][0]["t"], s["sfx"][0]["t"], s["punch"][0]["t"], s["look"]),
      ([[12.0, 15.5]], 15.5, 20.0, 25.0, "punchy"))
check("...and the saved edit itself is left as it was", ed["cuts"], [[1012.0, 1015.5]])
check("a clip from the start of a video (nothing to move) keeps its edit", edit.shifted(ed, 0) is ed)
check("the part cut is the part taken out of the piece", edit.keep_from_cuts(s["cuts"], 10.0, 40.0), [(0.0, 2.0), (5.5, 30.0)])

# ---- the clip being made gets the moved edit
with ctx.as_user("u_local"):
    job = jobs.create({"type": "url", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "name": "x"}, {"max_clips": 1}, enqueue=False)
d = Path(job["dir"]); (d / "clips").mkdir(parents=True, exist_ok=True)
piece = d / "clips" / "clip001.src.mp4"; piece.write_bytes(b"x" * 2000)
clip = {"id": "clip001", "start": 1010.0, "end": 1040.0, "src": str(piece), "src_offset": 1000.0, "src_end": 1060.0, "status": "queued",
        "hook": "", "title": "t", "captions": False, "layout": "blur", "edit": ed, "version": 1, "heard": True}
job["clips"] = [clip]
seen = {}
jobs._clip_source = lambda j, c: (piece, {"duration": 60.0, "width": 1280, "height": 720})
brain.can_listen = lambda: False


def fake_render(src, out_dir, name, local, words, w, h, progress=None):
    seen.update(local)
    return {"file": f"{name}.mp4", "cover": f"{name}.jpg", "layout": "blur"}


render.render_clip = fake_render
with ctx.as_user("u_local"):
    jobs._render_one(job, clip, [])
check("a long stream's clip is made with its cut where it was made in the editor",
      (seen.get("start"), seen.get("end"), (seen.get("edit") or {}).get("cuts"), (seen.get("edit") or {}).get("fx", [{}])[0].get("t")),
      (10.0, 40.0, [[12.0, 15.5]], 15.5))
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
