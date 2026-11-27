"""Following the face (studio/faces.py): a clip filled to the screen keeps the person in it instead of cutting them
off at the side. The camera holds still for small moves, glides for big ones, and stays in the middle without faces.

The real face model is used when it's on this machine (or can be downloaded); the camera maths runs without it."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-faces-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import faces, render  # noqa: E402
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


share = (1080 / 1920) / (16 / 9)                      # how much of a 16:9 picture a 9:16 crop keeps
# ---- the camera
jitter = [(i / 2, 0.5 + (0.02 if i % 2 else -0.02)) for i in range(40)]
keys = faces.camera(jitter, share)
check("a face that only fidgets near the middle: the camera doesn't move", len(keys) == 2 and abs(keys[0][1] - keys[-1][1]) < 1e-3)
walk = [(i / 2, 0.3 if i < 10 else 0.7) for i in range(40)]
keys = faces.camera(walk, share)
xs = [x for _, x in keys]
check("a face that walks across: the camera follows it there", abs(xs[-1] - 0.7) < 0.08 and abs(xs[0] - 0.3) < 0.02)
speeds = [abs(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(keys, keys[1:]) if b[0] > a[0]]
check(f"...gliding, never jumping (at most 0.35 of the width a second: {max(speeds):.2f})", max(speeds) <= 0.351)
check("too few faces to trust: no following (the middle, as before)", faces.camera([(i / 2, None) for i in range(20)] + [(10, 0.8)], share), [])
check("the crop never goes past the edge of the picture", all(share / 2 - 1e-3 <= x <= 1 - share / 2 + 1e-3 for _, x in faces.camera([(i / 2, 0.99) for i in range(10)], share)))
expr = faces.crop_x([(0.0, 0.3), (4.0, 0.7), (8.0, 0.7)])
check("the camera becomes ffmpeg's crop: straight lines between its keys, kept inside the picture",
      expr.startswith("max(0\\,min(iw-ow\\,") and "if(lt(t\\,4.00)" in expr and "0.3000+(0.4000)*(t-0.00)/4.00" in expr)
check("no keys: the middle", faces.crop_x([]), "")

# ---- the real model, on a picture with a face far off to the side
src_model = os.environ.get("CK_FACES_MODEL") or ""
if src_model and Path(src_model).is_file():
    faces.MODEL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_model, faces.MODEL)
else:
    os.environ["CLIPKONTRAST_FETCH_MODEL"] = "1"
    faces.ensure()
if faces.ready():
    work = Path(tempfile.mkdtemp(prefix="pc-faces-v-"))
    from PIL import Image, ImageDraw
    face = Path("web/brand/demo-clean.jpg")              # ClipKontrast's own demo picture: a streamer's face
    ok = face.is_file()
    if ok:
        Image.open(face).convert("RGB").resize((608, 1080)).save(work / "face.png")
    if ok:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(work / "face.png"), "-f", "lavfi", "-i", "sine=f=300:d=8",
                        "-filter_complex", "[0:v]pad=1920:1080:1920-iw:0:color=0x203040,format=yuv420p[v]", "-map", "[v]", "-map", "1:a",
                        "-t", "8", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(work / "src.mp4")], check=True)
        tr = faces.track(work / "src.mp4", 0, 8)
        check("the face is found, far to the right", len(tr) >= 14 and all(x is not None and x > 0.7 for _, x in tr))
        for name, clip in (("plain", {"start": 0, "end": 8, "layout": "crop", "hook": "", "captions": False}),
                           ("cut", {"start": 0, "end": 8, "layout": "crop", "hook": "", "captions": False, "edit": {"cuts": [[2, 4]]}})):
            render.render_clip(work / "src.mp4", work / "out", name, clip, [], 1920, 1080)
            p = subprocess.run(["ffmpeg", "-v", "error", "-ss", "2.5", "-i", str(work / "out" / f"{name}.mp4"), "-frames:v", "1", "-f", "rawvideo",
                                "-pix_fmt", "rgb24", "-"], capture_output=True)
            fs = faces.detect(np.frombuffer(p.stdout, np.uint8).reshape(1920, 1080, 3))
            check(f"the clip filled to the screen keeps the face in the middle ({name}{', with a cut in it' if name == 'cut' else ''})",
                  bool(fs) and 300 < fs[0][1] < 780)
        off = dict(clip, follow=False, edit={})
        render.render_clip(work / "src.mp4", work / "out", "off", off, [], 1920, 1080)
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", "2.5", "-i", str(work / "out" / "off.mp4"), "-frames:v", "1", "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-"], capture_output=True)
        fs = faces.detect(np.frombuffer(p.stdout, np.uint8).reshape(1920, 1080, 3))
        check("...while the middle crop (following off) misses it", not fs or not (300 < fs[0][1] < 780))
    else:
        print("SKIP the clip check: no picture with a face")
else:
    print("SKIP the real face model: not on this machine and it couldn't be downloaded (" + (faces.state.get("error") or "no internet") + ")")
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
