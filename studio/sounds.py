"""What can be heard in a video, second by second: laughter, cheering, screaming, and music. Free, on this computer.

A small sound-recognition model (CED mini, trained on Google's AudioSet: 527 kinds of sound) runs through
sherpa-onnx, the library ClipKontrast already uses for speech. It is about 10 MB and fast: a 2-second piece takes a
few milliseconds, so an hour of stream is heard in well under a minute.

What it's used for:
- picking moments: real laughter, cheering and screaming are the reactions viral clips are made of, beyond just
  "it got louder" (studio/brain.py, as one more signal);
- the editor's hype curve;
- a warning on a clip with music in the background, which YouTube and Instagram often mute or block.

It is downloaded once, by itself (about 48 MB packed), the first time ClipKontrast runs. Until it's there, or if
anything about it fails, everything works exactly as before without it: it is only ever a bonus."""
import subprocess
import tarfile
import threading
from pathlib import Path

import numpy as np

from . import config

NAME = "sherpa-onnx-ced-mini-audio-tagging-2024-04-19"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/audio-tagging-models/{NAME}.tar.bz2"
DIR = config.MODELS_DIR / "sounds"
MODEL, LABELS = DIR / "model.int8.onnx", DIR / "class_labels_indices.csv"
# The kinds of sound that count, by AudioSet's names
GROUPS = {
    "laugh": ("Laughter", "Belly laugh", "Giggle", "Snicker", "Chuckle, chortle", "Baby laughter"),
    "cheer": ("Cheering", "Applause", "Crowd", "Clapping", "Children shouting"),
    "scream": ("Screaming", "Shout", "Yell", "Battle cry", "Bellow", "Gasp"),
    "music": ("Music",),
}
WIN = 2.0                 # each piece heard is 2 seconds long
NO_WINDOW = 0x08000000 if __import__("os").name == "nt" else 0
_lock = threading.Lock()
_model = {"at": None, "failed": False}
state = {"doing": False, "error": ""}


def ready() -> bool:
    return MODEL.is_file() and LABELS.is_file()


def ensure() -> bool:
    """Download the model once (in the background at start). True when it's there."""
    if ready():
        return True
    if config.env("CLIPKONTRAST_FETCH_MODEL", "1") == "0":
        return False
    from . import fetch_model
    with _lock:
        if ready():
            return True
        state.update(doing=True, error="")
        tmp = config.MODELS_DIR / "sounds-model.tar.bz2"
        part = config.MODELS_DIR / "sounds.part"
        try:
            fetch_model._download(URL, tmp, (0, 100), progress={"percent": 0})
            part.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tmp, "r:bz2") as t:
                for m in t.getmembers():          # just the two files needed, flat, nothing outside the folder
                    base = m.name.rsplit("/", 1)[-1]
                    if m.isfile() and base in (MODEL.name, LABELS.name) and ".." not in m.name.split("/"):
                        f = t.extractfile(m)
                        (part / base).write_bytes(f.read())
            if not ((part / MODEL.name).is_file() and (part / LABELS.name).is_file()):
                raise RuntimeError("The download didn't have the sound model in it.")
            DIR.mkdir(parents=True, exist_ok=True)
            for base in (MODEL.name, LABELS.name):
                (part / base).replace(DIR / base)
            tmp.unlink(missing_ok=True)
            return True
        except Exception as e:  # noqa: BLE001 - only a bonus: tried again next time ClipKontrast starts
            state["error"] = str(e)[:200]
            return False
        finally:
            state["doing"] = False
            for f in part.glob("*") if part.is_dir() else []:
                f.unlink(missing_ok=True)
            if part.is_dir():
                part.rmdir()


def _tagger():
    if _model["at"] is not None or _model["failed"]:
        return _model["at"]
    with _lock:
        if _model["at"] is None and not _model["failed"]:
            try:
                from .transcribe import _sherpa
                so = _sherpa()
                cfg = so.AudioTaggingConfig(model=so.AudioTaggingModelConfig(ced=str(MODEL), num_threads=2, provider="cpu"),
                                            labels=str(LABELS), top_k=40)
                _model["at"] = so.AudioTagging(cfg)
            except Exception as e:  # noqa: BLE001 - a computer where it can't run: everything works without it
                _model["failed"] = True
                state["error"] = str(e)[:200]
    return _model["at"]


def per_second(audio, rate: int = 16000):
    """{"laugh", "cheer", "scream", "music", "react"}: how sure the model is of each, for every second of the audio
    (0..1; "react" is laughter, cheering and screaming together, 0..3). None when the model isn't there or fails."""
    if audio is None or not ready():
        return None
    at = _tagger()
    if at is None:
        return None
    n = int(len(audio) // rate)
    if n < 1:
        return None
    hop = 1 if n <= 3600 else 2           # over an hour: every 2 seconds, so a long VOD stays quick
    want = {name: g for g, names in GROUPS.items() for name in names}
    out = {g: np.zeros(n, dtype=np.float32) for g in GROUPS}
    w = int(WIN * rate)
    try:
        for s in range(0, n, hop):
            a = int(max(0, s + 0.5 - WIN / 2) * rate)
            piece = np.ascontiguousarray(audio[a: a + w], dtype=np.float32)
            if len(piece) < rate // 2:
                continue
            st = at.create_stream()
            st.accept_waveform(rate, piece)
            got = {g: 0.0 for g in GROUPS}
            for ev in at.compute(st):
                g = want.get(ev.name)
                if g:
                    got[g] = max(got[g], float(ev.prob))
            for g, v in got.items():
                out[g][s: s + hop] = v
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)[:200]
        return None
    out["react"] = np.clip(1.3 * out["laugh"] + 1.0 * out["cheer"] + 0.9 * out["scream"], 0, 3).astype(np.float32)
    return out


def of_file(path, start: float = 0.0, length: float = None):
    """per_second for a file (or a part of it), read through ffmpeg. None if it can't be read or heard."""
    if not ready():
        return None
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{start:.2f}"] if start else []) + ["-i", str(path)]
    cmd += (["-t", f"{length:.2f}"] if length else []) + ["-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    x = np.frombuffer(p.stdout[: len(p.stdout) // 4 * 4], dtype=np.float32)
    return per_second(x) if len(x) else None


MUSIC_NOTE = ("There's music in the background of this clip. YouTube and Instagram often mute or block clips with "
              "songs in them: turn the stream's sound down in the editor (Audio), or pick a moment without music.")


def music_share(ev) -> float:
    """How much of a clip has music in it (0..1), from per_second."""
    if not ev or not len(ev["music"]):
        return 0.0
    return float((ev["music"] >= 0.5).mean())


def check_music(path):
    """(share of the clip with music in it, or None if it couldn't be heard; the note to show, or "")."""
    ev = of_file(path)
    if ev is None:
        return None, ""
    share = round(music_share(ev), 2)
    return share, (MUSIC_NOTE if share >= 0.35 else "")
