"""Speech to text for Hindi and other languages, with Whisper (through faster-whisper), on this computer.

The main speech model (Parakeet, studio/transcribe.py) only understands English. A Hindi stream fed to it comes out
as English-sounding nonsense, so its captions were useless unless YouTube had its own Hindi transcript. Whisper
understands Hindi, Urdu, Bengali, Tamil and the other Indian languages, tells which language is spoken, and gives
the time of every word, which the captions need.

It is installed the first time it is needed, not with the rest of ClipKontrast: it is a large download (the library
about 200 MB, the model about 500 MB), and a person who only clips English streams never needs it. After that it
works offline like the rest.

Captions in Hindi come out of Whisper in Devanagari; studio/roman.py and the AI turn them into Hinglish, as before.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import threading

import numpy as np

from . import config

# The spoken languages a person can pick. "auto" lets Whisper tell (or YouTube, when it knows).
LANGUAGES = {"auto": "Auto-detect", "en": "English", "hi": "Hindi / Hinglish", "ur": "Urdu", "bn": "Bengali",
             "mr": "Marathi", "gu": "Gujarati", "pa": "Punjabi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
             "ml": "Malayalam"}
# What the captions are written in.
CAPTION_LANGS = {"auto": "As spoken (Hinglish)", "en": "Always English"}

PACKAGE = "faster-whisper==1.2.1"
# "small" is quick on an ordinary computer and good at Hindi; "large-v3-turbo" is better and slower.
MODEL = (config.env("CLIPKONTRAST_WHISPER_MODEL") or "small").strip()
ENABLED = config.env("CLIPKONTRAST_WHISPER", "1") != "0"
BEAM = max(1, int(config.env("CLIPKONTRAST_WHISPER_BEAM") or "1"))     # 5 is a little more accurate, about twice as slow
THREADS = int(config.env("CLIPKONTRAST_WHISPER_THREADS") or max(2, (os.cpu_count() or 4) - 2))
MODEL_DIR = config.MODELS_DIR / "whisper"
SR = 16000

_lock = threading.Lock()          # one install and one model load at a time
_run_lock = threading.Lock()      # one transcription at a time: a second copy of the model would double the memory
_model = None


def installed() -> bool:
    try:
        importlib.import_module("faster_whisper")
        return True
    except Exception:  # noqa: BLE001 - not installed, or broken: either way it is not usable
        return False


def install(note=None) -> bool:
    """Install faster-whisper into this ClipKontrast's own Python, once. Returns True when it can be used."""
    if not ENABLED:
        return False
    with _lock:
        if installed():
            return True
        if note:
            note("Installing Hindi and multi-language support (once, about 200 MB)")
        try:
            p = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", PACKAGE],
                               capture_output=True, text=True, timeout=1800)
        except Exception as e:  # noqa: BLE001
            print(f"  Couldn't install Whisper: {e}", flush=True)
            return False
        if p.returncode != 0:
            print(f"  Couldn't install Whisper: {(p.stderr or p.stdout)[-600:]}", flush=True)
            return False
        importlib.invalidate_caches()
        return installed()


def ready(note=None) -> bool:
    """Installed (installing it now if needed)."""
    return ENABLED and (installed() or install(note))


def _get(note=None):
    """The model, loaded once. The first time, it is downloaded into ClipKontrast's models folder."""
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            if note and not any(MODEL_DIR.iterdir()):
                note("Downloading the Hindi speech model (once, about 500 MB)")
            _model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=THREADS,
                                  download_root=str(MODEL_DIR))
        return _model


def _float(audio: np.ndarray) -> np.ndarray:
    return audio.astype(np.float32) / 32768.0 if audio.dtype == np.int16 else audio.astype(np.float32)


def _loudest(audio: np.ndarray, seconds: int = 30) -> np.ndarray:
    """The liveliest stretch of the audio: someone talking, not the silent start of a stream."""
    n = len(audio)
    size = seconds * SR
    if n <= size:
        return audio
    step = SR * 5
    best, at = -1.0, 0
    for a in range(0, n - size, step):
        x = audio[a:a + size:160].astype(np.float32)
        v = float((x * x).mean())
        if v > best:
            best, at = v, a
    return audio[at:at + size]


def detect(audio: np.ndarray, note=None):
    """(language code, how sure from 0 to 1) of the speech in this audio, or None if Whisper can't be used."""
    if not ready(note):
        return None
    m = _get(note)
    with _run_lock:
        _segments, info = m.transcribe(_float(_loudest(audio)), language=None, beam_size=1, vad_filter=True,
                                       without_timestamps=True)
    return (info.language or "en"), float(info.language_probability or 0)


def transcribe(audio: np.ndarray, lang: str = None, on_progress=None, note=None) -> list:
    """[{'w', 's', 'e'}, ...] for the whole audio, like transcribe.transcribe. Raises if Whisper can't be used."""
    if not ready(note):
        raise RuntimeError("Hindi speech support couldn't be installed. Check the internet connection and try again.")
    m = _get(note)
    a = _float(audio)
    dur = max(len(a) / SR, 0.01)
    words = []
    with _run_lock:
        segments, _info = m.transcribe(a, language=lang or None, task="transcribe", beam_size=BEAM,
                                       word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
        for seg in segments:
            for w in seg.words or []:
                text = (w.word or "").strip()
                if text:
                    s = round(float(w.start), 2)
                    words.append({"w": text, "s": s, "e": round(max(float(w.end), s + 0.05), 2)})
            if on_progress:
                on_progress(min(1.0, float(seg.end) / dur))
    return words


def is_english(lang: str) -> bool:
    return (lang or "").lower().startswith("en")
