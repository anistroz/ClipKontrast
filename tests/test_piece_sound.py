"""Long streams' clips are cut from pieces fetched one by one. A piece's sound sometimes came broken (bits repeated,
skipped, stuttering) while the picture was fine, so clips had glitchy, repeating audio. Each piece's sound is now
compared with the whole video's sound, and swapped for it when it doesn't match; a good piece is left alone."""
import os, subprocess, sys, tempfile
from pathlib import Path
os.environ.update(CLIPKONTRAST_DATA=tempfile.mkdtemp(prefix="pc-piece-"), DATABASE_URL="", CLIPKONTRAST_ACCOUNTS="0",
                  CLIPKONTRAST_FETCH_MODEL="0", CLIPKONTRAST_WHISPER="0", CLIPKONTRAST_UPDATE_CHECK="0")
sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from studio import media  # noqa: E402
fails = []


def check(n, got, want=True):
    ok = want(got) if callable(want) else got == want
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   got {got!r}")); ok or fails.append(n)


rs = np.random.RandomState(3)
sr = 16000
# a stream's sound: noise whose loudness rises and falls like talking, 10 minutes of it
env = np.repeat(np.abs(rs.randn(600 * 10)) * 0.6 + 0.05, sr // 10)
full = (rs.randn(len(env)) * env * 6000).clip(-32000, 32000).astype(np.int16)
off = 200.0
good = full[int(off * sr): int((off + 60) * sr)].copy()
g = media.audio_glitches(full, good, off)
check("a piece whose sound is the same stretch of the stream: right start, nothing broken", (g["start_ok"], g["bad"] < 0.05), (True, True))

broken = good.copy()
for k in range(12, 58, 6):              # a second repeated every few seconds, as the glitchy clips sounded
    a = k * sr
    broken[a: a + sr] = broken[a - sr: a]
    broken[a + sr: a + 2 * sr] = broken[a - 2 * sr: a - sr]
g = media.audio_glitches(full, broken, off)
check("a piece with bits of its sound repeated is found broken", (g["start_ok"], g["bad"] > 0.2), (True, True))
g = media.audio_glitches(full, good, off + 37)
check("...but a piece matched to the wrong place isn't 'fixed' with the wrong sound", g["start_ok"], False)

# ---- the swap itself: the picture kept, the sound from the whole video's audio file at that time
t = Path(tempfile.mkdtemp(prefix="pc-piece-f-"))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=6", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-shortest", "-c:v", "libx264", "-c:a", "aac", str(t / "piece.mp4")], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=30", "-c:a", "aac", str(t / "audio_src.m4a")], check=True)
check("a broken piece gets the whole video's sound", media.replace_audio(t / "piece.mp4", t / "audio_src.m4a", 10.0))
m = media.probe(t / "piece.mp4")
vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(t / "piece.mp4"), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
check("...with its picture and length kept", (m["width"], round(m["duration"])), (320, 6))
check("...and real sound where there was silence", "mean_volume: -9" not in vol and "mean_volume: -inf" not in vol and "mean_volume:" in vol)
check("a missing audio file leaves the piece as it was", media.replace_audio(t / "piece.mp4", t / "gone.m4a", 1.0), False)
check("...and the piece is still there", (t / "piece.mp4").is_file())
print(f"  {len(fails)} failed" if fails else "  ALL PASSED")
sys.exit(1 if fails else 0)
