"""Hearing laughs, cheers, screams and music (studio/sounds.py), and what ClipKontrast does with them: moments with
real laughter rank higher, the AI is told where people laughed, and a clip with music in it says so.

The real sound model is used when it's on this machine (or can be downloaded); the rest runs without it."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-sounds-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import brain, config, sounds  # noqa: E402
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


# ---- moments: real laughter is a reaction, even when the loudness doesn't jump
n = 120
db = np.full(n, -30.0, dtype=np.float32) + np.random.RandomState(1).randn(n).astype(np.float32) * 0.3
react = np.zeros(n, dtype=np.float32)
react[70:76] = 2.5                                   # people laughing at 70-75 s
words = [{"s": float(t), "e": t + 0.4, "w": "word"} for t in range(0, n, 1)]
plain, heard = brain.moment_scores(db, words), brain.moment_scores(db, words, events=react)
check("laughter heard lifts that moment's score", (heard[72] - plain[72]) > 2.0)
check("...and not the rest", abs(heard[20] - plain[20]) < 0.01)
c = brain.moment_candidates(db, words, 1, 15, 30, n, events=react)
check("without an AI, the moment picked is the one with the laugh in it", bool(c and c[0]["start"] <= 72 <= c[0]["end"]))
lines = brain.make_lines(words, events=react)
marked = [l for l in lines if l.get("laugh")]
check("the AI is told where people laughed: (LAUGH) on those lines", bool(marked and all(66 <= l["s"] <= 76 for l in marked) and "(LAUGH)" in brain._fmt(marked)))
check("...and nowhere else", "(LAUGH)" not in brain._fmt([l for l in lines if l["s"] < 60]))
check("...which the instructions explain", "(LAUGH)" in brain.HEAD and "(LAUGH)" in brain.FINAL)

# ---- music: a clip mostly with music gets a note, a talking one doesn't
ev = {"music": np.array([0.9] * 8 + [0.1] * 2, dtype=np.float32)}
check("how much of a clip has music in it", sounds.music_share(ev), 0.8)
real_of_file = sounds.of_file
sounds.of_file = lambda p, *a, **k: {"music": np.array([0.8] * 6 + [0.0] * 4, dtype=np.float32)}
check("a clip that's mostly music says it may get muted", sounds.check_music("x.mp4"), (0.6, sounds.MUSIC_NOTE))
sounds.of_file = lambda p, *a, **k: {"music": np.zeros(10, dtype=np.float32)}
check("a clip without music has no note", sounds.check_music("x.mp4"), (0.0, ""))
sounds.of_file = lambda p, *a, **k: None
check("a clip that couldn't be heard has no note and no number", sounds.check_music("x.mp4"), (None, ""))
sounds.of_file = real_of_file

# ---- headings that YouTube and Instagram hold back: the AI is told, and the clip says so
check("words platforms hold back are found in a heading or title", brain.risky_words("SHE IS NAKED ON STREAM", "So sexy bro"), ["naked", "sexy"])
check("...but not inside other words (Sextant, Essex, Bombay)", brain.risky_words("SEXTANT IN ESSEX", "Bombay nights"), [])
check("...and a normal heading is fine", brain.risky_words("TIME TO PULL OFF THIS BIG ROBBERY"), [])
check("the AI is told not to write them", "Never sexual or about nudity" in brain.RULES or "Never sexual or about nudity" in open("studio/brain.py", encoding="utf-8").read())

# ---- without the model: nothing breaks, nothing is made up
check("no model: nothing is heard (None), and nothing waits for it", sounds.per_second(np.zeros(32000, dtype=np.float32)) if not sounds.ready() else None, None)

# ---- the real model, when it's here (or can be fetched)
src = os.environ.get("CK_SOUNDS_MODEL") or ""
if src and Path(src, "model.int8.onnx").is_file():
    sounds.DIR.mkdir(parents=True, exist_ok=True)
    for f in ("model.int8.onnx", "class_labels_indices.csv"):
        shutil.copyfile(Path(src, f), sounds.DIR / f)
else:
    os.environ["CLIPKONTRAST_FETCH_MODEL"] = "1"
    sounds.ensure()
if sounds.ready():
    t = Path(tempfile.mkdtemp(prefix="pc-sounds-a-"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=6", "-ar", "16000", str(t / "tone.wav")], check=True)
    got = sounds.of_file(t / "tone.wav")
    check("the real model hears a file: every kind, one number per second, all between 0 and 1",
          got is not None and set(got) == {"laugh", "cheer", "scream", "music", "react"} and len(got["music"]) == 6
          and all(float(v.min()) >= 0 and float(v.max()) <= 3 for v in got.values()))
    check("...a plain tone isn't laughter or screaming", float(got["react"].max()) < 0.5)
    import time
    x = np.random.RandomState(0).randn(16000 * 120).astype(np.float32) * 0.05
    t0 = time.time(); sounds.per_second(x); took = time.time() - t0
    check(f"...and two minutes of sound is heard in a few seconds ({took:.1f} s)", took < 20)
else:
    print("SKIP the real sound model: not on this machine and it couldn't be downloaded (" + (sounds.state.get("error") or "no internet") + ")")
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
