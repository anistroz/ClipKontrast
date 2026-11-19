"""The split layout (facecam on top, game below) and the caption styles, rendered for real with ffmpeg.

Runs against the code directly, with its own empty data folder."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
os.environ["CLIPKONTRAST_DATA"] = tempfile.mkdtemp(prefix="pc-layouts-")
sys.path.insert(0, ".")
from studio import render
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


def size_of(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    return tuple(int(x) for x in out.split(",")) if out else None


def pixel(path, x, y):
    """The colour of one pixel of the frame half a second in, as (r, g, b)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(path), "-frames:v", "1",
                          "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return tuple(raw[:3])


work = Path(tempfile.mkdtemp(prefix="pc-layouts-work-"))
try:
    render.install_fonts()
    # a 1280x720 "stream": a blue game with a red webcam box in the top-left corner, and a tone for audio
    src = work / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x2040C0:size=1280x720:rate=25",
                    "-f", "lavfi", "-i", "color=c=0xD02020:size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-filter_complex", "[0:v][1:v]overlay=0:0[v]", "-map", "[v]", "-map", "2:a", "-t", "3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    words = [{"w": w, "s": 0.2 + i * 0.4, "e": 0.55 + i * 0.4} for i, w in enumerate("this is a really big moment".split())]
    face = [0, 0, 320, 180]

    check("the split layout is offered", "split" in render.LAYOUTS)
    check("the split layout looks for the webcam", "split" in render.FACECAM_LAYOUTS)
    f = render._filter("split", 1920, face)
    check("split stacks the webcam over the game", "vstack" in f and "crop=320:180:0:0" in f)
    check("split with no webcam fills the screen instead", "vstack" not in render._filter("split", 1920, None))

    clip = {"start": 0.0, "end": 2.8, "hook": "Big moment", "layout": "split", "facecam": face, "style": "box"}
    out = render.render_clip(src, work / "out", "split", clip, words, 1280, 720)
    mp4 = work / "out" / out["file"]
    check("split clip is made, 1080x1920", (out["layout"], size_of(mp4)), ("split", (1080, 1920)))
    top, bottom = pixel(mp4, 540, 60), pixel(mp4, 60, 1900)
    check("the top of the split clip is the webcam (red)", top[0] > 150 and top[2] < 100, True)
    check("the bottom of the split clip is the game (blue)", bottom[2] > 150 and bottom[0] < 100, True)

    out = render.render_clip(src, work / "out", "nocam", dict(clip, facecam=None), words, 1280, 720)
    check("split with no webcam found still makes a clip, showing the whole picture", (out["layout"], size_of(work / "out" / out["file"])), ("blur", (1080, 1920)))

    for name in render.STYLES:
        ass = render.build_ass(words, 0.0, 2.8, "Hook", name, [], 300, 1380)
        check(f"{name}: captions are written", ass.count("Dialogue:") > 5)
        o = render.render_clip(src, work / "out", f"s_{name}", dict(clip, style=name, layout="blur", facecam=None), words, 1280, 720)
        check(f"{name}: clip renders", size_of(work / "out" / o["file"]), (1080, 1920))

    box = render.build_ass(words, 0.0, 2.8, "", "box", [], 300, 1380)
    check("box: the word being said sits on a yellow box", "\\c&H00E5FF&\\bord0\\p1" in box)
    one = render.build_ass(words, 0.0, 2.8, "", "one", [], 300, 1380)
    check("one word: a single word on screen at a time", all(line.count("\\pos(") == 1 for line in one.splitlines() if ",Cap," in line))
    neon = render.build_ass(words, 0.0, 2.8, "", "neon", [], 300, 1380)
    check("neon: purple outline", "&H00FF3CC8" in neon)
finally:
    shutil.rmtree(work, ignore_errors=True)

if fails:
    print(f"{len(fails)} FAILED"); sys.exit(1)
print("ALL PASSED")
