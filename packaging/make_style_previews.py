"""Makes the little moving previews of each caption style shown in the app (web/brand/styles/<style>.webm and .jpg),
with the same caption code and fonts the clips use, so a preview is exactly what a clip will look like.

    python packaging/make_style_previews.py

Run it again after adding or changing a style in studio/render.py, and commit what it writes."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from studio import render  # noqa: E402

OUT = ROOT / "web" / "brand" / "styles"
WORDS = ["wait", "what", "bro"]
DUR = 2.2
CAP_Y = 1000
CROP_H = 300                       # the band of the frame around the captions that the preview shows


def words():
    out, t = [], 0.15
    for w in WORDS:
        out.append({"w": w, "s": round(t, 2), "e": round(t + 0.4, 2)})
        t += 0.45
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="ckprev"))
    try:
        shutil.copytree(ROOT / "studio" / "fonts", work / "f")
        for key in render.STYLES:
            ass = render.build_ass(words(), 0, DUR, "", key, ["what"], 300, CAP_Y)
            (work / f"{key}.ass").write_text(ass, encoding="utf-8")
            top = CAP_Y - CROP_H // 2
            vf = (f"[0:v]ass={key}.ass:fontsdir=f,crop=1000:{CROP_H}:40:{top},scale=400:120:flags=lanczos,format=yuv420p[v]")
            bg = "gradients=s=1080x1920:c0=0x3a2a6b:c1=0x0d4a46:c2=0x1e1612:nb_colors=3:speed=0.015:rate=30"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", str(DUR), "-i", bg, "-filter_complex", vf,
                            "-map", "[v]", "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "38", "-row-mt", "1", "-an",
                            str(OUT / f"{key}.webm")], cwd=work, check=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.85", "-i", str(OUT / f"{key}.webm"), "-frames:v", "1",
                            "-q:v", "4", str(OUT / f"{key}.jpg")], check=True)
            print("made", key)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
